"""Regression tests for the PR #7 independent review fixes.

Covers the four fix points from the independent review of the MVP backend
workflow:

* P1-1 imported-file read integrity (never serve modified/truncated bytes);
* P1-2 manifest self-check plus ``challenge_imported`` event binding;
* P1-3 exporting every imported archive and its extracted files;
* P2-1 Writeup completeness requiring real evidence, not substitutes.

Every byte used here is synthetic and assembled inside this module: hand-built
ZIP archives, plain text, and PNG magic headers.  No real competition material,
flag, or target is used.  Each test isolates its data root with ``tmp_path``.

The suite must pass on Windows locally and on Linux CI (Python 3.11).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sqlite3
import zipfile
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

PNG_HEADER = b"\x89PNG\r\n\x1a\n"

MISSING_APPROACH = "[待选手补充：核心解题思路]"
MISSING_CODE = "[证据缺失：尚未上传核心代码或脚本]"
MISSING_EXECUTION = "[证据缺失：尚无运行截图或执行输出证据]"

FILE_INTEGRITY_DETAIL = "Imported file failed its integrity check"
INTEGRITY_HEADER = "x-imported-file-integrity"
COMPLETENESS_HEADER = "x-dossier-completeness"

PROJECT_NAME = "SYNTH-REVIEW-PROJECT"
CHALLENGE_NAME = "SYNTH-REVIEW-CHALLENGE"
ORDINARY_NOTE_TEXT = "SYNTH-ORDINARY-NOTE: 普通笔记不能冒充核心解题思路"
APPROACH_TEXT = "SYNTH-APPROACH: 由合成样本推导出的核心思路"
COMMAND_TEXT = "python solve.py --synthetic-review"
RESULT_TEXT = "SYNTH-RESULT: 合成执行输出符合预期"
WORKING_DIRECTORY = "C:/synthetic/review-workspace"

FIRST_IMPORT_FILES = {
    "a.txt": b"SYNTHETIC-IMPORT-ONE-A\n",
    "dir/b.py": b"print('SYNTHETIC-IMPORT-ONE-B')\n",
}
SECOND_IMPORT_FILES = {"c.txt": b"SYNTHETIC-IMPORT-TWO-C\n"}

SOURCE_CODE_BYTES = b"def solve():\n    return 'SYNTHETIC_SOURCE_CODE'\n"
EXECUTION_BYTES = PNG_HEADER + b"SYNTHETIC-EXECUTION-EVIDENCE"
FLAG_CAPTURE_BYTES = PNG_HEADER + b"SYNTHETIC-FLAG-CAPTURE-EVIDENCE"
PLATFORM_BYTES = PNG_HEADER + b"SYNTHETIC-PLATFORM-VERIFICATION-EVIDENCE"

_ENV_NAMES = (
    "CTF_DATA_DIR",
    "CTF_MAX_ARTIFACT_BYTES",
    "CTF_RULES_MAX_BYTES",
    "CTF_IMPORT_MAX_FILES",
    "CTF_IMPORT_MAX_FILE_BYTES",
    "CTF_IMPORT_MAX_TOTAL_BYTES",
    "CTF_IMPORT_MAX_COMPRESSION_RATIO",
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_ctf_environment(monkeypatch):
    """Keep every test independent of an ambient CTF_* configuration."""
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def client(data_root: Path):
    with TestClient(create_app(data_root)) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# helpers (synthetic data only)
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def put_project(client: TestClient) -> dict:
    response = client.put("/api/project", json={"project_name": PROJECT_NAME})
    assert response.status_code == 200
    return response.json()


def create_challenge(
    client: TestClient,
    *,
    name: str = CHALLENGE_NAME,
    ai_usage_level: str = "A2",
) -> str:
    response = client.post(
        "/api/challenges",
        json={"name": name, "category": "Misc", "ai_usage_level": ai_usage_level},
    )
    assert response.status_code == 201
    return response.json()["challenge_id"]


def upload_import(
    client: TestClient,
    cid: str,
    payload: bytes,
    *,
    filename: str,
) -> dict:
    response = client.post(
        f"/api/challenges/{cid}/imports",
        files={"file": (filename, payload, "application/zip")},
    )
    assert response.status_code == 201
    return response.json()


def import_url(cid: str, import_id: str) -> str:
    return f"/api/challenges/{cid}/imports/{import_id}"


def import_file_url(cid: str, import_id: str, relative_path: str) -> str:
    encoded = quote(relative_path, safe="/")
    return f"{import_url(cid, import_id)}/files/{encoded}"


def installed_import_dir(data_root: Path, cid: str, import_id: str) -> Path:
    return data_root / "challenges" / cid / "imports" / import_id


def extracted_path(
    data_root: Path, cid: str, import_id: str, relative_path: str
) -> Path:
    return installed_import_dir(data_root, cid, import_id).joinpath(
        *relative_path.split("/")
    )


def manifest_path(data_root: Path, cid: str, import_id: str) -> Path:
    return installed_import_dir(data_root, cid, import_id) / "manifest.json"


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_bytes().decode("utf-8"))


def canonical_bytes(payload: dict) -> bytes:
    """Serialise a manifest exactly as the implementation stores it."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def manifest_digest(manifest: dict) -> str:
    """Recompute manifest_sha256 with the documented canonical algorithm."""
    basis = dict(manifest)
    basis["manifest_sha256"] = ""
    return sha256_hex(canonical_bytes(basis))


