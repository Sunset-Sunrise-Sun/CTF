"""Synthetic, offline tests for the unified Writeup/ZIP disclosure.

The suite consumes the pure builder functions directly (no HTTP server, no
network, no real competition material).  All identities, paths, digests and
Flags are synthetic values assembled inside this module, and every filesystem
side effect stays under ``tmp_path``.

Coverage:
* one successful + one failed model call, with synthetic calls counted apart;
* audit-unknown and not-recorded-answer states marked incomplete (not failure);
* tool lifecycle disclosure for succeeded/failed/timed_out/rejected plus the
  other terminal states, including the full traceability identifiers;
* absolute paths inside tool arguments never reach a deliverable;
* Flag confirmation shown as a SHA-256 prefix + length, ``platform_verified=false``;
* human Writeup bytes unchanged, generation/manifest/disclosure/SHA256SUMS from
  the same snapshot, and running/succeeded-without-artifact marked incomplete.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

from app.artifacts import ArtifactStore
from app.export import build_export_archive
from app.imports import ImportManifest
from app.models import (
    ArtifactView,
    Challenge,
    Event,
    ToolProposalRecord,
    WriteupDraft,
)
from app.writeup import (
    ABSOLUTE_PATH_PLACEHOLDER,
    build_writeup_preview,
    flag_confirmation_records,
    model_call_statistics,
    tool_proposal_statistics,
)

CHALLENGE_ID = "challenge-synthetic-unified"
PNG_HEADER = b"\x89PNG\r\n\x1a\n"
VALID_INTEGRITY = {"valid": True, "earliest_affected_sequence": None}
FLAG_PLAINTEXT = "flag{synthetic-disclosure-only}"
FLAG_DIGEST = hashlib.sha256(FLAG_PLAINTEXT.encode("utf-8")).hexdigest()
HUMAN_CONTENT = "# 合成人工稿\n\nSYNTHETIC-HUMAN-WRITEUP-CONTENT ✓\n"


# ---------------------------------------------------------------------------
# synthetic builders
# ---------------------------------------------------------------------------


def make_challenge(**overrides) -> Challenge:
    payload = {
        "challenge_id": CHALLENGE_ID,
        "name": "SYNTH-UNIFIED-CHALLENGE",
        "category": "Misc",
        "description": "synthetic challenge description",
        "ai_usage_level": "A2",
    }
    payload.update(overrides)
    return Challenge(**payload)


def make_event(
    sequence: int,
    event_type: str,
    payload: dict,
    *,
    actor: str = "user",
    artifact_ids: tuple[str, ...] = (),
) -> Event:
    return Event(
        event_id=f"event-{sequence:04d}",
        challenge_id=CHALLENGE_ID,
        sequence=sequence,
        occurred_at=f"2026-11-08T01:{sequence:02d}:00+00:00",
        actor=actor,
        event_type=event_type,
        payload=payload,
        artifact_ids=list(artifact_ids),
        previous_event_hash="0" * 64,
    )


def make_artifact(
    store: ArtifactStore,
    *,
    artifact_id: str,
    filename: str,
    data: bytes,
    evidence_kind: str,
    source_event_id: str,
) -> ArtifactView:
    ingested = store.ingest(io.BytesIO(data), filename=filename)
    return ArtifactView(
        artifact_id=artifact_id,
        challenge_id=CHALLENGE_ID,
        sha256=ingested.sha256,
        size=ingested.size,
        media_type=ingested.media_type,
        original_filename=ingested.original_filename,
        ingested_at="2026-11-08T01:00:00+00:00",
        source_event_id=source_event_id,
        evidence_kind=evidence_kind,
        capture_time_claim=None,
        source_event_sequence=None,
    )


def success_call(
    *, call_id: str = "call-success", event_id: str | None = "event-0007"
) -> dict:
    return {
        "call_id": call_id,
        "challenge_id": CHALLENGE_ID,
        "provider_id": "synthetic-provider",
        "model_id": "synthetic-model",
        "purpose": "challenge_chat",
        "synthetic": False,
        "data_scope": "A2:text_only",
        "requested_at": "2026-11-08T01:00:00+00:00",
        "completed_at": "2026-11-08T01:00:02+00:00",
        "response_status": "success",
        "error_category": None,
        "usage": {"total_tokens": 14},
        "event_id": event_id,
        "delivery_status": "recorded",
    }


def failed_call(
    *, call_id: str = "call-failed", event_id: str | None = "event-0010"
) -> dict:
    call = success_call(call_id=call_id, event_id=event_id)
    call.update(
        {
            "response_status": "rate_limited",
            "error_category": "rate_limited",
            "completed_at": "2026-11-08T01:00:03+00:00",
            "delivery_status": None,
        }
    )
    return call


def unknown_call(*, call_id: str = "call-unknown") -> dict:
    call = success_call(call_id=call_id, event_id=None)
    call.update(
        {
            "response_status": "unknown",
            "completed_at": None,
            "delivery_status": None,
        }
    )
    return call


def synthetic_call(*, call_id: str = "call-synthetic") -> dict:
    call = success_call(call_id=call_id, event_id=None)
    call.update(
        {
            "challenge_id": None,
            "synthetic": True,
            "purpose": "synthetic_connectivity",
            "data_scope": "synthetic_only",
            "delivery_status": None,
        }
    )
    return call


def make_proposal(
    proposal_id: str,
    status: str,
    *,
    tool_name: str = "file_inspect",
    arguments: dict | None = None,
    model_call_id: str | None = "call-success",
    approval_id: str | None = None,
    approved_by: str | None = None,
    approved_at: str | None = None,
    decision_note: str | None = None,
    decision_event_id: str | None = None,
    execution_id: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    started_event_id: str | None = None,
    finished_event_id: str | None = None,
    artifact_ids: list[str] | None = None,
    output_artifact_id: str | None = None,
    output_sha256: str | None = None,
    output_size: int | None = None,
    output_summary: str | None = None,
    error: str | None = None,
) -> ToolProposalRecord:
    return ToolProposalRecord(
        proposal_id=proposal_id,
        challenge_id=CHALLENGE_ID,
        model_call_id=model_call_id,
        tool_name=tool_name,
        arguments=arguments if arguments is not None else {"path": "src/solve.py"},
        reason="synthetic disclosure reason",
        risk_level="low",
        status=status,
        proposed_by="agent",
        proposed_at="2026-11-08T01:00:04+00:00",
        expires_at="2026-11-08T01:05:04+00:00",
        approval_id=approval_id,
        approved_by=approved_by,
        approved_at=approved_at,
        decision_note=decision_note,
        decision_event_id=decision_event_id,
        execution_id=execution_id,
        started_at=started_at,
        finished_at=finished_at,
        started_event_id=started_event_id,
        finished_event_id=finished_event_id,
        artifact_ids=artifact_ids or [],
        output_artifact_id=output_artifact_id,
        output_sha256=output_sha256,
        output_size=output_size,
        output_summary=output_summary,
        error=error,
    )


def preview_of(
    events: list[Event] | None = None,
    artifacts: list[ArtifactView] | None = None,
    calls: list[dict] | None = None,
    proposals: list[ToolProposalRecord] | None = None,
    *,
    challenge: Challenge | None = None,
    integrity: dict | None = None,
    read_verified=None,
):
    reader = read_verified or (lambda _sha: b"print('synthetic')\n")
    return build_writeup_preview(
        challenge or make_challenge(),
        events or [],
        artifacts or [],
        None,
        reader,
        integrity or VALID_INTEGRITY,
        calls if calls is not None else [],
        proposals if proposals is not None else [],
    )


# ---------------------------------------------------------------------------
# model call disclosure
# ---------------------------------------------------------------------------


def test_model_call_disclosure_counts_success_and_failure_and_separates_synthetic():
    calls = [success_call(), failed_call(), synthetic_call()]
    preview = preview_of(calls=calls)

    assert preview.model_call_count == 2
    assert preview.tool_proposal_count == 0
    assert preview.tool_execution_count == 0
    assert preview.tool_failure_count == 0

    markdown = preview.markdown
    assert "成功 1，失败 1" in markdown
    assert "rate_limited" in markdown
    assert "本题模型调用 2 次" in markdown
    assert "合成连通性测试调用 1 次单独统计" in markdown
    # The synthetic call is disclosed separately, never mixed into challenge
    # statistics or listed as challenge evidence.
    assert "call-synthetic" not in markdown

    stats = model_call_statistics(calls)
    assert stats["call_count"] == 2
    assert stats["successful"] == 1
    assert stats["failed"] == 1
    assert stats["cancelled"] == 0
    assert stats["unknown"] == 0
    assert stats["synthetic_call_count"] == 1


def test_model_call_disclosure_marks_unknown_and_unrecorded_incomplete():
    calls = [success_call(), failed_call(), unknown_call()]
    # Simulate "provider answered but the answer event could not be recorded".
    calls[0]["delivery_status"] = "not_recorded"
    preview = preview_of(calls=calls)

    missing = set(preview.missing_requirements)
    assert preview.completeness == "incomplete"
    assert "model_audit_incomplete" in missing
    assert "model_response_unrecorded" in missing

    markdown = preview.markdown
    assert "model_audit_incomplete" in markdown
    assert "model_response_unrecorded" in markdown
    # Unknown is undetermined, not a fabricated failure.
    assert "未确定 1" in markdown
    assert "失败 1" in markdown
    assert "回答未入事件" in markdown
    assert model_call_statistics(calls)["unknown"] == 1
    assert model_call_statistics(calls)["failed"] == 1


# ---------------------------------------------------------------------------
# tool lifecycle disclosure
# ---------------------------------------------------------------------------


def test_tool_disclosure_covers_lifecycle_and_hides_absolute_paths():
    proposals = [
        make_proposal(
            "prop-succeeded",
            "succeeded",
            approval_id="approval-1",
            approved_by="local-user",
            approved_at="2026-11-08T01:00:05+00:00",
            decision_event_id="event-0010",
            execution_id="execution-1",
            started_at="2026-11-08T01:00:06+00:00",
            finished_at="2026-11-08T01:00:07+00:00",
            started_event_id="event-0011",
            finished_event_id="event-0012",
            artifact_ids=["artifact-tool-output"],
            output_artifact_id="artifact-tool-output",
            output_sha256=hashlib.sha256(b"synthetic tool output").hexdigest(),
            output_size=21,
            output_summary="synthetic success output",
        ),
        make_proposal(
            "prop-failed",
            "failed",
            tool_name="sha256",
            approval_id="approval-2",
            execution_id="execution-2",
            error="synthetic tool failure",
        ),
        make_proposal(
            "prop-timed-out",
            "timed_out",
            tool_name="strings",
            approval_id="approval-3",
            execution_id="execution-3",
            error="timed out after 15s",
        ),
        make_proposal(
            "prop-rejected",
            "rejected",
            tool_name="list_files",
            model_call_id=None,
            decision_note="synthetic rejection",
            decision_event_id="event-0013",
        ),
        make_proposal(
            "prop-cancelled",
            "cancelled",
            tool_name="stat",
            model_call_id=None,
            decision_note="synthetic cancellation",
        ),
        make_proposal(
            "prop-expired",
            "expired",
            tool_name="image_info",
            model_call_id=None,
        ),
        make_proposal(
            "prop-absolute",
            "pending",
            tool_name="file_inspect",
            model_call_id=None,
            arguments={
                "path": "C:/Users/synthetic/secret.txt",
                "note": "/etc/synthetic-passwd",
            },
        ),
    ]
    preview = preview_of(proposals=proposals)

    assert preview.tool_proposal_count == len(proposals)
    # succeeded + failed + timed_out were started; rejected/cancelled/expired
    # never ran.
    assert preview.tool_execution_count == 3
    assert preview.tool_failure_count == 2
    stats = tool_proposal_statistics(proposals)
    assert stats["proposal_count"] == 7
    assert stats["approved_count"] == 3
    assert stats["execution_count"] == 3
    assert stats["failure_count"] == 2
    assert stats["status_counts"]["succeeded"] == 1
    assert stats["status_counts"]["rejected"] == 1
    assert stats["status_counts"]["cancelled"] == 1
    assert stats["status_counts"]["expired"] == 1
    assert stats["status_counts"]["pending"] == 1

    markdown = preview.markdown
    for token in (
        "prop-succeeded",
        "prop-failed",
        "prop-timed-out",
        "prop-rejected",
        "prop-cancelled",
        "prop-expired",
        "call-success",
        "approval-1",
        "execution-1",
        "event-0011",
        "event-0012",
        "artifact-tool-output",
        "synthetic success output",
        "synthetic tool failure",
        "timed out after 15s",
        "synthetic rejection",
        "待批准",
        "已拒绝",
        "已取消",
        "已过期",
        "已超时",
        "成功",
        "失败",
    ):
        assert token in markdown, token
    output_sha = hashlib.sha256(b"synthetic tool output").hexdigest()
    assert output_sha in markdown

    # Absolute paths are never copied into the deliverable.
    assert "C:/Users/synthetic/secret.txt" not in markdown
    assert "/etc/synthetic-passwd" not in markdown
    assert ABSOLUTE_PATH_PLACEHOLDER in markdown
    # Relative paths stay visible for traceability.
    assert "src/solve.py" in markdown


def test_tool_disclosure_marks_running_and_missing_output_incomplete():
    proposals = [
        make_proposal(
            "prop-running",
            "running",
            approval_id="approval-running",
            execution_id="execution-running",
            started_at="2026-11-08T01:00:06+00:00",
        ),
        make_proposal(
            "prop-succeeded-no-artifact",
            "succeeded",
            approval_id="approval-done",
            execution_id="execution-done",
            finished_at="2026-11-08T01:00:07+00:00",
        ),
        make_proposal(
            "prop-rejected-ok",
            "rejected",
            model_call_id=None,
            decision_event_id="event-0099",
        ),
    ]
    preview = preview_of(proposals=proposals)

    missing = set(preview.missing_requirements)
    assert preview.completeness == "incomplete"
    assert "tool_execution_running" in missing
    assert "tool_output_missing" in missing
    assert preview.tool_proposal_count == 3
    assert preview.tool_execution_count == 2
    assert preview.tool_failure_count == 0

    markdown = preview.markdown
    assert "tool_execution_running" in markdown
    assert "tool_output_missing" in markdown
    assert "prop-running" in markdown
    assert "prop-succeeded-no-artifact" in markdown


# ---------------------------------------------------------------------------
# Flag confirmation: digest only, never a platform verification
# ---------------------------------------------------------------------------


def test_flag_confirmation_discloses_digest_only_and_is_not_platform_verified():
    event = make_event(
        1,
        "flag_confirmed",
        {
            "flag_sha256": FLAG_DIGEST,
            "flag_length": len(FLAG_PLAINTEXT),
            "confirmed_by": "synthetic-tester",
            "note": "synthetic confirmation",
            "source": "manual_user_confirmation",
            # Even a tampered payload must never become a positive claim.
            "platform_verified": True,
        },
    )
    preview = preview_of(events=[event])

    records = flag_confirmation_records([event])
    assert len(records) == 1
    assert records[0]["platform_verified"] is False
    assert records[0]["flag_sha256"] == FLAG_DIGEST
    assert records[0]["flag_sha256_prefix"].startswith(FLAG_DIGEST[:16])
    assert records[0]["flag_length"] == len(FLAG_PLAINTEXT)

    markdown = preview.markdown
    assert FLAG_DIGEST[:16] in markdown
    assert f"长度 {len(FLAG_PLAINTEXT)}" in markdown
    assert "platform_verified=false" in markdown
    assert "人工确认不等于平台验证成功" in markdown
    assert "platform_verified=true" not in markdown
    assert FLAG_PLAINTEXT not in markdown
    # Only the prefix is disclosed, not the whole digest.
    assert FLAG_DIGEST not in markdown
    # A missing flag_capture screenshot keeps its explicit gap marker.
    assert "flag_capture" in preview.missing_requirements
    assert "[证据缺失：Flag 获取即时截图尚未提供]" in markdown


# ---------------------------------------------------------------------------
# export: one snapshot, byte-exact human draft, manifest/disclosure/SHA256SUMS
# ---------------------------------------------------------------------------


def build_dossier(tmp_path: Path) -> dict:
    data_root = tmp_path / "data"
    store = ArtifactStore(data_root / "artifacts")
    workspace = tmp_path / "workspace" / CHALLENGE_ID
    workspace.mkdir(parents=True)
    challenge = make_challenge()

    artifacts = [
        make_artifact(
            store,
            artifact_id="artifact-flag",
            filename="flag_capture.png",
            data=PNG_HEADER + b"SYNTHETIC-FLAG-CAPTURE",
            evidence_kind="flag_capture",
            source_event_id="event-0003",
        ),
        make_artifact(
            store,
            artifact_id="artifact-platform",
            filename="platform_verification.png",
            data=PNG_HEADER + b"SYNTHETIC-PLATFORM-VERIFICATION",
            evidence_kind="platform_verification",
            source_event_id="event-0004",
        ),
        make_artifact(
            store,
            artifact_id="artifact-execution",
            filename="execution.png",
            data=PNG_HEADER + b"SYNTHETIC-EXECUTION",
            evidence_kind="execution",
            source_event_id="event-0005",
        ),
        make_artifact(
            store,
            artifact_id="artifact-source",
            filename="solve.py",
            data=b"def solve():\n    return 'SYNTHETIC_SOURCE'\n",
            evidence_kind="source_code",
            source_event_id="event-0006",
        ),
        make_artifact(
            store,
            artifact_id="artifact-import",
            filename="challenge.zip",
            data=b"PK\x03\x04SYNTHETIC-IMPORT-ARCHIVE",
            evidence_kind="challenge_archive",
            source_event_id="event-0015",
        ),
    ]
    events = [
        make_event(
            1,
            "note",
            {"text": "SYNTH-APPROACH", "kind": "approach"},
            artifact_ids=(),
        ),
        make_event(
            2,
            "manual_operation_recorded",
            {
                "command": "python solve.py --synthetic",
                "working_directory": "synthetic/relative/workdir",
                "purpose": "synthetic verification",
                "exit_code": 0,
                "result_note": "SYNTH-RESULT",
                "execution_mode": "manual_external",
                "execution_verified": False,
            },
        ),
        make_event(
            3,
            "artifact_added",
            {"artifact_id": "artifact-flag", "sha256": artifacts[0].sha256},
            artifact_ids=("artifact-flag",),
        ),
        make_event(
            4,
            "artifact_added",
            {"artifact_id": "artifact-platform", "sha256": artifacts[1].sha256},
            artifact_ids=("artifact-platform",),
        ),
        make_event(
            5,
            "artifact_added",
            {"artifact_id": "artifact-execution", "sha256": artifacts[2].sha256},
            artifact_ids=("artifact-execution",),
        ),
        make_event(
            6,
            "artifact_added",
            {"artifact_id": "artifact-source", "sha256": artifacts[3].sha256},
            artifact_ids=("artifact-source",),
        ),
        make_event(
            7,
            "model_call",
            {
                "call_id": "call-success",
                "provider_id": "synthetic-provider",
                "model_id": "synthetic-model",
                "response_status": "success",
                "purpose": "challenge_chat",
                "synthetic": False,
            },
            actor="system",
        ),
        make_event(
            8,
            "agent_message",
            {
                "call_id": "call-success",
                "answer": "SYNTHETIC-UNVERIFIED-ADVICE",
                "verification_status": "unverified_suggestion",
            },
            actor="agent",
        ),
        make_event(
            9,
            "tool_proposed",
            {
                "proposal_id": "prop-succeeded",
                "model_call_id": "call-success",
                "tool": "file_inspect",
                "arguments": {"path": "src/solve.py"},
                "risk": "low",
            },
            actor="agent",
        ),
        make_event(
            10,
            "model_call",
            {
                "call_id": "call-failed",
                "provider_id": "synthetic-provider",
                "model_id": "synthetic-model",
                "response_status": "rate_limited",
                "purpose": "challenge_chat",
                "synthetic": False,
            },
            actor="system",
        ),
        make_event(
            11,
            "tool_approved",
            {
                "proposal_id": "prop-succeeded",
                "approval_id": "approval-success",
                "approving_user": "local-user",
            },
        ),
        make_event(
            12,
            "tool_started",
            {
                "proposal_id": "prop-succeeded",
                "execution_id": "execution-success",
            },
            actor="tool",
        ),
        make_event(
            13,
            "tool_finished",
            {
                "proposal_id": "prop-succeeded",
                "execution_id": "execution-success",
                "status": "succeeded",
                "output_artifact_id": "artifact-tool-output",
                "output_sha256": hashlib.sha256(b"synthetic tool output").hexdigest(),
                "output_size": 21,
                "output_summary": "synthetic success output",
                "error": None,
            },
            actor="tool",
        ),
        make_event(
            14,
            "flag_confirmed",
            {
                "flag_sha256": FLAG_DIGEST,
                "flag_length": len(FLAG_PLAINTEXT),
                "confirmed_by": "synthetic-tester",
                "source": "manual_user_confirmation",
                "platform_verified": False,
            },
        ),
        make_event(
            15,
            "challenge_imported",
            {
                "original_filename": "challenge.zip",
                "extracted_file_count": 0,
                "total_uncompressed_size": 0,
                "warnings": [],
            },
        ),
    ]
    manifests = [
        ImportManifest(
            import_id="import-synthetic",
            challenge_id=CHALLENGE_ID,
            original_artifact_id="artifact-import",
            original_filename="challenge.zip",
            extracted_file_count=0,
            total_uncompressed_size=0,
            warnings=[],
            created_at="2026-11-08T01:00:00+00:00",
        )
    ]
    calls = [
        success_call(call_id="call-success", event_id="event-0007"),
        failed_call(call_id="call-failed", event_id="event-0010"),
    ]
    proposals = [
        make_proposal(
            "prop-succeeded",
            "succeeded",
            approval_id="approval-success",
            approved_by="local-user",
            approved_at="2026-11-08T01:00:11+00:00",
            decision_event_id="event-0011",
            execution_id="execution-success",
            started_at="2026-11-08T01:00:12+00:00",
            finished_at="2026-11-08T01:00:13+00:00",
            started_event_id="event-0012",
            finished_event_id="event-0013",
            artifact_ids=["artifact-tool-output"],
            output_artifact_id="artifact-tool-output",
            output_sha256=hashlib.sha256(b"synthetic tool output").hexdigest(),
            output_size=21,
            output_summary="synthetic success output",
        ),
        make_proposal(
            "prop-rejected",
            "rejected",
            tool_name="list_files",
            model_call_id=None,
            decision_note="synthetic rejection",
            decision_event_id="event-0098",
        ),
        make_proposal(
            "prop-absolute",
            "pending",
            model_call_id=None,
            arguments={"path": "C:/Users/synthetic/secret.txt"},
        ),
    ]
    human = WriteupDraft(
        challenge_id=CHALLENGE_ID,
        content=HUMAN_CONTENT,
        version=2,
        sha256=hashlib.sha256(HUMAN_CONTENT.encode("utf-8")).hexdigest(),
        size=len(HUMAN_CONTENT.encode("utf-8")),
        saved_at="2026-11-08T01:00:00+00:00",
    )
    preview = build_writeup_preview(
        challenge,
        events,
        artifacts,
        None,
        store.read_verified,
        VALID_INTEGRITY,
        calls,
        proposals,
    )
    return {
        "data_root": data_root,
        "store": store,
        "workspace": workspace,
        "challenge": challenge,
        "artifacts": artifacts,
        "events": events,
        "manifests": manifests,
        "calls": calls,
        "proposals": proposals,
        "human": human,
        "preview": preview,
    }


def read_members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def parse_sha256sums(members: dict[str, bytes]) -> dict[str, str]:
    sums: dict[str, str] = {}
    for line in members["SHA256SUMS"].decode("utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        assert match is not None, line
        name, digest = match.group(2), match.group(1)
        assert name not in sums
        sums[name] = digest
    return sums


def export_dossier(dossier: dict, tmp_path: Path):
    return build_export_archive(
        data_root=dossier["data_root"],
        challenge=dossier["challenge"],
        project=None,
        events=dossier["events"],
        artifacts=dossier["artifacts"],
        manifests=dossier["manifests"],
        import_issues=[],
        artifact_store=dossier["store"],
        workspace_challenge=dossier["workspace"],
        generated_writeup_markdown=dossier["preview"].markdown,
        human_writeup=dossier["human"],
        writeup_integrity_error=None,
        completeness=dossier["preview"].completeness,
        missing_requirements=dossier["preview"].missing_requirements,
        writeup_warnings=dossier["preview"].warnings,
        integrity=VALID_INTEGRITY,
        model_calls=dossier["calls"],
        tool_proposals=dossier["proposals"],
    )


def test_export_snapshot_manifest_disclosure_and_sha256sums_are_consistent(
    tmp_path: Path,
) -> None:
    dossier = build_dossier(tmp_path)
    preview = dossier["preview"]
    human = dossier["human"]
    assert preview.completeness == "complete"
    assert preview.missing_requirements == []

    result = export_dossier(dossier, tmp_path)
    assert result.completeness == "complete"
    members = read_members(result.path)

    # The human draft is delivered byte for byte; the generated draft is the
    # same preview text that fed the manifest and the disclosure.
    assert members["writeup.md"] == human.content.encode("utf-8")
    assert members["writeup_generated.md"] == preview.markdown.encode("utf-8")
    for required in (
        "ai_disclosure.md",
        "manifest.json",
        "logs/events.json",
        "logs/timeline.json",
        "SHA256SUMS",
    ):
        assert required in members, required
    assert "INCOMPLETE.txt" not in members

    # SHA256SUMS covers every delivered file except itself.
    sums = parse_sha256sums(members)
    assert set(sums) == set(members) - {"SHA256SUMS"}
    for name, digest in sums.items():
        assert hashlib.sha256(members[name]).hexdigest() == digest, name

    manifest = json.loads(members["manifest.json"])
    disclosure = members["ai_disclosure.md"].decode("utf-8")

    # Manifest counters agree with the disclosed snapshot lengths.
    counts = manifest["counts"]
    assert counts["tool_proposals"] == len(manifest["tool_proposals"])
    assert counts["tool_proposals"] == preview.tool_proposal_count
    assert counts["tool_executions"] == manifest["tools"]["execution_count"]
    assert counts["tool_executions"] == preview.tool_execution_count
    assert counts["flag_confirmations"] == len(manifest["flag_confirmations"])
    assert counts["flag_confirmations"] == 1
    # Arbitrary execution stays disabled; only the fixed read-only tools can
    # run after human approval.
    assert manifest["tool_execution_enabled"] is False
    assert manifest["read_only_tool_execution_enabled"] is True

    # Manifest carries the same tool/Flag snapshots that were passed in.
    assert len(manifest["tool_proposals"]) == preview.tool_proposal_count
    assert manifest["tool_proposals"][0]["proposal_id"] == "prop-succeeded"
    assert manifest["tool_proposals"][0]["approval_id"] == "approval-success"
    assert manifest["tool_proposals"][0]["execution_id"] == "execution-success"
    assert manifest["tool_proposals"][0]["output_artifact_id"] == "artifact-tool-output"
    assert manifest["tool_proposals"][0]["output_sha256"] == hashlib.sha256(
        b"synthetic tool output"
    ).hexdigest()
    assert manifest["tools"]["proposal_count"] == preview.tool_proposal_count
    assert manifest["tools"]["execution_count"] == preview.tool_execution_count
    assert manifest["tools"]["failure_count"] == preview.tool_failure_count
    assert manifest["tool_execution_enabled"] is False
    assert len(manifest["model_calls"]) == 2
    assert [call["call_id"] for call in manifest["model_calls"]] == [
        "call-success",
        "call-failed",
    ]
    assert manifest["model_calls"][0]["delivery_status"] == "recorded"

    # Flag confirmation is a digest-only record, never a platform verification.
    assert len(manifest["flag_confirmations"]) == 1
    flag_record = manifest["flag_confirmations"][0]
    assert flag_record["platform_verified"] is False
    assert flag_record["flag_sha256"] == FLAG_DIGEST
    assert flag_record["flag_sha256_prefix"].startswith(FLAG_DIGEST[:16])
    assert FLAG_PLAINTEXT not in json.dumps(manifest, ensure_ascii=False)

    # Traceability links call -> proposal -> approval -> execution -> artifact.
    traceability = manifest["traceability"]
    assert traceability["model_call_ids"] == ["call-success", "call-failed"]
    assert set(traceability["tool_proposal_ids"]) == {
        "prop-succeeded",
        "prop-rejected",
        "prop-absolute",
    }
    success_chain = next(
        chain
        for chain in traceability["chains"]
        if chain["proposal_id"] == "prop-succeeded"
    )
    assert success_chain["complete"] is True
    assert success_chain["model_call_id"] == "call-success"
    assert success_chain["output_artifact_id"] == "artifact-tool-output"
    pending_chain = next(
        chain
        for chain in traceability["chains"]
        if chain["proposal_id"] == "prop-absolute"
    )
    assert pending_chain["complete"] is False

    # Absolute arguments are sanitised in both the manifest and disclosure.
    for document in (json.dumps(manifest, ensure_ascii=False), disclosure):
        assert "C:/Users/synthetic/secret.txt" not in document
        assert ABSOLUTE_PATH_PLACEHOLDER in document

    # ai_disclosure.md repeats exactly the manifest numbers.
    tools = manifest["tools"]
    call_stats = manifest["model_call_stats"]
    assert (
        f"本地工具申请统计（与 manifest.tools 一致）：共 {tools['proposal_count']} 条"
        in disclosure
    )
    assert f"获得人工批准 {tools['approved_count']} 条" in disclosure
    assert f"已开始执行 {tools['execution_count']} 次" in disclosure
    assert f"失败/超时 {tools['failure_count']} 次" in disclosure
    assert f"本题模型调用 {call_stats['call_count']} 次" in disclosure
    assert (
        "人工确认 Flag 统计（与 manifest.flag_confirmations 一致）："
        f"{len(manifest['flag_confirmations'])} 条"
    ) in disclosure
    assert "人工确认 Flag" in disclosure
    assert "成功 1，失败 1" in disclosure
    assert FLAG_DIGEST[:16] in disclosure
    assert "platform_verified=false" in disclosure
    assert "人工确认不等于平台验证成功" in disclosure

    # Timeline summaries disclose tool/Flag lifecycle without absolute paths.
    timeline = json.loads(members["logs/timeline.json"])
    summaries = [entry["summary"] for entry in timeline]
    assert any("prop-succeeded" in summary for summary in summaries)
    assert any("approval-success" in summary for summary in summaries)
    assert any("execution-success" in summary for summary in summaries)
    assert any("platform_verified=false" in summary for summary in summaries)
    assert "C:/Users/synthetic/secret.txt" not in json.dumps(timeline)

    # The manifest also records the exact delivered writeup digests.
    writeup = manifest["writeup"]
    assert writeup["final_source"] == "human"
    assert writeup["final_sha256"] == hashlib.sha256(members["writeup.md"]).hexdigest()
    assert writeup["final_size"] == len(members["writeup.md"])
    assert writeup["generated"]["sha256"] == hashlib.sha256(
        members["writeup_generated.md"]
    ).hexdigest()


def test_export_marks_incomplete_for_running_and_unrecorded_answer(
    tmp_path: Path,
) -> None:
    calls = [success_call(), unknown_call()]
    calls[0]["delivery_status"] = "not_recorded"
    proposals = [
        make_proposal(
            "prop-running",
            "running",
            approval_id="approval-running",
            execution_id="execution-running",
        ),
        make_proposal(
            "prop-succeeded-no-artifact",
            "succeeded",
            approval_id="approval-done",
            execution_id="execution-done",
        ),
    ]
    challenge = make_challenge()
    preview = build_writeup_preview(
        challenge,
        [],
        [],
        None,
        lambda _sha: b"",
        VALID_INTEGRITY,
        calls,
        proposals,
    )
    assert preview.completeness == "incomplete"

    data_root = tmp_path / "data"
    store = ArtifactStore(data_root / "artifacts")
    workspace = tmp_path / "workspace" / CHALLENGE_ID
    workspace.mkdir(parents=True)
    result = build_export_archive(
        data_root=data_root,
        challenge=challenge,
        project=None,
        events=[],
        artifacts=[],
        manifests=[],
        import_issues=[],
        artifact_store=store,
        workspace_challenge=workspace,
        generated_writeup_markdown=preview.markdown,
        human_writeup=None,
        writeup_integrity_error=None,
        completeness=preview.completeness,
        missing_requirements=preview.missing_requirements,
        writeup_warnings=preview.warnings,
        integrity=VALID_INTEGRITY,
        model_calls=calls,
        tool_proposals=proposals,
    )
    assert result.completeness == "incomplete"

    members = read_members(result.path)
    assert "INCOMPLETE.txt" in members
    manifest = json.loads(members["manifest.json"])
    missing = set(manifest["missing_requirements"])
    assert {
        "model_audit_incomplete",
        "model_response_unrecorded",
        "tool_execution_running",
        "tool_output_missing",
    } <= missing
    assert manifest["completeness"] == "incomplete"
    assert manifest["tools"]["status_counts"]["running"] == 1
    assert manifest["model_call_stats"]["delivery_not_recorded"] == 1
    assert manifest["counts"]["tool_proposals"] == len(manifest["tool_proposals"])
    assert (
        manifest["counts"]["tool_executions"]
        == manifest["tools"]["execution_count"]
    )
    assert manifest["counts"]["flag_confirmations"] == 0
    assert manifest["read_only_tool_execution_enabled"] is True

    disclosure = members["ai_disclosure.md"].decode("utf-8")
    assert "回答未入事件 1 次" in disclosure
    assert "运行中 1" in disclosure
    assert "档案完整性：incomplete" in disclosure
    assert "本证据档案不完整" in members["INCOMPLETE.txt"].decode("utf-8")
