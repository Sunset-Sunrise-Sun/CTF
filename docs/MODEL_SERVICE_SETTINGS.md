# 模型服务设置（P1 第一阶段）

- 日期：2026-11-09
- 基准：`D:\CTF-worktrees\p1-settings`（从 P0 冻结候选重建）
- 分支：`feat/p1-model-settings`
- 状态：未提交、未推送、未合并；等待独立审查
- 范围：仅模型服务配置页面与后端设置/凭证/联网开关；不扩展其他功能

## 1. 用户能力

工作台顶部「模型服务设置」打开独立设置页，不进入主要解题工作区：

- 服务商：固定 DeepSeek（显示为只读）；
- API 地址：默认 `https://api.deepseek.com`，可配置；地址输入框下方提示「API Key 将发送至当前填写的 API 地址，请确认该地址属于你信任的服务商。」
- API Key：密码输入框，支持显示/隐藏；保存后输入框清空；
- 模型：默认显示 `DeepSeek-V4.1-Flash`（官方 API model ID `deepseek-flash`），可手动配置；后端 Provider 使用解析后的官方 ID；
- 联网调用：默认关闭，必须显式保存开关；
- 保存配置、测试连接、连接状态与错误原因；
- 清除已保存 Key（显式操作）。

页面不把配置写进 localStorage，也不在页面/HTML 中保存或回显 Key。

## 2. 后端 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/model/settings` | 返回非敏感配置状态：base_url、model_id、`key_configured`、`key_source`、`key_storage_available`、`key_error`、`network_enabled`、`network_setting`、`network_env_override`、`config_error` |
| PUT | `/api/model/settings` | 保存 `base_url`、`model_id`、可选 `api_key`，或 `clear_api_key=true`；可用 `authorize_env_key_custom_base_url=true` 显式授权环境变量 Key 发送到当前自定义地址；响应永远不含 Key；不会自动开启联网 |
| PUT | `/api/model/network` | 单独修改持久化联网开关；响应为设置状态 |
| POST | `/api/model/test` | 现有合成连接测试；使用当前设置中的 Provider/Key；固定 `Reply with OK` 合成提示；需要 `confirm_synthetic_request=true`，且当前联网有效状态为开启 |
| GET | `/api/model/status` | 摘要状态；`credentials_configured` 为布尔，不返回 Key |

`README`、`docs/openapi.json`、`docs/contracts.json` 同步生成。

### 请求校验

- `base_url`：HTTPS；或仅回环 `http://localhost/127.0.0.1/[::1]`；拒绝 userinfo、query、fragment、控制字符；
- `model_id`：1..128，字符集 `[A-Za-z0-9._:/-]`；
- `api_key`：8..512 字符，拒绝换行/NUL；请求校验错误不会回显 Key；
- `api_key` 与 `clear_api_key=true` 同时出现返回 422；
- 不因保存 Key 而修改 `network_enabled`；
- 环境变量 Key + 非默认 DeepSeek 地址时，授权只对**该精确 base URL** 有效；修改地址会清除旧授权，必须重新显式授权；未授权时模型调用/测试连接在后端拒绝（403 `env_key_custom_base_url_not_authorized`）；
- DPAPI 保存的 Key 与 API 地址绑定由用户主动保存，不需要环境变量授权；
- 默认 DeepSeek 地址使用环境变量 Key 不需要额外授权。

## 3. 凭证存储

### 3.1 非敏感配置

`<data_root>/model-service.json`：

```json
{
  "schema": "ctf-workbench-model-service/1",
  "base_url": "https://api.deepseek.com",
  "model_id": "deepseek-flash",
  "network_enabled": false
}
```

不包含 API Key。

### 3.2 API Key：Windows DPAPI

`<data_root>/model-service.secret`：

- 内容为 magic `CTFW-DPAPI-1\n` + `CryptProtectData` 输出；
- 使用当前 Windows 用户作用域 + 固定 entropy；**其他 Windows 用户无法解密**；
- 不写入 SQLite、事件、Writeup、ZIP、普通日志或前端；
- 保存/读取均在后端进程内；`ProviderConfig` 不包含 Key 字段；
- 读取时使用 `CryptUnprotectData`；解密失败返回 `credential_store_error`，状态显示 Key 不可用，不泄露密文或明文；
- 本机其他进程以同一 Windows 用户运行时可调用相同 DPAPI 解密（这是 Windows 用户级凭证的边界）。

### 3.3 其他操作系统

当前部署为 Windows。非 Windows 上 `key_storage_available=false`，保存 Key 返回 503 `credential_store_unavailable`，不会退化为明文文件。若未来支持 Linux/macOS，应接入该平台的 Secret Service/Keychain 或明确提供加密密钥管理方案后再实现。

### 3.4 环境变量 Key 与自定义地址

- `DEEPSEEK_API_KEY`（或兼容环境变量）与 DPAPI 保存的 Key 在状态中通过 `key_source` 区分：`settings` / `environment` / `null`。
- 当使用环境变量 Key 且 `base_url` 不是 `https://api.deepseek.com` 时：
  - 必须由用户在设置页勾选授权，并随 `PUT /api/model/settings` 发送 `authorize_env_key_custom_base_url=true`；
  - 后端把授权绑定到该精确 base URL（`env_key_authorized_base_url`）；
  - 修改 base URL 时旧授权自动失效，不能静默把已有环境变量 Key 发往新地址；
  - 未授权时 `provider_values()` 抛出 `env_key_custom_base_url_not_authorized`，模型调用/测试连接返回 403，不发出网络请求。
