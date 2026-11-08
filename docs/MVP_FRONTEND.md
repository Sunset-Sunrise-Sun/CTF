# MVP 前端工作台（Codex / Part A）

**当前版本为 Phase C-5：人工稿已支持服务器保存、版本冲突处理及最终 ZIP 闭环。固定后端为 `6827791f1112a8308c9d705bbad0d6253655c6f5`；41 个单元测试、11 个真实浏览器用例通过，无跳过。最新接口、复现、文件清单、风险及原始输出见 [MVP_FRONTEND_C5.md](MVP_FRONTEND_C5.md)。**

以下首轮和上一轮适配报告仅为历史证据。“人工稿只能本地保存/ZIP 不包含人工稿”等旧限制已被 C-5 替代，不代表当前实现。

## 基线与范围

- 基线：`96152b7a66e16d726d50bebb4d833167b140e19c`（PR #6）。
- 分支：`feat/mvp-frontend-workbench`，Draft PR 目标为 `feat/p1-2-a00-integration`；不自动合并。
- 首轮实际联调后端（历史记录；当前版本见文末适配节）：DeepSeek 分支 `feat/mvp-backend-workflow`，固定提交 `30cc4d078a58bfade34edfc6a5c8b475571ae05b`（PR #7）。该版本在独立临时目录运行，没有合入前端分支，没有修改其源码。
- 修改范围仅为 frontend 与本前端交付文档。main、PR #6/#7、后端代码、迁移与冻结 KAT 均不变。

## 已实现

| 任务 | 实现及来源 |
| --- | --- |
| 比赛项目 | GET/PUT /api/project，名称、类型、规则概要及 AI 限制；POST /api/project/rules，显示规则原件名、SHA256、大小和下载链接；规则由项目共享，不逐题重复上传 |
| 题目 | 真实 POST /api/challenges；名称、五分类、描述、分值、AI A0/A1/A2/unknown；未知等级明确阻止 Agent 功能流程。本轮所有等级都没有模型/工具调用入口 |
| ZIP | 选择/拖拽，XMLHttpRequest 上传字节进度；100% 只表示已发送，另行等待后端校验解压成功；失败保持失败状态，不把原件 Artifact 当成解压成功 |
| 文件浏览 | 使用后端增量 GET imports、GET import detail 重建清单，刷新仍可浏览；左侧文件索引、路径清单、数量、总解压大小、每个文件 SHA；使用 GET import files 读取原件 |
| 证据 | 真实 multipart 上传 evidence_kind 与可选 capture_time_claim；显示服务器 ingested_at、用户申报时间、来源事件、SHA256、大小、分类；分类去重保留后端原始元数据，不擅自改写 |
| 预览 | PNG/JPEG/GIF/WebP 使用原始 Blob URL；文本/脚本仅插值展示；不渲染 HTML/SVG、不运行代码；图片 10 MiB、文本 1 MiB 硬预览限制，检查 Content-Length 和实际流字节；大文件可下载原件 |
| 人工运行 | 命令、目录、目的、可空退出码、结果说明和可选用户申报时间，POST manual-operations；显著标注人工申报、非工作台执行、未验证。提供复制命令流程及仅供手动参考的 Docker 命令 |
| 时间线 | 按真实 sequence 排序，显示服务器时间、actor、原 event_type、payload、事件/Artifact ID、event hash；建议不转换成人工执行。人工记录、AI 建议、历史工具事件、观察、验证申报分别标识 |
| 完整性 | GET integrity；成功只表述“事件链一致”，不认证执行、Flag 或截图真实性；失败显示 earliest_affected_sequence |
| Writeup | GET writeup/preview，显示真实 missing_requirements/warnings，九章节初稿来自后端；人工 Markdown 编辑，按 Challenge ID 在 localStorage 隔离持久化；不覆盖已有人工草稿；放弃草稿需确认 |
| 导出 | 人工 Markdown Blob 下载、浏览器打印/保存 PDF、真实 GET export 下载证据 ZIP；显示完整/不完整，人工编辑一律待复核；无预览状态一律未校验/不完整 |
| 刷新与错误 | 后端数据从 API 恢复；当前题目 ID 和人工草稿在浏览器恢复；HTTP 错误细节可见；上传超时/断连标为结果未知、提示刷新核对，不自动重试有副作用请求 |

