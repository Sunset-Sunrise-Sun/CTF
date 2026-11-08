# Phase C-5：人工稿持久化与最终 ZIP 闭环（Codex）

## 固定版本与范围

- 前端从 PR #8 的 `c62dd9fed36fc1459cbc5c6e3b409a15328ab34e` 追加开发，分支仍为 `feat/mvp-frontend-workbench`，目标仍为 `feat/p1-2-a00-integration`；不新建或合并 PR。
- 真实联调后端固定为 `6827791f1112a8308c9d705bbad0d6253655c6f5`。已读取该版本 MVP_BACKEND.md §4.10、MVP_WRITEUP_ACCEPTANCE.md 和 OpenAPI。运行目录的 17 个 app 文件均按 Git blob SHA 校验，没有修改后端源码或接口。
- 仅修改前端实现、测试及前端交付文档。不修改 main、PR #6/#7、迁移或冻结 KAT；未将 PR #7 合入本前端分支。最终提交 SHA 在 PR #8 和本地交付元数据中给出。

## 接口与状态设计

唯一人工稿路径为 `/api/challenges/{cid}/writeup/draft`：GET 200 恢复 `content/version/sha256/size/saved_at`，404 仅表示无人工稿；PUT 仅发送 `{content, base_version}`，创建 201、更新 200、冲突 409、超限 413、无效 422。保留 ApiError 的结构化 `detail`，409 读取 `detail.current`，不从错误字符串猜测版本。

`DraftSession` 独立于 Vue 和 HTTP，负责编辑状态；API 调用由固定路径注入。保存状态区分未保存、正在保存、已保存（版本）、保存失败和版本冲突；载入状态独立区分 loading/ready/unavailable。显示服务器版本、实际 saved_at、SHA256、size 和当前编辑内容 UTF-8 字节数。JSON 请求 30 秒超时，失败可能结果未知，明确提示重新读取核对。

### 加载与旧稿

| 状况 | 行为 |
| --- | --- |
| 服务器无稿，浏览器无稿 | 初始 base_version=0；用户可新建人工稿或生成初稿后编辑 |
| 服务器无稿，浏览器有旧稿 | 保留原始 localStorage key `ctf-workbench:draft:v1:<cid>`，显示“发现本地未同步的人工稿，是否保存到服务器？”；仅点击确认迁移才以 base_version=0 保存 |
| 服务器有稿，无本地稿 | 直接恢复服务器 content 与版本；刷新、新浏览器窗口均能读取，无需本地缓存 |
| 服务器有稿，本地不同 | 编辑器保留本地稿，展示服务器稿与版本；禁止直接保存，必须明确选择或合并 |
| GET 非 404 错误 | 显示错误，保留内存/缓存内容，base_version=null 禁止误以 0 覆盖；提供重新读取 |

### 保存、并发与缓存

- 每次输入保留 localStorage 草稿；另外保留当前窗口 sessionStorage 影子副本与编辑基准版本，避免同一浏览器的另一个窗口保存、清理共享缓存时，本窗口刷新丢失尚未保存内容。
- 成功响应后更新服务器版本与元数据；仅在已发送内容仍等于当前编辑内容时清理该稿缓存。若保存期间继续输入，保留新的输入并将其编辑基准更新到已确认的新版本，不把返回的旧文本灌回编辑器。
- 空白稿和超过 1 MiB UTF-8 的稿件在前端拒绝保存，不截断；同时实际 HTTP 测试确认后端分别返回 422/413。后端返回的保存错误仍保留当前内容与缓存。
- 409 不覆盖编辑器、不自动重试。展示 `current` 和本地稿；“采用服务器稿”是明确放弃本地编辑；“保留本地内容，按最新版本手动合并”只更新编辑基准，不提交，用户合并后再次点击保存。
- 版本冲突 current=null、相同缓存/服务器内容、读取完整性 409、存储配额异常等另有单元测试。完整性 409（没有 current）不会被伪装成可直接覆盖的版本冲突。
- 初稿刷新不会覆盖已有人工稿；服务器生成初稿在独立只读区域显示。放弃本地修改需确认，并重新读取服务器；不会删除服务器人工稿。

