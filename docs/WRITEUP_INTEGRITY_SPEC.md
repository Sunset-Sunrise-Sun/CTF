# Writeup Integrity Specification (P0)

Version: 1.0  
Date: 2026-11-07  
Status: implementation contract

## 1. Purpose

The Writeup system must preserve and explain the real solving process as it happens. It must not reconstruct a plausible process from a final flag, solved status, or model-generated narrative.

The evidence log is the source of truth. A Writeup is a derived, reviewable view of that log.

## 2. Non-negotiable principles

1. **Capture first, narrate second.** A command or tool result can appear as an observed action only if the workbench captured its execution lifecycle and output.
2. **No retrospective fabrication.** A missed action may be added later only as a retrospective note, with the actual note-entry timestamp and an explicit retrospective label.
3. **No hidden-reasoning capture.** Store user-visible model responses, plans, hypotheses, proposed actions, approvals, and tool results. Do not claim to store private chain-of-thought.
4. **Evidence is immutable.** Original attachments and captured outputs are content-addressed by SHA-256. Corrections create new records; they do not rewrite old evidence.
5. **Every material claim is traceable.** Each factual solution step in the generated Writeup must cite one or more event IDs and, where applicable, artifact IDs.
6. **Flag correctness and process completeness are independent.** A verified flag does not make an incomplete Writeup complete.
7. **Unknown means unknown.** Missing evidence must be surfaced, not guessed or silently filled.

## 3. Event lifecycle

For each tool action, persist distinct events:

- `tool_proposed`: actor, tool name, structured arguments, challenge scope, proposal timestamp.
- `tool_approved` or `tool_rejected`: approving user and decision timestamp.
- `tool_started`: actual executable, argv, working directory, environment allowlist, start timestamp.
- `tool_finished`: end timestamp, exit code, timeout status, stdout/stderr artifact IDs, output hashes.
- `finding`: concise observation supported by event/artifact references.
- `hypothesis`: interpretation explicitly marked as unverified until tested.
- `verification`: verification method, result, and supporting evidence.

A tool must not be represented as executed unless a matching start and finish record exists. A proposal is not an execution. A model claim is not a tool result.

## 4. Evidence and integrity

Each event must include:
- unique event ID;
- challenge ID;
- monotonic per-challenge sequence number;
- UTC timestamp;
- actor: user / agent / tool / system;
- event type and structured payload;
- evidence/artifact references;
- previous event hash;
- current event hash.

Hash calculation must use a documented canonical serialization. Verification must detect modified, removed, reordered, or inserted events. The implementation must document the threat model: a local hash chain detects accidental edits and unsophisticated tampering, but a user with full filesystem/database control can rewrite the entire chain unless an external checkpoint/signature exists. Do not describe the chain as cryptographic proof against the machine owner.

Artifacts must record SHA-256, size, media type, original filename, ingestion timestamp, and source event. Original input attachments must be read-only. Store stdout/stderr as artifacts, with secrets redacted before display/export; retain raw sensitive outputs only under a deliberate local secret-handling policy.

## 5. Writeup generation contract

The generator consumes only:
- ordered event records;
- referenced evidence artifacts;
- challenge metadata;
- explicitly labelled retrospective notes.

It must not use an unreferenced final flag or current chat context to invent intermediate steps.

For each report statement, include provenance:
- factual observation: event ID + evidence artifact ID(s);
- hypothesis: hypothesis event ID and status;
- conclusion: supporting finding/verification event IDs;
- retrospective detail: retrospective note ID and actual entry timestamp.

If provenance is missing, render a visible marker such as **[证据缺失：该步骤未被工作台记录]**. Do not output an unqualified command, output, tool name, timestamp, or intermediate result.

## 6. Separate status dimensions

Maintain at least two independent statuses:

### Solve status
- `unknown`
- `candidate`
- `verified`

### Writeup status
- `not_generated`
- `incomplete`
- `review_required`
- `complete`

A solve can be verified while the Writeup remains incomplete. A Writeup can be structurally complete while the flag remains unverified. Do not collapse these into one `solved` boolean.

