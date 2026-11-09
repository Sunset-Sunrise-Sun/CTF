# AI 辅助解题（DeepSeek）接入

本功能在既有 Provider 基础设施上增加工作台业务入口。P0 统一整合后只启用**固定只读工具**，且必须由用户单独批准、再单独执行；任意 Shell/Python/网络/写执行仍禁用。统一架构见 `docs/P0_UNIFIED_ARCHITECTURE.md`，安全边界见 `docs/P0_UNIFIED_SECURITY_REPORT.md`。

## 能力

- 通过 `POST /api/challenges/{cid}/ai/chat` 对当前题目进行多轮分析，并按 Crypto / Web / Pwn / Reverse / Misc 提供分类分析框架。
- 工作台提供独立 API 连通测试：`POST /api/model/test`。用户点击后只发送固定的 `Reply with OK` 合成提示，不包含题目、附件、比赛规则或聊天记录；该测试与实际题目分析的数据外发确认相互独立。
- 文字上下文包含题目描述、规则摘要、用户选定的文字和同一授权范围内最近 10 轮对话。等级、证据选择或规则改变后，旧范围的对话不进入新请求。
- A2 可另行确认最多 12 个明确选中的文件。导入文件须通过清单和事件绑定检查。每份选中内容复核大小及 SHA-256。UTF-8 文本最多 32,000 字节。指定二进制最多 2 MiB，投影只包含头部信息和最多 100 条可打印字符串。
- 发送前检查完整 Provider 请求 JSON 的 UTF-8 长度，上限 180,000 字节。每条历史问题或回答投影最多 4,000 字节。缓冲响应上限 512 KiB。
- 对上下文和用户问题执行常见 API Key、password、Bearer Token 格式脱敏。
- 每次请求必须由用户勾选数据外发确认；服务器还必须显式设置联网开关。
- 外发确认与当前 Challenge 绑定：切换题目会立即清空确认和待发送问题；请求体必须携带 `consent_challenge_id` 且等于路径 `{cid}`，服务端不匹配返回 409；页面刷新或重新打开面板不会恢复其他题目的确认。AI 多轮历史仍按题目从事件恢复，不受确认清理影响。
- 模型调用的开始和终结写入独立 SQLite 账本。题目调用的 model_call 和成功后的 agent_message 共享调用 ID。回答标记为 unverified_suggestion。合成连通性测试不关联题目。
- 模型本身不运行命令、不直接调用工具、不访问题目目标、不提交 Flag。A2 下模型可提出最多 3 个只读工具申请，但只能进入 `pending`；必须由人工批准，再由人工执行；工具只读取当前题目 workspace。人工外部运行记录仍由选手补录。
- 回答采用证据优先流程：列出已知事实、最多三个有证据的假设、一个优先手动验证步骤、预期输出和需要回传的证据；缺少关键输入时先问一个聚焦问题，不虚构环境或验证结果。

## 本机配置（Windows PowerShell）

在启动后端的同一个 PowerShell 会话中设置：

```powershell
$env:CTF_MODEL_NETWORK_ENABLED = "true"
$env:DEEPSEEK_API_KEY = "你的 DeepSeek API Key"
$env:CTF_MODEL_ID = "deepseek-flash"
$env:CTF_MODEL_API_KEY_ENV = "DEEPSEEK_API_KEY"
$env:CTF_MODEL_BASE_URL = "https://api.deepseek.com"
```

然后在该会话中启动后端。若后端由其他终端、IDE 或服务管理器启动，必须在那个进程的环境中配置变量。不要把 Key 写入仓库文件、命令历史、截图或题目材料。

### 推荐：使用安全启动脚本（Windows）

不想把 Key 输入命令行或写入环境文件时，使用仓库提供的隐藏输入启动脚本：

```powershell
.\backend\start-ai-backend.ps1 -DataDir "C:\Users\<用户名>\Documents\Codex\CTF-MVP-A00-acceptance-8002-5174\data" -Port 8002
```

脚本会通过 `Read-Host -AsSecureString` 隐藏输入 API Key，仅在当前 PowerShell 进程及其后端子进程中设置环境变量；不会写入仓库、配置文件或用户级永久环境变量。脚本要求数据目录已存在、端口未被占用，并且只绑定 `127.0.0.1`。如果 8002 仍由旧后端占用，脚本会拒绝启动，不会自动停止任何进程。

前端在另一个 PowerShell 窗口启动，使用专门指向 8002 的 Vite 配置（不会沿用开发默认的 8000 代理）：

```powershell
Set-Location .\frontend
npm run dev -- --config vite.a00.config.ts --host 127.0.0.1 --port 5174 --strictPort
```

打开 `http://127.0.0.1:5174/`。该配置只绑定本机回环地址；若 5174 已被占用会直接失败，不会自动换端口。

