# DeepSeek API 配置指南

## 1. 自己的 Key，不是统一 Key

本项目不附带 API Key，也不需要开发者提供统一 Key。每位用户在**自己的 Windows 用户**下配置自己的 DeepSeek Key。Key 仅保存在本机后端，不进入前端 localStorage、事件、Writeup、ZIP 或普通日志。

## 2. 准备

1. 在 DeepSeek 官方平台注册并创建 API Key。
2. 确认账号/地区/计费与使用条款适用于你。
3. 不需要把 Key 写进任何源码、`.env`、项目文件或聊天消息。
4. 本项目冻结验收不调用真实 API；真实使用前请自行确认 Key 和网络。

## 3. 在设置页配置

1. 启动工作台，点击右上角「模型服务设置」。
2. 服务商固定为 DeepSeek。
3. API 地址默认 `https://api.deepseek.com`；没有特殊代理时保持默认。
4. 模型默认显示 `DeepSeek-V4.1-Flash`，对应官方 API model ID `deepseek-flash`；也可手动填写其他可用模型名称/ID。后端会使用解析后的官方 API ID 发送 Provider 请求。
5. 在 API Key 输入框粘贴 Key；可用「显示/隐藏」检查，但不要截图或分享。
6. 点击「保存配置」。保存后输入框清空，状态显示「已保存在本机（Windows DPAPI 加密）」。
7. 页面会显示安全提示：「API Key 将发送至当前填写的 API 地址，请确认该地址属于你信任的服务商。」

## 4. 模型名称解析

- `DeepSeek-V4.1-Flash` → 官方 API ID `deepseek-flash`
- `DeepSeek-V4-Pro` → 官方 API ID `deepseek-v4-pro`
- 其他有效自定义 ID（例如 `deepseek-chat`）保持原值，不擅自改写
- 空模型字段使用默认 `DeepSeek-V4.1-Flash`（API ID `deepseek-flash`）
- 环境变量 `CTF_MODEL_ID` 与设置页面使用同一解析规则；设置页面保存的配置优先于环境变量模型值（不改变原有 Key/联网优先级）

## 5. 联网开关

- 默认关闭。
- 保存 Key/配置**不会**自动开启联网。
- 需要模型调用时，勾选「允许联网调用模型」并点击「保存联网开关」。
- 关闭联网时，AI 对话和测试连接都会被拒绝。
- 环境变量 `CTF_MODEL_NETWORK_ENABLED=true` 是运维覆盖，页面不能关闭它。

## 5. 测试连接

1. 先开启联网开关。
2. 点击「测试连接」。
3. 只发送固定合成提示，不发送题目、附件、规则或聊天记录。
4. 成功只表示网络/凭证/模型连通性；不代表题目外发授权或平台验证。
5. 失败时页面只显示安全错误信息，不显示 Key。

## 6. 自定义 API 地址和环境变量 Key

- 使用 DPAPI 保存的 Key 时，地址由你在设置页填写并保存。
- 如果使用服务器环境变量 Key，且 API 地址不是默认 `https://api.deepseek.com`：
  - 设置页要求明确勾选授权；
  - 后端把授权绑定到该精确地址；
  - 修改地址会清除旧授权，必须重新授权；
  - 未授权时模型调用/测试连接返回 403，不发起网络请求。
- 默认 DeepSeek 地址使用环境变量 Key 不需要额外授权。

## 7. 凭证存储边界

- 非敏感配置：`<data_root>/model-service.json`，不含 Key。
- Key：`<data_root>/model-service.secret`，Windows DPAPI 加密，绑定当前 Windows 用户。
- 其他 Windows 用户无法解密；同一 Windows 用户下的恶意进程仍可能调用 DPAPI，这是平台边界。
- 非 Windows 系统未实现凭证存储；保存 Key 会 fail-closed，不会退化为明文。
- 不同用户应使用各自的 data 目录。

## 8. 常见错误

| 现象 | 处理 |
|---|---|
| 保存 Key 返回 503 credential_store_unavailable | 当前系统 DPAPI 不可用；不会保存明文 |
| 已保存 Key 无法读取 | 可能由其他 Windows 用户保存；用当前用户重新配置 |
| 测试连接 403 env_key_custom_base_url_not_authorized | 环境变量 Key + 自定义地址需要显式授权 |
| 测试连接 503 config_invalid | 配置文件损坏；重新保存有效配置 |
| 测试连接 503 model_network_disabled | 先显式开启联网开关 |
| 测试连接 503 missing_credentials | 尚未配置 Key |