- 状态返回 `env_key_custom_base_url_authorized` 和 `env_key_custom_base_url_authorization_required`，不返回 Key 或授权值。
- 环境变量完全未配置时，设置页只显示未配置状态。

### 3.5 模型名称解析

- 显示名 `DeepSeek-V4.1-Flash` 对应官方 API ID `deepseek-flash`；
- `DeepSeek-V4-Pro` 对应 `deepseek-v4-pro`；
- 未知但合法的自定义 ID（如 `deepseek-chat`）保持原值；
- 空字段使用默认模型；
- 环境变量 `CTF_MODEL_ID` 与设置页面共用同一后端解析规则，Provider 始终发送解析后的 API ID；设置页面保存的配置优先于环境变量模型值。

### 3.6 配置损坏 fail-closed

- `model-service.json` 不存在或合法但字段错误时：缺失文件使用安全默认值；内容损坏/类型错误/非法 URL 等将 `config_error=invalid_config`。
- `config_error` 非空时：
  - `snapshot.config_error` 可见；
  - `/api/model/test`、AI 对话、`build_deepseek_provider(settings)` 在联网检查前返回 `config_invalid`（HTTP 503），不调用 Provider；
  - 不会静默使用默认配置 + 环境变量 Key 继续联网。
- 用户通过设置页重新保存有效配置（成功 200）后 `config_error` 清空，模型调用/测试连接恢复；损坏文件不会被自动删除。
- 环境变量 `CTF_MODEL_NETWORK_ENABLED=true` 也不能绕过损坏配置的拒绝。

### 3.7 每个用户独立

配置和密文位于该安装的 data root 下，并使用当前 Windows 用户 DPAPI。不同用户使用各自 data root 和各自 Windows 登录会话即可独立配置；同一 data root 被其他 Windows 用户打开时，无法解密 Key，状态会显示不可读，不会泄露。

## 4. 联网开关

- 初始默认关闭；保存 API 配置不改变开关。
- 有效联网状态 = 环境变量 `CTF_MODEL_NETWORK_ENABLED` 为真，或持久化 `network_enabled=true`。
- 环境变量仍作为运维/CLI 级覆盖；设置页会显示 `network_env_override=true`，不能通过页面关闭该环境变量导致的开启。
- AI 对话、`/api/model/test` 都检查有效联网状态；关闭时返回 503 `model_network_disabled`，不调用 Provider。
- A0/A1/A2 权限门禁保持原实现：设置 Key 或开启联网不改变题目等级门禁。

## 5. 安全边界

1. 单用户、回环服务、无认证；任何能访问该回环端口的本机进程都可能调用设置接口，`approving_user` 不是认证身份。
2. DPAPI 是 Windows 用户级保护，不是硬件密钥库；同一 Windows 用户下的恶意进程仍可能调用 DPAPI 解密。
3. 没有多用户认证/租户隔离；不同用户应各自运行自己的 data root。
4. API Key 会出现在发往配置 Provider 的 HTTPS Authorization 头中；不会出现在应用事件、ZIP、普通日志、前端 localStorage 或设置响应。
5. 测试连接只发送固定合成提示；不会发送题目/附件/规则/对话。测试连接仍受联网开关和显式确认约束。
6. 设置页错误信息只映射安全错误码，不包含 Key。
7. 不进行真实 DeepSeek 联网验证；本轮使用 MockTransport/Mock 路由。

## 6. 测试

后端：`backend/tests/test_model_service_settings.py`（13 项）：

- 初始未配置、网络关闭；
- 保存 Key 只返回脱敏状态；config 不含 Key、secret 不含明文；
- 重开应用恢复配置；
- 保存 Key 不自动开网；网络关闭时 AI 503；开启后 Mock Provider 调用成功；
- 成功/失败（401）连接测试不泄露 Key；审计无 Key；
- 网络开关独立持久化；
- 非法 base URL/model/key/冲突 422 且不回显 Key；
- 清除 Key；
- A0/A1/A2 门禁不被设置绕过；
- 设置失败不影响手动只读工具；
- data root 隔离；
- DPAPI 不可用时 fail-closed，不写明文。

前端：`frontend/tests/model-settings.test.mjs` 纯函数测试；`frontend/tests/model-settings.spec.ts` E2E 覆盖显示/隐藏、保存、脱敏、网络默认关闭、刷新恢复、Mock 连接成功/失败、1440/390px 布局、localStorage 无 Key。

## 7. 未解决/后续

- 真实 DeepSeek 联网、真实 Key、真实比赛题目/Flag 未执行；
- 多用户认证/租户隔离未实现，属于后续阶段；
- 非 Windows 凭证存储未实现；
- 测试连接要求先显式开启联网开关（与现有 `/api/model/test` 行为一致），未做成“绕过联网开关的测试”；
- Windows DPAPI 的同一用户恶意进程风险是平台边界，非本应用可完全消除。
