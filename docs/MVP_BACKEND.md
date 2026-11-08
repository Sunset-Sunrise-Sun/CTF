# MVP 后端工作流（DeepSeek / Part B）

分支：`feat/mvp-backend-workflow`（基于 `feat/p1-2-a00-integration` / PR #6 固定基线 `96152b7a66e16d726d50bebb4d833167b140e19c`）
目标 PR：以 `feat/p1-2-a00-integration` 为 base 的 Draft PR（不合并、不改写 PR #6）。

本轮实现「人工执行模式」的完整后端流程：项目与规则 → 题目元数据扩展 → ZIP 安全导入 → 证据分类 → 人工运行补录 → 事件时间线/完整性 → Writeup 初稿 → 完整证据 ZIP 导出。

## 1. 范围与非目标

已实现：

- 单本地工作区项目配置（`GET/PUT /api/project`）与比赛规则文件内容寻址存储、下载。
- Challenge 元数据扩展：`ai_usage_level`（A0/A1/A2/unknown）、`score`、`competition_name`；历史 Challenge JSON 兼容。
- 题目 ZIP 安全导入：预算校验、路径/符号链接/加密/压缩比防护、临时目录原子安装、文件清单与哈希、`challenge_imported` 事件。
- 证据上传分类：`evidence_kind`、`capture_time_claim`（用户申报时间，与 `ingested_at` 服务器时间严格区分）；证据列表返回分类与来源事件。
- 人工运行补录：`manual_operation_recorded` 事件，固定 `actor=user`、`execution_mode=manual_external`、`execution_verified=false`。
- Writeup 初稿：仅基于 Challenge/事件/Artifact/人工笔记/规则/AI 等级生成，缺失证据显示固定标记。
- **人工稿持久化**：每个 Challenge 可保存/读取人工编辑的 Markdown（版本号、SHA-256、服务器时间、1 MiB 上限、乐观并发冲突保护）；人工稿不是事件，不伪装成执行事实。
- 完整证据 ZIP：原始 ZIP、解压文件、脚本、分类证据、事件与时间线日志、Writeup、AI 披露、manifest、SHA256SUMS；不完整档案显著标记。
- 后端测试、Ruff、OpenAPI/契约文档。

非目标（与任务书 Part D 一致，**未实现**）：

- 任意命令执行 API、自动运行导入脚本/Dockerfile、Docker Socket 暴露。
- 自动扫描/提交 Flag、自动截图、真实模型自动工具调用、把 AI 建议写成人工事实。
- 身份认证、真实生产审计密钥、外部哈希链签名。
- 前端页面（由另一 Agent 负责，本分支不修改 `frontend/`）。

## 2. 数据布局

```text
<data_root>/
  workbench.sqlite3              # 既有 challenges/events/event_heads/artifacts，无新迁移
  project.json                   # 单项目配置（原子写入；不含规则字节）
  artifacts/sha256/<aa>/<bb>/<sha256>   # 证据、原始 ZIP、规则文件的统一内容寻址存储
  challenges/<challenge_id>/
    imports/<import_id>/
      manifest.json              # 文件清单（relative_path/size/sha256/media_type）+ 统计
      <解压文件...>
    .import-staging-<uuid>/      # 仅解压期间存在，成功后原子 rename；失败清理
  writeups/<challenge_id>.json    # 人工编辑 Writeup 的最新版本（原子写；无 DB 迁移）
  .exports/                      # 导出临时 ZIP，响应后台删除
```

- **没有新增数据库迁移**：`001_initial.sql`、`002_artifacts.sql` 未修改，未占用 P1-2 预留迁移编号。证据分类/声明时间记录在 `artifact_added` 事件 payload；项目配置为独立 JSON。
- 同一 data 目录只支持单进程本地服务（与 P1-1 相同限制）。

## 3. 配置

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `CTF_DATA_DIR` | `../.local-data` | 数据根目录 |
| `CTF_MAX_ARTIFACT_BYTES` | 50 MiB | 证据/原始 ZIP/导入 ZIP 上传上限 |
| `CTF_RULES_MAX_BYTES` | 50 MiB | 比赛规则文件上传上限 |
| `CTF_IMPORT_MAX_FILES` | 2000 | ZIP 内文件数量上限 |
| `CTF_IMPORT_MAX_FILE_BYTES` | 50 MiB | 单文件解压上限 |
| `CTF_IMPORT_MAX_TOTAL_BYTES` | 200 MiB | 总解压上限 |
| `CTF_IMPORT_MAX_COMPRESSION_RATIO` | 200 | 压缩比上限（单文件与总体） |
| `CTF_MAX_WRITEUP_BYTES` | 1 MiB | 人工编辑 Writeup 的 UTF-8 内容上限 |

