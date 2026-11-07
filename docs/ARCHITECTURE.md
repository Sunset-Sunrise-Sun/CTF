# Architecture and Evidence Model

## 1. Initial scope

Support only five categories:
- Misc: file/container inspection, metadata, encoding, steganography, authorized traffic-file analysis.
- Crypto: cipher identification, mathematical analysis, reproducible local scripts.
- Pwn: binary metadata, static analysis, debugger-assisted analysis, authorized challenge-instance interaction.
- Web: source/configuration analysis and narrowly scoped requests to an explicitly authorized challenge target.
- Reverse: static/dynamic binary analysis, disassembly, decompilation, local scripts.

A category selects an analysis playbook; it does not grant broader permissions. Target scope and competition policy always take precedence.

## 2. Recommended MVP stack

- Frontend: Vue 3 + TypeScript + Vite.
- API: Python + FastAPI.
- Event store: SQLite, append-only event rows, WAL mode.
- Evidence store: local filesystem, content-addressed by SHA-256.
- Agent adapter: provider-neutral interface; DeepSeek-compatible API first.
- Execution: explicit tool registry and subprocess wrapper. No unrestricted shell or autonomous network access.

Use a modular monolith, not microservices, for the MVP.

## 3. Core records

### Challenge
Fields: challenge_id, name, category, description, source (warmup/practice/competition), scope, status, created_at.

### Event (append-only)
Each event contains:
- event_id, challenge_id, monotonically increasing sequence
- occurred_at in UTC
- actor: user / agent / tool / system
- event_type: note / hypothesis / plan / command_started / command_finished / artifact_added / finding / verification / limitation
- structured payload and evidence references
- previous_event_hash and event_hash

Events are immutable. Corrections are new events referencing the original; never edit history in place. Hash-chain events in sequence so tampering is detectable.

For command events, capture actual argv, executable/version when available, working directory, start/end timestamps, exit code, and stdout/stderr artifact references and hashes. Do not claim to capture commands run outside the workbench. Such activity can only be added as a retrospective user note, timestamped when entered and clearly labelled retrospective.

Do not attempt to capture or reproduce hidden model reasoning. Record user-visible agent outputs, hypotheses, plans, tool requests, approvals, and actual tool results.

### Evidence artifact
Store bytes under a content-addressed local path. Record SHA-256, byte size, detected media type, original filename, ingestion time, and source event. Keep original challenge attachments read-only. A changed file is a new artifact; never overwrite evidence.

## 4. Writeup integrity contract

The Writeup generator may summarize only facts supported by recorded events and evidence.

1. Build the report from the event timeline in sequence order.
2. Every claimed command, observation, transformation, and result must cite event/evidence IDs.
3. Distinguish observed facts, hypotheses, failed attempts, and conclusions.
4. If a step was not captured, mark it as not recorded / evidence missing. Never invent commands, outputs, tools, timestamps, or intermediate results.
5. Retrospective notes are allowed only as separately labelled notes with their actual entry time. Never insert them into the historical timeline as if captured earlier.
6. A final flag alone is not proof of the path used to obtain it.
7. Flag verification is a separate event. Do not automate repeated submissions; never brute-force flag submissions.
8. Export Markdown first. PDF is a rendering of that Markdown and must preserve evidence references and missing-evidence warnings.

Suggested sections: challenge metadata and scope; summary; environment and tools; recorded analysis timeline; observations and evidence; reproducible solution steps; failed attempts; flag verification status (exclude the flag from public exports by default); limitations and unrecorded steps.

## 5. Execution and approval

- Every tool execution requires a proposal, explicit user approval, start event, and completion event.
- The Agent may propose commands; it cannot silently execute them.
- Enforce per-challenge filesystem boundaries and an explicit target allowlist.
- Network access is off by default. Enable only for an explicitly authorized challenge target and minimum required interaction.
- No scanning, broad enumeration, high-volume traffic, platform testing, flag brute force, or actions that disrupt other players.
- Enforce a configurable maximum of three active challenge containers for the XSWCTF profile.
- Run untrusted binaries in isolated environments, not on the host.
- Keep credentials and flags out of normal logs. Redact secrets from console output and exports.

## 6. Public repository vs local challenge data

This GitHub repository is public. It may contain source code, docs, tests, and synthetic fixtures only.

Keep local and gitignored: challenge attachments and extracted files; flags, team tokens, passwords, cookies, API keys; target URLs/IPs and instance identifiers; raw command output, PCAPs, memory dumps, screenshots; per-challenge logs and generated Writeups.

Teammates may clone the application code. Sharing actual challenge material must follow organizer rules and use an appropriately restricted channel.

## 7. Acceptance criteria

- All five categories can be created and use category-specific checklists.
- An attachment is copied read-only and its SHA-256 is stored and displayed.
- A proposed command cannot execute before user approval.
- Actual command, output, exit status, and timestamps are persisted.
- Events are append-only; hash-chain verification detects tampering.
- Writeups are generated only from recorded events; unsupported steps appear as gaps.
- Editing a Writeup cannot silently alter the evidence log.
- Challenge secrets and artifacts are excluded from Git.
- XSWCTF profile enforces no more than three active containers.
- Tests prove broad scanning and flag-submission brute force are blocked.
