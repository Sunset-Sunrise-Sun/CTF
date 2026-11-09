# P0 统一架构说明（Codex P0 × DeepSeek 工具系统）

- 日期：2026-11-09
- 固定基准 HEAD：`30eeed6dcc180ae21b5648f25047c5889e3c434a`（PR #9 Draft）
- 开发分支：`feat/p0-unified-ai-tools`
- 状态：P0 整合候选，未提交、未推送、未合并；等待独立审查
- 本地单用户部署边界：服务仅绑定回环地址，无多用户认证；`approving_user` 是本地操作者标识，不是认证身份

## 1. 输入候选与核对

| 候选 | 来源 | SHA-256 |
|---|---|---|
| PR #9 基线 | `30eeed6dcc180ae21b5648f25047c5889e3c434a`；归档 `CTF-PR9-30eeed6.tar.gz` | `c898e59889312ece0824055b778ac61eaa50c1592f28de84f432d2678e7eed46` |
| Codex P0（复审后源码候选） | `outputs/p0-audit-review-20261109/source-candidate.zip` | `8cf275cafc853d803cc29ecbfcfa82d2c72682ade46bb267712d3d471b5692e0` |
| Codex P0 增量复审补丁 | `p0-audit-review.diff` | `9866d16438bf486687d561fc22ffeb9a02486a7d3c49756a54897c17bde2a2d9` |
| DeepSeek 工具系统全量 diff | `CTF-PR9-30eeed6-deepseek-full.diff` | `5e33dc03acaffa1010ec0ecd7a25f9bc13d60106f359bd8d31b1a66d297f3611` |
| Codex 跨题确认补丁 | `CTF-PR9-30eeed6-changes.diff` | `475702f29ee38a64b4a36451eb4cec48812f89acb92ab894f5fb5dcee248326e` |

Codex 候选源码包中的 `backend/app/model_calls.py`、`main.py`、`ai_assistant.py` 等文件已按 `p0-audit-review.diff` 的 6 文件修正（路径链接/重解析点、恢复、回答记录投影）复核后作为统一基线。DeepSeek 工具系统只作为功能来源，不沿用其第二套 `model_calls` 表/`Store.model_calls` 审计路径。

## 2. 总体结构

```text
浏览器工作台 (Vue 3)
  ├─ AI 对话 / 外发范围 / A2 附件逐项选择
  ├─ 工具申请列表 → 批准 → 执行 → 结果/Artifact
  ├─ 模型调用审计状态（/api/model/calls）
  └─ Flag 人工确认（仅摘要）
        │ HTTP（回环）
FastAPI（单进程）
  ├─ 题目/事件/证据/导入/Writeup（workbench.sqlite3）
  ├─ 工具状态机 + 事件原子事务（workbench.sqlite3.tool_proposals）
  ├─ 独立模型审计账本（model-audit.sqlite3）
  ├─ 内容寻址 ArtifactStore（上传证据 + 工具输出）
  └─ 固定只读工具 registry/runner（子进程，无 shell/网络/写）
```

### 模块职责

| 模块 | 职责 |
|---|---|
| `backend/app/model_calls.py` | 唯一模型调用网关与独立追加式账本；`audited_complete`、`disclosure_calls`、`disclosure_lines` |
| `backend/app/ai_assistant.py` | 唯一 AI 请求契约、逐项附件选择/重读/哈希核对、工具目录与提案解析、工具结果回灌 |
| `backend/app/ai_policy.py` | 服务端 A0/unknown/A1/A2 权限矩阵；fail-closed |
| `backend/app/tool_registry.py` | 固定七个只读工具和严格参数 Schema |
| `backend/app/tool_impl.py` | 只读工具实现；workspace 边界复核 |
| `backend/app/tool_runner.py` | 固定子进程入口；stdin JSON、无 shell |
| `backend/app/tool_system.py` | 工具申请/批准/执行/拒绝/取消/过期状态机、原子事务、Artifact、恢复 |
| `backend/app/store.py` | 事件哈希链、`append_event(db,...)`、`add_artifact_with_db(db,...)` 事务原语 |
| `backend/app/writeup.py` / `export.py` | 同一快照的 Writeup/ZIP/ai_disclosure/manifest 披露 |
| `backend/app/migrations/003_tool_approvals.sql` | 工具状态表（无 `model_calls` 表） |
| `backend/app/model_cli.py` / `ai_smoke_cli.py` | 两个 CLI 共用同一安全策略与独立审计 |
| `frontend/src/components/ai/ToolApprovalPanel.vue` | 工具申请/批准/执行/结果面板 |

