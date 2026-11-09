# P1 第一阶段：模型服务设置页面交付报告

- 日期：2026-11-09
- 分支：`feat/p1-model-settings`
- 基准：P0 冻结候选 `D:\CTF-worktrees\p0-frozen`（P0 统一候选）；仓库基准 HEAD `30eeed6dcc180ae21b5648f25047c5889e3c434a`
- 状态：**未 commit、未 push、未 merge**；等待独立审查
- 范围：仅模型服务配置、凭证存储、联网开关与测试连接；不扩展其他功能
- 真实 API Key / 真实 DeepSeek 联网 / 真实题目 / 真实 Flag：**未使用**。全部测试使用合成 Key 和 MockTransport/Mock 路由。

## 1. 功能

独立「模型服务设置」页面（顶部按钮打开，不进入主要解题工作区）：

- 服务商：DeepSeek（只读）；
- API 地址：默认 `https://api.deepseek.com`，可配置；地址下方显示安全提示：
  “API Key 将发送至当前填写的 API 地址，请确认该地址属于你信任的服务商。”；
- API Key：密码框，支持显示/隐藏；保存后输入框清空；
- 模型：默认显示 `DeepSeek-V4.1-Flash`（官方 API ID `deepseek-flash`），可配置；
- 联网调用：默认关闭，独立保存开关；
- 保存配置、测试连接、连接状态与安全错误原因；
- 清除本机保存的 Key。

截图：

- `verification/p1-model-settings/frontend/model-settings-1440px.png`
- `verification/p1-model-settings/frontend/model-settings-390px.png`
- 独立启动/停止、真实端口/PID、真实运行截图与启动说明：
  [P1_INDEPENDENT_RUN_REPORT.md](P1_INDEPENDENT_RUN_REPORT.md)
- 第一轮复审整改报告：[P1_REVIEW_ROUND1_REPORT.md](P1_REVIEW_ROUND1_REPORT.md)
- 第二轮复审整改报告：[P1_REVIEW_ROUND2_REPORT.md](P1_REVIEW_ROUND2_REPORT.md)
- R3 安全收尾报告：[P1_REVIEW_ROUND3_REPORT.md](P1_REVIEW_ROUND3_REPORT.md)
- R4 最终复审整改报告：[P1_REVIEW_ROUND4_REPORT.md](P1_REVIEW_ROUND4_REPORT.md)
- R5 身份记录故障整改报告：[P1_REVIEW_ROUND5_REPORT.md](P1_REVIEW_ROUND5_REPORT.md)

## 2. 后端接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/model/settings` | 非敏感设置状态；不含 Key |
| PUT | `/api/model/settings` | 保存 base URL/model/可选 Key；不会自动开启联网 |
| PUT | `/api/model/network` | 独立持久化联网开关 |
| POST | `/api/model/test` | 固定合成提示测试；使用当前设置 Provider/Key；需联网有效开启 + 显式确认 |
| GET | `/api/model/status` | 摘要状态；`credentials_configured` 布尔，不含 Key |

接口契约：`docs/openapi.json`、`docs/contracts.json`（由 `python -m app.schema_cli` 生成）。
详细说明：[MODEL_SERVICE_SETTINGS.md](MODEL_SERVICE_SETTINGS.md)。

请求安全校验：

- base URL 仅 HTTPS 或回环 HTTP；拒绝 userinfo/query/fragment/控制字符；
- model id 1..128，字符集受限；
- API Key 8..512，拒绝换行/NUL；请求校验错误不回显 Key；
- `api_key` 与 `clear_api_key` 互斥；
- 保存 Key 不改变联网开关。

## 3. 凭证存储

- 非敏感设置：`<data_root>/model-service.json`，不含 Key；
- API Key：`<data_root>/model-service.secret`，Windows `CryptProtectData`（DPAPI）加密，当前 Windows 用户作用域；
- 不进入 SQLite、事件、Writeup、ZIP、普通日志、前端 localStorage、设置响应；
- `ProviderConfig` 不包含 Key 字段；Key 以私有参数注入 Provider 适配器；
- 非 Windows：`key_storage_available=false`，保存 Key 返回 503，不退化为明文；
- 不同 data root / Windows 用户独立；其他用户无法解密。

## 4. 联网与权限

