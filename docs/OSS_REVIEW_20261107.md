# Open-source CTF project review — 2026-11-07

## Executive decision

Do not adopt any of the three repositories wholesale. Use them as reference implementations and selectively port small, reviewed ideas into this project. The first release should remain a local-first, evidence-first workbench, not an autonomous all-challenges solver.

Recommended reference split:
- **Agonionce/Agoni_ctf**: primary reference for typed agent orchestration, policy/approval boundaries, workspace containment, challenge/domain models, and completion pipeline.
- **allen-haitao/ctf-agent**: reference for a compact observe/hypothesize/plan/execute/evidence/verify loop, evidence-linked state, and deterministic tool adapters. Do not copy its unrestricted shell execution.
- **kiwamizamurai/cctf**: reference for beginner-facing skills, platform profiles, queue/ledger workflow, and Writeup structure only. Do not copy its autonomous submit loop or shell hooks; no repository license was declared in GitHub metadata/tree at review time.

## Scope reviewed

Static GitHub source review and local ZIP review of the two uploaded repositories. ZIP integrity, dependency/configuration files, source patterns, selected tests, CLI smoke tests, and compile checks were inspected. No upstream project was installed into the global Python environment. Test commands were run from extracted audit copies under /mnt/data. No public target was contacted and no real challenge was attacked.

Repositories:
- https://github.com/Agonionce/Agoni_ctf
- https://github.com/allen-haitao/ctf-agent
- https://github.com/kiwamizamurai/cctf

## 1. Agonionce/Agoni_ctf

Repository metadata observed:
- Public Python repository; default branch main.
- GitHub reports Apache-2.0; the uploaded ZIP includes the Apache-2.0 LICENSE file.
- README describes a governed, evidence-driven agent, local workbench, policy/approval, artifacts, checkpointing, domain skills, and completion reports.

Useful source areas:
- `agent/policy/engine.py`, `agent/policy/approval.py`: typed policy decisions and explicit approval state.
- `agent/workspace/*`, `agent/tools/workspace/*`: challenge workspace and path containment.
- `agent/domains/*`, `skills/{misc,crypto,pwn,reverse}`: domain metadata, phase declarations, and skill knowledge.
- `agent/completion/collector.py`, `agent/completion/report.py`, `agent/completion/writeup.py`: read-only completion collection and deterministic report/writeup draft.
- `tests/unit/test_r86_completion_pipeline.py`, `tests/integration/test_r86_local_completion_pipeline.py`: completion pipeline tests and fake-local integration demonstration.

Static findings:
- README explicitly lists Pwn Runtime, Reverse Runtime, Crypto Runtime, and Misc Runtime on the roadmap.
- The inspected Pwn/Reverse/Crypto/Misc runtime classes are structure-only: they initialize domain metadata and phases; they are not working category-specific exploit/analysis engines.
- README says the R5 Web execution path is restricted to a challenge-declared loopback origin. This is not a ready-made remote CTF service connector.
- README explicitly states application-level policy/workspace controls are not an operating-system sandbox.
- The Bash tool invokes `bash -c`; the central CommandPolicy classifies commands and routes them to approval or denial. This is materially better than an unguarded shell wrapper, but still needs adversarial bypass tests before production reuse.
- The Python tool launches a workspace-resolved script in a host subprocess with a restricted environment. It is not equivalent to a container sandbox.
- The artifact store records path/creator/time/source-step/type but does not itself provide content-addressed SHA-256 immutability.
- CompletionCollector copies experiment goals/results/status and evidence observations/source/artifact references into a report projection. The WriteupGenerator avoids inventing extra solution steps, but it does not produce a detailed command-by-command narrative. It also labels a non-null termination flag candidate as VERIFIED in the completion projection; confirm the upstream termination path has already performed the required verification, and do not treat this projection alone as a verifier.

Local validation:
- ZIP: 465 entries; `ZipFile.testzip()` passed; no absolute/traversal paths or suspicious oversized members found.
- Python `compileall` over agent, CLI, platform, skills, utilities, tests, main.py and config.py passed.
- Selected pytest collection for completion, approval/workspace, policy and sandbox tests was blocked before test execution because the environment lacks `json_repair` (ModuleNotFoundError). No Agoni test pass rate is claimed.
- The repository's locked dependencies include openai, httpx, PyYAML, json-repair, jsonschema, Typer, Rich, FastAPI and Uvicorn. The audit environment had most but not all of these; no dependency installation was attempted.

