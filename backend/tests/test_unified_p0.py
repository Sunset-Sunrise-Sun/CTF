"""End-to-end P0 integration tests: audit -> AI proposal -> human approval ->
execution -> Artifact -> Writeup/ZIP disclosure, plus permission and leak checks.
"""

from __future__ import annotations

import io
import json
import zipfile

import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from app.providers import DeepSeekAdapter, ProviderConfig

CONFIG = ProviderConfig(
    provider_id="deepseek",
    adapter="deepseek",
    model_id="synthetic-model",
    base_url="https://synthetic.invalid",
    api_key_env="SYNTHETIC_UNIFIED_TEST_KEY",
)


def make_client(tmp_path, monkeypatch, answers):
    monkeypatch.setenv("CTF_MODEL_NETWORK_ENABLED", "true")
    monkeypatch.setenv("SYNTHETIC_UNIFIED_TEST_KEY", "synthetic-credential-sentinel")
    calls = []

    def handler(request):
        calls.append(json.loads(request.read()))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": answers.pop(0)}},
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
            },
        )

    monkeypatch.setattr(
        "app.ai_assistant.build_deepseek_provider",
        lambda: DeepSeekAdapter(CONFIG, httpx.MockTransport(handler)),
    )
    client = TestClient(create_app(tmp_path / "data"))
    return client, calls


