# P0 统一整合设计（工作文档）

状态：实现中，交付前冻结。基准 HEAD：`30eeed6dcc180ae21b5648f25047c5889e3c434a`（PR #9）。
本文件定义 Codex P0 与 DeepSeek 工具系统合并后的唯一事实来源、接口和事务边界。

## 1. 唯一事实来源

| 数据 | 存储 | 说明 |
|---|---|---|
| 题目、事件哈希链、证据 Artifact、导入、Writeup 人工稿 | `workbench.sqlite3` | 迁移 001/002 不变；新增 `003_tool_approvals.sql`。 |
| 模型调用审计 | `model-audit.sqlite3` | Codex P0 的 `ModelCallJournal`，`call_starts`/`call_finishes` 只追加。HTTP 解题、`/api/model/test`、两个 CLI 共用。 |
| 工具输出全文 | 内容寻址 ArtifactStore | 不再只依赖事件中的截断文本；事件和 proposal 记录 `output_artifact_id`。 |
| 工具申请/批准/执行状态 | `workbench.sqlite3.tool_proposals` | 与工具事件在同一 SQLite 事务中提交。 |

不保留第二套模型审计表：不创建 `model_calls`（迁移 003 旧版）表；`Store` 不提供模型调用审计方法。所有模型调用事实只从 `ModelCallJournal` 读取，`model_call` 题目事件只作为关联/交付证据。

## 2. AI 请求契约（唯一）

`POST /api/challenges/{cid}/ai/chat` 请求体：

```json
{
  "question": "...",
  "confirm_external_processing": true,
  "consent_challenge_id": "<cid>",
  "selected_texts": ["..."],
  "selected_files": [{"import_id": "...", "relative_path": "...", "sha256": "..."}],
  "selected_artifacts": [{"artifact_id": "...", "sha256": "..."}],
  "confirm_attachments": false
}
```

安全规则（全部在后端执行，与前端隐藏无关）：

1. `consent_challenge_id` 必须等于路径 `{cid}`，否则 409。
2. `unknown`/`A0`：拒绝 AI 调用和所有工具接口；`A1`：只允许文字，附件和工具申请一律拒绝；`A2`：允许，但附件必须逐项选择并额外 `confirm_attachments=true`。
3. 附件发送前按 `import_id/relative_path` 重新绑定 manifest、重新读取文件、核对大小与 SHA-256；跨题目文件返回 409/403。
4. 请求 JSON 上限 180,000 UTF-8 字节；响应缓冲上限 512 KiB；不自动收集附件。
5. 返回 `call_id`；成功回答写入 `agent_message` 事件，失败/未终结写入审计账本并保持 `unknown`。跨题目切换清除确认、即时问题和旧异步响应。

## 3. 权限矩阵

| 等级 | AI 对话 | 附件外发 | 工具申请 | 工具批准 | 工具执行 |
|---|---|---|---|---|---|
| unknown | 禁止 | 禁止 | 禁止 | 禁止 | 禁止 |
| A0 | 禁止 | 禁止 | 禁止 | 禁止 | 禁止 |
| A1 | 受限文字 | 禁止 | 禁止 | 禁止 | 禁止 |
| A2 | 允许 | 逐项确认 | 允许 | 每次人工批准 | 仅 approved 且未过期 |

`ToolService` 内部和 HTTP 端点都检查等级；等级在申请后降级时，批准/执行仍拒绝。

## 4. 工具注册表（固定七项）

`file_inspect`、`sha256`、`stat`、`strings`、`list_files`、`image_info`、`text_decode`。全部 `read_only=true`、`requires_approval=true`。

约束：严格参数 Schema；workspace 相对路径；拒绝绝对路径、盘符、`..`、冒号路径、符号链接/重解析点逃逸；申请时和 runner 执行前各自校验；固定 subprocess `[python, -I, -B, tool_runner.py]`、`shell=False`、最小环境、15 秒超时、输出上限、并发信号量；无任意 Shell/Python/网络/写工具。

## 5. 工具表与追踪链

`tool_proposals` 列：

```text
proposal_id PK, challenge_id, model_call_id, tool_name,
arguments_json, arguments_sha256, reason, risk_level, status,
proposed_by, proposed_at, expires_at,
approval_id UNIQUE, approved_by, approved_at, approved_arguments_sha256, decision_note,
execution_id UNIQUE, started_at, finished_at,
started_event_id, finished_event_id,
output_artifact_id, output_sha256, output_size, output_summary, error
```

状态机：

```text
pending -> approved -> running -> succeeded
   |          |          |-----> failed
   |          |          |-----> timed_out
   |          |-----> expired (未执行前超时/参数校验失败)
   |-----> rejected
   |-----> cancelled
   |-----> expired
```

规则：