## 3. 唯一模型调用审计

### 3.1 独立账本

`<data_root>/model-audit.sqlite3` 使用 schema v1：

- `call_starts(call_id PK, body)` 和 `call_finishes(call_id PK→call_starts, body)`；
- 两张表都有 update/delete 触发器，只允许追加；
- `PRAGMA user_version=1`、`synchronous=FULL`；
- 路径在每次连接前拒绝符号链接/Windows 重解析点及 `-journal/-wal/-shm` 侧车；失败即 `audit_unavailable`；
- `ModelCallRecord` 只保存元数据：`call_id`、题目、Provider、模型、用途、时间、范围、`response_status`、错误类别、usage；不保存 prompt/回答正文。

### 3.2 写入时序

1. 生成唯一 `call_id`，**先**持久化 `call_starts`；写入失败则不发送请求。
2. 发送 HTTP 请求（DeepSeek 适配器）。
3. 成功/失败/取消均持久化 `call_finishes`。
4. 若属于题目调用，再追加题目事件 `model_call`（`call_id` 关联）；事件写失败时错误向上传递，账本事实仍保留。
5. 只有 start 没有 finish 的调用在读取时投影为 `response_status="unknown"`、`completed_at=null`，不重放、不伪造终结。

HTTP 解题、`/api/model/test` 合成连接、`model_cli`、`ai_smoke_cli` 全部经 `audited_complete`；DeepSeek 候选的 `Store.model_calls` 与迁移 `003_model_audit.sql` 不进入统一实现。

### 3.3 关联

`model_call` 事件和 `agent_message` 事件共享 `call_id`；AI 工具申请把同一 `call_id` 写入 `tool_proposals.model_call_id`，工具申请/批准/执行事件继续携带该 ID。`disclosure_calls` 合并账本与旧事件并按 `call_id` 去重，成功题目调用若没有对应 `agent_message` 则标记 `delivery_status="not_recorded"`。

## 4. 唯一 AI 请求契约

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

响应：`event_id`、`answer`、`provider_id`、`model_id`、`included_files`、`verification_status`、`call_id`、`tool_proposals`。

校验顺序与要点：

1. Pydantic `extra=forbid`；`confirm_external_processing`/`confirm_attachments` 为严格布尔。
2. 题目存在（404）；显式外发确认（400）；`consent_challenge_id == {cid}`（409）；服务器联网开关（503）；`unknown/A0` 拒绝（403）。
3. A1 只允许用户选定的文字；A1/A0/unknown 不允许附件和工具提案。A2 附件必须逐项选择并 `confirm_attachments=true`。
4. 选中导入文件：按 `import_id/relative_path` 重新绑定 manifest、检查事件绑定、重新读取文件、核对大小与请求 SHA-256；跨题目文件/错误哈希/Tamper 返回 409/403。
5. 选中 Artifact：按本题 artifact 表查找、核对 SHA-256、从 CAS 重新读取并校验。
6. 同一 `context_scope`（等级+选择+规则摘要）内的最近 10 轮对话进入上下文；等级/选择/规则变化自动丢弃旧历史。
7. 完整 Provider JSON ≤180,000 UTF-8 字节；响应缓冲 ≤512 KiB；空回答/未请求的 wire tool_calls 按错误处理。
8. 回答写入 `agent_message`；A2 的待批准工具申请与 `agent_message`、`tool_proposed` 事件在**同一事务**提交，`agent_message.tool_proposal_ids` 记录申请 ID。