布局为顶栏比赛/题目/模式、左侧题目/文件/证据、中间题目/文件/运行/时间线/Writeup、右侧规则/建议/人工笔记。窄屏改为纵向布局。没有新增运行时 UI 库或外部字体/CDN；新增依赖仅为锁定的开发测试依赖 @playwright/test 1.65.0。

## 重要交互语义

1. AI 建议仅显示既有 agent/plan/hypothesis/proposal 事件，不生成演示建议，也不会作为 human_action 入库。历史 tool/command started/finished 只展示原记录，本轮不产生此类事件。
2. verified_result 标为“验证申报，非独立认证”，不会将服务端事件链校验当成 Flag/平台验证成功。
3. ingested_at 是服务器时间；capture_time_claim、started_at_claim、finished_at_claim 明确为用户申报。人工思路和回溯笔记追加事件，不改写历史。
4. 人工编辑仅保存在当前浏览器，可能包含敏感解题内容；界面提醒其本地范围，建议及时下载。服务器原始证据不因编辑改变。
5. **证据 ZIP 包含服务器初稿，不包含浏览器人工编辑稿。** 现有后端没有草稿保存接口，前端不擅自创造接口或修改后端；界面和下载完成提示均明确要求另存人工 Markdown。这是当前明确限制，不是“人工稿已归档”。
6. PDF 使用安全的 Markdown 文本打印样式（不是 HTML Markdown 渲染器）；保留原文字、缺失标记和复核状态，隐藏操作表单/侧栏。测试实际生成打印样式 PDF；未自动操作系统打印对话框。

## 本地启动

使用两个独立检出目录，分别运行固定后端分支和本前端分支，不需要合并任何 PR。

后端目录（PR #7 固定提交）：