`create_app(data_root, max_artifact_bytes, rules_max_bytes, import_limits)` 支持测试注入；`ImportLimits` 见 `app/imports.py`。

## 4. API 契约

完整 OpenAPI 见 [`docs/openapi.json`](openapi.json)，强类型 schema 见 [`docs/contracts.json`](contracts.json)。共同契约（Part C）之外新增的只读文件浏览接口见 4.6。

### 4.1 项目与规则

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/api/project` | 200 Project；未创建 404 |
| PUT | `/api/project` | 创建/更新 `project_name`、`competition_name`、`competition_type`、`ai_policy_summary`；创建缺 `project_name` → 422 |
| POST | `/api/project/rules` | multipart `file`；200 Project（写入 rules_filename/sha256/size/ingested_at）；项目未创建 409；超限 413；重复内容去重 |
| GET | `/api/project/rules/content` | 200 原始字节（服务端嗅探 Content-Type，attachment）；未上传 404；blob 篡改/缺失 409 |

Project 字段：`project_id, project_name, competition_name, competition_type, rules_filename, rules_sha256, rules_size, rules_ingested_at, ai_policy_summary`。
规则文件使用与证据相同的内容寻址存储 + SHA-256 校验 + 原子写入；项目内所有题目共享。

### 4.2 Challenge

`POST /api/challenges` / `GET /api/challenges` 在原有字段上增加：

- `ai_usage_level`: `A0 | A1 | A2 | unknown`（默认 `unknown`）
- `score`: 可空非负整数
- `competition_name`: 可空字符串；未传时若项目已配置则继承项目 `competition_name`

历史 Challenge JSON（不含新字段）可正常读取，新字段取默认值。**AI 使用等级未确认（unknown）时**：后端不提供任何模型/Agent 调用接口；Writeup 预览与导出会给出未确认警告并标记档案不完整（`missing_requirements` 含 `ai_usage_level`）。

### 4.3 ZIP 导入

`POST /api/challenges/{cid}/imports`，multipart 字段 `file` → 201 `ImportResult`：

```json
{
  "challenge_id": "…",
  "original_artifact": { "artifact_id": "…", "sha256": "…", "size": 1234,
    "media_type": "application/zip", "original_filename": "challenge.zip",
    "ingested_at": "…", "source_event_id": "…",
    "evidence_kind": "challenge_archive", "capture_time_claim": null,
    "source_event_type": "artifact_added", "source_event_sequence": 1 },
  "import_event_id": "…",
  "extracted_file_count": 2,
  "total_uncompressed_size": 456,
  "files": [
    { "relative_path": "readme.txt", "size": 10, "sha256": "…", "media_type": "text/plain" }
  ],
  "warnings": ["Nested archive was not extracted: inner.zip"]
}
```

- 原始 ZIP 保存为 Artifact（`evidence_kind=challenge_archive`），可经 `GET .../artifacts/{id}/content` 下载。
- 成功后追加一条 `challenge_imported` 事件：`actor=user`，`artifact_ids=[original_artifact]`，payload 含 `import_id/challenge_id/original_artifact_id/original_filename/extracted_file_count/total_uncompressed_size/warnings/created_at/manifest_sha256`。
- 每个导入目录的 `manifest.json` 记录文件清单与统计；读取时做两项校验：① 文件字节必须等于其 canonical 形式且 `manifest_sha256` 可按内容复算；② 必须与**恰好一条** `challenge_imported` 事件绑定（`import_id`、`challenge_id`、`original_artifact_id`、`manifest_sha256`、统计与创建时间逐字段比较，事件需引用原始 ZIP Artifact）。仅重算 Manifest 自身 SHA256 不足以通过（见 4.6）。
- 失败（非 ZIP/安全违规/超预算）→ 422（detail 说明原因），不产生 imports 目录与 staging 残留；若未产生 Artifact 行则上传的 blob 被清理。超过上传大小 → 413。
- 解压文件位于 `challenges/<cid>/imports/<import_id>/`；`manifest.json` 记录完整清单。

**安全校验（全部有测试）**：拒绝绝对路径、`..` 穿越、Windows 盘符、NUL/控制字符/结尾点空格/Windows 设备名、`: ` ADS、符号链接/特殊文件、加密 ZIP、重复路径与大小写冲突、文件与目录路径冲突、路径长度超限、文件数量/单文件大小/总解压大小/压缩比超限。嵌套 ZIP 只作为普通文件保存并给出 warning，绝不递归解压；导入文件永不执行。

### 4.4 证据上传与列表

`POST /api/challenges/{cid}/artifacts` 保留原有 multipart `file`，新增可选表单字段：

- `evidence_kind`：`challenge_archive | analysis | execution | execution_output | flag_capture | platform_verification | source_code | other`，非法值 422。
- `capture_time_claim`：ISO 8601 用户申报时间；非法格式 422。

响应与 `GET .../artifacts`、`GET .../artifacts/{id}` 返回 **ArtifactView**：原 Artifact 字段 + `evidence_kind`（默认 `other`）、`capture_time_claim`（默认 null）、`source_event_type`、`source_event_sequence`。

- `ingested_at` 是服务器实际接收时间；`capture_time_claim` 只是用户声明，二者语义严格区分，绝不互相替换。
- 分类与声明时间写入 `artifact_added` 事件 payload（旧事件 payload 无这些键时按默认值读取，历史数据可读）。
- 同内容去重沿用 P1-1 语义：同题同内容返回既有 Artifact、不新增事件，因此分类以首次摄入为准。

### 4.5 人工运行补录

`POST /api/challenges/{cid}/manual-operations` → 201 Event：

请求：`command`（1–4000）、`working_directory`（1–500）、`purpose`（1–500）、`exit_code`（可选整数）、`result_note`（1–4000）、`started_at_claim`/`finished_at_claim`（可选 ISO 8601，finished 早于 started → 422）。
额外字段（`actor`/`event_hash`/`sequence`/`source_event_id` 等）→ 422（`extra=forbid`）。

事件：`event_type=manual_operation_recorded`，`actor=user`，payload 固定含：

```text
execution_mode="manual_external", execution_verified=false, record_source="user_manual_entry"
```

不会生成 `tool_started/tool_finished`，不会把人工补录伪装为工作台自动执行或已验证执行。stdout/stderr/运行截图由用户另行上传为 Artifact。界面/文档应提示不要在命令与结果中写入 API Key、密码、Token。

### 4.6 文件浏览（新增只读接口）

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/api/challenges/{cid}/imports` | 200 `ImportRecord[]`（最新在前）；每个条目含 `manifest_verified`/`integrity_error`，失败项显式标记而不是静默隐藏 |
| GET | `/api/challenges/{cid}/imports/{import_id}` | 200 `ImportDetail`（含 files）；Manifest 校验或事件绑定失败 → **409** |
| GET | `/api/challenges/{cid}/imports/{import_id}/files/{relative_path}` | 200 文件原始字节；读取后按 Manifest 复核 **size 与 SHA256**；不匹配 → **409** 且绝不返回篡改字节；`X-Imported-File-Integrity: sha256-verified`；路径必须命中 Manifest，否则 404 |