def rehash_manifest(manifest: dict) -> dict:
    manifest["manifest_sha256"] = manifest_digest(manifest)
    return manifest


def upload_artifact(
    client: TestClient,
    cid: str,
    *,
    filename: str,
    data: bytes,
    evidence_kind: str | None = None,
) -> dict:
    form: dict[str, str] = {}
    if evidence_kind is not None:
        form["evidence_kind"] = evidence_kind
    response = client.post(
        f"/api/challenges/{cid}/artifacts",
        files={"file": (filename, data, "application/octet-stream")},
        data=form,
    )
    assert response.status_code == 201
    return response.json()


def add_note(
    client: TestClient, cid: str, text: str, *, kind: str | None = None
) -> dict:
    payload: dict[str, object] = {"text": text}
    if kind is not None:
        payload["kind"] = kind
    response = client.post(f"/api/challenges/{cid}/notes", json=payload)
    assert response.status_code == 201
    return response.json()


def add_manual_operation(client: TestClient, cid: str) -> dict:
    response = client.post(
        f"/api/challenges/{cid}/manual-operations",
        json={
            "command": COMMAND_TEXT,
            "working_directory": WORKING_DIRECTORY,
            "purpose": "synthetic review verification",
            "exit_code": 0,
            "result_note": RESULT_TEXT,
        },
    )
    assert response.status_code == 201
    return response.json()


def preview(client: TestClient, cid: str) -> dict:
    response = client.get(f"/api/challenges/{cid}/writeup/preview")
    assert response.status_code == 200
    return response.json()


def markdown_section(markdown: str, heading: str, next_heading: str) -> str:
    start = markdown.index(heading)
    end = markdown.index(next_heading, start)
    return markdown[start:end]


def export_members(client: TestClient, cid: str) -> tuple:
    response = client.get(f"/api/challenges/{cid}/export")
    assert response.status_code == 200
    assert response.headers["content-type"].split(";")[0] == "application/zip"
    # Materialise the archive before the FileResponse background task cleans up.
    content = response.content
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    return response, members


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


def find_import_record(records: list[dict], import_id: str) -> dict:
    matches = [record for record in records if record["import_id"] == import_id]
    assert len(matches) == 1, records
    return matches[0]


def import_status_entries(members: dict[str, bytes]) -> dict[str, dict]:
    payload = json.loads(members["manifest.json"])
    return {entry["import_id"]: entry for entry in payload["imports"]}


def build_two_imports(client: TestClient, cid: str) -> dict:
    first_bytes = make_zip(FIRST_IMPORT_FILES)
    second_bytes = make_zip(SECOND_IMPORT_FILES)
    first = upload_import(client, cid, first_bytes, filename="first.zip")
    second = upload_import(client, cid, second_bytes, filename="second.zip")
    return {
        "first_bytes": first_bytes,
        "first": first,
        "second_bytes": second_bytes,
        "second": second,
    }


def tamper_first_event(data_root: Path, cid: str) -> None:
    """Rewrite one persisted event body without recomputing its hash."""
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
        body["payload"]["synthetic_tamper"] = "review-fixes"
        connection.execute(
            "UPDATE events SET body=? WHERE event_id=?",
            (json.dumps(body), event_id),
        )
        connection.commit()
    finally:
        connection.close()


