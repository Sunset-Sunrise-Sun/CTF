# 安全边界与数据处理

## 1. 部署模型

- 单用户、本地回环（`127.0.0.1`）工具，**没有多用户认证**。
- 任何能访问本机回环端口的进程都可能调用 API；不要把端口暴露到局域网/公网。
- `approving_user`/`confirmed_by` 等是审计标签，不是认证身份。
- 多用户隔离属于后续阶段；当前每个用户应使用自己的 Windows 账户和 data 目录。

## 2. API Key

- 用户自行配置 DeepSeek Key；项目不提供统一 Key。
- 非敏感设置：`model-service.json`，不含 Key。
- Key：`model-service.secret`，Windows DPAPI 加密，绑定当前 Windows 用户和固定 entropy。
- 设置响应只返回 `key_configured`/`key_source`/错误码，不返回完整 Key 或密文。
- Key 不进入前端 localStorage、事件、Writeup、ZIP、普通日志或设置页 HTML。
- 非 Windows 未实现凭证存储；保存 Key 会 fail-closed，不写明文。
- 同一 Windows 用户下的恶意进程仍可能调用 DPAPI 解密；这是用户级凭证边界。
- 环境变量 Key + 自定义 API 地址需要显式后端授权；地址变化后旧授权失效。

## 3. 模型联网

- 默认关闭。
- 保存 Key/配置不会自动开启联网。
- 有效联网 = 环境变量 `CTF_MODEL_NETWORK_ENABLED` 为真，或持久化开关为真。
- 关闭时 AI 对话和测试连接被拒绝。
- 测试连接只发送固定合成提示，不发送题目/附件/规则/对话。
- 本轮冻结验收未调用真实 DeepSeek；所有模型测试使用 Mock Provider/隔离路由。

## 4. 权限门禁

| 等级 | AI 对话 | 附件外发 | 工具申请 | 工具批准 | 工具执行 |
|---|---|---|---|---|---|
| unknown | 禁止 | 禁止 | 禁止 | 禁止 | 禁止 |
| A0 | 禁止 | 禁止 | 禁止 | 禁止 | 禁止 |
| A1 | 受限文字 | 禁止 | 禁止 | 禁止 | 禁止 |
| A2 | 允许 | 逐项确认 | 允许 | 每次人工批准 | approved 且未过期 |

- 题目等级由后端重新读取，设置 Key/开启联网不改变门禁。
- A2 降级后，已有申请/批准也不能执行。
- 跨题目确认、文件哈希变化、范围变化会被拒绝。

## 5. 工具系统

- 固定七个只读工具，不经过 Shell、不访问网络、不写题目工作区。
- AI 只能提出申请；批准和执行是两个独立人工步骤。
- 执行前重新校验参数哈希、路径边界、题目等级、过期时间。
- 路径越界、Junction/ReparsePoint、符号链接等 fail-closed。
- 工具输出写入内容寻址 Artifact；事件只保存摘要/哈希/Artifact 引用。
- 任意 shell/Python/网络/写文件执行未启用。

## 6. 数据与导出

- 数据目录由启动脚本隔离；默认 `.local-run-frozen\data`。
- A0/A1/A2 事件、模型审计和工具状态写入独立 SQLite。
- Writeup/ZIP 导出使用同一快照，披露模型调用、工具调用、Flag 摘要和完整性。
- Flag 只保存 SHA-256 前缀和长度，不保存明文；`platform_verified=false`。
- ZIP 包含 `SHA256SUMS`；缺少证据时标记 `incomplete`/`INCOMPLETE.txt`。
- 不导出 API Key；密钥文件不进入 Writeup/ZIP。

## 7. 运行与进程安全

- RunDir/关键文件检查 reparse point；PID、日志、run-info 的叶节点也检查。
- 启动/停止脚本验证可执行文件、命令行、启动时间、身份 token 和端口。
- 进程身份 UNKNOWN/MISMATCH 时拒绝终止，宁可保留进程等待人工核对。
- 启动失败使用 verified-handle 清理；身份记录失败保留原始 PID、原因和 `start-failure.json`。
- 不触碰现有业务服务；冻结启动使用 18110/15190。

## 8. 已知边界

- 路径检查与文件打开之间仍有理论并发替换窗口；抵御同机恶意并发替换需要目录句柄打开。
- DPAPI 是 Windows 用户级保护，不是硬件密钥库。
- 单用户回环无认证；不要把服务暴露到不可信网络。
- 真实 DeepSeek、真实比赛题目/Flag 未在本轮验证。
- 环境变量覆盖和设置页开关的优先级需按 `MODEL_API_SETUP.md` 理解。
