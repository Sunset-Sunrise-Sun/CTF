"""Acceptance tests for P1-1: attachment and evidence storage.

Every input is synthetic bytes constructed in this module.  No real challenge
attachment, real flag, or real target is used.  Each test isolates its data root
with ``tmp_path`` so nothing is written into the repository.

The tests must pass on Windows locally and on Linux CI (Python 3.11); platform
specific behaviour such as symlink creation is skipped when unavailable.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import sqlite3
import subprocess
import tempfile
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.artifacts import (
    DEFAULT_MAX_ARTIFACT_BYTES,
    ArtifactPathError,
    ArtifactStore,
    sanitize_filename,
)
from app.main import ArtifactBodyLimitMiddleware, ArtifactBodyTooLarge, create_app
from app.models import Challenge, Event
from app.store import Store, digest

EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
ARTIFACT_FIELDS = {
    "artifact_id",
    "challenge_id",
    "sha256",
    "size",
    "media_type",
    "original_filename",
    "ingested_at",
    "source_event_id",
    # Additive evidence metadata from the MVP artifact view.
    "evidence_kind",
    "capture_time_claim",
    "source_event_type",
    "source_event_sequence",
}
EVENT_PAYLOAD_FIELDS = {"artifact_id", "sha256", "size", "media_type"}
PNG_HEADER = b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def expected_blob(data_root: Path, sha256: str) -> Path:
    """Content-addressed blob path the implementation promises."""
    return data_root / "artifacts" / "sha256" / sha256[:2] / sha256[2:4] / sha256


def blob_files(data_root: Path) -> list[Path]:
    sha_dir = data_root / "artifacts" / "sha256"
    if not sha_dir.exists():
        return []
    return sorted(path for path in sha_dir.rglob("*") if path.is_file())


def staging_entries(data_root: Path) -> list[Path]:
    staging = data_root / "artifacts" / ".staging"
    return sorted(staging.iterdir()) if staging.is_dir() else []


def db_rows(data_root: Path, sql: str, params: tuple = ()) -> list[tuple]:
    connection = sqlite3.connect(data_root / "workbench.sqlite3", timeout=15)
    try:
        return list(connection.execute(sql, params))
    finally:
        connection.close()


def artifact_rows(data_root: Path, cid: str) -> list[tuple]:
    return db_rows(
        data_root,
        "SELECT artifact_id, challenge_id, sha256, size, media_type, "
        "original_filename, ingested_at, source_event_id FROM artifacts "
        "WHERE challenge_id=? ORDER BY rowid",
        (cid,),
    )


def event_rows(data_root: Path, cid: str) -> list[tuple]:
    return db_rows(
        data_root,
        "SELECT event_id, challenge_id, sequence, body FROM events "
        "WHERE challenge_id=? ORDER BY sequence",
        (cid,),
    )


def create_challenge(client: TestClient, name: str = "Synthetic") -> str:
    response = client.post("/api/challenges", json={"name": name, "category": "Misc"})
    assert response.status_code == 201
    return response.json()["challenge_id"]


def upload(
    client: TestClient,
    cid: str,
    data: bytes,
    *,
    filename: str = "sample.bin",
    content_type: str = "application/octet-stream",
):
    return client.post(
        f"/api/challenges/{cid}/artifacts",
        files={"file": (filename, data, content_type)},
    )


def assert_challenge_integrity(client: TestClient, cid: str, valid: bool) -> None:
    response = client.get(f"/api/challenges/{cid}/integrity")
    assert response.status_code == 200
    assert response.json()["valid"] is valid


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


@pytest.fixture
def cid(client: TestClient) -> str:
    return create_challenge(client)


@pytest.fixture
def other_cid(client: TestClient) -> str:
    return create_challenge(client, "Second")


# ---------------------------------------------------------------------------
# extra required tests first (referenced by the acceptance matrix)
# ---------------------------------------------------------------------------


def test_duplicate_upload(client: TestClient, data_root: Path, cid: str) -> None:
    payload = b"synthetic duplicate upload payload"
    first = upload(client, cid, payload, filename="original.bin")
    assert first.status_code == 201
    assert first.headers["X-Artifact-Deduplicated"] == "false"
    artifact = first.json()

    second = upload(client, cid, payload, filename="renamed.bin")
    assert second.status_code == 200
    assert second.headers["X-Artifact-Deduplicated"] == "true"
    assert second.json()["artifact_id"] == artifact["artifact_id"]
    assert second.json()["sha256"] == artifact["sha256"]

    assert len(client.get(f"/api/challenges/{cid}/artifacts").json()) == 1
    assert len(client.get(f"/api/challenges/{cid}/events").json()) == 1
    assert len(artifact_rows(data_root, cid)) == 1
    assert len(event_rows(data_root, cid)) == 1
    assert len(blob_files(data_root)) == 1
    assert blob_files(data_root)[0] == expected_blob(data_root, artifact["sha256"])
    assert_challenge_integrity(client, cid, True)


def test_cross_challenge_access_denied(
    client: TestClient, data_root: Path, cid: str, other_cid: str
) -> None:
    payload = PNG_HEADER + b"synthetic private evidence"
    artifact = upload(client, cid, payload, filename="private.png").json()
    other_artifact = upload(
        client, other_cid, b"synthetic other evidence", filename="other.bin"
    ).json()

    # Foreign challenge cannot see the artifact through any endpoint.
    for suffix in (
        f"/artifacts/{artifact['artifact_id']}",
        f"/artifacts/{artifact['artifact_id']}/content",
        f"/artifacts/{artifact['artifact_id']}/integrity",
    ):
        response = client.get(f"/api/challenges/{other_cid}{suffix}")
        assert response.status_code == 404, suffix

    # Listing and events are isolated per challenge.
    other_list = client.get(f"/api/challenges/{other_cid}/artifacts").json()
    assert [item["artifact_id"] for item in other_list] == [
        other_artifact["artifact_id"]
    ]
    assert all(item["artifact_id"] != artifact["artifact_id"] for item in other_list)
    other_events = client.get(f"/api/challenges/{other_cid}/events").json()
    assert all(
        event["payload"].get("artifact_id") != artifact["artifact_id"]
        for event in other_events
    )

    # Owner still has full access and the list order is unaffected.
    assert (
        client.get(
            f"/api/challenges/{cid}/artifacts/{artifact['artifact_id']}"
        ).status_code
        == 200
    )
    download = client.get(
        f"/api/challenges/{cid}/artifacts/{artifact['artifact_id']}/content"
    )
    assert download.status_code == 200
    assert download.content == payload
    assert len(artifact_rows(data_root, cid)) == 1
    assert len(artifact_rows(data_root, other_cid)) == 1


def test_file_tamper_detected(client: TestClient, data_root: Path, cid: str) -> None:
    payload = PNG_HEADER + b"synthetic tamper detection payload"
    artifact = upload(client, cid, payload, filename="tamper.png").json()
    blob = expected_blob(data_root, artifact["sha256"])
    assert blob.is_file()

    # The stored blob is made writable only for the synthetic tamper.
    os.chmod(blob, 0o600)
    blob.write_bytes(PNG_HEADER + b"synthetic TAMPERED bytes")

    download = client.get(
        f"/api/challenges/{cid}/artifacts/{artifact['artifact_id']}/content"
    )
    assert download.status_code == 409

    integrity = client.get(
        f"/api/challenges/{cid}/artifacts/{artifact['artifact_id']}/integrity"
    )
    assert integrity.status_code == 200
    assert integrity.json() == {
        "artifact_id": artifact["artifact_id"],
        "sha256": artifact["sha256"],
        "valid": False,
    }

    # Metadata is never rewritten by a content integrity failure.
    metadata = client.get(f"/api/challenges/{cid}/artifacts/{artifact['artifact_id']}")
    assert metadata.status_code == 200
    assert metadata.json() == artifact
    rows = artifact_rows(data_root, cid)
    assert len(rows) == 1
    assert rows[0][2] == artifact["sha256"]
    assert rows[0][7] == artifact["source_event_id"]
    # Tampering with a blob does not damage the event hash chain.
    assert_challenge_integrity(client, cid, True)


def test_database_failure_consistency(
    client: TestClient, data_root: Path, cid: str, monkeypatch
) -> None:
    payload = b"synthetic database outage payload"

    def fail_add_artifact(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic db outage")

    monkeypatch.setattr(client.app.state.store, "add_artifact", fail_add_artifact)

    response = upload(client, cid, payload)
    assert response.status_code == 500

    assert client.get(f"/api/challenges/{cid}/artifacts").json() == []
    assert client.get(f"/api/challenges/{cid}/events").json() == []
    assert artifact_rows(data_root, cid) == []
    assert event_rows(data_root, cid) == []
    # No orphaned blob and no staging residue after the rollback.
    assert not expected_blob(data_root, sha256_hex(payload)).exists()
    assert blob_files(data_root) == []
    assert staging_entries(data_root) == []


def test_database_failure_keeps_shared_blob(
    client: TestClient, data_root: Path, cid: str, other_cid: str, monkeypatch
) -> None:
    payload = b"synthetic shared blob payload"
    first = upload(client, cid, payload)
    assert first.status_code == 201
    artifact = first.json()
    sha256 = artifact["sha256"]
    blob = expected_blob(data_root, sha256)
    assert blob.is_file()

    def fail_add_artifact(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic db outage")

    monkeypatch.setattr(client.app.state.store, "add_artifact", fail_add_artifact)

    response = upload(client, other_cid, payload)
    assert response.status_code == 500

    # The blob is already referenced by another artifact, so it must survive.
    assert blob.is_file()
    assert blob.read_bytes() == payload
    assert artifact_rows(data_root, other_cid) == []
    assert event_rows(data_root, other_cid) == []
    download = client.get(
        f"/api/challenges/{cid}/artifacts/{artifact['artifact_id']}/content"
    )
    assert download.status_code == 200
    assert download.content == payload


def test_file_write_failure_consistency(
    client: TestClient, data_root: Path, cid: str, monkeypatch
) -> None:
    payload = b"synthetic disk outage payload"

    def fail_ingest(*args, **kwargs):
        raise OSError("synthetic disk outage")

    monkeypatch.setattr(client.app.state.artifacts, "ingest", fail_ingest)

    response = upload(client, cid, payload)
    assert response.status_code == 500

    assert client.get(f"/api/challenges/{cid}/artifacts").json() == []
    assert client.get(f"/api/challenges/{cid}/events").json() == []
    assert artifact_rows(data_root, cid) == []
    assert event_rows(data_root, cid) == []
    assert blob_files(data_root) == []
    assert staging_entries(data_root) == []


def test_restart_persistence(data_root: Path) -> None:
    payload = PNG_HEADER + b"synthetic persistence payload"
    with TestClient(create_app(data_root)) as first:
        cid = create_challenge(first)
        artifact = upload(first, cid, payload, filename="persist.png").json()
        event_before = first.get(f"/api/challenges/{cid}/events").json()

    # Direct Store access proves the metadata and event chain are on disk.
    store = Store(data_root / "workbench.sqlite3")
    assert store.verify(cid) == {
        "valid": True,
        "earliest_affected_sequence": None,
    }
    persisted = store.artifact(cid, artifact["artifact_id"])
    assert persisted.sha256 == artifact["sha256"]
    assert persisted.original_filename == "persist.png"
    assert [item.artifact_id for item in store.artifacts(cid)] == [
        artifact["artifact_id"]
    ]
    assert expected_blob(data_root, artifact["sha256"]).read_bytes() == payload

    # After a restart the same bytes still deduplicate into the same artifact.
    with TestClient(create_app(data_root)) as second:
        repeated = upload(second, cid, payload, filename="again.png")
        assert repeated.status_code == 200
        assert repeated.json()["artifact_id"] == artifact["artifact_id"]
        assert second.get(f"/api/challenges/{cid}/events").json() == event_before
        assert len(second.get(f"/api/challenges/{cid}/artifacts").json()) == 1


def test_event_hash_chain(client: TestClient, data_root: Path, cid: str) -> None:
    payload = b"synthetic event chain payload"
    artifact = upload(client, cid, payload).json()

    raw_rows = event_rows(data_root, cid)
    assert len(raw_rows) == 1
    event_id, challenge_id, _sequence, raw_body = raw_rows[0]
    assert challenge_id == cid
    body = json.loads(raw_body)
    event = Event.model_validate_json(raw_body)

    # Independently recompute the chain hash over the canonical event body.
    canonical = json.dumps(
        event.model_dump(exclude={"event_hash"}),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    assert event.event_hash == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert event.previous_event_hash == "0" * 64
    assert event.payload["artifact_id"] == artifact["artifact_id"]
    assert event.artifact_ids == [artifact["artifact_id"]]
    assert client.get(f"/api/challenges/{cid}/integrity").json() == {
        "valid": True,
        "earliest_affected_sequence": None,
    }

    # Tamper with the persisted event payload (triggers dropped like the
    # existing event-chain tamper tests do) and require verification to fail
    # at the earliest affected sequence.
    body["payload"]["size"] = body["payload"]["size"] + 1
    connection = sqlite3.connect(data_root / "workbench.sqlite3", timeout=15)
    try:
        connection.execute("DROP TRIGGER IF EXISTS events_no_update")
        connection.execute("DROP TRIGGER IF EXISTS events_no_delete")
        connection.execute(
            "UPDATE events SET body=? WHERE event_id=?",
            (json.dumps(body), event_id),
        )
        connection.commit()
    finally:
        connection.close()

    tampered = client.get(f"/api/challenges/{cid}/integrity")
    assert tampered.status_code == 200
    assert tampered.json() == {
        "valid": False,
        "earliest_affected_sequence": 1,
    }
    assert Store(data_root / "workbench.sqlite3").verify(cid) == {
        "valid": False,
        "earliest_affected_sequence": 1,
    }


def test_concurrent_duplicate_upload(
    client: TestClient, data_root: Path, cid: str
) -> None:
    payload = b"synthetic concurrent duplicate payload"
    workers = 8
    barrier = threading.Barrier(workers)

    def upload_once(_index: int):
        barrier.wait(timeout=15)
        return upload(client, cid, payload, filename="race.bin")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        responses = list(pool.map(upload_once, range(workers)))

    statuses = [response.status_code for response in responses]
    assert all(status in (200, 201) for status in statuses), statuses
    assert statuses.count(201) == 1, statuses
    artifact_ids = {response.json()["artifact_id"] for response in responses}
    assert len(artifact_ids) == 1

    artifact_id = artifact_ids.pop()
    assert len(client.get(f"/api/challenges/{cid}/artifacts").json()) == 1
    events = client.get(f"/api/challenges/{cid}/events").json()
    assert len(events) == 1
    assert events[0]["artifact_ids"] == [artifact_id]
    assert len(artifact_rows(data_root, cid)) == 1
    assert len(event_rows(data_root, cid)) == 1
    assert len(blob_files(data_root)) == 1
    blob = blob_files(data_root)[0]
    assert blob == expected_blob(data_root, sha256_hex(payload))
    assert blob.read_bytes() == payload
    assert_challenge_integrity(client, cid, True)


# ---------------------------------------------------------------------------
# security tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../evil.sh", "evil.sh"),
        ("..\\..\\evil.exe", "evil.exe"),
        ("C:\\Windows\\a.txt", "a.txt"),
        ("\\\\server\\share\\name.bin", "name.bin"),
        ("/etc/passwd", "passwd"),
        ('a:b*c?d"e<f>g|h.txt', "abcdefgh.txt"),
        ("evil\x00\x01\x1f.txt", "evil.txt"),
        ("", "upload.bin"),
        (None, "upload.bin"),
        (".", "upload.bin"),
        ("..", "upload.bin"),
        ("恶意/证据.txt", "证据.txt"),
        ("a" * 300, "a" * 255),
    ],
)
def test_filename_traversal_sanitized(raw, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_media_type_spoofing_ignored(client: TestClient, cid: str) -> None:
    cases = [
        ("text/plain", PNG_HEADER + b"synthetic png", "image/png"),
        ("image/png", b"\xff\xd8\xff\xe0synthetic jpeg", "image/jpeg"),
        ("text/html", b"%PDF-1.7\nsynthetic pdf", "application/pdf"),
        ("application/pdf", b"PK\x03\x04synthetic zip", "application/zip"),
        ("text/plain", b"\x7fELF\x02\x01\x01synthetic elf", "application/x-elf"),
        ("image/png", b"synthetic plain text payload\n", "text/plain"),
        ("text/plain", b"\x00\x01\x02synthetic binary", "application/octet-stream"),
    ]
    for client_type, payload, expected_media_type in cases:
        response = upload(
            client,
            cid,
            payload,
            filename=f"spoofed-{expected_media_type.replace('/', '-')}.bin",
            content_type=client_type,
        )
        assert response.status_code == 201, expected_media_type
        artifact = response.json()
        assert artifact["media_type"] == expected_media_type
        download = client.get(
            f"/api/challenges/{cid}/artifacts/{artifact['artifact_id']}/content"
        )
        assert download.status_code == 200
        assert download.headers["content-type"].split(";")[0] == expected_media_type
        assert download.content == payload
        assert download.headers["x-content-type-options"] == "nosniff"


def test_symbolic_link_escape_rejected(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    artifacts_root = data_root / "artifacts"
    artifacts_root.mkdir(parents=True)

    with tempfile.TemporaryDirectory() as outside:
        link = artifacts_root / "sha256"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("Symlink privilege unavailable")

        store = ArtifactStore(artifacts_root, max_bytes=1024)
        sha256 = "ab" * 32
        with pytest.raises(ArtifactPathError):
            store.blob_path(sha256)
        with pytest.raises(ArtifactPathError):
            store.ingest(io.BytesIO(b"synthetic escape attempt"), filename="x.bin")


def test_no_auto_extraction(client: TestClient, data_root: Path, cid: str) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("notes.txt", "synthetic note")
        archive.writestr("../escape.sh", "#!/bin/sh\necho synthetic")
    payload = buffer.getvalue()
    assert payload.startswith(b"PK\x03\x04")

    response = upload(client, cid, payload, filename="synthetic.zip")
    assert response.status_code == 201
    artifact = response.json()
    assert artifact["media_type"] == "application/zip"

    blobs = blob_files(data_root)
    assert blobs == [expected_blob(data_root, artifact["sha256"])]
    assert blobs[0].read_bytes() == payload

    # No archive member was materialised anywhere under the data root.
    assert list(data_root.rglob("notes.txt")) == []
    assert list(data_root.rglob("escape.sh")) == []
    allowed_names = {
        "workbench.sqlite3",
        "workbench.sqlite3-wal",
        "workbench.sqlite3-shm",
        artifact["sha256"],
    }
    extra_files = [
        path
        for path in data_root.rglob("*")
        if path.is_file() and path.name not in allowed_names
    ]
    assert extra_files == []


def test_no_sensitive_content_in_logs(
    client: TestClient, data_root: Path, cid: str, caplog
) -> None:
    content_sentinel = "SYNTHETIC-CONTENT-SENTINEL-7c1f9a"
    filename_sentinel = "SYNTHETIC-NAME-SENTINEL-3d2e8b"
    payload = ("synthetic payload " + content_sentinel).encode()

    with caplog.at_level(logging.DEBUG):
        response = upload(client, cid, payload, filename=f"{filename_sentinel}.bin")
    assert response.status_code == 201
    artifact = response.json()

    assert content_sentinel not in caplog.text
    assert filename_sentinel not in caplog.text

    # Neither sentinel may leak into the persisted event JSON.
    for _event_id, _challenge_id, _sequence, body in event_rows(data_root, cid):
        assert content_sentinel not in body
        assert filename_sentinel not in body
    events_text = client.get(f"/api/challenges/{cid}/events").text
    assert content_sentinel not in events_text
    assert filename_sentinel not in events_text

    # Content must not be echoed by the metadata-facing API responses.
    for path in (
        f"/api/challenges/{cid}/artifacts",
        f"/api/challenges/{cid}/artifacts/{artifact['artifact_id']}",
        f"/api/challenges/{cid}/artifacts/{artifact['artifact_id']}/integrity",
    ):
        assert content_sentinel not in client.get(path).text
    assert content_sentinel not in response.text

    # The filename is display metadata by contract, so it is only allowed to
    # appear in the artifact metadata field, never in logs or events.
    assert artifact["original_filename"] == f"{filename_sentinel}.bin"


def test_missing_blob_and_unknown_ids(
    client: TestClient, data_root: Path, cid: str
) -> None:
    unknown_cid = "00000000-0000-0000-0000-000000000000"
    unknown_artifact = "00000000-0000-0000-0000-00000000dead"

    assert client.get(f"/api/challenges/{unknown_cid}/artifacts").status_code == 404
    assert (
        client.get(
            f"/api/challenges/{unknown_cid}/artifacts/{unknown_artifact}"
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/challenges/{unknown_cid}/artifacts/{unknown_artifact}/content"
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/challenges/{unknown_cid}/artifacts/{unknown_artifact}/integrity"
        ).status_code
        == 404
    )
    assert (
        upload(client, unknown_cid, b"synthetic unknown challenge").status_code == 404
    )

    payload = b"synthetic missing blob payload"
    artifact = upload(client, cid, payload).json()
    for suffix in (
        "",
        "/content",
        "/integrity",
    ):
        response = client.get(
            f"/api/challenges/{cid}/artifacts/{unknown_artifact}{suffix}"
        )
        assert response.status_code == 404, suffix

    # Deleting the blob must be reported as an integrity failure, not a crash,
    # and metadata must stay readable.
    blob = expected_blob(data_root, artifact["sha256"])
    os.chmod(blob, 0o600)
    blob.unlink()
    assert blob_files(data_root) == []

    download = client.get(
        f"/api/challenges/{cid}/artifacts/{artifact['artifact_id']}/content"
    )
    assert download.status_code == 409
    integrity = client.get(
        f"/api/challenges/{cid}/artifacts/{artifact['artifact_id']}/integrity"
    )
    assert integrity.status_code == 200
    assert integrity.json()["valid"] is False
    metadata = client.get(f"/api/challenges/{cid}/artifacts/{artifact['artifact_id']}")
    assert metadata.status_code == 200
    assert metadata.json()["sha256"] == artifact["sha256"]
    assert_challenge_integrity(client, cid, True)


def test_empty_file_accepted(client: TestClient, data_root: Path, cid: str) -> None:
    response = upload(client, cid, b"", filename="empty.bin")
    assert response.status_code == 201
    artifact = response.json()
    assert artifact["size"] == 0
    assert artifact["sha256"] == EMPTY_SHA256
    assert artifact["media_type"] == "application/octet-stream"
    assert set(artifact) == ARTIFACT_FIELDS

    blob = expected_blob(data_root, EMPTY_SHA256)
    assert blob.is_file()
    assert blob.stat().st_size == 0
    assert staging_entries(data_root) == []

    download = client.get(
        f"/api/challenges/{cid}/artifacts/{artifact['artifact_id']}/content"
    )
    assert download.status_code == 200
    assert download.content == b""
    assert download.headers["x-content-type-options"] == "nosniff"
    integrity = client.get(
        f"/api/challenges/{cid}/artifacts/{artifact['artifact_id']}/integrity"
    )
    assert integrity.json()["valid"] is True

    repeated = upload(client, cid, b"", filename="empty-again.bin")
    assert repeated.status_code == 200
    assert repeated.json()["artifact_id"] == artifact["artifact_id"]


# ---------------------------------------------------------------------------
# A01-A12 acceptance matrix
# ---------------------------------------------------------------------------


def test_a01_upload_success_and_metadata(
    client: TestClient, data_root: Path, cid: str
) -> None:
    payload = b"synthetic evidence for a01"
    response = upload(client, cid, payload)
    assert response.status_code == 201
    assert response.headers["X-Artifact-Deduplicated"] == "false"

    artifact = response.json()
    assert set(artifact) == ARTIFACT_FIELDS
    assert artifact["challenge_id"] == cid
    assert artifact["sha256"] == sha256_hex(payload)
    assert artifact["size"] == len(payload)
    assert artifact["media_type"] == "text/plain"
    assert artifact["original_filename"] == "sample.bin"
    assert artifact["artifact_id"]
    assert artifact["source_event_id"]
    assert artifact["ingested_at"]

    listed = client.get(f"/api/challenges/{cid}/artifacts").json()
    assert [item["artifact_id"] for item in listed] == [artifact["artifact_id"]]
    assert expected_blob(data_root, artifact["sha256"]).is_file()


def test_a02_content_addressed_layout(
    client: TestClient, data_root: Path, cid: str
) -> None:
    payload = PNG_HEADER + b"synthetic a02 payload"
    response = upload(client, cid, payload, filename="../../evil.sh")
    assert response.status_code == 201

    artifact = response.json()
    sha256 = sha256_hex(payload)
    assert artifact["sha256"] == sha256
    assert artifact["original_filename"] == "evil.sh"

    blob = expected_blob(data_root, sha256)
    assert blob.is_file()
    assert blob.read_bytes() == payload
    assert blob.name == sha256
    assert blob.parent == (
        data_root / "artifacts" / "sha256" / sha256[:2] / sha256[2:4]
    )
    assert sha256 == sha256.lower()
    assert len(sha256) == 64
    assert blob_files(data_root) == [blob]

    # The client filename never becomes a path component.
    assert "evil" not in str(blob)
    assert list(data_root.rglob("evil.sh")) == []
    assert not (data_root / "artifacts" / "evil.sh").exists()

    # Staging is empty after a successful upload.
    assert staging_entries(data_root) == []


def test_a03_metadata_sqlite_persistence(
    client: TestClient, data_root: Path, cid: str
) -> None:
    payload = b"synthetic sqlite row payload"
    artifact = upload(client, cid, payload).json()

    rows = artifact_rows(data_root, cid)
    assert len(rows) == 1
    row = rows[0]
    assert row[0] == artifact["artifact_id"]
    assert row[1] == cid
    assert row[2] == sha256_hex(payload)
    assert row[3] == len(payload)
    assert row[4] == "text/plain"
    assert row[5] == "sample.bin"
    assert row[6] == artifact["ingested_at"]
    assert row[7] == artifact["source_event_id"]

    triggers = {
        name
        for (name,) in db_rows(
            data_root, "SELECT name FROM sqlite_master WHERE type='trigger'"
        )
    }
    assert {"artifacts_no_update", "artifacts_no_delete"} <= triggers
    table_sql = db_rows(
        data_root,
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='artifacts'",
    )[0][0]
    assert "UNIQUE(challenge_id, sha256)" in table_sql
    assert db_rows(data_root, "PRAGMA foreign_key_check") == []

    connection = sqlite3.connect(data_root / "workbench.sqlite3", timeout=15)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        for statement in (
            "UPDATE artifacts SET size=0",
            "DELETE FROM artifacts",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(statement)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?)",
                (
                    "00000000-0000-0000-0000-00000000cafe",
                    cid,
                    artifact["sha256"],
                    len(payload),
                    "text/plain",
                    "duplicate.bin",
                    artifact["ingested_at"],
                    artifact["source_event_id"],
                ),
            )
    finally:
        connection.close()

    assert len(artifact_rows(data_root, cid)) == 1


def test_a04_artifact_added_event(
    client: TestClient, data_root: Path, cid: str
) -> None:
    payload = b"synthetic event payload"
    artifact = upload(client, cid, payload).json()

    events = client.get(f"/api/challenges/{cid}/events").json()
    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "artifact_added"
    assert event["actor"] == "user"
    assert set(event["payload"]) == EVENT_PAYLOAD_FIELDS
    assert event["payload"]["artifact_id"] == artifact["artifact_id"]
    assert event["payload"]["sha256"] == artifact["sha256"]
    assert event["payload"]["size"] == len(payload)
    assert event["payload"]["media_type"] == artifact["media_type"]
    assert event["artifact_ids"] == [artifact["artifact_id"]]
    assert event["challenge_id"] == cid

    # Duplicate upload creates no additional event.
    repeated = upload(client, cid, payload, filename="duplicate.bin")
    assert repeated.status_code == 200
    events_after = client.get(f"/api/challenges/{cid}/events").json()
    assert len(events_after) == 1
    assert events_after[0]["event_id"] == event["event_id"]
    assert len(event_rows(data_root, cid)) == 1


def test_a05_artifact_challenge_event_linkage(
    client: TestClient, data_root: Path, cid: str, other_cid: str
) -> None:
    payload = b"synthetic linkage payload"
    artifact = upload(client, cid, payload).json()
    events = client.get(f"/api/challenges/{cid}/events").json()
    assert len(events) == 1
    event = events[0]

    assert artifact["challenge_id"] == cid
    assert artifact["source_event_id"] == event["event_id"]
    assert event["challenge_id"] == cid
    assert event["artifact_ids"] == [artifact["artifact_id"]]
    assert event["payload"]["artifact_id"] == artifact["artifact_id"]

    raw_event = event_rows(data_root, cid)
    assert len(raw_event) == 1
    assert raw_event[0][0] == event["event_id"]
    assert raw_event[0][1] == cid
    body = json.loads(raw_event[0][3])
    assert body["artifact_ids"] == [artifact["artifact_id"]]
    assert body["payload"]["sha256"] == artifact["sha256"]
    assert body["challenge_id"] == cid

    # Every foreign key in the evidence schema resolves.
    assert db_rows(data_root, "PRAGMA foreign_key_check") == []

    # The other challenge has no artifacts/events and cannot see this one.
    assert client.get(f"/api/challenges/{other_cid}/artifacts").json() == []
    assert client.get(f"/api/challenges/{other_cid}/events").json() == []


def test_a06_artifact_listing(
    client: TestClient, data_root: Path, cid: str, other_cid: str
) -> None:
    payloads = [f"synthetic listing {index}".encode() for index in range(3)]
    artifact_ids = []
    for index, payload in enumerate(payloads):
        response = upload(client, cid, payload, filename=f"listing-{index}.bin")
        assert response.status_code == 201
        artifact_ids.append(response.json()["artifact_id"])

    listed = client.get(f"/api/challenges/{cid}/artifacts")
    assert listed.status_code == 200
    body = listed.json()
    assert [item["artifact_id"] for item in body] == artifact_ids
    assert [item["size"] for item in body] == [len(payload) for payload in payloads]
    assert all(item["challenge_id"] == cid for item in body)

    # Challenge isolation.
    assert client.get(f"/api/challenges/{other_cid}/artifacts").json() == []
    assert len(artifact_rows(data_root, cid)) == 3

    # A deduplicated re-upload does not append to the listing.
    assert upload(client, cid, payloads[0]).status_code == 200
    assert [
        item["artifact_id"]
        for item in client.get(f"/api/challenges/{cid}/artifacts").json()
    ] == artifact_ids


def test_a07_artifact_metadata_lookup(
    client: TestClient, cid: str, other_cid: str
) -> None:
    payload = b"synthetic metadata lookup payload"
    artifact = upload(client, cid, payload).json()

    response = client.get(f"/api/challenges/{cid}/artifacts/{artifact['artifact_id']}")
    assert response.status_code == 200
    assert response.json() == artifact

    unknown_artifact = "00000000-0000-0000-0000-00000000dead"
    assert (
        client.get(f"/api/challenges/{cid}/artifacts/{unknown_artifact}").status_code
        == 404
    )
    assert (
        client.get(
            f"/api/challenges/missing-challenge/artifacts/{artifact['artifact_id']}"
        ).status_code
        == 404
    )

    foreign = upload(client, other_cid, b"synthetic foreign payload").json()
    assert (
        client.get(
            f"/api/challenges/{cid}/artifacts/{foreign['artifact_id']}"
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/challenges/{other_cid}/artifacts/{artifact['artifact_id']}"
        ).status_code
        == 404
    )


def test_a08_download_content_and_headers(
    client: TestClient, cid: str, other_cid: str
) -> None:
    payload = PNG_HEADER + b"synthetic download payload"
    artifact = upload(
        client,
        cid,
        payload,
        filename="../../evil.png",
        content_type="text/plain",
    ).json()

    download = client.get(
        f"/api/challenges/{cid}/artifacts/{artifact['artifact_id']}/content"
    )
    assert download.status_code == 200
    assert download.content == payload
    assert download.headers["content-type"].split(";")[0] == "image/png"
    assert download.headers["x-content-type-options"] == "nosniff"
    disposition = download.headers["content-disposition"]
    assert "attachment" in disposition
    assert "evil.png" in disposition
    assert "evil.sh" not in disposition
    assert "../../evil.png" not in disposition

    foreign = upload(client, other_cid, b"synthetic foreign payload").json()
    assert (
        client.get(
            f"/api/challenges/{cid}/artifacts/{foreign['artifact_id']}/content"
        ).status_code
        == 404
    )
    unknown_artifact = "00000000-0000-0000-0000-00000000dead"
    assert (
        client.get(
            f"/api/challenges/{cid}/artifacts/{unknown_artifact}/content"
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/challenges/missing-challenge/artifacts/"
            f"{artifact['artifact_id']}/content"
        ).status_code
        == 404
    )


def test_a09_content_deduplication(
    client: TestClient, data_root: Path, cid: str, other_cid: str
) -> None:
    payload = b"synthetic deduplication payload"
    first = upload(client, cid, payload, filename="first.bin")
    assert first.status_code == 201
    artifact = first.json()

    second = upload(client, cid, payload, filename="second.bin")
    assert second.status_code == 200
    assert second.headers["X-Artifact-Deduplicated"] == "true"
    assert second.json()["artifact_id"] == artifact["artifact_id"]
    assert len(artifact_rows(data_root, cid)) == 1
    assert len(event_rows(data_root, cid)) == 1
    assert len(blob_files(data_root)) == 1

    cross = upload(client, other_cid, payload, filename="cross.bin")
    assert cross.status_code == 201
    assert cross.headers["X-Artifact-Deduplicated"] == "false"
    cross_artifact = cross.json()
    assert cross_artifact["artifact_id"] != artifact["artifact_id"]
    assert cross_artifact["sha256"] == artifact["sha256"]
    assert cross_artifact["challenge_id"] == other_cid

    # Two metadata rows but a single shared blob on disk.
    assert len(blob_files(data_root)) == 1
    assert blob_files(data_root)[0] == expected_blob(data_root, artifact["sha256"])
    assert len(artifact_rows(data_root, cid)) == 1
    assert len(artifact_rows(data_root, other_cid)) == 1
    assert len(event_rows(data_root, cid)) == 1
    assert len(event_rows(data_root, other_cid)) == 1

    cross_again = upload(client, other_cid, payload)
    assert cross_again.status_code == 200
    assert cross_again.json()["artifact_id"] == cross_artifact["artifact_id"]


def test_a10_append_only_and_content_integrity(
    client: TestClient, data_root: Path, cid: str
) -> None:
    payload = b"synthetic append-only payload"
    artifact = upload(client, cid, payload).json()
    artifact_url = f"/api/challenges/{cid}/artifacts/{artifact['artifact_id']}"

    for method in ("PUT", "PATCH", "DELETE"):
        assert client.request(method, artifact_url).status_code == 405, method
    assert client.request("DELETE", f"{artifact_url}/content").status_code == 405

    connection = sqlite3.connect(data_root / "workbench.sqlite3", timeout=15)
    try:
        for statement in (
            "UPDATE artifacts SET size=0",
            "DELETE FROM artifacts",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(statement)
    finally:
        connection.close()
    rows = artifact_rows(data_root, cid)
    assert len(rows) == 1
    assert rows[0][2] == artifact["sha256"]

    # Baseline integrity is valid, then a tampered blob is detected on read.
    integrity = client.get(f"{artifact_url}/integrity")
    assert integrity.status_code == 200
    assert integrity.json() == {
        "artifact_id": artifact["artifact_id"],
        "sha256": artifact["sha256"],
        "valid": True,
    }
    os.chmod(expected_blob(data_root, artifact["sha256"]), 0o600)
    expected_blob(data_root, artifact["sha256"]).write_bytes(b"synthetic tampered")
    assert client.get(f"{artifact_url}/content").status_code == 409
    assert client.get(f"{artifact_url}/integrity").json()["valid"] is False

    # Read-only evidence endpoints remain available after the tamper.
    assert client.get(artifact_url).status_code == 200
    assert client.get(artifact_url).json()["sha256"] == artifact["sha256"]
    assert artifact_rows(data_root, cid)[0][2] == artifact["sha256"]


def test_a11_size_limit_default_and_configurable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CTF_MAX_ARTIFACT_BYTES", raising=False)
    assert DEFAULT_MAX_ARTIFACT_BYTES == 50 * 1024 * 1024

    default_app = create_app(tmp_path / "default-root")
    assert default_app.state.max_artifact_bytes == DEFAULT_MAX_ARTIFACT_BYTES

    limited_root = tmp_path / "limited-root"
    with TestClient(create_app(limited_root, max_artifact_bytes=10)) as limited:
        cid = create_challenge(limited)
        oversized = upload(limited, cid, b"x" * 11)
        assert oversized.status_code == 413

        # A rejected upload leaves no artifact, event, blob, or staging file.
        assert artifact_rows(limited_root, cid) == []
        assert event_rows(limited_root, cid) == []
        assert limited.get(f"/api/challenges/{cid}/artifacts").json() == []
        assert limited.get(f"/api/challenges/{cid}/events").json() == []
        assert blob_files(limited_root) == []
        assert staging_entries(limited_root) == []
        assert not expected_blob(limited_root, sha256_hex(b"x" * 11)).exists()

        # The configured limit is exposed and the exact boundary is accepted.
        assert limited.get("/api/health").json()["artifact_max_bytes"] == 10
        exact = upload(limited, cid, b"y" * 10)
        assert exact.status_code == 201
        assert exact.json()["size"] == 10
        assert expected_blob(limited_root, sha256_hex(b"y" * 10)).is_file()


def test_a12_restart_keeps_artifacts(data_root: Path) -> None:
    payloads = [
        PNG_HEADER + b"synthetic restart one",
        b"%PDF-1.7\nsynthetic restart two",
    ]

    with TestClient(create_app(data_root)) as first:
        cid = create_challenge(first)
        artifacts = [
            upload(first, cid, payload, filename=f"restart-{index}.bin").json()
            for index, payload in enumerate(payloads)
        ]
        events_before = first.get(f"/api/challenges/{cid}/events").json()

    with TestClient(create_app(data_root)) as second:
        listed = second.get(f"/api/challenges/{cid}/artifacts")
        assert listed.status_code == 200
        assert [item["artifact_id"] for item in listed.json()] == [
            artifact["artifact_id"] for artifact in artifacts
        ]
        for payload, artifact in zip(payloads, artifacts):
            metadata = second.get(
                f"/api/challenges/{cid}/artifacts/{artifact['artifact_id']}"
            )
            assert metadata.status_code == 200
            assert metadata.json() == artifact
            download = second.get(
                f"/api/challenges/{cid}/artifacts/{artifact['artifact_id']}/content"
            )
            assert download.status_code == 200
            assert download.content == payload
            integrity = second.get(
                f"/api/challenges/{cid}/artifacts/{artifact['artifact_id']}/integrity"
            )
            assert integrity.status_code == 200
            assert integrity.json() == {
                "artifact_id": artifact["artifact_id"],
                "sha256": artifact["sha256"],
                "valid": True,
            }
        assert second.get(f"/api/challenges/{cid}/events").json() == events_before
        assert_challenge_integrity(second, cid, True)
        assert staging_entries(data_root) == []


# ---------------------------------------------------------------------------
# hardening tests added after independent security review
# ---------------------------------------------------------------------------


def test_http_body_limit_rejects_declared_oversize_before_buffering() -> None:
    """A declared Content-Length above the cap is refused before parsing."""
    calls: list[str] = []
    messages: list[dict] = []

    async def downstream(scope, receive, send):
        calls.append("downstream")

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/challenges/synthetic/artifacts",
        "headers": [(b"content-length", str(10**9).encode())],
    }
    asyncio.run(ArtifactBodyLimitMiddleware(downstream, 1024)(scope, receive, send))

    start = next(
        message for message in messages if message["type"] == "http.response.start"
    )
    assert start["status"] == 413
    assert calls == []


def test_http_body_limit_counts_chunked_bodies() -> None:
    """Chunked bodies are counted and abort once the cap is exceeded."""
    chunks = [
        {"type": "http.request", "body": b"x" * 600, "more_body": True},
        {"type": "http.request", "body": b"x" * 600, "more_body": False},
    ]

    async def receive():
        return chunks.pop(0)

    async def downstream(scope, receive, send):
        while True:
            message = await receive()
            if not message.get("more_body"):
                return

    async def send(message):
        pass

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/challenges/synthetic/artifacts",
        "headers": [],
    }
    with pytest.raises(ArtifactBodyTooLarge):
        asyncio.run(ArtifactBodyLimitMiddleware(downstream, 1024)(scope, receive, send))


def test_recursive_replace_cannot_bypass_append_only(tmp_path: Path) -> None:
    """INSERT OR REPLACE must fire the append-only DELETE trigger."""
    store = Store(tmp_path / "append.db")
    challenge = Challenge(name="Synthetic", category="Misc")
    store.create(challenge)
    artifact, event = store.add_artifact(
        challenge.challenge_id,
        sha256="a" * 64,
        size=1,
        media_type="text/plain",
        original_filename="a.bin",
    )
    with pytest.raises(sqlite3.IntegrityError):
        with store.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO artifacts VALUES (?,?,?,?,?,?,?,?)",
                (
                    artifact.artifact_id,
                    challenge.challenge_id,
                    "b" * 64,
                    2,
                    "text/plain",
                    "b.bin",
                    "2000-01-01T00:00:00+00:00",
                    event.event_id,
                ),
            )


def test_junction_escape_rejected(tmp_path: Path) -> None:
    """A Windows directory junction pointing outside is refused (POSIX: symlink)."""
    if os.name != "nt":
        pytest.skip("Windows junction test; POSIX symlink covered above")
    artifacts_root = tmp_path / "data" / "artifacts"
    artifacts_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = artifacts_root / "sha256"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip("Junction creation unavailable")
    store = ArtifactStore(artifacts_root, max_bytes=1024)
    with pytest.raises(ArtifactPathError):
        store.blob_path("ab" * 32)
    with pytest.raises(ArtifactPathError):
        store.ingest(io.BytesIO(b"synthetic junction escape"), filename="x.bin")


# ---------------------------------------------------------------------------
# artifact <-> source event association constraints (002 migration fix)
# ---------------------------------------------------------------------------


def insert_artifact_row(
    data_root: Path,
    *,
    artifact_id: str,
    challenge_id: str,
    sha256: str,
    source_event_id: str,
) -> None:
    """Insert an artifact row directly so constraint violations can be tested."""
    connection = sqlite3.connect(data_root / "workbench.sqlite3", timeout=15)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        with connection:
            connection.execute(
                "INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?)",
                (
                    artifact_id,
                    challenge_id,
                    sha256,
                    4,
                    "text/plain",
                    "synthetic.bin",
                    "2026-11-07T00:00:00+00:00",
                    source_event_id,
                ),
            )
    finally:
        connection.close()


def test_source_event_is_unique_per_artifact(
    client: TestClient, data_root: Path, cid: str
) -> None:
    """One event must not be the source event of two artifacts."""
    uploaded = upload(client, cid, b"synthetic unique source event").json()
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        insert_artifact_row(
            data_root,
            artifact_id="00000000-0000-0000-0000-0000000000aa",
            challenge_id=cid,
            sha256="b" * 64,
            source_event_id=uploaded["source_event_id"],
        )
    assert [
        item["artifact_id"]
        for item in client.get(f"/api/challenges/{cid}/artifacts").json()
    ] == [uploaded["artifact_id"]]
    assert_challenge_integrity(client, cid, True)


def test_artifact_cannot_reference_other_challenge_event(
    client: TestClient, data_root: Path, cid: str, other_cid: str
) -> None:
    """The composite foreign key keeps artifact and source event in one challenge."""
    foreign_event = client.post(
        f"/api/challenges/{cid}/notes",
        json={"text": "synthetic event owned by another challenge"},
    ).json()
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        insert_artifact_row(
            data_root,
            artifact_id="00000000-0000-0000-0000-0000000000bb",
            challenge_id=other_cid,
            sha256="c" * 64,
            source_event_id=foreign_event["event_id"],
        )
    assert client.get(f"/api/challenges/{other_cid}/artifacts").json() == []
    assert_challenge_integrity(client, cid, True)
    assert_challenge_integrity(client, other_cid, True)


def test_constraints_keep_upload_dedupe_and_cross_challenge_behavior(
    client: TestClient, data_root: Path, cid: str, other_cid: str
) -> None:
    """Normal upload, same-challenge dedupe and cross-challenge copies still work."""
    payload = b"synthetic constraints regression payload"
    first = upload(client, cid, payload)
    assert first.status_code == 201
    artifact = first.json()

    repeated = upload(client, cid, payload, filename="again.bin")
    assert repeated.status_code == 200
    assert repeated.json()["artifact_id"] == artifact["artifact_id"]
    assert len(client.get(f"/api/challenges/{cid}/events").json()) == 1

    across = upload(client, other_cid, payload, filename="copy.bin")
    assert across.status_code == 201
    copy = across.json()
    assert copy["artifact_id"] != artifact["artifact_id"]
    assert copy["sha256"] == artifact["sha256"]
    assert copy["source_event_id"] != artifact["source_event_id"]
    assert len(client.get(f"/api/challenges/{other_cid}/events").json()) == 1

    assert len(blob_files(data_root)) == 1
    assert_challenge_integrity(client, cid, True)
    assert_challenge_integrity(client, other_cid, True)


def test_migration_preserves_p0_data_and_adds_relation_constraints(
    tmp_path: Path,
) -> None:
    """A P0 (001 only) database upgrades and keeps its challenges/events/chain."""
    data_root = tmp_path / "p0-data"
    data_root.mkdir()
    db_path = data_root / "workbench.sqlite3"
    challenge = Challenge(name="Synthetic P0 migration", category="Crypto")
    event = Event(
        challenge_id=challenge.challenge_id,
        sequence=1,
        actor="user",
        event_type="note",
        payload={"text": "synthetic P0 note"},
        previous_event_hash="0" * 64,
    )
    event.event_hash = digest(event)

    connection = sqlite3.connect(db_path)
    try:
        connection.executescript("PRAGMA foreign_keys=ON;")
        connection.executescript(
            "CREATE TABLE schema_migrations (version TEXT PRIMARY KEY);"
        )
        connection.executescript(
            (
                Path(__file__).parent.parent / "app/migrations/001_initial.sql"
            ).read_text()
        )
        connection.execute("INSERT INTO schema_migrations VALUES ('001_initial.sql')")
        connection.execute(
            "INSERT INTO challenges VALUES (?,?)",
            (challenge.challenge_id, challenge.model_dump_json()),
        )
        connection.execute(
            "INSERT INTO events VALUES (?,?,?,?)",
            (
                event.event_id,
                challenge.challenge_id,
                event.sequence,
                event.model_dump_json(),
            ),
        )
        connection.execute(
            "INSERT INTO event_heads VALUES (?,?,?)",
            (challenge.challenge_id, event.sequence, event.event_hash),
        )
        connection.commit()
    finally:
        connection.close()

    # Opening the store applies 002_artifacts.sql to the existing P0 database.
    upgraded = Store(db_path)
    assert upgraded.get(challenge.challenge_id).name == challenge.name
    assert [item.sequence for item in upgraded.events(challenge.challenge_id)] == [1]
    assert upgraded.verify(challenge.challenge_id) == {
        "valid": True,
        "earliest_affected_sequence": None,
    }
    with upgraded.connect() as db:
        versions = [
            row[0]
            for row in db.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        event_indexes = {row[1] for row in db.execute("PRAGMA index_list(events)")}
        artifact_fks = {
            (row[2], row[3], row[4])
            for row in db.execute("PRAGMA foreign_key_list(artifacts)")
        }
    assert versions == ["001_initial.sql", "002_artifacts.sql"]
    assert "events_challenge_event" in event_indexes
    assert ("events", "challenge_id", "challenge_id") in artifact_fks
    assert ("events", "source_event_id", "event_id") in artifact_fks

    # The upgraded database still serves P0 data and accepts a new artifact.
    with TestClient(create_app(data_root)) as client:
        listed = client.get("/api/challenges").json()
        assert [item["challenge_id"] for item in listed] == [challenge.challenge_id]
        events = client.get(f"/api/challenges/{challenge.challenge_id}/events").json()
        assert [item["event_id"] for item in events] == [event.event_id]
        assert_challenge_integrity(client, challenge.challenge_id, True)
        uploaded = upload(
            client, challenge.challenge_id, b"synthetic post-upgrade artifact"
        )
        assert uploaded.status_code == 201
        assert_challenge_integrity(client, challenge.challenge_id, True)
