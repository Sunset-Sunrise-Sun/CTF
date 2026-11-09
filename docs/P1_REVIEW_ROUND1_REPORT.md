# P1 模型服务设置：第一轮独立复审整改报告

- 日期：2026-11-09
- 工作区：`D:\CTF-worktrees\p1-settings`
- 分支：`feat/p1-model-settings`
- 基准：P0 冻结候选 `D:\CTF-worktrees\p0-frozen`
- 状态：未 commit、未 push、未 merge；等待独立复审
- 范围：只处理复审四项；未增加其他功能

## 1. 环境变量 Key 与自定义 API 地址

### 行为

- 状态中明确区分 `key_source`：`settings`（DPAPI）/ `environment` / `null`；绝不返回 Key。
- 环境变量 Key + 非默认 `https://api.deepseek.com` 地址时，必须由用户显式授权：
  - 前端显示授权勾选框与警告；
  - `PUT /api/model/settings` 接受 `authorize_env_key_custom_base_url`；
  - 后端把授权绑定到当前**精确** base URL；
  - 地址变更时旧授权清除，新地址必须重新授权；
  - 未授权时 `provider_values()` 拒绝，`build_deepseek_provider(settings)` 抛出 `env_key_custom_base_url_not_authorized`；
  - `/api/model/test` 返回 403，不发出网络请求；
  - 默认 DeepSeek 地址使用环境变量 Key 无需额外授权。
- 授权状态：`env_key_custom_base_url_authorized`、`env_key_custom_base_url_authorization_required`。

### 回归测试

- `test_environment_key_custom_address_requires_explicit_backend_authorization`：未授权 403、授权后状态为 true、换自定义地址后旧授权失效并再次 403；
- `test_default_deepseek_address_with_environment_key_needs_no_extra_authorization`；
- 前端 `model-settings.test.mjs`：环境变量 + 自定义地址的 helper 状态；
- E2E：环境变量 Key + 自定义地址的授权 UI、保存请求包含授权字段。

## 2. 独立运行停止脚本

- 停止前不再直接 taskkill：
  - 验证 PID 对应可执行文件；
  - 验证完整启动命令行；
  - 验证进程启动时间（防 PID 复用）；
  - 验证身份 token；
  - 验证记录端口确由该 PID 监听。
- 身份不匹配时拒绝停止且不杀任何进程；进程不存在时幂等返回（视为已停止）；正常匹配才 `taskkill /T /F`。
- 启动脚本记录上述身份元数据；停止结果写入 `stop-result.json`。
- 可复现验证：`scripts/verify-p1-guards.ps1` 覆盖：
  - PID 复用/身份不匹配：exit 2，进程存活；
  - 进程不存在：exit 0，不杀；
  - 正常停止：两个真实监听进程被停止，端口释放。

## 3. 独立数据目录保护

- DataDir 绝对路径规范化；
- 拒绝 `D:\CTF\.local-data` 等原项目数据目录、任何 `.local-data` 路径、工作区源码目录；
- 拒绝包含 `workbench.sqlite3`、`model-audit.sqlite3`、`project.json`、`challenges`、`artifacts`、`writeups` 等既有数据的目录；
- 自定义已有非空目录必须显式 `-AllowNonEmptyDataDir`，且仍拒绝业务数据库；
- 默认 `.local-run\data` 运行方式保持可用；
- 不删除/修改现有数据。

## 4. 配置损坏 fail-closed

- `config_error=invalid_config` 非空时：
  - `/api/model/test`、AI 对话、`ask_challenge`、`test_deepseek_connection`、Provider 构建全部拒绝；
  - 返回明确错误码 `config_invalid`（HTTP 503）；
  - 即使 `CTF_MODEL_NETWORK_ENABLED=true` 也不使用损坏配置联网；
- 用户重新保存有效配置后 `config_error` 清空，模型调用/测试连接恢复；
- 测试覆盖：损坏配置拒绝调用、修复后状态清空、修复后 Mock 连接成功。

## 5. 本轮验收结果

| 检查 | 结果 | 退出码 | 日志 |
|---|---|---|---|
| 后端全量 pytest | **306 passed, 7 skipped, 0 failed** | 0 | `verification/p1-model-settings/review-round-1/backend-pytest.log` |
| Ruff | **All checks passed** | 0 | `review-round-1/ruff.log` |
| 设置专项 | **16 passed** | 0 | `review-round-1/settings-tests.log` |
| 前端 npm test | **63 pass / 0 fail** | 0 | `review-round-1/frontend/npm-test.log` |
| TypeScript + 生产构建 | `vue-tsc --noEmit && vite build` 成功 | 0 | `review-round-1/frontend/npm-build.log` |
| AI 设置 E2E | **15 passed**（4 个设置用例） | 0 | `review-round-1/frontend/e2e-ai.log` |
| DataDir/停止保护 | **8 项 guard 检查通过** | 0 | `review-round-1/guard-tests.log` |

退出码汇总：`review-round-1/EXIT-CODES.txt`。

## 6. 独立运行证据（本轮）

- 后端 18110 / 前端 15190；后端 PID 57496、前端 PID 42896；
- 启动 `2026-11-09T05:21:50Z`，停止 `2026-11-09T05:23:03Z`；
- 数据目录 `.local-run\data`；
- 停止校验全部通过（`review-round-1/run/stop-result.json`）；
- 1440/390 截图：`review-round-1/run/model-settings-1440px.png`、`model-settings-390px.png`；
- `run-screenshots.json`：`key_visible=false`、`storage_contains_key=false`、`mobile_no_horizontal_overflow=true`；
- 无真实模型请求。

## 7. 未解决/边界

- 单用户、回环、无认证；DPAPI 为 Windows 用户级保护。
- 非 Windows 凭证存储未实现。
- 环境变量 Key + 自定义地址的授权是本地用户行为；无多用户认证。
- 真实 DeepSeek 联网/真实 Key/真实题目/Flag 未验证。
- 停止脚本拒绝身份不匹配的进程；若运行记录损坏，需要人工核对后处理，不会盲目 taskkill。

## 8. 停止条件

仅完成复审四项整改。**停止，等待独立复审。** 不 commit/push/merge，不进入真实 API 测试。
