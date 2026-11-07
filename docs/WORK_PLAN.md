# Implementation Plan and Agent Handoff

## Delivery model

Codex scaffolds and integrates the application framework. DeepSeek implements bounded feature modules against agreed interfaces. The reviewer inspects each diff and its tests before integration.

## A. Codex — framework scaffold

Create:
- Vue 3 + TypeScript + Vite frontend.
- FastAPI backend with typed request/response schemas.
- SQLite initialization and migrations.
- Local workspace configuration and path-boundary utilities.
- Provider-neutral Agent interface with a DeepSeek adapter stub.
- Tool registry and approval workflow interfaces.
- Test, lint, run scripts, CI, and a safe synthetic demo.
- A strict .gitignore for challenge data and secrets.

Do not add speculative CTF solving logic. Do not add challenge files, flags, credentials, or real target endpoints.

Deliver a runnable frontend/backend, API schema, setup guide, baseline tests, file map, and known limitations.

## B. DeepSeek — feature implementation

Implement one bounded task per branch/PR:

### B1. Challenge manager
- CRUD for challenge metadata.
- Exactly the five initial categories.
- Attachment ingestion, read-only original, SHA-256, size, and media type.
- Local workspace creation and path validation.

### B2. Evidence/event recorder
- Append-only event API and SQLite persistence.
- Monotonic sequence and hash chain.
- Artifact storage and references.
- Command lifecycle events with actual stdout/stderr, exit code, and timestamps.
- Secret redaction and tamper-detection tests.

### B3. Safe execution broker
- Tool registry with explicit allowlist.
- Agent proposal -> user approval -> execution -> captured result.
- Per-challenge working directory and time/output limits.
- Network disabled by default; explicit host allowlist for authorized challenge targets.
- No scanner execution, broad/high-rate requests, platform probing, or flag-submission automation.
- Configurable maximum of three active containers for the XSWCTF profile.

### B4. Category playbooks and Agent adapter
- Misc / Crypto / Pwn / Web / Reverse checklists.
- Agent returns structured hypotheses, evidence requests, and proposed actions.
- No direct shell/network access from the model.
- Model cannot claim a tool ran until the broker returns a result.

### B5. Writeup generator
- Generate strictly from ordered events and evidence references.
- Cite event IDs for every factual solution step.
- Label hypotheses, failures, and retrospective notes.
- Surface missing evidence instead of filling gaps.
- Never infer a solve path from a flag or final status.
- Export Markdown first; PDF after Markdown acceptance.

## C. Reviewer — independent acceptance

Review contracts and data boundaries before implementation; inspect diffs and tests; verify event immutability, evidence provenance, approval/scope enforcement, Writeup claims against raw events, .gitignore, and secret leakage.

Do not approve based only on a successful demo. Inspect persisted records and require tests.

## Branch / PR discipline

- main: accepted, runnable baseline only.
- feat/framework-scaffold: Codex scaffold PR.
- feat/challenge-manager
- feat/evidence-recorder
- feat/execution-broker
- feat/agent-playbooks
- feat/writeup

One PR should have one bounded responsibility. No direct pushes to main after the scaffold; merge only after review.

## MVP definition of done

A user can create a synthetic or permitted warmup challenge, import an attachment, inspect its hash, ask the Agent for a plan, approve a command, execute it through the broker, inspect the captured result, and generate a Writeup whose steps all link to actual events/evidence. If a step was not recorded, the report says so.