## 导出闭环

所有证据 ZIP 均通过真实 GET `/export` 下载，前端不组装、不修改 ZIP。

1. 当前编辑内容未保存时先弹出确认：ZIP 使用服务器已保存版本，若无人稿则使用初稿；不是当前未保存文本。
2. 导出前读取人工稿状态；无人稿明确提示初稿，完整性异常明确提示后端将 fallback/incomplete。并发期间最终来源与版本以 ZIP manifest 为准，不以导出前读取快照冒充最终内容。
3. 下载后采用实际 `X-Dossier-Completeness`；缺失响应头或 incomplete 保守降级。不因人工稿保存成功就宣称截图/事件证据完整。
4. 人工稿有效：`writeup.md` 与服务器 UTF-8 内容逐字节一致；`writeup_generated.md` 保留服务器初稿。manifest.writeup 的 final_source、version、sha256、size、saved_at 与 API 对照。AI 披露准确标识来源。
5. 无人稿和损坏稿：验证明确 fallback 注明、generated 初稿保留、损坏文本不泄露、INCOMPLETE 标记保留。
6. Markdown 下载保留当前编辑内容原字节编码，不额外添加状态前缀；状态在页面显示。打印 PDF 功能继续保留并由既有浏览器用例验证打印样式。

## 当前实际测试

2026-11-08，Windows + 已安装 Microsoft Edge，Node 24.19.0、npm 11.17.0、Python 3.14.7。新建隔离目录 `work/c5-runtime/data-final`，开始前 challenges=[]；后端 17 个 app 文件逐项核对固定 SHA。Vite 使用真实 /api 代理；所有 E2E 都访问真实 FastAPI，无 Mock API、无伪造 409/413/422 响应，也没有前端 route 注入假数据。

| 命令 | 实际结果 |
| --- | --- |
| npm ci --no-audit --no-fund | exit 0，依赖/锁文件未新增或变更；保留 npm esbuild 安装脚本提示 |
| npm run build | TypeScript + Vite 成功 |
| npm test | **41 passed / 0 failed / 0 skipped**；原 15 个用例保留，新增 26 个 |
| npm run test:e2e | **11 passed / 0 failed / 0 skipped**；原 3 个用例保留，新增 8 个 |

既有完整业务用例仅增加“未保存稿导出”的明确确认动作，未删除或降低原导入、预览、证据、人工记录、时间线、刷新、打印、导出检查。

### 新增真实浏览器用例

| 用例 | 核验结果 |
| --- | --- |
| 保存→刷新→修改→再保存→新窗口恢复 | 首次 201/v1、更新 200/v2；清除本地缓存后仍从服务器恢复；桌面和 390px 保存状态正常；分别下载 v1/v2 ZIP；v2 manifest.saved_at/sha256/size 与 GET 人工稿逐字段一致；人工稿保存不产生事件 |
| 证据齐全的合成档案 | 原 ZIP/解压文件、核心代码、三类合成 PNG、approach 与明确未验证的合成人工申报；保存人工稿后实际导出 **complete**；12/12 SHA256SUMS；最终稿/初稿字节、来源与版本全部正确 |
| 两个独立浏览器窗口冲突 | 同一 base v1，窗口 A 保存 v2，窗口 B 实际收到 409；本地文本保留，显示服务器 current；没有自动重试；手动合并后保存 v3。桌面/390px 冲突区无水平溢出 |
| 同浏览器配置的两个窗口 | 共享 localStorage，A 保存后 B 刷新仍保留未保存编辑，并看到与服务器的冲突，明确选择后保存；会话影子副本保护实测通过 |
| 旧本地稿迁移与双稿选择 | 404 时未自动 PUT；确认迁移请求 base_version=0 → 201；服务器/本地不同内容同时展示；采用服务器是显式选择 |
| 空稿与超限 | UI 保留文本且不发送非法 PUT；真实 HTTP 另行核验空稿 422、UTF-8 超过 1 MiB 为 413；服务器无意外稿件 |
| 无人稿/损坏稿 | 无人稿导出初稿并注明；仅破坏测试自己新建的 sidecar 内容，GET 实际 409；编辑器保留原文本；导出 fallback，incomplete，ZIP 不含 C5_TAMPERED |
| 实际后端断开 | 测试终止显式指定的本轮后端 PID，保存与读取实际连接失败；文本/缓存仍在；按同一固定 app 目录、同一测试数据目录重启真实 uvicorn，刷新后确认迁移，保存 v1 成功。不是仅模拟浏览器离线 |