def build_complete_dossier(client: TestClient) -> dict:
    """A complete synthetically recorded dossier for Writeup completeness."""
    put_project(client)
    cid = create_challenge(client, ai_usage_level="A2")
    imported = upload_import(
        client, cid, make_zip(FIRST_IMPORT_FILES), filename="synthetic.zip"
    )
    approach = add_note(client, cid, APPROACH_TEXT, kind="approach")
    manual = add_manual_operation(client, cid)
    artifacts = {
        "source_code": upload_artifact(
            client,
            cid,
            filename="solve.py",
            data=SOURCE_CODE_BYTES,
            evidence_kind="source_code",
        ),
        "execution": upload_artifact(
            client,
            cid,
            filename="execution.png",
            data=EXECUTION_BYTES,
            evidence_kind="execution",
        ),
        "flag_capture": upload_artifact(
            client,
            cid,
            filename="flag_capture.png",
            data=FLAG_CAPTURE_BYTES,
            evidence_kind="flag_capture",
        ),
        "platform_verification": upload_artifact(
            client,
            cid,
            filename="platform_verification.png",
            data=PLATFORM_BYTES,
            evidence_kind="platform_verification",
        ),
    }
    return {
        "cid": cid,
        "import": imported,
        "approach": approach,
        "manual": manual,
        "artifacts": artifacts,
    }


# ---------------------------------------------------------------------------
# P1-1 imported-file read integrity
# ---------------------------------------------------------------------------


def test_p1_1_imported_file_download_is_integrity_verified(
    client: TestClient,
) -> None:
    cid = create_challenge(client)
    payload = make_zip(
        {
            "a.txt": b"SYNTHETIC-ALPHA\n",
            "dir/b.py": b"print('SYNTHETIC-B')\n",
        }
    )
    result = upload_import(client, cid, payload, filename="synthetic.zip")

    response = client.get(import_file_url(cid, result["import_id"], "a.txt"))
    assert response.status_code == 200
    assert response.content == b"SYNTHETIC-ALPHA\n"
    assert response.headers[INTEGRITY_HEADER] == "sha256-verified"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "inline" in response.headers["content-disposition"]

    # A '/'-containing relative path is served through the catch-all route.
    nested = client.get(import_file_url(cid, result["import_id"], "dir/b.py"))
    assert nested.status_code == 200
    assert nested.content == b"print('SYNTHETIC-B')\n"


def test_p1_1_same_size_tamper_returns_409(client: TestClient, data_root: Path) -> None:
    cid = create_challenge(client)
    original = b"SYNTHETIC-ALPHA"
    tampered = b"SYNTHETIC-BRAVO"
    assert len(original) == len(tampered)
    payload = make_zip({"a.txt": original, "sibling.txt": b"SYNTHETIC-SIBLING-BYTES"})
    result = upload_import(client, cid, payload, filename="synthetic.zip")

    extracted_path(data_root, cid, result["import_id"], "a.txt").write_bytes(tampered)
    response = client.get(import_file_url(cid, result["import_id"], "a.txt"))
    assert response.status_code == 409
    assert response.json()["detail"] == FILE_INTEGRITY_DETAIL
    assert tampered not in response.content

    # An untouched file in the same directory is still served.
    sibling = client.get(import_file_url(cid, result["import_id"], "sibling.txt"))
    assert sibling.status_code == 200
    assert sibling.content == b"SYNTHETIC-SIBLING-BYTES"


def test_p1_1_truncated_file_returns_409(client: TestClient, data_root: Path) -> None:
    cid = create_challenge(client)
    original = b"SYNTHETIC-TRUNCATE-ME"
    payload = make_zip({"a.txt": original})
    result = upload_import(client, cid, payload, filename="synthetic.zip")

    extracted_path(data_root, cid, result["import_id"], "a.txt").write_bytes(
        original[:-1]
    )
    response = client.get(import_file_url(cid, result["import_id"], "a.txt"))
    assert response.status_code == 409
    assert response.json()["detail"] == FILE_INTEGRITY_DETAIL
    assert original[:-1] not in response.content


