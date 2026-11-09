"""Model service settings, DPAPI key storage and network-switch tests.

No real API key or network request is used: the provider is replaced by a local
httpx MockTransport.  The synthetic key is only used to prove it is stored
encrypted and never returned.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app.ai_assistant as ai_assistant
import app.model_service as model_service
from app.main import create_app
from app.providers import DeepSeekAdapter, Message, ModelRequest, ProviderConfig

KEY = "synthetic-deepseek-key-1234567890"
BASE = "https://synthetic.invalid"
MODEL = "synthetic-model"


def provider_config() -> ProviderConfig:
    return ProviderConfig(
        provider_id="deepseek",
        adapter="deepseek",
        base_url=BASE,
        model_id=MODEL,
        api_key_env="SYNTHETIC_P1_KEY",
    )


def install_mock_provider(monkeypatch, answer="synthetic answer", status=200):
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            {
                "url": str(request.url),
                "authorization": request.headers.get("authorization", ""),
                "body": json.loads(request.content.decode("utf-8")),
            }
        )
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "synthetic failure"}})
        return httpx.Response(
            200, json={"choices": [{"message": {"content": answer}}]}
        )

    monkeypatch.setattr(
        ai_assistant,
        "build_deepseek_provider",
        lambda settings=None: DeepSeekAdapter(
            provider_config(), httpx.MockTransport(handler), api_key=KEY
        ),
    )
    return calls


def client_for(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "data"))


def save_settings(client: TestClient, **overrides):
    payload = {
        "base_url": BASE,
        "model_id": MODEL,
        "api_key": KEY,
    }
    payload.update(overrides)
    return client.put("/api/model/settings", json=payload)


def create_challenge(client: TestClient, level="A2") -> str:
    response = client.post(
        "/api/challenges",
        json={"name": "Synthetic settings", "category": "Misc", "ai_usage_level": level},
    )
    assert response.status_code == 201, response.text
    return response.json()["challenge_id"]


def chat(client: TestClient, cid: str):
    return client.post(
        f"/api/challenges/{cid}/ai/chat",
        json={
            "question": "synthetic question",
            "confirm_external_processing": True,
            "consent_challenge_id": cid,
        },
    )


def test_initial_state_has_no_key_and_network_off(tmp_path, monkeypatch):
    monkeypatch.delenv("CTF_MODEL_NETWORK_ENABLED", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with client_for(tmp_path) as client:
        response = client.get("/api/model/settings")
        assert response.status_code == 200
        body = response.json()
        assert body["provider"] == "deepseek"
        assert body["base_url"] == model_service.DEFAULT_BASE_URL
        assert body["model_id"] == "deepseek-flash"
        assert body["model_name"] == "DeepSeek-V4.1-Flash"
        assert body["default_model_id"] == "deepseek-flash"
        assert body["default_model_name"] == "DeepSeek-V4.1-Flash"
        assert body["key_configured"] is False
        assert body["key_source"] is None
        assert body["network_enabled"] is False
        assert body["network_setting"] is False
        assert body["network_env_override"] is False
        assert KEY not in response.text


def test_public_v4_1_flash_name_maps_to_official_api_id(tmp_path, monkeypatch):
    monkeypatch.delenv("CTF_MODEL_NETWORK_ENABLED", raising=False)
    with client_for(tmp_path) as client:
        saved = save_settings(client, model_id="DeepSeek-V4.1-Flash")
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["model_id"] == "deepseek-flash"
        assert body["model_name"] == "DeepSeek-V4.1-Flash"
        assert body["default_model_id"] == "deepseek-flash"
        assert body["default_model_name"] == "DeepSeek-V4.1-Flash"
        # The persisted and Provider-facing id must be the official API id.
        config = json.loads(
            (tmp_path / "data" / model_service.CONFIG_FILENAME).read_text(
                encoding="utf-8"
            )
        )
        assert config["model_id"] == "deepseek-flash"
        assert client.app.state.model_settings.provider_values()[1] == "deepseek-flash"

        pro = save_settings(client, model_id="DeepSeek-V4-Pro")
        assert pro.status_code == 200, pro.text
        assert pro.json()["model_id"] == "deepseek-v4-pro"
        assert pro.json()["model_name"] == "DeepSeek-V4-Pro"


def test_public_v4_1_flash_name_is_sent_to_provider_as_official_id(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("CTF_MODEL_NETWORK_ENABLED", raising=False)
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    with client_for(tmp_path) as client:
        assert save_settings(client, model_id="DeepSeek-V4.1-Flash").status_code == 200
        settings = client.app.state.model_settings
        base_url, model_id, key, _env_name = settings.provider_values()
        adapter = DeepSeekAdapter(
            ProviderConfig(
                provider_id="deepseek",
                adapter="deepseek",
                base_url=base_url,
                model_id=model_id,
                api_key_env="SYNTHETIC_P1_KEY",
            ),
            httpx.MockTransport(handler),
            api_key=key,
        )
        response = asyncio.run(
            adapter.complete(
                ModelRequest(
                    messages=[
                        Message(
                            role="user",
                            content="Reply with exactly: CTF_AGENT_SYNTHETIC_OK",
                        )
                    ]
                )
            )
        )
    assert response.text == "OK"
    assert calls[0]["model"] == "deepseek-flash"


@pytest.mark.parametrize(
    ("input_model", "expected_api_id"),
    [
        ("DeepSeek-V4.1-Flash", "deepseek-flash"),
        ("deepseek-flash", "deepseek-flash"),
        ("deepseek-chat", "deepseek-chat"),
        ("custom-model-v1", "custom-model-v1"),
        ("", "deepseek-flash"),
    ],
)
def test_environment_model_name_is_resolved_for_provider_request(
    monkeypatch, input_model, expected_api_id
):
    monkeypatch.setenv("CTF_MODEL_ID", input_model)
    monkeypatch.setenv("DEEPSEEK_API_KEY", KEY)
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    adapter = ai_assistant.build_deepseek_provider()
    adapter.transport = httpx.MockTransport(handler)
    response = asyncio.run(
        adapter.complete(
            ModelRequest(
                messages=[
                    Message(
                        role="user",
                        content="Reply with exactly: CTF_AGENT_SYNTHETIC_OK",
                    )
                ]
            )
        )
    )
    assert response.text == "OK"
    assert adapter.config.model_id == expected_api_id
    assert calls[0]["model"] == expected_api_id


def test_saved_settings_take_priority_over_environment_model(tmp_path, monkeypatch):
    monkeypatch.delenv("CTF_MODEL_NETWORK_ENABLED", raising=False)
    monkeypatch.setenv("CTF_MODEL_ID", "DeepSeek-V4-Pro")
    with client_for(tmp_path) as client:
        assert save_settings(client, model_id="deepseek-chat").status_code == 200
        settings = client.app.state.model_settings
        provider = ai_assistant.build_provider_for_settings(settings)
        assert provider.config.model_id == "deepseek-chat"
        assert settings.provider_values()[1] == provider.config.model_id


def test_blank_model_save_uses_default(tmp_path, monkeypatch):
    monkeypatch.delenv("CTF_MODEL_NETWORK_ENABLED", raising=False)
    with client_for(tmp_path) as client:
        saved = save_settings(client, model_id="")
        assert saved.status_code == 200, saved.text
        assert saved.json()["model_id"] == "deepseek-flash"
        assert saved.json()["model_name"] == "DeepSeek-V4.1-Flash"


def test_save_key_is_encrypted_and_only_masked_status_returned(tmp_path, monkeypatch):
    monkeypatch.delenv("CTF_MODEL_NETWORK_ENABLED", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with client_for(tmp_path) as client:
        response = save_settings(client)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["key_configured"] is True
        assert body["key_source"] == "settings"
        assert body["network_enabled"] is False
        assert body["network_setting"] is False
        assert KEY not in response.text
        assert "api_key" not in response.text.lower()

        data_root = client.app.state.model_settings.root
        config_text = (data_root / model_service.CONFIG_FILENAME).read_text(
            encoding="utf-8"
        )
        assert KEY not in config_text
        assert (data_root / model_service.SECRET_FILENAME).exists()
        assert KEY.encode("utf-8") not in (
            data_root / model_service.SECRET_FILENAME
        ).read_bytes()

        status = client.get("/api/model/status")
        assert status.json()["credentials_configured"] is True
        assert status.json()["key_source"] == "settings"
        assert KEY not in status.text


def test_refresh_recovers_settings_from_disk(tmp_path, monkeypatch):
    monkeypatch.delenv("CTF_MODEL_NETWORK_ENABLED", raising=False)
    with client_for(tmp_path) as client:
        assert save_settings(client).status_code == 200
        assert client.put(
            "/api/model/network", json={"network_enabled": True}
        ).status_code == 200
    with client_for(tmp_path) as client:
        body = client.get("/api/model/settings").json()
        assert body["base_url"] == BASE
        assert body["model_id"] == MODEL
        assert body["key_configured"] is True
        assert body["key_source"] == "settings"
        assert body["network_enabled"] is True
        assert body["network_setting"] is True


def test_saving_key_does_not_enable_network_and_ai_stays_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv("CTF_MODEL_NETWORK_ENABLED", raising=False)
    calls = install_mock_provider(monkeypatch)
    with client_for(tmp_path) as client:
        assert save_settings(client).status_code == 200
        cid = create_challenge(client, "A2")
        denied = chat(client, cid)
        assert denied.status_code == 503
        assert denied.json()["detail"]["code"] == "model_network_disabled"
        assert calls == []

        enabled = client.put("/api/model/network", json={"network_enabled": True})
        assert enabled.status_code == 200
        assert enabled.json()["network_enabled"] is True
        assert KEY not in enabled.text
        allowed = chat(client, cid)
        assert allowed.status_code == 201, allowed.text
        assert len(calls) == 1
        assert calls[0]["body"]["model"] == MODEL
        assert KEY in calls[0]["authorization"]  # sent only in the request header

        events = client.get(f"/api/challenges/{cid}/events")
        assert KEY not in events.text
        preview = client.get(f"/api/challenges/{cid}/writeup/preview")
        assert KEY not in preview.text
        export = client.get(f"/api/challenges/{cid}/export")
        assert export.status_code == 200
        assert KEY not in export.content.decode("utf-8", "ignore")


def test_successful_synthetic_connection_does_not_leak_key(tmp_path, monkeypatch):
    monkeypatch.delenv("CTF_MODEL_NETWORK_ENABLED", raising=False)
    calls = install_mock_provider(monkeypatch)
    with client_for(tmp_path) as client:
        assert save_settings(client).status_code == 200
        assert client.put(
            "/api/model/network", json={"network_enabled": True}
        ).status_code == 200
        response = client.post(
            "/api/model/test", json={"confirm_synthetic_request": True}
        )
        assert response.status_code == 200, response.text
        assert response.json()["sent_synthetic_content_only"] is True
        assert response.json()["call_id"]
        assert KEY not in response.text
        assert len(calls) == 1
        assert "question" not in json.dumps(calls[0]["body"]).lower()
        assert KEY in calls[0]["authorization"]
        # Audit metadata records the provider/model, never the key.
        audit = client.get("/api/model/calls")
        assert audit.status_code == 200
        assert KEY not in audit.text
        assert audit.json()["calls"][0]["purpose"] == "synthetic_connectivity"


def test_wrong_key_connection_failure_does_not_leak_key(tmp_path, monkeypatch):
    monkeypatch.delenv("CTF_MODEL_NETWORK_ENABLED", raising=False)
    install_mock_provider(monkeypatch, status=401)
    with client_for(tmp_path) as client:
        assert save_settings(client).status_code == 200
        assert client.put(
            "/api/model/network", json={"network_enabled": True}
        ).status_code == 200
        response = client.post(
            "/api/model/test", json={"confirm_synthetic_request": True}
        )
        assert response.status_code in {502, 503}
        assert KEY not in response.text
        audit = client.get("/api/model/calls")
        assert audit.status_code == 200
        assert KEY not in audit.text
        assert audit.json()["calls"][0]["response_status"] == "authentication"


def test_network_switch_is_separate_and_persists(tmp_path, monkeypatch):
    monkeypatch.delenv("CTF_MODEL_NETWORK_ENABLED", raising=False)
    with client_for(tmp_path) as client:
        assert client.get("/api/model/settings").json()["network_setting"] is False
        assert client.put(
            "/api/model/network", json={"network_enabled": True}
        ).status_code == 200
        assert client.get("/api/model/settings").json()["network_setting"] is True
        assert save_settings(client).status_code == 200
        assert client.get("/api/model/settings").json()["network_enabled"] is True
        assert client.put(
            "/api/model/network", json={"network_enabled": False}
        ).status_code == 200
        assert client.get("/api/model/settings").json()["network_enabled"] is False


def test_invalid_settings_are_rejected_without_echoing_key(tmp_path, monkeypatch):
    monkeypatch.delenv("CTF_MODEL_NETWORK_ENABLED", raising=False)
    with client_for(tmp_path) as client:
        for payload in (
            {"base_url": "http://public.example", "api_key": KEY},
            {"base_url": "not a url", "api_key": KEY},
            {"base_url": BASE, "model_id": "bad model", "api_key": KEY},
            {"base_url": BASE, "api_key": "short"},
            {"base_url": BASE, "api_key": KEY, "clear_api_key": True},
        ):
            response = client.put("/api/model/settings", json=payload)
            assert response.status_code == 422, response.text
            assert KEY not in response.text
        assert client.get("/api/model/settings").json()["key_configured"] is False


def test_clear_key_is_explicit_and_masked(tmp_path, monkeypatch):
    monkeypatch.delenv("CTF_MODEL_NETWORK_ENABLED", raising=False)
    with client_for(tmp_path) as client:
        assert save_settings(client).status_code == 200
        cleared = client.put(
            "/api/model/settings",
            json={"base_url": BASE, "model_id": MODEL, "clear_api_key": True},
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["key_configured"] is False
        assert KEY not in cleared.text
        assert not (client.app.state.model_settings.secret_path).exists()


def test_settings_do_not_bypass_a0_a1_a2_gates(tmp_path, monkeypatch):
    monkeypatch.delenv("CTF_MODEL_NETWORK_ENABLED", raising=False)
    install_mock_provider(monkeypatch)
    with client_for(tmp_path) as client:
        assert save_settings(client).status_code == 200
        assert client.put(
            "/api/model/network", json={"network_enabled": True}
        ).status_code == 200
        a0 = create_challenge(client, "A0")
        denied = chat(client, a0)
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "ai_usage_not_permitted"

        a1 = create_challenge(client, "A1")
        assert chat(client, a1).status_code == 201
        tool = client.post(
            f"/api/challenges/{a1}/tool-proposals",
            json={
                "tool_name": "list_files",
                "arguments": {"path": "."},
                "reason": "must stay denied",
            },
        )
        assert tool.status_code == 403


def test_settings_failure_does_not_break_manual_tools(tmp_path, monkeypatch):
    monkeypatch.delenv("CTF_MODEL_NETWORK_ENABLED", raising=False)
    with client_for(tmp_path) as client:
        cid = create_challenge(client, "A2")
        root = client.app.state.workspace.challenge(cid)
        (root / "sample.bin").write_bytes(b"\x7fELF" + b"\x00" * 20 + b" TOOL_OK ")
        invalid = client.put(
            "/api/model/settings",
            json={"base_url": "http://public.example", "api_key": KEY},
        )
        assert invalid.status_code == 422
        proposal = client.post(
            f"/api/challenges/{cid}/tool-proposals",
            json={
                "tool_name": "file_inspect",
                "arguments": {"path": "sample.bin"},
                "reason": "settings failure must not affect tools",
            },
        )
        assert proposal.status_code == 201
        pid = proposal.json()["proposal_id"]
        assert client.post(
            f"/api/challenges/{cid}/tool-proposals/{pid}/approve",
            json={"approving_user": "synthetic-user"},
        ).status_code == 200
        executed = client.post(
            f"/api/challenges/{cid}/tool-proposals/{pid}/execute"
        )
        assert executed.status_code == 200
        assert executed.json()["status"] == "succeeded"


def test_settings_are_isolated_per_data_root(tmp_path, monkeypatch):
    monkeypatch.delenv("CTF_MODEL_NETWORK_ENABLED", raising=False)
    with client_for(tmp_path / "a") as first, client_for(tmp_path / "b") as second:
        assert save_settings(first).status_code == 200
        assert first.get("/api/model/settings").json()["key_configured"] is True
        assert second.get("/api/model/settings").json()["key_configured"] is False
        assert KEY not in second.get("/api/model/settings").text


def test_environment_key_custom_address_requires_explicit_backend_authorization(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("CTF_MODEL_NETWORK_ENABLED", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-environment-key-123456")
    with client_for(tmp_path) as client:
        saved = client.put(
            "/api/model/settings",
            json={
                "base_url": "https://trusted.example",
                "model_id": MODEL,
            },
        )
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["key_source"] == "environment"
        assert body["env_key_custom_base_url_authorized"] is False
        assert body["env_key_custom_base_url_authorization_required"] is True
        assert "synthetic-environment-key-123456" not in saved.text

        assert client.put(
            "/api/model/network", json={"network_enabled": True}
        ).status_code == 200
        denied = client.post(
            "/api/model/test", json={"confirm_synthetic_request": True}
        )
        assert denied.status_code == 403, denied.text
        assert (
            denied.json()["detail"]["code"]
            == "env_key_custom_base_url_not_authorized"
        )

        # Changing to another custom URL must not inherit the old permission.
        authorized = client.put(
            "/api/model/settings",
            json={
                "base_url": "https://trusted.example",
                "model_id": MODEL,
                "authorize_env_key_custom_base_url": True,
            },
        )
        assert authorized.status_code == 200, authorized.text
        assert authorized.json()["env_key_custom_base_url_authorized"] is True
        changed = client.put(
            "/api/model/settings",
            json={
                "base_url": "https://other.example",
                "model_id": MODEL,
            },
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["env_key_custom_base_url_authorized"] is False
        assert (
            changed.json()["env_key_custom_base_url_authorization_required"] is True
        )
        assert (
            client.post(
                "/api/model/test", json={"confirm_synthetic_request": True}
            ).status_code
            == 403
        )


def test_default_deepseek_address_with_environment_key_needs_no_extra_authorization(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("CTF_MODEL_NETWORK_ENABLED", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-environment-key-123456")
    with client_for(tmp_path) as client:
        saved = client.put(
            "/api/model/settings",
            json={"base_url": "https://api.deepseek.com", "model_id": MODEL},
        )
        assert saved.status_code == 200
        assert saved.json()["key_source"] == "environment"
        assert saved.json()["env_key_custom_base_url_authorized"] is False
        assert saved.json()["env_key_custom_base_url_authorization_required"] is False
        assert client.app.state.model_settings.provider_values()[2] == (
            "synthetic-environment-key-123456"
        )


def test_corrupt_config_fails_closed_until_user_saves_valid_config(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("CTF_MODEL_NETWORK_ENABLED", raising=False)
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True)
    (data_root / model_service.CONFIG_FILENAME).write_text(
        "{not valid json", encoding="utf-8"
    )
    install_mock_provider(monkeypatch, answer="synthetic recovered answer")
    with client_for(tmp_path) as client:
        status = client.get("/api/model/settings")
        assert status.status_code == 200
        assert status.json()["config_error"] == "invalid_config"

        # Even with the model network env switch enabled, a corrupt config is
        # not used for outbound calls.
        monkeypatch.setenv("CTF_MODEL_NETWORK_ENABLED", "true")
        tested = client.post(
            "/api/model/test", json={"confirm_synthetic_request": True}
        )
        assert tested.status_code == 503
        assert tested.json()["detail"]["code"] == "config_invalid"
        cid = create_challenge(client, "A2")
        chat_denied = chat(client, cid)
        assert chat_denied.status_code == 503
        assert chat_denied.json()["detail"]["code"] == "config_invalid"

        # Saving a valid configuration clears the error and restores calls.
        repaired = save_settings(client)
        assert repaired.status_code == 200, repaired.text
        assert repaired.json()["config_error"] is None
        assert repaired.json()["key_configured"] is True
        assert client.put(
            "/api/model/network", json={"network_enabled": True}
        ).status_code == 200
        tested_again = client.post(
            "/api/model/test", json={"confirm_synthetic_request": True}
        )
        assert tested_again.status_code == 200, tested_again.text
        assert tested_again.json()["sent_synthetic_content_only"] is True


def test_config_write_failure_restores_state_and_keeps_corrupt_error(
    tmp_path, monkeypatch
):
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True)
    config_path = data_root / model_service.CONFIG_FILENAME
    corrupt = "{not valid json"
    config_path.write_text(corrupt, encoding="utf-8")
    install_mock_provider(monkeypatch, answer="synthetic after repair")
    real_atomic_write = model_service._atomic_write

    def fail_config_write(path, data):
        if Path(path).name == model_service.CONFIG_FILENAME:
            raise OSError("injected config write failure")
        return real_atomic_write(path, data)

    with client_for(tmp_path) as client:
        assert client.get("/api/model/settings").json()["config_error"] == "invalid_config"
        monkeypatch.setattr(model_service, "_atomic_write", fail_config_write)
        failed = save_settings(client)
        assert failed.status_code == 500, failed.text
        assert failed.json()["detail"]["code"] == "settings_write_failed"
        settings = client.get("/api/model/settings").json()
        assert settings["config_error"] == "invalid_config"
        assert settings["key_configured"] is False
        assert config_path.read_text(encoding="utf-8") == corrupt
        assert not (data_root / model_service.SECRET_FILENAME).exists()

        # A corrupt config still blocks model calls while the env switch is on.
        monkeypatch.setenv("CTF_MODEL_NETWORK_ENABLED", "true")
        denied = client.post(
            "/api/model/test", json={"confirm_synthetic_request": True}
        )
        assert denied.status_code == 503
        assert denied.json()["detail"]["code"] == "config_invalid"

        # Once disk writes work again, a valid save clears the error and calls
        # become possible.
        monkeypatch.setattr(model_service, "_atomic_write", real_atomic_write)
        repaired = save_settings(client)
        assert repaired.status_code == 200, repaired.text
        assert repaired.json()["config_error"] is None
        assert repaired.json()["key_configured"] is True
        assert client.put(
            "/api/model/network", json={"network_enabled": True}
        ).status_code == 200
        tested = client.post(
            "/api/model/test", json={"confirm_synthetic_request": True}
        )
        assert tested.status_code == 200, tested.text


def test_secret_write_failure_rolls_back_config_and_secret(
    tmp_path, monkeypatch
):
    real_atomic_write = model_service._atomic_write

    def fail_secret_write(path, data):
        if Path(path).name == model_service.SECRET_FILENAME:
            raise OSError("injected secret write failure")
        return real_atomic_write(path, data)

    with client_for(tmp_path) as client:
        monkeypatch.setattr(model_service, "_atomic_write", fail_secret_write)
        failed = save_settings(client)
        assert failed.status_code == 500, failed.text
        assert failed.json()["detail"]["code"] == "settings_write_failed"
        settings = client.get("/api/model/settings").json()
        assert settings["key_configured"] is False
        assert settings["config_error"] is None
        data_root = tmp_path / "data"
        assert not (data_root / model_service.CONFIG_FILENAME).exists()
        assert not (data_root / model_service.SECRET_FILENAME).exists()

        monkeypatch.setattr(model_service, "_atomic_write", real_atomic_write)
        repaired = save_settings(client)
        assert repaired.status_code == 200, repaired.text
        assert repaired.json()["key_configured"] is True


def test_credential_store_unavailable_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("CTF_MODEL_NETWORK_ENABLED", raising=False)
    monkeypatch.setattr(model_service, "_dpapi_available", lambda: False)
    with client_for(tmp_path) as client:
        response = save_settings(client)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "credential_store_unavailable"
        assert KEY not in response.text
        assert client.get("/api/model/settings").json()["key_configured"] is False
        config = client.app.state.model_settings.config_path
        assert not config.exists()
