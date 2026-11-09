import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.models import Challenge
from app.store import Store
from app.workspace import Workspace


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.db")
    s.create(
        Challenge(
            challenge_id="00000000-0000-0000-0000-000000000001",
            name="Synthetic",
            category="Misc",
        )
    )
    return s


CID = "00000000-0000-0000-0000-000000000001"


def test_api(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/health").status_code == 200
        fixtures = json.loads(
            (Path(__file__).parent / "fixtures/challenges.json").read_text()
        )
        for fixture in fixtures:
            c = client.post("/api/challenges", json=fixture).json()
            assert (
                c["solve_status"] == "unknown"
                and c["writeup_status"] == "not_generated"
            )
        assert (
            client.post(
                "/api/challenges", json={"name": "bad", "category": "OSINT"}
            ).status_code
            == 422
        )
        cid = c["challenge_id"]
        e = client.post(
            f"/api/challenges/{cid}/notes",
            json={"text": "Synthetic retrospective", "retrospective": True},
        ).json()
        assert e["actor"] == "user" and e["payload"]["retrospective"]
        assert client.get(f"/api/challenges/{cid}/integrity").json()["valid"]
        assert (
            client.post(
                f"/api/challenges/{cid}/notes",
                json={"text": "x", "actor": "tool", "occurred_at": "y"},
            ).status_code
            == 422
        )
        assert client.get("/api/challenges/missing/events").status_code == 404
        tool_catalog = client.get("/api/tools").json()
        assert {item["name"] for item in tool_catalog["tools"]} == {
            "file_inspect",
            "sha256",
            "stat",
            "strings",
            "list_files",
            "image_info",
            "text_decode",
        }
        assert tool_catalog["execution_enabled"] is False
        assert tool_catalog["read_only_tool_execution_enabled"] is True


def test_migrations_and_append_only(store):
    Store(store.path)
    e = store.append(
        CID, "agent", "agent_message", {"text": "command succeeded (unverified claim)"}
    )
    assert e.event_type == "agent_message"
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 3
        for sql in ["UPDATE events SET sequence=2", "DELETE FROM events"]:
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(sql)


def test_concurrent_sequence(store):
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: store.append(CID, "user", "note", {"n": n}), range(20)))
    assert [e.sequence for e in store.events(CID)] == list(range(1, 21))
    assert store.verify(CID)["valid"]


@pytest.mark.parametrize("mode", ["modify", "remove", "reorder", "insert", "tail"])
def test_w07_tamper(store, mode):
    for n in range(3):
        store.append(CID, "user", "note", {"n": n})
    with store.connect() as db:
        db.execute("DROP TRIGGER events_no_update")
        db.execute("DROP TRIGGER events_no_delete")
        if mode in ("remove", "tail"):
            db.execute(
                "DELETE FROM events WHERE sequence=?", (2 if mode == "remove" else 3,)
            )
        else:
            row = db.execute("SELECT body FROM events WHERE sequence=2").fetchone()[0]
            body = json.loads(row)
            if mode == "modify":
                body["payload"] = {"n": 999}
            elif mode == "reorder":
                body["sequence"] = 1
            else:
                body["previous_event_hash"] = "f" * 64
            db.execute("UPDATE events SET body=? WHERE sequence=2", (json.dumps(body),))
    assert store.verify(CID) == {
        "valid": False,
        "earliest_affected_sequence": 3 if mode == "tail" else 2,
    }


@pytest.mark.parametrize(
    "path", ["../escape", "/escape", "C:/escape", "x/../../escape", "x:stream"]
)
def test_boundary(tmp_path, path):
    with pytest.raises(ValueError):
        Workspace(tmp_path).resolve(path)


def test_symlink(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    try:
        (root / "escape").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink privilege unavailable")
    with pytest.raises(ValueError):
        Workspace(root).resolve("escape/file")
