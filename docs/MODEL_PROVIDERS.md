# Model Provider Interface

实现位于 backend/app/providers.py。业务只依赖 ModelProvider：
`complete(ModelRequest) -> ModelResponse`、`stream(ModelRequest) -> AsyncIterator[StreamChunk]`。
统一消息包含 role/content；工具描述包含 name/description/parameters(JSON Schema)；返回工具调用包含 call_id/name/arguments。
流式片段的 text 可展示，只有最终 response 中完整且可解析的 tool_calls 能转换提案。
P0.1：转换的 ToolProposal.call_id 保留原始 ToolCall.call_id，proposal_id 仍为独立审批标识。call_id 可为空以兼容非模型来源提案及旧数据，模型转换路径始终赋值。
`proposals(response, challenge_id, scope)` 转换为统一 ToolProposal；Provider 不持有执行器，不执行系统命令。

| Adapter | 当前实现 |
|---|---|
| OpenAI-Compatible | 可运行 Chat Completions HTTP/SSE |
| OpenAI | 同一 Chat Completions 协议，独立配置 |
| DeepSeek | 同一 Chat Completions 协议，独立配置 |
| Anthropic | native Messages 接口骨架，明确拒绝调用 |

不宣称支持所有兼容服务；capabilities.streaming/tool_calling/structured_output 默认 false，按具体服务和模型显式配置。
请求不支持能力默认抛 unsupported_capability；仅 allow_degrade=true 时省略不支持工具/schema并返回 degraded_features。流式降级为一次 complete 返回最终 response。降级文本不能自动执行，Structured Output 降级后由调用方按需验证 schema。
OpenAI/DeepSeek 也不自动假定每个模型支持全部能力。原生 Responses API 和 Anthropic 的实现后续添加，无须修改业务契约。

## 配置与切换
复制 backend/config/providers.example.json 为 providers.local.json（gitignored）；修改独立 provider_id/adapter/base_url/model_id/api_key_env 和能力。
JSON 只记录环境变量名称，不含 Key。`ProviderRegistry.from_file(path)` 载入，`select(provider_id)` 切换，重复/未知 ID 拒绝。
API Key 通过对应环境变量传入，不输出到模型日志。只在用户配置并显式允许时连接模型服务；模型通信权限不授予题目目标网络权限。
OpenAI-Compatible base_url 可以指向本地服务；支持 HTTP 的原因是本地模型，远程服务应使用 HTTPS。禁用自动重定向，避免凭证转发。

在 backend 目录运行旧 model_cli 或新 ai_smoke_cli 时，设置 CTF_MODEL_NETWORK_ENABLED=true 和独立绝对 CTF_DATA_DIR，并传入 --allow-model-network。旧命令保留配置文件及 --provider 参数。两个入口均发送固定合成提示，使用隔离临时目录，并输出调用 ID。

工作台和 CLI 均使用 audited_complete，在发出请求前记录开始，在返回前记录终结。远程端点使用 HTTPS，本机回环服务允许 HTTP。审计记录调用 ID、用途、Provider、模型、时间、状态和可取得的 token 计数。P0.1 recorded_complete 保留原接口和旧事件格式。流式生产审计仍为独立阶段。

统一异常 ProviderError.code：missing_credentials、unsupported_capability、timeout、rate_limited（保留 Retry-After）、authentication、upstream_error、transport_error、invalid_response、adapter_not_implemented。
不自动重试，避免隐式重复计费与重复工具提案；调用方可按 Retry-After 决定重试。超时可配置，取消由 asyncio 向上传递。异常不包含 upstream body 或凭证。

## 真实 Provider 验证
需要合法凭证。设置 CTF_RUN_LIVE_MODEL=1、CTF_MODEL_NETWORK_ENABLED=true、独立绝对 CTF_DATA_DIR 和 CTF_LIVE_PROVIDER_CONFIG（单个 ProviderConfig JSON，仅含 API Key 环境变量名称），运行 `python -m pytest -q tests/test_providers.py -k live`。
本次默认跳过；Mock 测试验证协议、流式聚合、错误、能力降级、切换和 Anthropic 明确失败，不代替真实 Provider 联通性测试。
