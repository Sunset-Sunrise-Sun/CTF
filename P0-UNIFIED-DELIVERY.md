# P0 统一整合交付摘要（待独立审查）

- 日期：2026-11-09
- 工作区：`D:\CTF-worktrees\unified`
- 固定基准 HEAD：`30eeed6dcc180ae21b5648f25047c5889e3c434a`（PR #9 Draft）
- 独立开发分支：`feat/p0-unified-ai-tools`
- 状态：**未 commit、未 push、未 merge**；原仓库工作树、PR #9 远端、8000/8001/8002/5173/5174 服务均未修改；等待独立审查
- 范围：P0-1 统一模型审计、P0-2 统一 AI 契约、P0-3 A0/A1/A2 门禁、P0-4 七工具、P0-5 审批状态机、P0-6 追踪链、P0-7 Writeup/ZIP、P0-8 CLI 统一；前端必要调整
- 未执行：真实 DeepSeek 联网、真实 API Key、真实题目/Flag/平台验证、多用户认证（第二阶段）

## 1. 候选输入核对（SHA-256）

| 候选 | 文件 | SHA-256 |
|---|---|---|
| PR #9 基线 | `CTF-PR9-30eeed6.tar.gz` | `c898e59889312ece0824055b778ac61eaa50c1592f28de84f432d2678e7eed46` |
| Codex P0 复审源码候选 | `p0-audit-review-20261109/source-candidate.zip` | `8cf275cafc853d803cc29ecbfcfa82d2c72682ade46bb267712d3d471b5692e0` |
| Codex P0 增量复审 diff | `p0-audit-review.diff` | `9866d16438bf486687d561fc22ffeb9a02486a7d3c49756a54897c17bde2a2d9` |
| DeepSeek 工具系统全量 diff | `CTF-PR9-30eeed6-deepseek-full.diff` | `5e33dc03acaffa1010ec0ecd7a25f9bc13d60106f359bd8d31b1a66d297f3611` |
| Codex 跨题确认补丁 | `CTF-PR9-30eeed6-changes.diff` | `475702f29ee38a64b4a36451eb4cec48812f89acb92ab894f5fb5dcee248326e` |

## 2. 统一实现要点

- **唯一审计事实来源**：`model-audit.sqlite3` 的 `call_starts/call_finishes` 追加式账本（Codex P0），HTTP 解题、合成连接、两个 CLI 共用；不保留 DeepSeek 的 `model_calls` 表/Store 审计路径。
- **唯一 AI 契约**：`consent_challenge_id`、`selected_texts`、`selected_files`、`selected_artifacts`、`confirm_attachments`；后端逐项重新读取/绑定/哈希；跨题 409；A1 无附件/工具，A2 逐项确认。
- **A0/A1/A2 后端门禁**：AI 对话、附件、工具申请/批准/执行全部服务端检查；直接 HTTP 不可绕过；降级后批准/执行仍拒绝。
- **七个固定只读工具**：严格 Schema、workspace 路径/符号链接/junction 防护、固定 runner、无 shell/网络/写、最小环境、超时、输出上限。
- **审批状态机**：`pending → approved → running → succeeded/failed/timed_out`，加 rejected/cancelled/expired；批准与执行分离；参数哈希、重复批准/执行 409、过期拒绝。
- **原子事务与恢复**：状态行 + 对应事件同一 `BEGIN IMMEDIATE`；最终事务写 Artifact + `tool_finished` + 状态；启动恢复 running→failed(recovered=true)。
- **追踪链**：`model_call_id → proposal_id → approval_id → execution_id → decision_event_id/started_event_id/finished_event_id → artifact_ids`。
- **Writeup/ZIP**：同一快照；模型调用只读账本；工具 9 状态披露；Flag 仅摘要且 `platform_verified=false`；缺失记录 incomplete。
- **CLI**：两个 CLI 共用 opt-in、绝对独立目录、拒绝工作台数据根、固定合成提示、独立审计。
- **前端**：AI 外发范围、A2 逐项确认、工具申请/批准/执行/结果、中文状态、模型审计、Flag 摘要、切题清理与异步代次守卫。

## 3. 交付物索引

