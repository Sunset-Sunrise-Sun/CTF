# CTF Workbench — P0 + P1 冻结候选

一个单用户、本地运行、证据优先的 CTF 解题工作台。P0 提供统一 AI 调用审计、A0/A1/A2 权限门禁、人工审批的只读工具和 Writeup/ZIP 导出；P1 提供独立的 DeepSeek 模型服务设置、DPAPI 凭证存储、联网开关和测试连接。

- 默认不联网：模型联网调用默认关闭。
- 模型只提出建议；工具只能提出申请。
- 批准和执行为两个独立人工步骤。
- 只读工具不经过 Shell、不访问网络、不写入题目工作区。
- API Key 由每位用户自行填写；项目不附带统一 Key，也不需要开发者提供 Key。
- 本轮不包含真实 DeepSeek 调用，未使用真实比赛题目或 Flag。

## 快速启动（Windows）

```powershell
cd D:\CTF-worktrees\p0-p1-frozen\backend
python -m pip install -e ".[dev]"

cd ..\frontend
npm install

cd ..
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\freeze-start.ps1
```

打开：

- 前端：`http://127.0.0.1:15190/`
- 后端健康：`http://127.0.0.1:18110/api/health`

停止：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\freeze-stop.ps1
```

独立运行使用 `.local-run\data` 和 `.local-run\run`，不会复用其他工作区的 SQLite 数据库，也不使用 8000/8001/8002/5173/5174 端口。

## 首次使用

1. 打开前端，在「比赛项目设置」创建项目。
2. 在「＋ 创建题目」创建题目，并选择 AI 使用等级。工具申请需要 A2。
3. 点击右上角「模型服务设置」，填写自己的 DeepSeek API Key，保存配置。
4. 默认联网关闭；需要模型联网时在设置页显式开启。
5. 导入题目附件，勾选外发确认后让 AI 分析。
6. AI 可提出只读工具申请；在「本地工具审批」中先批准，再单独点击执行。
7. 工具输出会作为 Artifact 进入事件链，可选择后交给 AI 继续分析。
8. 人工确认 Flag（只记录 SHA-256 和长度），生成 Writeup 并导出证据 ZIP。

## 文档

- [INSTALL.md](INSTALL.md)：Windows 安装与启动
- [USER_GUIDE.md](USER_GUIDE.md)：完整操作指南
- [MODEL_API_SETUP.md](MODEL_API_SETUP.md)：DeepSeek API 配置
- [SECURITY.md](SECURITY.md)：安全边界与数据处理
- [FREEZE_INTEGRATION_AUDIT.md](FREEZE_INTEGRATION_AUDIT.md)：P0/P1 整合审计
- [FREEZE_ACCEPTANCE_REPORT.md](FREEZE_ACCEPTANCE_REPORT.md)：冻结验收报告
- [FREEZE_FILE_MANIFEST.md](FREEZE_FILE_MANIFEST.md)：文件清单与 SHA-256

## 测试

```powershell
cd backend
$env:CTF_MODEL_NETWORK_ENABLED='false'
$env:CTF_RUN_LIVE_MODEL='0'
python -m pytest -q -rs
python -m ruff check app tests

cd ..\frontend
npm test
npm run build
$env:CTF_E2E_CHANNEL='msedge'
npx playwright test --config=playwright.ai.config.ts
```

测试使用 Mock Provider/隔离 FastAPI 和合成数据，不是真实模型测试。安全专项脚本位于 `scripts/verify-p1-*.ps1`。

## 状态

冻结候选，未提交、未推送、未合并；等待人工独立验收。最终验收状态见 `FREEZE_ACCEPTANCE_REPORT.md`。
