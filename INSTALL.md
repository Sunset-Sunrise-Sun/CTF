# Windows 安装与部署

## 1. 环境要求

- Windows 10/11 x64。
- Python 3.11 或更高版本（已在 Python 3.14.7 上验证）。
- Node.js 20 或更高版本（已在 Node 24.19.0 上验证），带 npm。
- 浏览器：Microsoft Edge；或安装 Playwright Chromium。
- 磁盘：源码约数十 MB；前端依赖另需数百 MB。

本项目是本地单用户工具，不要求数据库服务器或容器。

## 2. 安装后端

```powershell
cd D:\CTF-worktrees\p0-p1-frozen\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

如果不使用虚拟环境，可直接在用户 Python 环境执行 `python -m pip install -e ".[dev]"`。

## 3. 安装前端

```powershell
cd D:\CTF-worktrees\p0-p1-frozen\frontend
npm install
```

离线环境需提前准备 npm 缓存或 `node_modules`。源码 ZIP 不包含 `node_modules`。

## 4. 浏览器与 E2E（可选）

开发/验收 E2E 可使用系统 Edge：

```powershell
$env:CTF_E2E_CHANNEL='msedge'
npx playwright test --config=playwright.ai.config.ts
```

也可安装 Playwright Chromium：

```powershell
npx playwright install chromium
```

## 5. 启动与停止

在仓库根目录：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\freeze-start.ps1
```

打开 `http://127.0.0.1:15190/`。

停止：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\freeze-stop.ps1
```

启动脚本会：

- 使用 `127.0.0.1:18110`（后端）和 `127.0.0.1:15190`（前端）；
- 使用独立的 `.local-run\data` 和 `.local-run\run`；
- 默认设置 `CTF_MODEL_NETWORK_ENABLED=false`；
- 写入 PID、身份元数据、run-info 与日志；
- 拒绝复用已有监听端口。

停止脚本会重新校验进程身份，身份未知或不匹配时拒绝终止。

## 6. 数据目录

- 运行数据库：`.local-run\data\workbench.sqlite3`
- 模型审计库：`.local-run\data\model-audit.sqlite3`
- 模型配置：`.local-run\data\model-service.json`（不含 Key）
- 模型 Key：`.local-run\data\model-service.secret`（Windows DPAPI 加密）
- Writeup/附件/导入：`.local-run\data\...`
- 运行日志/PID：`.local-run\run\...`

不同 Windows 用户不应共享同一 data 目录中的 Key；DPAPI 密文只对保存它的 Windows 用户可解密。

## 7. 端口冲突

如果 18110 或 15190 被占用，启动脚本会拒绝启动。不要修改为现有的 8000/8001/8002/5173/5174；如需自定义端口，必须同步调整 `frontend/vite.p1.config.ts` 的代理目标。

## 8. 故障排查

- 后端不健康：查看 `.local-run\run\logs\backend.stderr.log`。
- 前端不启动：查看 `.local-run\run\logs\frontend.stderr.log` 和 `start-failure.json`。
- 停止被拒绝：查看 `.local-run\run\stop-result.json`，人工核对 PID/身份/端口后再处理；不要盲目杀进程。
- 模型设置保存失败：查看设置页错误和 `model-service.json` 是否损坏；配置损坏时模型调用会 fail-closed，需重新保存有效配置。
- DPAPI 不可用：保存 Key 返回 503，不会退化为明文。