def test_p1_1_replaced_with_larger_file_returns_409(
    client: TestClient, data_root: Path
) -> None:
    cid = create_challenge(client)
    original = b"SYNTHETIC-ORIGINAL"
    replacement = b"SYNTHETIC-REPLACEMENT-WITH-MORE-BYTES"
    payload = make_zip({"a.txt": original})
    result = upload_import(client, cid, payload, filename="synthetic.zip")

    extracted_path(data_root, cid, result["import_id"], "a.txt").write_bytes(
        replacement
    )
    response = client.get(import_file_url(cid, result["import_id"], "a.txt"))
    assert response.status_code == 409
    assert response.json()["detail"] == FILE_INTEGRITY_DETAIL
    assert replacement not in response.content


def test_p1_1_untrusted_manifest_blocks_file_download(
    client: TestClient, data_root: Path
) -> None:
    cid = create_challenge(client)
    secret = b"SYNTHETIC-SECRET-BYTES"
    payload = make_zip({"secret.txt": secret})
    result = upload_import(client, cid, payload, filename="synthetic.zip")

    path = manifest_path(data_root, cid, result["import_id"])
    manifest = load_manifest(path)
    manifest["files"][0]["sha256"] = sha256_hex(b"different-bytes")
    path.write_bytes(canonical_bytes(manifest))

    response = client.get(import_file_url(cid, result["import_id"], "secret.txt"))
    assert response.status_code == 409
    assert secret not in response.content


# ---------------------------------------------------------------------------
# P1-2 manifest self-check and event binding
# ---------------------------------------------------------------------------


def test_p1_2_verified_import_is_listed_and_readable(
    client: TestClient,
) -> None:
    cid = create_challenge(client)
    payload = make_zip(FIRST_IMPORT_FILES)
    result = upload_import(client, cid, payload, filename="synthetic.zip")

    listing = client.get(f"/api/challenges/{cid}/imports")
    assert listing.status_code == 200
    records = listing.json()
    assert len(records) == 1
    record = records[0]
    assert record["import_id"] == result["import_id"]
    assert record["manifest_verified"] is True
    assert record["integrity_error"] is None

    detail = client.get(import_url(cid, result["import_id"]))
    assert detail.status_code == 200
    body = detail.json()
    assert body["manifest_verified"] is True
    assert body["integrity_error"] is None
    assert body["files"] == result["files"]
    assert client.get(f"/api/challenges/{cid}/integrity").json()["valid"] is True


def test_p1_2_manifest_self_checksum_tamper_marks_import_unverified(
    client: TestClient, data_root: Path
) -> None:
    cid = create_challenge(client)
    payload = make_zip(FIRST_IMPORT_FILES)
    result = upload_import(client, cid, payload, filename="synthetic.zip")

    # Change a file digest but keep the stored manifest digest stale.
    path = manifest_path(data_root, cid, result["import_id"])
    manifest = load_manifest(path)
    manifest["files"][0]["sha256"] = sha256_hex(b"tampered-file-bytes")
    path.write_bytes(canonical_bytes(manifest))

    listing = client.get(f"/api/challenges/{cid}/imports")
    assert listing.status_code == 200
    record = find_import_record(listing.json(), result["import_id"])
    assert record["manifest_verified"] is False
    assert record["integrity_error"]
    assert "Manifest" in record["integrity_error"]

    assert client.get(import_url(cid, result["import_id"])).status_code == 409
    assert (
        client.get(import_file_url(cid, result["import_id"], "a.txt")).status_code
        == 409
    )

    response, members = export_members(client, cid)
    assert response.headers[COMPLETENESS_HEADER] == "incomplete"
    assert "INCOMPLETE.txt" in members
    payload = json.loads(members["manifest.json"])
    assert payload["counts"]["imports"] == 1
    assert payload["completeness"] == "incomplete"
    entry = payload["imports"][0]
    assert entry["import_id"] == result["import_id"]
    assert entry["status"] == "unverified"
    assert entry["error"]
    prefix = f"challenge/imports/{result['import_id']}/"
    assert not any(name.startswith(prefix) for name in members)


def test_p1_2_rehashed_manifest_still_fails_event_binding(
    client: TestClient, data_root: Path
) -> None:
    cid = create_challenge(client)
    payload = make_zip(FIRST_IMPORT_FILES)
    result = upload_import(client, cid, payload, filename="synthetic.zip")

    # A self-consistent manifest whose digest was recomputed after tampering.
    path = manifest_path(data_root, cid, result["import_id"])
    manifest = load_manifest(path)
    manifest["files"][0]["sha256"] = sha256_hex(b"self-consistent-tamper")
    rehash_manifest(manifest)
    path.write_bytes(canonical_bytes(manifest))

    stored = load_manifest(path)
    assert stored["manifest_sha256"] == manifest_digest(stored)

    listing = client.get(f"/api/challenges/{cid}/imports")
    assert listing.status_code == 200
    record = find_import_record(listing.json(), result["import_id"])
    assert record["manifest_verified"] is False
    assert record["integrity_error"]
    assert "manifest_sha256" in record["integrity_error"]

    detail = client.get(import_url(cid, result["import_id"]))
    assert detail.status_code == 409
    assert "manifest_sha256" in detail.json()["detail"]
    assert (
        client.get(import_file_url(cid, result["import_id"], "a.txt")).status_code
        == 409
    )