这些增量接口用于刷新后重建文件树与图片/文本预览；不存在的 import/文件为 404，不接受任意 workspace 路径。事件链不可信（`integrity.valid=false`）时，imports 列表/详情/文件均返回 409，不基于不可信事件做绑定判断。

### 4.7 事件与完整性

- `GET /api/challenges/{cid}/events`：按 sequence 排序；事件类型新增 `challenge_imported`、`manual_operation_recorded`。
- `GET /api/challenges/{cid}/integrity`：沿用 P1-1 哈希链校验。

### 4.8 Writeup 预览

`GET /api/challenges/{cid}/writeup/preview` → 200：

| 字段 | 说明 |
|---|---|
| `markdown` | 固定 9 章节初稿（基本信息/解题思路/关键操作/核心代码/运行结果/Flag 获取过程/平台验证/AI 使用说明/证据清单），可人工编辑 |
| `missing_requirements` | 机器可读缺失项：`core_approach`、`manual_operation`、`core_code`、`execution_evidence`、`flag_capture`、`platform_verification`、`ai_usage_level`、`integrity` |
| `event_count` / `artifact_count` | 实际数量 |
| `completeness` | 仅当全部必需证据存在且事件链有效时为 `complete`，否则 `incomplete` |
| `warnings` | AI 等级未确认、哈希链失败、用户申报时间提示、导入警告等 |

