# P1 独立运行验收报告（模型服务设置）

- 日期：2026-11-09
- 工作区：`D:\CTF-worktrees\p1-settings`
- 分支：`feat/p1-model-settings`
- 基准：P0 冻结候选 `D:\CTF-worktrees\p0-frozen`
- 状态：未 commit、未 push、未 merge；等待独立审查
- 本轮只增加 API 地址安全提示与独立运行/验收材料；未扩展功能

## 1. 独立运行参数

| 项 | 值 |
|---|---|
| 后端地址 | `http://127.0.0.1:18110` |
| 前端地址 | `http://127.0.0.1:15190/` |
| 独立数据目录 | `D:\CTF-worktrees\p1-settings\.local-run\data` |
| 后端 PID（实际运行） | `32196` |
| 前端 PID（实际运行） | `54736` |
| 启动时间（UTC） | `2026-11-09T05:39:23.9887231Z` |
| 停止时间（UTC） | `2026-11-09T05:40:37.4540489Z` |
| 模型联网 | `CTF_MODEL_NETWORK_ENABLED=false`，页面开关默认关闭 |
| 运行模式 | 合成数据/本地 Mock；未发送真实 DeepSeek 请求 |

实际端口/进程记录：`verification/p1-model-settings/run/processes.json`、`run-info.json`；停止校验结果：`stop-result.json`。
后端启动日志（uvicorn 实际监听 18110）：`verification/p1-model-settings/run/backend.stdout.log`。
本轮独立启动/停止证据另存于 `verification/p1-model-settings/review-round-2/run/`。

未触碰现有 8000/8001/8002/5173/5174 服务；启动脚本会先检查 18110/15190 是否被占用，占用则拒绝启动。

## 2. 启动与停止

### 启动

```powershell
cd D:\CTF-worktrees\p1-settings
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\p1-start.ps1
```

可自定义独立绝对数据目录：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\p1-start.ps1 `
  -DataDir D:\CTF-worktrees\p1-settings\.local-run\data `
  -BackendPort 18110 -FrontendPort 15190
