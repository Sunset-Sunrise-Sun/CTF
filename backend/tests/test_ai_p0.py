"""Safety and disclosure regression coverage through the real HTTP handlers."""

import asyncio
import hashlib
import io
import json
import sqlite3
import subprocess
import sys
import zipfile
from contextlib import closing
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import ai_smoke_cli, model_cli
from app.main import create_app
from app.model_calls import ModelCallJournal, audited_complete
from app.providers import (
    DeepSeekAdapter,
    ModelRequest,
    ModelResponse,
    ProviderConfig,
    ProviderError,
)


CONFIG = ProviderConfig(
    provider_id="deepseek",
    adapter="deepseek",
    model_id="synthetic-model",
    base_url="https://synthetic.invalid",
    api_key_env="SYNTHETIC_P0_TEST_KEY",
)


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("CTF_MODEL_NETWORK_ENABLED", "true")
    monkeypatch.setenv("SYNTHETIC_P0_TEST_KEY", "fixture-credential-not-real")
    calls = []
    replies = []
    with TestClient(create_app(tmp_path / "data")) as client:

        def provider(request):
            # The transport may only be reached after committing a start record.
            journal = client.app.state.model_calls
            assert journal.records()[-1].response_status == "unknown"
            calls.append(json.loads(request.read()))
            return (
                replies.pop(0)
                if replies
                else httpx.Response(
                    200,
                    json={
                        "choices": [
                            {"message": {"content": "Synthetic unverified advice"}}
                        ],
                        "usage": {
                            "prompt_tokens": 10,
                            "completion_tokens": 4,
                            "total_tokens": 14,
                        },
                    },
                )
            )

        monkeypatch.setattr(
            "app.ai_assistant.build_deepseek_provider",
            lambda: DeepSeekAdapter(CONFIG, httpx.MockTransport(provider)),
        )
        yield client, calls, replies


def create(client, level="A2", description="synthetic challenge"):
    response = client.post(
        "/api/challenges",
        json={
            "name": "Synthetic P0",
            "category": "Misc",
            "description": description,
            "ai_usage_level": level,
        },
    )
    assert response.status_code == 201
    return response.json()["challenge_id"]


def chat(client, cid, **fields):
    return client.post(
        f"/api/challenges/{cid}/ai/chat",
        json={
            "question": "Synthetic question",
            "confirm_external_processing": True,
            "consent_challenge_id": cid,
            **fields,
        },
    )


def upload(client, cid, name, data):
    response = client.post(
        f"/api/challenges/{cid}/artifacts",
        files={
            "file": (name, data, "text/plain"),
        },
    )
    assert response.status_code == 201
    artifact = response.json()
    return {k: artifact[k] for k in ("artifact_id", "sha256")}


def test_a1_only_selected_text_and_no_attachment_reads(service):
    client, calls, _ = service
    cid = create(client, "A1", "RULES_OR_DESCRIPTION_AS_DATA")
    artifact = upload(client, cid, "private-notes.txt", b"DO_NOT_SEND_ATTACHMENT")
    denied = chat(client, cid, selected_artifacts=[artifact], confirm_attachments=True)
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "attachments_not_permitted"
    assert calls == []
    assert client.get("/api/model/calls").json() == {"calls": []}
    assert chat(client, cid, selected_texts=["EXPLICIT_TEXT"]).status_code == 201
    sent = json.dumps(calls[0])
    assert "EXPLICIT_TEXT" in sent
    assert "private-notes" not in sent and "DO_NOT_SEND_ATTACHMENT" not in sent
    assert "RULES_OR_DESCRIPTION_AS_DATA" not in calls[0]["messages"][0]["content"]
    assert "tools" not in calls[0]


