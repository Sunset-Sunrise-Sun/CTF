# P0 统一安全报告

- 日期：2026-11-09
- 分支：`feat/p0-unified-ai-tools`；基准 `30eeed6`
- 结论：P0 候选，安全门禁与审计已统一；**未进行真实联网/真实题目验收**，不宣称生产可用或平台验证通过。
- 本地单用户边界：服务仅回环、无认证/授权；`approving_user` 是本地声明而非可信身份。多用户配置隔离属于后续阶段，未实现。

## 1. 权限矩阵落实位置

| 能力 | 后端强制点 | 测试 |
|---|---|---|
| AI 对话 | `main.ai_chat` → `model_calls_allowed`；`ask_challenge` 再次检查；`model_calls.audited_complete` 联网开关 | `test_ai_p0.py`、`test_unified_p0.py` |
| 附件外发 | `collect_challenge_context`：A2-only + `confirm_attachments` + 逐项绑定/重读/哈希 | `test_ai_p0.py`、E2E A2 |
| 工具申请 | HTTP 端点 `require_tool_policy` + `ToolService.propose` 内部 A2 检查 | `test_tools.py` A0/A1/降级 |
| 工具批准 | HTTP 端点 + `ToolService.approve` 重新读取当前等级 | `test_tools.py` downgrade |
| 工具执行 | HTTP 端点 + `ToolService.execute` 重新读取当前等级、状态、过期、参数哈希 | `test_tools.py`、HTTP acceptance |
| 工具拒绝/取消 | A1 允许清理；unknown/A0 拒绝；不触发执行 | `test_tools.py` |
| Flag | 仅人工确认接口；只保存 SHA-256/长度；`platform_verified=false` | `test_flag`/`test_unified_p0.py` |
| CLI | 显式 `--allow-model-network` + `CTF_MODEL_NETWORK_ENABLED`；绝对独立目录；拒绝工作台数据根；固定合成提示 | `test_ai_p0.py` |

直接 HTTP 请求不能绕过：所有端点都从存储读取题目等级；工具服务内部再检查一次；前端隐藏按钮不构成安全边界。

## 2. 工具攻击面

- 固定七工具白名单；未知工具/参数/类型/枚举/越界/未知键均 422；
- 路径：拒绝绝对路径、盘符、`..`、冒号、NUL、设备名、末尾点/空格、符号链接/Windows reparse point；申请时与 runner 执行前双重校验；
- runner：固定 `[python,-I,-B,tool_runner.py]`、`shell=False`、最小环境、15 s 超时、64 KiB 输出/256 KiB stdout 上限、进程内并发信号量；
- 无 shell、python、curl、写、删除、安装、任意代码工具；无网络工具；
- 输出全文进内容寻址 ArtifactStore；成功执行必须在 `tool_finished` 中带 `output_artifact_id`/`artifact_ids`；
- 参数篡改：`arguments_sha256` + `approved_arguments_sha256` 在 execute 前重算；不一致原子标记 `expired` 并写 `tool_expired`，409。

## 3. 状态与审计一致性

- 每个工具状态转换（propose/approve/reject/cancel/expire/claim/finalize）与对应事件在同一 `BEGIN IMMEDIATE` 事务提交；
- 执行子进程不在事务内；最终事务同时写 `artifact_added`、`tool_finished` 和状态行；
- 崩溃恢复：启动时 `running → failed`（`interrupted_during_execution`，`recovered=true`）并写 `tool_finished`；过期 pending/approved 被 sweep 为 `expired`；
- 模型审计：独立追加式 SQLite，先写 start 再发请求，finish 失败保持 `unknown`；无第二套 `model_calls` 表；
- 故障注入 6/6 通过（见 `P0_UNIFIED_TEST_REPORT.md` 第 6 节）。

## 4. 披露完整性

- 模型调用只从独立账本读取；成功但回答未入事件时 `delivery_status=not_recorded`；
- 工具 9 种状态全部披露；统计基于同一 proposal 快照；
- Flag 只显示 SHA-256 前缀/长度/确认人/时间，明确 `platform_verified=false`；没有平台验证截图仍标记缺失；
- ZIP 内 `writeup.md`、`writeup_generated.md`、`ai_disclosure.md`、`manifest.json`、`logs/*`、`SHA256SUMS` 同一快照；人工 Writeup 原字节不重写；
- 缺少必要记录（审计 unknown、回答未入事件、成功工具缺 Artifact、running、事件链无效）标记 `incomplete`，不冒充成功。

## 5. 密钥/敏感数据

- API Key 只从环境变量读取；`/api/model/status` 只返回 `credentials_configured` 布尔与脱敏 model id；
- 审计账本不保存 prompt/回答/密钥；错误只保存白名单错误码；
- 日志/事件/错误/导出不包含 Key；测试用合成 sentinel 验证 `/api/model/status`、`/api/model/calls`、事件、Writeup 预览、ZIP 均不出现；
- 真实 Key 未读取、未复制、未使用。

## 6. 明确残余风险

1. 单用户、无认证；任何能访问回环服务的本地进程都能调用批准接口（`approving_user` 可伪造）。生产前必须增加可信人工审批身份/本机 Origin/CSRF 边界。
2. 工具隔离是应用层路径检查 + 只读 runner，没有 OS 沙箱/网络命名空间；TOCTOU 窗口不能完全消除；建议后续使用容器/低权限账户。
3. 运行器脚本可被同机用户直接调用并传入任意 root（本地文件读能力本来就存在）；不构成远程越权，但不是强隔离。
4. 符号链接逃逸用例在无权限环境 skip；junction/reparse 已通过；需在有权限环境补测。
5. 工具失败/超时仅记录 error 文本，不保存 stderr Artifact；成功执行必须有 Artifact。
6. 工具输出按内容寻址去重：相同输出不重复写 `artifact_added`，但元数据/链接完整。
7. 审计账本依赖本机文件系统权限与 SQLite 约束，无外部签名；本机管理员可篡改。
8. 模型调用与工具状态跨两个 SQLite 文件：无法做跨库原子事务；通过 call_id 关联、失败标记 incomplete 与启动恢复保证“不冒充成功”，但不能保证跨库同时可见。
9. 前端 E2E 使用系统 Edge；bundled Chromium 未验证。
10. 真实 DeepSeek 联网、真实题目/Flag/平台验证未执行，等待后续明确授权。

## 7. 安全验收结论

- 后端权限矩阵、附件授权、工具生命周期、审计恢复、Artifact 完整性、Writeup/ZIP 披露、CLI 隔离、Key 泄漏检查均有自动化覆盖并通过。
- **不声称独立验收通过**；本候选等待独立审查者复核代码、测试与证据后决定是否进入 P1/真实环境验收。
