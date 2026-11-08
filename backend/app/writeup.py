"""Deterministic Writeup draft generated only from recorded evidence.

The generator consumes challenge metadata, the ordered event log, artifacts and
the project rules configuration.  It never invents commands, screenshots, a
flag or a verification result: missing evidence is rendered with an explicit
marker and makes the dossier incomplete.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .models import ArtifactView, Challenge, Event, Project, WriteupPreview

MISSING_APPROACH = "[待选手补充：核心解题思路]"
MISSING_FLAG_CAPTURE = "[证据缺失：Flag 获取即时截图尚未提供]"
MISSING_PLATFORM_VERIFICATION = "[证据缺失：平台验证截图尚未提供]"
MISSING_MANUAL_OPERATION = "[证据缺失：尚无人工运行记录]"
MISSING_AI_LEVEL = "[待确认：AI 使用等级尚未确认]"
MISSING_CODE = "[证据缺失：尚未上传核心代码或脚本]"
MISSING_EXECUTION_EVIDENCE = "[证据缺失：尚无运行截图或执行输出证据]"

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


def build_writeup_preview(
    challenge: Challenge,
    events: list[Event],
    artifacts: list[ArtifactView],
    project: Project | None,
    artifact_reader: Callable[[str], bytes],
    integrity: dict,
) -> WriteupPreview:
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
    missing: list[str] = []
    if not approach_notes:
        missing.append("core_approach")
    if not manual_ops:
        missing.append("manual_operation")
    if not code_artifacts:
        missing.append("core_code")
    if not execution_artifacts:
        missing.append("execution_evidence")
    if not by_kind.get("flag_capture"):
        missing.append("flag_capture")
    if not by_kind.get("platform_verification"):
        missing.append("platform_verification")
    if challenge.ai_usage_level == "unknown":
        missing.append("ai_usage_level")
    if not complete_integrity:
        missing.append("integrity")

    warnings: list[str] = []
    if challenge.ai_usage_level == "unknown":
        warnings.append("AI 使用等级尚未确认，无法界定 AI 参与范围")
    if not complete_integrity:
        warnings.append(
            "事件哈希链校验失败，档案不可作为可信证据：最早受影响 sequence "
            f"{integrity.get('earliest_affected_sequence')}"
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
            code_contents[artifact.artifact_id] = artifact_reader(artifact.sha256)
        except Exception:
            continue
    if not code_contents and "core_code" not in missing:
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
        lines.append(MISSING_CODE)
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
        lines.append(MISSING_FLAG_CAPTURE)
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
    lines.append(
        "- 本工作台未启用自动工具执行、模型联网调用或自动 Flag 提交；"
        "本轮所有运行由选手在本地手动完成。"
    )
    lines.append(
        "- AI 分析建议（如有）仅作为参考，不得作为已执行操作或已验证结果的证据。"
    )
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
    if missing:
        lines.append("### 缺失/未确认项")
        lines.append("")
        for code in missing:
            label = dict(_REQUIRED_EVIDENCE).get(code, "事件哈希链完整性")
            lines.append(f"- {code}：{label}")
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
        event_count=len(events),
        artifact_count=len(artifacts),
        completeness=completeness,
        warnings=warnings,
    )