- 默认关闭；保存 Key 不自动开启。
- 有效联网 = `CTF_MODEL_NETWORK_ENABLED` 环境变量为真，或持久化 `network_enabled=true`。
- 环境变量仍是运维/CLI 覆盖；设置页显示 `network_env_override`，页面不能关闭环境变量导致的开启。
- 关闭联网时 AI 请求与测试连接均返回 503，不调用 Provider。
- A0/A1/A2 门禁保持原实现：设置 Key 或开启联网不改变题目等级权限；A0/A1 仍禁止工具申请。

### 4.1 复审整改补充

- 环境变量 Key 与 DPAPI Key 通过 `key_source=environment/settings` 区分；
- 环境变量 Key + 非默认 DeepSeek 地址：必须显式授权当前**精确** base URL；地址一变旧授权即失效，未授权时后端 403 `env_key_custom_base_url_not_authorized`，不会发出网络请求；
- 配置损坏（`config_error=invalid_config`）：模型调用/测试连接在联网检查前 503 `config_invalid`；即使环境变量强制联网也不使用损坏配置；重新保存有效配置后恢复；
- 独立运行停止脚本校验 PID 对应可执行文件、完整命令行、启动时间、身份 token 和监听端口，不匹配拒绝停止；
- DataDir 规范化并拒绝原项目数据目录、源码目录、既有业务数据库目录；自定义非空目录需显式 `-AllowNonEmptyDataDir`。
- 配置保存故障注入：备份 `_config`/`_config_error`/`_configured` 与旧配置文件/凭证；配置或凭证写入失败时完整回滚，`config_error` 不会在持久化成功前被清除。
- DataDir 逐级拒绝 Junction/Symlink/ReparsePoint；路径枚举/属性读取异常 fail-closed；创建目录后再次检查。
- 停止脚本使用两轮身份校验 + verified Process 句柄终止；启动失败统一走 verified-handle 清理并保留失败记录/日志。

## 5. 测试结果

| 检查 | 结果 | 原始退出码 | 日志 |
|---|---|---|---|
| 后端全量 pytest | **308 passed, 7 skipped, 0 failed** | 0 | `verification/p1-model-settings/review-round-5/final/backend-pytest.log` |
| Ruff | **All checks passed** | 0 | `review-round-5/final/ruff.log` |
| 设置后端专项 | **18 passed**（上一轮） | 0 | `review-round-2/settings-tests.log` |
| 前端 npm test | **63 pass / 0 fail** | 0 | `review-round-5/final/frontend/npm-test.log` |
| 前端生产构建 | vue-tsc + vite build 成功 | 0 | `review-round-5/final/frontend/npm-build.log` |
| API 设置 E2E | **15 passed**（含 4 个设置用例） | 0 | `review-round-5/final/frontend/e2e-ai.log` |
| 身份生成故障专项 | 5 项通过 | 0 | `review-round-5/final/identity-generation-tests.log` |
| RunDir 文件叶节点专项 | 14 项通过 | 0 | `review-round-5/final/runfile-tests.log` |
| RunDir/Junction 专项 | 6 项通过 | 0 | `review-round-5/final/rundir-tests.log` |
| 进程身份专项 | 7 项通过 | 0 | `review-round-5/final/process-identity-tests.log` |

后端 7 个 skip 仍为环境限制：5 个 Windows symlink 权限、1 个工具文件 symlink、1 个真实 Provider opt-in。

新增测试覆盖：

- 未配置 Key 状态、默认关闭；
- 保存 Key 后只返回脱敏状态；config 无 Key、secret 无明文；
- 环境变量 Key 与 DPAPI Key 区分；环境变量 Key + 自定义地址必须显式后端授权，换地址不继承旧授权；
- 配置损坏时模型调用/测试连接 fail-closed 返回 `config_invalid`，重新保存有效配置后恢复；
- 刷新/重开应用恢复设置；
- 保存 Key 不自动开网；关闭联网 AI 请求 503；
- 成功/失败（401）连接测试不泄露 Key，审计无 Key；
- 非法 base URL/model/key/冲突 422 且不回显 Key；
- 显式清除 Key；
- A0/A1/A2 门禁不被设置绕过；
- 设置失败不影响手动只读工具；
- data root 隔离；
- DPAPI 不可用时 fail-closed，不写明文；
- 前端显示/隐藏 Key、localStorage 无 Key、刷新恢复、网络默认关闭、错误连接提示、1440/390px 布局。

## 6. 真实后端 vs Mock

- **真实后端/DPAPI/SQLite/HTTP**：后端设置专项（TestClient + 真实 DPAPI 文件）、E2E 的设置保存/刷新/网络开关；
- **Mock Provider/Mock 路由**：AI 连接测试（`httpx.MockTransport`）；E2E 的测试连接成功/失败为浏览器路由替身；没有真实 DeepSeek 请求；
- 未使用真实 Key；测试 Key 仅用于证明加密存储/不泄露。

