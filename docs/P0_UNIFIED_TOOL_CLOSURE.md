# P0 只读工具完整闭环记录

- 日期：2026-11-09
- 证据：`verification/evidence/transcript.json`（18 条真实 HTTP 请求）、`verification/evidence/results.json`、`verification/evidence/frontend/` 截图与日志
- 数据：全部为合成 ELF 样本与合成 Flag；未使用真实题目材料或真实 API Key

## 1. 闭环路径

```text
AI 对话（A2，可选工具申请）
  → model_call 审计记录（call_id）
  → tool_proposed（pending，model_call_id 关联）
  → 人工批准（approval_id，只改状态，不执行）
  → 人工执行（execution_id，claim running + tool_started）
  → 固定只读子进程读取 challenge workspace
  → 输出全文写入 ArtifactStore（artifact_added）
  → tool_finished（succeeded/failed/timed_out，artifact_ids）
  → 工具结果回灌下一轮 AI 上下文
  → Writeup/ZIP/ai_disclosure/manifest 同一快照披露
  → Flag 人工确认（仅摘要，platform_verified=false）
```

## 2. 真实 HTTP 验收实际记录（合成文件）

样本：51 字节合成 ELF 头 + `HTTP_ACCEPTANCE_TOOL_MARKER`；样本 SHA-256 `22e841aa803c3d366736e70cc72585f173736b58a81822509d8e1ec8b2361d26`。

| 步骤 | 实际结果 |
|---|---|
| `GET /api/health` | 200，`execution_enabled=false`，`read_only_tool_execution_enabled=true`，`tool_count=7`，`model_network_enabled=false` |
| `GET /api/tools` | 7 个固定只读工具 |
| `POST /tool-proposals`（路径穿越 `../outside.txt`） | 422 `path outside challenge workspace`，无状态/事件 |
| `POST /tool-proposals`（`file_inspect sample.bin`） | 201，`status=pending`，`model_call_id=null`（手工申请） |
| `GET /events`（批准前） | 仅 `tool_proposed`，无 `tool_started` |
| `POST /approve` | 200，`status=approved`，`approval_id` 非空，`execution_id=null` |
| `GET /events`（批准后） | `tool_proposed, tool_approved` |
| `POST /approve` 第二次 | 409 `Tool proposal is approved, not pending` |
| `POST /execute` | 200，`status=succeeded`，`execution_id`、`output_artifact_id`、`output_sha256` 非空 |
| `POST /execute` 第二次 | 409 `Tool proposal is succeeded, not approved` |
| `GET /artifacts/{aid}/content` | 200，字节 SHA-256 = `b294da710c44df7a2c5b452c638eb9c91002e71a188a1a8079bb9a2ea1290223` |
| 事件链 | `tool_proposed → tool_approved → tool_started → artifact_added → tool_finished` |
| `tool_finished` 追踪链 | `proposal_id → approval_id → execution_id → started_event_id/finished_event_id → artifact_ids=[aid]`，`output_sha256` 与下载一致 |
| A1 题目直接 `POST /tool-proposals` | 403 `ai_usage_not_permitted` |
| `POST /flag-confirmation` | 201，只保存 `flag_sha256`/`flag_length`/`confirmed_by`/`note`，`platform_verified=false`，明文不出现 |
| Writeup 预览 | `tool_proposal_count=1`、`tool_execution_count=1`，工具披露存在 |
| ZIP | manifest counts 1/1、`read_only_tool_execution_enabled=true`、`ai_disclosure.md` 含工具与 Flag 披露；`SHA256SUMS` 8 条覆盖全部交付文件 |

## 3. 前端真实后端闭环（E2E）

`frontend/tests/ai-assistant.spec.ts::a real read-only tool runs only after approval and a separate execute`：

- 真实隔离 FastAPI + Vite；
- 点击“批准”后事件链只有 `tool_proposed → tool_approved`，没有 `tool_started`；
- 点击“执行”后才出现 `tool_started`、`artifact_added`、`tool_finished`；
- 页面显示 success 及 Artifact 下载链接；
- 1440px/390px 截图保存于 `verification/evidence/frontend/`。

## 4. AI 申请关联闭环

`test_unified_p0.py::test_ai_proposal_is_linked_to_audit_and_requires_human_execution`：

- MockTransport 返回带 fenced `tool_proposals` 的 A2 回答；
- `model_call` 审计记录、`agent_message.call_id`、`tool_proposals[0].model_call_id`、`tool_proposed.model_call_id` 四者相同；
- `agent_message.tool_proposal_ids` 包含该 proposal；
- 回答本身不产生 `tool_started/tool_finished`；
- 人工批准/执行后 Artifact 可读取，Writeup/ZIP 计数与追踪字段一致；
- 第二次 execute 409，Provider 调用次数保持 1。

## 5. 故障态闭环

- `tool_started` 写失败：状态回滚 approved，不产生 started；
- `tool_finished` / `artifact_added` 写失败：最终事务回滚，重启恢复 running→failed（recovered=true）；
- 审计 finish 写失败：503，账本 unknown；
- `model_call` 事件写失败：503，账本 success 但无事件，导出标记 incomplete；
- 过期/拒绝/取消：均不执行，事件可审计。

## 6. 未完成/未执行

- 真实 DeepSeek 多轮工具申请：未执行（需真实 API Key、联网和明确授权）。
- 真实题目/真实 Flag/平台验证：未执行。
- 失败/超时 stderr Artifact：当前只存 error 文本，未实现。
- OS 级沙箱/容器隔离：未实现（应用层隔离 + 固定只读 runner）。