def test_p1_2_missing_manifest_marks_import_unverified(
    client: TestClient, data_root: Path
) -> None:
    cid = create_challenge(client)
    payload = make_zip(FIRST_IMPORT_FILES)
    result = upload_import(client, cid, payload, filename="synthetic.zip")
    manifest_path(data_root, cid, result["import_id"]).unlink()

    listing = client.get(f"/api/challenges/{cid}/imports")
    assert listing.status_code == 200
    record = find_import_record(listing.json(), result["import_id"])
    assert record["manifest_verified"] is False
    assert record["integrity_error"]

    assert client.get(import_url(cid, result["import_id"])).status_code == 409

    response, members = export_members(client, cid)
    assert response.headers[COMPLETENESS_HEADER] == "incomplete"
    payload = json.loads(members["manifest.json"])
    entry = payload["imports"][0]
    assert entry["import_id"] == result["import_id"]
    assert entry["status"] == "unverified"
    assert entry["error"]


@pytest.mark.parametrize(
    ("field", "value", "fragment"),
    [
        (
            "challenge_id",
            "00000000-0000-0000-0000-00000000c1d0",
            "another challenge",
        ),
        (
            "original_artifact_id",
            "00000000-0000-0000-0000-00000000a71d",
            "original_artifact_id",
        ),
        (
            "import_id",
            "00000000-0000-0000-0000-000000001d1d",
            "not bound",
        ),
    ],
)
def test_p1_2_manifest_event_field_mismatch_is_untrusted(
    client: TestClient,
    data_root: Path,
    field: str,
    value: str,
    fragment: str,
) -> None:
    cid = create_challenge(client)
    payload = make_zip(FIRST_IMPORT_FILES)
    result = upload_import(client, cid, payload, filename="synthetic.zip")

    # Change one binding field and recompute the manifest's own digest so only
    # the event can expose the mismatch.
    path = manifest_path(data_root, cid, result["import_id"])
    manifest = load_manifest(path)
    manifest[field] = value
    rehash_manifest(manifest)
    path.write_bytes(canonical_bytes(manifest))

    listing = client.get(f"/api/challenges/{cid}/imports")
    assert listing.status_code == 200
    record = find_import_record(listing.json(), result["import_id"])
    assert record["manifest_verified"] is False
    assert record["integrity_error"]
    assert fragment in record["integrity_error"]

    assert client.get(import_url(cid, result["import_id"])).status_code == 409
    assert (
        client.get(import_file_url(cid, result["import_id"], "a.txt")).status_code
        == 409
    )


def test_p1_2_tampered_event_chain_blocks_import_reads(
    client: TestClient, data_root: Path
) -> None:
    cid = create_challenge(client)
    payload = make_zip(FIRST_IMPORT_FILES)
    result = upload_import(client, cid, payload, filename="synthetic.zip")
    original = FIRST_IMPORT_FILES["a.txt"]
    tamper_first_event(data_root, cid)

    assert client.get(f"/api/challenges/{cid}/integrity").json()["valid"] is False

    listing = client.get(f"/api/challenges/{cid}/imports")
    assert listing.status_code == 409
    assert client.get(import_url(cid, result["import_id"])).status_code == 409
    file_response = client.get(import_file_url(cid, result["import_id"], "a.txt"))
    assert file_response.status_code == 409
    assert original not in file_response.content


# ---------------------------------------------------------------------------
# P1-3 export every import
# ---------------------------------------------------------------------------


