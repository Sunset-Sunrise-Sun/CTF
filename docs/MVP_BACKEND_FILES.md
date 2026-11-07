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
| `backend/tests/test_mvp_imports.py` | 1076 | 42 个测试函数 / 50 个用例：项目规则、Challenge 扩展兼容、ZIP 导入与 12 类安全用例、证据分类、人工操作、health/限制/重启。 |
| `backend/tests/test_mvp_writeup_export.py` | 756 | 21 个测试函数 / 24 个用例：Writeup 预览、缺失标记、AI 披露、导出结构与 SHA256SUMS、字节一致性、不完整/篡改/只读、端到端流程。 |
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

## 复现命令

```powershell
cd backend
python -m pytest -q
python -m ruff check app tests
python -m app.schema_cli
```