Decision: strongest overall architectural reference. Port/adapt contracts and design patterns, not the entire application. Before code reuse, satisfy dependencies in an isolated environment and run the full fake-local test suite plus adversarial policy/workspace tests.

## 2. allen-haitao/ctf-agent

Repository metadata observed:
- Public Python repository; default branch main.
- GitHub reports MIT; uploaded ZIP includes the MIT LICENSE file.
- Python >=3.11; core package declares no runtime Python dependencies, while optional development dependencies include pytest.

Useful source areas:
- `ctf_agent/core/models.py`: typed Evidence, Hypothesis, Experiment, Fact, Capability, FlagCandidate.
- `ctf_agent/core/store.py`: append-only JSONL EvidenceStore.
- `ctf_agent/core/orchestrator.py`: one-brain orchestration, experiment execution, evidence capture, category skills.
- `ctf_agent/core/verifier.py`: flag candidate shape and evidence checks.
- `ctf_agent/reporting.py`: Markdown report from structured state plus evidence log.
- `ctf_agent/llm/policy.py`: structured AgentDecision boundary.
- `ctf_agent/tools/*`: deterministic tool adapters.

Useful design:
- Clear separation between model proposals and deterministic tool execution.
- Evidence IDs are attached to hypotheses/experiments/capabilities/flag candidates.
- Raw tool output is recorded separately from compact reasoning state.
- The verifier does not accept a flag candidate with no supporting evidence.
- Workspace layout is simple and easy to understand.

Important limitations and risks:
- EvidenceStore is append-only at the application level but has no hash chain or tamper-evident verification.
- The report is a useful evidence summary, not yet a strict step-by-step Writeup with a provenance reference for every factual sentence.
- Inspected ShellTool calls subprocess with `shell=True`; ToolRuntime exposes it as a general shell tool. This is not an acceptable default execution boundary for our workbench without a stronger broker, argument model, sandbox, and explicit approval layer.
- PythonTool and HTTP tool also execute commands or network requests; scope checks and approvals must be tested for every adapter, not assumed from the existence of a workspace.
- README describes current supported runtime as Web and Pwn; Reverse, Crypto and Forensics are planned, not implemented.
- Scope/authorized markers are guardrails and must not be mistaken for OS-level isolation.

Local validation:
- ZIP: 89 entries; `ZipFile.testzip()` passed; no absolute/traversal paths or suspicious oversized members found.
- Full test suite: **47 passed**, exit code 0, in approximately 2.49 seconds.
- CLI smoke test: `python -m ctf_agent.cli --help` passed.
- CLI diagnostics: `python -m ctf_agent.cli doctor --json` ran successfully. Python, file, readelf and objdump were available; GDB was optional and absent; no LLM API key was configured. No LLM request was made.
- The Python process emitted a host-environment spreadsheet warmup traceback on stderr, but the test and CLI exit codes remained 0; this was not emitted by ctf-agent source.

Decision: borrow the typed evidence/state model, experiment lifecycle, verifier pattern, deterministic tool adapter concept, and compact CLI workflow. Do not reuse the unrestricted shell tool or claim full five-category support.

## 3. kiwamizamurai/cctf

Repository metadata observed:
- Public Python/Claude Code workspace; default branch main.
- Recently updated/pushed 2026-11-03 at review time.
- GitHub metadata reports no license; the recursive tree reviewed contains no LICENSE/COPYING/NOTICE file. Treat code reuse as not cleared unless the maintainer adds an explicit license or permission is obtained.
- Not included in the uploaded ZIPs and was not dynamically tested.

Useful source areas:
- `.claude/skills/*`: specialist learning/analysis skills for binary, crypto, forensics, networking, and other domains.
- `.claude/agents/*`: wizard, hint helper, auditor roles.
- `.claude/rules/writeup-format.md`: beginner-friendly Writeup structure, reproducibility and tool listing.
- `.claude/skills/ctf-autosolve/scripts/ctf_state.py`: queue and append-only decision ledger.
- `.claude/CONDITIONS.md` and platform profiles: per-event scope, AI policy, deadlines, and stop conditions.

