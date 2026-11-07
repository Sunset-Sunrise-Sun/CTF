"""Acceptance tests for the Writeup draft preview and evidence ZIP export.

Every input is synthetic data built inside this module: hand-assembled ZIP
archives, fake PNG magic headers, and synthetic text.  No real competition
attachment, real flag, or real target is used.  Each test isolates its data
root with ``tmp_path`` so nothing is written into the repository.

The tests must pass on Windows locally and on Linux CI (Python 3.11).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sqlite3
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

PNG_HEADER = b"\x89PNG\r\n\x1a\n"

MISSING_APPROACH = "[待选手补充：核心解题思路]"
MISSING_FLAG_CAPTURE = "[证据缺失：Flag 获取即时截图尚未提供]"
MISSING_PLATFORM_VERIFICATION = "[证据缺失：平台验证截图尚未提供]"

SECTION_HEADINGS = [
    "## 1. 题目基本信息",
    "## 2. 解题思路",
    "## 3. 关键操作",
    "## 4. 核心代码",
    "## 5. 运行结果",
    "## 6. Flag 获取过程",
    "## 7. 平台验证",
    "## 8. AI 使用说明",
    "## 9. 证据清单",
]

TIMELINE_KEYS = {
    "sequence",
    "occurred_at",
    "actor",
    "event_type",
    "summary",
    "artifact_ids",
    "event_id",
}

PROJECT_NAME = "SYNTH-PROJECT-9f2c"
COMPETITION_NAME = "SYNTH-COMPETITION-4a71"
AI_POLICY_SUMMARY = "SYNTH-AI-POLICY: A1/A2 需披露"
RULE_BYTES = b"%PDF-1.7\nSYNTHETIC-COMPETITION-RULES\n"

CHALLENGE_NAME = "SYNTH_CHALLENGE_7d3e"
CHALLENGE_SCORE = 450
APPROACH_TEXT = "SYNTH-APPROACH: 由合成样本推导出解题思路"
COMMAND_TEXT = "python solve.py --synthetic-input"
RESULT_TEXT = "SYNTH-RESULT: 合成执行输出符合预期"
WORKING_DIRECTORY = "C:/synthetic/workspace"

CAPTURE_CLAIM = "2026-11-08T01:00:00+08:00"
STARTED_CLAIM = "2026-11-08T01:00:00+08:00"
FINISHED_CLAIM = "2026-11-08T01:02:00+08:00"

ZIP_FILES = {
    "README.txt": b"SYNTHETIC challenge readme\n",
    "src/solve.py": b"print('SYNTHETIC imported source')\n",
}

FLAG_BYTES = PNG_HEADER + b"SYNTHETIC-FLAG-CAPTURE-EVIDENCE"
PLATFORM_BYTES = PNG_HEADER + b"SYNTHETIC-PLATFORM-VERIFICATION-EVIDENCE"
EXECUTION_BYTES = PNG_HEADER + b"SYNTHETIC-EXECUTION-EVIDENCE"
SOURCE_CODE_BYTES = b"def solve():\n    return 'SYNTHETIC_SOURCE_CODE'\n"
ANALYSIS_BYTES = b"SYNTHETIC-ANALYSIS-NOTES\n"

# (evidence_kind, uploaded filename, bytes, optional capture_time_claim)
ARTIFACT_SPECS = (
    ("flag_capture", "flag_capture.png", FLAG_BYTES, CAPTURE_CLAIM),
    ("platform_verification", "platform_verification.png", PLATFORM_BYTES, None),
    ("execution", "execution.png", EXECUTION_BYTES, None),
    ("source_code", "solve.py", SOURCE_CODE_BYTES, None),
    ("analysis", "analysis_notes.txt", ANALYSIS_BYTES, None),
)

# kind -> archive path used by the export contract
EVIDENCE_ARCHIVE_PATHS = {
    "flag_capture": "evidence/flag_capture/flag_capture.png",
    "platform_verification": "evidence/platform_verification/platform_verification.png",
    "execution": "evidence/execution/execution.png",
    "source_code": "scripts/solve.py",
    "analysis": "evidence/analysis/analysis_notes.txt",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def blob_path(data_root: Path, sha256: str) -> Path:
    return data_root / "artifacts" / "sha256" / sha256[:2] / sha256[2:4] / sha256


def make_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


ZIP_BYTES = make_zip(ZIP_FILES)


def put_project(client: TestClient) -> dict:
    response = client.put(
        "/api/project",
        json={
            "project_name": PROJECT_NAME,
            "competition_name": COMPETITION_NAME,
            "competition_type": "CTF",
            "ai_policy_summary": AI_POLICY_SUMMARY,
        },
    )
    assert response.status_code == 200
    return response.json()


def upload_rules(client: TestClient) -> dict:
    response = client.post(
        "/api/project/rules",
        files={"file": ("rules.pdf", RULE_BYTES, "application/pdf")},
    )
    assert response.status_code == 200
    return response.json()


def create_challenge(
    client: TestClient,
    *,
    name: str = CHALLENGE_NAME,
    category: str = "Misc",
    score: int | None = CHALLENGE_SCORE,
    ai_usage_level: str = "A2",
) -> str:
    payload = {
        "name": name,
        "category": category,
        "description": "synthetic challenge description",
        "ai_usage_level": ai_usage_level,
    }
    if score is not None:
        payload["score"] = score
    response = client.post("/api/challenges", json=payload)
    assert response.status_code == 201
    return response.json()["challenge_id"]


def upload_import(client: TestClient, cid: str) -> dict:
    response = client.post(
        f"/api/challenges/{cid}/imports",
        files={"file": ("challenge.zip", ZIP_BYTES, "application/zip")},
    )
    assert response.status_code == 201
    return response.json()


def upload_artifact(
    client: TestClient,
    cid: str,
    *,
    filename: str,
    data: bytes,
    evidence_kind: str | None = None,
    capture_time_claim: str | None = None,
) -> dict:
    form: dict[str, str] = {}
    if evidence_kind is not None:
        form["evidence_kind"] = evidence_kind
    if capture_time_claim is not None:
        form["capture_time_claim"] = capture_time_claim
    response = client.post(
        f"/api/challenges/{cid}/artifacts",
        files={"file": (filename, data, "application/octet-stream")},
        data=form,
    )
    assert response.status_code == 201
    return response.json()


def add_note(client: TestClient, cid: str) -> dict:
    response = client.post(
        f"/api/challenges/{cid}/notes",
        json={"text": APPROACH_TEXT},
    )
    assert response.status_code == 201
    return response.json()


def add_manual_operation(client: TestClient, cid: str) -> dict:
    response = client.post(
        f"/api/challenges/{cid}/manual-operations",
        json={
            "command": COMMAND_TEXT,
            "working_directory": WORKING_DIRECTORY,
            "purpose": "synthetic verification",
            "exit_code": 0,
            "result_note": RESULT_TEXT,
            "started_at_claim": STARTED_CLAIM,
            "finished_at_claim": FINISHED_CLAIM,
        },
    )
    assert response.status_code == 201
    return response.json()


def build_full_dossier(client: TestClient) -> dict:
    """Build a complete, synthetically recorded dossier and return its parts."""
    project = put_project(client)
    rules = upload_rules(client)
    cid = create_challenge(client)
    import_body = upload_import(client, cid)
    artifacts = {}
    for kind, filename, data, claim in ARTIFACT_SPECS:
        artifacts[kind] = upload_artifact(
            client,
            cid,
            filename=filename,
            data=data,
            evidence_kind=kind,
            capture_time_claim=claim,
        )
    note = add_note(client, cid)
    manual = add_manual_operation(client, cid)
    return {
        "cid": cid,
        "project": project,
        "rules": rules,
        "import": import_body,
        "artifacts": artifacts,
        "note": note,
        "manual": manual,
    }


def preview_body(client: TestClient, cid: str) -> dict:
    response = client.get(f"/api/challenges/{cid}/writeup/preview")
    assert response.status_code == 200
    return response.json()


def export_response(client: TestClient, cid: str):
    response = client.get(f"/api/challenges/{cid}/export")
    assert response.status_code == 200
    media_type = response.headers["content-type"].split(";")[0]
    assert media_type == "application/zip"
    return response


def read_members(response) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def parse_sha256sums(members: dict[str, bytes]) -> dict[str, str]:
    lines = members["SHA256SUMS"].decode("utf-8").splitlines()
    assert lines
    sums: dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        assert match is not None, line
        name = match.group(2)
        assert name not in sums
        sums[name] = match.group(1)
    return sums


def tap_event(data_root: Path, cid: str, mutate) -> None:
    """Tamper one persisted event body, dropping append-only triggers first."""
    connection = sqlite3.connect(data_root / "workbench.sqlite3", timeout=15)
    try:
        connection.execute("DROP TRIGGER IF EXISTS events_no_update")
        connection.execute("DROP TRIGGER IF EXISTS events_no_delete")
        row = connection.execute(
            "SELECT event_id, body FROM events WHERE challenge_id=? "
            "ORDER BY sequence LIMIT 1",
            (cid,),
        ).fetchone()
        assert row is not None
        event_id, raw_body = row
        body = json.loads(raw_body)
        mutate(body)
        connection.execute(
            "UPDATE events SET body=? WHERE event_id=?",
            (json.dumps(body), event_id),
        )
        connection.commit()
    finally:
        connection.close()


def wait_for_export_cleanup(export_dir: Path, timeout: float = 5.0) -> list[str]:
    """Wait until no temporary/final export archives remain in the export dir."""
    deadline = time.monotonic() + timeout
    leftovers: list[str] = []
    while time.monotonic() < deadline:
        leftovers = (
            [
                path.name
                for path in export_dir.iterdir()
                if path.suffix in {".zip", ".part"}
            ]
            if export_dir.is_dir()
            else []
        )
        if not leftovers:
            return leftovers
        time.sleep(0.05)
    return leftovers


def file_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256_hex(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def client(data_root: Path):
    with TestClient(create_app(data_root)) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# Writeup preview
# ---------------------------------------------------------------------------


def test_writeup_preview_empty_challenge_marks_all_missing(
    client: TestClient,
) -> None:
    cid = create_challenge(
        client, name="SYNTH-EMPTY", score=None, ai_usage_level="unknown"
    )

    body = preview_body(client, cid)

    assert body["completeness"] == "incomplete"
    assert body["event_count"] == 0
    assert body["artifact_count"] == 0
    missing = set(body["missing_requirements"])
    assert {
        "core_approach",
        "manual_operation",
        "flag_capture",
        "platform_verification",
        "ai_usage_level",
    } <= missing
    assert "integrity" not in missing

    markdown = body["markdown"]
    assert MISSING_APPROACH in markdown
    assert MISSING_FLAG_CAPTURE in markdown
    assert MISSING_PLATFORM_VERIFICATION in markdown
    assert "尚无证据文件。" in markdown
    assert "尚无事件。" in markdown


@pytest.mark.parametrize(
    ("ai_usage_level", "is_missing"),
    [("A0", False), ("A1", False), ("A2", False), ("unknown", True)],
)
def test_writeup_preview_ai_usage_level_requirement(
    client: TestClient, ai_usage_level: str, is_missing: bool
) -> None:
    cid = create_challenge(
        client, name=f"SYNTH-AI-{ai_usage_level}", ai_usage_level=ai_usage_level
    )

    body = preview_body(client, cid)

    assert ("ai_usage_level" in body["missing_requirements"]) is is_missing
    assert f"题目 AI 使用等级：{ai_usage_level}" in body["markdown"]


def test_writeup_preview_has_nine_fixed_sections(client: TestClient) -> None:
    cid = create_challenge(client, name="SYNTH-SECTIONS")

    markdown = preview_body(client, cid)["markdown"]

    headings = re.findall(r"^## \d+\. .+$", markdown, flags=re.MULTILINE)
    assert headings == SECTION_HEADINGS
    positions = [markdown.index(heading) for heading in SECTION_HEADINGS]
    assert positions == sorted(positions)
    assert "工作台未启用自动工具执行" in markdown
    assert "AI 建议" in markdown
    assert "### 事件时间线摘要" in markdown


def test_writeup_preview_renders_only_recorded_content(
    client: TestClient,
) -> None:
    ctx = build_full_dossier(client)

    body = preview_body(client, ctx["cid"])
    markdown = body["markdown"]

    assert body["completeness"] == "complete"
    assert body["missing_requirements"] == []
    assert "档案完整性：complete" in markdown

    for value in (
        PROJECT_NAME,
        COMPETITION_NAME,
        CHALLENGE_NAME,
        str(CHALLENGE_SCORE),
        "A2",
        APPROACH_TEXT,
        COMMAND_TEXT,
        RESULT_TEXT,
        WORKING_DIRECTORY,
        AI_POLICY_SUMMARY,
        ctx["rules"]["rules_sha256"],
    ):
        assert value in markdown, value

    for artifact in ctx["artifacts"].values():
        assert artifact["original_filename"] in markdown
        assert artifact["sha256"] in markdown
    assert ctx["import"]["original_artifact"]["original_filename"] in markdown

    # The evidence table and the timeline summary are rendered as tables.
    assert "| 文件 | 证据类型 | 大小 | SHA256 |" in markdown
    assert "| sequence | 时间（服务器） | 来源 | 类型 | 关联证据 |" in markdown

    # Claimed (user-declared) capture/participation times are called out.
    assert any("申报" in warning for warning in body["warnings"])


def test_writeup_preview_labels_manual_runs_as_declared(
    client: TestClient,
) -> None:
    cid = create_challenge(client, name="SYNTH-MANUAL")
    add_note(client, cid)
    manual = add_manual_operation(client, cid)

    events = client.get(f"/api/challenges/{cid}/events").json()
    assert [event["event_type"] for event in events] == [
        "note",
        "manual_operation_recorded",
    ]
    event_types = {event["event_type"] for event in events}
    assert "tool_started" not in event_types
    assert "tool_finished" not in event_types
    assert manual["payload"]["execution_mode"] == "manual_external"
    assert manual["payload"]["execution_verified"] is False

    markdown = preview_body(client, cid)["markdown"]
    assert "execution_mode=manual_external" in markdown
    assert "execution_verified=false" in markdown
    assert "不是工作台自动执行" in markdown
    assert "已自动执行" not in markdown
    assert COMMAND_TEXT in markdown


def test_writeup_preview_reports_precise_missing_requirements(
    client: TestClient,
) -> None:
    cid = create_challenge(client, name="SYNTH-PARTIAL")
    add_note(client, cid)
    add_manual_operation(client, cid)

    body = preview_body(client, cid)

    assert body["completeness"] == "incomplete"
    assert body["missing_requirements"] == ["flag_capture", "platform_verification"]
    assert body["event_count"] == 2
    assert body["artifact_count"] == 0

    markdown = body["markdown"]
    assert MISSING_FLAG_CAPTURE in markdown
    assert MISSING_PLATFORM_VERIFICATION in markdown
    assert MISSING_APPROACH not in markdown
    # Missing evidence must not be replaced with fabricated content.
    assert "尚无证据文件。" in markdown
    assert "flag{" not in markdown


def test_writeup_preview_detects_tampered_event_chain(
    client: TestClient, data_root: Path
) -> None:
    ctx = build_full_dossier(client)
    cid = ctx["cid"]

    def mutate(body: dict) -> None:
        body["payload"]["size"] = int(body["payload"]["size"]) + 1

    tap_event(data_root, cid, mutate)

    integrity = client.get(f"/api/challenges/{cid}/integrity").json()
    assert integrity == {"valid": False, "earliest_affected_sequence": 1}

    body = preview_body(client, cid)
    assert body["completeness"] == "incomplete"
    assert "integrity" in body["missing_requirements"]
    assert body["warnings"]
    assert "事件哈希链校验失败" in body["markdown"]


def test_writeup_preview_counts_and_restart_persistence(data_root: Path) -> None:
    with TestClient(create_app(data_root)) as first:
        ctx = build_full_dossier(first)
        cid = ctx["cid"]
        events = first.get(f"/api/challenges/{cid}/events").json()
        artifacts = first.get(f"/api/challenges/{cid}/artifacts").json()
        before = preview_body(first, cid)

        assert before["completeness"] == "complete"
        assert before["event_count"] == len(events)
        assert before["artifact_count"] == len(artifacts)

    with TestClient(create_app(data_root)) as restarted:
        after = preview_body(restarted, cid)

    assert after == before


def test_writeup_and_export_unknown_challenge_return_404(
    client: TestClient,
) -> None:
    unknown = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/challenges/{unknown}/writeup/preview").status_code == 404
    assert client.get(f"/api/challenges/{unknown}/export").status_code == 404


# ---------------------------------------------------------------------------
# Evidence export: archive structure and content
# ---------------------------------------------------------------------------


def test_export_archive_contains_all_required_entries(
    client: TestClient,
) -> None:
    ctx = build_full_dossier(client)

    response = export_response(client, ctx["cid"])
    assert response.headers["X-Dossier-Completeness"] == "complete"

    members = read_members(response)
    names = set(members)
    for required in (
        "challenge/original.zip",
        "challenge/extracted/README.txt",
        "challenge/extracted/src/solve.py",
        "scripts/solve.py",
        "evidence/analysis/analysis_notes.txt",
        "evidence/execution/execution.png",
        "evidence/flag_capture/flag_capture.png",
        "evidence/platform_verification/platform_verification.png",
        "challenge/rules/rules.pdf",
        "logs/events.json",
        "logs/timeline.json",
        "writeup.md",
        "manifest.json",
        "ai_disclosure.md",
        "SHA256SUMS",
    ):
        assert required in names, required
    assert "INCOMPLETE.txt" not in names


def test_export_events_and_timeline_preserve_chain_order(
    client: TestClient,
) -> None:
    ctx = build_full_dossier(client)
    cid = ctx["cid"]
    api_events = client.get(f"/api/challenges/{cid}/events").json()

    members = read_members(export_response(client, cid))

    events = json.loads(members["logs/events.json"])
    assert isinstance(events, list)
    sequences = [event["sequence"] for event in events]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)
    assert sequences == [event["sequence"] for event in api_events]

    timeline = json.loads(members["logs/timeline.json"])
    assert isinstance(timeline, list)
    assert [entry["sequence"] for entry in timeline] == sequences
    for entry in timeline:
        assert set(entry) == TIMELINE_KEYS
        assert isinstance(entry["artifact_ids"], list)
        assert isinstance(entry["summary"], str) and entry["summary"]
        assert entry["event_id"]


def test_export_sha256sums_verifies_every_delivered_file(
    client: TestClient,
) -> None:
    ctx = build_full_dossier(client)

    members = read_members(export_response(client, ctx["cid"]))
    sums = parse_sha256sums(members)

    assert "SHA256SUMS" not in sums
    assert set(sums) == set(members) - {"SHA256SUMS"}
    for name, digest in sums.items():
        assert sha256_hex(members[name]) == digest, name


def test_export_manifest_describes_dossier(client: TestClient) -> None:
    ctx = build_full_dossier(client)
    cid = ctx["cid"]
    api_events = client.get(f"/api/challenges/{cid}/events").json()
    api_artifacts = client.get(f"/api/challenges/{cid}/artifacts").json()

    members = read_members(export_response(client, cid))
    manifest = json.loads(members["manifest.json"])

    assert manifest["schema"]
    assert manifest["challenge"]["challenge_id"] == cid
    assert manifest["challenge"]["name"] == CHALLENGE_NAME
    assert manifest["challenge"]["score"] == CHALLENGE_SCORE
    assert manifest["challenge"]["ai_usage_level"] == "A2"
    assert manifest["project"]["project_name"] == PROJECT_NAME
    assert manifest["project"]["rules_sha256"] == ctx["rules"]["rules_sha256"]
    assert manifest["counts"] == {
        "events": len(api_events),
        "artifacts": len(api_artifacts),
        "imports": 1,
    }
    assert manifest["completeness"] == "complete"
    assert manifest["missing_requirements"] == []
    assert manifest["missing_files"] == []
    assert isinstance(manifest["warnings"], list)
    assert manifest["integrity"] == {
        "valid": True,
        "earliest_affected_sequence": None,
    }
    assert manifest["tool_execution_enabled"] is False
    assert manifest["ai_suggestions_are_not_actions"] is True
    assert len(manifest["imports"]) == 1
    assert manifest["imports"][0]["import_id"] == ctx["import"]["import_id"]
    assert len(manifest["artifacts"]) == len(api_artifacts)

    flag = next(
        item
        for item in manifest["artifacts"]
        if item["evidence_kind"] == "flag_capture"
    )
    assert flag["sha256"] == ctx["artifacts"]["flag_capture"]["sha256"]
    assert flag["capture_time_claim"] == CAPTURE_CLAIM
    assert flag["original_filename"] == "flag_capture.png"


def test_export_bytes_match_uploaded_synthetic_evidence(
    client: TestClient,
) -> None:
    ctx = build_full_dossier(client)
    cid = ctx["cid"]
    markdown = preview_body(client, cid)["markdown"]

    members = read_members(export_response(client, cid))

    original = members["challenge/original.zip"]
    assert original == ZIP_BYTES
    assert sha256_hex(original) == ctx["import"]["original_artifact"]["sha256"]

    with zipfile.ZipFile(io.BytesIO(ZIP_BYTES)) as source:
        for name, data in ZIP_FILES.items():
            extracted = members[f"challenge/extracted/{name}"]
            assert extracted == data
            assert extracted == source.read(name)

    for kind, _filename, data, _claim in ARTIFACT_SPECS:
        arcname = EVIDENCE_ARCHIVE_PATHS[kind]
        assert members[arcname] == data
        assert sha256_hex(members[arcname]) == ctx["artifacts"][kind]["sha256"]

    assert members["writeup.md"].decode("utf-8") == markdown

    disclosure = members["ai_disclosure.md"].decode("utf-8")
    assert "否" in disclosure
    assert "未启用" in disclosure
    assert "execution_mode=manual_external" in disclosure


def test_export_does_not_mutate_recorded_evidence(
    client: TestClient, data_root: Path
) -> None:
    ctx = build_full_dossier(client)
    cid = ctx["cid"]
    events_before = client.get(f"/api/challenges/{cid}/events").json()
    artifacts_before = client.get(f"/api/challenges/{cid}/artifacts").json()
    integrity_before = client.get(f"/api/challenges/{cid}/integrity").json()
    sha_root = data_root / "artifacts" / "sha256"
    blobs_before = file_hashes(sha_root)
    assert integrity_before["valid"] is True

    response = export_response(client, cid)
    assert response.headers["X-Dossier-Completeness"] == "complete"

    assert client.get(f"/api/challenges/{cid}/events").json() == events_before
    assert client.get(f"/api/challenges/{cid}/artifacts").json() == artifacts_before
    assert client.get(f"/api/challenges/{cid}/integrity").json() == integrity_before
    assert file_hashes(sha_root) == blobs_before


# ---------------------------------------------------------------------------
# Evidence export: completeness marking
# ---------------------------------------------------------------------------


def test_export_incomplete_dossier_is_marked_incomplete(
    client: TestClient,
) -> None:
    cid = create_challenge(
        client, name="SYNTH-INCOMPLETE", score=None, ai_usage_level="unknown"
    )

    response = export_response(client, cid)
    assert response.headers["X-Dossier-Completeness"] == "incomplete"

    members = read_members(response)
    assert "INCOMPLETE.txt" in members
    assert "challenge/original.zip" not in members
    assert json.loads(members["logs/events.json"]) == []

    manifest = json.loads(members["manifest.json"])
    assert manifest["completeness"] == "incomplete"
    missing = set(manifest["missing_requirements"])
    assert {
        "core_approach",
        "manual_operation",
        "flag_capture",
        "platform_verification",
        "ai_usage_level",
    } <= missing
    assert "challenge/original.zip" in manifest["missing_files"]
    assert manifest["project"] is None
    assert manifest["tool_execution_enabled"] is False
    assert manifest["ai_suggestions_are_not_actions"] is True

    markdown = members["writeup.md"].decode("utf-8")
    assert MISSING_APPROACH in markdown
    assert MISSING_FLAG_CAPTURE in markdown
    assert MISSING_PLATFORM_VERIFICATION in markdown
    assert "本证据档案不完整" in members["INCOMPLETE.txt"].decode("utf-8")


def test_export_complete_dossier_has_no_incomplete_marker(
    client: TestClient,
) -> None:
    ctx = build_full_dossier(client)

    response = export_response(client, ctx["cid"])
    assert response.headers["X-Dossier-Completeness"] == "complete"

    members = read_members(response)
    assert "INCOMPLETE.txt" not in members
    manifest = json.loads(members["manifest.json"])
    assert manifest["completeness"] == "complete"
    assert manifest["missing_requirements"] == []
    assert manifest["missing_files"] == []
    assert "缺失/未确认项" not in members["writeup.md"].decode("utf-8")
    assert "档案完整性：complete" in members["ai_disclosure.md"].decode("utf-8")


def test_export_tampered_artifact_is_reported_incomplete(
    client: TestClient, data_root: Path
) -> None:
    ctx = build_full_dossier(client)
    cid = ctx["cid"]
    events_before = client.get(f"/api/challenges/{cid}/events").json()
    flag = ctx["artifacts"]["flag_capture"]
    stored = blob_path(data_root, flag["sha256"])
    assert stored.is_file()
    os.chmod(stored, 0o600)
    stored.write_bytes(FLAG_BYTES + b"-TAMPERED")

    # A tampered blob must not crash the export; it is reported as incomplete.
    response = export_response(client, cid)
    assert response.headers["X-Dossier-Completeness"] == "incomplete"

    members = read_members(response)
    manifest = json.loads(members["manifest.json"])
    assert manifest["completeness"] == "incomplete"
    assert manifest["missing_files"]
    assert any("flag_capture.png" in item for item in manifest["missing_files"])
    assert manifest["warnings"]
    assert "INCOMPLETE.txt" in members
    assert "evidence/flag_capture/flag_capture.png" not in members

    # The recorded evidence log itself is never rewritten by an export.
    assert client.get(f"/api/challenges/{cid}/events").json() == events_before
    integrity = client.get(f"/api/challenges/{cid}/integrity").json()
    assert integrity["valid"] is True


def test_export_temporary_archives_are_cleaned_up(data_root: Path) -> None:
    with TestClient(create_app(data_root)) as client:
        ctx = build_full_dossier(client)
        export_dir = data_root / ".exports"

        for _ in range(3):
            export_response(client, ctx["cid"])
            leftovers = wait_for_export_cleanup(export_dir)
            assert leftovers == [], leftovers

        entries = list(export_dir.iterdir()) if export_dir.is_dir() else []
        assert [path.name for path in entries if path.suffix in {".zip", ".part"}] == []


def test_export_is_repeatable_but_generated_at_changes(
    client: TestClient,
) -> None:
    ctx = build_full_dossier(client)

    first = read_members(export_response(client, ctx["cid"]))
    second = read_members(export_response(client, ctx["cid"]))

    first_manifest = json.loads(first["manifest.json"])
    second_manifest = json.loads(second["manifest.json"])

    assert set(first) == set(second)
    assert first["writeup.md"] == second["writeup.md"]
    assert first_manifest["generated_at"] != second_manifest["generated_at"]
    assert first_manifest["completeness"] == second_manifest["completeness"]
    assert first_manifest["counts"] == second_manifest["counts"]


# ---------------------------------------------------------------------------
# End-to-end workflow
# ---------------------------------------------------------------------------


def test_writeup_and_export_end_to_end_workflow(data_root: Path) -> None:
    with TestClient(create_app(data_root)) as client:
        project = put_project(client)
        assert project["project_name"] == PROJECT_NAME
        rules = upload_rules(client)
        assert rules["rules_sha256"] == sha256_hex(RULE_BYTES)

        cid = create_challenge(client, score=CHALLENGE_SCORE)
        import_body = upload_import(client, cid)
        assert import_body["extracted_file_count"] == len(ZIP_FILES)
        assert import_body["original_artifact"]["evidence_kind"] == "challenge_archive"

        artifact_views = []
        for kind, filename, data, claim in ARTIFACT_SPECS:
            artifact_views.append(
                upload_artifact(
                    client,
                    cid,
                    filename=filename,
                    data=data,
                    evidence_kind=kind,
                    capture_time_claim=claim,
                )
            )
        add_note(client, cid)
        add_manual_operation(client, cid)

        events = client.get(f"/api/challenges/{cid}/events").json()
        artifacts = client.get(f"/api/challenges/{cid}/artifacts").json()
        event_types = [event["event_type"] for event in events]
        assert event_types.count("artifact_added") == 1 + len(artifact_views)
        assert "challenge_imported" in event_types
        assert "note" in event_types
        assert "manual_operation_recorded" in event_types
        assert [event["sequence"] for event in events] == list(
            range(1, len(events) + 1)
        )

        preview = preview_body(client, cid)
        assert preview["completeness"] == "complete"
        assert preview["missing_requirements"] == []
        assert preview["event_count"] == len(events)
        assert preview["artifact_count"] == len(artifacts)

        response = export_response(client, cid)
        assert response.headers["X-Dossier-Completeness"] == "complete"
        members = read_members(response)

        sums = parse_sha256sums(members)
        assert set(sums) == set(members) - {"SHA256SUMS"}
        for name, digest in sums.items():
            assert sha256_hex(members[name]) == digest, name

        assert members["challenge/original.zip"] == ZIP_BYTES
        assert members["challenge/rules/rules.pdf"] == RULE_BYTES
        assert members["writeup.md"].decode("utf-8") == preview["markdown"]
        assert members["logs/events.json"]
        timeline = json.loads(members["logs/timeline.json"])
        assert [entry["sequence"] for entry in timeline] == [
            event["sequence"] for event in events
        ]
        manifest = json.loads(members["manifest.json"])
        assert manifest["completeness"] == "complete"
        assert manifest["counts"]["events"] == len(events)
        assert manifest["counts"]["artifacts"] == len(artifacts)
        assert "INCOMPLETE.txt" not in members

    # Restarting the app must reproduce the same draft and export result.
    with TestClient(create_app(data_root)) as restarted:
        assert preview_body(restarted, cid) == preview
        repeated = export_response(restarted, cid)
        assert repeated.headers["X-Dossier-Completeness"] == "complete"
        repeated_members = read_members(repeated)
        assert repeated_members["writeup.md"] == members["writeup.md"]