## 7. 修改文件与 diff

- 增量 diff（相对 P0 冻结候选）：`verification/p1-model-settings/incremental.diff`
- 完整 diff（相对仓库基准 `30eeed6`）：`verification/p1-model-settings/complete.diff`
- 修改文件清单：`docs/P1_MODEL_SETTINGS_FILES.md`
- SHA-256：`verification/p1-model-settings/SHA256SUMS`
- 原始退出码：`verification/p1-model-settings/EXIT-CODES-*.txt`

主要新增/修改：

- `backend/app/model_service.py`（DPAPI + 非敏感配置 + 联网开关）
- `backend/app/providers.py`（私有 inline key，不进入 ProviderConfig）
- `backend/app/ai_assistant.py`（设置感知 Provider/网络）
- `backend/app/model_calls.py`（环境变量 + 持久化开关）
- `backend/app/main.py`（settings/network 接口，设置感知状态/测试/AI）
- `backend/app/models.py`（settings 请求/响应模型）
- `backend/app/schema_cli.py`（契约生成）
- `frontend/src/components/settings/ModelServiceSettings.vue`
- `frontend/src/model-settings.ts`
- `frontend/src/App.vue`（独立设置入口，隐藏主工作区）
- `frontend/tests/model-settings.test.mjs`
- `frontend/tests/model-settings.spec.ts`
- `backend/tests/test_model_service_settings.py`
- `docs/MODEL_SERVICE_SETTINGS.md`
- `scripts/p1-start.ps1`、`scripts/p1-stop.ps1`、`scripts/p1-common.ps1`（独立端口/数据目录/身份校验进程记录）
- `scripts/verify-p1-guards.ps1`（DataDir 与停止脚本身份校验的可复现测试）
- `scripts/verify-p1-datadir.ps1`（Windows Junction/ReparsePoint/权限专项）
- `scripts/verify-p1-start-cleanup.ps1`（启动失败清理测试）
- `scripts/verify-p1-rundir.ps1`（RunDir Junction 专项）
- `scripts/verify-p1-process-identity.ps1`（进程身份 NORMAL/MISSING/UNKNOWN 专项）
- `scripts/verify-p1-r3-startup.ps1`（启动失败集成专项）
- `scripts/verify-p1-runfile.ps1`（RunDir 叶节点文件保护专项）
- `scripts/verify-p1-r4-startup.ps1`（R4 生命周期故障注入专项）
- `scripts/verify-p1-r5-identity.ps1`（R5 真实身份记录生成失败专项）
- `docs/P1_REVIEW_ROUND3_REPORT.md`（R3 安全收尾报告）
- `docs/P1_REVIEW_ROUND4_REPORT.md`（R4 最终复审整改报告）
- `docs/P1_REVIEW_ROUND5_REPORT.md`（R5 身份记录故障整改报告）
- `frontend/vite.p1.config.ts`、`frontend/scripts/capture-p1-screenshots.mjs`
- `docs/P1_INDEPENDENT_RUN_REPORT.md`（独立运行验收材料）
- `docs/P1_REVIEW_ROUND1_REPORT.md`（第一轮复审整改报告）

## 8. 未解决问题与安全边界

1. 单用户、回环、无认证；任何能访问回环端口的本机进程可能调用设置接口。没有多用户认证/租户隔离。
2. DPAPI 是 Windows 用户级保护，不是硬件密钥库；同一 Windows 用户下的恶意进程仍可能调用 DPAPI 解密。
3. 非 Windows 凭证存储未实现；当前部署为 Windows。
4. 测试连接要求先显式开启联网开关（与既有 `/api/model/test` 一致），没有提供“绕过联网开关的测试”。
5. 环境变量 `CTF_MODEL_NETWORK_ENABLED=true` 是运维覆盖；设置页开关不能覆盖它，只能显示该状态。
6. 真实 DeepSeek 联网/真实 Key/真实题目/Flag 未验证。
7. 设置页面重新加载后不会恢复 Key 明文（只恢复脱敏状态），符合设计。
8. 若整个 data root 被复制到另一 Windows 用户，DPAPI 无法解密 Key；状态显示不可读，不泄露。

## 9. 停止条件

P1 第一阶段只完成模型服务配置。**停止，等待独立审查。** 不提交、不推送、不合并；不进行真实联网测试。
