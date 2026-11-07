# P1-1 文件变更清单

分支：`feat/p1-evidence-storage`（基于 `ed4850dc17601a9e8177c12c95d1281e072cccd4`，目标分支 `feat/framework-scaffold`）

## 新增

| 文件 | 说明 |
|---|---|
| `backend/app/artifacts.py` | 内容寻址存储模块：流式写入、SHA-256、50MB 限制、魔数媒体类型嗅探、文件名清理、存储根路径守卫（路径穿越/符号链接/junction 逃逸、Windows 扩展路径归一化）、原子安装、只读 blob、读取后哈希校验、孤立 blob 清理。 |
| `backend/app/migrations/002_artifacts.sql` | `artifacts` 表、`UNIQUE(challenge_id, sha256)` 去重约束、`source_event_id UNIQUE` 一对一约束、`(challenge_id, source_event_id) → events(challenge_id, event_id)` 联合外键、`events_challenge_event` 复合唯一索引、append-only 触发器、题目索引。 |
| `backend/tests/test_artifacts.py` | A01–A12 验收测试、7 类必需测试、安全测试、独立审查后的加固测试与 Artifact/Event 关联约束修复测试，共 36 个测试函数 / 48 个 pytest item；全部使用合成数据。 |
| `docs/P1_ARTIFACT_STORAGE.md` | P1-1 设计说明：数据关联、存储布局、上传/一致性流程、API 契约、安全对照、A01–A12 矩阵、已知限制、SHA-256 实测示例。 |
| `docs/P1_FILES.md` | 本文件变更清单。 |
| `docs/P1_TEST_REPORT.md` | 本地测试、Ruff 与远程 CI 结果。 |
| `docs/P1_FIX_REPORT.md` | Artifact/Event 关联约束修复报告（问题、根因、约束修复、测试与 CI）。 |

## 修改

| 文件 | 说明 |
|---|---|
| `backend/app/store.py` | 新增 `add_artifact`（单事务写入 `artifact_added` 事件 + `event_heads` + `artifacts` 行）、`artifacts`、`artifact`（含题目归属）、`artifact_by_sha`、`count_artifacts_with_sha`；抽出 `_append_event` 复用哈希链追加逻辑，`append` 行为不变；连接启用 `PRAGMA recursive_triggers=ON` 阻断 `INSERT OR REPLACE` 绕过 append-only 触发器；`verify` 不变。 |
| `backend/app/main.py` | 新增附件上传/列表/元数据/下载/完整性接口；`create_app` 支持 `max_artifact_bytes`（默认 50MB，可被 `CTF_MAX_ARTIFACT_BYTES` 覆盖）；新增 ASGI 入口体积限额中间件 `ArtifactBodyLimitMiddleware`（Content-Length 预检 + chunked 字节计数）；单进程上传锁；DB 失败时未引用 blob 清理；下载哈希校验与安全响应头；`/api/health` 增加 `artifact_max_bytes`。未改动题目、事件、笔记、完整性接口行为。 |
| `backend/pyproject.toml` | 新增运行时依赖 `python-multipart==0.0.20`（FastAPI multipart 上传所需）。 |
| `backend/tests/test_core.py` | 迁移数量断言由 1 改为 2（新增 `002_artifacts.sql` 后的预期值），未改动其它测试逻辑。 |
| `docs/openapi.json` | 并入新附件接口的 OpenAPI 导出（仅新增 292 行，无删除）。 |
| `README.md` | 追加 P1-1 文档导航。 |

## 未修改（按范围约束）

- `main` 分支、`feat/framework-scaffold` 既有提交与事件历史。
- `backend/app/tools.py`、`providers.py`、`workspace.py`：不启用工具执行、不接入模型网络；工作区路径边界能力不被附件存储复用（附件路径完全由服务端 SHA-256 派生）。
- 前端未改动：P1-1 只交付后端证据存储能力，前端接入不在本轮范围。
- 未提交任何本地数据（`.local-data/`、附件、数据库、日志均被 `.gitignore` 忽略）；仓库内不存在真实比赛材料。