固定缺失标记（原文）：

- 无人工解题思路：`[待选手补充：核心解题思路]`
- 无核心代码/脚本：`[证据缺失：尚未上传核心代码或脚本]`
- 无运行截图/执行输出：`[证据缺失：尚无运行截图或执行输出证据]`
- 无人工运行记录：`[证据缺失：尚无人工运行记录]`
- 无 Flag 获取截图：`[证据缺失：Flag 获取即时截图尚未提供]`
- 无平台验证截图：`[证据缺失：平台验证截图尚未提供]`

**普通 note 与核心解题思路严格区分**：`POST .../notes` 支持 `{"text": "...", "kind": "note"|"approach"}`（默认 `note`）。只有 `kind="approach"` 的笔记进入「解题思路」章节并满足 `core_approach`；普通笔记只显示为「其他人工笔记（普通笔记，非核心解题思路）」。`core_code` 需要 `source_code`/`analysis` 文本 Artifact（无则缺失，即使存在普通文本文件也不冒充核心代码）；`execution_evidence` 需要 `execution`/`execution_output` 证据（仅有补录记录不算运行证据）。生成器只消费 Challenge 元数据、有序事件、Artifact 字节/元数据、显式 approach 笔记、项目规则与 AI 等级；不调用模型、不编造步骤/截图/Flag/验证结果。

### 4.9 完整证据 ZIP 导出

`GET /api/challenges/{cid}/export` → 200 `application/zip`，响应头 `X-Dossier-Completeness: complete|incomplete`。

ZIP 内容（存在对应数据时）：

```text
challenge/imports/<import_id>/original.zip       # 每次导入的原始 ZIP（字节与 Artifact sha256 一致）
challenge/imports/<import_id>/extracted/<path>   # 每次导入的解压文件（逐个复核 size+sha256）
challenge/rules/<rules>         # 项目规则文件（如已上传）
scripts/<source_code>           # source_code 证据
evidence/analysis|execution|flag_capture|platform_verification|other/<files>
logs/events.json                # 全量事件（按 sequence 排序）
logs/timeline.json              # 时间线摘要
writeup.md                      # 最终稿：人工稿（存在且校验通过）或初稿 + 注明
writeup_generated.md            # 服务器生成的初稿（始终存在）
ai_disclosure.md                # AI 使用披露
manifest.json                   # 元数据、统计、缺失项、缺失文件、警告、完整性、逐导入导出状态
SHA256SUMS                      # 覆盖除自身外所有交付文件的 sha256（"<hex>  <path>"）
INCOMPLETE.txt                  # 不完整时存在，显著标记
```

- **每次导入都独立导出**：以 `import_id` 分目录，原始 ZIP 与解压文件均逐字节复核；`manifest.json.imports` 列出全部导入及各自 `status`（`exported` / `incomplete` / `unverified`）、`exported_file_count`、`missing_files`、`error`。
- 每份 Manifest 在导出前经自身校验与 `challenge_imported` 事件绑定校验；未验证的导入不会导出任何文件，只记录为 `unverified`。
- 任意一次导入文件缺失/大小或哈希不匹配、任一 Artifact 校验失败、存在未验证导入、或人工稿完整性校验失败 → 整个档案标记 `incomplete`（响应头、manifest、`INCOMPLETE.txt` 一致），导出仍返回 200。
- `writeup.md` 规则：人工稿有效 → 逐字节等于人工稿；无人稿 → `> 注意：尚未保存人工稿，本文件为服务器生成的初稿。` + 初稿；人工稿损坏 → `> 注意：已保存的人工稿完整性校验失败，本文件为服务器生成的初稿。` + 初稿（不输出篡改内容）。
- `manifest.json.writeup` 记录：`final_source`（`human`/`generated`）、`final_sha256`/`final_size`、`generated.sha256/size`、`human.version/sha256/size/saved_at`（或 null）、`integrity_error`；`SHA256SUMS` 含 `writeup.md` 与 `writeup_generated.md`。
- 不修改任何事件或 Artifact；事件按 sequence 输出；文件名/路径净化，防 ZIP 内路径穿越；`SHA256SUMS` 覆盖所有实际交付文件。
- 导出为只读投影；临时 ZIP 响应后由后台任务删除。