def test_a2_selection_scope_and_history_do_not_expand(service):
    client, calls, _ = service
    cid, other = create(client), create(client)
    a = upload(client, cid, "only-selected.txt", b"SELECTED_CONTENT")
    upload(client, cid, "unselected.txt", b"UNSELECTED_CONTENT")
    foreign = upload(client, other, "another-challenge.txt", b"FOREIGN_CONTENT")
    assert chat(client, cid, selected_artifacts=[a]).status_code == 400
    assert (
        chat(
            client, cid, selected_artifacts=[foreign], confirm_attachments=True
        ).status_code
        == 409
    )
    assert (
        chat(
            client,
            cid,
            selected_artifacts=[{**a, "sha256": "0" * 64}],
            confirm_attachments=True,
        ).status_code
        == 409
    )
    assert calls == []
    answer = chat(
        client,
        cid,
        question="ATTACHMENT_SCOPE_QUESTION",
        selected_artifacts=[a],
        confirm_attachments=True,
    )
    assert answer.status_code == 201
    assert answer.json()["included_files"] == ["evidence/only-selected.txt"]
    sent = json.dumps(calls[0])
    assert (
        "SELECTED_CONTENT" in sent
        and "UNSELECTED_CONTENT" not in sent
        and "FOREIGN_CONTENT" not in sent
    )
    assert chat(client, cid).status_code == 201
    assert "ATTACHMENT_SCOPE_QUESTION" not in json.dumps(calls[1])
    assert "only-selected.txt" not in json.dumps(calls[1])


def test_import_selection_verifies_hash_and_never_uses_unselected_sibling(service):
    client, calls, _ = service
    cid = create(client)
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("allowed.txt", "SELECTED_IMPORT_MARKER")
        archive.writestr("other.txt", "UNSELECTED_IMPORT_MARKER")
    uploaded = client.post(
        f"/api/challenges/{cid}/imports",
        files={
            "file": ("synthetic.zip", data.getvalue(), "application/zip"),
        },
    )
    assert uploaded.status_code == 201
    import_id = uploaded.json()["import_id"]
    selected = {
        "import_id": import_id,
        "relative_path": "allowed.txt",
        "sha256": hashlib.sha256(b"SELECTED_IMPORT_MARKER").hexdigest(),
    }
    assert (
        chat(
            client, cid, selected_files=[selected], confirm_attachments=True
        ).status_code
        == 201
    )
    sent = json.dumps(calls[0])
    assert "SELECTED_IMPORT_MARKER" in sent and "UNSELECTED_IMPORT_MARKER" not in sent
    workspace = client.app.state.workspace.challenge(cid)
    (workspace / "imports" / import_id / "allowed.txt").write_bytes(b"TAMPERED_FIXTURE")
    assert (
        chat(
            client, cid, selected_files=[selected], confirm_attachments=True
        ).status_code
        == 409
    )
    assert len(calls) == 1


def test_request_budget_and_validation_do_not_echo_input(service):
    client, calls, _ = service
    cid = create(client, "A1")
    assert chat(client, cid, selected_texts=["x" * 30000] * 7).status_code == 413
    error = chat(client, cid, api_key="FIXTURE_SECRET_DO_NOT_ECHO")
    assert error.status_code == 422
    assert "FIXTURE_SECRET_DO_NOT_ECHO" not in error.text
    assert calls == []


