# P0 统一验收脚本与证据

本目录只包含合成数据验收，不读取真实 API Key、不联网、不使用真实比赛题目。

## 脚本

| 脚本 | 用途 |
|---|---|
| `run_http_acceptance.py` | 启动隔离 uvicorn（127.0.0.1:18080，独立数据目录），用外部 httpx 执行真实 HTTP 工具/审计/披露闭环，生成 `evidence/transcript.json` 与 `evidence/results.json` |
| `run_fault_injection.py` | 用 SQLite 触发器精确注入 `tool_started`/`tool_finished`/`artifact_added`/审计 finish/`model_call` 事件写入失败，验证回滚与启动恢复；生成 `evidence/fault-results.json` |
| `build_manifest.py` | 生成 `docs/P0_UNIFIED_FILES.md` 与 `docs/P0_UNIFIED_SHA256SUMS` |

## 复现

```powershell
cd D:\CTF-worktrees\unified
$env:PYTHONPATH='D:\CTF-worktrees\unified\backend'
python -B verification\run_http_acceptance.py
python -B verification\run_fault_injection.py
python -B verification\build_manifest.py
```

`run_http_acceptance.py` 会打印证据目录（`%TEMP%\p0-http-acceptance-*`）；本仓库 `evidence/` 保存了本轮实际运行的副本。

## 证据文件

- `evidence/transcript.json`：18 条 HTTP 请求/响应；
- `evidence/results.json`：19 项检查（19 PASS）；
- `evidence/server.stdout.log`/`server.stderr.log`：uvicorn 子进程输出；
- `evidence/fault-results.json`：6 项故障注入（6 PASS）；
- `evidence/backend-pytest.log`：最终后端全量 pytest；
- `evidence/ruff.log`：最终 ruff；
- `evidence/frontend/logs/`：前端 npm test/build/E2E 原始日志；
- `evidence/frontend/*.png`：1440px/390px 工具面板、AI 面板、真实后端工具执行截图。

## 边界

- E2E 使用系统 Edge（离线环境无法下载 bundled Chromium）；默认 Playwright 配置仍为 chromium。
- 真实 DeepSeek 联网、真实 API Key、真实题目/Flag 未执行。
- 结果只证明本候选在合成数据下的行为，不代表平台验证或生产可用。
