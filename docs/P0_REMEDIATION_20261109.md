# P0 复审整改报告（Junction / 真实后端工具链 / 全链路验证）

- 日期：2026-11-09
- 工作区：`D:\CTF-worktrees\unified`
- 分支：`feat/p0-unified-ai-tools`
- 基准 HEAD：`30eeed6dcc180ae21b5648f25047c5889e3c434a`
- 状态：复审整改完成，**未 commit、未 push、未 merge**；等待独立审查
- 真实 API Key / 真实比赛题目 / 真实 Flag：**未使用**
- 原始候选、原始证据、原始完整 diff：保留在 `verification/evidence/` 与 `verification/unified-p0.diff`，本轮新增证据在 `verification/remediation-20261109/`，不覆盖历史文件

## 1. 整改项与结果

### 1.1 Windows Junction/reparse point 递归遍历防护

修改 `backend/app/tool_impl.py`：

- 新增统一判定 `_is_link_like(path)`：同时检查 `lstat` 的 `S_ISLNK`、`st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT`、以及 `Path.is_junction()`；覆盖符号链接、NTFS junction、其他 Windows reparse point。
- 新增 `_checked_root(root)`：在 `resolve()` 之前用 `lstat` 检查 workspace root 本身，拒绝 root 为链接/reparse point；再解析并要求真实目录。
- `_resolve()` 现在先检查 root 本身，再逐级检查路径组件；`resolve_workspace_path()` 与所有七个工具共享该边界。
- `list_files()`：
  - `recursive=True`：在 `os.walk(..., followlinks=False)` 的每一层，用 `_is_link_like` 剪除所有链接目录；文件名也逐个检查；junction 不会被 `os.walk` 跟随。
  - `recursive=False`：目录和文件均检查，链接/reparse point 条目直接跳过。
  - workspace root 自身也由 `_checked_root` 检查。
- `backend/app/tool_runner.py`：使用 `resolve_workspace_path(requested_root, ".")` 先验证 root，再把**词法 root**传给 `dispatch`，避免“先 resolve 掩盖 root 是 junction”。
- `backend/app/tool_system.py`：`_validate`/`_run` 使用 `workspace.challenge_lexical(cid)`，不再先 resolve challenge 目录。
- `backend/app/workspace.py`：新增 `challenge_lexical()`，`challenge()` 仍做 resolve + containment 校验。

### 1.2 Junction 测试（不跳过有权限环境的用例）

新增/强化 `backend/tests/test_tools.py`：

- `test_windows_junction_listing_prunes_external_recursive_and_flat`：
  - 在 challenge workspace 内创建指向外部真实目录的 junction；
  - `list_files(recursive=True)` 结果不包含 junction 名或外部文件名；
  - `list_files(recursive=False)` 同样不包含；
  - `file_inspect`/`strings` 访问 `junction/outside-secret.txt` 被拒绝；
  - 直接调用 `tool_runner.py`（绕过 HTTP 服务）仍拒绝，且输出不含外部内容。
- `test_windows_workspace_root_junction_is_rejected`：
  - challenge workspace root 本身是 junction 时，`ToolService.propose` 直接拒绝；
  - 直接调用 runner 也拒绝；外部 `root-secret.txt` 名称/内容不出现。
- 原 `test_windows_junction_escape_is_rejected` 改为 Windows 上创建失败即 `pytest.fail`，**不再用 skip 掩盖有权限环境的失败**。
- 唯一仍 skip 的是“文件符号链接”用例（Windows 当前账户无 symlink 权限）；junction/reparse point 用例本轮全部执行并通过。

### 1.3 真实 FastAPI 工具链集成测试

强化 `backend/tests/test_unified_p0.py::test_ai_proposal_is_linked_to_audit_and_requires_human_execution`：

- 使用真实 `TestClient(create_app(...))`，不是 Playwright route.fulfill；
- Mock Provider 返回带 fenced `tool_proposals` 的 A2 回答；
- 真实 `POST /api/challenges/{cid}/ai/chat` → 持久化 proposal；
- 人工 `POST .../approve`（此步不执行）；
- 人工 `POST .../execute`（只有此步执行）；
- 工具输出写入 ArtifactStore，HTTP 下载校验 SHA-256；
- **第二轮真实 `/ai/chat`**：断言下一次模型请求上下文中包含 `tool_finished`、proposal_id、output_artifact_id、output_sha256；不自动产生第二次提案/执行。

### 1.4 完整关联链与状态顺序

同一测试断言：

```text
model_call_id -> proposal_id -> approval_id -> execution_id
  -> decision_event_id / started_event_id / finished_event_id
  -> artifact_ids
```

并逐项验证：

- 提案 pending 时无 `tool_started/tool_finished`；
- approve 后状态 `approved`、`execution_id` 为空、无 `tool_started`；
- 只有显式 execute 后出现 `tool_started/artifact_added/tool_finished`；
- 重复 approve / execute 返回 409，Provider 调用次数不增加；
- 工具 Artifact 下载字节 SHA-256 与 `tool_finished.output_sha256` 一致。

### 1.5 失败、超时、重复、降级、跨题、写入失败

现有与本轮测试覆盖：