def test_http_audit_and_zip_disclose_actual_success_and_failure(service, tmp_path):
    client, calls, replies = service
    cid = create(client)
    route = f"/api/challenges/{cid}"
    preview = client.get(route + "/writeup/preview").json()["markdown"]
    assert "没有模型调用" in preview
    synthetic = client.post("/api/model/test", json={"confirm_synthetic_request": True})
    assert synthetic.status_code == 200
    synthetic_id = synthetic.json()["call_id"]
    success = chat(client, cid)
    assert success.status_code == 201
    success_id = success.json()["call_id"]
    replies.append(httpx.Response(429, text="PRIVATE_UPSTREAM_BODY"))
    failure = chat(client, cid)
    assert (
        failure.status_code == 429
        and failure.json()["detail"]["code"] == "rate_limited"
    )
    records = client.get("/api/model/calls").json()["calls"]
    assert len(records) == len(calls) == 3
    assert records[0]["synthetic"] and records[0]["challenge_id"] is None
    assert records[1]["usage"]["total_tokens"] == 14
    assert records[2]["error_category"] == "rate_limited"
    assert "PRIVATE_UPSTREAM_BODY" not in json.dumps(records)
    assert "fixture-credential-not-real" not in json.dumps(records)
    events = client.get(route + "/events").json()
    assert [e["event_type"] for e in events] == [
        "model_call",
        "agent_message",
        "model_call",
    ]
    assert (
        events[0]["payload"]["call_id"] == events[1]["payload"]["call_id"] == success_id
    )
    human = "# Synthetic human draft\n\nManually authored.\n"
    assert (
        client.put(
            route + "/writeup/draft", json={"content": human, "base_version": 0}
        ).status_code
        == 201
    )
    preview = client.get(route + "/writeup/preview").json()["markdown"]
    exported = client.get(route + "/export")
    assert exported.status_code == 200
    (tmp_path / "verified-synthetic-ai-disclosure.zip").write_bytes(exported.content)
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        assert archive.read("writeup.md") == human.encode()
        assert archive.read("writeup_generated.md") == preview.encode()
        disclosure = archive.read("ai_disclosure.md").decode()
        assert "成功 1，失败 1" in disclosure and "成功 1，失败 1" in preview
        assert "rate_limited" in disclosure and synthetic_id not in disclosure
        manifest = json.loads(archive.read("manifest.json"))
        assert [c["call_id"] for c in manifest["model_calls"]] == [
            success_id,
            records[2]["call_id"],
        ]
        assert manifest["model_calls"][0]["delivery_status"] == "recorded"
        entries = dict(
            line.split("  ", 1)[::-1]
            for line in archive.read("SHA256SUMS").decode().splitlines()
        )
        assert set(entries) == set(archive.namelist()) - {"SHA256SUMS"}
        assert all(
            hashlib.sha256(archive.read(name)).hexdigest() == h
            for name, h in entries.items()
        )