Important limitations and risks:
- Main workflow is tightly coupled to Claude Code commands, agents, hooks, and skill conventions; it requires adaptation for Codex and DeepSeek.
- The pre-bash hook is a small dangerous-pattern blacklist, not a robust security boundary.
- The harness includes automatic platform enumeration, remote challenge interactions and flag submission. These must not be copied into the XSWCTF profile without organizer approval; the XSWCTF rules prohibit scanners, flag submission brute force, platform attacks, and cross-team sharing.
- The state helper stores flags in local queue/ledger records. Our system should separate secret flag storage from shareable reports and logs.

Decision: borrow the Writeup outline, specialist skill packaging, event-specific CONDITIONS/profile idea, and beginner mode as concepts only. Do not copy source code until licensing is clarified; do not adopt the autonomous submission workflow.

## Cross-project decision matrix

| Capability | Agoni_ctf | ctf-agent | cctf | Our decision |
|---|---|---|---|---|
| Typed orchestration / approval | Strong reference | Partial | Claude hooks/rules | Adapt Agoni contracts |
| Evidence model | Rich structured intelligence | Simple typed Evidence + JSONL | Queue/ledger notes | Combine with stricter event provenance |
| Tamper evidence | No hash chain in inspected artifact store | No hash chain in inspected store | No hash chain in inspected ledger | Implement hash-chained append-only events |
| Writeup generation | Evidence-bound deterministic draft | Evidence-linked summary report | Rich format guide, generation skill | Build our own strict evidence-grounded generator |
| Category runtime | Four non-Web runtimes are structure-only | Web/Pwn runtime today | Skills and playbooks | Build five thin category playbooks first |
| Tool execution | Policy + approval + workspace boundary; host subprocesses remain | Shell tool uses shell=True | Shell hooks are weak blacklist | Implement explicit allowlisted execution broker |
| Local test evidence | Compileall passed; pytest blocked by missing dependency | 47 tests passed | Not tested | Validate all reusable paths locally |
| XSWCTF fit | Adaptable, needs remote-target policy review | Needs stronger execution guardrails | Must remove auto-submit loop | Event-specific restrictive profile |

## Proposed implementation architecture

Keep our existing repository as the product, not a fork of any one upstream project.

1. **Challenge manager** — metadata, five categories, local workspaces, read-only attachment import, SHA-256.
2. **Evidence/event recorder** — append-only events with sequence numbers, UTC timestamps, actor, actual command argv, exit code, stdout/stderr artifact references, and hash chain.
3. **Execution broker** — named tools only; proposal -> user approval -> execution -> captured result. Network off by default; explicit per-challenge allowlist; no scanner or flag-submission automation.
4. **Agent adapter** — provider-neutral interface; DeepSeek first; model returns structured hypotheses and proposed tool calls, never direct shell access.
5. **Category playbooks** — initial triage checklists for Misc/Crypto/Pwn/Web/Reverse; specialist tools are optional adapters and must be locally installed/verified.
6. **Writeup generator** — generated only from recorded events and evidence. Each factual operation/observation points to event/evidence IDs. Missing steps are labelled missing; retrospective notes remain labelled as retrospective. Flag is excluded from shareable report by default.
7. **Competition profile** — XSWCTF rule constraints, deadline metadata, maximum three active containers, no cross-team sharing, no scanner, no platform attack, no flag brute force.

## Recommended build order

- P0: Challenge manager + immutable evidence recorder + Writeup integrity contract.
- P1: Agent adapter + user-approved execution broker.
- P2: Misc/Crypto/Reverse local analysis adapters.
- P3: Web/Pwn challenge-specific tools, gated by exact authorization scope and competition policy.
- P4: UI polish and team sharing after data classification and access control are defined.

## Dynamic validation still required

- Install Agoni's pinned dependencies in a disposable environment, then run the complete unit/integration suite and fake-local completion demo.
- Add adversarial tests for shell syntax, path traversal/symlink escapes, approval bypass, environment-variable leakage, and network-origin redirects.
- Build a Writeup traceability fixture with missing intermediate events; generated prose must mark the gap instead of fabricating a command, observation, or result.
- Verify candidate-flag status against the actual upstream termination/verifier path.
- Test all ctf-agent tool adapters with fake-local fixtures and prove that shell execution cannot bypass approval/scope.
- Review cctf license/permission before copying any code.