```powershell
$env:CTF_DATA_DIR = 'C:\path\to\new-empty-synthetic-data'
$env:CTF_RUN_LIVE_MODEL = '0'
cd backend
python -m pip install -e '.[dev]'
python -B -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

前端目录（本分支），已测试 Node 24.19.0、npm 11.17.0：

```powershell
cd frontend
npm ci
npm run dev -- --port 5173 --strictPort
```

访问 http://127.0.0.1:5173 。Vite 现有代理将 /api 发送到 127.0.0.1:8000。`npm run build` 是生产静态构建；生产部署需要反向代理 /api 到本地 FastAPI，不能假定 Vite preview 会提供开发代理。后端无认证，仅限本地单用户运行。

测试：

```powershell
npm test
npm run build
npm run test:e2e
```

E2E 使用本机已安装的 Microsoft Edge (`channel: msedge`)，后端和 Vite 必须按上述端口先启动。需 Node 支持直接载入可擦除 TS 类型（测试环境 Node 24）；没有浏览器时应安装 Edge 或调整测试 channel，不能把无法运行记为通过。E2E 会向该本地后端写入合成项目/题目/证据，须使用隔离空白数据目录，不能指向日常比赛数据。

## 首轮实际测试与验收映射（历史记录）

最终测试日期：2026-11-08（Asia/Shanghai）。后端独立进程从新的 `work/mvp-acceptance-empty-data` 目录启动。未执行题目脚本、人工申报中的命令或 Docker；合成 PNG 是分类/预览测试素材，不是真实 Flag/平台截图。

| 检查 | 实际结果 |
| --- | --- |
| npm ci --no-audit --no-fund | exit 0；保留 npm 的 esbuild install-script 提示 |
| npm run build | TypeScript + Vite 成功 |
| npm test | 10 passed，0 failed，0 skipped |
| npm run test:e2e | 2 passed，0 failed，0 skipped；真实本地 FastAPI + Edge，无 API mock |
| 实际下载 ZIP SHA256SUMS | 13/13 匹配 |
| ZIP Artifact 原件 | 4/4 对照 manifest SHA256 匹配 |
| 导出事件 | 7 条按 sequence 排序；1 条 manual_external / execution_verified=false；0 条 tool execution |
| 不完整性 | ZIP 存在 INCOMPLETE.txt；AI 等级 unknown；人工编辑稿没有悄悄混入服务器 ZIP |

10 个单元测试覆盖：人工申报标签、agent 不得冒充 human、proposal 非执行、缺失/矛盾完整性、编辑必须复核、草稿隔离、中文 URL 编码、HTTP 验证细节、声明长度超限与流式字节超限。

正向 E2E 实际走完：项目创建 → PDF 规则上传 → 五分类之一创建题目/unknown AI 禁用 → ZIP 上传并显示两个文件 → Python 文本预览 → 人工申报及事件链校验 → 三类合成 PNG 上传/图像解码预览 → 人工思路笔记 → 后端 Writeup 九章节初稿 → 人工编辑 → Markdown 下载 → 证据 ZIP 下载 → 浏览器刷新后恢复文件树与人工草稿 → 打印样式 PDF / 桌面与 390px 窄屏截图。未进行实际解题或真实 Flag 验证。

负向 E2E：真实后端拒绝无效 ZIP，界面显示 **422 / Uploaded file is not a valid ZIP archive**，保持失败提示，没有导入目录清单。开发时测试曾有等待加载时序、select label 精确定位、隐藏打印状态重复定位、误写 400 等问题，均修正后从空白目录重新执行；没有把中间失败当作通过。

截图/PDF/原始日志及实际下载文件保存在交付包（outputs/MVP-frontend-evidence.zip）；测试重跑会在 frontend/test-results/demo 自动生成。测试产物被 frontend/.gitignore 忽略，不会提交真实附件、截图或生成 Writeup。原始命令输出附于本文后。

## 文件清单

- frontend/src/App.vue：单页工作台与交互、真实接口编排。
- frontend/src/api.ts：JSON 请求、真实 multipart 上传进度、有界预览、下载。
- frontend/src/domain.ts：接口类型、来源标签、完整性和路径/草稿辅助函数。
- frontend/src/style.css：桌面/窄屏/打印样式。
- frontend/package.json、frontend/package-lock.json：测试脚本及锁定测试依赖。
- frontend/playwright.config.ts：Edge 真实 API 集成配置。
- frontend/tests/domain.test.mjs：10 个单元用例。
- frontend/tests/workbench.spec.ts：2 个真实 API 浏览器用例及合成素材。
- frontend/.gitignore：忽略本地测试产物。
- docs/MVP_FRONTEND.md、docs/MVP_FRONTEND_SHA256SUMS：本报告与文件校验和。

## 未实现与风险

- 没有模型联网/新建议生成；只能展示已有建议。没有任意命令执行、Docker 自动构建、扫描、Flag 提交或真实审计密钥。
- 人工 Markdown 没有服务器保存/ZIP 合并接口，编辑不作为已审核证据；本地存储清除会丢失草稿。不同浏览器/端口的草稿不共享。
- 正式前后端整体部署仍依赖 PR #7 与本 PR 在独立验收后由维护者整合；本 PR 基线后端只有 P1-1，直接运行它会明确暴露新增 API 404，不能声称旧后端已支持 MVP。
- 只实际测试 Windows / Edge，不声明其他浏览器、Linux、生产部署或 OS 打印对话框通过。既有后端全量测试结果属于 DeepSeek 报告，本交付没有冒充重跑后端全部测试。
- 超过预览预算的文件只下载原件；打印为安全原始 Markdown 文本。证据与截图真实性需要外部复核，哈希链不防本机所有者重写全库。

完成后停止，保持 Draft，等待独立验收；不修改或合并 PR #6/#7。

## 首轮原始命令与输出（历史记录）

### npm-ci

```text
$ npm.cmd ci --no-audit --no-fund

added 48 packages in 3s
npm warn allow-scripts 1 package has install scripts not yet covered by allowScripts:
npm warn allow-scripts   esbuild@0.28.2 (postinstall: node install.js)
npm warn allow-scripts
npm warn allow-scripts Run `npm approve-scripts --allow-scripts-pending` to review, or `npm approve-scripts <pkg>` to allow.