def create(client, level="A2"):
    response = client.post(
        "/api/challenges",
        json={
            "name": "Synthetic unified",
            "category": "Misc",
            "description": "synthetic challenge",
            "ai_usage_level": level,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["challenge_id"]


def chat(client, cid, **fields):
    return client.post(
        f"/api/challenges/{cid}/ai/chat",
        json={
            "question": "Inspect the synthetic file",
            "confirm_external_processing": True,
            "consent_challenge_id": cid,
            **fields,
        },
    )


def write_workspace_file(client, cid):
    root = client.app.state.workspace.challenge(cid)
    (root / "sample.bin").write_bytes(
        b"\x7fELF\x02\x01" + b"\x00" * 14 + b"\x3e\x00" + b" SYNTHETIC_MARKER "
    )


def test_ai_proposal_is_linked_to_audit_and_requires_human_execution(tmp_path, monkeypatch):
    answer = (
        "先检查文件头。\n\n"
        "```json\n"
        '{"tool_proposals":[{"tool_name":"file_inspect",'
        '"arguments":{"path":"sample.bin"},"reason":"synthetic inspection"}]}\n'
        "```"
    )
    client, calls = make_client(
        tmp_path, monkeypatch, [answer, "synthetic second-turn answer"]
    )
    with client:
        cid = create(client, "A2")
        write_workspace_file(client, cid)
        response = chat(client, cid)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["call_id"]
        assert len(body["tool_proposals"]) == 1
        proposal = body["tool_proposals"][0]
        assert proposal["status"] == "pending"
        assert proposal["model_call_id"] == body["call_id"]
        assert proposal["tool_name"] == "file_inspect"

        # The model response itself must not execute anything.
        events = client.get(f"/api/challenges/{cid}/events").json()
        event_types = [event["event_type"] for event in events]
        assert "tool_proposed" in event_types
        assert "tool_started" not in event_types and "tool_finished" not in event_types
        proposed = next(e for e in events if e["event_type"] == "tool_proposed")
        assert proposed["payload"]["proposal_id"] == proposal["proposal_id"]
        assert proposed["payload"]["model_call_id"] == body["call_id"]
        agent = next(e for e in events if e["event_type"] == "agent_message")
        assert agent["payload"]["call_id"] == body["call_id"]
        assert agent["payload"]["tool_proposal_ids"] == [proposal["proposal_id"]]
        audit = client.get("/api/model/calls").json()["calls"]
        assert audit[0]["call_id"] == body["call_id"]
        assert audit[0]["response_status"] == "success"

        # Approval is a separate human action and does not execute.
        approved = client.post(
            f"/api/challenges/{cid}/tool-proposals/{proposal['proposal_id']}/approve",
            json={"approving_user": "synthetic-human", "note": "approved"},
        )
        assert approved.status_code == 200, approved.text
        approved_body = approved.json()
        assert approved_body["status"] == "approved"
        assert approved_body["approval_id"]
        assert approved_body["execution_id"] is None
        assert "tool_started" not in [
            e["event_type"] for e in client.get(f"/api/challenges/{cid}/events").json()
        ]

        executed = client.post(
            f"/api/challenges/{cid}/tool-proposals/{proposal['proposal_id']}/execute"
        )
        assert executed.status_code == 200, executed.text
        result = executed.json()
        assert result["status"] == "succeeded"
        assert result["execution_id"]
        assert result["output_artifact_id"]
        assert result["output_sha256"]
        assert result["artifact_ids"] == [result["output_artifact_id"]]

        finished = [
            e
            for e in client.get(f"/api/challenges/{cid}/events").json()
            if e["event_type"] == "tool_finished"
        ][-1]
        assert finished["payload"]["execution_id"] == result["execution_id"]
        assert finished["payload"]["artifact_ids"] == [result["output_artifact_id"]]
        assert finished["artifact_ids"] == [result["output_artifact_id"]]

        artifact = client.get(
            f"/api/challenges/{cid}/artifacts/{result['output_artifact_id']}/content"
        )
        assert artifact.status_code == 200
        stored = json.loads(artifact.content.decode("utf-8"))
        assert stored["format"] == "ELF"
        import hashlib

        assert hashlib.sha256(artifact.content).hexdigest() == result["output_sha256"]

        preview = client.get(f"/api/challenges/{cid}/writeup/preview").json()
        assert "本地工具" in preview["markdown"] or "工具申请" in preview["markdown"]
        assert preview["tool_proposal_count"] == 1
        assert preview["tool_execution_count"] == 1

        export = client.get(f"/api/challenges/{cid}/export")
        assert export.status_code == 200
        with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
            disclosure = archive.read("ai_disclosure.md").decode("utf-8")
            manifest = json.loads(archive.read("manifest.json"))
        assert "工具" in disclosure
        assert manifest["counts"]["tool_proposals"] == 1
        assert manifest["tool_proposals"][0]["proposal_id"] == proposal["proposal_id"]
        assert manifest["tool_proposals"][0]["model_call_id"] == body["call_id"]
        assert manifest["tool_proposals"][0]["output_artifact_id"]
        assert manifest["model_calls"][0]["call_id"] == body["call_id"]
        assert "synthetic-credential-sentinel" not in json.dumps(manifest)

        # A second execute is a duplicate and must not run again.
        twice = client.post(
            f"/api/challenges/{cid}/tool-proposals/{proposal['proposal_id']}/execute"
        )
        assert twice.status_code == 409
        assert len(calls) == 1

        # The next real /ai/chat request must replay the recorded tool result
        # (output artifact/hash and proposal/event links) into the model context.
        second = chat(client, cid, question="Use the recorded tool result")
        assert second.status_code == 201, second.text
        assert len(calls) == 2
        second_request = json.dumps(calls[1], ensure_ascii=False)
        assert "tool_finished" in second_request
        assert result["output_artifact_id"] in second_request
        assert result["output_sha256"] in second_request
        assert proposal["proposal_id"] in second_request
        # No automatic follow-up execution or second proposal was created.
        assert len(
            client.get(f"/api/challenges/{cid}/tool-proposals").json()
        ) == 1
        event_types_after = [
            e["event_type"]
            for e in client.get(f"/api/challenges/{cid}/events").json()
        ]
        assert event_types_after.count("tool_proposed") == 1
        assert event_types_after.count("tool_started") == 1
        assert event_types_after.count("tool_finished") == 1


def test_a1_a0_unknown_cannot_use_tool_endpoints(tmp_path, monkeypatch):
    client, _ = make_client(
        tmp_path, monkeypatch, ["A1 answer", "A2 answer"]
    )
    with client:
        a1 = create(client, "A1")
        write_workspace_file(client, a1)
        a1_chat = chat(client, a1)
        assert a1_chat.status_code == 201
        bad = client.post(
            f"/api/challenges/{a1}/tool-proposals",
            json={
                "tool_name": "file_inspect",
                "arguments": {"path": "sample.bin"},
                "reason": "must be denied",
            },
        )
        assert bad.status_code == 403

        for level in ("A0", "unknown"):
            cid = create(client, level)
            write_workspace_file(client, cid)
            denied = client.post(
                f"/api/challenges/{cid}/tool-proposals",
                json={
                    "tool_name": "file_inspect",
                    "arguments": {"path": "sample.bin"},
                    "reason": "must be denied",
                },
            )
            assert denied.status_code == 403

        # Direct HTTP calls cannot approve or execute a proposal after a
        # challenge is downgraded from A2 to A1.
        a2 = create(client, "A2")
        write_workspace_file(client, a2)
        proposal = client.post(
            f"/api/challenges/{a2}/tool-proposals",
            json={
                "tool_name": "file_inspect",
                "arguments": {"path": "sample.bin"},
                "reason": "downgrade fixture",
            },
        )
        assert proposal.status_code == 201
        pid = proposal.json()["proposal_id"]
        with client.app.state.store.connect() as db:
            row = db.execute(
                "SELECT body FROM challenges WHERE challenge_id=?", (a2,)
            ).fetchone()
            challenge = json.loads(row[0])
            challenge["ai_usage_level"] = "A1"
            db.execute(
                "UPDATE challenges SET body=? WHERE challenge_id=?",
                (json.dumps(challenge, ensure_ascii=False), a2),
            )
        assert (
            client.post(
                f"/api/challenges/{a2}/tool-proposals/{pid}/approve",
                json={"approving_user": "synthetic-human"},
            ).status_code
            == 403
        )
        assert (
            client.post(f"/api/challenges/{a2}/tool-proposals/{pid}/execute").status_code
            == 403
        )


def test_flag_confirmation_is_hash_only_and_disclosed(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch, [])
    with client:
        cid = create(client, "A2")
        flag = "flag{SYNTHETIC_UNIFIED_ONLY}"
        response = client.post(
            f"/api/challenges/{cid}/flag-confirmation",
            json={
                "flag": flag,
                "confirmed_by": "synthetic-user",
                "note": "manual confirmation",
            },
        )
        assert response.status_code == 201
        event = response.json()
        assert event["payload"]["platform_verified"] is False
        assert flag not in json.dumps(event, ensure_ascii=False)
        preview = client.get(f"/api/challenges/{cid}/writeup/preview").json()
        assert "人工确认 Flag" in preview["markdown"]
        assert "平台验证" in preview["markdown"]
        export = client.get(f"/api/challenges/{cid}/export")
        with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
            disclosure = archive.read("ai_disclosure.md").decode("utf-8")
            manifest = json.loads(archive.read("manifest.json"))
        assert "人工确认 Flag" in disclosure
        assert manifest["counts"]["flag_confirmations"] == 1
        assert flag not in json.dumps(manifest, ensure_ascii=False)


def test_api_key_does_not_leak_in_status_events_audit_or_export(tmp_path, monkeypatch):
    client, _ = make_client(
        tmp_path,
        monkeypatch,
        ["synthetic answer without credentials"],
    )
    with client:
        cid = create(client, "A2")
        response = chat(client, cid)
        assert response.status_code == 201
        surfaces = [
            client.get("/api/model/status").text,
            client.get("/api/model/calls").text,
            client.get(f"/api/challenges/{cid}/events").text,
            client.get(f"/api/challenges/{cid}/writeup/preview").text,
            client.get(f"/api/challenges/{cid}/export").content.decode("utf-8", "ignore"),
        ]
        assert all("synthetic-credential-sentinel" not in text for text in surfaces)