PNG、人工操作申报、Flag/平台字段均为合成测试夹具，不能将结构性 complete 当成真实比赛事实或真实 Flag 已验证。测试没有执行附件，也没有真实模型、Docker Socket、Flag 提交或比赛平台请求。

### 五份实际 ZIP 的独立核验

Python 标准库 `zipfile/hashlib` 对真实浏览器下载做核验，不读取应用内部实现、不在测试运行时编造 expected 人工稿。人工稿 expected 是测试固定字符串；generated expected 来自导出前独立 HTTP GET preview；SHA256SUMS 覆盖集合必须恰为除其自身外所有文件，并逐文件重算。

| 文件 | 来源 | 结果 |
| --- | --- | --- |
| human-v1.zip | human v1 | 7/7，writeup.md 与固定 v1 字节相等，缺截图所以 incomplete |
| human-v2.zip | human v2 | 7/7，writeup.md 为刚更新的 v2，旧 v1 未被错用；初稿同时保留；incomplete |
| complete-human-dossier.zip | human v1，合成证据齐全 | 12/12，complete，manifest.final_source=human，最终稿/初稿/AI 披露/元数据全部核验 |
| no-human.zip | generated | 7/7，附“尚未保存人工稿”说明，incomplete |
| corrupted.zip | generated fallback | 7/7，integrity_error 非空，INCOMPLETE.txt 存在，未输出被篡改人工稿 |

每个 ZIP 的逐文件 expected/actual SHA、来源、版本、人工稿元数据均保存在同名 `.verification.json`；最终 ZIP、HTTP 请求/响应日志、PNG/PDF、原始测试命令输出见 `outputs/Phase-C5-frontend-evidence.zip`。不会将合成以外的附件、真实敏感请求或密钥加入 Git。

## 复现

分别运行固定 PR #7 后端与本 PR #8 前端。后端与前端目录独立，不要求合并 PR。后端需要 `6827791f...`，旧 aa35e91 没有本轮人工稿接口。

```powershell
# 后端目录；必须使用新的合成数据目录
$env:CTF_DATA_DIR='C:\path\to\isolated-c5-data'
$env:CTF_RUN_LIVE_MODEL='0'
python -B -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 本分支 frontend 目录；另一个终端
npm ci
npm run dev -- --port 5173 --strictPort
```

```powershell
# 同一个 frontend 目录，测试前显式填入本轮自有服务信息
$env:CTF_TEST_DATA_DIR='C:\path\to\isolated-c5-data'
$env:CTF_TEST_BACKEND_PID='<本轮自己启动的 uvicorn PID>'
$env:CTF_TEST_BACKEND_APP_DIR='C:\path\to\fixed-backend\backend'
# 可选：CTF_TEST_PYTHON 指向可运行该后端的 Python
npm run build
npm test
npm run test:e2e
```

**测试会实际停止指定 PID 并重启该固定后端，还会篡改它自己创建的合成稿件/Manifest。** 必须使用隔离目录与自有 PID，不能指向日常数据或未知进程。缺少所需环境变量时相关用例会明确 skip，不能计为通过；本次全部已配置并实际通过。重新启动的 PID 记录在 test-results/c5/restarted-backend.json。Windows/Edge 以及 Python 标准库是本次浏览器/ZIP核验的环境要求。

## 文件清单

