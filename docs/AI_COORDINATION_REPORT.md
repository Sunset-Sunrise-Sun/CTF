# Codex 工程集成与回归交付

日期：2026-11-09（任务开始于 2026-11-08）。整体状态：**NO-GO，尚未达到真实题目人工解题验收标准**。本次完成 Codex 的独立工作区、补丁核验集成、前端审查、权限契约、任务拆分、契约同步和实际离线回归；不把 DeepSeek 待实现任务计为完成。

## 1. 版本、工作区和保护

- 远端 PR #9 HEAD：`30eeed6dcc180ae21b5648f25047c5889e3c434a`，Draft / Open，目标 feat/p1-2-a00-integration；审查开始时通过 GitHub 核实。
- 本地工作区：`C:\Users\28746\.codex\worktrees\ctf-ai-coordination-ready\p1-2a-audit`。
- 分支：`codex/ai-workbench-convergence`；HEAD 仍为上述基线。全部修改未提交；无新 commit SHA，未推送或合并。交付快照须同时使用 integration.patch 和 SHA256SUMS，不能把基线 HEAD 当成修改后的提交。
- 原仓库工作区中两个已有未跟踪文件保留。原 CTF-MVP-A00、CTF-PR9 源目录和验收数据均未改写。
- 开始/结束核查均观察到原服务：8000 PID37196、8001 PID7804、8002 PID55984、5173 PID53204、5174 PID53372；未停止或重启它们。
- 测试只管理自己启动的 18002/15174，禁止复用；结束后未发现这两个测试端口继续监听。

首次 managed worktree 创建因 partial clone 缺少 blob 失败；仅补齐 Git 对象后重新创建成功，未 reset/merge/rebase 原工作区。无删除操作。

## 2. 补丁集成

用户原始文件 `C:\Users\28746\Documents\Codex\CTF-PR9-30eeed6-changes.diff` 存在，实际 SHA-256 与预期完全一致：

`475702f29ee38a64b4a36451eb4cec48812f89acb92ab894f5fb5dcee248326e`

`git apply --check` 在固定 HEAD 上成功，8 文件补丁仅应用到独立 worktree。没有冲突、没有猜测重建补丁、没有覆盖源目录。补丁中的测试文件末尾多余空行另作最小清理，原补丁保持原字节。审查详情见 FRONTEND_AUDIT.md。

另外完成：schema_cli 注册三个 AI 请求/响应模型；重新导出 openapi.json 和 contracts.json；增加两个契约一致性测试；增加真实本地 API 拒绝及桌面/390px 布局截图测试；AI E2E 改为每次全新绝对临时数据目录并隔离 TEMP/TMP/TMPDIR。该测试配置可能被 Playwright 在 worker 中再次求值，日志中可有额外空临时根目录；真正后端使用主进程配置创建的数据根，不复用旧目录。临时目录保留，未删除。

## 3. 当前快照的实际测试

环境：Windows、Python 3.14.7、Node v24.19.0、npm 11.17.0。后端命令在 backend 下执行；前端命令在 frontend 下执行；KAT 在仓库根目录执行。真实模型测试强制关闭：CTF_RUN_LIVE_MODEL=0、CTF_MODEL_NETWORK_ENABLED=false。

| 检查 | 原始固定基线 | 集成候选实际结果 |
|---|---|---|
| `python -B -m pytest -q -rs -p no:cacheprovider --basetemp <独立目录>` | 211 passed / 3 skipped | **214 passed / 3 skipped** |
| `python -B -m ruff check app tests` | 未单列本地基线结果 | **All checks passed** |
| `npm test` | 41 passed | **46 passed / 0 failed** |
| `npm run build` | 通过 | **通过，含 vue-tsc 检查** |
| `npm run test:e2e:ai` | 首次因缺浏览器执行文件失败，未冒称通过 | **4 passed**，独立 FastAPI/Vite/Chromium |
| Python KAT runner | 不引用历史结果 | **195 frozen cases + 6 fresh-process checks PASS** |
| Node KAT runner | 不引用历史结果 | **195 frozen cases + 6 fresh-process checks PASS** |
| compare_reports.py | 不引用历史结果 | **195 exact frozen results PASS**；56 正向、139 精确错误码；完整 bytes/MAC 相同 |
| STREAM_CONTENT_V1_KAT_SHA256SUMS | 原始冻结文件 | **4/4 匹配，fixture 与脚本未修改** |
| `git diff --check` | — | **通过** |