前端在每个请求发出时重新断言 `consent_challenge_id`，切换题目即清空确认、问题、附件选择、工具列表、Flag 输入与旧异步响应（generation guard）。

## 5. 权限矩阵（后端强制）

| 等级 | AI 对话 | 附件外发 | 工具申请 | 工具批准 | 工具执行 |
|---|---|---|---|---|---|
| unknown | 禁止 | 禁止 | 禁止 | 禁止 | 禁止 |
| A0 | 禁止 | 禁止 | 禁止 | 禁止 | 禁止 |
| A1 | 受限文字 | 禁止 | 禁止 | 禁止 | 禁止 |
| A2 | 允许 | 逐项确认 | 允许 | 每次人工批准 | 仅 approved 且未过期 |

`ToolService` 的 `propose/approve/execute` 内部再次读取题目等级；申请后降级为 A1/A0/unknown 时，批准/执行仍返回 403。HTTP 端点另外做同类检查，因此直接 HTTP 请求不能绕过。reject/cancel 仅用于清理，A1 允许，unknown/A0 拒绝。

## 6. 工具系统

### 6.1 固定注册表

| 工具 | 参数 | 行为 |
|---|---|---|
| `file_inspect` | `path` | 格式/大小/SHA-256/前 64 字节；不执行 |
| `sha256` | `path` | 流式 SHA-256 与大小 |
| `stat` | `path` | kind/size/mtime(UTC)/mode |
| `strings` | `path`, `min_length` 4..64, `max_strings` 1..200 | 有界可打印 ASCII |
| `list_files` | `path` 默认 `.`, `recursive`, `max_entries` 1..500 | 有界目录列表，跳过链接 |
| `image_info` | `path` | PNG/GIF/JPEG/WebP 头部尺寸 |
| `text_decode` | `path`, `encoding` base64/hex/url | 有界文本解码 |

全部 `read_only=true`、`requires_approval=true`；没有 shell、python、curl、写、删除、安装或任意代码执行工具。

### 6.2 路径与执行隔离

- 注册表严格拒绝未知工具/参数/类型/枚举/越界/未知键；
- workspace 相对路径，拒绝绝对路径、盘符、`..`、冒号路径、NUL、设备名、末尾点/空格、符号链接/Windows reparse point（junction）；统一 `_is_link_like` 检查 symlink、`FILE_ATTRIBUTE_REPARSE_POINT` 与 `Path.is_junction()`；**workspace root 本身也检查**；申请时校验，runner 执行前再次校验；
- `list_files` 递归模式在 `os.walk` 每层剪除所有链接/reparse point 目录，非递归模式目录和文件都检查；外部文件名称/内容不可通过工具读取；
- 固定子进程：`[python, -I, -B, tool_runner.py]`、`shell=False`、最小环境白名单、15 秒超时、64 KiB 输出上限/256 KiB stdout 上限、进程内并发信号量；
- 输出全文写入内容寻址 ArtifactStore，事件/状态只引用 `output_artifact_id`、`output_sha256`、`output_size`，不把截断文本当作完整结果。

### 6.3 状态机与原子事务

```text
pending -> approved -> running -> succeeded
   |          |          |-----> failed
   |          |          |-----> timed_out
   |          |-----> expired
   |-----> rejected
   |-----> cancelled
   |-----> expired
```

- `approved` 生成唯一 `approval_id` 和 `approved_arguments_sha256`；
- `execute` 前重算库中 `arguments_json` 的 SHA-256，与请求时的 `arguments_sha256` 和批准时的哈希比较；不一致原子标记 `expired` + `tool_expired`，返回 409；
- claim 使用条件 UPDATE（`WHERE status='approved'`），重复批准/重复执行返回 409；
- `expires_at` 过期后不能批准/执行；启动时 sweep 过期 pending/approved；
- 每个转换在 `BEGIN IMMEDIATE` 中同时写状态行和对应 `tool_*` 事件；
- 执行子进程不在数据库事务内；最终事务同时写 `artifact_added`、`tool_finished` 和状态行；
- 启动时 `recover_interrupted` 将残留 `running` 标记为 `failed`（`error=interrupted_during_execution`、`recovered=true`）并在同一事务写 `tool_finished`；
- 参数哈希、批准 ID、执行 ID、事件 ID、artifact ID 构成完整追踪链。

