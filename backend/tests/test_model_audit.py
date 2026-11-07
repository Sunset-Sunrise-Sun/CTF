import asyncio

import pytest

from app.models import Challenge, Scope
from app.providers import (
    Message,
    ModelRequest,
    ModelResponse,
    ProviderConfig,
    ProviderError,
    ToolCall,
    proposals,
    recorded_complete,
)
from app.store import Store


class SyntheticProvider:
    config = ProviderConfig(
        provider_id="synthetic",
        adapter="openai-compatible",
        base_url="https://synthetic.invalid",
        model_id="synthetic-model",
        api_key_env="SYNTHETIC_AUDIT_KEY",
    )

    def __init__(self, error=None):
        self.error = error
        self.response = ModelResponse(
            provider_id="synthetic",
            model_id="synthetic-model",
            text="synthetic sensitive response",
        )

    async def complete(self, request):
        if self.error is not None:
            raise self.error
        return self.response


@pytest.mark.parametrize(
    "error,status",
    [
        (None, "success"),
        (ProviderError("rate_limited"), "rate_limited"),
        (RuntimeError("synthetic sensitive error"), "internal_error"),
    ],
)
def test_audit_outcomes(tmp_path, monkeypatch, error, status):
    monkeypatch.setenv("SYNTHETIC_AUDIT_KEY", "synthetic credential sentinel")
    store = Store(tmp_path / "audit.db")
    challenge = Challenge(name="Synthetic audit", category="Misc")
    store.create(challenge)
    provider = SyntheticProvider(error)
    request = ModelRequest(
        messages=[Message(role="user", content="synthetic sensitive request")]
    )
    if error is None:
        result = asyncio.run(
            recorded_complete(provider, request, store, challenge.challenge_id)
        )
        assert result is provider.response
    else:
        with pytest.raises(type(error)) as caught:
            asyncio.run(
                recorded_complete(provider, request, store, challenge.challenge_id)
            )
        assert caught.value is error  # Preserve the original exception instance.
    assert_audit(store, challenge.challenge_id, status)


def assert_audit(store, cid, status):
    events = store.events(cid)
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "model_call" and event.actor == "system"
    assert set(event.payload) == {
        "provider_id",
        "model_id",
        "requested_at",
        "response_status",
    }
    assert event.payload["provider_id"] == "synthetic"
    assert event.payload["model_id"] == "synthetic-model"
    assert event.payload["requested_at"].endswith("+00:00")
    assert event.payload["response_status"] == status
    assert "sensitive" not in event.model_dump_json()
    assert "credential sentinel" not in event.model_dump_json()
    assert store.verify(cid)["valid"]


def test_task_cancellation_audited_once(tmp_path):
    store = Store(tmp_path / "cancel.db")
    challenge = Challenge(name="Synthetic cancellation", category="Misc")
    store.create(challenge)

    async def run():
        entered = asyncio.Event()
        captured = []

        class BlockingProvider(SyntheticProvider):
            async def complete(self, request):
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError as error:
                    captured.append(error)
                    raise

        task = asyncio.create_task(
            recorded_complete(
                BlockingProvider(),
                ModelRequest(messages=[]),
                store,
                challenge.challenge_id,
            )
        )
        await entered.wait()
        task.cancel("synthetic cancellation")
        with pytest.raises(asyncio.CancelledError) as caught:
            await task
        assert task.cancelled()
        assert caught.value is captured[0]

    asyncio.run(run())
    assert_audit(store, challenge.challenge_id, "cancelled")


def test_tool_call_provenance_roundtrip():
    response = ModelResponse(
        provider_id="synthetic",
        model_id="synthetic-model",
        text="",
        tool_calls=[
            ToolCall(
                call_id="synthetic-call-A", name="metadata", arguments={"path": "a"}
            ),
            ToolCall(
                call_id="synthetic-call-B", name="metadata", arguments={"path": "b"}
            ),
        ],
    )
    converted = proposals(response, "synthetic-challenge", Scope())
    assert [p.call_id for p in converted] == ["synthetic-call-A", "synthetic-call-B"]
    assert converted[0].proposal_id != converted[1].proposal_id
    for original, proposal in zip(response.tool_calls, converted):
        restored = type(proposal).model_validate_json(proposal.model_dump_json())
        assert restored.call_id == original.call_id
        assert restored.tool_name == original.name
        assert restored.arguments == original.arguments
