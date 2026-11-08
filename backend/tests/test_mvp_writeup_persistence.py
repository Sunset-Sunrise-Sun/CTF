"""Regression tests for human Writeup persistence and the final evidence ZIP.

Every input here is synthetic data built inside this module: hand-written
Markdown strings, fake PNG magic headers, and ZIP archives assembled in memory.
No real competition material, credential, or Flag is used.  Each test isolates
its data root with ``tmp_path`` so nothing is written into the repository.

The suite must stay portable: it runs on Windows locally and on Linux CI with
Python 3.11, avoiding platform-specific paths and timing assumptions.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

# ---------------------------------------------------------------------------
# contract constants (independently restated, not imported from the app)
# ---------------------------------------------------------------------------

DEFAULT_MAX_WRITEUP_BYTES = 1_048_576
WRITEUP_JSON_OVERHEAD_BYTES = 64 * 1024

NO_HUMAN_NOTE = "> 注意：尚未保存人工稿，本文件为服务器生成的初稿。\n\n"
INTEGRITY_FALLBACK_NOTE = (
    "> 注意：已保存的人工稿完整性校验失败，本文件为服务器生成的初稿。\n\n"
)
CONFLICT_MESSAGE = "Writeup version conflict; reload the latest draft before saving"

HUMAN_CONTENT = (
    "# 合成人工稿\n\nSYNTHETIC-HUMAN-WRITEUP-CONTENT\n第二行：中文与符号 ✓\n"
)
HUMAN_CONTENT_V2 = "# 合成人工稿 v2\n\nSYNTHETIC-HUMAN-WRITEUP-CONTENT-V2\n"
STALE_LOCAL_CONTENT = "# STALE-LOCAL-DRAFT\n\nSYNTHETIC-STALE-LOCAL\n"
TAMPERED_CONTENT = "# TAMPERED-LOCAL-ONLY\n\nSYNTHETIC-TAMPERED-WRITEUP-CONTENT\n"

PNG_HEADER = b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def draft_url(cid: str) -> str:
    return f"/api/challenges/{cid}/writeup/draft"


def create_challenge(
    client: TestClient,
    *,
    name: str = "SYNTH_WRITEUP",
    ai_usage_level: str = "A1",
) -> str:
    response = client.post(
        "/api/challenges",
        json={
            "name": name,
            "category": "Misc",
            "description": "synthetic challenge for writeup persistence tests",
            "ai_usage_level": ai_usage_level,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["challenge_id"]


def put_draft(client: TestClient, cid: str, content: str, base_version):
    return client.put(
        draft_url(cid),
        json={"content": content, "base_version": base_version},
    )


def save_ok(
    client: TestClient,
    cid: str,
    content: str,
    base_version: int,
    expected_status: int,
) -> dict:
    response = put_draft(client, cid, content, base_version)
    assert response.status_code == expected_status, response.text
    return response.json()


def sidecar_path(data_root: Path, cid: str) -> Path:
    return data_root / "writeups" / f"{cid}.json"


def read_sidecar(data_root: Path, cid: str) -> dict:
    return json.loads(sidecar_path(data_root, cid).read_text(encoding="utf-8"))


def rewrite_sidecar(data_root: Path, cid: str, payload: dict) -> None:
    sidecar_path(data_root, cid).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def writeup_temp_files(data_root: Path) -> list[str]:
    directory = data_root / "writeups"
    if not directory.is_dir():
        return []
    return sorted(path.name for path in directory.glob(".writeup-*.json.tmp"))


def preview_markdown(client: TestClient, cid: str) -> str:
    response = client.get(f"/api/challenges/{cid}/writeup/preview")
    assert response.status_code == 200, response.text
    return response.json()["markdown"]


def export_members(client: TestClient, cid: str) -> tuple[dict[str, bytes], object]:
    response = client.get(f"/api/challenges/{cid}/export")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].split(";")[0] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    return members, response


def manifest_of(members: dict[str, bytes]) -> dict:
    return json.loads(members["manifest.json"].decode("utf-8"))


def parse_sha256sums(members: dict[str, bytes]) -> dict[str, str]:
    lines = members["SHA256SUMS"].decode("utf-8").splitlines()
    assert lines, "SHA256SUMS must not be empty"
    sums: dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        assert match is not None, f"malformed SHA256SUMS line: {line!r}"
        digest, name = match.group(1), match.group(2)
        assert name not in sums, f"duplicate SHA256SUMS entry: {name!r}"
        sums[name] = digest
    return sums


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
# 1. save and read a human draft
# ---------------------------------------------------------------------------


def test_human_draft_create_read_and_sidecar(
    client: TestClient, data_root: Path
) -> None:
    cid = create_challenge(client)

    missing = client.get(draft_url(cid))
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Writeup draft not found"}

    response = put_draft(client, cid, HUMAN_CONTENT, 0)
    assert response.status_code == 201, response.text
    draft = response.json()
    content_bytes = HUMAN_CONTENT.encode("utf-8")

    assert draft["challenge_id"] == cid
    assert draft["content"] == HUMAN_CONTENT
    assert draft["version"] == 1
    assert draft["sha256"] == sha256_hex(content_bytes)
    assert draft["size"] == len(content_bytes)
    assert draft["is_human_draft"] is True
    assert set(draft) == {
        "challenge_id",
        "content",
        "version",
        "sha256",
        "size",
        "saved_at",
        "is_human_draft",
    }
    # saved_at must be a parseable ISO-8601 timestamp with a UTC offset.
    saved_at = datetime.fromisoformat(draft["saved_at"])
    assert saved_at.tzinfo is not None

    fetched = client.get(draft_url(cid))
    assert fetched.status_code == 200
    assert fetched.json() == draft

    sidecar = read_sidecar(data_root, cid)
    assert sidecar_path(data_root, cid).parent == data_root / "writeups"
    assert sidecar == draft
    assert writeup_temp_files(data_root) == []


# ---------------------------------------------------------------------------
# 2. a new application instance on the same data root recovers the draft
# ---------------------------------------------------------------------------


def test_human_draft_survives_app_restart(data_root: Path) -> None:
    with TestClient(create_app(data_root)) as first:
        cid = create_challenge(first)
        saved = save_ok(first, cid, HUMAN_CONTENT, 0, 201)

    with TestClient(create_app(data_root)) as second:
        response = second.get(draft_url(cid))
        assert response.status_code == 200
        assert response.json() == saved


# ---------------------------------------------------------------------------
# 3. update increments the version and changes the digest
# ---------------------------------------------------------------------------


def test_human_draft_update_increments_version(
    client: TestClient, data_root: Path
) -> None:
    cid = create_challenge(client)
    first = save_ok(client, cid, HUMAN_CONTENT, 0, 201)
    second = save_ok(client, cid, HUMAN_CONTENT_V2, 1, 200)

    assert second["version"] == 2
    assert second["content"] == HUMAN_CONTENT_V2
    assert second["sha256"] == sha256_hex(HUMAN_CONTENT_V2.encode("utf-8"))
    assert second["sha256"] != first["sha256"]
    assert second["size"] == len(HUMAN_CONTENT_V2.encode("utf-8"))

    fetched = client.get(draft_url(cid))
    assert fetched.status_code == 200
    assert fetched.json() == second
    assert read_sidecar(data_root, cid) == second

    # MVP keeps only the latest version: one sidecar, no historical copies.
    json_files = sorted(path.name for path in (data_root / "writeups").glob("*.json"))
    assert json_files == [f"{cid}.json"]
    assert writeup_temp_files(data_root) == []


# ---------------------------------------------------------------------------
# 4. optimistic version conflicts never overwrite the stored draft
# ---------------------------------------------------------------------------


def test_human_draft_version_conflicts_return_latest(client: TestClient) -> None:
    cid = create_challenge(client)
    first = save_ok(client, cid, HUMAN_CONTENT, 0, 201)

    stale_create = put_draft(client, cid, STALE_LOCAL_CONTENT, 0)
    assert stale_create.status_code == 409, stale_create.text
    detail = stale_create.json()["detail"]
    assert detail["message"] == CONFLICT_MESSAGE
    assert detail["current"] == first
    assert client.get(draft_url(cid)).json() == first

    second = save_ok(client, cid, HUMAN_CONTENT_V2, 1, 200)
    stale_update = put_draft(client, cid, STALE_LOCAL_CONTENT, 1)
    assert stale_update.status_code == 409, stale_update.text
    assert stale_update.json()["detail"]["current"] == second
    assert client.get(draft_url(cid)).json() == second


def test_human_draft_conflict_reports_null_when_no_draft(client: TestClient) -> None:
    cid = create_challenge(client)
    response = put_draft(client, cid, HUMAN_CONTENT, 1)
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["message"] == CONFLICT_MESSAGE
    assert detail["current"] is None
    assert client.get(draft_url(cid)).status_code == 404


def test_concurrent_human_draft_creates_exactly_one_winner(
    client: TestClient, data_root: Path
) -> None:
    cid = create_challenge(client)
    barrier = threading.Barrier(2)

    def attempt(content: str):
        barrier.wait(timeout=10)
        return put_draft(client, cid, content, 0)

    contents = ["# SYNTH-WINNER-A\n", "# SYNTH-WINNER-B\n"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = [
            future.result(timeout=30)
            for future in [pool.submit(attempt, content) for content in contents]
        ]

    assert sorted(response.status_code for response in responses) == [201, 409]
    winner = next(r for r in responses if r.status_code == 201).json()
    loser = next(r for r in responses if r.status_code == 409).json()
    assert loser["detail"]["current"] == winner
    assert winner["version"] == 1

    stored = client.get(draft_url(cid))
    assert stored.status_code == 200
    assert stored.json() == winner
    assert read_sidecar(data_root, cid) == winner
    assert [p.name for p in (data_root / "writeups").glob("*.json")] == [f"{cid}.json"]
    assert writeup_temp_files(data_root) == []


# ---------------------------------------------------------------------------
# 5. empty and oversized drafts are refused without touching stored state
# ---------------------------------------------------------------------------


def test_empty_and_whitespace_human_draft_rejected(client: TestClient) -> None:
    cid = create_challenge(client)
    first = save_ok(client, cid, HUMAN_CONTENT, 0, 201)

    for empty in ("", "   ", "\n\t  \r\n"):
        response = put_draft(client, cid, empty, 1)
        assert response.status_code == 422, (empty, response.text)

    assert client.get(draft_url(cid)).json() == first


def test_human_draft_over_byte_limit_rejected(data_root: Path) -> None:
    with TestClient(create_app(data_root, max_writeup_bytes=64)) as client:
        cid = create_challenge(client)
        accepted_content = "a" * 64
        first = save_ok(client, cid, accepted_content, 0, 201)
        assert first["size"] == 64

        rejected = put_draft(client, cid, "a" * 65, 1)
        assert rejected.status_code == 413, rejected.text
        assert client.get(draft_url(cid)).json() == first

        # The limit counts UTF-8 bytes, not characters.
        multibyte_cid = create_challenge(client, name="SYNTH_WRITEUP_UTF8")
        multibyte = "中" * 22
        assert len(multibyte.encode("utf-8")) == 66
        too_large = put_draft(client, multibyte_cid, multibyte, 0)
        assert too_large.status_code == 413, too_large.text
        assert client.get(draft_url(multibyte_cid)).status_code == 404

        assert writeup_temp_files(data_root) == []


def test_default_writeup_limit_is_one_mib(client: TestClient) -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["writeup_max_bytes"] == DEFAULT_MAX_WRITEUP_BYTES


def test_default_writeup_limit_boundary(client: TestClient) -> None:
    cid = create_challenge(client)
    content = "a" * DEFAULT_MAX_WRITEUP_BYTES
    first = save_ok(client, cid, content, 0, 201)
    assert first["size"] == DEFAULT_MAX_WRITEUP_BYTES

    too_large = put_draft(client, cid, "a" * (DEFAULT_MAX_WRITEUP_BYTES + 1), 1)
    assert too_large.status_code == 413, too_large.text
    assert client.get(draft_url(cid)).json() == first


# ---------------------------------------------------------------------------
# 6. strict request validation: base_version types and extra fields
# ---------------------------------------------------------------------------


def test_strict_base_version_and_extra_fields_rejected(
    client: TestClient, data_root: Path
) -> None:
    cid = create_challenge(client)
    invalid_bodies = [
        {"content": "x", "base_version": "0"},
        {"content": "x", "base_version": 0.0},
        {"content": "x", "base_version": True},
        {"content": "x", "base_version": -1},
        {"content": "x", "base_version": 0, "version": 99},
        {"content": "x", "base_version": 0, "sha256": "0" * 64},
        {"content": "x", "base_version": 0, "saved_at": "2026-01-01T00:00:00+00:00"},
        {"content": "x", "base_version": 0, "actor": "agent"},
    ]
    for body in invalid_bodies:
        response = client.put(draft_url(cid), json=body)
        assert response.status_code == 422, (body, response.text)

    # None of the rejected requests may have created a sidecar.
    assert client.get(draft_url(cid)).status_code == 404
    assert not sidecar_path(data_root, cid).exists()

    first = save_ok(client, cid, HUMAN_CONTENT, 0, 201)
    for body in invalid_bodies:
        response = client.put(draft_url(cid), json=body)
        assert response.status_code == 422, (body, response.text)
    assert client.get(draft_url(cid)).json() == first


# ---------------------------------------------------------------------------
# 7. tampered sidecar: read fails loudly, export falls back to the preview
# ---------------------------------------------------------------------------


def _tamper_sidecar_content(data_root: Path, cid: str) -> None:
    sidecar = read_sidecar(data_root, cid)
    sidecar["content"] = TAMPERED_CONTENT
    # Deliberately keep the recorded sha256/size: this is a content-only edit.
    rewrite_sidecar(data_root, cid, sidecar)


def test_tampered_sidecar_get_returns_409_without_content(
    client: TestClient, data_root: Path
) -> None:
    cid = create_challenge(client)
    save_ok(client, cid, HUMAN_CONTENT, 0, 201)
    _tamper_sidecar_content(data_root, cid)

    response = client.get(draft_url(cid))
    assert response.status_code == 409, response.text
    body = response.json()
    assert isinstance(body["detail"], str)
    assert "content" not in body
    assert TAMPERED_CONTENT not in response.text


def test_corrupted_sidecar_json_returns_409(
    client: TestClient, data_root: Path
) -> None:
    cid = create_challenge(client)
    save_ok(client, cid, HUMAN_CONTENT, 0, 201)
    sidecar_path(data_root, cid).write_text("{not valid json", encoding="utf-8")

    response = client.get(draft_url(cid))
    assert response.status_code == 409, response.text
    assert isinstance(response.json()["detail"], str)
    assert HUMAN_CONTENT not in response.text


def test_tampered_sidecar_export_falls_back_to_generated(
    client: TestClient, data_root: Path
) -> None:
    cid = create_challenge(client)
    save_ok(client, cid, HUMAN_CONTENT, 0, 201)
    _tamper_sidecar_content(data_root, cid)

    assert client.get(draft_url(cid)).status_code == 409
    markdown = preview_markdown(client, cid)
    members, response = export_members(client, cid)

    assert response.headers["X-Dossier-Completeness"] == "incomplete"
    writeup = manifest_of(members)["writeup"]
    assert writeup["final_source"] == "generated"
    assert writeup["human"] is None
    assert isinstance(writeup["integrity_error"], str)
    assert writeup["integrity_error"]

    final = members["writeup.md"]
    assert final.startswith(INTEGRITY_FALLBACK_NOTE.encode("utf-8"))
    assert members["writeup_generated.md"] == markdown.encode("utf-8")
    assert TAMPERED_CONTENT not in final.decode("utf-8")
    assert "INCOMPLETE.txt" in members
    assert writeup["final_sha256"] == sha256_hex(final)
    assert writeup["final_size"] == len(final)


# ---------------------------------------------------------------------------
# 8. export: byte-exact final writeup, generated preview, and manifest fields
# ---------------------------------------------------------------------------


def test_export_writeup_is_byte_exact_human_draft(client: TestClient) -> None:
    cid = create_challenge(client)
    save_ok(client, cid, HUMAN_CONTENT, 0, 201)
    saved = save_ok(client, cid, HUMAN_CONTENT_V2, 1, 200)
    markdown = preview_markdown(client, cid)

    members, _response = export_members(client, cid)
    assert "writeup.md" in members
    assert "writeup_generated.md" in members
    final = members["writeup.md"]
    generated = members["writeup_generated.md"]
    # The export carries the latest saved version, byte for byte.
    assert final == HUMAN_CONTENT_V2.encode("utf-8")
    assert generated == markdown.encode("utf-8")

    writeup = manifest_of(members)["writeup"]
    assert writeup["final_source"] == "human"
    assert writeup["human"] == {
        "version": saved["version"],
        "sha256": saved["sha256"],
        "size": saved["size"],
        "saved_at": saved["saved_at"],
    }
    assert writeup["final_sha256"] == sha256_hex(final)
    assert writeup["final_size"] == len(final)
    assert writeup["generated"]["sha256"] == sha256_hex(generated)
    assert writeup["generated"]["size"] == len(generated)
    assert writeup["integrity_error"] is None


# ---------------------------------------------------------------------------
# 9. export without a human draft: generated fallback and legacy compatibility
# ---------------------------------------------------------------------------


def test_export_without_human_draft_uses_generated_writeup(
    client: TestClient,
) -> None:
    cid = create_challenge(client, name="SYNTH_LEGACY")
    note = client.post(
        f"/api/challenges/{cid}/notes", json={"text": "SYNTH-LEGACY-NOTE"}
    )
    assert note.status_code == 201
    artifact = client.post(
        f"/api/challenges/{cid}/artifacts",
        files={
            "file": (
                "synthetic_evidence.png",
                PNG_HEADER + b"SYNTHETIC-LEGACY-EVIDENCE",
                "image/png",
            )
        },
        data={"evidence_kind": "analysis"},
    )
    assert artifact.status_code == 201

    events_before = client.get(f"/api/challenges/{cid}/events").json()
    artifacts_before = client.get(f"/api/challenges/{cid}/artifacts").json()

    # A challenge that predates human drafts: no draft exists yet.
    assert client.get(draft_url(cid)).status_code == 404

    markdown = preview_markdown(client, cid)
    members, _response = export_members(client, cid)
    final = members["writeup.md"]
    assert final == (NO_HUMAN_NOTE + markdown).encode("utf-8")
    assert members["writeup_generated.md"] == markdown.encode("utf-8")

    writeup = manifest_of(members)["writeup"]
    assert writeup["final_source"] == "generated"
    assert writeup["human"] is None
    assert writeup["integrity_error"] is None
    assert writeup["final_sha256"] == sha256_hex(final)
    assert writeup["final_size"] == len(final)

    # Recording/exporting evidence is unchanged by this feature.
    assert client.get(f"/api/challenges/{cid}/events").json() == events_before
    assert client.get(f"/api/challenges/{cid}/artifacts").json() == artifacts_before
    manifest = manifest_of(members)
    assert json.loads(members["logs/events.json"].decode("utf-8")) == events_before
    assert manifest["counts"]["events"] == len(events_before)
    assert manifest["counts"]["artifacts"] == len(artifacts_before)
    assert any(name.startswith("evidence/") for name in members)
    assert client.get(draft_url(cid)).status_code == 404


# ---------------------------------------------------------------------------
# 10. SHA256SUMS covers every delivered file, including both writeups
# ---------------------------------------------------------------------------


def test_export_sha256sums_cover_every_delivered_file(client: TestClient) -> None:
    cid = create_challenge(client)
    save_ok(client, cid, HUMAN_CONTENT, 0, 201)
    members, _response = export_members(client, cid)

    sums = parse_sha256sums(members)
    assert set(sums) == set(members) - {"SHA256SUMS"}
    assert "SHA256SUMS" not in sums
    assert "writeup.md" in sums
    assert "writeup_generated.md" in sums
    for name, digest in sums.items():
        assert digest == sha256_hex(members[name]), name


# ---------------------------------------------------------------------------
# 11. saving/reading drafts never pollutes the event chain
# ---------------------------------------------------------------------------


def test_writeup_draft_operations_do_not_pollute_events(client: TestClient) -> None:
    cid = create_challenge(client)
    note = client.post(
        f"/api/challenges/{cid}/notes", json={"text": "SYNTH-DRAFT-NOTE"}
    )
    assert note.status_code == 201
    artifact = client.post(
        f"/api/challenges/{cid}/artifacts",
        files={
            "file": (
                "synthetic_draft_evidence.png",
                PNG_HEADER + b"SYNTHETIC-DRAFT-EVIDENCE",
                "image/png",
            )
        },
        data={"evidence_kind": "execution"},
    )
    assert artifact.status_code == 201

    events_before = client.get(f"/api/challenges/{cid}/events").json()
    integrity_before = client.get(f"/api/challenges/{cid}/integrity").json()
    artifacts_before = client.get(f"/api/challenges/{cid}/artifacts").json()
    assert integrity_before == {"valid": True, "earliest_affected_sequence": None}

    save_ok(client, cid, HUMAN_CONTENT, 0, 201)
    assert client.get(draft_url(cid)).status_code == 200
    save_ok(client, cid, HUMAN_CONTENT_V2, 1, 200)
    assert client.get(draft_url(cid)).status_code == 200

    events_after = client.get(f"/api/challenges/{cid}/events").json()
    assert events_after == events_before
    assert client.get(f"/api/challenges/{cid}/integrity").json() == integrity_before
    assert client.get(f"/api/challenges/{cid}/artifacts").json() == artifacts_before

    event_types = {event["event_type"] for event in events_after}
    assert "tool_started" not in event_types
    assert "tool_finished" not in event_types


# ---------------------------------------------------------------------------
# 12. request body limits: declared Content-Length and chunked transports
# ---------------------------------------------------------------------------


def test_declared_content_length_over_request_limit_returns_413(
    data_root: Path,
) -> None:
    with TestClient(create_app(data_root, max_writeup_bytes=32)) as client:
        cid = create_challenge(client)
        oversized = b"x" * (32 + WRITEUP_JSON_OVERHEAD_BYTES + 1024)
        response = client.put(
            draft_url(cid),
            content=oversized,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413, response.text
        assert client.get(draft_url(cid)).status_code == 404


def test_chunked_writeup_body_over_limit_returns_413(data_root: Path) -> None:
    # No Content-Length: the server must count the bytes it actually receives
    # and answer 413 (per docs/MVP_BACKEND.md), not let JSON parsing fail first.
    with TestClient(create_app(data_root, max_writeup_bytes=32)) as client:
        cid = create_challenge(client)
        chunks = (b"x" * 8192 for _ in range(25))  # ~200 KiB, limit is 32 + 64 KiB
        response = client.put(
            draft_url(cid),
            content=chunks,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413, response.text
        assert client.get(draft_url(cid)).status_code == 404


# ---------------------------------------------------------------------------
# 13. old localStorage-style draft: explicit migration, no silent overwrite
# ---------------------------------------------------------------------------


def test_legacy_local_draft_migrates_only_with_explicit_base_version(
    client: TestClient,
) -> None:
    cid = create_challenge(client)

    # Server has no draft: the frontend must keep its local draft for migration.
    assert client.get(draft_url(cid)).status_code == 404

    migrated = save_ok(client, cid, HUMAN_CONTENT, 0, 201)
    assert migrated["version"] == 1

    # A second attempt with the same stale base_version is rejected, and the
    # response exposes the server draft so the client can show the conflict.
    conflict = put_draft(client, cid, STALE_LOCAL_CONTENT, 0)
    assert conflict.status_code == 409, conflict.text
    detail = conflict.json()["detail"]
    assert detail["message"] == CONFLICT_MESSAGE
    assert detail["current"] == migrated
    assert detail["current"]["content"] == HUMAN_CONTENT

    fetched = client.get(draft_url(cid))
    assert fetched.status_code == 200
    assert fetched.json() == migrated

    members, _response = export_members(client, cid)
    assert members["writeup.md"] == HUMAN_CONTENT.encode("utf-8")
    assert STALE_LOCAL_CONTENT.encode("utf-8") not in members["writeup.md"]


# ---------------------------------------------------------------------------
# 14. atomic writes: no temp leftovers, a failed concurrent save is harmless
# ---------------------------------------------------------------------------


def test_failed_concurrent_update_preserves_existing_sidecar(
    client: TestClient, data_root: Path
) -> None:
    cid = create_challenge(client)
    save_ok(client, cid, HUMAN_CONTENT, 0, 201)
    barrier = threading.Barrier(2)

    def attempt(content: str):
        barrier.wait(timeout=10)
        return put_draft(client, cid, content, 1)

    contents = [HUMAN_CONTENT_V2, "# SYNTH-OTHER-UPDATE\n"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = [
            future.result(timeout=30)
            for future in [pool.submit(attempt, content) for content in contents]
        ]

    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(r for r in responses if r.status_code == 200).json()
    stored = client.get(draft_url(cid))
    assert stored.status_code == 200
    assert stored.json() == winner
    assert stored.json()["version"] == 2

    sidecar = read_sidecar(data_root, cid)
    assert sidecar == stored.json()
    assert sidecar["version"] == 2
    assert writeup_temp_files(data_root) == []
    assert [p.name for p in (data_root / "writeups").glob("*.json")] == [f"{cid}.json"]


# ---------------------------------------------------------------------------
# extra: unknown challenge ids are rejected uniformly
# ---------------------------------------------------------------------------


def test_unknown_challenge_writeup_endpoints_return_404(client: TestClient) -> None:
    cid = str(uuid4())
    assert client.get(draft_url(cid)).status_code == 404
    assert put_draft(client, cid, HUMAN_CONTENT, 0).status_code == 404
    assert client.get(f"/api/challenges/{cid}/export").status_code == 404
