# MVP 后端测试报告 — 2026-11-08

环境（本地）：Windows PowerShell；Python 3.14.7；FastAPI 0.142.2；pytest 9.1.1；ruff 0.14.10。
CI 环境：GitHub Actions `P0 checks`（Ubuntu latest，Python 3.11，Node 22）。

## 本地结果

| 检查 | 命令 | 结果 |
|---|---|---|
| 全仓测试 | `cd backend; python -m pytest -q` | **199 passed, 3 skipped, 0 failed**（24.30s） |
| 人工稿持久化 + 最终 ZIP | `python -m pytest -q tests/test_mvp_writeup_persistence.py` | **23 passed, 0 failed** |
| MVP 导入/证据/人工操作 | `python -m pytest -q tests/test_mvp_imports.py` | **50 passed, 0 failed** |
| MVP Writeup/导出 | `python -m pytest -q tests/test_mvp_writeup_export.py` | **24 passed, 0 failed** |
| PR #7 审查修复回归 | `python -m pytest -q tests/test_mvp_review_fixes.py` | **27 passed, 0 failed** |
| 既有 P1 回归 | `python -m pytest -q tests/test_artifacts.py tests/test_core.py` | 通过（仅平台性 skip） |
| Ruff lint | `python -m ruff check app tests` | **All checks passed** |
| Ruff format | `python -m ruff format --check app tests` | **all formatted** |

跳过项（如实说明，不计作通过）：

1. `test_artifacts.py::test_symbolic_link_escape_rejected`：Windows 无创建符号链接权限（POSIX CI 会真实执行；Windows 另有 junction 用例覆盖）。
2. `test_core.py` 符号链接用例：同上，Windows 权限限制。
3. `test_providers.py`：真实 Provider 联网测试需显式 opt-in 与合法凭证（按设计禁用）。

## PR #7 独立审查修复回归（test_mvp_review_fixes.py，24 函数 / 27 用例）

| 修复项 | 回归覆盖 |
|---|---|
| P1-1 导入文件读取完整性 | 正常读取 200 + `X-Imported-File-Integrity: sha256-verified`；同大小篡改 / 截断 / 替换为更大文件 → 409 且不返回篡改字节；未篡改兄弟文件仍 200；Manifest 不可信时拒绝返回内容 |
| P1-2 Manifest 与事件绑定 | 正常 `manifest_verified=true`；自身摘要被改、重算摘要自洽但事件摘要不符、删除 manifest、challenge_id/original_artifact_id/import_id 与事件不符、事件链被篡改 → 列表显式 unverified / detail+file 409 / 导出该导入 unverified 且不导出文件、整体 incomplete |
| P1-3 导出全部导入 | 两个 ZIP 连续导入：两份 original.zip + extracted 全部导出；逐文件 sha256/字节校验；`counts.imports=2` 与逐项 status/exported_file_count/missing_files/error；SHA256SUMS 全覆盖；篡改/缺失任一次导入文件 → 该项 incomplete、另一项 exported、整体 incomplete |
| P2-1 Writeup 完整性 | 普通笔记（缺省/note）不满足 core_approach，仅在「其他人工笔记」展示；显式 `kind="approach"` 才满足；无 source_code/analysis → core_code 缺失并显示中文标记；仅有补录记录不满足 execution_evidence；真实 execution 证据满足；完整组合 complete；不伪造 Flag/自动执行声明 |

## 人工稿持久化与最终 ZIP（test_mvp_writeup_persistence.py，23 函数）

| 范围 | 覆盖 |
|---|---|
| 创建/读取 | PUT base=0 → 201 v1；GET 内容/版本/SHA/size/saved_at 一致；sidecar 结构；无 `.tmp` 残留 |
| 持久化/版本 | 新 app 同 data_root 恢复；v1→v2 更新；仅保留最新版本 |
| 并发 | 同 base 并发创建恰好一个 201、一个 409；失败请求不破坏 sidecar |
| 冲突 | 旧 base 覆盖 → 409 + current 最新稿；无稿时 base>0 → 409 current=null |
| 校验 | 空/空白 422；64B 边界接受、65B/UTF-8 多字节超限 413；默认 1 MiB 与边界；base_version 严格类型/额外字段 422 |
| 篡改 | sidecar content 或 JSON 被改 → GET 409 且不回传内容；导出 fallback 初稿、incomplete、无篡改内容 |
| 最终 ZIP | writeup.md 逐字节人工稿；writeup_generated.md == preview；manifest final_source/version/sha/size 正确；无人工稿初稿提示；SHA256SUMS 全量覆盖并逐文件复算 |
| 兼容/安全 | 历史无稿 GET 404 + 导出 fallback；保存不产生事件、事件链不变；Content-Length 预检 413、chunked 超限 413；未知 cid 404 |