Suggested completeness rules:
- **complete**: all required solution steps are evidenced; no unresolved critical gaps; verification status is accurately represented.
- **incomplete**: at least one required step is absent or unsupported.
- **review_required**: evidence exists but has conflicting, ambiguous, or unverified claims.
- **not_generated**: no report exists yet.

## 7. Required synthetic acceptance tests

Use synthetic fixture data only; never use real competition flags or private challenge materials in public tests.

### W01 — Complete trace
Given an imported synthetic file, a captured metadata command, a captured transformation script, a captured output, and a verification event:
- generate a chronological report;
- cite each operation and observation to event/artifact IDs;
- report the actual command, exit status, and output references;
- mark Writeup complete only if all required steps are supported.

### W02 — Missing middle step
Given an initial observation and a final result but no recorded transformation:
- do not invent the missing command or method;
- include an explicit missing-evidence marker;
- Writeup status must be incomplete.

### W03 — Unsupported flag
Given a flag candidate or even a manually set solve status of verified, but no verification event/evidence:
- do not claim the flag was independently verified;
- do not mark the Writeup complete;
- flag status and Writeup status remain separate.

### W04 — Hypothesis is not fact
Given an agent hypothesis with no confirming observation:
- label it as a hypothesis;
- do not phrase it as a discovered fact or final conclusion.

### W05 — Failed attempt retained
Given a failed command and a later successful command:
- retain both in the event timeline;
- do not erase the failed attempt from the report data;
- allow concise presentation without deleting provenance.

### W06 — Retrospective note
Given a user note added after the solve:
- label it retrospective;
- use its actual creation time;
- do not backdate it into the historical execution sequence.

### W07 — Tamper detection
Modify, remove, reorder, or insert an event in a fixture event chain:
- integrity verification must fail and identify the earliest affected sequence.

### W08 — Model/tool boundary
Given an agent message claiming that a command succeeded but no broker execution record exists:
- do not create a tool-finished event;
- do not treat the claim as observed evidence;
- report it as an unverified agent statement.

### W09 — Export consistency
Markdown and PDF exports must preserve status, evidence references, missing-evidence markers, and retrospective labels.

### W10 — Secret-safe export
Flags, tokens, passwords, cookies, API keys, and sensitive target details must not leak into shareable Writeups or repository fixtures by default.

## 8. Implementation tasks

### Codex — contracts and integration
1. Define typed Event, Artifact, ToolProposal, ToolExecutionResult, Finding, Hypothesis, Verification, and Writeup models.
2. Implement SQLite schema/migrations and append-only event API.
3. Implement canonical event hashing and chain verification.
4. Define separate solve/writeup status fields.
5. Wire frontend timeline and evidence references to backend IDs.
6. Add synthetic fixtures and test harness; do not use real challenge artifacts.

### DeepSeek — bounded feature implementation
1. Implement Evidence Recorder persistence and artifact hashing.
2. Implement tool lifecycle capture (proposal/approval/start/finish).
3. Implement deterministic Writeup generator from event/evidence data only.
4. Implement provenance markers and missing-evidence status.
5. Implement Markdown export; PDF only after Markdown passes.
6. Add W01-W10 tests. Do not add autonomous target discovery, scanning, or flag submission.

## 9. Reviewer acceptance gate

Reviewer must inspect:
- persisted SQLite rows and raw JSONL/artifact data;
- event hash verification output;
- generated report against source events;
- each W01-W10 test;
- secret redaction behavior;
- whether any report text is generated from untracked model context.

A passing demo alone is insufficient. A report containing fabricated or unsupported steps is a release blocker.

## 10. XSWCTF profile constraints

The event profile must enforce:
- no attack against the competition platform;
- no scanner or broad enumeration;
- no flag submission brute force;
- no cross-team challenge/flag/hint sharing;
- no disruption of other participants;
- at most three active challenge containers.

The organizer's rules and clarifications take precedence. AI use and third-party upload permissions must be confirmed with organizers before using external AI services on live competition material.
