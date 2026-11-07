-- P0 data stays readable: this migration only adds the composite parent key
-- for the artifact/source-event foreign key; existing tables are untouched.
CREATE UNIQUE INDEX events_challenge_event ON events(challenge_id, event_id);
CREATE TABLE artifacts (
 artifact_id TEXT PRIMARY KEY,
 challenge_id TEXT NOT NULL REFERENCES challenges(challenge_id),
 sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
 size INTEGER NOT NULL CHECK(size >= 0),
 media_type TEXT NOT NULL CHECK(length(media_type) > 0),
 original_filename TEXT NOT NULL CHECK(length(original_filename) > 0),
 ingested_at TEXT NOT NULL,
 source_event_id TEXT NOT NULL UNIQUE,
 UNIQUE(challenge_id, sha256),
 FOREIGN KEY (challenge_id, source_event_id)
  REFERENCES events(challenge_id, event_id)
);
CREATE INDEX artifacts_by_challenge ON artifacts(challenge_id);
CREATE TRIGGER artifacts_no_update BEFORE UPDATE ON artifacts BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER artifacts_no_delete BEFORE DELETE ON artifacts BEGIN SELECT RAISE(ABORT, 'append-only'); END;
