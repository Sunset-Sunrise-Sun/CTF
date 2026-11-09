# P0 + P1 冻结候选验收报告

- 日期：2026-11-09
- 工作区：`D:\CTF-worktrees\p0-p1-frozen`
- 分支：`feat/p0-p1-freeze`（基于 `30eeed6dcc180ae21b5648f25047c5889e3c434a`，未提交）
- 最终状态：**CONDITIONAL GO**

## 1. 结论

P0 与 P1 已真实整合；冻结源码在加入交付文档前与当前 P1 源码逐文件一致（忽略行尾归一化、依赖/证据目录）。P0 完整补丁可复现 P0 冻结源码。未发现 P0/P1 运行时代码冲突或 P0 安全能力丢失。

本轮全部本地测试、Mock 模型测试、HTTP 验收、前端 E2E、安全专项和独立启动均通过。未执行真实 DeepSeek 联网（任务明确禁止），因此状态为 CONDITIONAL GO，而不是声称真实模型已验收。

## 2. 整合与审计

- 审计文件：[FREEZE_INTEGRATION_AUDIT.md](FREEZE_INTEGRATION_AUDIT.md)
- P0 完整补丁：`7c4c959bb548a52a148f7f547b184928dc5d715e74656dce1f888c7010eea12a`
- P1 增量补丁：`59d5c03312e453dd3acb6b6946fa9144ca0a1f214ecc80451f7caaf07dc8e057`
- P0 补丁应用到 baseline 后与 `p0-frozen` 内容一致。
- P1 补丁以 P0 冻结候选为基准；唯一差异为 R5 最终测试脚本的两版测试专用增量，已用两个经验证的测试-only diff 补齐。没有替换运行时代码。
- 整合后源码与 `p1-settings` 当前源码一致（排除证据/依赖目录，CRLF/LF 归一化）。
- 未修改 `unified`、`p1-settings`、`p0-frozen`；未修改 PR #9；未 commit/push/merge。

## 3. 后端回归

工作目录：`p0-p1-frozen/backend`

| 检查 | 结果 | 退出码 | 日志 |
|---|---|---:|---|
| 全量 pytest | **308 passed, 7 skipped, 0 failed** | 0 | `verification/freeze-20261109/backend/pytest.log` |
| Ruff | **All checks passed** | 0 | `verification/freeze-20261109/backend/ruff.log` |
| 安全相关定向测试 | **157 passed, 5 skipped, 0 failed** | 0 | `verification/freeze-20261109/backend/security-tests.log` |
| 真实 HTTP 验收 | **19 passed, 0 failed** | 0 | `verification/freeze-20261109/backend/http-acceptance.log` |

覆盖：

- AI 调用审计、A0/A1/A2 门禁；
- 工具路径安全、lstat fail-closed、人工审批状态机；
- Artifact 保存/完整性；
- Writeup/ZIP 导出与披露；
- 模型设置/DPAPI、环境变量 Key 授权、配置损坏 fail-closed；
- 配置写入/凭证写入失败回滚。

### 跳过项（未计为通过）

7 个 skip：

1. `test_artifacts.py:537`：Windows symlink 权限不可用。
2. `test_core.py:137`：Windows symlink 权限不可用。
3. `test_model_call_paths.py:37`（3 项）：Windows symbolic link privilege unavailable（WinError 1314）。
4. `test_providers.py:147`：需要显式 opt-in 和合法 Provider 凭证的真实 Provider 测试。
5. `test_tools.py:472`：本机不允许创建 symlink。

定向安全测试的 5 个 skip 是上述 symlink 类测试的子集，原因相同。

## 4. 前端与 E2E

工作目录：`p0-p1-frozen/frontend`

| 检查 | 结果 | 退出码 | 日志 |
|---|---|---:|---|
| `npm test` | **63 pass / 0 fail** | 0 | `verification/freeze-20261109/frontend/npm-test.log` |
| TypeScript + 生产构建 | `vue-tsc --noEmit && vite build` 成功 | 0 | `verification/freeze-20261109/frontend/npm-build.log` |
| Playwright AI/设置 E2E | **15 passed** | 0 | `verification/freeze-20261109/frontend/e2e-ai.log` |

E2E 覆盖 AI 助手、工具审批、跨题目确认隔离、A2 附件授权、Flag 摘要、模型设置页面、Key 显示/隐藏、刷新恢复和连接错误。

布局截图：

- `verification/freeze-20261109/frontend/model-settings-1440px.png`
- `verification/freeze-20261109/frontend/model-settings-390px.png`
- 独立未配置状态截图：`verification/freeze-20261109/startup/model-settings-unconfigured-1440.png`、`...-390.png`

E2E 截图是在测试状态下保存的（含已配置的合成 Key 状态）；独立启动截图是未配置状态，二者均不含 Key 明文。

