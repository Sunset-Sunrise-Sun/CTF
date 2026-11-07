# P0 运行与交接

## 安装和启动
需要 Python >=3.11、Node >=22.12、npm。
在仓库根目录执行：
```powershell
python -m venv .venv
.venv/Scripts/Activate.ps1
python -m pip install -e './backend[dev]'
cd frontend
npm ci
cd ..
./scripts/backend.ps1
```
另一终端运行 `./scripts/frontend.ps1`，打开 http://127.0.0.1:5173 。
Linux/macOS：在 backend 运行 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`；在 frontend 运行 `npm run dev`。
Swagger: http://127.0.0.1:8000/docs ，OpenAPI: http://127.0.0.1:8000/openapi.json 。
服务只绑定回环地址；这是单用户本地开发服务，尚未实现身份认证。不要将其暴露给其他主机。

默认数据位于仓库 `.local-data/`，`CTF_DATA_DIR` 可指定绝对本地路径。不要将其设置到版本控制目录。
首次启动应用迁移 SQL；schema_migrations 记录版本。后续增加编号 SQL 文件，不修改已应用迁移。
升级前停止服务并备份整个数据目录；当前未提供降级迁移。

## 验证
`./scripts/check.ps1` 或在 backend 执行 `python -m pytest -q`、`python -m ruff check app tests`，在 frontend 执行 `npm run build`。
合成五类题目元数据见 backend/tests/fixtures/challenges.json；测试使用临时目录，不使用比赛附件、Flag、目标或真实凭证。

## P0 可用范围
创建五类题目、独立解题/Writeup 状态、工作区目录、追加用户笔记、回溯标签、查看事件和完整性校验。
公共 API 不允许客户端写入 actor/type/time/hash，因此无法通过笔记接口伪造 broker 执行记录。
Provider 通过独立显式 CLI 调用；Web API 不开放模型网络调用。工具注册表为空，即使批准也拒绝执行。

## 未完成事项
- 附件导入、内容寻址证据持久化和只读原件（目前提供 Artifact 契约；无附件上传 API）。
- 工具提案/审批持久化、真实执行生命周期、输出捕获、隔离容器和运行数量限制；当前禁用全部执行，配置最多三个容器。
- 五类 playbook、完整 Agent、外部模型调用 UI、流式调用审计接入。
- Anthropic 原生 Messages 通信；目前其接口明确返回 adapter_not_implemented。
- 确定性 Writeup/Markdown/PDF 生成器、W01–W10 完整验收、敏感信息识别与导出脱敏。
- 真 Provider 接入测试：需要合法配置凭证；当前未验证。
- 身份认证、备份恢复自动化、外部完整性签名/检查点和可迁移的权限隔离。

不允许依赖此 P0 执行不可信二进制；路径检查是应用级边界，并非 OS sandbox。路径检查与文件访问之间仍存在 TOCTOU 风险，后续执行器必须使用隔离文件系统。