- AI 申请必须带 `model_call_id`，且该调用属于同一题目；手工申请可为空。
- 每次批准生成唯一 `approval_id` 和 `approved_arguments_sha256`；参数变化必须重新申请/批准；执行只使用库中已批准参数，客户端不能覆盖。
- 重复批准/重复执行返回 409；过期申请不能执行；AI 不能调用批准接口（批准只来自用户动作；本地单用户部署边界见文档）。
- 执行 claim 用条件 UPDATE 原子抢占。
- 完整链：`model_call_id -> proposal_id -> approval_id -> execution_id -> started_event_id/finished_event_id -> output_artifact_id`。

事件：

```text
tool_proposed  (actor=agent|user; proposal_id, model_call_id, tool, arguments, risk)
tool_approved  (actor=user; proposal_id, approval_id, approving_user)
tool_rejected / tool_cancelled / tool_expired
tool_started   (actor=tool; proposal_id, execution_id)
tool_finished  (actor=tool; proposal_id, execution_id, status, output_artifact_id, output_sha256, output_size, output_summary, error, recovered?)
```

原子性：propose/approve/reject/cancel/claim/finalize 各自在 `BEGIN IMMEDIATE` 中完成“状态行 + 对应事件”的同一事务。执行子进程不在事务内；完成后用同一事务写 `artifact_added` + `tool_finished` + 状态。启动时恢复：`running` -> `failed`（`recovered=true`，`error=interrupted_during_execution`）并写 `tool_finished`；过期 pending/approved 标记 `expired` 并写事件。

## 6. API

```text
GET  /api/tools                                # 固定目录 + 执行能力标志
GET  /api/challenges/{cid}/tool-proposals
POST /api/challenges/{cid}/tool-proposals      # A2 only; 手工申请
GET  /api/challenges/{cid}/tool-proposals/{pid}
POST /api/challenges/{cid}/tool-proposals/{pid}/approve   # A2 only; pending -> approved
POST /api/challenges/{cid}/tool-proposals/{pid}/execute   # A2 only; approved -> running -> final
POST /api/challenges/{cid}/tool-proposals/{pid}/reject
POST /api/challenges/{cid}/tool-proposals/{pid}/cancel
POST /api/challenges/{cid}/flag-confirmation   # hash only; platform_verified=false
```

错误：400 确认缺失；403 等级不允许；404 未知/跨题目；409 状态冲突/过期/重复/参数变化；413 上下文超限；422 Schema；503 审计/持久化不可用。

## 7. Writeup 与 ZIP

- 模型调用披露只使用 `ModelCallJournal` 记录（合成调用单列），`model_call` 事件只用于关联；`delivery_status=not_recorded` 时标记不完整。
- 工具申请、批准、执行、失败、超时、拒绝、取消、过期全部披露；统计基于同一次读取的 `tool_proposals` 快照。
- Flag 只记录人工确认事件（SHA-256 前缀、长度、确认人、时间）并明确 `platform_verified=false`；不描述为平台验证成功。
- 人工 Writeup 原字节不变；`writeup.md`、`writeup_generated.md`、`ai_disclosure.md`、`manifest.json`、`SHA256SUMS`、`timeline.json` 使用同一导出快照。
- 缺失必要记录（审计未知、回答未入事件、成功工具执行缺 Artifact、running 状态等）标记 `incomplete` 并写入 manifest/披露。

## 8. CLI

`python -m app.ai_smoke_cli --allow-model-network` 与 `python -m app.model_cli <config> --allow-model-network` 共用 `run_smoke`：

- 必须显式 `--allow-model-network` 且 `CTF_MODEL_NETWORK_ENABLED=true`。
- `CTF_DATA_DIR` 必须是绝对路径；拒绝工作台数据根及其子目录；不得复用 `workbench.sqlite3`。
- 固定合成提示，不包含题目数据；使用 `ModelCallJournal` 独立审计；临时目录位于指定根内。

## 9. 前端必要调整

保留工作台结构。AI 区域：状态、提问、A2 逐项附件选择与额外确认、工具申请列表、参数/目标展示、人工批准、人工执行、结果（Artifact/SHA/状态）、模型调用审计状态、Flag 人工确认。中文状态：待批准、已批准、运行中、成功、失败、已超时、已拒绝、已取消、已过期。切换题目时清除确认、即时问题、旧题目的异步响应和工具列表。

## 10. 测试与交付

必须覆盖：A0/A1/A2 矩阵、附件选择与哈希、跨题目隔离、工具申请/批准/执行、参数篡改、重复批准、过期、执行崩溃、审计恢复、事件写入失败、Artifact 完整性、Writeup/ZIP 披露一致、CLI 隔离、API Key 泄漏、桌面/移动端。保留原始日志、diff、SHA-256、OpenAPI/contracts 和未解决问题。