关闭联网：

```powershell
Remove-Item Env:CTF_MODEL_NETWORK_ENABLED -ErrorAction SilentlyContinue
```

真实发送题目内容前，建议先用合成请求单独验证 API Key 与网络连通性：

```powershell
cd backend
$env:CTF_DATA_DIR = "C:\CTF-AI-Smoke-Isolated"
python -m app.ai_smoke_cli --allow-model-network
```

该命令要求联网环境变量已开启，并再次要求显式命令行确认；只发送固定的合成 OK 提示，不发送题目内容，记录写入独立目录下的 model-audit.sqlite3，CLI 仅输出调用 ID 和状态。旧 model_cli 采用同一策略。成功后再打开工作台使用 AI 面板。

配置通过 `GET /api/model/status` 查看。该接口只返回联网开关、模型 ID 和凭证是否存在，不返回 Key，也不代表真实 API 已经联通。点击 AI 面板中的“测试 API 连接”会调用 `POST /api/model/test`，在服务器联网开关与凭证均就绪时执行一次合成请求，成功才证明当前后端进程能够连接配置的 Provider。

## 比赛规则

- `unknown` 和 `A0` 题目禁止调用 AI。
- A1 只允许文字上下文，后端拒绝附件选择。A2 的附件选择默认为空。确认附件时绑定题目、所选对象和 SHA-256。
- 题目等级由比赛实际许可决定。工具申请和人工审批属于后续阶段。
- 上传题目材料前确认自己有权将相关内容发送给所配置的模型服务。前端每次请求前都要求明确确认。

## P0 调用与审计契约

AI chat 保留 question、consent_challenge_id、confirm_external_processing。可选 selected_texts 包含用户主动选定的文字。A2 选中的导入文件通过 selected_files（每项 import_id、relative_path、sha256）传递。独立证据通过 selected_artifacts（每项 artifact_id、sha256）传递。任何附件选择均要求 confirm_attachments 为 true。前端发送后消耗确认，问题、选题或附件范围变更时清空确认。响应新增 call_id。

GET /api/model/calls 返回本数据目录的审计元数据。字段包括调用 ID、关联题目、Provider、模型、用途、范围、开始/结束时间、状态、错误类别和可取得的 token 计数。首次调用时创建独立 model-audit.sqlite3。只有开始记录的调用显示 unknown。题目事件在账本终结后关联，两个存储之间出现故障时，缺少关联的档案标为不完整。账本没有外部签名。

Writeup 初稿、ZIP 的 ai_disclosure.md 和 manifest.json.model_calls 使用同一导出快照。系统合成连接调用与题目调用分别统计。人工稿保留原字节。

## 错误码

- attachments_not_permitted（403）、attachment_confirmation_required（400）、unsupported_evidence（422）表示附件门禁。
- evidence_selection_changed、context_integrity_error（409）表示选择失效或证据校验失败。
- context_limit_exceeded（413）、response_limit_exceeded（502）表示请求或响应超出预算。
- audit_unavailable（503）表示审计不可用。已有开始记录而终结失败时保留 unknown。

- `model_network_disabled`：服务端联网开关关闭。
- `missing_credentials`：找不到指定环境变量中的 Key。
- `ai_usage_not_permitted`：题目等级不允许 AI。
- `409`：外发确认不属于请求路径中的题目（`consent_challenge_id` 与 `{cid}` 不一致），或上下文完整性校验失败。
- `rate_limited`、`timeout`、`authentication`、`upstream_error`、`transport_error`、`invalid_response`：Provider 错误；不会自动重试。

## 自动化端到端检查

在已安装 Python 后端依赖、Node 依赖和 Playwright Chromium 的环境中，可从 `frontend` 目录运行：

```powershell
npm run test:e2e:ai
```

该专用测试会自动启动隔离的本地 FastAPI 与 Vite 服务，使用独立端口 `18002` / `15174`，并为每次运行生成独立数据目录；启动时拒绝复用已有服务，避免误连本机其他 CTF 服务或写入其数据。模型联网强制关闭；测试验证 AI 面板、题目等级为 A2 时的 UI 展示、用户勾选数据外发确认、服务端未开启联网时的 503 拒绝、切换题目/刷新后确认与问题清空、A→B→A 不恢复旧确认、B 题重新确认后可发送、按题目恢复历史，以及服务端拒绝属于其他题目的确认。测试不会连接真实模型，也不会发送题目内容到外部服务。

## 验收边界

Mock 测试只验证业务门控、事件记录和脱敏；不等于真实 DeepSeek 网络验证。真实连通性需在用户自己的机器上设置合法凭证后，通过工作台发送合成题目测试。当前服务是无认证的本地单用户工作台，不应暴露到公网或不可信局域网。