- frontend/src/App.vue：读取/保存/迁移/双稿冲突界面、状态和导出提示。
- frontend/src/api.ts：保留结构化错误 detail；JSON 请求超时保护。
- frontend/src/drafts.ts（新增）：独立人工稿状态机与兼容缓存、窗口影子副本。
- frontend/src/style.css：保存状态/冲突区样式、窄屏可读布局。
- frontend/tests/drafts.test.mjs（新增）：26 个有针对性的单元用例。
- frontend/tests/drafts.spec.ts（新增）：8 个真实 HTTP/浏览器用例、截图、请求日志。
- frontend/tests/assert_draft_zip.py（新增）：独立字节、manifest、披露和全量 SHA256SUMS 核验。
- frontend/tests/workbench.spec.ts：保留原 3 个用例，加入未保存导出的明确确认动作。
- docs/MVP_FRONTEND.md：当前文档入口；旧报告标为历史。
- docs/MVP_FRONTEND_C5.md（新增）：本报告、复现、风险及原始输出。
- docs/MVP_FRONTEND_SHA256SUMS：更新全部前端交付文件校验和，自身除外。

## 限制、失败记录与未完成项

- 核心 Codex 任务已完成，没有未解释的应用测试失败。初次单元运行因 Node strip-only 不支持 TS parameter property 失败，已改为普通字段赋值，不删除测试；最终全部通过。
- 服务器只保存最新人工稿，本地前端没有引入历史稿件管理、多用户权限或自动合并。并发变更会要求显式选择/合并；选手仍需审核最终事实。
- 浏览器存储配额/清理、窗口会话关闭仍可能影响未保存文本；存储失败会提示并保留内存内容，应保存服务器或下载 Markdown。sessionStorage 影子副本保护本窗口刷新，不声称是持久化服务器备份。
- 前端采用契约默认 1 MiB 上限；后端若配置更低，真实 413 仍保稿；若配置更高，前端仍保守限制 1 MiB。
- 导出前读到的人工稿元数据只是快照，最终来源与版本以 ZIP manifest 为准。前端不自行拼包或偷偷把未保存文字放进 ZIP。
- 仅实际验证 Windows/Edge（390px 为桌面浏览器 viewport），不宣称实体手机、其他浏览器、生产多进程或多用户通过。保持打印能力，未自动操作 OS 打印对话框。
- 没有重复执行后端完整测试套件，也不把 DeepSeek 的后端报告冒充自己的结果；本报告证明固定后端上的真实前端联调与独立导出核验。
- 未引入产品中的浏览器/桌面控制、任意命令执行、模型联网、自动 Flag 提交。Playwright 和测试用服务启停仅属于隔离验收。

完成后保持原 Draft PR #8，等待独立验收，不合并任何 PR。

## 本轮原始命令输出

### npm-ci

```text
$ npm ci --no-audit --no-fund

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
✓ 14 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.34 kB │ gzip:  0.26 kB
dist/assets/index-CTAkXZ8U.css    5.94 kB │ gzip:  2.07 kB
dist/assets/index--dGklMJ0.js   105.93 kB │ gzip: 40.08 kB
✓ built in 697ms

exit_code=0
```

### unit

