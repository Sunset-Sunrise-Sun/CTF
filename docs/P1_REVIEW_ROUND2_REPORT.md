# P1 模型服务设置：第二轮独立复审整改报告

- 日期：2026-11-09
- 工作区：`D:\CTF-worktrees\p1-settings`
- 分支：`feat/p1-model-settings`
- 基准：当前 P1 候选（未回退 P0）
- 状态：未 commit、未 push、未 merge；等待独立复审
- 范围：只修复 R2-01 ~ R2-04；未增加其他功能

## R2-01 配置保存失败时恢复完整状态

- `save()` 保存前备份 `_config`、`_config_error`、`_configured`，同时备份旧配置文件与旧凭证文件字节。
- DPAPI 凭证在写文件前预先加密；加密失败不触碰任何文件。
- 配置写入成功前不清除 `config_error`；全部文件操作成功后，才更新 `_config_error`/`_configured`。
- 配置写失败：不改动原配置，恢复全部内存状态；原损坏配置与 `config_error=invalid_config` 保留。
- 凭证写失败（或清除失败）：回滚已写入的配置和凭证，保证配置文件/凭证与内存状态一致。
- 使用 `config_written`/`secret_changed` 标志，仅补偿真正改动的文件。
- 故障注入测试覆盖：
  - 原配置损坏；
  - 保存新配置时注入配置磁盘写入失败；
  - `config_error` 仍存在；
  - 环境变量强制联网仍返回 503 `config_invalid`；
  - 恢复写入后重新保存成功，模型调用恢复；
  - 凭证写入失败时配置/凭证均回滚，恢复后可正常保存。

## R2-02 DataDir Junction/ReparsePoint 防护

- 在 `p1-common.ps1` 增加 `Assert-P1NoReparseComponents`：
  - 使用原始绝对路径，逐级检查已存在的父路径组件和 DataDir 本身；
  - 任何组件带 `ReparsePoint` 即拒绝（Junction/Symlink/ReparsePoint）；
  - 不使用 `Resolve-Path` 预先解析，避免丢失链接身份；
  - 属性读取异常、非目录组件、枚举异常一律 fail-closed。
- `Assert-P1SafeDataDir` 在路径检查、业务数据库扫描、目录枚举处均使用 `-ErrorAction Stop` 并转换为拒绝。
- 启动脚本创建数据目录后**再次**调用安全检查，防止创建期间路径被替换为 Junction。
- 保留默认 `.local-run\data` 正常启动。
- Windows 实机测试：
  - DataDir 本身为 Junction；
  - 父目录为 Junction；
  - Junction 指向原项目数据；
  - ACL 权限不足导致枚举失败；
  - 正常独立目录与默认目录通过。

## R2-03 停止脚本终止前二次核验

- 停止前执行两轮身份验证：可执行文件、完整命令行、启动时间、身份 token、监听端口。
- 第二轮验证通过后获取 `System.Diagnostics.Process` 句柄，并核对句柄启动时间；使用经过验证的进程句柄 `Kill()`，不再仅按 PID 执行 `taskkill`。
- 终止前再次检查句柄存活与启动时间；身份不一致时拒绝停止且不杀进程。
- 保留行为：正常停止、进程不存在幂等返回、PID 复用/身份不匹配拒绝。
- `stop-result.json` 记录两轮 checks/preflight、停止方式（`identity-verified Process.Kill handles`）和失败项。

## R2-04 启动失败清理统一

- 启动脚本为后端/前端创建统一启动记录（PID、可执行文件、完整命令行、启动时间、身份 token、端口）。
- 后端健康失败、前端就绪失败均调用 `Stop-P1ProcessByVerifiedHandle` 统一安全清理；不再直接 `Stop-Process` 未验证 PID。
- 清理前重新验证身份；身份不匹配返回 mismatch、不杀进程；清理失败保留进程信息和日志，写入 `start-failure.json`（含 `records`、`cleanup`、stdout/stderr 路径）。
- 启动失败测试：
  - 后端启动后、健康前被外部终止 → 启动脚本识别失败、写 `start-failure.json`、无残留端口；
  - 前端清理使用同一 verified-handle helper；
  - 身份不匹配的 cleanup 拒绝 kill 并保留进程信息。

## 验收结果（本轮）

| 检查 | 结果 | 退出码 | 日志 |
|---|---|---|---|
| 后端全量 pytest | **308 passed, 7 skipped, 0 failed** | 0 | `verification/p1-model-settings/review-round-2/backend-pytest.log` |
| Ruff | **All checks passed** | 0 | `review-round-2/ruff.log` |
| 设置专项 | **18 passed** | 0 | `review-round-2/settings-tests.log` |
| 前端 npm test | **63 pass / 0 fail** | 0 | `review-round-2/frontend/npm-test.log` |
| TypeScript + 生产构建 | `vue-tsc --noEmit && vite build` 成功 | 0 | `review-round-2/frontend/npm-build.log` |
| AI 设置 E2E | **15 passed**（4 个设置用例） | 0 | `review-round-2/frontend/e2e-ai.log` |
| DataDir Windows 专项 | **6 项通过** | 0 | `review-round-2/datadir-windows-tests.log` |
| DataDir/停止 guard | **8 项通过** | 0 | `review-round-2/guard-tests.log` |
| 启动失败清理 | **5 项通过** | 0 | `review-round-2/start-cleanup-tests.log` |
| DataDir 原项目拒绝 | 预期拒绝 | 1（预期） | `review-round-2/datadir-refusal.log` |

原始退出码：`review-round-2/EXIT-CODES.txt`。

## 独立运行证据

- 后端 `127.0.0.1:18110`，PID `32196`
- 前端 `127.0.0.1:15190`，PID `54736`
- 数据目录 `.local-run\data`
- 启动 `2026-11-09T05:39:23Z`，停止 `2026-11-09T05:40:37Z`
- 停止结果：两轮身份校验通过，`Process.Kill` 句柄停止，backend/frontend 均 `ok`
- 截图：`review-round-2/run/model-settings-1440px.png`、`model-settings-390px.png`
- `run-screenshots.json`：`key_visible=false`、`storage_contains_key=false`、`mobile_no_horizontal_overflow=true`
- 无真实模型请求

## 未解决/边界

- 单用户、回环、无认证；DPAPI 为 Windows 用户级保护。
- 非 Windows 凭证存储未实现。
- 真实 DeepSeek 联网、真实 Key、真实题目/Flag 未验证。
- 启动失败清理测试使用外部终止后端模拟健康失败；前端失败路径由同一 verified-handle helper 覆盖。
- 运行记录损坏或身份不匹配时停止/清理会拒绝操作，需要人工核对；不会盲目杀进程。

## 停止条件

仅完成第二轮复审四项整改。**停止，等待独立复审。** 不 commit/push/merge，不进入真实 API 测试。
