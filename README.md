# CTF Agent Workbench

A local-first CTF workbench for Misc, Crypto, Pwn, Web, and Reverse.

**Non-negotiable rule:** Writeups are generated from an append-only record of real actions and evidence captured as the work happens. They are never reconstructed from a final flag or desired outcome.

## First release
- Challenge workspace and attachment integrity checks.
- Category-aware analysis playbooks.
- Human-approved, scoped tool execution.
- Append-only event and evidence recording.
- Writeup generation with event references and explicit gaps.
- Local-first storage; no challenge secrets or artifacts committed to this public repository.

## Project documents
- Architecture and evidence model: docs/ARCHITECTURE.md
- Implementation plan and agent handoff: docs/WORK_PLAN.md

## Development roles
- Codex: scaffold and integrate the application framework.
- DeepSeek: implement feature modules against documented contracts.
- Reviewer: independent code, security, evidence-integrity, and acceptance review.

## Scope and safety
Authorized CTF challenge environments only. Do not attack the competition platform, scan networks, brute-force flag submissions, disrupt other players, or exceed the configured container limit. Competition rules and organizer clarifications take precedence over this software.

## Data handling
This repository is public. Commit application code, documentation, tests, and synthetic fixtures only. Keep challenge attachments, flags, tokens, raw logs, target URLs/IPs, and generated writeups out of Git.


## P0 scaffold

- [Setup and limitations](docs/P0_RUNBOOK.md)
- [API and integrity contract](docs/P0_API.md)
- [Model providers](docs/MODEL_PROVIDERS.md)
- [Test report](docs/P0_TEST_REPORT.md)
- [Complete file map and change list](docs/P0_FILES.md)

## P1-1 evidence storage

- [Attachment storage design, API, security model and known limitations](docs/P1_ARTIFACT_STORAGE.md)
- [File change list](docs/P1_FILES.md)
- [Test report](docs/P1_TEST_REPORT.md)
- [Artifact/Event constraint fix report](docs/P1_FIX_REPORT.md)

## MVP backend workflow (manual execution mode)

- [Backend API contract, security model, demo steps and known limitations](docs/MVP_BACKEND.md)
- [File change list](docs/MVP_BACKEND_FILES.md)
- [Test report](docs/MVP_BACKEND_TEST_REPORT.md)
- [Deliverable checksums](docs/MVP_BACKEND_SHA256SUMS)
