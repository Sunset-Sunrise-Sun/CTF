import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from .models import Challenge, Event


def canonical(value: dict) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest(event: Event) -> str:
    return hashlib.sha256(
        canonical(event.model_dump(exclude={"event_hash"})).encode("utf-8")
    ).hexdigest()


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY)"
            )
            for migration in sorted(
                (Path(__file__).parent / "migrations").glob("*.sql")
            ):
                if not db.execute(
                    "SELECT 1 FROM schema_migrations WHERE version=?", (migration.name,)
                ).fetchone():
                    # executescript starts its own transaction; migration and marker commit together.
                    db.executescript(
                        "BEGIN IMMEDIATE;"
                        + migration.read_text()
                        + "INSERT INTO schema_migrations VALUES ('"
                        + migration.name
                        + "'); COMMIT;"
                    )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, challenge: Challenge):
        with self.connect() as db:
            db.execute(
                "INSERT INTO challenges VALUES (?,?)",
                (challenge.challenge_id, challenge.model_dump_json()),
            )

    def challenges(self) -> list[Challenge]:
        with self.connect() as db:
            return [
                Challenge.model_validate_json(r[0])
                for r in db.execute("SELECT body FROM challenges ORDER BY rowid")
            ]

    def get(self, cid: str) -> Challenge:
        with self.connect() as db:
            row = db.execute(
                "SELECT body FROM challenges WHERE challenge_id=?", (cid,)
            ).fetchone()
            if row is None:
                raise KeyError(cid)
            return Challenge.model_validate_json(row[0])

    def events(self, cid: str) -> list[Event]:
        self.get(cid)
        with self.connect() as db:
            return [
                Event.model_validate_json(r[0])
                for r in db.execute(
                    "SELECT body FROM events WHERE challenge_id=? ORDER BY sequence",
                    (cid,),
                )
            ]

    def append(self, cid: str, actor: str, event_type: str, payload: dict) -> Event:
        self.get(cid)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            head = db.execute(
                "SELECT sequence,event_hash FROM event_heads WHERE challenge_id=?",
                (cid,),
            ).fetchone()
            event = Event(
                challenge_id=cid,
                sequence=head[0] + 1 if head else 1,
                actor=actor,
                event_type=event_type,
                payload=payload,
                previous_event_hash=head[1] if head else "0" * 64,
            )
            event.event_hash = digest(event)
            db.execute(
                "INSERT INTO events VALUES (?,?,?,?)",
                (event.event_id, cid, event.sequence, event.model_dump_json()),
            )
            db.execute(
                "INSERT INTO event_heads VALUES (?,?,?) ON CONFLICT(challenge_id) DO UPDATE SET sequence=excluded.sequence,event_hash=excluded.event_hash",
                (cid, event.sequence, event.event_hash),
            )
            return event

    def verify(self, cid: str) -> dict:
        previous = "0" * 64
        events = self.events(cid)
        for index, event in enumerate(events, 1):
            if (
                event.sequence != index
                or event.previous_event_hash != previous
                or digest(event) != event.event_hash
                or event.challenge_id != cid
            ):
                return {"valid": False, "earliest_affected_sequence": index}
            previous = event.event_hash
        with self.connect() as db:
            head = db.execute(
                "SELECT sequence,event_hash FROM event_heads WHERE challenge_id=?",
                (cid,),
            ).fetchone()
        if head and (head[0] != len(events) or head[1] != previous):
            return {"valid": False, "earliest_affected_sequence": len(events) + 1}
        return {"valid": True, "earliest_affected_sequence": None}
