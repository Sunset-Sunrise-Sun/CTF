# P1-1 测试报告 — 2026-11-07

环境（本地）：Windows PowerShell；Python 3.14.7；FastAPI 0.142.2；pytest 9.1.1；ruff 0.14.10。
CI 环境：GitHub Actions `P0 checks`（Ubuntu latest，Python 3.11，Node 22）。

## 本地结果

| 检查 | 命令 | 结果 |
|---|---|---|
| 全仓测试 | `cd backend; python -m pytest -q` | **71 passed, 3 skipped, 0 failed**（4.85s） |
| P1 验收测试 | `python -m pytest -q tests/test_artifacts.py` | **43 passed, 1 skipped, 0 failed**（3.62s） |
| Ruff lint | `python -m ruff check app tests` | **All checks passed** |
| Ruff format | `python -m ruff format --check app tests` | **13 files already formatted** |
| 前端构建 | 未改动前端；沿用 P0 CI | — |

跳过项说明：

1. `test_symbolic_link_escape_rejected`：Windows 当前账户无创建符号链接权限，按仓库既有 `test_core.py` 先例 `pytest.skip`；Linux CI 会真实执行该用例（Windows 本地另有 `test_junction_escape_rejected` 用目录 junction 实测通过）。
2. `test_core.py` 中 2 个 P0 既有跳过项（符号链接权限、真实 Provider 联网凭证）不受本轮影响。

## P1 测试覆盖

`backend/tests/test_artifacts.py`（32 个测试函数 / 44 个 pytest item）：

- **A01–A12 验收矩阵**（函数名 `test_a01_*` … `test_a12_*`）：上传与哈希、内容寻址布局、SQLite 元数据、`artifact_added` 事件、三方关联、列表、元数据查询、下载与归属、去重、不可变性与篡改检测、50MB 限制、重启持久化。
- **必需专项测试**：`test_duplicate_upload`、`test_cross_challenge_access_denied`、`test_file_tamper_detected`、`test_database_failure_consistency`、`test_database_failure_keeps_shared_blob`、`test_file_write_failure_consistency`、`test_restart_persistence`、`test_event_hash_chain`、`test_concurrent_duplicate_upload`（8 并发 + `threading.Barrier`，断言恰好 1 个 201、唯一 artifact_id、各 1 行 DB/事件、单份 blob、链有效；额外压测 30 轮全过）。
- **安全测试**：文件名穿越/控制字符/超长参数化 13 组、客户端 MIME 伪造 7 组、符号链接逃逸、ZIP 不解压、敏感内容不进日志、缺失 blob/未知 ID、空文件。
- **独立安全审查后的加固测试**：入口 `Content-Length` 预检、chunked 字节计数、`INSERT OR REPLACE` 被 append-only 触发器拒绝、Windows junction 逃逸（POSIX 由符号链接测试覆盖）。

测试数据全部为模块内自造的合成字节（自造 PNG/JPEG/PDF/ZIP/ELF 魔数、合成文本），未使用任何真实比赛附件、Flag 或目标；每个测试用 `tmp_path` 隔离数据根。

## 独立安全审查

独立审查员（只读代码、临时目录对抗验证、未修改仓库）对 15 项安全/一致性要求复核，结论「无严重 blocker」；1 项中等（入口 multipart 缓冲）与 2 项低风险（Windows 扩展路径守卫、非 sqlite 异常孤立 blob）及 1 项信息项（REPLACE 旁路）已在本分支修复，详见 `docs/P1_ARTIFACT_STORAGE.md` 第 11 节。

## 远程 CI

| 项目 | 结果 |
|---|---|
| PR | 待创建 |
| `P0 checks`（backend） | 待运行 |
| `P0 checks`（frontend） | 待运行 |

> 远程 CI 状态以 PR 页面实际运行结果为准，创建 PR 后回填运行链接与结论。

## 复现

```powershell
cd backend
python -m pip install -e ".[dev]"
python -m ruff check app tests
python -m pytest -q
```
