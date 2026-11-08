CREATE TABLE challenges (challenge_id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE events (
 event_id TEXT PRIMARY KEY, challenge_id TEXT NOT NULL REFERENCES challenges(challenge_id),
 sequence INTEGER NOT NULL CHECK(sequence > 0), body TEXT NOT NULL,
 UNIQUE(challenge_id, sequence)
);
CREATE TABLE event_heads (challenge_id TEXT PRIMARY KEY REFERENCES challenges(challenge_id), sequence INTEGER NOT NULL, event_hash TEXT NOT NULL);
CREATE TRIGGER events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