```

脚本会：

1. 检查 P1 运行记录和端口；拒绝复用已有服务；
2. 创建独立数据目录、日志目录、临时目录；
3. 以 `CTF_DATA_DIR=<独立目录>`、`CTF_MODEL_NETWORK_ENABLED=false` 启动 uvicorn（18110）；
4. 等待 `/api/health` 健康；
5. 以 `node node_modules/vite/bin/vite.js --config vite.p1.config.ts --port 15190` 启动前端；
6. 等待页面可访问，写入 `run-info.json`/PID/日志。

### 停止

```powershell
cd D:\CTF-worktrees\p1-settings
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\p1-stop.ps1
```

停止脚本先验证 PID 对应的可执行文件、完整启动命令行、进程启动时间、身份 token 和监听端口归属；不匹配即拒绝停止。第二轮验证通过后获取并核对 `System.Diagnostics.Process` 句柄，使用已验证句柄终止，减少 PID 复用竞态。写回 `stopped_at`/`stop_mode`/`stop_checks`/`stop_preflight`。实际停止后 18110/15190 均无监听。

数据目录：启动前规范化绝对路径，拒绝 `D:\CTF\.local-data` 等原项目数据目录、工作区源码目录、包含 `workbench.sqlite3`/`model-audit.sqlite3` 等既有业务数据的目录；自定义非空目录需显式 `-AllowNonEmptyDataDir`，默认 `.local-run\data` 保持可用。

## 3. 实际截图（独立运行）

截图由 `frontend/scripts/capture-p1-screenshots.mjs` 在独立启动的真实 uvicorn/Vite 上执行：

- [1440px](verification/p1-model-settings/run-screenshots/model-settings-1440px.png)
- [390px](verification/p1-model-settings/run-screenshots/model-settings-390px.png)
- 运行结果：`verification/p1-model-settings/run-screenshots/run-screenshots.json`

截图实际状态：

- 已通过后端写入一条**合成** API Key（仅用于展示“已配置/DPAPI”状态），截图后立即清除；
- 页面不显示 Key；`run-screenshots.json` 记录 `key_visible=false`、`storage_contains_key=false`；
- 联网默认关闭，测试连接按钮按门禁禁用；
- 390px `scrollWidth <= innerWidth + 1`，无横向溢出；
- 截图中的安全提示可见：
  “API Key 将发送至当前填写的 API 地址，请确认该地址属于你信任的服务商。”

## 4. 测试日志/退出码（本轮重跑）

| 检查 | 结果 | 退出码 | 日志 |
|---|---|---|---|
| 后端全量 pytest | 308 passed, 7 skipped, 0 failed | 0 | `verification/p1-model-settings/review-round-2/backend-pytest.log` |
| Ruff | All checks passed | 0 | `verification/p1-model-settings/review-round-2/ruff.log` |
| 设置/DPAPI 专项 | 18 passed | 0 | `verification/p1-model-settings/review-round-2/settings-tests.log` |
| 前端 npm test | 63 pass / 0 fail | 0 | `verification/p1-model-settings/review-round-2/frontend/npm-test.log` |
| TypeScript/生产构建 | `vue-tsc --noEmit && vite build` 成功 | 0 | `verification/p1-model-settings/review-round-2/frontend/npm-build.log` |
| AI 设置 E2E | 15 passed（含 4 个设置用例） | 0 | `verification/p1-model-settings/review-round-2/frontend/e2e-ai.log` |
| DataDir Junction/Stop/Start 专项 | 6 + 8 + 5 项通过 | 0 | `review-round-2/datadir-windows-tests.log`、`guard-tests.log`、`start-cleanup-tests.log` |

原始退出码：`review-round-2/EXIT-CODES.txt`。

## 5. 真实后端 / Mock / 真实联网边界

- **真实后端、真实 DPAPI、真实 SQLite、真实 HTTP**：
  - 后端全量 pytest/设置专项（TestClient + 真实 DPAPI 文件）；
  - 独立运行启动脚本、uvicorn、Vite、浏览器截图（真实进程/HTTP）；
  - E2E 中设置保存/刷新/网络开关/密钥显示隐藏与真实后端 API。
- **Mock Provider / Mock 路由**：
  - 后端 `/api/model/test` 和 AI 回答使用 `httpx.MockTransport`；
  - E2E 的“连接成功/失败”使用浏览器路由替身；
  - 无真实 DeepSeek 请求。
- **真实模型联网**：**未执行**。没有真实 API Key，没有真实题目/附件/Flag。

## 6. 安全约束核对

- 默认关闭模型联网：启动环境强制 `CTF_MODEL_NETWORK_ENABLED=false`，页面开关默认 false；
- 保存 Key 不自动开启联网：后端测试与 E2E 均覆盖；
- 测试连接只发送固定合成提示；需要联网有效开启 + 显式确认；
- 不发送真实题目/附件/Flag；
- A0/A1/A2 门禁未削弱；
- DPAPI 不可用时返回 503，不写明文；
- Key 不在日志、事件、Writeup、ZIP、截图或 localStorage；
- 独立运行截图时写入的合成 Key 在截图后清除。

## 7. 已知问题 / 未验证事项

1. 单用户、回环、无认证；任何可访问回环端口的本机进程都可能调用设置接口。
2. DPAPI 是 Windows 用户级保护；同一 Windows 用户下的恶意进程仍可能调用 DPAPI 解密。
3. 非 Windows 凭证存储未实现；当前部署 Windows。
4. 测试连接要求先显式开启联网开关，不提供绕过门禁的测试路径。
5. 环境变量 `CTF_MODEL_NETWORK_ENABLED=true` 是运维覆盖；设置页不能覆盖它。
6. 真实 DeepSeek 联网/真实 Key/真实题目/Flag 未验证。
7. 独立运行脚本使用固定 18110/15190；若被占用会拒绝启动，不会复用/停止已有服务。
8. 截图由系统 Edge/Playwright 生成；bundled Chromium 未使用（离线环境）。

## 8. 复现命令

```powershell
cd D:\CTF-worktrees\p1-settings
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\p1-start.ps1
$env:CTF_E2E_CHANNEL='msedge'
$env:P1_FRONTEND_URL='http://127.0.0.1:15190/'
$env:P1_BACKEND_URL='http://127.0.0.1:18110'
$env:P1_SCREENSHOT_DIR='D:\CTF-worktrees\p1-settings\verification\p1-model-settings\run-screenshots'
node frontend\scripts\capture-p1-screenshots.mjs
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\p1-stop.ps1
```

停止后 18110/15190 应无监听；不要再启动真实模型测试。

## 9. 停止条件

仅完成 P1 模型服务设置最后整改和独立运行材料。**停止，等待独立审查。** 不提交、不推送、不合并；不进入真实 API 测试。
