"""Deterministic Writeup draft generated only from recorded evidence.

The generator consumes challenge metadata, the ordered event log, artifacts and
the project rules configuration.  It never invents commands, screenshots, a
flag or a verification result: missing evidence is rendered with an explicit
marker and makes the dossier incomplete.

AI/tool disclosure follows one rule: the caller passes the snapshots it actually
read (``calls`` = merged ModelCallJournal records for this challenge,
``tool_proposals`` = the ``tool_proposals`` table snapshot).  Nothing here
re-derives model calls from events, so the preview, the exported ZIP and
``ai_disclosure.md`` always describe the same facts.  Synthetic connectivity
calls are counted separately and never mixed into challenge call counts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable

from .model_calls import disclosure_lines
from .models import ArtifactView, Challenge, Event, Project, WriteupPreview

MISSING_APPROACH = "[待选手补充：核心解题思路]"
MISSING_FLAG_CAPTURE = "[证据缺失：Flag 获取即时截图尚未提供]"
MISSING_PLATFORM_VERIFICATION = "[证据缺失：平台验证截图尚未提供]"
MISSING_MANUAL_OPERATION = "[证据缺失：尚无人工运行记录]"
MISSING_AI_LEVEL = "[待确认：AI 使用等级尚未确认]"
MISSING_CODE = "[证据缺失：尚未上传核心代码或脚本]"
NOT_APPLICABLE_CODE = "[不适用：synthetic connectivity 没有独立解题代码；不伪造代码证据]"
NOT_APPLICABLE_FLAG = "[不适用：synthetic connectivity 没有真实 Flag；不伪造 Flag 截图]"
MISSING_EXECUTION_EVIDENCE = "[证据缺失：尚无运行截图或执行输出证据]"

_TOOL_STATUS_LABELS: dict[str, str] = {
    "pending": "待批准",
    "approved": "已批准",
    "running": "运行中",
    "succeeded": "成功",
    "failed": "失败",
    "timed_out": "已超时",
    "rejected": "已拒绝",
    "cancelled": "已取消",
    "expired": "已过期",
}
_TOOL_STATUS_ORDER = tuple(_TOOL_STATUS_LABELS)
_EXECUTION_STATUSES = frozenset({"running", "succeeded", "failed", "timed_out"})
_FAILURE_STATUSES = frozenset({"failed", "timed_out"})

_CODE_SUFFIXES = {
    ".py",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".js",
    ".mjs",
    ".ts",
    ".sh",
    ".ps1",
    ".rb",
    ".go",
    ".rs",
    ".php",
    ".java",
    ".txt",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".html",
    ".css",
    ".sql",
}
_IMAGE_PREFIX = "image/"
_TEXT_PREFIX = "text/"
_MAX_CODE_FILES = 10
_MAX_CODE_BYTES_PER_FILE = 20 * 1024
_MAX_CODE_BYTES_TOTAL = 150 * 1024

_REQUIRED_EVIDENCE = (
    ("core_approach", "人工填写的核心解题思路"),
    ("manual_operation", "人工运行记录"),
    ("core_code", "核心代码/脚本证据"),
    ("execution_evidence", "运行截图或执行输出证据"),
    ("flag_capture", "Flag 获取截图"),
    ("platform_verification", "平台验证截图"),
    ("ai_usage_level", "AI 使用等级确认"),
)

_MISSING_LABELS: dict[str, str] = dict(_REQUIRED_EVIDENCE)
_MISSING_LABELS.update(
    {
        "integrity": "事件哈希链完整性",
        "model_audit_incomplete": "模型调用审计未终结或缺少题目事件关联",
        "model_response_unrecorded": "模型已响应但回答未写入题目事件",
        "tool_execution_running": "存在仍在运行中的工具执行",
        "tool_output_missing": "成功工具执行缺少输出 Artifact",
    }
)

_REMEDIATION = {
    "core_approach": "由选手在 Writeup 工作区新增 kind=approach 的人工解题思路笔记。",
    "manual_operation": "由选手在工作台外手动执行后，通过人工运行记录接口补录命令、时间与结果。",
    "core_code": "上传独立解题脚本/源码，evidence_kind 设为 source_code 或 analysis。",
    "execution_evidence": "上传执行截图或保留只读工具输出的 execution_output Artifact。",
    "flag_capture": "由选手上传 Flag 获取即时截图，evidence_kind=flag_capture。",
    "platform_verification": "由选手上传平台验证截图，evidence_kind=platform_verification。",
    "ai_usage_level": "将题目 AI 使用等级设置为实际使用的 A0/A1/A2。",
    "integrity": "修复被影响的事件链；不得删除或重写证据。",
    "model_audit_incomplete": "等待未终结模型调用完成，或补齐回答事件关联。",
    "model_response_unrecorded": "将模型回答写入题目事件，或明确记录失败。",
    "tool_execution_running": "等待运行中的工具执行结束并记录终态。",
    "tool_output_missing": "修复成功执行缺少输出 Artifact 的记录。",
}
_SYNTHETIC_NA_REASONS = {
    "core_code": "synthetic connectivity 测试没有真实题目，也没有独立解题代码；不伪造代码证据。",
    "flag_capture": "synthetic connectivity 测试没有真实 Flag；不伪造 Flag 获取截图。",
}


def is_synthetic_connectivity(challenge: Challenge) -> bool:
    """Return true only for an explicitly synthetic connectivity challenge.

    The explicit profile is authoritative.  A narrow legacy-name fallback
    keeps pre-existing synthetic smoke-test challenges from being treated as
    real challenges after upgrade; real challenges keep the default profile.
    """
    profile = getattr(challenge, "evidence_profile", "real_challenge")
    if profile == "synthetic_connectivity":
        return True
    if profile != "real_challenge":
        return False
    label = f"{challenge.name} {challenge.description}".casefold()
    return "synthetic connectivity" in label or "合成连通" in label


def _requirement(
    code: str,
    *,
    proven: bool,
    synthetic: bool = False,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    label = _MISSING_LABELS.get(code, code)
    if synthetic and code in _SYNTHETIC_NA_REASONS:
        return {
            "code": code,
            "label": label,
            "status": "not_applicable",
            "reason": _SYNTHETIC_NA_REASONS[code],
            "evidence": [],
            "remediation": None,
        }
    if proven:
        return {
            "code": code,
            "label": label,
            "status": "proven",
            "reason": "已由审计事件或证据 Artifact 证明。",
            "evidence": evidence or [],
            "remediation": None,
        }
    return {
        "code": code,
        "label": label,
        "status": "missing",
        "reason": "必需证据尚未提供。",
        "evidence": [],
        "remediation": _REMEDIATION.get(code),
    }


def _requirement_list(
    *,
    synthetic: bool,
    approaches: list[Event],
    manual_ops: list[Event],
    code_artifacts: list[ArtifactView],
    execution_artifacts: list[ArtifactView],
    flag_artifacts: list[ArtifactView],
    platform_artifacts: list[ArtifactView],
    ai_usage_level: str,
    integrity_valid: bool,
) -> list[dict[str, Any]]:
    rows = [
        _requirement(
            "core_approach",
            proven=bool(approaches),
            synthetic=synthetic,
            evidence=[f"event:{event.event_id}" for event in approaches[-3:]],
        ),
        _requirement(
            "manual_operation",
            proven=bool(manual_ops),
            synthetic=synthetic,
            evidence=[f"event:{event.event_id}" for event in manual_ops[-3:]],
        ),
        _requirement(
            "core_code",
            proven=bool(code_artifacts),
            synthetic=synthetic,
            evidence=[f"artifact:{item.artifact_id}" for item in code_artifacts[-3:]],
        ),
        _requirement(
            "execution_evidence",
            proven=bool(execution_artifacts),
            synthetic=synthetic,
            evidence=[
                f"artifact:{item.artifact_id}" for item in execution_artifacts[-3:]
            ],
        ),
        _requirement(
            "flag_capture",
            proven=bool(flag_artifacts),
            synthetic=synthetic,
            evidence=[f"artifact:{item.artifact_id}" for item in flag_artifacts[-3:]],
        ),
        _requirement(
            "platform_verification",
            proven=bool(platform_artifacts),
            synthetic=synthetic,
            evidence=[
                f"artifact:{item.artifact_id}" for item in platform_artifacts[-3:]
            ],
        ),
        _requirement(
            "ai_usage_level",
            proven=ai_usage_level != "unknown",
            synthetic=synthetic,
            evidence=[f"challenge.ai_usage_level={ai_usage_level}"],
        ),
        _requirement(
            "integrity",
            proven=integrity_valid,
            synthetic=synthetic,
            evidence=["event_hash_chain:valid"] if integrity_valid else [],
        ),
    ]
    return rows

# Absolute Windows drive paths, UNC paths and POSIX absolute paths must never be
# copied into exported disclosure text from tool arguments.
_WINDOWS_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|//)")
_POSIX_ABSOLUTE = re.compile(r"^/(?!/)")
_ABSOLUTE_TOKEN = re.compile(r"(?:[A-Za-z]:[\\/][^\s\"'，；)）]*|\\\\[^\s\"'，；)）]+)")
ABSOLUTE_PATH_PLACEHOLDER = "[绝对路径已省略]"


def escape_absolute_paths(text: str) -> str:
    """Best-effort redaction of absolute paths embedded in free text."""

    return _ABSOLUTE_TOKEN.sub(ABSOLUTE_PATH_PLACEHOLDER, str(text))


def _looks_absolute(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    return bool(
        _WINDOWS_ABSOLUTE.match(text) or _POSIX_ABSOLUTE.match(text) or re.match(
            r"^[A-Za-z]:", text
        )
    )


def sanitize_arguments(arguments: object) -> dict[str, Any]:
    """Render tool arguments without leaking absolute filesystem paths.

    Tool schemas only accept workspace-relative paths, so this is a defensive
    second line of defence: any value that still looks absolute is replaced by
    a fixed placeholder instead of being copied into a deliverable.
    """

    def clean(value: object) -> object:
        if isinstance(value, str):
            return ABSOLUTE_PATH_PLACEHOLDER if _looks_absolute(value) else value
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {str(key): clean(item) for key, item in value.items()}
        return value

    if not isinstance(arguments, dict):
        return {}
    return {str(key): clean(value) for key, value in arguments.items()}


def _escape_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _fence(content: str) -> str:
    longest = 0
    current = 0
    for character in content:
        if character == "`":
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return "`" * max(3, longest + 1)


def _render_code(content: str, language: str) -> str:
    fence = _fence(content)
    return f"{fence}{language}\n{content.rstrip()}\n{fence}"


def _is_text_artifact(artifact: ArtifactView) -> bool:
    if artifact.media_type.startswith(_IMAGE_PREFIX):
        return False
    if artifact.media_type.startswith(_TEXT_PREFIX):
        return True
    return Path(artifact.original_filename).suffix.casefold() in _CODE_SUFFIXES


def _kind(artifact: ArtifactView) -> str:
    return artifact.evidence_kind


# ---------------------------------------------------------------------------
# Shared disclosure helpers (also used by export.py so both deliverables show
# exactly the same numbers for the same snapshot).
# ---------------------------------------------------------------------------


def _field(item: object, name: str, default: object = None) -> object:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _as_mapping(item: object) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    dump = getattr(item, "model_dump", None)
    if callable(dump):
        return dump()
    return {
        key: getattr(item, key)
        for key in (
            "proposal_id",
            "challenge_id",
            "model_call_id",
            "tool_name",
            "arguments",
            "reason",
            "risk_level",
            "status",
            "proposed_by",
            "proposed_at",
            "expires_at",
        )
        if hasattr(item, key)
    }


def _clean_text(value: object) -> str:
    return escape_absolute_paths(str(value))


def _clean_optional(value: object) -> str | None:
    if value is None:
        return None
    text = _clean_text(value)
    return text or None


def split_model_calls(
    calls: Iterable[dict] | None,
) -> tuple[list[dict], list[dict]]:
    """Split the passed call snapshot into challenge calls and synthetic ones."""

    challenge_calls: list[dict] = []
    synthetic_calls: list[dict] = []
    for call in calls or []:
        item = _as_mapping(call)
        if bool(item.get("synthetic")):
            synthetic_calls.append(item)
        else:
            challenge_calls.append(item)
    return challenge_calls, synthetic_calls


def model_call_statistics(calls: Iterable[dict] | None) -> dict[str, Any]:
    """Count model calls from the passed journal snapshot only.

    ``response_status == "unknown"`` is counted as undetermined, never as a
    failure.  Synthetic connectivity calls are reported separately and are not
    part of the challenge call count.
    """

    challenge_calls, synthetic_calls = split_model_calls(calls)
    statuses = [str(call.get("response_status", "unknown")) for call in challenge_calls]
    successful = statuses.count("success")
    cancelled = statuses.count("cancelled")
    unknown = statuses.count("unknown")
    failed = len(statuses) - successful - cancelled - unknown
    not_recorded = sum(
        1
        for call in challenge_calls
        if call.get("response_status") == "success"
        and call.get("delivery_status") == "not_recorded"
    )
    providers = sorted(
        {
            str(call.get("provider_id"))
            for call in challenge_calls
            if call.get("provider_id")
        }
    )
    models = sorted(
        {
            str(call.get("model_id"))
            for call in challenge_calls
            if call.get("model_id")
        }
    )
    return {
        "call_count": len(challenge_calls),
        "successful": successful,
        "failed": failed,
        "cancelled": cancelled,
        "unknown": unknown,
        "delivery_not_recorded": not_recorded,
        "synthetic_call_count": len(synthetic_calls),
        "providers": providers,
        "models": models,
    }


def tool_proposal_snapshot(
    tool_proposals: Iterable[object] | None,
) -> list[dict[str, Any]]:
    """Normalise the tool proposal snapshot into JSON-safe disclosure records."""

    snapshot: list[dict[str, Any]] = []
    for proposal in tool_proposals or []:
        row = _as_mapping(proposal)
        status = str(row.get("status") or "pending")
        artifact_ids = row.get("artifact_ids")
        snapshot.append(
            {
                "proposal_id": row.get("proposal_id"),
                "challenge_id": row.get("challenge_id"),
                "model_call_id": row.get("model_call_id"),
                "tool_name": row.get("tool_name"),
                "arguments": sanitize_arguments(row.get("arguments") or {}),
                "reason": _clean_optional(row.get("reason")),
                "risk_level": row.get("risk_level"),
                "status": status,
                "proposed_by": row.get("proposed_by"),
                "proposed_at": row.get("proposed_at"),
                "expires_at": row.get("expires_at"),
                "approval_id": row.get("approval_id"),
                "approved_by": row.get("approved_by"),
                "approved_at": row.get("approved_at"),
                "decision_note": _clean_optional(row.get("decision_note")),
                "execution_id": row.get("execution_id"),
                "started_at": row.get("started_at"),
                "finished_at": row.get("finished_at"),
                "decision_event_id": row.get("decision_event_id"),
                "started_event_id": row.get("started_event_id"),
                "finished_event_id": row.get("finished_event_id"),
                "artifact_ids": [str(item) for item in (artifact_ids or [])],
                "output_artifact_id": row.get("output_artifact_id"),
                "output_sha256": row.get("output_sha256"),
                "output_size": row.get("output_size"),
                "output_summary": _clean_optional(row.get("output_summary")),
                "error": _clean_optional(row.get("error")),
            }
        )
    return snapshot


def tool_proposal_statistics(
    tool_proposals: Iterable[object] | None,
) -> dict[str, Any]:
    """Count every tool lifecycle state from the same proposal snapshot."""

    snapshot = tool_proposal_snapshot(tool_proposals)
    status_counts = {status: 0 for status in _TOOL_STATUS_ORDER}
    for item in snapshot:
        status = str(item["status"])
        status_counts[status] = status_counts.get(status, 0) + 1
    executions = [
        item
        for item in snapshot
        if item["status"] in _EXECUTION_STATUSES or item["execution_id"]
    ]
    failures = [
        item for item in snapshot if item["status"] in _FAILURE_STATUSES
    ]
    approved = [item for item in snapshot if item["approval_id"]]
    output_artifact_ids = {
        str(item["output_artifact_id"])
        for item in executions
        if item.get("output_artifact_id")
    }
    output_sha256s = {
        str(item["output_sha256"])
        for item in executions
        if item.get("output_sha256")
    }
    return {
        "proposal_count": len(snapshot),
        "approved_count": len(approved),
        "execution_count": len(executions),
        # Separate executions from content-addressed output artifacts: several
        # executions may legitimately share one byte-identical artifact.
        "unique_output_artifact_count": len(output_artifact_ids),
        "unique_output_sha256_count": len(output_sha256s),
        "failure_count": len(failures),
        "running_count": status_counts.get("running", 0),
        "pending_count": status_counts.get("pending", 0),
        "status_counts": status_counts,
    }


def flag_confirmation_records(
    events: Iterable[Event] | None,
) -> list[dict[str, Any]]:
    """Describe human Flag confirmations as digests only, never a verification.

    ``platform_verified`` is forced to ``False``: a manual confirmation event
    says the player typed a Flag, not that the platform accepted it.
    """

    records: list[dict[str, Any]] = []
    for event in events or []:
        if event.event_type != "flag_confirmed":
            continue
        payload = event.payload or {}
        digest = str(payload.get("flag_sha256") or "")
        prefix = digest[:16] + ("…" if len(digest) > 16 else "")
        records.append(
            {
                "event_id": event.event_id,
                "occurred_at": event.occurred_at,
                "confirmed_by": _clean_text(
                    payload.get("confirmed_by") or "local-user"
                ),
                "flag_sha256": digest,
                "flag_sha256_prefix": prefix,
                "flag_length": payload.get("flag_length"),
                "platform_verified": False,
                "source": payload.get("source") or "manual_user_confirmation",
                "note": _clean_optional(payload.get("note")),
            }
        )
    return records


def disclosure_requirements(
    calls: Iterable[dict] | None,
    tool_proposals: Iterable[object] | None,
    integrity: dict,
) -> tuple[list[str], list[str]]:
    """Missing-requirement codes/warnings derived from the disclosure snapshot.

    Audit states that merely lack a recorded outcome are reported as
    ``incomplete`` instead of being silently treated as a failure.
    """

    missing: list[str] = []
    warnings: list[str] = []
    challenge_calls, _synthetic = split_model_calls(calls)
    if calls is None:
        missing.append("model_audit_incomplete")
        warnings.append("模型调用审计快照不可用，无法确认模型参与范围")
    else:
        if any(
            call.get("response_status") == "unknown" or not call.get("event_id")
            for call in challenge_calls
        ):
            missing.append("model_audit_incomplete")
            warnings.append("模型审计存在未终结调用或缺少题目事件关联")
        if any(
            call.get("response_status") == "success"
            and call.get("delivery_status") == "not_recorded"
            for call in challenge_calls
        ):
            missing.append("model_response_unrecorded")
            warnings.append("模型已响应，但题目事件中没有关联的回答记录")
    snapshot = tool_proposal_snapshot(tool_proposals)
    running = [item for item in snapshot if item["status"] == "running"]
    if running:
        missing.append("tool_execution_running")
        warnings.append(
            "存在仍在运行中的工具执行：" + "、".join(
                str(item["proposal_id"]) for item in running
            )
        )
    missing_output = [
        item
        for item in snapshot
        if item["status"] == "succeeded" and not item["output_artifact_id"]
    ]
    if missing_output:
        missing.append("tool_output_missing")
        warnings.append(
            "成功工具执行缺少输出 Artifact："
            + "、".join(str(item["proposal_id"]) for item in missing_output)
        )
    if not integrity.get("valid"):
        if "integrity" not in missing:
            missing.append("integrity")
    return missing, warnings


def flag_disclosure_lines(events: Iterable[Event] | None) -> list[str]:
    """Markdown lines describing manual Flag confirmations (digest only)."""

    records = flag_confirmation_records(events)
    if not records:
        return []
    lines = [
        "### 人工 Flag 确认（仅摘要，非平台验证）",
        "",
        "- 以下条目来自人工确认事件；不包含 Flag 明文，也不代表平台验证成功。",
    ]
    for record in records:
        length = (
            record["flag_length"]
            if record["flag_length"] is not None
            else "未记录"
        )
        lines.append(
            "- 人工确认 Flag："
            f"{record['confirmed_by']} 于 {record['occurred_at']} 确认"
            f"（SHA-256 前缀 {record['flag_sha256_prefix']}，长度 {length}；"
            f"来源 {record['source']}；platform_verified=false）"
        )
    lines.append("- 平台验证仍需平台验证截图证据；人工确认不等于平台验证成功。")
    return lines


def tool_disclosure_lines(tool_proposals: Iterable[object] | None) -> list[str]:
    """Markdown lines disclosing every tool proposal and execution state."""

    snapshot = tool_proposal_snapshot(tool_proposals)
    statistics = tool_proposal_statistics(snapshot)
    status_counts = statistics["status_counts"]
    status_text = "，".join(
        f"{_TOOL_STATUS_LABELS[status]} {status_counts.get(status, 0)}"
        for status in _TOOL_STATUS_ORDER
    )
    lines = [
        "### 本地工具申请与执行披露",
        "",
        f"- 工具申请统计：共 {statistics['proposal_count']} 条"
        f"（当前状态：{status_text}）",
        f"- 人工批准：{statistics['approved_count']} 条；"
        f"已开始执行：{statistics['execution_count']} 次；"
        f"唯一输出 Artifact：{statistics['unique_output_artifact_count']} 个；"
        f"失败/超时：{statistics['failure_count']} 次。",
        "- 工具结果由固定只读工具在人工逐次批准后执行；工具输出不等同于模型推断。",
    ]
    if not snapshot:
        lines.append("- 本题记录中没有本地工具申请或执行。")
        return lines
    for item in snapshot:
        arguments = json.dumps(
            item["arguments"], ensure_ascii=False, sort_keys=True
        )
        parts = [
            f"申请 {item['proposal_id'] or '未记录'}",
            f"工具 {item['tool_name'] or '未记录'}",
            f"参数 {arguments}",
            f"状态 {item['status']}"
            f"（{_TOOL_STATUS_LABELS.get(str(item['status']), '未知')}）",
            f"风险 {item['risk_level'] or '未记录'}",
            f"申请人 {item['proposed_by'] or '未记录'}",
            f"申请时间 {item['proposed_at'] or '未记录'}",
            f"过期时间 {item['expires_at'] or '未记录'}",
            f"模型调用 {item['model_call_id'] or '未关联'}",
            f"批准 {item['approval_id'] or '无'}",
        ]
        if item["approved_by"]:
            parts.append(f"批准人 {item['approved_by']}")
        if item["approved_at"]:
            parts.append(f"批准时间 {item['approved_at']}")
        if item["decision_note"]:
            parts.append(f"决定备注 {item['decision_note']}")
        parts.append(f"执行 {item['execution_id'] or '无'}")
        if item["started_at"]:
            parts.append(f"开始时间 {item['started_at']}")
        if item["finished_at"]:
            parts.append(f"结束时间 {item['finished_at']}")
        events = [
            f"决定事件 {item['decision_event_id']}"
            if item["decision_event_id"]
            else None,
            f"开始事件 {item['started_event_id']}"
            if item["started_event_id"]
            else None,
            f"结束事件 {item['finished_event_id']}"
            if item["finished_event_id"]
            else None,
        ]
        event_text = "；".join(part for part in events if part)
        if event_text:
            parts.append(event_text)
        if item["output_artifact_id"]:
            parts.append(f"输出 Artifact {item['output_artifact_id']}")
        if item["output_sha256"]:
            parts.append(f"output_sha256 {item['output_sha256']}")
        if item["output_size"] is not None:
            parts.append(f"输出大小 {item['output_size']} 字节")
        if item["output_summary"]:
            parts.append(f"输出摘要 {item['output_summary']}")
        if item["error"]:
            parts.append(f"错误 {item['error']}")
        lines.append("- " + "；".join(parts) + "。")
    return lines


def traceability_snapshot(
    challenge: Challenge,
    calls: Iterable[dict] | None,
    tool_proposals: Iterable[object] | None,
) -> dict[str, Any]:
    """Describe the call -> proposal -> approval -> execution -> artifact chain."""

    challenge_calls, synthetic_calls = split_model_calls(calls)
    snapshot = tool_proposal_snapshot(tool_proposals)
    chains: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for item in snapshot:
        status = str(item["status"])
        if status in {"pending", "approved", "running"}:
            chain_complete = False
        elif status in {"rejected", "cancelled", "expired"}:
            chain_complete = bool(item["approval_id"] or item["decision_event_id"])
        elif status == "succeeded":
            chain_complete = bool(
                item["execution_id"]
                and item["finished_event_id"]
                and item["output_artifact_id"]
            )
        else:  # failed / timed_out
            chain_complete = bool(
                item["execution_id"] and item["finished_event_id"]
            )
        chain = {
            "proposal_id": item["proposal_id"],
            "model_call_id": item["model_call_id"],
            "approval_id": item["approval_id"],
            "execution_id": item["execution_id"],
            "started_event_id": item["started_event_id"],
            "finished_event_id": item["finished_event_id"],
            "output_artifact_id": item["output_artifact_id"],
            "output_sha256": item["output_sha256"],
            "status": status,
            "complete": chain_complete,
        }
        chains.append(chain)
        if not chain_complete:
            unresolved.append(
                f"proposal {item['proposal_id']} ({status}) 的追踪链未闭合"
            )
    call_links = [
        {
            "call_id": call.get("call_id"),
            "event_id": call.get("event_id"),
            "response_status": call.get("response_status"),
            "delivery_status": call.get("delivery_status"),
        }
        for call in challenge_calls
    ]
    return {
        "challenge_id": challenge.challenge_id,
        "model_call_ids": [
            str(call.get("call_id"))
            for call in challenge_calls
            if call.get("call_id")
        ],
        "synthetic_call_ids": [
            str(call.get("call_id"))
            for call in synthetic_calls
            if call.get("call_id")
        ],
        "tool_proposal_ids": [
            str(item["proposal_id"])
            for item in snapshot
            if item["proposal_id"]
        ],
        "model_call_links": call_links,
        "chains": chains,
        "unresolved": unresolved,
    }


def build_writeup_preview(
    challenge: Challenge,
    events: list[Event],
    artifacts: list[ArtifactView],
    project: Project | None,
    read_verified: Callable[[str], bytes],
    integrity: dict,
    calls: list[dict] | None = None,
    tool_proposals: list[object] | None = None,
) -> WriteupPreview:
    """Build the deterministic generated Writeup plus disclosure counters.

    ``calls`` must be the merged ModelCallJournal snapshot for this challenge
    (``delivery_status`` included); it is never reconstructed from events.
    ``tool_proposals`` must be the same ``tool_proposals`` snapshot used by the
    export, so all disclosed counts agree.
    """

    challenge_calls, synthetic_calls = split_model_calls(calls)
    call_stats = model_call_statistics(calls)
    proposal_snapshot = tool_proposal_snapshot(tool_proposals)
    tool_stats = tool_proposal_statistics(proposal_snapshot)
    flag_records = flag_confirmation_records(events)
    notes = [event for event in events if event.event_type == "note"]
    approach_notes = [
        event for event in notes if event.payload.get("kind") == "approach"
    ]
    ordinary_notes = [
        event for event in notes if event.payload.get("kind") != "approach"
    ]
    manual_ops = [
        event for event in events if event.event_type == "manual_operation_recorded"
    ]
    imports = [event for event in events if event.event_type == "challenge_imported"]
    by_kind: dict[str, list[ArtifactView]] = {}
    for artifact in artifacts:
        by_kind.setdefault(_kind(artifact), []).append(artifact)

    code_artifacts = [
        artifact
        for artifact in artifacts
        if _kind(artifact) in {"source_code", "analysis"}
        and _is_text_artifact(artifact)
    ]
    execution_artifacts = by_kind.get("execution", []) + by_kind.get(
        "execution_output", []
    )

    complete_integrity = bool(integrity.get("valid"))
    synthetic = is_synthetic_connectivity(challenge)
    requirements = _requirement_list(
        synthetic=synthetic,
        approaches=approach_notes,
        manual_ops=manual_ops,
        code_artifacts=code_artifacts,
        execution_artifacts=execution_artifacts,
        flag_artifacts=by_kind.get("flag_capture", []),
        platform_artifacts=by_kind.get("platform_verification", []),
        ai_usage_level=challenge.ai_usage_level,
        integrity_valid=complete_integrity,
    )
    disclosure_missing, disclosure_warnings = disclosure_requirements(
        calls, proposal_snapshot, integrity
    )
    for code in disclosure_missing:
        if any(row["code"] == code for row in requirements):
            continue
        requirements.append(
            {
                "code": code,
                "label": _MISSING_LABELS.get(code, code),
                "status": "missing",
                "reason": "必需审计关联证据尚未满足。",
                "evidence": [],
                "remediation": _REMEDIATION.get(code),
            }
        )
    missing = [row["code"] for row in requirements if row["status"] == "missing"]
    not_applicable = [
        row["code"] for row in requirements if row["status"] == "not_applicable"
    ]

    warnings: list[str] = []
    if challenge.ai_usage_level == "unknown":
        warnings.append("AI 使用等级尚未确认，无法界定 AI 参与范围")
    if not complete_integrity:
        warnings.append(
            "事件哈希链校验失败，档案不可作为可信证据：最早受影响 sequence "
            f"{integrity.get('earliest_affected_sequence')}"
        )
    warnings.extend(
        warning
        for warning in disclosure_warnings
        if warning not in warnings
    )
    if any(artifact.capture_time_claim for artifact in artifacts) or any(
        event.payload.get("started_at_claim") or event.payload.get("finished_at_claim")
        for event in manual_ops
    ):
        warnings.append(
            "档案包含用户声明的参与时间（capture_time_claim / *_at_claim），"
            "这些是申报值，不是服务器可信时间"
        )
    warnings.extend(
        "导入警告：" + warning
        for event in imports
        for warning in event.payload.get("warnings", [])
    )

    # Read the candidate code evidence once so an unreadable artifact is also
    # reported as missing core code rather than only rendered as a gap marker.
    code_contents: dict[str, bytes] = {}
    for artifact in code_artifacts:
        try:
            code_contents[artifact.artifact_id] = read_verified(artifact.sha256)
        except Exception:
            continue
    if not code_contents and not synthetic and "core_code" not in missing:
        for row in requirements:
            if row["code"] == "core_code":
                row["status"] = "missing"
                row["reason"] = "核心代码 Artifact 存在，但无法通过完整性校验读取。"
                row["remediation"] = _REMEDIATION["core_code"]
                break
        missing.append("core_code")

    lines: list[str] = []
    lines.append(f"# {challenge.name} — Writeup 初稿")
    lines.append("")
    lines.append(
        "> 本文件由 CTF Workbench 依据已记录事件与证据自动生成初稿。"
        "标记为「证据缺失/待补充」的内容必须由选手补充后才构成完整档案；"
        "AI 建议不等同于人工执行事实。"
    )
    lines.append("")
    completeness = "complete" if not missing else "incomplete"
    lines.append(f"**档案完整性：{completeness}**")
    if warnings:
        lines.append("")
        lines.append("**警告**")
        for warning in warnings:
            lines.append(f"- {warning}")
    lines.append("")

    lines.append("## 1. 题目基本信息")
    lines.append("")
    lines.append("| 字段 | 值 |")
    lines.append("|---|---|")
    rows = [
        ("题目名称", challenge.name),
        ("分类", challenge.category),
        ("分值", challenge.score if challenge.score is not None else "未填写"),
        ("来源", challenge.source),
        ("比赛项目", challenge.competition_name or "未填写"),
        ("AI 使用等级", challenge.ai_usage_level),
        ("解题状态", challenge.solve_status),
        ("Writeup 状态", challenge.writeup_status),
        (
            "项目",
            project.project_name if project is not None else "未创建项目",
        ),
        ("Challenge ID", challenge.challenge_id),
        ("创建时间（服务器）", challenge.created_at),
    ]
    for label, value in rows:
        lines.append(f"| {label} | {_escape_cell(value)} |")
    lines.append("")

    lines.append("## 2. 解题思路")
    lines.append("")
    if approach_notes:
        for event in approach_notes:
            retrospective = "（回溯笔记）" if event.payload.get("retrospective") else ""
            lines.append(
                f"- {event.payload.get('text', '')} "
                f"[事件 {event.event_id} / #{event.sequence} / {event.occurred_at}]{retrospective}"
            )
    else:
        lines.append(MISSING_APPROACH)
        if ordinary_notes:
            lines.append("")
            lines.append(
                "> 已记录的普通笔记不会自动认定为「核心解题思路」；请明确标记并补充解题思路。"
            )
    lines.append("")

    lines.append("## 3. 关键操作")
    lines.append("")
    lines.append(
        "> 本轮为人工执行模式：以下操作由选手在工作台之外手动执行后在本地补录，"
        "记录为人工申报（execution_mode=manual_external, execution_verified=false），"
        "不是工作台自动执行或已验证执行。"
    )
    lines.append("")
    if ordinary_notes:
        lines.append("### 其他人工笔记（普通笔记，非核心解题思路）")
        lines.append("")
        for event in ordinary_notes:
            retrospective = "（回溯笔记）" if event.payload.get("retrospective") else ""
            lines.append(
                f"- {event.payload.get('text', '')} "
                f"[事件 {event.event_id} / #{event.sequence} / {event.occurred_at}]{retrospective}"
            )
        lines.append("")
    if manual_ops:
        for event in manual_ops:
            payload = event.payload
            lines.append(f"### 操作 #{event.sequence}（事件 {event.event_id}）")
            lines.append("")
            lines.append(f"- 时间（服务器记录）：{event.occurred_at}")
            if payload.get("started_at_claim"):
                lines.append(f"- 开始时间（用户申报）：{payload['started_at_claim']}")
            if payload.get("finished_at_claim"):
                lines.append(f"- 结束时间（用户申报）：{payload['finished_at_claim']}")
            lines.append(f"- 执行目的：{payload.get('purpose', '')}")
            lines.append(f"- 工作目录：`{payload.get('working_directory', '')}`")
            lines.append("- 实际执行命令：")
            lines.append("")
            lines.append(_render_code(str(payload.get("command", "")), "text"))
            lines.append("")
            lines.append(f"- 退出码：{payload.get('exit_code', '未填写')}")
            lines.append(f"- 运行结果说明：{payload.get('result_note', '')}")
            lines.append(
                "- 执行属性：execution_mode=manual_external, execution_verified=false"
            )
            lines.append("")
    else:
        lines.append(MISSING_MANUAL_OPERATION)
        lines.append("")
    for event in imports:
        payload = event.payload
        lines.append(
            f"- 导入题目附件 ZIP：{payload.get('original_filename', '')}，"
            f"{payload.get('extracted_file_count', 0)} 个文件，"
            f"{payload.get('total_uncompressed_size', 0)} 字节"
            f"（事件 {event.event_id} / #{event.sequence}）"
        )
    lines.append("")

    lines.append("## 4. 核心代码")
    lines.append("")
    rendered = 0
    total_bytes = 0
    for artifact in code_artifacts:
        if rendered >= _MAX_CODE_FILES or total_bytes >= _MAX_CODE_BYTES_TOTAL:
            lines.append("（核心代码数量超过初稿展示上限，完整文件见导出证据档案。）")
            break
        content = code_contents.get(artifact.artifact_id)
        if content is None:
            lines.append(
                f"- {artifact.original_filename}：无法读取（证据完整性校验失败）"
            )
            continue
        subset = content[:_MAX_CODE_BYTES_PER_FILE]
        total_bytes += len(subset)
        rendered += 1
        text = subset.decode("utf-8", errors="replace")
        suffix = Path(artifact.original_filename).suffix.lstrip(".").casefold()
        lines.append(
            f"### {artifact.original_filename}（证据 {artifact.artifact_id}，"
            f"SHA256 {artifact.sha256}）"
        )
        lines.append("")
        lines.append(_render_code(text, suffix if suffix.isalnum() else "text"))
        lines.append("")
    if rendered == 0:
        lines.append(NOT_APPLICABLE_CODE if synthetic else MISSING_CODE)
        lines.append("")

    lines.append("## 5. 运行结果")
    lines.append("")
    if manual_ops:
        for event in manual_ops:
            payload = event.payload
            lines.append(
                f"- 人工运行 #{event.sequence}：退出码 {payload.get('exit_code', '未填写')}；"
                f"{payload.get('result_note', '')}"
            )
    for artifact in execution_artifacts:
        lines.append(
            f"- 执行证据：{artifact.original_filename}"
            f"（{artifact.evidence_kind}，SHA256 {artifact.sha256}，"
            f"事件 {artifact.source_event_id}）"
        )
    if not manual_ops and not execution_artifacts:
        lines.append(MISSING_EXECUTION_EVIDENCE)
    elif not execution_artifacts:
        lines.append("")
        lines.append(MISSING_EXECUTION_EVIDENCE)
    lines.append("")

    lines.append("## 6. Flag 获取过程")
    lines.append("")
    flags = by_kind.get("flag_capture", [])
    if flags:
        for artifact in flags:
            claim = (
                f"，用户申报拍摄时间 {artifact.capture_time_claim}"
                if artifact.capture_time_claim
                else ""
            )
            lines.append(
                f"- Flag 获取即时截图：{artifact.original_filename}"
                f"（SHA256 {artifact.sha256}，服务器接收时间 {artifact.ingested_at}"
                f"{claim}，事件 {artifact.source_event_id}）"
            )
    else:
        lines.append(NOT_APPLICABLE_FLAG if synthetic else MISSING_FLAG_CAPTURE)
    if flag_records:
        lines.append("")
        lines.extend(flag_disclosure_lines(events))
    lines.append("")

    lines.append("## 7. 平台验证")
    lines.append("")
    verification = by_kind.get("platform_verification", [])
    if verification:
        for artifact in verification:
            lines.append(
                f"- 平台验证截图：{artifact.original_filename}"
                f"（SHA256 {artifact.sha256}，服务器接收时间 {artifact.ingested_at}，"
                f"事件 {artifact.source_event_id}）"
            )
    else:
        lines.append(MISSING_PLATFORM_VERIFICATION)
    lines.append("")

    lines.append("## 8. AI 使用说明")
    lines.append("")
    lines.extend(disclosure_lines(challenge_calls))
    lines.append(
        "- 模型调用统计（与导出 manifest 一致）：本题模型调用 "
        f"{call_stats['call_count']} 次（成功 {call_stats['successful']}，"
        f"失败 {call_stats['failed']}，取消 {call_stats['cancelled']}，"
        f"未确定 {call_stats['unknown']}）；回答未入事件 "
        f"{call_stats['delivery_not_recorded']} 次；合成连通性测试调用 "
        f"{call_stats['synthetic_call_count']} 次单独统计，不包含题目数据。"
    )
    if synthetic_calls:
        lines.append(
            "- 合成连通性测试调用不携带任何题目数据，单独计 "
            f"{len(synthetic_calls)} 次，不计入本题模型调用。"
        )
    lines.append("- 本工作台未启用自动工具执行或自动 Flag 提交。人工运行记录单独列出。")
    lines.append(
        "- AI 分析建议（如有）仅作为参考，不得作为已执行操作或已验证结果的证据。"
    )
    lines.append("")
    lines.extend(tool_disclosure_lines(proposal_snapshot))
    lines.append("")
    lines.append(f"- 题目 AI 使用等级：{challenge.ai_usage_level}")
    if challenge.ai_usage_level == "unknown":
        lines.append(f"- {MISSING_AI_LEVEL}")
    if project is not None and project.ai_policy_summary:
        lines.append(f"- 比赛规则中记录的 AI 使用限制：{project.ai_policy_summary}")
    else:
        lines.append("- 比赛规则中记录的 AI 使用限制：未填写")
    if project is not None and project.rules_sha256:
        lines.append(
            f"- 比赛规则文件：{project.rules_filename}（SHA256 {project.rules_sha256}）"
        )
    lines.append("")

    lines.append("## 9. 证据清单")
    lines.append("")
    if artifacts:
        lines.append(
            "| 文件 | 证据类型 | 大小 | SHA256 | 上传时间（服务器） | 来源事件 |"
        )
        lines.append("|---|---|---|---|---|---|")
        for artifact in artifacts:
            lines.append(
                f"| {_escape_cell(artifact.original_filename)} "
                f"| {artifact.evidence_kind} | {artifact.size} "
                f"| {artifact.sha256} | {artifact.ingested_at} "
                f"| {artifact.source_event_id} |"
            )
    else:
        lines.append("尚无证据文件。")
    lines.append("")
    lines.append("### 完整性判定矩阵")
    lines.append("")
    lines.append("| 项目 | 状态 | 依据/缺项说明 | 补充方式 |")
    lines.append("|---|---|---|---|")
    for row in requirements:
        lines.append(
            f"| {row['code']} | {row['status']} | "
            f"{_escape_cell(row['reason'])} | "
            f"{_escape_cell(row['remediation'] or '')} |"
        )
    lines.append("")
    if missing:
        lines.append("### 缺失/未确认项")
        lines.append("")
        for code in missing:
            label = _MISSING_LABELS.get(code, "其他缺失证据")
            lines.append(
                f"- {code}：{label}；补充方式：{_REMEDIATION.get(code, '待人工说明')}"
            )
        lines.append("")

    lines.append("### 事件时间线摘要")
    lines.append("")
    if events:
        lines.append("| sequence | 时间（服务器） | 来源 | 类型 | 关联证据 |")
        lines.append("|---|---|---|---|---|")
        for event in events:
            lines.append(
                f"| {event.sequence} | {event.occurred_at} | {event.actor} "
                f"| {event.event_type} "
                f"| {', '.join(event.artifact_ids) or '无'} |"
            )
    else:
        lines.append("尚无事件。")
    lines.append("")

    markdown = "\n".join(lines).rstrip() + "\n"
    return WriteupPreview(
        markdown=markdown,
        missing_requirements=missing,
        requirements=requirements,
        not_applicable_requirements=not_applicable,
        event_count=len(events),
        artifact_count=len(artifacts),
        completeness=completeness,
        warnings=warnings,
        model_call_count=call_stats["call_count"],
        tool_proposal_count=tool_stats["proposal_count"],
        tool_execution_count=tool_stats["execution_count"],
        unique_tool_output_artifact_count=tool_stats["unique_output_artifact_count"],
        tool_failure_count=tool_stats["failure_count"],
    )