```text
$ npm.cmd test

> ctf-workbench-ui@0.1.0 test
> node --test tests/*.test.mjs

✔ manual claims never become verified execution (0.9918ms)
✔ agent text cannot masquerade as human execution (0.1591ms)
✔ proposal is never an execution (0.1084ms)
✔ missing or contradictory completeness fails closed (0.1163ms)
✔ edited report is always subject to review (0.8252ms)
✔ drafts are isolated by challenge (0.1666ms)
✔ file path segments encode URLs without query injection (0.1384ms)
✔ API reports validation detail and preserves HTTP status (20.6956ms)
✔ declared oversized preview is cancelled (1.1773ms)
✔ chunked preview cannot bypass byte cap (2.596ms)
✔ unverified manifest never fetches details or exposes stale files (0.7129ms)
✔ one 409 preserves other verified imports (0.202ms)
✔ unknown or downgraded verification never exposes files (0.1589ms)
✔ actual incomplete export overrides complete preview (0.1111ms)
✔ missing export header fails closed; complete header cannot remove missing requirements (0.0861ms)
✔ 404 is absence and does not issue a write (2.3608ms)
✔ legacy local draft requires explicit migration (0.3679ms)
✔ server restores with version and timestamp (0.1642ms)
✔ different server and local content requires choice (0.1632ms)
✔ identical cache and server preserves cache until explicit action (0.1392ms)
✔ successful create clears local only after acknowledgement (0.2985ms)
✔ updates use loaded server version (0.1662ms)
✔ 409 retains editor and never automatically retries (0.2066ms)
✔ explicit keep-local rebases but does not submit (0.1928ms)
✔ explicit server choice does not write (0.2643ms)
✔ read outage preserves local and prevents base-zero overwrite (0.2031ms)
✔ save outage preserves cache and error state (0.1627ms)
✔ integrity 409 without current is not treated as mergeable conflict (0.1393ms)
✔ HTTP 413 save keeps user content (0.1519ms)
✔ HTTP 422 save keeps user content (0.0744ms)
✔ empty draft never gets a write (0.095ms)
✔ UTF-8 exact 1MiB boundary is accepted (5.7204ms)
✔ UTF-8 over boundary is refused without truncation (2.4863ms)
✔ typing during save survives response and uses new base (0.2158ms)
✔ parallel save clicks do not duplicate requests (0.1212ms)
✔ generated preview never replaces local or saved human draft (0.0909ms)
✔ current null conflict requires explicit choice and version zero (0.1023ms)
✔ storage quota failure warns without losing in-memory text (0.211ms)
✔ sessions are independent per challenge (0.0854ms)
✔ same-profile windows preserve unsaved text through another window save (0.2232ms)
✔ cache can still recover historical localStorage-only text (0.0641ms)
ℹ tests 41
ℹ suites 0
ℹ pass 41
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 181.0073

exit_code=0
```

### browser

```text
$ npm.cmd run test:e2e

> ctf-workbench-ui@0.1.0 test:e2e
> playwright test


Running 11 tests using 1 worker

(node:46976) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
(Use `node --trace-warnings ...` to show where the warning was created)
ZIP PASS: human, 7/7 SHA256SUMS, final/generated exact bytes, incomplete
ZIP PASS: human, 7/7 SHA256SUMS, final/generated exact bytes, incomplete
  ok  1 tests\drafts.spec.ts:153:1 › C5 save reload update fresh browser and final ZIP closure (4.5s)
ZIP PASS: human, 12/12 SHA256SUMS, final/generated exact bytes, complete
  ok  2 tests\drafts.spec.ts:230:1 › C5 complete synthetic dossier exports saved human and generated draft (2.6s)
  ok  3 tests\drafts.spec.ts:345:1 › C5 two windows conflict preserves editor and requires manual merge (2.3s)
  ok  4 tests\drafts.spec.ts:422:1 › C5 same profile second window retains unsaved draft after first saves (1.7s)
  ok  5 tests\drafts.spec.ts:460:1 › C5 legacy migration and server-local divergent content choice (2.1s)
  ok  6 tests\drafts.spec.ts:533:1 › C5 empty and over 1MiB drafts retain content and exact server errors (1.3s)
ZIP PASS: generated, 7/7 SHA256SUMS, final/generated exact bytes, incomplete
ZIP PASS: generated, 7/7 SHA256SUMS, final/generated exact bytes, incomplete
  ok  7 tests\drafts.spec.ts:580:1 › C5 no human draft and corrupted draft export generated fallback (2.6s)
  ok  8 tests\drafts.spec.ts:635:1 › C5 actual backend disconnect keeps local draft and reconnect migrates (3.2s)
  ok  9 tests\workbench.spec.ts:13:1 › real FastAPI: full synthetic manual workflow, reload and downloads (5.3s)
  ok 10 tests\workbench.spec.ts:210:1 › real API rejection remains a failure in the UI (751ms)
  ok 11 tests\workbench.spec.ts:239:1 › real unverified manifest stays visible without blocking sibling import (928ms)

  11 passed (29.2s)

exit_code=0
```