| 交付物 | 路径 |
|---|---|
| 统一架构说明 | `docs/P0_UNIFIED_ARCHITECTURE.md` |
| 修改文件清单 + SHA-256 | `docs/P0_UNIFIED_FILES.md` |
| SHA-256 清单（机器可读） | `docs/P0_UNIFIED_SHA256SUMS` |
| 完整 diff | `verification/unified-p0.diff` |
| OpenAPI | `docs/openapi.json` |
| Pydantic contracts | `docs/contracts.json` |
| 测试报告 | `docs/P0_UNIFIED_TEST_REPORT.md` |
| 安全报告 | `docs/P0_UNIFIED_SECURITY_REPORT.md` |
| 工具完整闭环记录 | `docs/P0_UNIFIED_TOOL_CLOSURE.md` |
| 复审整改报告（第一轮） | `docs/P0_REMEDIATION_20261109.md` |
| fail-closed 最终整改报告 | `docs/P0_LINK_FAIL_CLOSED_20261109.md` |
| 未解决问题 / 非目标 | `docs/P0_UNIFIED_OPEN_ISSUES.md` |
| 真实 HTTP 验收脚本 | `verification/run_http_acceptance.py` |
| 故障注入脚本 | `verification/run_fault_injection.py` |
| 复审整改证据（HTTP transcript/results、pytest/ruff、前端截图） | `verification/remediation-20261109/` |
| 历史证据（上一轮，保留不覆盖） | `verification/evidence/` |

## 4. 实际验证结果

| 检查 | 结果 | 原始日志 |
|---|---|---|
| 后端全量 pytest | **290 passed, 7 skipped, 0 failed**（fail-closed 整改后） | `verification/final-fail-closed-20261109/backend-pytest.log` |
| 后端 ruff | **All checks passed** | `verification/remediation-20261109/ruff.log` |
| 前端 `npm test` | **57 pass / 0 fail** | `verification/remediation-20261109/frontend/npm-test.log` |
| 前端 `npm run build` | **vue-tsc + vite build 成功** | `verification/remediation-20261109/frontend/npm-build.log` |
| 前端 E2E（Edge，1440/390） | **11 passed** | `verification/remediation-20261109/frontend/e2e-ai.log` |
| 真实 HTTP 闭环 | **19/19 passed，18 请求** | `verification/remediation-20261109/http-acceptance/` |
| 故障注入 | **6/6 passed** | `verification/remediation-20261109/fault-injection/` |

7 个 skip 全部为环境限制：5 个 Windows 符号链接权限、1 个工具 symlink 权限、1 个真实 Provider 显式 opt-in。没有把 skip 计入通过。

## 5. 复现命令

```powershell
# 后端
cd D:\CTF-worktrees\unified\backend
$env:CTF_MODEL_NETWORK_ENABLED='false'
$env:CTF_RUN_LIVE_MODEL='0'
python -B -m pytest -q -rs -p no:cacheprovider --basetemp "$env:TEMP\p0-unified-basetemp"
python -m ruff check app tests

# 契约生成与一致性
python -B -m app.schema_cli

# 前端
cd ..\frontend
npm test
npm run build

# 隔离 AI E2E（本机 Edge）
$env:CTF_E2E_CHANNEL='msedge'
npx playwright test --config=playwright.ai.config.ts

# 真实 HTTP 验收 / 故障注入
cd ..
python -B verification\run_http_acceptance.py
python -B verification\run_fault_injection.py
```

## 6. 交付 diff 校验

- `verification/unified-p0.diff`：完整修改/新增（排除 `verification/evidence` 二进制证据与 diff 自身）。
- `verification/unified-p0.diff.sha256`：该 diff 的 SHA-256。
- `docs/P0_UNIFIED_FILES.md` / `docs/P0_UNIFIED_SHA256SUMS`：源文件清单与每个文件 SHA-256（不含证据二进制与生成的元数据文件自身）。

## 7. 审查建议顺序

1. 先读 `docs/P0_UNIFIED_ARCHITECTURE.md` 与 `docs/P0_UNIFIED_SECURITY_REPORT.md`。
2. 核对 `docs/P0_UNIFIED_FILES.md` 与 diff 是否一致；重点检查 `model_calls.py`、`tool_system.py`、`ai_assistant.py`、`main.py`、`writeup.py`、`export.py`、`ToolApprovalPanel.vue`。
3. 复跑后端全量 + ruff + 前端 test/build；有权限环境补跑 symlink skip。
4. 检查 `verification/remediation-20261109/http-acceptance/transcript.json` 的 18 条请求与 `results.json` 的 19 项 PASS；历史 `verification/evidence/` 保留为上一轮证据。
5. 检查 `docs/openapi.json`/`docs/contracts.json` 与代码一致。

## 8. 停止条件

P0 整合到此停止，交付独立审查。真实 DeepSeek 联网、多轮真实工具申请、最终实战验收等待后续明确授权；**不得把本候选描述为生产可用或平台验证通过**。
