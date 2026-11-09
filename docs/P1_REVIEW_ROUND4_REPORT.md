# P1-R4 最终独立复审整改报告

- 日期：2026-11-09
- 工作区：`D:\CTF-worktrees\p1-settings`
- 分支：`feat/p1-model-settings`
- HEAD：`30eeed6dcc180ae21b5648f25047c5889e3c434a`
- 未 commit/push/merge；未修改 P0 冻结候选、PR #9、现有业务服务；无真实 DeepSeek/题目/Flag

## 1. RunDir 关键文件保护

`p1-common.ps1` 新增 `Assert-P1SafeRunFile` 与安全写入封装：

- 对 `backend.pid`、`frontend.pid`、`run-info.json`、`start-failure.json`、`stop-result.json`、backend/frontend stdout/stderr 共 9 个叶节点检查；
- 文件不存在视为正常；普通文件接受；Symlink/Junction/ReparsePoint 和目录冒充文件拒绝；
- 读取 run-info、移动历史 run-info、PID 写入、启动失败记录、stop-result、run-info 覆盖写入分别检查；
- 日志重定向启动前检查既有日志文件；
- 属性读取异常 fail-closed。

RunDir 文件叶节点专项 **14 项通过**，包括 9 个文件预置 Junction、普通目录冒充文件、启动前预置 `backend.pid` Junction 拒绝启动且无监听。

## 2. 启动生命周期异常清理

`p1-start.ps1` 使用覆盖整个启动流程的统一 `try/catch`：

- 进程启动后立即记录 PID 与完整身份；
- 任意阶段异常时检查所有已启动进程；
- 统一使用 `Stop-P1ProcessByVerifiedHandle`；
- `UNKNOWN`/`MISMATCH` 拒绝终止；
- 清理失败保留 PID、身份、日志和 `start-failure.json`；
- 正常启动/停止不变。

故障注入专项 **7 项通过**：

- 后端 PID 文件写入失败 → 安全清理；
- 后端身份记录生成失败 → 安全清理；
- 前端记录写入失败 → 前端/后端安全清理；
- 最终 run-info 写入失败 → 两进程清理；
- 清理时身份变更 → 拒绝终止并保留进程；
- 清理失败不误杀无关 sentinel 进程；
- 正常启动/停止成功，两进程 `ok`/`stopped`，端口释放。

## 3. 验收日志

| 检查 | 结果 | 退出码 | 日志 |
|---|---|---:|---|
| 后端全量 pytest | 308 passed, 7 skipped | 0 | `review-round-4/final/backend-pytest.log` |
| Ruff | All checks passed | 0 | `review-round-4/final/ruff.log` |
| 前端 npm test | 63 pass | 0 | `review-round-4/final/frontend/npm-test.log` |
| TypeScript + 构建 | 成功 | 0 | `review-round-4/final/frontend/npm-build.log` |
| AI 设置 E2E | 15 passed | 0 | `review-round-4/final/frontend/e2e-ai.log` |
| RunDir 文件叶节点专项 | 14 项通过 | 0 | `review-round-4/final/runfile-tests.log` |
| RunDir/Junction 专项 | 6 项通过 | 0 | `review-round-4/final/rundir-tests.log` |
| 进程身份专项 | 7 项通过 | 0 | `review-round-4/final/process-identity-tests.log` |
| 启动失败/生命周期专项 | 7 项通过 | 0 | `review-round-4/final/startup-failure-tests.log` |

7 个 backend skip 为原环境限制（6 个 Windows symlink 权限、1 个真实 Provider opt-in）。

## 4. 证据与边界

- 启动失败/身份变更/正常启动停止证据：`review-round-4/final/startup-evidence/`
- 原始退出码：`review-round-4/final/EXIT-CODES.txt`
- 未触碰 8000/8001/8002/5173/5174。
- 路径检查与文件打开之间仍有理论并发替换窗口；按本地可信用户目录假设。
- `UNKNOWN`/`MISMATCH` 宁可保留进程也不强杀，需人工核对。
- 未运行真实 DeepSeek、真实题目/Flag；E2E 模型连接使用 Mock/隔离路由。

## 停止条件

P1-R4 最终整改完成。**停止，等待独立复审。** 不 commit/push/merge。
