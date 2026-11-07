import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .models import Artifact, Challenge, Event, now, uid


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


ARTIFACT_COLUMNS = (
    "artifact_id, challenge_id, sha256, size, media_type, "
    "original_filename, ingested_at, source_event_id"
)


def _artifact_from_row(row) -> Artifact:
    return Artifact(
        artifact_id=row[0],
        challenge_id=row[1],
        sha256=row[2],
        size=row[3],
        media_type=row[4],
        original_filename=row[5],
        ingested_at=row[6],
        source_event_id=row[7],
    )


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
        # INSERT OR REPLACE on an append-only table must still fire the
        # DELETE trigger, so a REPLACE cannot silently rewrite evidence rows.
        db.execute("PRAGMA recursive_triggers=ON")
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

    @staticmethod
    def _append_event(
        db,
        cid: str,
        actor: str,
        event_type: str,
        payload: dict,
        artifact_ids: tuple[str, ...] = (),
    ) -> Event:
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
            artifact_ids=list(artifact_ids),
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

    def append(self, cid: str, actor: str, event_type: str, payload: dict) -> Event:
        self.get(cid)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._append_event(db, cid, actor, event_type, payload)

    def add_artifact(
        self,
        cid: str,
        *,
        sha256: str,
        size: int,
        media_type: str,
        original_filename: str,
    ) -> tuple[Artifact, Event | None]:
        """Persist artifact metadata and its artifact_added event atomically.

        Identical bytes in the same challenge are deduplicated: the existing
        artifact is returned with no new event.  The same bytes in a different
        challenge produce a distinct artifact ID that reuses the content blob.
        """
        self.get(cid)
        try:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute(
                    "SELECT " + ARTIFACT_COLUMNS + " FROM artifacts "
                    "WHERE challenge_id=? AND sha256=?",
                    (cid, sha256),
                ).fetchone()
                if existing is not None:
                    return _artifact_from_row(existing), None
                artifact_id = uid()
                ingested_at = now()
                event = self._append_event(
                    db,
                    cid,
                    "user",
                    "artifact_added",
                    {
                        "artifact_id": artifact_id,
                        "sha256": sha256,
                        "size": size,
                        "media_type": media_type,
                    },
                    artifact_ids=(artifact_id,),
                )
                db.execute(
                    "INSERT INTO artifacts (" + ARTIFACT_COLUMNS + ") "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        artifact_id,
                        cid,
                        sha256,
                        size,
                        media_type,
                        original_filename,
                        ingested_at,
                        event.event_id,
                    ),
                )
                return (
                    Artifact(
                        artifact_id=artifact_id,
                        challenge_id=cid,
                        sha256=sha256,
                        size=size,
                        media_type=media_type,
                        original_filename=original_filename,
                        ingested_at=ingested_at,
                        source_event_id=event.event_id,
                    ),
                    event,
                )
        except sqlite3.IntegrityError:
            # A concurrent writer inserted the same content between the
            # pre-check and the insert; the unique constraint is authoritative.
            with self.connect() as db:
                row = db.execute(
                    "SELECT " + ARTIFACT_COLUMNS + " FROM artifacts "
                    "WHERE challenge_id=? AND sha256=?",
                    (cid, sha256),
                ).fetchone()
            if row is None:
                raise
            return _artifact_from_row(row), None

    def artifacts(self, cid: str) -> list[Artifact]:
        self.get(cid)
        with self.connect() as db:
            return [
                _artifact_from_row(row)
                for row in db.execute(
                    "SELECT " + ARTIFACT_COLUMNS + " FROM artifacts "
                    "WHERE challenge_id=? ORDER BY rowid",
                    (cid,),
                )
            ]

    def artifact(self, cid: str, artifact_id: str) -> Artifact:
        """Return an artifact only when it belongs to the given challenge."""
        with self.connect() as db:
            row = db.execute(
                "SELECT " + ARTIFACT_COLUMNS + " FROM artifacts "
                "WHERE challenge_id=? AND artifact_id=?",
                (cid, artifact_id),
            ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        return _artifact_from_row(row)

    def artifact_by_sha(self, cid: str, sha256: str) -> Artifact | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT " + ARTIFACT_COLUMNS + " FROM artifacts "
                "WHERE challenge_id=? AND sha256=?",
                (cid, sha256),
            ).fetchone()
        return None if row is None else _artifact_from_row(row)

    def count_artifacts_with_sha(self, sha256: str) -> int:
        with self.connect() as db:
            return db.execute(
                "SELECT count(*) FROM artifacts WHERE sha256=?", (sha256,)
            ).fetchone()[0]

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
