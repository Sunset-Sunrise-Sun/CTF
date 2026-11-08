"""Acceptance tests for the backend MVP workflow.

Covered areas: project configuration and competition rules, challenge
extension fields, safe ZIP import, evidence classification, and manual
operation records.

Every byte used here is synthetic and constructed inside this module: no real
competition attachment, flag, or target is used.  Each test isolates its data
root with ``tmp_path``.

The suite must pass on Windows locally and on Linux CI (Python 3.11).  Archive
safety is checked through ``ZipInfo`` metadata only, so no real symbolic link is
created, and archive member paths are addressed through URL-encoded segments.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import warnings
import zipfile
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app.imports import ImportLimits
from app.main import create_app
from app.models import Challenge

PNG_HEADER = b"\x89PNG\r\n\x1a\n"
PDF_HEADER = b"%PDF-1.7\n"
SYNTHETIC_RULES = PDF_HEADER + b"synthetic competition rules\n"
CAPTURE_TIME_CLAIM = "2020-01-02T03:04:05+00:00"

DEFAULT_MAX_FILES = 2000
DEFAULT_MAX_FILE_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 200 * 1024 * 1024
DEFAULT_MAX_COMPRESSION_RATIO = 200.0

ARTIFACT_VIEW_FIELDS = {
    "artifact_id",
    "challenge_id",
    "sha256",
    "size",
    "media_type",
    "original_filename",
    "ingested_at",
    "source_event_id",
    "evidence_kind",
    "capture_time_claim",
    "source_event_type",
    "source_event_sequence",
}
LEGACY_ARTIFACT_PAYLOAD_FIELDS = {"artifact_id", "sha256", "size", "media_type"}
IMPORT_RECORD_FIELDS = {
    "import_id",
    "challenge_id",
    "original_artifact_id",
    "original_filename",
    "extracted_file_count",
    "total_uncompressed_size",
    "warnings",
    "created_at",
    "manifest_sha256",
    "manifest_verified",
    "integrity_error",
}
IMPORT_RESULT_FIELDS = IMPORT_RECORD_FIELDS | {
    "files",
    "original_artifact",
    "import_event_id",
}
IMPORT_FILE_FIELDS = {"relative_path", "size", "sha256", "media_type"}
IMPORT_EVENT_PAYLOAD_FIELDS = {
    "import_id",
    "challenge_id",
    "original_artifact_id",
    "original_filename",
    "extracted_file_count",
    "total_uncompressed_size",
    "warnings",
    "created_at",
    "manifest_sha256",
}

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


@pytest.fixture
def cid(client: TestClient) -> str:
    return create_challenge(client)


# ---------------------------------------------------------------------------
# helpers (synthetic data only)
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def expected_blob(data_root: Path, sha256: str) -> Path:
    return data_root / "artifacts" / "sha256" / sha256[:2] / sha256[2:4] / sha256


def blob_files(data_root: Path) -> list[Path]:
    sha_root = data_root / "artifacts" / "sha256"
    if not sha_root.is_dir():
        return []
    return sorted(path for path in sha_root.rglob("*") if path.is_file())


def staging_entries(data_root: Path) -> list[Path]:
    staging = data_root / "artifacts" / ".staging"
    return sorted(staging.iterdir()) if staging.is_dir() else []


def db_rows(data_root: Path, sql: str, params: tuple = ()) -> list[tuple]:
    connection = sqlite3.connect(data_root / "workbench.sqlite3", timeout=15)
    try:
        return list(connection.execute(sql, params))
    finally:
        connection.close()


def build_zip(entries, *, compression: int = zipfile.ZIP_STORED) -> bytes:
    """Build a ZIP from ``(name_or_ZipInfo, bytes)`` pairs in memory."""
    buffer = io.BytesIO()
    with warnings.catch_warnings():
        # Deliberately duplicated member names warn in the stdlib; the test
        # needs such an archive to exercise the server-side duplicate check.
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(buffer, "w", compression) as archive:
            for member, data in entries:
                archive.writestr(member, data)
    return buffer.getvalue()


def symlink_zip() -> bytes:
    """A ZIP entry that declares itself as a symbolic link (metadata only)."""
    info = zipfile.ZipInfo("link")
    info.external_attr = 0o120777 << 16
    return build_zip([(info, b"target")])


def create_challenge(client: TestClient, name: str = "Synthetic Challenge") -> str:
    response = client.post("/api/challenges", json={"name": name, "category": "Misc"})
    assert response.status_code == 201
    return response.json()["challenge_id"]


def create_project(client: TestClient, **fields) -> dict:
    payload = {"project_name": "Synthetic Project"}
    payload.update(fields)
    response = client.put("/api/project", json=payload)
    assert response.status_code == 200
    return response.json()


def upload_rules(
    client: TestClient,
    data: bytes = SYNTHETIC_RULES,
    *,
    filename: str = "rules.pdf",
    content_type: str = "application/octet-stream",
):
    return client.post(
        "/api/project/rules",
        files={"file": (filename, data, content_type)},
    )


def upload_artifact(
    client: TestClient,
    cid: str,
    data: bytes,
    *,
    filename: str = "evidence.bin",
    evidence_kind: str | None = None,
    capture_time_claim: str | None = None,
):
    form: dict[str, str] = {}
    if evidence_kind is not None:
        form["evidence_kind"] = evidence_kind
    if capture_time_claim is not None:
        form["capture_time_claim"] = capture_time_claim
    return client.post(
        f"/api/challenges/{cid}/artifacts",
        files={"file": (filename, data, "application/octet-stream")},
        data=form,
    )


def upload_import(
    client: TestClient,
    cid: str,
    data: bytes,
    *,
    filename: str = "synthetic-challenge.zip",
):
    return client.post(
        f"/api/challenges/{cid}/imports",
        files={"file": (filename, data, "application/zip")},
    )


def import_url(cid: str, import_id: str, suffix: str = "") -> str:
    return f"/api/challenges/{cid}/imports/{import_id}{suffix}"


def import_file_url(cid: str, import_id: str, relative_path: str) -> str:
    encoded = quote(relative_path, safe="/")
    return import_url(cid, import_id, f"/files/{encoded}")


def installed_import_dir(data_root: Path, cid: str, import_id: str) -> Path:
    return data_root / "challenges" / cid / "imports" / import_id


def assert_no_import_residue(client: TestClient, data_root: Path, cid: str) -> None:
    """A rejected import leaves no installed directory, artifact, or blob."""
    challenge_dir = data_root / "challenges" / cid
    imports_dir = challenge_dir / "imports"
    assert not imports_dir.exists() or list(imports_dir.iterdir()) == []
    assert list(challenge_dir.rglob(".import-staging-*")) == []
    assert client.get(f"/api/challenges/{cid}/artifacts").json() == []
    assert client.get(f"/api/challenges/{cid}/events").json() == []
    assert db_rows(
        data_root,
        "SELECT count(*) FROM artifacts WHERE challenge_id=?",
        (cid,),
    ) == [(0,)]
    assert blob_files(data_root) == []
    assert staging_entries(data_root) == []


def assert_import_rejected(
    client: TestClient,
    data_root: Path,
    cid: str,
    payload: bytes,
    *,
    detail_contains: str,
    status_code: int = 422,
) -> None:
    response = upload_import(client, cid, payload)
    assert response.status_code == status_code
    detail = response.json().get("detail", "")
    assert isinstance(detail, str) and detail
    assert detail_contains in detail
    assert_no_import_residue(client, data_root, cid)


def reject_import_with_limits(
    tmp_path: Path,
    payload: bytes,
    *,
    limits: ImportLimits,
    detail_contains: str,
    max_artifact_bytes: int | None = None,
    status_code: int = 422,
) -> None:
    data_root = tmp_path / "data"
    kwargs = {"import_limits": limits}
    if max_artifact_bytes is not None:
        kwargs["max_artifact_bytes"] = max_artifact_bytes
    with TestClient(create_app(data_root, **kwargs)) as limited:
        cid = create_challenge(limited)
        assert_import_rejected(
            limited,
            data_root,
            cid,
            payload,
            detail_contains=detail_contains,
            status_code=status_code,
        )


# ---------------------------------------------------------------------------
# project configuration
# ---------------------------------------------------------------------------


def test_project_not_configured_returns_404(client: TestClient) -> None:
    response = client.get("/api/project")
    assert response.status_code == 404
    assert response.json() == {"detail": "Project is not configured"}


def test_project_create_update_and_get(client: TestClient) -> None:
    created = client.put(
        "/api/project",
        json={
            "project_name": "Synthetic Project",
            "competition_name": "Synthetic Cup",
            "competition_type": "Jeopardy",
            "ai_policy_summary": "AI use allowed with disclosure",
        },
    )
    assert created.status_code == 200
    project = created.json()

    assert project["project_name"] == "Synthetic Project"
    assert project["competition_name"] == "Synthetic Cup"
    assert project["competition_type"] == "Jeopardy"
    assert project["ai_policy_summary"] == "AI use allowed with disclosure"
    assert project["project_id"]
    assert project["rules_filename"] is None
    assert project["rules_sha256"] is None
    assert project["rules_size"] is None
    assert project["rules_ingested_at"] is None

    # Only the supplied fields change; the rest of the project is preserved.
    updated = client.put("/api/project", json={"competition_type": "Attack-Defense"})
    assert updated.status_code == 200
    body = updated.json()
    assert body["project_id"] == project["project_id"]
    assert body["project_name"] == "Synthetic Project"
    assert body["competition_name"] == "Synthetic Cup"
    assert body["competition_type"] == "Attack-Defense"
    assert body["ai_policy_summary"] == "AI use allowed with disclosure"
    assert client.get("/api/project").json() == body


def test_project_create_requires_project_name(client: TestClient) -> None:
    response = client.put("/api/project", json={"competition_name": "Synthetic Cup"})
    assert response.status_code == 422
    assert "project_name" in response.json()["detail"]
    # A rejected creation leaves the project unconfigured.
    assert client.get("/api/project").status_code == 404


# ---------------------------------------------------------------------------
# competition rules
# ---------------------------------------------------------------------------


def test_rules_upload_requires_project(client: TestClient) -> None:
    response = upload_rules(client)
    assert response.status_code == 409
    assert "Create the project" in response.json()["detail"]
    assert client.get("/api/project").status_code == 404


def test_rules_upload_and_content_download(client: TestClient, data_root: Path) -> None:
    create_project(client)
    response = upload_rules(client)
    assert response.status_code == 200

    project = response.json()
    sha256 = sha256_hex(SYNTHETIC_RULES)
    assert project["rules_filename"] == "rules.pdf"
    assert project["rules_sha256"] == sha256
    assert project["rules_size"] == len(SYNTHETIC_RULES)
    assert project["rules_ingested_at"]
    blob = expected_blob(data_root, sha256)
    assert blob.read_bytes() == SYNTHETIC_RULES

    download = client.get("/api/project/rules/content")
    assert download.status_code == 200
    assert download.content == SYNTHETIC_RULES
    assert download.headers["content-type"].split(";")[0] == "application/pdf"
    assert download.headers["x-content-type-options"] == "nosniff"
    disposition = download.headers["content-disposition"]
    assert "attachment" in disposition
    assert "rules.pdf" in disposition
    assert client.get("/api/project").json() == project


def test_rules_upload_size_limit(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    with TestClient(create_app(data_root, rules_max_bytes=5)) as client:
        create_project(client)
        assert SYNTHETIC_RULES.startswith(b"%PDF-") and len(SYNTHETIC_RULES) > 5
        response = upload_rules(client)
        assert response.status_code == 413
        assert "size limit" in response.json()["detail"]

        project = client.get("/api/project").json()
        assert project["rules_filename"] is None
        assert project["rules_sha256"] is None
        assert project["rules_size"] is None
        assert blob_files(data_root) == []
        assert staging_entries(data_root) == []


def test_rules_duplicate_upload_keeps_single_blob(
    client: TestClient, data_root: Path
) -> None:
    create_project(client)
    first = upload_rules(client, filename="rules.pdf")
    second = upload_rules(client, filename="rules-copy.pdf")
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["rules_sha256"] == first.json()["rules_sha256"]
    assert second.json()["rules_size"] == first.json()["rules_size"]

    # The same bytes stay a single content-addressed blob on disk.
    sha256 = first.json()["rules_sha256"]
    assert blob_files(data_root) == [expected_blob(data_root, sha256)]
    download = client.get("/api/project/rules/content")
    assert download.status_code == 200
    assert download.content == SYNTHETIC_RULES


def test_rules_filename_traversal_is_display_only(
    client: TestClient, data_root: Path, tmp_path: Path
) -> None:
    create_project(client)
    traversal_name = "../../synthetic-rules.pdf"
    response = upload_rules(client, filename=traversal_name)
    assert response.status_code == 200
    project = response.json()
    assert project["rules_filename"] == "synthetic-rules.pdf"

    # The filename is display metadata only: nothing is written outside the
    # data root, and the blob name is the digest.
    assert list(tmp_path.rglob("synthetic-rules.pdf")) == []
    sha256 = project["rules_sha256"]
    blob = expected_blob(data_root, sha256)
    assert blob.is_file()
    assert "synthetic-rules" not in str(blob)

    download = client.get("/api/project/rules/content")
    assert download.status_code == 200
    assert download.content == SYNTHETIC_RULES
    disposition = download.headers["content-disposition"]
    assert "synthetic-rules.pdf" in disposition
    assert ".." not in disposition


def test_rules_content_missing_tampered_and_deleted(
    client: TestClient, data_root: Path
) -> None:
    create_project(client)
    missing = client.get("/api/project/rules/content")
    assert missing.status_code == 404

    response = upload_rules(client)
    assert response.status_code == 200
    sha256 = response.json()["rules_sha256"]
    blob = expected_blob(data_root, sha256)

    # A tampered rules blob is an integrity failure, not a silent download.
    os.chmod(blob, 0o600)
    blob.write_bytes(PDF_HEADER + b"synthetic TAMPERED rules")
    assert client.get("/api/project/rules/content").status_code == 409

    os.chmod(blob, 0o600)
    blob.unlink()
    assert client.get("/api/project/rules/content").status_code == 409

    # Project metadata still records what was ingested.
    assert client.get("/api/project").json()["rules_sha256"] == sha256


# ---------------------------------------------------------------------------
# challenge extension fields
# ---------------------------------------------------------------------------


def test_challenge_extension_fields_and_defaults(client: TestClient) -> None:
    created = client.post(
        "/api/challenges",
        json={
            "name": "Extended",
            "category": "Misc",
            "ai_usage_level": "A2",
            "score": 500,
            "competition_name": "Synthetic Cup",
        },
    )
    assert created.status_code == 201
    challenge = created.json()
    assert challenge["ai_usage_level"] == "A2"
    assert challenge["score"] == 500
    assert challenge["competition_name"] == "Synthetic Cup"

    listed = {
        item["challenge_id"]: item for item in client.get("/api/challenges").json()
    }
    assert listed[challenge["challenge_id"]] == challenge

    defaulted = client.post(
        "/api/challenges", json={"name": "Defaults", "category": "Misc"}
    )
    assert defaulted.status_code == 201
    assert defaulted.json()["ai_usage_level"] == "unknown"
    assert defaulted.json()["score"] is None
    assert defaulted.json()["competition_name"] is None


@pytest.mark.parametrize(
    "extra",
    [
        {"ai_usage_level": "A3"},
        {"ai_usage_level": "a0"},
        {"score": -1},
        {"score": 1_000_001},
    ],
)
def test_challenge_rejects_invalid_extension_values(
    client: TestClient, extra: dict
) -> None:
    response = client.post(
        "/api/challenges", json={"name": "Invalid", "category": "Misc", **extra}
    )
    assert response.status_code == 422
    assert client.get("/api/challenges").json() == []


def test_challenge_competition_name_inherited_from_project(
    client: TestClient,
) -> None:
    create_project(client, project_name="Synthetic Project")

    # No project competition name yet -> the challenge keeps the default.
    first = client.post(
        "/api/challenges", json={"name": "First", "category": "Misc"}
    ).json()
    assert first["competition_name"] is None

    client.put("/api/project", json={"competition_name": "Synthetic Cup"})
    inherited = client.post(
        "/api/challenges", json={"name": "Inherited", "category": "Misc"}
    ).json()
    assert inherited["competition_name"] == "Synthetic Cup"

    explicit = client.post(
        "/api/challenges",
        json={
            "name": "Explicit",
            "category": "Misc",
            "competition_name": "Other Cup",
        },
    ).json()
    assert explicit["competition_name"] == "Other Cup"


def test_challenge_historical_json_gets_defaults(
    client: TestClient, data_root: Path
) -> None:
    legacy_id = "00000000-0000-0000-0000-0000000000aa"
    legacy = Challenge(name="Legacy synthetic challenge", category="Misc")
    body = legacy.model_dump()
    # Historical rows always carried the base challenge fields; only the MVP
    # extension keys are missing from the stored JSON body.
    body["challenge_id"] = legacy_id
    for key in ("ai_usage_level", "score", "competition_name"):
        body.pop(key)
    assert set(body).isdisjoint({"ai_usage_level", "score", "competition_name"})

    connection = sqlite3.connect(data_root / "workbench.sqlite3", timeout=15)
    try:
        with connection:
            connection.execute(
                "INSERT INTO challenges VALUES (?,?)",
                (legacy_id, json.dumps(body)),
            )
    finally:
        connection.close()

    response = client.get("/api/challenges")
    assert response.status_code == 200
    loaded = {item["challenge_id"]: item for item in response.json()}
    assert set(loaded) == {legacy_id}
    record = loaded[legacy_id]
    assert record["name"] == "Legacy synthetic challenge"
    assert record["ai_usage_level"] == "unknown"
    assert record["score"] is None
    assert record["competition_name"] is None


# ---------------------------------------------------------------------------
# ZIP import: success path
# ---------------------------------------------------------------------------


def test_import_records_manifest_and_extracted_files(
    client: TestClient, data_root: Path, cid: str
) -> None:
    members = [
        ("docs/readme.txt", b"synthetic readme", "text/plain"),
        ("icon.png", PNG_HEADER + b"synthetic icon", "image/png"),
        ("raw.bin", b"\x00\x01\x02", "application/octet-stream"),
    ]
    payload = build_zip([(name, data) for name, data, _ in members])
    response = upload_import(client, cid, payload, filename="synthetic-challenge.zip")
    assert response.status_code == 201
    result = response.json()

    assert set(result) == IMPORT_RESULT_FIELDS
    assert result["challenge_id"] == cid
    assert result["original_filename"] == "synthetic-challenge.zip"
    assert result["extracted_file_count"] == len(members)
    assert result["total_uncompressed_size"] == sum(len(data) for _, data, _ in members)
    assert result["warnings"] == []
    assert len(result["manifest_sha256"]) == 64
    assert len(result["import_id"]) == 36
    assert len(result["import_event_id"]) == 36

    expected_files = [
        {
            "relative_path": name,
            "size": len(data),
            "sha256": sha256_hex(data),
            "media_type": media_type,
        }
        for name, data, media_type in members
    ]
    assert result["files"] == sorted(
        expected_files, key=lambda item: item["relative_path"]
    )
    assert all(set(item) == IMPORT_FILE_FIELDS for item in result["files"])

    # Extraction goes to <data_root>/challenges/<cid>/imports/<import_id>/.
    install_dir = installed_import_dir(data_root, cid, result["import_id"])
    assert install_dir.is_dir()
    for name, data, _media_type in members:
        extracted = install_dir.joinpath(*name.split("/"))
        assert extracted.is_file()
        assert extracted.read_bytes() == data

    manifest_path = install_dir / "manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["import_id"] == result["import_id"]
    assert manifest["manifest_sha256"] == result["manifest_sha256"]
    assert [item["relative_path"] for item in manifest["files"]] == [
        item["relative_path"] for item in result["files"]
    ]

    listing = client.get(f"/api/challenges/{cid}/imports")
    assert listing.status_code == 200
    records = listing.json()
    assert len(records) == 1
    assert set(records[0]) == IMPORT_RECORD_FIELDS
    assert records[0] == {key: result[key] for key in IMPORT_RECORD_FIELDS}

    detail = client.get(import_url(cid, result["import_id"]))
    assert detail.status_code == 200
    assert set(detail.json()) == IMPORT_RECORD_FIELDS | {"files"}
    assert detail.json()["files"] == result["files"]

    # Every manifest-listed file is downloadable with a server-sniffed type.
    download = client.get(import_file_url(cid, result["import_id"], "docs/readme.txt"))
    assert download.status_code == 200
    assert download.content == b"synthetic readme"
    assert download.headers["content-type"].split(";")[0] == "text/plain"
    assert download.headers["x-content-type-options"] == "nosniff"
    assert "inline" in download.headers["content-disposition"]

    png = client.get(import_file_url(cid, result["import_id"], "icon.png"))
    assert png.status_code == 200
    assert png.content == PNG_HEADER + b"synthetic icon"
    assert png.headers["content-type"].split(";")[0] == "image/png"


def test_import_saves_original_artifact_and_event(
    client: TestClient, data_root: Path, cid: str
) -> None:
    payload = build_zip([("notes.txt", b"synthetic import event")])
    response = upload_import(client, cid, payload, filename="synthetic-import.zip")
    assert response.status_code == 201
    result = response.json()

    artifacts = client.get(f"/api/challenges/{cid}/artifacts").json()
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert set(artifact) == ARTIFACT_VIEW_FIELDS
    assert artifact["artifact_id"] == result["original_artifact_id"]
    assert artifact["sha256"] == sha256_hex(payload)
    assert artifact["size"] == len(payload)
    assert artifact["media_type"] == "application/zip"
    assert artifact["original_filename"] == "synthetic-import.zip"
    assert artifact["evidence_kind"] == "challenge_archive"
    assert artifact["source_event_type"] == "artifact_added"
    assert artifact == result["original_artifact"]

    download = client.get(
        f"/api/challenges/{cid}/artifacts/{artifact['artifact_id']}/content"
    )
    assert download.status_code == 200
    assert download.content == payload

    events = client.get(f"/api/challenges/{cid}/events").json()
    assert [event["event_type"] for event in events] == [
        "artifact_added",
        "challenge_imported",
    ]
    imported = events[1]
    assert imported["event_id"] == result["import_event_id"]
    assert imported["actor"] == "user"
    assert imported["artifact_ids"] == [result["original_artifact_id"]]
    assert set(imported["payload"]) == IMPORT_EVENT_PAYLOAD_FIELDS
    assert imported["payload"] == {
        key: result[key] for key in IMPORT_EVENT_PAYLOAD_FIELDS
    }

    assert client.get(f"/api/challenges/{cid}/integrity").json() == {
        "valid": True,
        "earliest_affected_sequence": None,
    }


def test_import_lookup_returns_404_for_unknown_ids(
    client: TestClient, cid: str
) -> None:
    payload = build_zip([("notes.txt", b"synthetic lookup")])
    result = upload_import(client, cid, payload).json()
    import_id = result["import_id"]

    other_cid = create_challenge(client, "Second")
    unknown_import = "00000000-0000-0000-0000-00000000dead"
    unknown_cid = "00000000-0000-0000-0000-000000000000"

    assert client.get(f"/api/challenges/{unknown_cid}/imports").status_code == 404
    assert client.get(f"/api/challenges/{other_cid}/imports").json() == []
    assert client.get(import_url(other_cid, import_id)).status_code == 404
    assert (
        client.get(import_file_url(other_cid, import_id, "notes.txt")).status_code
        == 404
    )
    assert client.get(import_url(cid, unknown_import)).status_code == 404
    assert (
        client.get(import_file_url(cid, unknown_import, "notes.txt")).status_code == 404
    )
    # A manifest lookup never serves an arbitrary path.
    assert (
        client.get(import_file_url(cid, import_id, "not-in-manifest.txt")).status_code
        == 404
    )


def test_import_lookup_rejects_malformed_import_id(tmp_path: Path) -> None:
    """A non-UUID import id is an unknown import, not a server error."""
    data_root = tmp_path / "data"
    with TestClient(create_app(data_root), raise_server_exceptions=False) as client:
        cid = create_challenge(client)
        assert client.get(import_url(cid, "not-a-uuid")).status_code == 404
        assert (
            client.get(import_file_url(cid, "not-a-uuid", "notes.txt")).status_code
            == 404
        )


# ---------------------------------------------------------------------------
# ZIP import: archive validation and budgets
# ---------------------------------------------------------------------------


def test_import_rejects_non_zip_and_empty_uploads(
    client: TestClient, data_root: Path, cid: str
) -> None:
    cases = [
        (b"this is not a zip archive", "not a valid ZIP"),
        (b"", "empty"),
    ]
    for payload, detail_contains in cases:
        assert_import_rejected(
            client,
            data_root,
            cid,
            payload,
            detail_contains=detail_contains,
        )


def test_import_rejects_zip_slip(client: TestClient, data_root: Path, cid: str) -> None:
    payload = build_zip([("../evil.txt", b"synthetic zip slip")])
    assert_import_rejected(
        client, data_root, cid, payload, detail_contains="Path traversal"
    )


def test_import_rejects_absolute_path(
    client: TestClient, data_root: Path, cid: str
) -> None:
    payload = build_zip([("/etc/passwd", b"synthetic absolute path")])
    assert_import_rejected(
        client, data_root, cid, payload, detail_contains="Absolute path"
    )


def test_import_rejects_windows_drive_path(
    client: TestClient, data_root: Path, cid: str
) -> None:
    for member in ("C:\\evil.txt", "C:/evil.txt"):
        payload = build_zip([(member, b"synthetic windows drive path")])
        assert_import_rejected(
            client, data_root, cid, payload, detail_contains="Windows drive path"
        )


def test_import_rejects_symlink_entry(
    client: TestClient, data_root: Path, cid: str
) -> None:
    assert_import_rejected(
        client, data_root, cid, symlink_zip(), detail_contains="Symbolic link"
    )


def test_import_rejects_duplicate_path(
    client: TestClient, data_root: Path, cid: str
) -> None:
    payload = build_zip(
        [("same.txt", b"synthetic first"), ("same.txt", b"synthetic second")]
    )
    assert_import_rejected(
        client, data_root, cid, payload, detail_contains="Duplicate path"
    )


def test_import_rejects_case_conflict(
    client: TestClient, data_root: Path, cid: str
) -> None:
    payload = build_zip([("A.txt", b"synthetic upper"), ("a.txt", b"synthetic lower")])
    assert_import_rejected(
        client, data_root, cid, payload, detail_contains="Case-insensitive"
    )


def test_import_rejects_file_count_over_limit(tmp_path: Path) -> None:
    payload = build_zip([("a.txt", b"a"), ("b.txt", b"b"), ("c.txt", b"c")])
    reject_import_with_limits(
        tmp_path,
        payload,
        limits=ImportLimits(max_files=2),
        detail_contains="file count",
    )


def test_import_rejects_single_file_over_limit(tmp_path: Path) -> None:
    payload = build_zip([("large.txt", b"x" * 11)])
    reject_import_with_limits(
        tmp_path,
        payload,
        limits=ImportLimits(max_file_bytes=10),
        detail_contains="uncompressed size limit",
    )


def test_import_rejects_total_size_over_limit(tmp_path: Path) -> None:
    payload = build_zip([("a.bin", b"a" * 15), ("b.bin", b"b" * 15)])
    reject_import_with_limits(
        tmp_path,
        payload,
        limits=ImportLimits(max_total_bytes=20),
        detail_contains="total uncompressed size limit",
    )


def test_import_rejects_compression_ratio_bomb(tmp_path: Path) -> None:
    payload = build_zip(
        [("bomb.bin", b"\x00" * 100_000)], compression=zipfile.ZIP_DEFLATED
    )
    reject_import_with_limits(
        tmp_path,
        payload,
        limits=ImportLimits(max_compression_ratio=5),
        detail_contains="compression ratio",
    )


def test_import_rejects_oversized_archive(tmp_path: Path) -> None:
    payload = b"PK\x03\x04" + b"x" * 7
    assert len(payload) == 11
    reject_import_with_limits(
        tmp_path,
        payload,
        limits=ImportLimits(),
        max_artifact_bytes=10,
        detail_contains="size limit",
        status_code=413,
    )


# ---------------------------------------------------------------------------
# ZIP import: extraction behaviour and persistence
# ---------------------------------------------------------------------------


def test_import_does_not_extract_nested_archive(
    client: TestClient, data_root: Path, cid: str
) -> None:
    inner = build_zip([("inside.txt", b"synthetic inner content")])
    payload = build_zip([("inner.zip", inner), ("note.txt", b"synthetic note")])
    response = upload_import(client, cid, payload)
    assert response.status_code == 201
    result = response.json()

    assert [item["relative_path"] for item in result["files"]] == [
        "inner.zip",
        "note.txt",
    ]
    assert result["extracted_file_count"] == 2
    assert result["warnings"] == ["Nested archive was not extracted: inner.zip"]

    install_dir = installed_import_dir(data_root, cid, result["import_id"])
    assert (install_dir / "inner.zip").read_bytes() == inner
    # The nested archive is stored as a file and never recursively extracted.
    assert list(install_dir.rglob("inside.txt")) == []

    detail = client.get(import_url(cid, result["import_id"])).json()
    assert detail["warnings"] == result["warnings"]
    assert detail["files"] == result["files"]


def test_import_accepts_unicode_and_space_filenames(
    client: TestClient, data_root: Path, cid: str
) -> None:
    members = [
        ("说明 文档.txt", "合成文本内容".encode()),
        ("子目录/解题 笔记.txt", "合成笔记内容".encode()),
    ]
    payload = build_zip(members)
    response = upload_import(client, cid, payload)
    assert response.status_code == 201
    result = response.json()

    assert result["extracted_file_count"] == len(members)
    assert [item["relative_path"] for item in result["files"]] == sorted(
        name for name, _data in members
    )
    install_dir = installed_import_dir(data_root, cid, result["import_id"])
    for name, data in members:
        assert install_dir.joinpath(*name.split("/")).read_bytes() == data
        download = client.get(import_file_url(cid, result["import_id"], name))
        assert download.status_code == 200
        assert download.content == data
        assert download.headers["content-type"].split(";")[0] == "text/plain"


def test_import_survives_restart(data_root: Path) -> None:
    payload = build_zip([("深 层/笔记 1.txt", b"synthetic persistence")])

    with TestClient(create_app(data_root)) as first:
        cid = create_challenge(first)
        result = upload_import(first, cid, payload).json()
        events_before = first.get(f"/api/challenges/{cid}/events").json()
        listing_before = first.get(f"/api/challenges/{cid}/imports").json()

    with TestClient(create_app(data_root)) as second:
        assert second.get(f"/api/challenges/{cid}/imports").json() == listing_before
        detail = second.get(import_url(cid, result["import_id"]))
        assert detail.status_code == 200
        assert detail.json()["files"] == result["files"]

        download = second.get(
            import_file_url(cid, result["import_id"], "深 层/笔记 1.txt")
        )
        assert download.status_code == 200
        assert download.content == b"synthetic persistence"

        artifacts = second.get(f"/api/challenges/{cid}/artifacts").json()
        assert len(artifacts) == 1
        original = second.get(
            f"/api/challenges/{cid}/artifacts/{artifacts[0]['artifact_id']}/content"
        )
        assert original.status_code == 200
        assert original.content == payload

        assert second.get(f"/api/challenges/{cid}/events").json() == events_before
        assert second.get(f"/api/challenges/{cid}/integrity").json() == {
            "valid": True,
            "earliest_affected_sequence": None,
        }


# ---------------------------------------------------------------------------
# evidence classification
# ---------------------------------------------------------------------------


def test_artifact_evidence_kind_and_capture_time(client: TestClient, cid: str) -> None:
    payload = PNG_HEADER + b"synthetic flag evidence"
    response = upload_artifact(
        client,
        cid,
        payload,
        filename="flag.png",
        evidence_kind="flag_capture",
        capture_time_claim=CAPTURE_TIME_CLAIM,
    )
    assert response.status_code == 201
    artifact = response.json()

    assert set(artifact) == ARTIFACT_VIEW_FIELDS
    assert artifact["evidence_kind"] == "flag_capture"
    assert artifact["capture_time_claim"] == CAPTURE_TIME_CLAIM
    assert artifact["source_event_type"] == "artifact_added"
    assert artifact["source_event_sequence"] == 1
    # The user claim is kept distinct from the server ingestion timestamp.
    assert artifact["ingested_at"]
    assert artifact["ingested_at"] != CAPTURE_TIME_CLAIM

    assert client.get(f"/api/challenges/{cid}/artifacts").json() == [artifact]
    assert (
        client.get(f"/api/challenges/{cid}/artifacts/{artifact['artifact_id']}").json()
        == artifact
    )

    events = client.get(f"/api/challenges/{cid}/events").json()
    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "artifact_added"
    assert set(event["payload"]) == LEGACY_ARTIFACT_PAYLOAD_FIELDS | {
        "evidence_kind",
        "capture_time_claim",
    }
    assert event["payload"]["artifact_id"] == artifact["artifact_id"]
    assert event["payload"]["sha256"] == artifact["sha256"]
    assert event["payload"]["size"] == len(payload)
    assert event["payload"]["media_type"] == "image/png"
    assert event["payload"]["evidence_kind"] == "flag_capture"
    assert event["payload"]["capture_time_claim"] == CAPTURE_TIME_CLAIM
    assert event["artifact_ids"] == [artifact["artifact_id"]]
    assert client.get(f"/api/challenges/{cid}/integrity").json()["valid"] is True


def test_artifact_evidence_defaults_for_legacy_payload(
    client: TestClient, cid: str
) -> None:
    payload = b"synthetic legacy evidence"
    artifact = upload_artifact(client, cid, payload).json()

    # Without classification the stored event payload is byte-compatible with
    # historical artifact_added payloads, so the view falls back to defaults.
    assert artifact["evidence_kind"] == "other"
    assert artifact["capture_time_claim"] is None
    assert artifact["source_event_type"] == "artifact_added"
    assert artifact["source_event_sequence"] == 1

    event = client.get(f"/api/challenges/{cid}/events").json()[0]
    assert event["event_type"] == "artifact_added"
    assert set(event["payload"]) == LEGACY_ARTIFACT_PAYLOAD_FIELDS
    assert "evidence_kind" not in event["payload"]
    assert "capture_time_claim" not in event["payload"]

    listed = client.get(f"/api/challenges/{cid}/artifacts").json()
    assert listed == [artifact]
    assert listed[0]["evidence_kind"] == "other"
    assert listed[0]["capture_time_claim"] is None


def test_artifact_rejects_invalid_evidence_fields(
    client: TestClient, data_root: Path, cid: str
) -> None:
    invalid_kind = upload_artifact(
        client, cid, b"synthetic bad kind", evidence_kind="definitely-not-a-kind"
    )
    assert invalid_kind.status_code == 422
    assert "evidence_kind" in invalid_kind.json()["detail"]

    invalid_claim = upload_artifact(
        client, cid, b"synthetic bad claim", capture_time_claim="not-a-time"
    )
    assert invalid_claim.status_code == 422
    assert "capture_time_claim" in invalid_claim.json()["detail"]

    assert client.get(f"/api/challenges/{cid}/artifacts").json() == []
    assert client.get(f"/api/challenges/{cid}/events").json() == []
    assert blob_files(data_root) == []
    assert staging_entries(data_root) == []


# ---------------------------------------------------------------------------
# manual operation records
# ---------------------------------------------------------------------------


MANUAL_OPERATION = {
    "command": "python synthetic-solve.py",
    "working_directory": "/tmp/synthetic-workdir",
    "purpose": "exercise a synthetic local exploit",
    "exit_code": 0,
    "result_note": "synthetic local run printed a placeholder flag",
    "started_at_claim": "2020-01-01T00:00:00+00:00",
    "finished_at_claim": "2020-01-01T00:01:00+00:00",
}
MANUAL_OPERATION_PAYLOAD = {
    "command": MANUAL_OPERATION["command"],
    "working_directory": MANUAL_OPERATION["working_directory"],
    "purpose": MANUAL_OPERATION["purpose"],
    "exit_code": 0,
    "result_note": MANUAL_OPERATION["result_note"],
    "started_at_claim": MANUAL_OPERATION["started_at_claim"],
    "finished_at_claim": MANUAL_OPERATION["finished_at_claim"],
    "execution_mode": "manual_external",
    "execution_verified": False,
    "record_source": "user_manual_entry",
}


def manual_operation_url(cid: str) -> str:
    return f"/api/challenges/{cid}/manual-operations"


def test_manual_operation_recorded_event(client: TestClient, cid: str) -> None:
    response = client.post(manual_operation_url(cid), json=MANUAL_OPERATION)
    assert response.status_code == 201
    event = response.json()

    assert event["challenge_id"] == cid
    assert event["event_type"] == "manual_operation_recorded"
    assert event["actor"] == "user"
    assert event["sequence"] == 1
    assert event["artifact_ids"] == []
    assert event["payload"] == MANUAL_OPERATION_PAYLOAD

    events = client.get(f"/api/challenges/{cid}/events").json()
    assert events == [event]
    # A manual record can never masquerade as a tool execution.
    assert not any(item["event_type"].startswith("tool_") for item in events)
    assert client.get(f"/api/challenges/{cid}/integrity").json() == {
        "valid": True,
        "earliest_affected_sequence": None,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("actor", "tool"),
        ("event_hash", "a" * 64),
        ("sequence", 2),
        ("source_event_id", "00000000-0000-0000-0000-000000000000"),
        ("event_type", "tool_started"),
        ("occurred_at", "2020-01-01T00:00:00+00:00"),
    ],
)
def test_manual_operation_rejects_client_system_fields(
    client: TestClient, cid: str, field: str, value
) -> None:
    body = {**MANUAL_OPERATION, field: value}
    response = client.post(manual_operation_url(cid), json=body)
    assert response.status_code == 422
    assert client.get(f"/api/challenges/{cid}/events").json() == []


def test_manual_operation_validates_claims_and_limits(
    client: TestClient, cid: str
) -> None:
    invalid_bodies = [
        {"started_at_claim": "not-a-time"},
        {"finished_at_claim": "not-a-time"},
        {
            "started_at_claim": "2020-01-02T00:01:00+00:00",
            "finished_at_claim": "2020-01-01T00:00:00+00:00",
        },
        {"command": "a" * 4001},
        {"command": ""},
        {"working_directory": ""},
        {"purpose": "a" * 501},
    ]
    for extra in invalid_bodies:
        response = client.post(
            manual_operation_url(cid), json={**MANUAL_OPERATION, **extra}
        )
        assert response.status_code == 422, extra
    assert client.get(f"/api/challenges/{cid}/events").json() == []


# ---------------------------------------------------------------------------
# health, limits and restart persistence
# ---------------------------------------------------------------------------


def test_health_reports_manual_mode_and_import_limits(
    client: TestClient,
) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["execution_enabled"] is False
    assert body["manual_execution_mode"] == "manual_external"
    assert body["import_limits"] == {
        "max_files": DEFAULT_MAX_FILES,
        "max_file_bytes": DEFAULT_MAX_FILE_BYTES,
        "max_total_bytes": DEFAULT_MAX_TOTAL_BYTES,
        "max_compression_ratio": DEFAULT_MAX_COMPRESSION_RATIO,
    }


def test_import_limits_defaults_and_environment(monkeypatch) -> None:
    assert ImportLimits() == ImportLimits(
        max_files=DEFAULT_MAX_FILES,
        max_file_bytes=DEFAULT_MAX_FILE_BYTES,
        max_total_bytes=DEFAULT_MAX_TOTAL_BYTES,
        max_compression_ratio=DEFAULT_MAX_COMPRESSION_RATIO,
    )
    assert ImportLimits.from_env() == ImportLimits()

    monkeypatch.setenv("CTF_IMPORT_MAX_FILES", "7")
    monkeypatch.setenv("CTF_IMPORT_MAX_FILE_BYTES", "11")
    monkeypatch.setenv("CTF_IMPORT_MAX_TOTAL_BYTES", "13")
    monkeypatch.setenv("CTF_IMPORT_MAX_COMPRESSION_RATIO", "2.5")
    assert ImportLimits.from_env() == ImportLimits(
        max_files=7,
        max_file_bytes=11,
        max_total_bytes=13,
        max_compression_ratio=2.5,
    )

    monkeypatch.setenv("CTF_IMPORT_MAX_FILES", "0")
    with pytest.raises(ValueError):
        ImportLimits.from_env()


def test_import_limits_configurable_via_create_app(tmp_path: Path) -> None:
    limits = ImportLimits(
        max_files=3,
        max_file_bytes=4,
        max_total_bytes=5,
        max_compression_ratio=6.0,
    )
    with TestClient(create_app(tmp_path / "data", import_limits=limits)) as client:
        assert client.get("/api/health").json()["import_limits"] == {
            "max_files": 3,
            "max_file_bytes": 4,
            "max_total_bytes": 5,
            "max_compression_ratio": 6.0,
        }


def test_restart_keeps_project_rules_and_challenge_extensions(
    data_root: Path,
) -> None:
    with TestClient(create_app(data_root)) as first:
        first_project = create_project(
            first,
            project_name="Synthetic Project",
            competition_name="Synthetic Cup",
            competition_type="Jeopardy",
            ai_policy_summary="AI use allowed with disclosure",
        )
        rules = upload_rules(first)
        assert rules.status_code == 200
        challenge = first.post(
            "/api/challenges",
            json={
                "name": "Persistent",
                "category": "Misc",
                "ai_usage_level": "A1",
                "score": 250,
            },
        ).json()

    with TestClient(create_app(data_root)) as second:
        assert second.get("/api/project").json() == rules.json()
        download = second.get("/api/project/rules/content")
        assert download.status_code == 200
        assert download.content == SYNTHETIC_RULES

        challenges = second.get("/api/challenges").json()
        assert len(challenges) == 1
        assert challenges[0] == challenge
        assert challenges[0]["ai_usage_level"] == "A1"
        assert challenges[0]["score"] == 250
        assert challenges[0]["competition_name"] == "Synthetic Cup"
        assert first_project["project_id"] == rules.json()["project_id"]