- 失败/超时：`test_tools.py::test_failed_execution_is_recorded`、`test_timeout_is_recorded`；
- 重复批准/执行：`test_tools.py`、`test_unified_p0.py`、真实 HTTP acceptance；
- 等级降级：`test_tools.py::test_downgrade_after_proposal_blocks_approve_and_execute`、`test_unified_p0.py` 的 A1/A0/unknown/降级断言；
- 跨题目隔离：`test_tools.py::test_cross_challenge_isolation`、`test_ai_p0.py` consent 跨题 409；
- 事件写入失败：`test_tools.py` 的 `tool_started`/`tool_finished`/`artifact_added` 触发器回滚测试、`test_ai_p0.py` 的 `model_call`/`agent_message` 写入失败；
- Artifact 写入失败：`test_tools.py` 的 `artifact_added` 最终事务回滚 + 启动恢复；
- 故障注入脚本 `verification/run_fault_injection.py` 6/6 通过。

## 2. 本轮验证结果

| 检查 | 结果 | 日志 |
|---|---|---|
| 后端全量 pytest | **276 passed, 7 skipped, 0 failed** | `verification/remediation-20261109/backend-pytest.log` |
| Ruff | **All checks passed** | `verification/remediation-20261109/ruff.log` |
| Junction 专项 | **3 passed**（两个新增 + 原用例；无 junction skip） | `verification/remediation-20261109/junction-tests.log` |
| 工具子系统 | **30 passed, 1 skipped**（唯一 skip：文件符号链接权限） | `verification/remediation-20261109/tools-pytest.log` |
| AI 工具链集成 | **4 passed** | `verification/remediation-20261109/unified-p0-integration.log` |
| 前端 `npm test` | **57 pass / 0 fail** | `verification/remediation-20261109/frontend/npm-test.log` |
| 前端 `npm run build` | **vue-tsc + vite build 成功** | `verification/remediation-20261109/frontend/npm-build.log` |
| 前端 AI E2E | **11 passed**（Edge，1440/390px） | `verification/remediation-20261109/frontend/e2e-ai.log` |
| 隔离 HTTP acceptance | **19/19 passed，18 请求** | `verification/remediation-20261109/http-acceptance/` |
| 故障注入 | **6/6 passed** | `verification/remediation-20261109/fault-injection/` |

7 个后端 skip 仍全部为环境限制：5 个 Windows 符号链接权限、1 个工具文件 symlink 权限、1 个真实 Provider 显式 opt-in。**没有任何 junction/reparse point 用例被跳过**。

## 3. 真实后端 vs Mock Provider 的边界

| 验证 | 是否真实 FastAPI | 模型 Provider | 说明 |
|---|---|---|---|
| 后端 pytest（含 `test_unified_p0.py`） | 是（TestClient/lifespan） | **MockTransport** | 真实 API 路由、SQLite、工具子进程、ArtifactStore；模型响应为本地 Mock |
| 隔离 HTTP acceptance | 是（uvicorn + 外部 httpx） | 无模型调用 | 工具/审计/披露/Flag 全走真实 HTTP；合成数据 |
| 故障注入 | 是（TestClient） | MockTransport | 用 SQLite 触发器注入失败 |
| 前端 E2E 工具批准/执行 | 是（隔离 FastAPI） | 无模型调用 | 工具两步执行走真实后端事件链 |
| 前端 E2E AI 回答/审计部分 | 是（隔离 FastAPI） | **浏览器 route Mock** | 仅 UI/契约路径；不作为后端工具链证据 |
| 真实 DeepSeek 联网 | **否** | 未使用 | 等待后续明确授权 |

## 4. 增量 diff / 完整 diff / 校验和

本轮新增：

- `verification/remediation-20261109/incremental.diff`：相对上一轮候选（由 `verification/unified-p0.diff` 重建）的增量 diff；
- `verification/remediation-20261109/complete.diff`：相对基准 `30eeed6` 的完整 diff（排除证据二进制与 remediation 日志）；
- `verification/remediation-20261109/SHA256SUMS`：本轮交付文件与 diff 的 SHA-256；
- 上一轮 `verification/unified-p0.diff`、`verification/evidence/` 保持原样，未覆盖。

## 5. 复现命令

```powershell
cd D:\CTF-worktrees\unified\backend
$env:CTF_MODEL_NETWORK_ENABLED='false'
$env:CTF_RUN_LIVE_MODEL='0'
python -B -m pytest -q -rs -p no:cacheprovider --basetemp "$env:TEMP\p0-remediation-basetemp"
python -m ruff check app tests
python -B -m pytest -q -rs tests/test_tools.py -k junction --basetemp "$env:TEMP\p0-junction"

cd ..\frontend
npm test
npm run build
$env:CTF_E2E_CHANNEL='msedge'
npx playwright test --config=playwright.ai.config.ts

cd ..
python -B verification\run_http_acceptance.py
python -B verification\run_fault_injection.py
```

## 6. 结论与停止条件

本轮复审整改已完成：Junction/reparse point 递归遍历已修复并有 Windows 实机测试；真实 FastAPI 工具链、完整关联链、失败/超时/重复/降级/跨题/写入失败均已覆盖；所有要求的检查已重新执行并保留原始日志。

**停止在独立审查点。** 不提交、不推送、不合并；不声称独立验收通过；真实 DeepSeek 联网/真实题目/真实 Flag 等待后续明确授权。
