-- Human-approved, read-only local tool proposals (P0 unified tool subsystem).
--
-- This table is the authoritative proposal/approval/execution state.  Each
-- state transition is committed in the same SQLite transaction as its
-- append-only challenge event, so a crash cannot leave "state changed but no
-- event" (or the reverse).  Tool output bytes live in the content-addressed
-- ArtifactStore; only their digest/size and the artifact row are recorded here.
--
-- Traceability chain:
--   model_call_id -> proposal_id -> approval_id -> execution_id
--     -> decision_event_id / started_event_id / finished_event_id
--     -> artifact_ids (JSON array of artifact IDs referenced by events)
--
-- There is deliberately no model_calls table: model call auditing lives only
-- in the separate ModelCallJournal (model-audit.sqlite3).
CREATE TABLE tool_proposals (
    proposal_id TEXT PRIMARY KEY,
    challenge_id TEXT NOT NULL REFERENCES challenges(challenge_id),
    model_call_id TEXT,
    tool_name TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    arguments_sha256 TEXT NOT NULL CHECK(length(arguments_sha256) = 64),
    reason TEXT NOT NULL,
    risk_level TEXT NOT NULL CHECK(risk_level IN ('low', 'medium', 'high')),
    status TEXT NOT NULL CHECK(status IN (
        'pending', 'approved', 'running', 'succeeded', 'failed',
        'timed_out', 'rejected', 'cancelled', 'expired'
    )),
    proposed_by TEXT NOT NULL CHECK(proposed_by IN ('agent', 'user')),
    proposed_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    approval_id TEXT UNIQUE,
    approved_by TEXT,
    approved_at TEXT,
    approved_arguments_sha256 TEXT,
    decision_note TEXT,
    decision_event_id TEXT,
    execution_id TEXT UNIQUE,
    started_at TEXT,
    finished_at TEXT,
    started_event_id TEXT,
    finished_event_id TEXT,
    output_artifact_id TEXT,
    output_sha256 TEXT,
    output_size INTEGER CHECK(output_size IS NULL OR output_size >= 0),
    output_summary TEXT,
    artifact_ids TEXT,
    error TEXT
);
CREATE INDEX tool_proposals_by_challenge ON tool_proposals(challenge_id, proposed_at);
CREATE INDEX tool_proposals_by_status ON tool_proposals(challenge_id, status);
CREATE INDEX tool_proposals_by_expiry ON tool_proposals(status, expires_at);