### 4.10 人工稿持久化（人工编辑 Writeup）

人工稿与服务器初稿严格分离：初稿由 `GET /writeup/preview` 实时生成；人工稿由选手编辑并通过本接口保存，**不写入事件链**（不产生 `tool_*`/`finding`/`verification` 事件，不改 `integrity` 结果），因此不会被当作自动执行或已验证事实。

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/api/challenges/{cid}/writeup/draft` | 200 `WriteupDraft`；无稿 404；sidecar 损坏/篡改 409（不返回内容） |
| PUT | `/api/challenges/{cid}/writeup/draft` | 创建 201 / 更新 200；版本冲突 409；空稿 422；超限 413 |

请求（`extra=forbid`）：

```json
{"content": "# 解题思路\n\n人工 Markdown……", "base_version": 2}
```

- `content`：人工 Markdown；UTF-8 字节数 ≤ `CTF_MAX_WRITEUP_BYTES`（默认 1 MiB）；`strip()` 后不得为空。
- `base_version`：**严格非负整数**（拒绝字符串/浮点/布尔/负数，422）；`0` 表示“服务端尚无人工稿”，`N` 表示客户端编辑时看到的版本。

响应 `WriteupDraft`：`challenge_id, content, version(≥1), sha256, size, saved_at, is_human_draft=true`；`sha256` 为 content UTF-8 字节的 SHA-256，`size` 为字节数，`saved_at` 为服务器保存时间（UTC）。

版本冲突：`409`，`detail={message, current}`，`current` 为最新 `WriteupDraft` 或 `null`；服务端在锁内比较 `base_version` 后原子写入，**绝不静默覆盖**。两个并发保存同一 base 时恰好一个成功，另一个收到 409。

存储与原子性：`<data_root>/writeups/<challenge_id>.json`，临时文件 → `fsync` → `os.replace`；保留最新版本（MVP 不做历史版本管理），读取时校验 `challenge_id/sha256/size`，损坏或符号链接拒绝。**仅支持单进程**本地服务，不宣称支持多进程同时写入。

请求安全：对 `PUT .../writeup/draft` 做 `Content-Length` 预检并按实际接收字节数计数（覆盖 chunked），超过 `1 MiB + JSON 开销` 直接 413，避免绕过内容上限；最终精确上限仍由存储层校验。

SHA-256 完整性边界：该校验用于检测内容与元数据不一致（意外损坏、简单篡改、导入/导出一致性），**不宣称能够抵御拥有文件系统完全控制权的攻击者**；后者可同时改写内容与记录的 SHA。

前端旧草稿兼容（供 Codex 联调）：后端无人工稿时 GET 返回 404，前端应**保留 localStorage 旧草稿**并提示“服务器尚无人工稿，是否迁移”；用户确认后以 `base_version=0` 保存迁移。若服务器已有稿而前端本地草稿不同，保存会收到 409 + `current`，前端必须展示服务器最新稿并让用户显式选择，**不得静默覆盖**本地或服务器版本；只在成功保存或用户明确放弃后才清理本地草稿。

## 5. 本地启动与演示

```powershell
cd backend
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# Swagger: http://127.0.0.1:8000/docs
```

演示（PowerShell + curl；数据目录用默认 `../.local-data` 或设置 `$env:CTF_DATA_DIR`）：

```powershell
$b = "http://127.0.0.1:8000"
# 1) 创建项目
curl.exe -sS -X PUT "$b/api/project" -H "Content-Type: application/json" -d '{\"project_name\":\"Demo\",\"competition_name\":\"SyntheticCTF\",\"ai_policy_summary\":\"AI 仅作学习参考\"}'
# 2) 上传规则
curl.exe -sS -X POST "$b/api/project/rules" -F "file=@rules.pdf;type=application/pdf"
# 3) 创建题目
curl.exe -sS -X POST "$b/api/challenges" -H "Content-Type: application/json" -d '{\"name\":\"Demo Misc\",\"category\":\"Misc\",\"score\":100,\"ai_usage_level\":\"A1\"}'
# 4) 上传并导入 ZIP（<cid> 用上一步返回）
curl.exe -sS -X POST "$b/api/challenges/<cid>/imports" -F "file=@challenge.zip;type=application/zip"
# 5) 浏览文件（import_id/relative_path 取上一步返回值）
curl.exe -sS "$b/api/challenges/<cid>/imports/<import_id>/files/readme.txt"
# 6) 人工运行补录
curl.exe -sS -X POST "$b/api/challenges/<cid>/manual-operations" -H "Content-Type: application/json" -d '{\"command\":\"python solve.py\",\"working_directory\":\"D:\\\\demo\",\"purpose\":\"手动运行\",\"exit_code\":0,\"result_note\":\"输出合成结果\"}'
# 7) 上传证据（flag_capture / platform_verification / execution）
curl.exe -sS -X POST "$b/api/challenges/<cid>/artifacts" -F "file=@flag.png;type=image/png" -F "evidence_kind=flag_capture"
# 8) 时间线与完整性、Writeup 初稿
curl.exe -sS "$b/api/challenges/<cid>/events"
curl.exe -sS "$b/api/challenges/<cid>/integrity"
curl.exe -sS "$b/api/challenges/<cid>/writeup/preview"
# 9) 保存/读取人工稿（base_version=0 新建；后续用当前 version 更新）
curl.exe -sS -X PUT "$b/api/challenges/<cid>/writeup/draft" -H "Content-Type: application/json" -d '{"content":"# 人工稿\n\n由选手编辑","base_version":0}'
curl.exe -sS "$b/api/challenges/<cid>/writeup/draft"
# 10) 导出最终证据 ZIP（writeup.md 为人工稿，writeup_generated.md 为初稿）
curl.exe -sS -o dossier.zip "$b/api/challenges/<cid>/export"
```

## 6. 已知限制与风险

1. **单进程**：项目配置/上传锁/人工稿版本锁为进程内串行化；多 worker 或多实例写同一 data 目录不支持。人工稿只保留最新版本，没有历史版本/回滚接口。
2. **无认证**：本地回环单用户服务，不要暴露到其他主机；题目归属校验不是多用户授权模型。
3. **无数据库迁移**：项目配置在 JSON 文件；若进程在项目/规则写入时崩溃，原子 replace 保证不会留下半写文件，但需要一次完整写入才能更新。
4. **没有真正的自动执行/验证**：`execution_mode=manual_external`、`execution_verified=false` 是固定语义；工作台无法证明用户手动操作真实发生，只能记录申报与证据。
5. **哈希链与人工稿 SHA-256 的威胁模型**：只能检测未重算哈希/摘要的篡改；拥有 DB/文件系统完全控制权者可同时改写内容与记录的 SHA，无外部签名。SHA-256 是内容一致性检查，不是防全盘控制者的密码学证明。
6. **导入预算为应用级防护**：防 ZIP Slip/炸弹/资源耗尽的常见形式，但不是 OS 沙箱；解压文件不执行，不应把工作台当安全执行环境。
7. **Writeup 初稿的“核心代码”** 只从 `source_code`/`analysis` 文本 Artifact 截断展示（单文件 20 KiB / 总计 150 KiB / 最多 10 个），完整文件在导出档案中；普通文本文件不会冒充核心代码。
8. **截图/Flag 验证是外部事实**：预览与导出只引用用户上传的截图 Artifact 和人工申报，不验证截图内容或平台结果。
9. **导出一致性**：导出开始时读取事件/证据快照，不包含导出期间新写入的数据；并发写入下不保证跨表强一致。
10. **哈希链损坏** 时 preview/export 仍可用，但 completeness 必为 incomplete 并带警告。
11. 前端联调需按本文件契约（尤其增量文件浏览接口与 ArtifactView 字段）；本分支不修改前端。

## 7. 验证

```powershell
cd backend
python -m pytest -q
python -m ruff check app tests
python -m app.schema_cli   # 重新导出 docs/openapi.json 与 docs/contracts.json
```

测试报告见 [`docs/MVP_BACKEND_TEST_REPORT.md`](MVP_BACKEND_TEST_REPORT.md)，文件清单见 [`docs/MVP_BACKEND_FILES.md`](MVP_BACKEND_FILES.md)。
