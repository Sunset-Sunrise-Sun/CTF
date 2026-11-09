"""Complete evidence dossier export as a ZIP archive.

The export is a read-only projection: it verifies every artifact against its
recorded SHA-256 before including it, keeps original bytes unchanged, orders
events by sequence, records missing evidence in the manifest, and writes a
SHA256SUMS file covering the delivered files.  An incomplete dossier is still
exportable but is marked prominently.

Every verified ZIP import is exported separately under
``challenge/imports/<import_id>/`` with its original archive and extracted
files.  An import whose manifest or files fail verification is listed in the
manifest with an explicit issue and makes the whole dossier incomplete.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .model_calls import disclosure_lines

from .artifacts import (
    ArtifactIntegrityError,
    ArtifactPathError,
    ArtifactStore,
)
from .imports import ImportIssue, ImportManifest
from .models import ArtifactView, Challenge, Event, Project, WriteupDraft, now
from .writeup import (
    disclosure_requirements,
    escape_absolute_paths,
    flag_confirmation_records,
    flag_disclosure_lines,
    model_call_statistics,
    sanitize_arguments,
    split_model_calls,
    tool_disclosure_lines,
    tool_proposal_snapshot,
    tool_proposal_statistics,
    traceability_snapshot,
)

_EXPORT_DIR = ".exports"
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
WRITEUP_NO_HUMAN_NOTE = "> 注意：尚未保存人工稿，本文件为服务器生成的初稿。\n\n"
WRITEUP_INTEGRITY_NOTE = (
    "> 注意：已保存的人工稿完整性校验失败，本文件为服务器生成的初稿。\n\n"
)
_KIND_DIRECTORIES = {
    "analysis": "evidence/analysis",
    "execution": "evidence/execution",
    "execution_output": "evidence/execution",
    "flag_capture": "evidence/flag_capture",
    "platform_verification": "evidence/platform_verification",
    "other": "evidence/other",
}


@dataclass(frozen=True)
class ExportResult:
    path: Path
    completeness: str


class ExportError(ValueError):
    """Raised when an export archive cannot be built."""


def _safe_name(filename: str, fallback: str) -> str:
    base = str(filename).replace("\\", "/").split("/")[-1]
    cleaned = "".join(
        character
        for character in base
        if character.isprintable() and character not in ':*?"<>|/\\'
    ).strip()
    if not cleaned or cleaned in {".", ".."}:
        return fallback
    return cleaned[:180]


def _safe_relative_path(path: str) -> str:
    normalised = path.replace("\\", "/")
    if normalised.startswith("/") or _DRIVE_PREFIX.match(normalised):
        raise ExportError("Unsafe extracted path in import manifest")
    parts: list[str] = []
    for part in normalised.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ExportError("Unsafe extracted path in import manifest")
        if ":" in part or any(ord(character) < 32 for character in part):
            raise ExportError("Unsafe extracted path in import manifest")
        parts.append(part)
    if not parts:
        raise ExportError("Unsafe extracted path in import manifest")
    return "/".join(parts)


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    return info


def _short_digest(value: object) -> str:
    digest = str(value or "")
    if not digest:
        return "未记录"
    return digest[:16] + ("…" if len(digest) > 16 else "")


def _event_summary(event: Event) -> str:
    payload = event.payload
    event_type = event.event_type
    if event_type == "artifact_added":
        return (
            f"证据 {payload.get('artifact_id', '')} "
            f"sha256={_short_digest(payload.get('sha256'))}"
        )
    if event_type == "challenge_imported":
        return (
            f"导入 ZIP {payload.get('original_filename', '')}："
            f"{payload.get('extracted_file_count', 0)} 个文件，"
            f"{payload.get('total_uncompressed_size', 0)} 字节"
        )
    if event_type == "manual_operation_recorded":
        command = str(payload.get("command", "")).replace("\n", " ")[:120]
        return f"人工运行记录：{command}"
    if event_type == "note":
        return str(payload.get("text", "")).replace("\n", " ")[:120]
    if event_type == "tool_proposed":
        arguments = sanitize_arguments(payload.get("arguments") or {})
        return escape_absolute_paths(
            f"工具申请 {payload.get('proposal_id', '')}："
            f"{payload.get('tool') or payload.get('tool_name') or ''} "
            + json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        )[:220]
    if event_type == "tool_approved":
        return (
            f"工具批准 {payload.get('proposal_id', '')}："
            f"approval_id={payload.get('approval_id') or '未记录'} "
            f"批准人={payload.get('approving_user') or payload.get('approved_by') or '未记录'}"
        )
    if event_type in {"tool_rejected", "tool_cancelled", "tool_expired"}:
        label = {
            "tool_rejected": "工具已拒绝",
            "tool_cancelled": "工具已取消",
            "tool_expired": "工具已过期",
        }[event_type]
        return escape_absolute_paths(
            f"{label} {payload.get('proposal_id', '')}："
            f"{payload.get('note') or payload.get('decision_note') or ''}"
        )[:220]
    if event_type == "tool_started":
        return (
            f"工具执行开始 {payload.get('proposal_id', '')}："
            f"execution_id={payload.get('execution_id') or '未记录'}"
        )
    if event_type == "tool_finished":
        return (
            f"工具执行结束 {payload.get('proposal_id', '')}："
            f"状态 {payload.get('status', '')}，"
            f"execution_id={payload.get('execution_id') or '未记录'}，"
            f"output_artifact_id={payload.get('output_artifact_id') or '无'}，"
            f"output_sha256={_short_digest(payload.get('output_sha256'))}"
        )
    if event_type == "flag_confirmed":
        return (
            "人工确认 Flag："
            f"SHA-256 前缀 {_short_digest(payload.get('flag_sha256'))}，"
            f"长度 {payload.get('flag_length', '未记录')}，"
            "platform_verified=false"
        )
    if event_type == "model_call":
        return (
            f"模型调用 {payload.get('call_id', '')}："
            f"{payload.get('provider_id', '')}/{payload.get('model_id', '')} "
            f"状态 {payload.get('response_status', 'unknown')}"
        )
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)[:160]


def _ai_disclosure(
    challenge: Challenge,
    project: Project | None,
    completeness: str,
    writeup_source: str,
    model_calls: list[dict] | None,
    tool_proposals: list[object] | None,
    events: list[Event],
) -> str:
    challenge_calls, synthetic_calls = split_model_calls(model_calls)
    call_stats = model_call_statistics(model_calls)
    proposal_snapshot = tool_proposal_snapshot(tool_proposals)
    tool_stats = tool_proposal_statistics(proposal_snapshot)
    flag_records = flag_confirmation_records(events)
    status_counts = tool_stats["status_counts"]
    status_text = "，".join(
        f"{label} {status_counts.get(status, 0)}"
        for status, label in (
            ("pending", "待批准"),
            ("approved", "已批准"),
            ("running", "运行中"),
            ("succeeded", "成功"),
            ("failed", "失败"),
            ("timed_out", "已超时"),
            ("rejected", "已拒绝"),
            ("cancelled", "已取消"),
            ("expired", "已过期"),
        )
    )
    lines = [
        "# AI 使用披露",
        "",
        "本档案由 CTF Workbench 本地证据工作台导出。",
        "",
        "- 工作台是否自动执行工具或命令：否（工具执行必须经过人工审批；自动工具执行未启用）",
        "- AI 建议是否被登记为人工执行事实：否",
        "- 是否自动生成 Flag 或平台验证截图：否",
        f"- 题目 AI 使用等级：{challenge.ai_usage_level}",
    ]
    lines.extend(disclosure_lines(challenge_calls))
    lines.append(
        "- 模型调用统计（与 manifest.model_call_stats 一致）：本题模型调用 "
        f"{call_stats['call_count']} 次（成功 {call_stats['successful']}，"
        f"失败 {call_stats['failed']}，取消 {call_stats['cancelled']}，"
        f"未确定 {call_stats['unknown']}）；回答未入事件 "
        f"{call_stats['delivery_not_recorded']} 次；合成连通性测试调用 "
        f"{call_stats['synthetic_call_count']} 次单独统计，不包含题目数据。"
    )
    if synthetic_calls:
        lines.append(
            "- 合成连通性测试调用不计入本题模型调用，且不携带题目数据。"
        )
    lines.append(
        "- 工具执行必须由人工逐次批准；自动工具执行未启用，"
        "工具结果不等同于模型推断。"
    )
    lines.append(
        "- 本地工具申请统计（与 manifest.tools 一致）：共 "
        f"{tool_stats['proposal_count']} 条（当前状态：{status_text}）；"
        f"获得人工批准 {tool_stats['approved_count']} 条，"
        f"已开始执行 {tool_stats['execution_count']} 次，"
        f"唯一输出 Artifact {tool_stats['unique_output_artifact_count']} 个，"
        f"失败/超时 {tool_stats['failure_count']} 次。"
    )
    lines.append(
        "- 人工确认 Flag 统计（与 manifest.flag_confirmations 一致）："
        f"{len(flag_records)} 条；仅记录 SHA-256 与长度，platform_verified=false，"
        "人工确认不等于平台验证成功。"
    )
    lines.append("")
    lines.extend(tool_disclosure_lines(proposal_snapshot))
    lines.append("")
    lines.extend(flag_disclosure_lines(events))
    lines.append("")
    if project is not None:
        lines.append(f"- 比赛规则 AI 政策摘要：{project.ai_policy_summary or '未填写'}")
        if project.rules_sha256:
            lines.append(
                f"- 比赛规则文件：{project.rules_filename} "
                f"(SHA256 {project.rules_sha256})"
            )
    lines.append(
        "- 所有运行记录均为选手在工作台之外手动执行后在本地补录，"
        "标记为 execution_mode=manual_external、execution_verified=false。"
    )
    lines.append(f"- 最终 Writeup 来源：{writeup_source}")
    lines.append(f"- 档案完整性：{completeness}")
    lines.append("")
    return "\n".join(lines)


def _writeup_diff(generated: str, human: str) -> dict:
    """Describe human-vs-server Writeup differences without overwriting either."""
    generated_bytes = generated.encode("utf-8")
    human_bytes = human.encode("utf-8")
    change = list(
        difflib.unified_diff(
            generated.splitlines(keepends=True),
            human.splitlines(keepends=True),
            fromfile="writeup_generated.md",
            tofile="writeup.md",
            n=2,
        )
    )
    added = sum(1 for line in change if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in change if line.startswith("-") and not line.startswith("---"))
    preview = "".join(change)
    encoded = preview.encode("utf-8")
    if len(encoded) > 16_384:
        encoded = encoded[:16_384] + b"\n...[diff truncated]\n"
        preview = encoded.decode("utf-8", errors="replace")
    return {
        "changed": generated_bytes != human_bytes,
        "generated_sha256": hashlib.sha256(generated_bytes).hexdigest(),
        "human_sha256": hashlib.sha256(human_bytes).hexdigest(),
        "added_lines": added,
        "removed_lines": removed,
        "diff_sha256": hashlib.sha256("".join(change).encode("utf-8")).hexdigest(),
        "diff_preview": preview,
        "final_source": "human",
        "human_never_overwritten": True,
    }


def _normalise_calls(model_calls: list[object] | None) -> list[dict]:
    normalised: list[dict] = []
    for call in model_calls or []:
        if isinstance(call, dict):
            normalised.append(dict(call))
            continue
        dump = getattr(call, "model_dump", None)
        normalised.append(dump() if callable(dump) else dict(call))
    return normalised


def build_export_archive(
    *,
    data_root: Path,
    challenge: Challenge,
    project: Project | None,
    events: list[Event],
    artifacts: list[ArtifactView],
    manifests: list[ImportManifest],
    import_issues: list[ImportIssue],
    artifact_store: ArtifactStore,
    workspace_challenge: Path,
    generated_writeup_markdown: str,
    human_writeup: WriteupDraft | None,
    writeup_integrity_error: str | None,
    completeness: str,
    missing_requirements: list[str],
    writeup_warnings: list[str],
    integrity: dict,
    model_calls: list[dict] | None = None,
    tool_proposals: list[object] | None = None,
) -> ExportResult:
    # One snapshot feeds the preview-derived writeup, the manifest, the AI
    # disclosure and the timeline: nothing below re-reads or re-derives facts.
    calls = _normalise_calls(model_calls)
    proposal_snapshot = tool_proposal_snapshot(tool_proposals)
    call_stats = model_call_statistics(calls)
    tool_stats = tool_proposal_statistics(proposal_snapshot)
    flag_records = flag_confirmation_records(events)
    traceability = traceability_snapshot(challenge, calls, proposal_snapshot)
    disclosure_missing, disclosure_warnings = disclosure_requirements(
        model_calls, tool_proposals, integrity
    )
    export_missing_requirements = list(missing_requirements)
    for code in disclosure_missing:
        if code not in export_missing_requirements:
            export_missing_requirements.append(code)
    if not integrity.get("valid") and "integrity" not in export_missing_requirements:
        export_missing_requirements.append("integrity")
    data_root = Path(data_root).resolve()
    export_dir = data_root / _EXPORT_DIR
    export_dir.mkdir(parents=True, exist_ok=True)
    final_path = export_dir / f"writeup-{challenge.challenge_id}.zip"
    temp_path = export_dir / f".export-{uuid4().hex}.zip.part"
    added: dict[str, str] = {}
    missing_files: list[str] = []
    warnings = list(writeup_warnings)
    for warning in disclosure_warnings:
        if warning not in warnings:
            warnings.append(warning)
    import_statuses: list[dict] = []
    import_export_error = False
    manifests = sorted(manifests, key=lambda item: (item.created_at, item.import_id))

    generated_writeup_bytes = generated_writeup_markdown.encode("utf-8")
    if human_writeup is not None:
        final_writeup_bytes = human_writeup.content.encode("utf-8")
        final_writeup_source = "human"
        writeup_source_label = f"人工稿 v{human_writeup.version}"
    elif writeup_integrity_error is not None:
        final_writeup_bytes = (
            WRITEUP_INTEGRITY_NOTE + generated_writeup_markdown
        ).encode("utf-8")
        final_writeup_source = "generated"
        writeup_source_label = "服务器初稿（人工稿完整性校验失败后的 fallback）"
        warnings.append(
            "已保存的人工稿完整性校验失败，未使用人工稿：" + writeup_integrity_error
        )
    else:
        final_writeup_bytes = (
            WRITEUP_NO_HUMAN_NOTE + generated_writeup_markdown
        ).encode("utf-8")
        final_writeup_source = "generated"
        writeup_source_label = "服务器初稿（尚未保存人工稿）"

    def add_bytes(archive, arcname: str, data: bytes) -> None:
        archive.writestr(_zip_info(arcname), data)
        added[arcname] = hashlib.sha256(data).hexdigest()

    def read_artifact(artifact: ArtifactView) -> bytes | None:
        try:
            return artifact_store.read_verified(artifact.sha256)
        except (ArtifactIntegrityError, ArtifactPathError):
            missing_files.append(
                f"{artifact.original_filename} ({artifact.artifact_id})"
            )
            warnings.append(
                f"证据文件完整性校验失败，未导出：{artifact.original_filename}"
            )
            return None

    def export_import(archive, manifest: ImportManifest) -> dict:
        nonlocal import_export_error
        prefix = f"challenge/imports/{manifest.import_id}"
        status = {
            "import_id": manifest.import_id,
            "original_artifact_id": manifest.original_artifact_id,
            "original_filename": manifest.original_filename,
            "extracted_file_count": manifest.extracted_file_count,
            "total_uncompressed_size": manifest.total_uncompressed_size,
            "created_at": manifest.created_at,
            "status": "exported",
            "exported_file_count": 0,
            "original_archive_entry_count": len(manifest.files),
            "original_archive_entries": [
                item.relative_path for item in manifest.files
            ],
            "generated_manifest": None,
            "missing_files": [],
            "error": None,
        }
        original = next(
            (
                artifact
                for artifact in artifacts
                if artifact.artifact_id == manifest.original_artifact_id
            ),
            None,
        )
        if original is None:
            status["missing_files"].append(f"{prefix}/original.zip")
            missing_files.append(f"{prefix}/original.zip")
            warnings.append(f"导入原始 ZIP 证据缺失：{manifest.import_id}")
        else:
            data = read_artifact(original)
            if data is None:
                status["missing_files"].append(f"{prefix}/original.zip")
            else:
                add_bytes(archive, f"{prefix}/original.zip", data)
                status["exported_file_count"] += 1
        # The import system writes this canonical manifest into the extracted
        # directory.  It is generated metadata, not an entry of the original
        # challenge ZIP, so keep it labelled and separate from original entries.
        generated_manifest = manifest.canonical_bytes()
        generated_name = f"{prefix}/generated-manifest.json"
        add_bytes(archive, generated_name, generated_manifest)
        status["generated_manifest"] = {
            "path": generated_name,
            "sha256": hashlib.sha256(generated_manifest).hexdigest(),
            "size": len(generated_manifest),
            "is_original_archive_entry": False,
            "generated_by": "ctf-workbench-import",
        }
        import_root = workspace_challenge / "imports" / manifest.import_id
        for item in manifest.files:
            try:
                relative = _safe_relative_path(item.relative_path)
            except ExportError as error:
                status["missing_files"].append(item.relative_path)
                missing_files.append(f"{prefix}/extracted/{item.relative_path}")
                warnings.append(f"{error}（{manifest.import_id}）")
                continue
            source = import_root.joinpath(*relative.split("/"))
            try:
                resolved = source.resolve()
                resolved.relative_to(import_root.resolve())
                data = resolved.read_bytes()
            except (OSError, ValueError):
                status["missing_files"].append(relative)
                missing_files.append(f"{prefix}/extracted/{relative}")
                warnings.append(
                    f"解压文件缺失，未导出：{manifest.import_id}/{relative}"
                )
                continue
            if (
                len(data) != item.size
                or hashlib.sha256(data).hexdigest() != item.sha256
            ):
                status["missing_files"].append(relative)
                missing_files.append(f"{prefix}/extracted/{relative}")
                warnings.append(
                    f"解压文件大小或哈希不匹配，未导出：{manifest.import_id}/{relative}"
                )
                continue
            add_bytes(archive, f"{prefix}/extracted/{relative}", data)
            status["exported_file_count"] += 1
        if status["missing_files"]:
            status["status"] = "incomplete"
            import_export_error = True
        import_statuses.append(status)
        return status

    try:
        with zipfile.ZipFile(
            temp_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
        ) as archive:
            for manifest in manifests:
                export_import(archive, manifest)

            for issue in import_issues:
                import_export_error = True
                import_statuses.append(
                    {
                        "import_id": issue.import_id,
                        "original_artifact_id": None,
                        "original_filename": None,
                        "extracted_file_count": 0,
                        "total_uncompressed_size": 0,
                        "created_at": None,
                        "status": "unverified",
                        "exported_file_count": 0,
                        "missing_files": [],
                        "error": issue.reason,
                    }
                )
                missing_files.append(
                    f"challenge/imports/{issue.import_id} (unverified)"
                )
                warnings.append(
                    "导入记录未通过 Manifest/事件校验，未导出："
                    f"{issue.import_id}（{issue.reason}）"
                )
            if not manifests and not import_issues:
                missing_files.append("challenge/imports")
                warnings.append("尚未导入题目 ZIP")

            used_paths = set(added)
            for artifact in artifacts:
                if artifact.evidence_kind == "challenge_archive":
                    continue
                directory = _KIND_DIRECTORIES.get(
                    artifact.evidence_kind, "evidence/other"
                )
                if artifact.evidence_kind == "source_code":
                    directory = "scripts"
                base = _safe_name(
                    artifact.original_filename,
                    f"artifact-{artifact.artifact_id[:8]}.bin",
                )
                arcname = f"{directory}/{base}"
                if arcname in used_paths:
                    arcname = f"{directory}/{artifact.artifact_id[:8]}-{base}"
                used_paths.add(arcname)
                data = read_artifact(artifact)
                if data is not None:
                    add_bytes(archive, arcname, data)

            if project is not None and project.rules_sha256:
                try:
                    rules = artifact_store.read_verified(project.rules_sha256)
                except (ArtifactIntegrityError, ArtifactPathError):
                    rules = None
                    missing_files.append("challenge/rules")
                    warnings.append("比赛规则文件完整性校验失败，未导出")
                if rules is not None:
                    rules_name = _safe_name(
                        project.rules_filename or "rules.pdf", "rules.pdf"
                    )
                    add_bytes(archive, f"challenge/rules/{rules_name}", rules)

            events_sorted = sorted(events, key=lambda event: event.sequence)
            events_bytes = json.dumps(
                [event.model_dump() for event in events_sorted],
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            add_bytes(archive, "logs/events.json", events_bytes)
            timeline = [
                {
                    "sequence": event.sequence,
                    "occurred_at": event.occurred_at,
                    "actor": event.actor,
                    "event_type": event.event_type,
                    "summary": _event_summary(event),
                    "artifact_ids": list(event.artifact_ids),
                    "event_id": event.event_id,
                }
                for event in events_sorted
            ]
            add_bytes(
                archive,
                "logs/timeline.json",
                json.dumps(timeline, ensure_ascii=False, indent=2).encode("utf-8"),
            )
            add_bytes(
                archive,
                "writeup_generated.md",
                generated_writeup_bytes,
            )
            add_bytes(archive, "writeup.md", final_writeup_bytes)
            # Missing/tampered evidence, an unverified import or an unresolved
            # disclosure fact makes the delivered dossier incomplete even if the
            # metadata-level preview passed.
            export_completeness = (
                "incomplete"
                if (
                    missing_files
                    or import_export_error
                    or writeup_integrity_error is not None
                    or export_missing_requirements
                )
                else completeness
            )
            disclosure_markdown = _ai_disclosure(
                challenge,
                project,
                export_completeness,
                writeup_source_label,
                calls,
                proposal_snapshot,
                events,
            ).encode("utf-8")
            add_bytes(archive, "ai_disclosure.md", disclosure_markdown)

            manifest_payload = {
                "schema": "ctf-workbench-evidence-export/1",
                "generated_at": now(),
                "challenge": challenge.model_dump(),
                "project": project.model_dump() if project is not None else None,
                "counts": {
                    "events": len(events),
                    "artifacts": len(artifacts),
                    "imports": len(import_statuses),
                    "tool_proposals": len(proposal_snapshot),
                    "tool_executions": tool_stats["execution_count"],
                    "flag_confirmations": len(flag_records),
                },
                "completeness": export_completeness,
                "missing_requirements": export_missing_requirements,
                "missing_files": missing_files,
                "warnings": sorted(set(warnings)),
                "integrity": integrity,
                # No arbitrary command/shell/Python execution is enabled; only
                # the fixed read-only tool registry can run, after human
                # approval of each proposal.
                "tool_execution_enabled": False,
                "read_only_tool_execution_enabled": True,
                "ai_suggestions_are_not_actions": True,
                "model_calls": calls,
                "model_call_stats": call_stats,
                "tool_proposals": proposal_snapshot,
                "tools": tool_stats,
                "flag_confirmations": flag_records,
                "traceability": traceability,
                "writeup": {
                    "final_source": final_writeup_source,
                    "final_sha256": hashlib.sha256(final_writeup_bytes).hexdigest(),
                    "final_size": len(final_writeup_bytes),
                    "generated": {
                        "sha256": hashlib.sha256(generated_writeup_bytes).hexdigest(),
                        "size": len(generated_writeup_bytes),
                    },
                    "human": (
                        {
                            "version": human_writeup.version,
                            "sha256": human_writeup.sha256,
                            "size": human_writeup.size,
                            "saved_at": human_writeup.saved_at,
                        }
                        if human_writeup is not None
                        else None
                    ),
                    "integrity_error": writeup_integrity_error,
                    "human_generated_diff": (
                        _writeup_diff(generated_writeup_markdown, human_writeup.content)
                        if human_writeup is not None
                        else None
                    ),
                },
                "imports": import_statuses,
                "artifacts": [
                    {
                        "artifact_id": artifact.artifact_id,
                        "original_filename": artifact.original_filename,
                        "sha256": artifact.sha256,
                        "size": artifact.size,
                        "media_type": artifact.media_type,
                        "evidence_kind": artifact.evidence_kind,
                        "capture_time_claim": artifact.capture_time_claim,
                        "ingested_at": artifact.ingested_at,
                        "source_event_id": artifact.source_event_id,
                    }
                    for artifact in artifacts
                ],
            }
            manifest_bytes = json.dumps(
                manifest_payload, ensure_ascii=False, indent=2, sort_keys=True
            ).encode("utf-8")
            add_bytes(archive, "manifest.json", manifest_bytes)

            if export_completeness != "complete" or missing_files:
                incomplete_lines = [
                    "本证据档案不完整（INCOMPLETE）。",
                    "",
                    "缺失/未确认项：",
                    *[f"- {item}" for item in export_missing_requirements],
                ]
                if missing_files:
                    incomplete_lines.extend(
                        [
                            "",
                            "缺失文件/未验证导入：",
                            *[f"- {item}" for item in missing_files],
                        ]
                    )
                if writeup_integrity_error is not None:
                    incomplete_lines.extend(
                        [
                            "",
                            "人工稿完整性错误：",
                            f"- {writeup_integrity_error}",
                            "- 导出已改用服务器初稿，不包含被篡改的人工稿内容。",
                        ]
                    )
                incomplete_lines.append("")
                add_bytes(
                    archive,
                    "INCOMPLETE.txt",
                    "\n".join(incomplete_lines).encode("utf-8"),
                )

            sums = "".join(
                f"{checksum}  {name}\n" for name, checksum in sorted(added.items())
            ).encode("utf-8")
            # SHA256SUMS itself is not listed, it covers every other delivered file.
            archive.writestr(_zip_info("SHA256SUMS"), sums)

        os.replace(temp_path, final_path)
        return ExportResult(path=final_path, completeness=export_completeness)
    except BaseException:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise
