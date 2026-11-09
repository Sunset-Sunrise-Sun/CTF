"""Unified model-call audit tests (single independent journal).

These tests replace the retired DeepSeek `Store.model_calls` tests; the only
audit source is now `ModelCallJournal` in model-audit.sqlite3.
"""

import asyncio
import json

import pytest

from app.model_calls import ModelCallJournal, ModelCallRecord, audited_complete
from app.models import Challenge, now
from app.providers import (
    Message,
    ModelRequest,
    ModelResponse,
    ProviderConfig,
    ProviderError,
)
from app.store import Store


def config() -> ProviderConfig:
    return ProviderConfig(
        provider_id="synthetic",
        adapter="openai-compatible",
        base_url="https://synthetic.invalid",
        model_id="synthetic-model",
        api_key_env="SYNTHETIC_AUDIT_KEY",
    )


class SyntheticProvider:
    def __init__(self, error=None):
        self.config = config()
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


def make_store(tmp_path):
    store = Store(tmp_path / "audit.db")
    challenge = Challenge(name="Synthetic audit", category="Misc")
    store.create(challenge)
    return store, challenge


@pytest.fixture(autouse=True)
def network_enabled(monkeypatch):
    monkeypatch.setenv("CTF_MODEL_NETWORK_ENABLED", "true")
    monkeypatch.setenv("SYNTHETIC_AUDIT_KEY", "synthetic credential sentinel")


def test_audited_success_writes_start_finish_and_event(tmp_path):
    store, challenge = make_store(tmp_path)
    journal = ModelCallJournal(tmp_path / "model-audit.sqlite3")
    provider = SyntheticProvider()
    request = ModelRequest(
        messages=[Message(role="user", content="synthetic sensitive request")]
    )
    response = asyncio.run(
        audited_complete(
            provider,
            request,
            journal,
            challenge_id=challenge.challenge_id,
            store=store,
            purpose="challenge_chat",
            synthetic=False,
            data_scope="A2:text_only",
        )
    )
    assert response.audit_call_id
    records = journal.records(challenge.challenge_id)
    assert len(records) == 1
    record = records[0]
    assert record.call_id == response.audit_call_id
    assert record.response_status == "success"
    assert record.completed_at
    assert "synthetic sensitive request" not in json.dumps(record.model_dump())
    events = store.events(challenge.challenge_id)
    assert [event.event_type for event in events] == ["model_call"]
    assert events[0].payload["call_id"] == response.audit_call_id
    assert events[0].payload["response_status"] == "success"
    assert store.verify(challenge.challenge_id)["valid"]


@pytest.mark.parametrize(
    "error,status",
    [
        (ProviderError("rate_limited"), "rate_limited"),
        (ProviderError("timeout"), "timeout"),
    ],
)
def test_audited_provider_error_is_terminal_and_evented(tmp_path, error, status):
    store, challenge = make_store(tmp_path)
    journal = ModelCallJournal(tmp_path / "model-audit.sqlite3")
    provider = SyntheticProvider(error)
    with pytest.raises(ProviderError) as caught:
        asyncio.run(
            audited_complete(
                provider,
                ModelRequest(messages=[Message(role="user", content="synthetic")]),
                journal,
                challenge_id=challenge.challenge_id,
                store=store,
                purpose="challenge_chat",
                synthetic=False,
            )
        )
    assert caught.value is error
    records = journal.records(challenge.challenge_id)
    assert records[0].response_status == status
    assert records[0].completed_at is not None
    event = store.events(challenge.challenge_id)[0]
    assert event.payload["call_id"] == records[0].call_id
    assert event.payload["response_status"] == status


def test_audited_cancellation_is_durable(tmp_path, monkeypatch):
    store, challenge = make_store(tmp_path)
    journal = ModelCallJournal(tmp_path / "model-audit.sqlite3")

    async def run():
        entered = asyncio.Event()

        class BlockingProvider(SyntheticProvider):
            async def complete(self, request):
                entered.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(
            audited_complete(
                BlockingProvider(),
                ModelRequest(messages=[]),
                journal,
                challenge_id=challenge.challenge_id,
                store=store,
                purpose="challenge_chat",
                synthetic=False,
            )
        )
        await entered.wait()
        task.cancel("synthetic cancellation")
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    records = journal.records(challenge.challenge_id)
    assert records[0].response_status == "cancelled"
    assert records[0].completed_at is not None
    assert store.events(challenge.challenge_id)[0].payload["response_status"] == "cancelled"


def test_unmatched_start_projects_unknown_without_replay(tmp_path):
    journal = ModelCallJournal(tmp_path / "model-audit.sqlite3")
    record = ModelCallRecord(
        call_id="synthetic-unmatched",
        challenge_id=None,
        provider_id="synthetic",
        model_id="synthetic-model",
        purpose="synthetic_connectivity",
        synthetic=True,
        data_scope="synthetic_only",
        requested_at=now(),
    )
    journal.start(record)
    records = journal.records()
    assert len(records) == 1
    assert records[0].response_status == "unknown"
    assert records[0].completed_at is None
    # Reading never closes or replays the call.
    assert journal.records()[0].response_status == "unknown"


def test_ledger_tables_are_append_only(tmp_path):
    journal = ModelCallJournal(tmp_path / "model-audit.sqlite3")
    record = ModelCallRecord(
        call_id="synthetic-append-only",
        challenge_id=None,
        provider_id="synthetic",
        model_id="synthetic-model",
        purpose="synthetic_connectivity",
        synthetic=True,
        data_scope="synthetic_only",
        requested_at=now(),
    )
    journal.start(record)
    with pytest.raises(ProviderError, match="audit_unavailable"):
        with journal.connect() as db:
            db.execute("UPDATE call_starts SET body='tampered'")
    with pytest.raises(ProviderError, match="audit_unavailable"):
        with journal.connect() as db:
            db.execute("DELETE FROM call_starts")
