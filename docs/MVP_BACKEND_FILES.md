# MVP 后端文件清单与变更说明

基线：`96152b7a66e16d726d50bebb4d833167b140e19c`（`feat/p1-2-a00-integration`，PR #6 head）
分支：`feat/mvp-backend-workflow`（本文件所在分支）
说明：未修改 `main`，未修改/改写 PR #6，未修改 `frontend/`，未修改既有迁移 `001_initial.sql` / `002_artifacts.sql`。

## 新增文件

| 文件 | 行数 | 说明 |
|---|---|---|
| `backend/app/project.py` | 104 | 单项目配置 JSON 原子读写、规则文件内容寻址上传/下载与 SHA-256 校验。 |
| `backend/app/imports.py` | 459 | ZIP 安全校验、预算（文件数/单文件/总解压/压缩比）、路径与符号链接防护、staging 解压与原子安装、manifest 读写与文件浏览路径解析。 |
| `backend/app/writeup.py` | 383 | 仅基于 Challenge/事件/Artifact/人工笔记/规则/AI 等级生成确定性的 Writeup 初稿；固定缺失标记与完整性判定。 |
| `backend/app/export.py` | 349 | 完整证据 ZIP 导出：证据逐个复核 SHA-256、原始/解压文件、分类证据、脚本、事件/时间线日志、Writeup、AI 披露、manifest、SHA256SUMS、不完整标记。 |
| `backend/app/schema_cli.py` | 110 | 导出 `docs/openapi.json` 与 `docs/contracts.json` 的可复现命令（`python -m app.schema_cli`）。 |
| `backend/app/writeups.py` | 新增 | 人工稿 sidecar 存储：版本比较、1 MiB UTF-8 上限、SHA/size/challenge 校验、符号链接/损坏拒绝、原子写（temp+fsync+os.replace）、进程内锁。 |
| `backend/tests/test_mvp_imports.py` | 1076 | 42 个测试函数 / 50 个用例：项目规则、Challenge 扩展兼容、ZIP 导入与 12 类安全用例、证据分类、人工操作、health/限制/重启。 |
| `backend/tests/test_mvp_writeup_export.py` | 756 | 21 个测试函数 / 24 个用例：Writeup 预览、缺失标记、AI 披露、导出结构与 SHA256SUMS、字节一致性、不完整/篡改/只读、端到端流程。 |
| `backend/tests/test_mvp_review_fixes.py` | 新增 | 24 个测试函数 / 27 个用例：PR #7 独立审查修复回归（文件读取完整性、Manifest/事件绑定、全部导入导出、Writeup approach/code/execution 完整性）。 |
| `backend/tests/test_mvp_writeup_persistence.py` | 新增 | 23 个测试函数：人工稿创建/读取/重启恢复/版本更新/并发冲突/空稿超长/严格类型/篡改 fallback/最终 ZIP 字节一致/SHA256SUMS/无事件污染/请求安全/legacy 迁移。 |
| `docs/MVP_BACKEND.md` | 151 | 后端 API 契约、数据布局、安全预算、演示步骤、已知限制。 |
| `docs/MVP_BACKEND_FILES.md` | — | 本文件。 |
| `docs/MVP_BACKEND_TEST_REPORT.md` | — | 测试、Ruff、CI 结果与 B9 覆盖映射。 |
| `docs/MVP_BACKEND_SHA256SUMS` | — | 交付文件的 SHA-256 校验和（不含自身）。 |

## 修改文件

| 文件 | 变更 |
|---|---|
| `backend/app/models.py` | `ChallengeCreate/Challenge` 增加可选 `ai_usage_level`、`score`、`competition_name`（旧 JSON 默认兼容）；`EventType` 增加 `challenge_imported`、`manual_operation_recorded`；新增 `ArtifactView`、`Project`、`ProjectUpdate`、`ManualOperationCreate`、`ImportFile`、`ImportRecord`、`ImportDetail`、`ImportResult`、`WriteupPreview`。 |
| `backend/app/store.py` | `add_artifact` 支持 `evidence_kind`/`capture_time_claim` 写入 `artifact_added` payload（默认上传保持旧 payload 形状）；`append` 支持 `artifact_ids`；新增 `artifact_views`/`artifact_view`（JOIN 来源事件，解析分类与声明时间，旧数据默认 `other`/`None`）。 |
| `backend/app/main.py` | 新增项目/规则、ZIP 导入（含 imports 列表/详情/文件浏览）、证据分类、人工操作、Writeup 预览、完整档案导出等 API；上传体积中间件覆盖规则/导入/证据上传；Challenge 继承项目比赛名；`/api/health` 增加人工执行模式与导入预算；版本号 0.2.0。 |
| `backend/tests/test_artifacts.py` | 仅更新 `ARTIFACT_FIELDS` 常量以匹配新增 ArtifactView 证据字段（4 行），不改断言语义。 |
| `README.md` | 增加 MVP 后端文档导航。 |
| `docs/openapi.json` | 由 `python -m app.schema_cli` 重新生成，含全部新接口/schema。 |
| `docs/contracts.json` | 由 `python -m app.schema_cli` 重新生成，增加 9 个新模型 schema。 |

## 未修改（边界确认）

