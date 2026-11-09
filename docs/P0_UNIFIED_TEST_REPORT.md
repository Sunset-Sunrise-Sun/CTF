# P0 统一整合测试报告

- 日期：2026-11-09
- 分支：`feat/p0-unified-ai-tools`
- 基准 HEAD：`30eeed6dcc180ae21b5648f25047c5889e3c434a`
- 环境：Windows；Python 3.14.7；Node v24.19.0；npm 11.17.0；Playwright（本机 Edge 通道；离线环境无法下载 bundled Chromium）
- 真实联网/真实 Key：**未使用**。所有模型调用使用 `httpx.MockTransport` 或浏览器路由替身；合成测试 Key 只用于证明不会泄漏。
- 所有测试使用合成数据、`tmp_path`/独立临时数据目录；未复用 8000/8001/8002/5173/5174 服务或人工验收数据库。

## 1. 后端全量

命令（`backend` 目录）：

```powershell
$env:CTF_MODEL_NETWORK_ENABLED='false'
$env:CTF_RUN_LIVE_MODEL='0'
python -B -m pytest -q -rs -p no:cacheprovider --basetemp <独立临时目录>
```

结果：**290 passed, 7 skipped, 0 failed**（fail-closed lstat 整改后；新增 2 个 Windows Junction/reparse point 用例与 14 个 lstat 失败关闭用例）。

7 个 skip：

- 5 个 Windows 符号链接权限不足（`WinError 1314`）：2 个历史证据 symlink 用例、3 个审计路径 symlink 用例；
- 1 个工具**文件符号链接**用例（当前账户不允许创建 symlink；**junction/reparse point 用例全部执行并通过**，不是 skip）；
- 1 个真实 Provider 用例要求显式 opt-in 和合法凭证。

原始日志：`verification/final-fail-closed-20261109/backend-pytest.log`（fail-closed 整改后最终运行；失败项为 0）。历史 `verification/evidence/backend-pytest.log` 与 `verification/remediation-20261109/` 保留为前序候选/整改证据，未覆盖。详见 `docs/P0_LINK_FAIL_CLOSED_20261109.md`。

覆盖范围（既有 + 新增）：

- 事件哈希链、Artifact/导入完整性、人工操作、Writeup/ZIP、人类稿冲突；
- 统一审计账本成功/限流/超时/取消/unmatched start=unknown/append-only/路径链接拒绝；
- AI 契约：consent 绑定、跨题 409、A1 附件拒绝、A2 逐项选择/哈希/篡改、prompt 预算、错误脱敏；
- 工具注册表/7 工具/路径边界/junction、严格 Schema、批准-执行分离、拒绝/取消/过期、参数篡改、重复批准/执行、超时/失败、输出边界、Artifact、崩溃恢复、事件写入失败回滚、跨题隔离、A0/A1/A2/降级；
- 统一闭环：AI 提案 linked `model_call_id` → 人工批准 → 人工执行 → Artifact → Writeup/ZIP 披露；API Key 不泄漏；Flag 仅摘要。

## 2. 后端静态检查

```powershell
python -m ruff check app tests
```

结果：**All checks passed!** 原始日志：`verification/evidence/ruff.log`。

`python -m app.schema_cli` 重新生成 `docs/openapi.json` 与 `docs/contracts.json`；`tests/test_schema_contracts.py` 两项均通过（导出 OpenAPI 与运行时完全一致、AI 契约包含 `consent_challenge_id` 且 `additionalProperties=false`）。

## 3. 前端单元测试 / 构建

```powershell
cd frontend
npm test
npm run build
```

结果：

- `npm test`：**57 tests / 57 pass / 0 fail**（`node:test`，含 11 个新增工具/Flag/切换题目/代次守卫用例）；
- `npm run build`：`vue-tsc --noEmit && vite build` **成功**，dist JS 125.69 kB。

原始日志：`verification/evidence/frontend/logs/npm-test.log`、`npm-build.log`。

## 4. 前端 E2E（桌面 + 390px 移动端）

```powershell
cd frontend
$env:CTF_E2E_CHANNEL='msedge'
npx playwright test --config=playwright.ai.config.ts
```

结果：**11 passed (20.4 s)**。覆盖：

- A2 附件逐项选择 + 额外确认；
- 跨题目 consent 被真实 FastAPI 409 拒绝；
- 切换题目清空工具列表/Flag/确认/问题；
- 旧题延迟 AI 响应不覆盖新题；
- 工具批准与执行是两个独立人工步骤（真实后端事件链：`tool_proposed → tool_approved → tool_started → artifact_added → tool_finished`；批准后没有 `tool_started`；artifact 可下载）；
- 9 种工具状态中文标签、无原始英文状态；
- Flag 只显示摘要，不显示明文，`platform_verified=false`；
- 1440px 与 390px 无横向溢出。

原始日志：`verification/evidence/frontend/logs/e2e-ai.log`；截图：`verification/evidence/frontend/*.png`。

## 5. 真实 HTTP 闭环验收

脚本：`verification/run_http_acceptance.py`（uvicorn 子进程 + 外部 httpx，不 import 应用代码；独立数据目录；回环 18080）。

结果：**19 checks / 19 passed / 0 failed**；共 18 条 HTTP 请求。

