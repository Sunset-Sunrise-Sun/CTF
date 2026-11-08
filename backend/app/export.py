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

import hashlib
import json
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .artifacts import (
    ArtifactIntegrityError,
    ArtifactPathError,
    ArtifactStore,
)
from .imports import ImportIssue, ImportManifest
from .models import ArtifactView, Challenge, Event, Project, now

_EXPORT_DIR = ".exports"
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
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


def _event_summary(event: Event) -> str:
    payload = event.payload
    event_type = event.event_type
    if event_type == "artifact_added":
        return (
            f"证据 {payload.get('artifact_id', '')} "
            f"sha256={str(payload.get('sha256', ''))[:16]}…"
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
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)[:160]


def _ai_disclosure(
    challenge: Challenge, project: Project | None, completeness: str
) -> str:
    lines = [
        "# AI 使用披露",
        "",
        "本档案由 CTF Workbench 本地证据工作台导出。",
        "",
        "- 工作台是否自动调用模型：否（本轮 MVP 未启用模型联网）",
        "- 工作台是否自动执行工具或命令：否（本轮为人工执行模式）",
        "- AI 建议是否被登记为人工执行事实：否",
        "- 是否自动生成 Flag 或平台验证截图：否",
        f"- 题目 AI 使用等级：{challenge.ai_usage_level}",
    ]
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
    lines.append(f"- 档案完整性：{completeness}")
    lines.append("")
    return "\n".join(lines)


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
    writeup_markdown: str,
    completeness: str,
    missing_requirements: list[str],
    writeup_warnings: list[str],
    integrity: dict,
) -> ExportResult:
    data_root = Path(data_root).resolve()
    export_dir = data_root / _EXPORT_DIR
    export_dir.mkdir(parents=True, exist_ok=True)
    final_path = export_dir / f"writeup-{challenge.challenge_id}.zip"
    temp_path = export_dir / f".export-{uuid4().hex}.zip.part"
    added: dict[str, str] = {}
    missing_files: list[str] = []
    warnings = list(writeup_warnings)
    import_statuses: list[dict] = []
    import_export_error = False
    manifests = sorted(manifests, key=lambda item: (item.created_at, item.import_id))

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
                "writeup.md",
                writeup_markdown.encode("utf-8"),
            )
            # Missing/tampered evidence or an unverified import makes the
            # delivered dossier incomplete even if metadata-level preview passed.
            export_completeness = (
                "incomplete" if (missing_files or import_export_error) else completeness
            )
            add_bytes(
                archive,
                "ai_disclosure.md",
                _ai_disclosure(challenge, project, export_completeness).encode("utf-8"),
            )

            manifest_payload = {
                "schema": "ctf-workbench-evidence-export/1",
                "generated_at": now(),
                "challenge": challenge.model_dump(),
                "project": project.model_dump() if project is not None else None,
                "counts": {
                    "events": len(events),
                    "artifacts": len(artifacts),
                    "imports": len(import_statuses),
                },
                "completeness": export_completeness,
                "missing_requirements": missing_requirements,
                "missing_files": missing_files,
                "warnings": sorted(set(warnings)),
                "integrity": integrity,
                "tool_execution_enabled": False,
                "ai_suggestions_are_not_actions": True,
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
                    *[f"- {item}" for item in missing_requirements],
                ]
                if missing_files:
                    incomplete_lines.extend(
                        [
                            "",
                            "缺失文件/未验证导入：",
                            *[f"- {item}" for item in missing_files],
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
