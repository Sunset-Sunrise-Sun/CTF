"""Issue #10 regressions: completeness states, counts, imports, human diff.

All data is synthetic.  No real challenge, Flag, credential or network target
is used.  The tests exercise the actual FastAPI application through TestClient
and the pure disclosure builders.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Challenge
from app.writeup import (
    build_writeup_preview,
    tool_proposal_statistics,
    tool_proposal_snapshot,
)

PNG = b"\x89PNG\r\n\x1a\nSYNTHETIC-ISSUE10"


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(tmp_path / "data")) as test_client:
        yield test_client


def create_challenge(
    client: TestClient,
    *,
    name: str = "SYNTHETIC-ISSUE10",
    profile: str = "real_challenge",
    ai_usage_level: str = "A2",
) -> str:
    response = client.post(
        "/api/challenges",
        json={
            "name": name,
            "category": "Misc",
            "description": "synthetic issue #10 fixture",
            "ai_usage_level": ai_usage_level,
            "evidence_profile": profile,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["challenge_id"]


def upload(
    client: TestClient,
    cid: str,
    filename: str,
    data: bytes,
    evidence_kind: str,
) -> dict:
    response = client.post(
        f"/api/challenges/{cid}/artifacts",
        files={"file": (filename, data, "application/octet-stream")},
        data={"evidence_kind": evidence_kind},
    )
    assert response.status_code == 201, response.text
    return response.json()


def add_approach(client: TestClient, cid: str) -> None:
    assert (
        client.post(
            f"/api/challenges/{cid}/notes",
            json={"text": "SYNTHETIC-APPROACH", "kind": "approach"},
        ).status_code
        == 201
    )


def add_manual(client: TestClient, cid: str) -> None:
    assert (
        client.post(
            f"/api/challenges/{cid}/manual-operations",
            json={
                "command": "python synth.py",
                "working_directory": "C:/synthetic",
                "purpose": "synthetic issue10",
                "exit_code": 0,
                "result_note": "synthetic result",
            },
        ).status_code
        == 201
    )


def preview(client: TestClient, cid: str) -> dict:
    response = client.get(f"/api/challenges/{cid}/writeup/preview")
    assert response.status_code == 200, response.text
    return response.json()


def test_tool_statistics_distinguish_executions_from_unique_artifacts():
    proposals = []
    for index in range(8):
        # Two executions share one byte-identical output Artifact ID.
        artifact_id = f"artifact-{index if index < 7 else 2}"
        proposals.append(
            {
                "proposal_id": f"proposal-{index}",
                "status": "succeeded",
                "execution_id": f"execution-{index}",
                "approval_id": f"approval-{index}",
                "output_artifact_id": artifact_id,
                "output_sha256": hashlib.sha256(artifact_id.encode()).hexdigest(),
            }
        )
    snapshot = tool_proposal_snapshot(proposals)
    stats = tool_proposal_statistics(snapshot)
    assert stats["execution_count"] == 8
    assert stats["unique_output_artifact_count"] == 7
    assert stats["unique_output_sha256_count"] == 7

    challenge = Challenge(
        name="SYNTHETIC-ISSUE10",
        category="Misc",
        ai_usage_level="A2",
        evidence_profile="synthetic_connectivity",
    )
    result = build_writeup_preview(
        challenge,
        [],
        [],
        None,
        lambda _sha: b"",
        {"valid": True, "earliest_affected_sequence": None},
        tool_proposals=snapshot,
    )
    assert result.tool_execution_count == 8
    assert result.unique_tool_output_artifact_count == 7
    assert "已开始执行：8 次" in result.markdown
    assert "唯一输出 Artifact：7 个" in result.markdown


def test_synthetic_connectivity_marks_code_and_flag_na_with_reasons(
    client: TestClient,
):
    cid = create_challenge(
        client, name="P2 synthetic connectivity", profile="synthetic_connectivity"
    )
    for index in range(7):
        upload(
            client,
            cid,
            f"tool-{index}.json",
            json.dumps({"index": index}).encode(),
            "execution_output",
        )

    body = preview(client, cid)
    requirements = {row["code"]: row for row in body["requirements"]}
    assert requirements["core_code"]["status"] == "not_applicable"
    assert "没有真实题目" in requirements["core_code"]["reason"]
    assert requirements["flag_capture"]["status"] == "not_applicable"
    assert "没有真实 Flag" in requirements["flag_capture"]["reason"]
    assert requirements["execution_evidence"]["status"] == "proven"
    assert requirements["manual_operation"]["status"] == "missing"
    assert requirements["platform_verification"]["status"] == "missing"
    assert "core_code" not in body["missing_requirements"]
    assert "flag_capture" not in body["missing_requirements"]
    assert set(body["not_applicable_requirements"]) == {
        "core_code",
        "flag_capture",
    }
    assert "不适用：synthetic connectivity 没有独立解题代码" in body["markdown"]
    assert "不适用：synthetic connectivity 没有真实 Flag" in body["markdown"]
    assert body["completeness"] == "incomplete"


def test_real_challenge_gets_no_na_pass_and_can_become_complete(
    client: TestClient,
):
    cid = create_challenge(client, name="SYNTHETIC-REAL-ISSUE10")
    add_approach(client, cid)
    add_manual(client, cid)
    upload(client, cid, "solve.py", b"print('synthetic')\n", "source_code")
    upload(client, cid, "run.png", PNG + b"run", "execution")
    upload(client, cid, "flag.png", PNG + b"flag", "flag_capture")
    upload(client, cid, "platform.png", PNG + b"platform", "platform_verification")

    body = preview(client, cid)
    assert body["completeness"] == "complete"
    assert body["missing_requirements"] == []
    assert body["not_applicable_requirements"] == []
    statuses = {row["code"]: row["status"] for row in body["requirements"]}
    assert statuses["core_code"] == "proven"
    assert statuses["flag_capture"] == "proven"
    assert statuses["manual_operation"] == "proven"
    assert statuses["platform_verification"] == "proven"


def test_missing_requirements_explain_who_and_how_to_supply(
    client: TestClient,
):
    cid = create_challenge(client, name="SYNTHETIC-MISSING-ISSUE10")
    body = preview(client, cid)
    rows = {row["code"]: row for row in body["requirements"]}
    for code in body["missing_requirements"]:
        if code in rows:
            assert rows[code]["status"] == "missing"
            assert rows[code]["remediation"], code
    assert "补充方式" in body["markdown"]


def make_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("a2-readonly-smoke.txt", b"CTF synthetic marker\n")
    return buffer.getvalue()


def test_import_manifest_is_distinguished_from_original_zip_entries(
    client: TestClient,
):
    cid = create_challenge(client, name="SYNTHETIC-IMPORT-ISSUE10")
    archive = make_zip()
    response = client.post(
        f"/api/challenges/{cid}/imports",
        files={"file": ("a2-readonly-smoke.zip", archive, "application/zip")},
    )
    assert response.status_code == 201, response.text

    exported = client.get(f"/api/challenges/{cid}/export")
    assert exported.status_code == 200, exported.text
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive_zip:
        names = archive_zip.namelist()
        manifest = json.loads(archive_zip.read("manifest.json"))
    import_status = manifest["imports"][0]
    assert import_status["original_archive_entries"] == ["a2-readonly-smoke.txt"]
    assert import_status["original_archive_entry_count"] == 1
    assert import_status["generated_manifest"]["is_original_archive_entry"] is False
    assert (
        import_status["generated_manifest"]["path"]
        == f"challenge/imports/{import_status['import_id']}/generated-manifest.json"
    )
    assert (
        f"challenge/imports/{import_status['import_id']}/generated-manifest.json"
        in names
    )
    extracted = [
        name for name in names if name.startswith("challenge/imports/") and "extracted" in name
    ]
    assert extracted == [
        f"challenge/imports/{import_status['import_id']}/extracted/a2-readonly-smoke.txt"
    ]


def test_human_draft_is_not_overwritten_and_diff_is_disclosed(
    client: TestClient,
):
    cid = create_challenge(client, name="SYNTHETIC-HUMAN-ISSUE10")
    add_approach(client, cid)
    add_manual(client, cid)
    upload(client, cid, "solve.py", b"print('synthetic')\n", "source_code")
    upload(client, cid, "run.png", PNG + b"run", "execution")
    upload(client, cid, "flag.png", PNG + b"flag", "flag_capture")
    upload(client, cid, "platform.png", PNG + b"platform", "platform_verification")
    human = "# Synthetic human writeup\n\nHUMAN-BYTE-EXACT\n"
    saved = client.put(
        f"/api/challenges/{cid}/writeup/draft",
        json={"content": human, "base_version": 0},
    )
    assert saved.status_code == 201, saved.text

    exported = client.get(f"/api/challenges/{cid}/export")
    assert exported.status_code == 200, exported.text
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    assert members["writeup.md"] == human.encode("utf-8")
    manifest = json.loads(members["manifest.json"])
    writeup = manifest["writeup"]
    assert writeup["final_source"] == "human"
    assert writeup["human"]["sha256"] == hashlib.sha256(
        human.encode("utf-8")
    ).hexdigest()
    diff = writeup["human_generated_diff"]
    assert diff["changed"] is True
    assert diff["human_sha256"] == writeup["human"]["sha256"]
    assert diff["human_never_overwritten"] is True
    assert "HUMAN-BYTE-EXACT" in diff["diff_preview"]