exit_code=0
```

### build

```text
$ npm.cmd run build

> ctf-workbench-ui@0.1.0 build
> vue-tsc --noEmit && vite build

vite v7.3.7 building client environment for production...
transforming...
✓ 13 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                  0.34 kB │ gzip:  0.25 kB
dist/assets/index-CbN69aTG.css   5.62 kB │ gzip:  1.97 kB
dist/assets/index-BHsryBM4.js   96.20 kB │ gzip: 37.13 kB
✓ built in 782ms

exit_code=0
```

### unit

```text
$ npm.cmd test

> ctf-workbench-ui@0.1.0 test
> node --test tests/*.test.mjs

✔ manual claims never become verified execution (1.0593ms)
✔ agent text cannot masquerade as human execution (0.1558ms)
✔ proposal is never an execution (0.1162ms)
✔ missing or contradictory completeness fails closed (0.1439ms)
✔ edited report is always subject to review (0.1034ms)
✔ drafts are isolated by challenge (0.1383ms)
✔ file path segments encode URLs without query injection (0.1274ms)
✔ API reports validation detail and preserves HTTP status (24.7549ms)
✔ declared oversized preview is cancelled (1.3332ms)
✔ chunked preview cannot bypass byte cap (2.0086ms)
ℹ tests 10
ℹ suites 0
ℹ pass 10
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 193.5861

exit_code=0
```

### e2e

```text
$ npm.cmd run test:e2e

> ctf-workbench-ui@0.1.0 test:e2e
> playwright test


Running 2 tests using 1 worker

(node:49824) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
  ok 1 tests\workbench.spec.ts:11:1 › real FastAPI: full synthetic manual workflow, reload and downloads (4.2s)
  ok 2 tests\workbench.spec.ts:206:1 › real API rejection remains a failure in the UI (626ms)

  2 passed (6.4s)

exit_code=0
```

### 实际下载后核验

```json
{
  "downloaded_zip_sha256": "e5b5ff9fba73853dfee9ca9c316fa666b2c7a8def466e0a6e6b835faf4da3e11",
  "SHA256SUMS_entries_verified": 13,
  "artifact_original_bytes_verified": 4,
  "event_count": 7,
  "manual_claim_not_verified": true,
  "tool_execution_events": 0,
  "incomplete_marker_present": true,
  "local_editor_not_silently_in_server_zip": true,
  "backend_commit": "30cc4d078a58bfade34edfc6a5c8b475571ae05b"
}
```

## PR #7 修复适配（当前版本，2026-11-08）

固定后端升级到 aa35e919533af1c5db7cbc2e037e98127e9502a3，独立运行目录的全部 backend/app 文件已逐一对照 Git blob SHA 校验一致；不修改或合入后端代码。Git lazy-fetch 曾连接失败，改用已连接 GitHub 接口读取固定版本原始文件并逐项校验 Git blob SHA 后才进行最终联调。初次启动的混合快照结果不计为新版通过。

### 适配内容

- 新增显式笔记类型选择：普通笔记 kind=note、核心解题思路 kind=approach。默认普通笔记，切换题目恢复默认；不将既有普通笔记自动升级为解题思路。生成初稿时显示服务器返回的 core_approach/core_code/execution_evidence 等缺失项，不自行猜测满足状态。
- ImportRecord 增加 manifest_verified / integrity_error。只有明确 verified 的记录才请求详情或展示文件入口；缺失状态按未校验处理（需要新版后端）。列表中不可信记录仍可见并显示错误原因，文件列表清空；单条详情 409/其他错误只降级该条，不阻断其余导入。刷新时清除旧文件预览与旧清单，避免继续显示失效内容。
- 导出完成提示与文件名采用实际响应 X-Dossier-Completeness；incomplete/缺失响应头会把本次显示状态降为不完整，不能用预览先前的 complete 掩盖导出快照异常。ZIP 格式与多次导入目录完全由后端提供，前端不硬编码原 ZIP 路径。
- 人工编辑稿仍只存浏览器；导出 ZIP 保留服务器初稿。这一既有明确限制没有改变。

### 当前实际验证

- npm run build 成功；npm test：15 passed、0 skipped；npm run test:e2e：3 passed、0 skipped。
- 新增 5 个单元用例：未验证列表禁止详情/文件、单条 409 不阻断正常记录、缺失或降级校验状态拒绝文件、实际 incomplete 覆盖 complete 预览、缺失导出响应头保守降级。
- 在新版后端的空白隔离目录 work/mvp-reviewed-release-empty-data 重新执行完整流程；正向用例明确选择 approach 后提交思路，原始下载 ZIP 的 13 项 SHA256SUMS 及 4 项 Artifact 原件哈希复核一致。
- 第三个浏览器测试显式使用 CTF_TEST_DATA_DIR 指向该隔离合成目录，创建两次导入，仅破坏自己创建的第一份 Manifest。实际 UI 保留异常记录、显示错误且无文件入口，没有请求其详情；第二份导入仍有可访问文件。测试不修改历史用户数据，不生成真实证据。
- 运行第三个 E2E 前须设置 `$env:CTF_TEST_DATA_DIR = <与隔离后端 CTF_DATA_DIR 相同的绝对路径>`。未设置时会明确 skip，不能计为通过。本次已设置并实际通过。第一、二个 E2E 仍分别验证完整人工流程和真实 422 拒绝。
- 本轮依赖及 lockfile 未变，未重复 npm ci；首轮 npm ci 结果保留在历史记录。没有重跑后端全量测试，也不以 DeepSeek 报告替代前端联调。
- 仅更新既有前端 PR #8，不新建 PR、不合并、不修改 PR #6/#7 或 main。修订证据包为 outputs/MVP-frontend-review-evidence.zip；早期证据包是旧后端的历史快照。

### 当前原始命令输出

```text
$ npm.cmd run build

> ctf-workbench-ui@0.1.0 build
> vue-tsc --noEmit && vite build

vite v7.3.7 building client environment for production...
transforming...
✓ 13 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                  0.34 kB │ gzip:  0.25 kB
dist/assets/index-CbN69aTG.css   5.62 kB │ gzip:  1.97 kB
dist/assets/index-DnxVGPbT.js   97.45 kB │ gzip: 37.51 kB
✓ built in 920ms

exit_code=0
```

```text
$ npm.cmd test

> ctf-workbench-ui@0.1.0 test
> node --test tests/*.test.mjs

✔ manual claims never become verified execution (1.3624ms)
✔ agent text cannot masquerade as human execution (0.2183ms)
✔ proposal is never an execution (0.1442ms)
✔ missing or contradictory completeness fails closed (0.1588ms)
✔ edited report is always subject to review (0.1492ms)
✔ drafts are isolated by challenge (1.0758ms)
✔ file path segments encode URLs without query injection (0.268ms)
✔ API reports validation detail and preserves HTTP status (27.6569ms)
✔ declared oversized preview is cancelled (1.8293ms)
✔ chunked preview cannot bypass byte cap (2.773ms)
✔ unverified manifest never fetches details or exposes stale files (1.7641ms)
✔ one 409 preserves other verified imports (0.2769ms)
✔ unknown or downgraded verification never exposes files (0.204ms)
✔ actual incomplete export overrides complete preview (0.335ms)
✔ missing export header fails closed; complete header cannot remove missing requirements (0.4316ms)
ℹ tests 15
ℹ suites 0
ℹ pass 15
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 233.3772

exit_code=0
```

```text
$ npm.cmd run test:e2e

> ctf-workbench-ui@0.1.0 test:e2e
> playwright test


Running 3 tests using 1 worker

(node:52668) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
  ok 1 tests\workbench.spec.ts:13:1 › real FastAPI: full synthetic manual workflow, reload and downloads (4.5s)
  ok 2 tests\workbench.spec.ts:209:1 › real API rejection remains a failure in the UI (654ms)
  ok 3 tests\workbench.spec.ts:238:1 › real unverified manifest stays visible without blocking sibling import (801ms)

  3 passed (7.8s)

exit_code=0
```
