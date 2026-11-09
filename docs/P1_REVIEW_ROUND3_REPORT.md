# P1-R3 安全收尾报告

- 日期：2026-11-09
- 工作区：`D:\CTF-worktrees\p1-settings`
- 分支：`feat/p1-model-settings`
- HEAD：`30eeed6dcc180ae21b5648f25047c5889e3c434a`
- 未 commit/push/merge；未修改 P0 冻结候选、PR #9、现有业务服务；无真实 DeepSeek/题目/Flag

## 1. RunDir 路径安全

- `Assert-P1SafeRunDir` 使用原始绝对路径逐级检查 RunDir 自身和全部已有父路径组件，拒绝 Junction/Symlink/ReparsePoint。
- 启动脚本在创建前、创建 RunDir 后、创建 logs/tmp 后分别检查。
- 历史 run-info 归档移动到最终 RunDir 复核之后；检查失败时不写 PID、日志文件或 run-info。
- 默认 `.local-run` 保持可用。
- Windows 专项：RunDir 自身 Junction、父目录 Junction、无写入、创建后复核，共 6 项通过。

## 2. 进程身份异常分类

- `Get-P1ProcessInfo` 返回 `NORMAL` / `MISSING` / `UNKNOWN`。
- CIM 查询异常、CIM 权限不足、进程句柄权限异常、身份字段/启动时间不完整均为 `UNKNOWN`。
- `UNKNOWN` 在停止、清理、启动身份校验中一律拒绝终止，不当作 `MISSING`。
- 真实不存在 PID 才返回 `MISSING`。
- 专项 7 项通过：NORMAL、MISSING、CIM 权限失败、句柄访问拒绝、进程访问拒绝、CIM 无身份、身份不完整。

## 3. 启动失败集成

- 后端进程仍存活但健康检查失败：统一 verified-handle 清理，清理前进程存活记录、端口释放、`start-failure.json`。
- 前端真实 Vite 启动失败：前端 `missing`（已自行退出），后端 `stopped`，端口释放。
- 身份不匹配：拒绝终止并保留进程信息。
- 正常启动/停止：隔离端口 18186/15186，后端 PID 56976、前端 27048，两进程 `ok`/`stopped`，无失败项。

## 4. 验收日志

| 检查 | 结果 | 退出码 | 日志 |
|---|---|---:|---|
| 后端全量 pytest | 308 passed, 7 skipped | 0 | `review-round-3/final/backend-pytest.log` |
| Ruff | All checks passed | 0 | `review-round-3/final/ruff.log` |
| 前端 npm test | 63 pass | 0 | `review-round-3/final/frontend/npm-test.log` |
| TypeScript + 构建 | 成功 | 0 | `review-round-3/final/frontend/npm-build.log` |
| AI 设置 E2E | 15 passed | 0 | `review-round-3/final/frontend/e2e-ai.log` |
| RunDir 专项 | 6 项通过 | 0 | `review-round-3/final/rundir-tests.log` |
| 进程身份专项 | 7 项通过 | 0 | `review-round-3/final/process-identity-tests.log` |
| 启动失败集成 | 3 项通过 | 0 | `review-round-3/final/startup-failure-tests.log` |
| 正常启动/停止 | 成功 | 0 | `review-round-3/final/normal-run/` |
| R3 增量补丁 | 6 文件，apply check 通过 | 0 | `review-round-3/final/P1-R3.diff` |

`P1-R3.diff` SHA-256：`d8e60eead2809d1faac06664c2b3a28f110656dc2649ea4f811538ae9b6ad3f9`。

7 个 backend skip 均为原环境限制（6 个 Windows symlink 权限、1 个真实 Provider opt-in），未计为通过。

## 5. 边界

- 路径检查与文件打开之间仍存在理论并发替换窗口；抵御同机恶意并发替换需基于目录句柄打开。
- `UNKNOWN` 会宁可留下无法安全确认身份的进程，也不按 PID 强杀；必须人工核对记录、进程和端口。
- 未运行真实 DeepSeek、真实题目/Flag；E2E 模型连接使用 Mock/隔离路由。
- 未触碰 8000/8001/8002/5173/5174。

## 6. 停止条件

P1-R3 三项安全收尾完成。**停止，等待独立复审。** 不 commit/push/merge。