真实 HTTP 验收（独立 uvicorn + 30 条请求）：创建/更新/恢复/冲突/空稿/超长/严格类型/最终 ZIP/tamper fallback 全部通过，详见 `docs/MVP_WRITEUP_ACCEPTANCE.md`。

## B9 必需测试覆盖映射

| B9 要求 | 测试（文件::函数） |
|---|---|
| 正常 ZIP 导入 | test_mvp_imports.py::test_import_records_manifest_and_extracted_files / test_import_saves_original_artifact_and_event |
| ZIP Slip | ::test_import_rejects_zip_slip |
| Windows 绝对路径 | ::test_import_rejects_absolute_path / ::test_import_rejects_windows_drive_path |
| 符号链接 | ::test_import_rejects_symlink_entry |
| 重复路径 | ::test_import_rejects_duplicate_path |
| 大小写冲突 | ::test_import_rejects_case_insensitive_conflict |
| ZIP 炸弹预算 | ::test_import_rejects_compression_ratio_bomb |
| 文件数量超限 | ::test_import_rejects_file_count_over_limit |
| 嵌套 ZIP 不自动解压 | ::test_import_does_not_extract_nested_archive |
| 导入失败无部分目录残留 | ::test_import_failure_leaves_no_partial_directory（各安全用例中断言） |
| 原始 ZIP Artifact 可下载 | ::test_import_saves_original_artifact_and_event |
| 证据分类持久化 | test_mvp_imports.py::test_artifact_evidence_kind_and_capture_time / test_artifact_evidence_defaults_for_legacy_payload |
| 人工操作不能伪装成 tool execution | ::test_manual_operation_recorded_event / ::test_manual_operation_rejects_client_system_fields（6 参数） |
| 历史 Challenge 兼容 | ::test_challenge_historical_json_gets_defaults |
| Writeup 缺失项准确显示 | test_mvp_writeup_export.py::test_writeup_preview_empty_challenge_marks_all_missing / ::test_writeup_preview_reports_precise_missing_requirements |
| ZIP 导出内容与原始 Artifact 哈希一致 | ::test_export_bytes_match_uploaded_synthetic_evidence |
| SHA256SUMS 校验成功 | ::test_export_sha256sums_verifies_every_delivered_file |
| 其他（安全预算/项目规则/只读导出/重启/端到端/审查修复回归/人工稿持久化） | 见四个 MVP 测试文件的函数清单 |

## 覆盖要点（非穷尽）

- 项目：创建/更新/读取、创建缺名 422、规则上传/下载/去重/大小限制/未配置 409/篡改 409、文件名穿越仅展示。
- Challenge：AI 等级 A0/A1/A2/unknown、score、competition_name 继承项目、非法值 422、历史 JSON 默认兼容。
- ZIP：非 ZIP/空文件、SIZE 上限 413、文件数/单文件/总大小/压缩比、重复与大小写冲突、符号链接/特殊文件、加密 ZIP、Windows 盘符/绝对路径穿越、嵌套不解压、中文空格文件名、失败无残留、重启后可读。
- 证据：evidence_kind 合法/非法、capture_time_claim 与 ingested_at 区分、`artifact_added` payload 扩展、ArtifactView 默认值兼容旧 payload。
- 人工记录：固定 `execution_mode=manual_external`、`execution_verified=false`、`actor=user`、拒绝客户端系统字段、时间声明校验、不产生 tool_* 事件。
- Writeup：空题目固定缺失标记、9 个固定章节、AI 披露、内容只来自已记录数据、事件链篡改 → incomplete + integrity 缺失、计数、重启一致性。
- 导出：目录结构、原始/解压/证据字节一致性、SHA256SUMS 逐文件复算、events 按 sequence、manifest 缺失项、不完整/完整标记、篡改证据降级 incomplete、导出只读不改事件、临时文件清理、两次导出可复现、端到端完整流程。

测试全部使用合成数据（自拼 ZIP、合成 PNG/PDF 魔数、合成文本），未使用任何真实比赛附件、Flag 或目标；每个测试 `tmp_path` 隔离数据根；未写入仓库数据目录。

## 远程 CI

PR：**#7**（Draft）https://github.com/Sunset-Sunrise-Sun/CTF/pull/7 ，目标分支 `feat/p1-2-a00-integration`。

提交 `67f236ba`（初版）、`5f343697`（审查修复）的 `P0 checks` 均已通过。本轮「人工稿持久化 + 最终 ZIP」提交的两次 `P0 checks` 运行结果待推送后回填；PR 最终 head 以 PR Checks 页面最新运行结果为准（验收时应为通过）。

## 复现

```powershell
cd backend
python -m pip install -e ".[dev]"
python -m ruff check app tests
python -m pytest -q
```