def test_audit_storage_failure_blocks_send_or_marks_unresolved(service, monkeypatch):
    client, calls, _ = service
    cid = create(client)
    journal = client.app.state.model_calls

    def unavailable(_record):
        raise ProviderError("audit_unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(journal, "start", unavailable)
        assert chat(client, cid).status_code == 503
        assert calls == []
    monkeypatch.setattr(journal, "finish", unavailable)
    assert chat(client, cid).status_code == 503
    assert len(calls) == 1
    assert journal.records()[0].response_status == "unknown"
    preview = client.get(f"/api/challenges/{cid}/writeup/preview").json()
    assert "model_audit_incomplete" in preview["missing_requirements"]
    assert "未确定 1" in preview["markdown"]


def assert_recovery_export(client, cid, missing):
    route = f"/api/challenges/{cid}"
    preview = client.get(route + "/writeup/preview").json()
    assert preview["completeness"] == "incomplete"
    assert missing in preview["missing_requirements"]
    exported = client.get(route + "/export")
    assert exported.status_code == 200
    assert exported.headers["X-Dossier-Completeness"] == "incomplete"
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["completeness"] == "incomplete"
        assert missing in manifest["missing_requirements"]
        assert archive.read("writeup_generated.md").decode() == preview["markdown"]
        disclosure = archive.read("ai_disclosure.md").decode()
    return manifest["model_calls"], disclosure


def test_abrupt_process_exit_after_start_is_unknown_on_restart(service, tmp_path):
    client, calls, _ = service
    cid = create(client)
    journal = client.app.state.model_calls
    marker = tmp_path / "unexpected-provider-entry"
    script = """
import asyncio
import os
import sys
from pathlib import Path
from app.model_calls import ModelCallJournal, audited_complete
from app.providers import ModelRequest, ProviderConfig

class CrashAfterStart(ModelCallJournal):
    def start(self, record):
        super().start(record)
        os._exit(72)

class NeverCall:
    config = ProviderConfig(provider_id="synthetic", adapter="deepseek",
        base_url="https://synthetic.invalid", model_id="fixture", api_key_env="UNUSED")

    async def complete(self, request):
        Path(sys.argv[3]).touch()
        raise AssertionError("Provider entered before the intended crash")

asyncio.run(audited_complete(NeverCall(), ModelRequest(messages=[]),
    CrashAfterStart(Path(sys.argv[1])), challenge_id=sys.argv[2],
    purpose="challenge_chat", synthetic=False, data_scope="A2:text_only"))
"""
    child = subprocess.run(
        [sys.executable, "-B", "-c", script, str(journal.path), cid, str(marker)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert child.returncode == 72, child.stderr
    assert not marker.exists()
    with TestClient(create_app(journal.path.parent)) as restarted:
        records = restarted.get("/api/model/calls").json()["calls"]
        assert len(records) == 1 and records[0]["response_status"] == "unknown"
        assert records[0]["completed_at"] is None
        assert restarted.get(f"/api/challenges/{cid}/events").json() == []
        reported, disclosure = assert_recovery_export(
            restarted, cid, "model_audit_incomplete"
        )
        assert reported[0]["call_id"] == records[0]["call_id"]
        assert reported[0]["response_status"] == "unknown"
        assert "成功 0" in disclosure and "未确定 1" in disclosure
    assert calls == [] and not marker.exists()


def test_sqlite_finish_write_failure_keeps_start_after_reopen(service, monkeypatch):
    client, calls, _ = service
    cid = create(client)
    journal = client.app.state.model_calls
    finish = journal.finish

    def fail_insert(record):
        assert record.response_status == "success"
        with journal.connect() as db:
            db.execute("""CREATE TRIGGER test_abort_finish BEFORE INSERT ON call_finishes
                        BEGIN SELECT RAISE(ABORT, 'synthetic finish failure'); END""")
        finish(record)

    monkeypatch.setattr(journal, "finish", fail_insert)
    failed = chat(client, cid)
    assert failed.status_code == 503
    assert failed.json()["detail"]["code"] == "audit_unavailable"
    with TestClient(create_app(journal.path.parent)) as restarted:
        assert restarted.get(f"/api/challenges/{cid}/events").json() == []
        reported, disclosure = assert_recovery_export(
            restarted, cid, "model_audit_incomplete"
        )
        assert len(reported) == 1 and reported[0]["response_status"] == "unknown"
        assert "成功 0" in disclosure
    assert len(calls) == 1


def test_locked_journal_rejects_before_provider(service, monkeypatch):
    client, calls, _ = service
    cid = create(client)
    journal = client.app.state.model_calls
    journal._initialize()
    connect = sqlite3.connect

    def connect_without_wait(database, **kwargs):
        if database == journal.path:
            kwargs["timeout"] = 0
        return connect(database, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect_without_wait)
    with closing(connect(journal.path)) as lock:
        lock.execute("BEGIN IMMEDIATE")
        failed = chat(client, cid)
        assert failed.status_code == 503
        assert failed.json()["detail"]["code"] == "audit_unavailable"
    assert journal.records() == []
    assert client.get(f"/api/challenges/{cid}/events").json() == []
    assert calls == []


@pytest.mark.parametrize("event_type", ["model_call", "agent_message"])
def test_successful_provider_with_event_insert_failure(service, event_type):
    client, calls, _ = service
    cid = create(client)
    store = client.app.state.store
    with store.connect() as db:
        db.execute(f"""CREATE TRIGGER test_abort_event BEFORE INSERT ON events
                    WHEN json_extract(NEW.body, '$.event_type') = '{event_type}'
                    BEGIN SELECT RAISE(ABORT, 'synthetic event write failure'); END""")
    response = chat(client, cid)
    assert response.status_code == 503
    assert "synthetic event write failure" not in response.text
    assert "Synthetic unverified advice" not in response.text
    records = client.get("/api/model/calls").json()["calls"]
    assert len(records) == 1 and records[0]["response_status"] == "success"
    call_id = records[0]["call_id"]
    detail = response.json()["detail"]
    if event_type == "model_call":
        assert detail["code"] == "audit_unavailable"
        expected_events = []
        missing = "model_audit_incomplete"
    else:
        assert detail["code"] == "ai_response_persistence_failed"
        assert detail["call_id"] == call_id and detail["response_status"] == "success"
        assert call_id in detail["message"]
        expected_events = ["model_call"]
        missing = "model_response_unrecorded"
    with TestClient(create_app(client.app.state.model_calls.path.parent)) as restarted:
        events = restarted.get(f"/api/challenges/{cid}/events").json()
        assert [event["event_type"] for event in events] == expected_events
        if events:
            assert events[0]["payload"]["call_id"] == call_id
        reported, disclosure = assert_recovery_export(restarted, cid, missing)
        assert len(reported) == 1 and reported[0]["call_id"] == call_id
        assert reported[0]["response_status"] == "success"
        assert reported[0]["delivery_status"] == "not_recorded"
        assert "模型已响应，回答未入事件" in disclosure
    assert len(calls) == 1


@pytest.mark.parametrize(
    "mode", ["invalid_usage", "empty", "unsolicited_tool", "oversize"]
)
def test_invalid_provider_result_cannot_be_success(service, mode):
    client, _, replies = service
    cid = create(client)
    message = {"content": "synthetic"}
    payload = {"choices": [{"message": message}]}
    if mode == "invalid_usage":
        payload["usage"] = {"total_tokens": True}
    elif mode == "empty":
        message["content"] = " "
    elif mode == "unsolicited_tool":
        message["tool_calls"] = [
            {"id": "unexpected", "function": {"name": "file", "arguments": "{}"}}
        ]
    else:
        message["content"] = "x" * (513 * 1024)
    replies.append(httpx.Response(200, json=payload))
    assert chat(client, cid).status_code == 502
    records = client.get("/api/model/calls").json()["calls"]
    assert len(records) == 1 and records[0]["response_status"] != "success"
    assert [
        e["event_type"] for e in client.get(f"/api/challenges/{cid}/events").json()
    ] == ["model_call"]


def test_gateway_cancellation_is_durable_after_reopen(tmp_path, monkeypatch):
    monkeypatch.setenv("CTF_MODEL_NETWORK_ENABLED", "true")
    path = tmp_path / "calls.sqlite3"
    journal = ModelCallJournal(path)

    async def run():
        entered = asyncio.Event()

        class Waiting:
            config = CONFIG

            async def complete(self, request):
                entered.set()
                await asyncio.Future()

        task = asyncio.create_task(
            audited_complete(Waiting(), ModelRequest(messages=[]), journal)
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert [c.response_status for c in ModelCallJournal(path).records()] == [
        "cancelled"
    ]


@pytest.mark.parametrize("legacy", [False, True])
def test_smoke_commands_share_opt_in_and_absolute_isolation(
    tmp_path, monkeypatch, legacy
):
    entry = model_cli if legacy else ai_smoke_cli
    monkeypatch.setattr(
        sys,
        "argv",
        ["smoke", *(["unused.json"] if legacy else []), "--allow-model-network"],
    )
    root = tmp_path / "dedicated-smoke"
    monkeypatch.setenv("CTF_DATA_DIR", str(root))
    monkeypatch.setenv("CTF_MODEL_NETWORK_ENABLED", "false")
    with pytest.raises(SystemExit) as error:
        entry.main()
    assert error.value.code == 2 and not root.exists()
    monkeypatch.setenv("CTF_MODEL_NETWORK_ENABLED", "true")
    monkeypatch.setenv("CTF_DATA_DIR", "relative-untrusted")
    with pytest.raises(SystemExit) as error:
        entry.main()
    assert error.value.code == 2 and not root.exists()
    monkeypatch.setenv("CTF_DATA_DIR", str(root))
    observed = []

    class LocalSynthetic:
        config = CONFIG

        async def complete(self, request):
            observed.extend(m.content for m in request.messages)
            return ModelResponse(
                provider_id="deepseek", model_id="synthetic-model", text="OK"
            )

    if legacy:
        monkeypatch.setattr(
            model_cli.ProviderRegistry,
            "from_file",
            lambda _: type(
                "Registry",
                (),
                {"get": lambda self: LocalSynthetic()},
            )(),
        )
    else:
        monkeypatch.setattr(ai_smoke_cli, "build_deepseek_provider", LocalSynthetic)
    entry.main()
    assert len(observed) == 1 and observed[0].startswith("Reply with OK.")
    records = ModelCallJournal(root / "model-audit.sqlite3").records()
    assert (
        len(records) == 1 and records[0].synthetic and records[0].challenge_id is None
    )
    assert not (root / "workbench.sqlite3").exists()
