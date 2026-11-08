# AI 辅助解题（DeepSeek）接入

本功能在既有 Provider 基础设施上增加工作台业务入口，不启用工具执行器。

## 能力

- 通过 `POST /api/challenges/{cid}/ai/chat` 对当前题目进行多轮分析，并按 Crypto / Web / Pwn / Reverse / Misc 提供分类分析框架。
- 上下文包括题目描述、比赛 AI 政策摘要、最近 20 条事件，以及最多 12 个经过清单/事件绑定和 SHA-256 校验的文本导入文件或独立上传的文本证据。
- 仅读取白名单文本扩展名；单文本文件最多 32 KiB。对不超过 2 MiB 的 ELF/PE 等指定二进制，仅提取文件头元数据和最多 100 条可打印 ASCII 字符串，不发送二进制原文、不执行文件。总上下文最多约 180 KiB。
- 对上下文和用户问题执行常见 API Key、password、Bearer Token 格式脱敏。
- 每次请求必须由用户勾选数据外发确认；服务器还必须显式设置联网开关。
- 每次模型调用记录 `model_call` 状态事件；成功回答记录 `agent_message`，标记 `unverified_suggestion`。
- 不运行命令、不调用工具、不访问题目目标、不提交 Flag。人工执行仍由选手在工作台外完成并补录。

## 本机配置（Windows PowerShell）

在启动后端的同一个 PowerShell 会话中设置：

```powershell
$env:CTF_MODEL_NETWORK_ENABLED = "true"
$env:DEEPSEEK_API_KEY = "你的 DeepSeek API Key"
$env:CTF_MODEL_ID = "deepseek-chat"
$env:CTF_MODEL_API_KEY_ENV = "DEEPSEEK_API_KEY"
$env:CTF_MODEL_BASE_URL = "https://api.deepseek.com"
```

然后在该会话中启动后端。若后端由其他终端、IDE 或服务管理器启动，必须在那个进程的环境中配置变量。不要把 Key 写入仓库文件、命令历史、截图或题目材料。

关闭联网：

```powershell
Remove-Item Env:CTF_MODEL_NETWORK_ENABLED -ErrorAction SilentlyContinue
```

真实发送题目内容前，建议先用合成请求单独验证 API Key 与网络连通性：

```powershell
cd backend
python -m app.ai_smoke_cli --allow-model-network
```

该命令要求联网环境变量已开启，并再次要求显式命令行确认；只发送固定的合成 OK 提示，不发送题目内容，记录写入单独的 `model-smoke.sqlite3`，不打印模型回答。成功后再打开工作台使用 AI 面板。

配置通过 `GET /api/model/status` 查看。该接口只返回联网开关、模型 ID 和凭证是否存在，不返回 Key，也不代表真实 API 已经联通。首次请求才会进行真实 Provider 通信。

## 比赛规则

- `unknown` 和 `A0` 题目禁止调用 AI。
- `A1` / `A2` 仅表示题目配置允许进入 AI 辅助入口；仍须遵守项目规则摘要和比赛官方规则。
- 上传题目材料前确认自己有权将相关内容发送给所配置的模型服务。前端每次请求前都要求明确确认。

## 错误码

- `model_network_disabled`：服务端联网开关关闭。
- `missing_credentials`：找不到指定环境变量中的 Key。
- `ai_usage_not_permitted`：题目等级不允许 AI。
- `rate_limited`、`timeout`、`authentication`、`upstream_error`、`transport_error`、`invalid_response`：Provider 错误；不会自动重试。

## 自动化端到端检查

在已安装 Python 后端依赖、Node 依赖和 Playwright Chromium 的环境中，可从 `frontend` 目录运行：

```powershell
npm run test:e2e:ai
```

该专用测试会自动启动隔离的本地 FastAPI 与 Vite 服务，使用独立的 `.playwright-ai-data` 数据目录，并强制关闭模型联网；它验证 AI 面板、题目等级为 A2 时的 UI 展示、用户勾选数据外发确认，以及服务端未开启联网时的 503 拒绝。测试不会连接真实模型，也不会发送题目内容到外部服务。

## 验收边界

Mock 测试只验证业务门控、事件记录和脱敏；不等于真实 DeepSeek 网络验证。真实连通性需在用户自己的机器上设置合法凭证后，通过工作台发送合成题目测试。当前服务是无认证的本地单用户工作台，不应暴露到公网或不可信局域网。
