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
| GET | `/api/challenges/{cid}/imports` | 200 `ImportRecord[]`（最新在前） |
| GET | `/api/challenges/{cid}/imports/{import_id}` | 200 `ImportDetail`（含 files） |
| GET | `/api/challenges/{cid}/imports/{import_id}/files/{relative_path}` | 200 文件原始字节；服务端嗅探 Content-Type；`nosniff`；路径必须命中该 import 的 manifest，否则 404 |

这两个增量接口用于刷新后重建文件树与图片/文本预览；不存在的 import/文件均为 404，不接受任意 workspace 路径。

### 4.7 事件与完整性

- `GET /api/challenges/{cid}/events`：按 sequence 排序；事件类型新增 `challenge_imported`、`manual_operation_recorded`。
- `GET /api/challenges/{cid}/integrity`：沿用 P1-1 哈希链校验。

### 4.8 Writeup 预览

`GET /api/challenges/{cid}/writeup/preview` → 200：

| 字段 | 说明 |
|---|---|
| `markdown` | 固定 9 章节初稿（基本信息/解题思路/关键操作/核心代码/运行结果/Flag 获取过程/平台验证/AI 使用说明/证据清单），可人工编辑 |
| `missing_requirements` | 机器可读缺失项：`core_approach`、`manual_operation`、`flag_capture`、`platform_verification`、`ai_usage_level`、`integrity` |
| `event_count` / `artifact_count` | 实际数量 |
| `completeness` | 仅当全部必需证据存在且事件链有效时为 `complete`，否则 `incomplete` |
| `warnings` | AI 等级未确认、哈希链失败、用户申报时间提示、导入警告等 |

固定缺失标记（原文）：

- 无人工解题思路：`[待选手补充：核心解题思路]`
- 无 Flag 获取截图：`[证据缺失：Flag 获取即时截图尚未提供]`
- 无平台验证截图：`[证据缺失：平台验证截图尚未提供]`

生成器只消费 Challenge 元数据、有序事件、Artifact 字节/元数据、人工笔记、项目规则与 AI 等级；不调用模型、不编造步骤/截图/Flag/验证结果。

### 4.9 完整证据 ZIP 导出

`GET /api/challenges/{cid}/export` → 200 `application/zip`，响应头 `X-Dossier-Completeness: complete|incomplete`。

ZIP 内容（存在对应数据时）：

```text
challenge/original.zip          # 最近一次导入的原始 ZIP（字节与 Artifact sha256 一致）
challenge/extracted/<path>      # 最近一次导入的解压文件（逐个复核 sha256）
challenge/rules/<rules>         # 项目规则文件（如已上传）
scripts/<source_code>           # source_code 证据
evidence/analysis|execution|flag_capture|platform_verification|other/<files>
logs/events.json                # 全量事件（按 sequence 排序）
logs/timeline.json              # 时间线摘要
writeup.md                      # 与 preview markdown 一致
ai_disclosure.md                # AI 使用披露
manifest.json                   # 元数据、统计、缺失项、缺失文件、警告、完整性
SHA256SUMS                      # 覆盖除自身外所有交付文件的 sha256（"<hex>  <path>"）
INCOMPLETE.txt                  # 不完整时存在，显著标记
```

- 每个 Artifact 在写入前复核 SHA-256；校验失败/文件缺失时跳过并记入 `missing_files`/`warnings`，导出仍可完成但标记 `incomplete`。
- 不修改任何事件或 Artifact；事件按 sequence 输出；文件名/路径净化，防 ZIP 内路径穿越。
- 导出为只读投影；临时 ZIP 响应后由后台任务删除。

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
# 8) 时间线与完整性、Writeup、导出
curl.exe -sS "$b/api/challenges/<cid>/events"
curl.exe -sS "$b/api/challenges/<cid>/integrity"
curl.exe -sS "$b/api/challenges/<cid>/writeup/preview"
curl.exe -sS -o dossier.zip "$b/api/challenges/<cid>/export"
```

## 6. 已知限制与风险

1. **单进程**：项目配置/上传锁为进程内串行化；多 worker 或多实例写同一 data 目录不支持。
2. **无认证**：本地回环单用户服务，不要暴露到其他主机；题目归属校验不是多用户授权模型。
3. **无数据库迁移**：项目配置在 JSON 文件；若进程在项目/规则写入时崩溃，原子 replace 保证不会留下半写文件，但需要一次完整写入才能更新。
4. **没有真正的自动执行/验证**：`execution_mode=manual_external`、`execution_verified=false` 是固定语义；工作台无法证明用户手动操作真实发生，只能记录申报与证据。
5. **哈希链威胁模型**：只能检测未重算哈希的篡改；拥有 DB/文件系统完全控制权者可重写链，无外部签名。
6. **导入预算为应用级防护**：防 ZIP Slip/炸弹/资源耗尽的常见形式，但不是 OS 沙箱；解压文件不执行，不应把工作台当安全执行环境。
7. **Writeup 初稿的“核心代码”** 从文本类 Artifact 截断展示（单文件 20 KiB / 总计 150 KiB / 最多 10 个），完整文件在导出档案中。
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
