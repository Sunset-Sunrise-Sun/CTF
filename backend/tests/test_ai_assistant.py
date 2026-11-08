from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from app.ai_assistant import redact_sensitive, collect_challenge_context
from app.providers import DeepSeekAdapter, ProviderConfig
from app.models import Challenge


def test_ai_chat_requires_explicit_consent_and_server_opt_in(tmp_path, monkeypatch):
    monkeypatch.delenv("CTF_MODEL_NETWORK_ENABLED", raising=False)
    with TestClient(create_app(tmp_path / "data")) as client:
        challenge = client.post(
            "/api/challenges",
            json={"name": "Synthetic Web", "category": "Web", "ai_usage_level": "A2"},
        ).json()
        cid = challenge["challenge_id"]
        no_consent = client.post(
            f"/api/challenges/{cid}/ai/chat",
            json={"question": "Analyze this", "confirm_external_processing": False},
        )
        assert no_consent.status_code == 400
        consent_but_disabled = client.post(
            f"/api/challenges/{cid}/ai/chat",
            json={"question": "Analyze this", "confirm_external_processing": True},
        )
        assert consent_but_disabled.status_code == 503
        assert client.get("/api/health").json()["model_network_enabled"] is False


def test_ai_chat_calls_provider_and_records_unverified_suggestion(tmp_path, monkeypatch):
    monkeypatch.setenv("CTF_MODEL_NETWORK_ENABLED", "true")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-test-key")
    captured = {}

    def handler(request):
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = request.read().decode("utf-8")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "建议先检查输入点。"}}]},
        )

    config = ProviderConfig(
        provider_id="deepseek",
        adapter="deepseek",
        base_url="https://api.deepseek.com",
        model_id="deepseek-chat",
        api_key_env="DEEPSEEK_API_KEY",
    )
    monkeypatch.setattr(
        "app.ai_assistant.build_deepseek_provider",
        lambda: DeepSeekAdapter(config, httpx.MockTransport(handler)),
    )
    with TestClient(create_app(tmp_path / "data")) as client:
        challenge = client.post(
            "/api/challenges",
            json={"name": "Synthetic Web", "category": "Web", "ai_usage_level": "A2"},
        ).json()
        cid = challenge["challenge_id"]
        response = client.post(
            f"/api/challenges/{cid}/ai/chat",
            json={
                "question": "Explain the synthetic challenge",
                "confirm_external_processing": True,
            },
        )
        assert response.status_code == 201
        result = response.json()
        assert result["verification_status"] == "unverified_suggestion"
        assert result["included_files"] == []
        assert captured["authorization"] == "Bearer synthetic-test-key"
        assert "Synthetic Web" in captured["body"]
        assert "Explain the synthetic challenge" in captured["body"]
        assert "source/sink" in captured["body"]
        events = client.get("/api/challenges/" + cid + "/events").json()
        assert [event["event_type"] for event in events[-2:]] == [
            "model_call", "agent_message"
        ]
        assert events[-1]["payload"]["question"] == "Explain the synthetic challenge"
        assert events[-1]["payload"]["execution_performed"] is False


def test_ai_chat_blocks_unknown_and_a0(tmp_path, monkeypatch):
    monkeypatch.setenv("CTF_MODEL_NETWORK_ENABLED", "true")
    with TestClient(create_app(tmp_path / "data")) as client:
        for level in ("unknown", "A0"):
            challenge = client.post(
                "/api/challenges",
                json={"name": "Synthetic", "category": "Misc", "ai_usage_level": level},
            ).json()
            response = client.post(
                f"/api/challenges/{challenge['challenge_id']}/ai/chat",
                json={"question": "Analyze", "confirm_external_processing": True},
            )
            assert response.status_code == 403


def test_secret_redaction_covers_prompts_and_context():
    value = "api_key=sk-synthetic-secret Bearer abcdefghijklmnop password: synthetic-pass"
    redacted = redact_sensitive(value)
    assert "sk-synthetic-secret" not in redacted
    assert "abcdefghijklmnop" not in redacted
    assert "synthetic-pass" not in redacted


def test_ai_context_includes_verified_standalone_text_evidence(tmp_path):
    with TestClient(create_app(tmp_path / "data")) as client:
        raw = b"synthetic source: print('hello from evidence')"
        challenge = client.post(
            "/api/challenges",
            json={"name": "Synthetic", "category": "Reverse", "ai_usage_level": "A2"},
        ).json()
        cid = challenge["challenge_id"]
        uploaded = client.post(
            f"/api/challenges/{cid}/artifacts",
            files={"file": ("notes.txt", raw, "text/plain")},
        )
        assert uploaded.status_code == 201
        state = client.app.state
        context, included = collect_challenge_context(
            challenge=Challenge.model_validate(challenge),
            project=None,
            store=state.store,
            workspace_challenge=state.workspace.challenge(cid),
            artifact_store=state.artifacts,
        )
        assert "hello from evidence" in context
        assert included == ["evidence/notes.txt"]
