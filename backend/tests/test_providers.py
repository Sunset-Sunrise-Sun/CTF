import asyncio
import json
import os
import httpx
import pytest
from app.providers import (
    ProviderConfig,
    ProviderRegistry,
    ProviderError,
    ModelRequest,
    Message,
    ToolDefinition,
    Capabilities,
    proposals,
)
from app.models import Scope, ToolApproval
from app.tools import DisabledBroker


def config(adapter="openai-compatible", **kw):
    return ProviderConfig(
        provider_id=adapter,
        adapter=adapter,
        base_url="https://synthetic.invalid/v1",
        model_id="synthetic",
        api_key_env="CTF_TEST_KEY",
        **kw,
    )


def request(**kw):
    return ModelRequest(
        messages=[Message(role="user", content="Synthetic fixture")], **kw
    )


@pytest.mark.parametrize(
    "adapter", ["deepseek", "openai", "openai-compatible", "anthropic"]
)
def test_adapter_contract(adapter, monkeypatch):
    monkeypatch.setenv("CTF_TEST_KEY", "synthetic-test-only")
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "synthetic response",
                            "tool_calls": [
                                {
                                    "id": "call1",
                                    "function": {
                                        "name": "metadata",
                                        "arguments": '{"path":"sample"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )
    )
    registry = ProviderRegistry([config(adapter)], adapter)
    provider = registry.get(transport)
    if adapter == "anthropic":
        with pytest.raises(ProviderError, match="adapter_not_implemented"):
            asyncio.run(provider.complete(request()))
        return
    response = asyncio.run(provider.complete(request()))
    assert response.provider_id == adapter
    proposal = proposals(response, "synthetic", Scope())[0]
    assert proposal.tool_name == "metadata"
    with pytest.raises(PermissionError):
        asyncio.run(
            DisabledBroker().execute(
                proposal,
                ToolApproval(
                    proposal_id=proposal.proposal_id,
                    approving_user="synthetic",
                    approved=False,
                ),
            )
        )
    with pytest.raises(PermissionError, match="No tools"):
        asyncio.run(
            DisabledBroker().execute(
                proposal,
                ToolApproval(
                    proposal_id=proposal.proposal_id,
                    approving_user="synthetic",
                    approved=True,
                ),
            )
        )


def test_capabilities_and_switch():
    registry = ProviderRegistry([config(), config("openai")], "openai")
    registry.select("openai-compatible")
    provider = registry.get()
    req = request(
        tools=[ToolDefinition(name="metadata", description="synthetic", parameters={})],
        output_schema={},
    )
    with pytest.raises(ProviderError, match="unsupported_capability"):
        provider.prepare(req)
    req.allow_degrade = True
    body, missing = provider.prepare(req)
    assert missing == ["tool_calling", "structured_output"] and "tools" not in body
    with pytest.raises(ValueError):
        registry.select("missing")


@pytest.mark.parametrize(
    "status,code",
    [(429, "rate_limited"), (401, "authentication"), (500, "upstream_error")],
)
def test_errors(status, code, monkeypatch):
    monkeypatch.setenv("CTF_TEST_KEY", "synthetic-test-only")
    provider = ProviderRegistry([config()], "openai-compatible").get(
        httpx.MockTransport(
            lambda r: httpx.Response(
                status, json={"secret": "must not appear"}, headers={"retry-after": "1"}
            )
        )
    )
    with pytest.raises(ProviderError, match=code) as error:
        asyncio.run(provider.complete(request()))
    assert "must not appear" not in str(error.value)


def test_timeout(monkeypatch):
    monkeypatch.setenv("CTF_TEST_KEY", "synthetic-test-only")

    def fail(req):
        raise httpx.ReadTimeout("sensitive upstream body")

    provider = ProviderRegistry([config()], "openai-compatible").get(
        httpx.MockTransport(fail)
    )
    with pytest.raises(ProviderError, match="timeout"):
        asyncio.run(provider.complete(request()))


def test_stream(monkeypatch):
    monkeypatch.setenv("CTF_TEST_KEY", "synthetic-test-only")
    chunks = [
        {"choices": [{"delta": {"content": "syn"}}]},
        {"choices": [{"delta": {"content": "thetic"}}]},
    ]
    data = (
        "".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n"
    )
    provider = ProviderRegistry(
        [config(capabilities=Capabilities(streaming=True))], "openai-compatible"
    ).get(httpx.MockTransport(lambda r: httpx.Response(200, text=data)))

    async def run():
        return [chunk async for chunk in provider.stream(request())]

    results = asyncio.run(run())
    assert results[-1].response.text == "synthetic"


@pytest.mark.skipif(
    os.getenv("CTF_RUN_LIVE_MODEL") != "1",
    reason="Requires explicit opt-in and legal provider credentials",
)
def test_live_provider():
    cfg = ProviderConfig.model_validate_json(os.environ["CTF_LIVE_PROVIDER_CONFIG"])
    provider = ProviderRegistry([cfg], cfg.provider_id).get()
    assert asyncio.run(provider.complete(request())).text