三个 skip：Windows symlink 权限不足两条、真实 Provider 测试未授权一条。skip 不计入通过。npm ci 提示 esbuild postinstall 未列入 allowScripts，但实际 Vite 构建成功；没有自行修改安装批准配置。首次 AI E2E 的环境失败日志保留；之后只在证据目录安装独立 Playwright 浏览器缓存并重跑成功，不改系统浏览器或既有服务。

### E2E 的真实与替身边界

1. 新增用例：真实独立 FastAPI 创建合成题目、拒绝跨题目确认（409）、事件仍为空；真实 UI 桌面和 390px 无横向溢出并截图。
2. 原用例：真实服务联网关闭，UI 禁止发送，API 返回 503。
3. 补丁用例：真实创建题目，但模型状态/聊天响应采用浏览器路由替身，检查确认隔离与请求 cid；不是模型联网测试。
4. 补丁历史用例：历史事件采用浏览器路由替身，检查按题目显示；不是服务端多轮持久化的动态验收。后端 MockTransport 两轮契约测试在 pytest 内另行执行。

本次没有任何真实 DeepSeek 请求，没有使用真实 API Key。测试凭证均为已有测试里的 synthetic 字符串。离线 KAT 通过不代表生产流式审计完成。

### 未执行的旧全流程 E2E

未直接运行普通 `npm run test:e2e`：其配置和多处测试固定连接 8000/5173，且草稿断网测试能停止配置 PID。直接运行会违反本任务对原有环境的保护。FE-07 任务要求先参数化所有 API、子窗口 origin 和受控进程，再在新环境运行全部旧业务 E2E。这里明确记为未执行，不写成全套浏览器回归通过。

## 4. 数据和协议兼容性

`git diff --exit-code HEAD -- backend/app/migrations backend/app/models.py backend/app/store.py backend/app/artifacts.py tests/fixtures scripts/kat` 返回 0：未修改 001/002、Event canonical、Store、ArtifactStore 或冻结 expected，没有新增 003/004。

新增必填 consent_challenge_id 是 API 行为变化：未携带返回 422，跨题目返回 409。前后端必须使用同一候选快照，旧前端不可直接接新后端。schema 一致性测试保证文档包含实际三条模型路由和该必填字段；没有新增工具执行接口。

## 5. 剩余阻断与交接

| 项目 | 当前状态 / 后续责任 |
|---|---|
| 所有入口完整调用审计 | 未完成；DeepSeek AI-S01，尤其无题目的 /model/test 系统审计与失败闭环 |
| Writeup / ai_disclosure 准确披露 | 未修复；DeepSeek AI-S02，当前仍存在旧的“未联网”文字 |
| 旧 CLI 绕过网络开关/绝对数据根 | 未修复；DeepSeek AI-S01 |
| A1/A2 后端权限差异 | 用户已确认契约，**未实现**；AI-S03 |
| 完整请求预算、敏感字段和不可信上下文 | 未完成；AI-S03/04 |
| 题目刷新、导出异步竞态 | 已审查并形成复现条件，未修复；FE-S01 |
| 前端模块拆分 | FRONTEND_AUDIT 已交付；未重写 App.vue，FE-S02 待执行 |
| 本地工具与可信审批 | 未实现；DisabledBroker / execution_enabled=false 保持；先 T-D01 安全设计 |
| 真实合成模型连通性 | 未执行；需授权与合法凭证，不能用本次 Mock 或状态接口替代 |
| 最终 AI→审批→工具→Writeup→ZIP 演示 | 未执行；生产工具不可用，不能生成伪造演示 ZIP |

详见 NEXT_STAGE_TASKS.md 的文件所有权、依赖顺序和每项退出条件。本次没有可调用的 DeepSeek 会话连接，因此只交付可直接下发的任务单，不冒称 DeepSeek 已接单或完成。此处属于 Codex 工程交付，完整产品开发仍在进行；不批准 PR 合并或真实比赛使用。

## 6. 证据位置

外部交付目录：`C:\Users\28746\Documents\Codex\2026-11-07\ctf-agent-workbench-p0-https-github\outputs\ai-optimization-20261108`。

其中包含实际测试日志、两份 KAT actual、跨语言比较、桌面/手机截图、完整 integration.patch（含新增文件）、源码快照及小型证据包、文件清单和 SHA256SUMS。Playwright 浏览器缓存及合成测试数据库不打入交付包；不把任何实际题目、Key 或验收数据库加入源码包。最终交付状态为待审查、未提交。