def test_p1_3_export_includes_every_import(client: TestClient) -> None:
    cid = create_challenge(client)
    ctx = build_two_imports(client, cid)
    _response, members = export_members(client, cid)

    for label, files in (
        ("first", FIRST_IMPORT_FILES),
        ("second", SECOND_IMPORT_FILES),
    ):
        result = ctx[label]
        prefix = f"challenge/imports/{result['import_id']}"
        original = members[f"{prefix}/original.zip"]
        assert original == ctx[f"{label}_bytes"]
        assert sha256_hex(original) == result["original_artifact"]["sha256"]
        for relative, data in files.items():
            assert members[f"{prefix}/extracted/{relative}"] == data


def test_p1_3_export_manifest_lists_every_import(client: TestClient) -> None:
    cid = create_challenge(client)
    ctx = build_two_imports(client, cid)
    _response, members = export_members(client, cid)

    payload = json.loads(members["manifest.json"])
    assert payload["counts"]["imports"] == 2
    entries = {entry["import_id"]: entry for entry in payload["imports"]}
    assert set(entries) == {
        ctx["first"]["import_id"],
        ctx["second"]["import_id"],
    }

    for label in ("first", "second"):
        result = ctx[label]
        entry = entries[result["import_id"]]
        for field in ("status", "exported_file_count", "missing_files", "error"):
            assert field in entry
        assert entry["status"] == "exported"
        assert entry["missing_files"] == []
        assert entry["error"] is None
        assert entry["exported_file_count"] == 1 + len(result["files"])


def test_p1_3_sha256sums_cover_every_import_deliverable(
    client: TestClient,
) -> None:
    cid = create_challenge(client)
    ctx = build_two_imports(client, cid)
    _response, members = export_members(client, cid)

    sums = parse_sha256sums(members)
    assert set(sums) == set(members) - {"SHA256SUMS"}
    for name, expected in sums.items():
        assert sha256_hex(members[name]) == expected, name

    for label, files in (
        ("first", FIRST_IMPORT_FILES),
        ("second", SECOND_IMPORT_FILES),
    ):
        result = ctx[label]
        prefix = f"challenge/imports/{result['import_id']}"
        assert f"{prefix}/original.zip" in sums
        for relative in files:
            assert f"{prefix}/extracted/{relative}" in sums


def test_p1_3_tampered_import_is_exported_as_incomplete(
    client: TestClient, data_root: Path
) -> None:
    cid = create_challenge(client)
    ctx = build_two_imports(client, cid)
    second = ctx["second"]
    extracted_path(data_root, cid, second["import_id"], "c.txt").write_bytes(
        b"SYNTHETIC-TAMPERED-C\n"
    )

    response, members = export_members(client, cid)
    assert response.headers[COMPLETENESS_HEADER] == "incomplete"
    payload = json.loads(members["manifest.json"])
    assert payload["completeness"] == "incomplete"
    assert "INCOMPLETE.txt" in members

    entries = import_status_entries(members)
    assert entries[ctx["first"]["import_id"]]["status"] == "exported"
    second_entry = entries[second["import_id"]]
    assert second_entry["status"] == "incomplete"
    assert second_entry["missing_files"]
    assert f"challenge/imports/{second['import_id']}/extracted/c.txt" not in members
    assert f"challenge/imports/{second['import_id']}/original.zip" in members


def test_p1_3_missing_import_file_is_exported_as_incomplete(
    client: TestClient, data_root: Path
) -> None:
    cid = create_challenge(client)
    ctx = build_two_imports(client, cid)
    second = ctx["second"]
    os.remove(extracted_path(data_root, cid, second["import_id"], "c.txt"))

    response, members = export_members(client, cid)
    assert response.headers[COMPLETENESS_HEADER] == "incomplete"
    payload = json.loads(members["manifest.json"])
    assert payload["completeness"] == "incomplete"

    entries = import_status_entries(members)
    assert entries[ctx["first"]["import_id"]]["status"] == "exported"
    second_entry = entries[second["import_id"]]
    assert second_entry["status"] == "incomplete"
    assert second_entry["missing_files"]
    assert f"challenge/imports/{second['import_id']}/extracted/c.txt" not in members


# ---------------------------------------------------------------------------
# P2-1 Writeup completeness requires real evidence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", [None, "note"])
def test_p2_1_ordinary_note_is_not_core_approach(
    client: TestClient, kind: str | None
) -> None:
    cid = create_challenge(client, ai_usage_level="A2")
    add_note(client, cid, ORDINARY_NOTE_TEXT, kind=kind)

    body = preview(client, cid)
    assert "core_approach" in body["missing_requirements"]
    markdown = body["markdown"]

    approach_section = markdown_section(markdown, "## 2. 解题思路", "## 3. 关键操作")
    assert MISSING_APPROACH in approach_section
    assert ORDINARY_NOTE_TEXT not in approach_section

    notes_section = markdown_section(markdown, "## 3. 关键操作", "## 4. 核心代码")
    assert "其他人工笔记" in notes_section
    assert ORDINARY_NOTE_TEXT in notes_section