- `frontend/`（Codex 负责）。
- `backend/app/migrations/`：无新增迁移，未占用 P1-2 预留迁移编号；项目配置与证据分类不依赖数据库结构变更。
- `backend/app/artifacts.py`、`workspace.py`、`providers.py`、`tools.py`：未改（复用既有 ArtifactStore/Workspace/Store 事件链，没有第二套事件存储）。
- PR #6 分支与其历史、`main` 分支。

## PR #7 独立审查修复追加变更（2026-11-08）

| 文件 | 变更 |
|---|---|
| `backend/app/imports.py` | `read_manifest` 校验 canonical 字节与 `manifest_sha256`；新增 `bind_manifest` 与 `scan_imports`，将 Manifest 与 `challenge_imported` 事件逐字段绑定（含 original_artifact_id、事件 artifact_ids）；`imported_file` 返回 Manifest 条目供读取时复核；不再静默跳过不可信 Manifest。 |
| `backend/app/main.py` | imports 列表显式返回 `manifest_verified`/`integrity_error` 不可信项；详情/文件路径在事件链无效、Manifest 校验或绑定失败时 409；文件读取复核 size+SHA256（409 且不返回篡改内容），新增 `X-Imported-File-Integrity`；导出把全部已验证导入与未验证问题传入导出器。 |
| `backend/app/export.py` | 按 `import_id` 导出每一次导入的 `challenge/imports/<id>/original.zip` 与 `extracted/...`；逐文件复核 size+SHA256；`manifest.json.imports` 记录每项 `status/exported_file_count/missing_files/error`；任一项缺失/篡改/未验证 → 整体 incomplete。 |
| `backend/app/models.py` | `NoteCreate.kind`（note/approach，默认 note，历史笔记默认普通笔记）；`ImportRecord.manifest_verified`、`integrity_error` 增量字段。 |
| `backend/app/writeup.py` | 仅 `kind="approach"` 笔记满足 core_approach，普通笔记只作为「其他人工笔记」；新增 `core_code`（需 source_code/analysis 文本证据）与 `execution_evidence`（需 execution/execution_output 证据）缺失项与中文标记；不伪造内容。 |
| `backend/tests/test_mvp_imports.py` | 导入记录字段集合加入增量验证字段。 |
| `backend/tests/test_mvp_writeup_export.py` | 适配每导入目录的导出结构、approach 笔记、新增 missing codes。 |
| `backend/tests/test_mvp_review_fixes.py` | 新增 P1-1/P1-2/P1-3/P2-1 全量回归测试。 |
| `docs/MVP_BACKEND.md` | 更新 Manifest 校验、文件读取 409、逐导入导出、Writeup approach/code/execution 语义与标记。 |
| `docs/openapi.json` / `docs/contracts.json` | 由 `python -m app.schema_cli` 重新生成（NoteCreate.kind、ImportRecord 验证字段）。 |

## 人工稿持久化追加变更（2026-11-08）

| 文件 | 变更 |
|---|---|
| `backend/app/models.py` | 新增 `WriteupDraft`（响应）与 `WriteupDraftSave`（请求；`content` StrictStr、`base_version` StrictInt≥0、extra forbid）。 |
| `backend/app/writeups.py` | 新增 `WriteupStore`：每 Challenge sidecar、版本 v1 起、SHA-256/size/服务器时间、1 MiB、乐观冲突、原子写、单进程锁、损坏拒绝。 |
| `backend/app/main.py` | `max_writeup_bytes` / `CTF_MAX_WRITEUP_BYTES`；`GET/PUT /writeup/draft`（201/200/409/413/422；无别名）；Writeup PUT 请求体 Content-Length 预检 + 实际接收字节计数（含 chunked，超限 413）；导出加载人工稿并传递生成稿/人工稿/完整性错误；health 增加 `writeup_max_bytes`；版本 0.3.0。 |
| `backend/app/export.py` | 新增 `writeup_generated.md`；`writeup.md` 人工稿逐字节/初稿+注明/损坏 fallback；manifest `writeup` 段（final_source/final_sha256/final_size/generated/human/integrity_error）；人工稿损坏 → incomplete + INCOMPLETE 说明；SHA256SUMS 自动覆盖两份 writeup。 |
| `backend/app/schema_cli.py` | 导出模型清单加入 `WriteupDraft`/`WriteupDraftSave`。 |
| `backend/tests/test_mvp_writeup_export.py` | 适配 `writeup_generated.md`、无人工稿 `writeup.md` 头注、manifest writeup 字段（不删除原有测试）。 |
| `backend/tests/test_mvp_writeup_persistence.py` | 新增 23 项回归（B3 10 项 + 并发/无事件/请求安全/legacy 迁移/原子性）。 |
| `docs/MVP_BACKEND.md` | 新增 §4.10 人工稿契约（路径、请求/响应、409、1 MiB、原子性、单进程、SHA256 完整性边界、前端 localStorage 迁移指引）；更新导出结构/manifest/限制。 |
| `docs/MVP_WRITEUP_ACCEPTANCE.md` | 真实 HTTP 验收记录（30 条请求、ZIP/manifest/SHA 校验、tamper fallback、证据文件哈希）。 |
| `docs/openapi.json` / `docs/contracts.json` | 重新生成新端点与模型。 |

**无数据库迁移**；数据目录新增 `writeups/` sidecar 目录（运行时，不提交）。

## 复现命令

```powershell
cd backend
python -m pytest -q
python -m ruff check app tests
python -m app.schema_cli
```