## 5. 安全专项

工作目录：`p0-p1-frozen`

| 专项 | 结果 | 退出码 | 日志 |
|---|---|---:|---|
| RunDir 关键文件叶节点/Junction | 14 项通过 | 0 | `verification/freeze-20261109/security/verify-p1-runfile.log` |
| RunDir Junction/创建后复核 | 6 项通过 | 0 | `.../verify-p1-rundir.log` |
| DataDir Junction/权限 | 6 项通过 | 0 | `.../verify-p1-datadir.log` |
| DataDir/停止身份 guard | 8 项通过 | 0 | `.../verify-p1-guards.log` |
| 进程身份 NORMAL/MISSING/UNKNOWN | 7 项通过 | 0 | `.../verify-p1-process-identity.log` |
| 启动失败清理 | 通过 | 0 | `.../verify-p1-start-cleanup.log` |
| R3 启动失败集成 | 通过 | 0 | `.../verify-p1-r3-startup.log` |
| R4 生命周期故障注入 | 7 项通过 | 0 | `.../verify-p1-r4-startup.log` |
| R5 身份生成故障/恢复 | 通过 | 0 | `.../verify-p1-r5-identity.log` |

另外：

- 证据日志中未发现测试 Key 明文（`synthetic-deepseek-key`、`synthetic-independent-run-key`、`sk-...` 搜索无匹配）。
- 后端设置测试验证 Key 不进入设置响应、事件、Writeup/ZIP 导出文本；E2E 验证 localStorage 不含 Key。
- lstat fail-closed、跨题目确认隔离、A1/A2 附件授权由后端定向测试和 E2E 覆盖。

## 6. 独立运行验收

脚本：`scripts/freeze-start.ps1`、`scripts/freeze-stop.ps1`，底层使用经身份验证的 P1 启动/停止逻辑。

实际记录：

- 后端 `127.0.0.1:18110`，前端 `127.0.0.1:15190`；
- 后端 PID `46300`、前端 PID `4244`（wrapper 运行记录）；
- 数据目录 `.local-run\data`；运行目录 `.local-run\run`；
- 模型联网默认关闭；
- 健康检查 `status=ok`；
- 停止结果为 backend/frontend 均 `stopped`，无残留监听；
- 未复用其他工作区 SQLite。

证据：

- `verification/freeze-20261109/startup/wrapper-run-info.json`
- `verification/freeze-20261109/startup/wrapper-stop-result.json`
- `verification/freeze-20261109/startup/wrapper-start.stdout.log`
- `verification/freeze-20261109/startup/wrapper-stop.stdout.log`
- `verification/freeze-20261109/startup/run-info.json`（前一版核心启动记录）
- `verification/freeze-20261109/startup/stop-result.json`
- `verification/freeze-20261109/startup/unconfigured-check.log`
- `verification/freeze-20261109/startup/ui-check.json`

独立未配置检查：

- `GET /api/model/settings`：`key_configured=false`、`network_enabled=false`、`network_setting=false`、`config_error=null`；
- `PUT /api/model/settings`（base/model，无 Key）：`network_enabled` 仍为 `false`；
- 前端可访问；
- 设置页显示「未配置 API Key」和「已关闭」，390px 无横向溢出；
- 手动工具独立可用性由隔离 HTTP 验收覆盖（工具申请→批准→执行→Artifact→披露；19 项通过）。

## 7. 用户独立配置 Key

- 每位用户使用自己的 Windows 账户和各自 data 目录配置自己的 API Key。
- 项目不提供统一 Key，不需要开发者 Key。
- DPAPI 密文绑定当前 Windows 用户；其他 Windows 用户无法解密。
- 设置页面可由每个用户独立打开和保存；非 Windows 无凭证存储，保存会 fail-closed。
- 单用户回环部署没有多用户认证，不应把服务暴露到局域网/公网。

## 8. P0 阻断问题

未发现阻止进入真实 DeepSeek **合成**连接测试的 P0 问题。真实 DeepSeek 联网未执行，是任务约束而不是 P0 缺陷；真实 API 仍需下一阶段人工独立验证。

## 9. 最终状态

**CONDITIONAL GO**

允许进入下一阶段，但必须保留以下明确条件：

1. 本轮没有真实 DeepSeek API 联网证据；下一阶段需用真实（或组织批准的）Key 做固定合成提示测试。
2. 仍有 7 个环境限制 skip（symlink 权限 6 个、真实 Provider opt-in 1 个）。
3. P1 提供的增量/完整补丁相对当前 P1 测试脚本存在测试-only 版本滞后；冻结已用经验证的两个测试脚本增量补齐，需在最终审计中保留该说明。
4. 单用户回环、无多用户认证，不得暴露服务端口。