关键记录：

- 固定七工具目录、`execution_enabled=false`、`read_only_tool_execution_enabled=true`；
- 路径穿越 422；提案 pending 且无执行；批准后状态 approved、无 `tool_started`；重复批准 409；
- 执行 succeeded，`execution_id`、`output_artifact_id`、`output_sha256` 完整；重复执行 409；
- Artifact 下载字节 SHA-256 与响应一致；
- 事件链 `tool_proposed → tool_approved → tool_started → artifact_added → tool_finished`；
- 追踪链 `proposal_id → approval_id → execution_id → started/finished event → artifact_ids`；
- A1 直接工具申请 403；
- Flag 仅 SHA-256/长度，`platform_verified=false`，明文不出现；
- Writeup 工具计数 1/1；ZIP manifest counts、`read_only_tool_execution_enabled=true`、`ai_disclosure.md` 工具/Flag 披露一致；`SHA256SUMS` 覆盖全部交付文件（8 条）。

原始证据：`verification/evidence/transcript.json`、`results.json`、`server.stdout.log`、`server.stderr.log`。

## 6. 故障注入

脚本：`verification/run_fault_injection.py`（SQLite 触发器精确失败目标写入）。

结果：**6 / 6 passed**：

| 场景 | 观察 |
|---|---|
| `tool_started` 写入失败 | HTTP 500；状态回滚为 `approved`；无 `tool_started` 事件 |
| `tool_finished` 写入失败 | HTTP 500；状态保持 `running`；重启后恢复为 `failed`，`error=interrupted_during_execution`，`tool_finished.recovered=true` |
| `artifact_added` 写入失败 | 最终事务回滚；状态保持 `running`，Artifact 元数据不落库 |
| 审计 `call_finishes` 写入失败 | HTTP 503；账本只有 start，读取为 `unknown`；Provider 已调用但未产生成功回答 |
| 题目 `model_call` 事件写入失败 | HTTP 503；账本 `success` 但题目事件为空，导出/披露可识别为缺失 |

原始证据：`verification/evidence/fault-results.json`。

## 7. 15 类要求覆盖矩阵

| # | 要求 | 证据 |
|---|---|---|
| 1 | A0/A1/A2 权限矩阵 | `test_tools.py::test_a0_a1_levels_are_denied`、`test_downgrade_after_proposal_blocks_approve_and_execute`、`test_unified_p0.py::test_a1_a0_unknown_cannot_use_tool_endpoints`、E2E |
| 2 | A2 附件选择与哈希核对 | `test_ai_p0.py` A2 选择/跨题/哈希/Tamper、E2E A2 两段确认 |
| 3 | 跨题目确认隔离 | `test_ai_p0.py` consent mismatch、`test_tools.py` cross-challenge、E2E real 409 |
| 4 | 工具申请与人工审批 | `test_tools.py` propose/approve/execute、`test_unified_p0.py`、HTTP transcript |
| 5 | 参数篡改 | `test_tools.py` tamper before/after approval |
| 6 | 重复批准 | `test_tools.py`、HTTP duplicate-approve 409 |
| 7 | 过期执行 | `test_tools.py` expired pending/approval + `expire_stale` |
| 8 | 执行期间崩溃 | `test_tools.py::test_recover_interrupted_running_claim`、fault injection |
| 9 | 审计账本恢复 | `test_ai_p0.py` os._exit/finish failure、`test_model_audit.py` unmatched start、fault injection |
| 10 | 事件写入失败 | `test_tools.py` 三类 trigger、`test_ai_p0.py` model_call/agent_message、fault injection |
| 11 | 工具输出 Artifact 完整性 | `test_tools.py` artifact hash/read、`test_unified_p0.py` download SHA、HTTP acceptance |
| 11a | Windows Junction/reparse 递归遍历 | `test_tools.py::test_windows_junction_listing_prunes_external_recursive_and_flat`、`test_windows_workspace_root_junction_is_rejected`（Windows 实机执行，不 skip） |
| 12 | Writeup/ZIP 披露一致 | `test_unified_disclosure.py`、`test_unified_p0.py`、HTTP acceptance SHA256SUMS |
| 13 | CLI 隔离 | `test_ai_p0.py` both CLIs（opt-in/绝对目录/拒绝工作台目录/独立审计） |
| 14 | API Key 泄漏检查 | `test_unified_p0.py::test_api_key_does_not_leak...`、HTTP acceptance disclosure 检查 |
| 15 | 桌面/移动端前端 | Playwright 11 passed（1440px + 390px 截图/布局/交互） |

## 8. 未执行 / 不计入通过

- 真实 DeepSeek 联网请求、真实 API Key、真实比赛题目/附件、真实平台 Flag 提交：按任务授权边界未执行。
- 旧业务全量 E2E（固定 8000/5173 的 `npm run test:e2e`）：未运行，避免触碰原服务；本轮运行隔离的 AI E2E（18002/15174 及独立数据根）。
- 真实模型 Provider 合成连通性：未执行。
- 本机 bundled Playwright Chromium：离线不可用；E2E 使用系统 Edge，默认配置仍为 chromium。
- 5 个 Windows 符号链接用例 skip；建议在有权限环境补跑。