def test_p2_1_approach_note_satisfies_core_approach(
    client: TestClient,
) -> None:
    cid = create_challenge(client, ai_usage_level="A2")
    add_note(client, cid, APPROACH_TEXT, kind="approach")

    body = preview(client, cid)
    assert "core_approach" not in body["missing_requirements"]
    markdown = body["markdown"]
    approach_section = markdown_section(markdown, "## 2. 解题思路", "## 3. 关键操作")
    assert APPROACH_TEXT in approach_section
    assert MISSING_APPROACH not in markdown


def test_p2_1_missing_code_evidence_is_marked(client: TestClient) -> None:
    cid = create_challenge(client, ai_usage_level="A2")
    # A plain-text artifact of another kind must not masquerade as core code.
    upload_artifact(
        client,
        cid,
        filename="notes.txt",
        data=b"SYNTHETIC-PLAIN-NOTES\n",
        evidence_kind="other",
    )

    body = preview(client, cid)
    assert "core_code" in body["missing_requirements"]
    assert MISSING_CODE in body["markdown"]


def test_p2_1_source_code_artifact_satisfies_core_code(
    client: TestClient,
) -> None:
    cid = create_challenge(client, ai_usage_level="A2")
    upload_artifact(
        client,
        cid,
        filename="solve.py",
        data=SOURCE_CODE_BYTES,
        evidence_kind="source_code",
    )

    body = preview(client, cid)
    assert "core_code" not in body["missing_requirements"]
    markdown = body["markdown"]
    assert MISSING_CODE not in markdown
    code_section = markdown_section(markdown, "## 4. 核心代码", "## 5. 运行结果")
    assert "SYNTHETIC_SOURCE_CODE" in code_section


def test_p2_1_manual_operation_alone_is_not_execution_evidence(
    client: TestClient,
) -> None:
    cid = create_challenge(client, ai_usage_level="A2")
    add_manual_operation(client, cid)

    body = preview(client, cid)
    assert "manual_operation" not in body["missing_requirements"]
    assert "execution_evidence" in body["missing_requirements"]
    assert MISSING_EXECUTION in body["markdown"]


def test_p2_1_execution_artifact_satisfies_execution_evidence(
    client: TestClient,
) -> None:
    cid = create_challenge(client, ai_usage_level="A2")
    upload_artifact(
        client,
        cid,
        filename="execution.png",
        data=EXECUTION_BYTES,
        evidence_kind="execution",
    )

    body = preview(client, cid)
    assert "execution_evidence" not in body["missing_requirements"]
    assert MISSING_EXECUTION not in body["markdown"]


def test_p2_1_complete_evidence_set_is_complete(client: TestClient) -> None:
    ctx = build_complete_dossier(client)
    body = preview(client, ctx["cid"])

    assert body["completeness"] == "complete"
    assert body["missing_requirements"] == []
    assert "档案完整性：complete" in body["markdown"]


def test_p2_1_writeup_does_not_fabricate_flag_or_execution(
    client: TestClient,
) -> None:
    ctx = build_complete_dossier(client)
    cid = ctx["cid"]
    body = preview(client, cid)
    markdown = body["markdown"]

    # No fabricated flag and no claim that the workbench executed tools.
    assert "flag{" not in markdown.lower()
    assert "flag{" not in json.dumps(body, ensure_ascii=False).lower()
    assert "execution_mode=manual_external, execution_verified=false" in markdown
    assert "本工作台未启用自动工具执行" in markdown

    events = client.get(f"/api/challenges/{cid}/events").json()
    manual_events = [
        event for event in events if event["event_type"] == "manual_operation_recorded"
    ]
    assert len(manual_events) == 1
    payload = manual_events[0]["payload"]
    assert payload["execution_mode"] == "manual_external"
    assert payload["execution_verified"] is False
    assert payload["record_source"] == "user_manual_entry"

    event_types = {event["event_type"] for event in events}
    assert not event_types & {"tool_started", "tool_finished", "tool_approved"}