### 6.4 工具事件

```text
tool_proposed  actor=agent|user, proposal_id, model_call_id, tool, arguments, risk
tool_approved  actor=user, proposal_id, approval_id, approving_user
tool_rejected / tool_cancelled / tool_expired
tool_started   actor=tool, proposal_id, execution_id
tool_finished  actor=tool, proposal_id, execution_id, status, output_artifact_id,
               output_sha256, output_size, output_summary, error, recovered,
               artifact_ids
```

## 7. Writeup 与 ZIP

- 主入口一次性读取 `calls = disclosure_calls(events, model_call_records(cid))` 与 `tool_proposals = tools.list(cid)`，把同一快照传给预览与导出；不在 writeup/export 内部重新统计模型调用。
- `writeup.md`/`writeup_generated.md`/`ai_disclosure.md`/`manifest.json`/`logs/events.json`/`logs/timeline.json`/`SHA256SUMS` 使用同一快照；人工 Writeup 原字节不重写。
- 模型调用披露：成功/失败/取消/未确定/合成分离；`delivery_status=not_recorded` 明确说明“模型已响应、回答未入事件”。
- 工具披露：9 种状态逐条列出 `proposal_id/model_call_id/approval_id/execution_id/tool/相对路径参数/时间/output_sha256/artifact id/error`；统计口径来自同一 proposal 快照。
- Flag：只记录 `flag_confirmed` 事件的 SHA-256 前缀、长度、确认人、时间；`platform_verified=false`；没有 `flag_capture` 截图仍保留缺失标记，绝不描述为平台验证成功。
- 缺少必要记录（审计 unknown、成功回答未入事件、成功工具缺 Artifact、running、事件链无效、必要证据缺失）标记 `incomplete`，写入 manifest、披露和 `INCOMPLETE.txt`。

## 8. CLI

`python -m app.ai_smoke_cli --allow-model-network [--data-dir <绝对目录>]` 与 `python -m app.model_cli <config> --allow-model-network [--data-dir ...]`：

- 必须显式 `--allow-model-network` 且 `CTF_MODEL_NETWORK_ENABLED=true`；
- 数据目录必须绝对；拒绝工作台数据根及其子目录；不得包含 `workbench.sqlite3`/`project.json`/`artifacts`/`challenges`/`writeups`；
- 固定合成提示，不包含题目内容；临时目录位于指定根内；
- 只写独立 `model-audit.sqlite3`；不读写工作台数据库。

## 9. 前端

保留现有工作台结构，仅整合必要区域：

- AI 区域：模型状态、提问、A2 逐项附件选择 + 额外确认、外发确认、模型调用审计状态；
- 工具区域：申请列表、工具名/参数/目标/reason/risk/status、批准与执行两个独立按钮、拒绝/取消、结果摘要/SHA-256/Artifact 下载；
- 中文状态：待批准/已批准/运行中/成功/失败/已超时/已拒绝/已取消/已过期；
- Flag：人工确认只显示摘要，不显示明文，不宣称平台验证；
- 切换题目清空确认、问题、附件选择、工具列表、Flag 输入与旧异步响应。

## 10. 明确的安全边界

- 单用户、仅回环、无认证/授权：`approving_user` 是本地声明，不是可信身份；多用户隔离未实现。
- 工具隔离是应用层路径检查 + 固定只读 runner；没有 OS 沙箱/网络命名空间；TOCTOU 窗口不能完全消除。
- 审计账本依赖本机文件系统权限与 SQLite 约束，没有外部签名/远程不可篡改保证。
- 工具输出/失败不保留 stderr Artifact（仅 error 文本）；成功执行必须有 Artifact。
- 合成连接测试只证明当前进程能连通配置的 Provider；不代表真实题目联网验收。
- 未执行真实 DeepSeek 请求、未使用真实 API Key、未进行真实比赛题目验收；等待后续明确授权。
