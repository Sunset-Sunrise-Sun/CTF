# 人工稿持久化 + 最终 ZIP 真实 HTTP 验收记录

- 日期：2026-11-08
- 被测版本：`feat/mvp-backend-workflow`（本文件所在提交；基线 PR #7 head `aa35e919533af1c5db7cbc2e037e98127e9502a3`）
- 服务：真实本地 `uvicorn`，`http://127.0.0.1:8800`，独立临时数据目录 `%TEMP%\mvp-writeup-http\data`（与仓库 `.local-data`、Codex 数据隔离）
- 客户端：`httpx 0.28.1` 外部 HTTP 请求（不 import 应用代码），共 30 条请求
- 结论：**通过**。人工稿创建/读取/更新/冲突/校验、最终 ZIP（`writeup.md` 逐字节人工稿、`writeup_generated.md` 初稿、manifest 元数据、SHA256SUMS）、无人稿 fallback、篡改 fallback 全部符合契约。

## 1. 验收数据

| 项 | 值 |
|---|---|
| Challenge A（人工稿） | `a154798b-7f52-494b-b1d0-d8db69f64796` |
| Challenge B（无人稿） | `67405914-c212-4609-96fe-594ff655ca91` |
| v1 content | `# 人工稿 v1\n\nHTTP 联调人工稿。\n`，40 字节，SHA-256 `5ee27a91e991b74c2bfb73ebdc1a1c5c0b41ad2f95a54341e2a37ab6ef6b5aea` |
| v2 content | `# 人工稿 v2\n\n更新后的 HTTP 联调人工稿。\n`，53 字节，SHA-256 `7203b9e22fe5f85b9da7b34f76c8c2e016df6a4080150565a3f5d9d8f5274429` |
| 导出 ZIP（人工稿） | 3956 字节，SHA-256 `a4e22e471afe83f9c3102c34518657eb00197e2d4dc102f55fd999178dad1cde`，8 个条目 |
| 导出 ZIP（篡改稿） | 5433 字节，SHA-256 `ac46ec983f4a622cba341409a59661a0343b3c2e5b215cba9c348a7784cb57d4`，`incomplete` |

## 2. 实际请求与响应（节选，完整 30 条见 transcript.json）

### 2.1 无人工稿 → 404

```http
GET /api/challenges/a154.../writeup/draft
-> 404 {"detail":"Writeup draft not found"}
```

### 2.2 创建人工稿 v1 → 201

```http
PUT /api/challenges/a154.../writeup/draft
Content-Type: application/json
{"content":"# 人工稿 v1\n\nHTTP 联调人工稿。\n","base_version":0}
-> 201
{"challenge_id":"a154798b-7f52-494b-b1d0-d8db69f64796",
 "content":"# 人工稿 v1\n\nHTTP 联调人工稿。\n",
 "version":1,
 "sha256":"5ee27a91e991b74c2bfb73ebdc1a1c5c0b41ad2f95a54341e2a37ab6ef6b5aea",
 "size":40,
 "saved_at":"2026-11-08T05:09:33.914529+00:00",
 "is_human_draft":true}
```

### 2.3 更新 v2 → 200

```http
PUT .../writeup/draft
{"content":"# 人工稿 v2\n\n更新后的 HTTP 联调人工稿。\n","base_version":1}
-> 200 {"version":2,
        "sha256":"7203b9e22fe5f85b9da7b34f76c8c2e016df6a4080150565a3f5d9d8f5274429",
        "size":53,"saved_at":"2026-11-08T05:09:33.933984+00:00", ...}
GET .../writeup/draft -> 200 与保存响应一致（刷新/重连后可恢复）
```

### 2.4 旧版本覆盖 → 409（不静默覆盖）

```http
PUT .../writeup/draft
{"content":"STALE","base_version":1}
-> 409
{"detail":{
  "message":"Writeup version conflict; reload the latest draft before saving",
  "current":{"challenge_id":"a154...","content":"# 人工稿 v2\n\n更新后的 HTTP 联调人工稿。\n",
             "version":2,"sha256":"7203b9e2...","size":53,
             "saved_at":"2026-11-08T05:09:33.933984+00:00","is_human_draft":true}}}
```

随后 GET 仍为 v2，证明失败请求没有覆盖。

### 2.5 空稿 / 超长稿 / 严格类型

```http
PUT {"content":"   ","base_version":2}                  -> 422 {"detail":"Writeup content must not be empty"}
PUT {"content":"A" * 1048577,"base_version":2}          -> 413 {"detail":"Writeup content exceeds the 1048576 byte limit"}
PUT {"content":"bad","base_version":"2"}                -> 422   (字符串)
PUT {"content":"bad","base_version":2.0}                -> 422   (浮点)
PUT {"content":"bad","base_version":true}               -> 422   (布尔)
PUT {"content":"bad","base_version":-1}                 -> 422   (负数)
```

### 2.6 导出最终 ZIP（人工稿存在）

```http
GET /api/challenges/a154.../export -> 200
Content-Type: application/zip
X-Dossier-Completeness: incomplete
zip size=3956 sha256=a4e22e471afe83f9c3102c34518657eb00197e2d4dc102f55fd999178dad1cde
```

ZIP 与 manifest 实际校验：

```text
writeup.md            == v2 content 的 UTF-8 字节（逐字节比较通过）
                         sha256=7203b9e22fe5f85b9da7b34f76c8c2e016df6a4080150565a3f5d9d8f5274429 size=53
writeup_generated.md  == GET /writeup/preview 的 markdown UTF-8 字节
                         sha256=0a796e71ded46c9adfa34e58eabb87455ff379d98fe23e4076b06806a8049444 size=2109
manifest.writeup.final_source        = "human"
manifest.writeup.final_sha256/size   = 7203b9e2... / 53
manifest.writeup.generated.sha256/size = 0a796e71... / 2109
manifest.writeup.human               = {version:2, sha256:7203b9e2..., size:53, saved_at:...}
manifest.writeup.integrity_error     = null
SHA256SUMS                           = 7 行（8 个交付文件除去自身），逐文件复算全部一致
```

> 该 Challenge 只有人工稿、没有导入/截图/运行记录，因此 `X-Dossier-Completeness: incomplete`（Writeup 证据缺失），与人工稿持久化无关；`writeup.md`/`writeup_generated.md`/manifest/SHA256SUMS 的人工稿部分均通过。

### 2.7 无人工稿 → 初稿 + 注明

```http
GET /api/challenges/6740.../export -> 200 (incomplete，因无证据)
writeup.md 开头：
> 注意：尚未保存人工稿，本文件为服务器生成的初稿。
+ 服务器初稿（writeup_generated.md 内容）
manifest.writeup.final_source = "generated"; human = null
```

### 2.8 人工稿篡改 → 拒绝读取、导出 fallback、不泄露篡改内容

直接把 `<data_root>/writeups/a154....json` 的 `content` 改为 `# TAMPERED-CONTENT\n`（不改记录的 sha）：

```http
GET .../writeup/draft -> 409
{"detail":"Saved writeup content does not match its recorded SHA-256"}

GET .../export -> 200
X-Dossier-Completeness: incomplete
zip sha256=ac46ec983f4a622cba341409a59661a0343b3c2e5b215cba9c348a7784cb57d4
writeup.md 开头 = "> 注意：已保存的人工稿完整性校验失败，本文件为服务器生成的初稿。"
manifest.writeup.final_source = "generated"
manifest.writeup.integrity_error = "Saved writeup content does not match its recorded SHA-256"
INCOMPLETE.txt 存在，且整个 ZIP 中不存在 "TAMPERED-CONTENT"
```

## 3. 证据文件（本地交付，不提交到仓库）

| 文件 | 大小 | SHA-256 |
|---|---|---|
| `human-draft-evidence.zip` | 3956 | `a4e22e471afe83f9c3102c34518657eb00197e2d4dc102f55fd999178dad1cde` |
| `tampered-draft-evidence.zip` | 5433 | `ac46ec983f4a622cba341409a59661a0343b3c2e5b215cba9c348a7784cb57d4` |
| `transcript.json`（30 条请求/响应） | 22903 | `ddbf681db8b70123b19524e46417b5896fea42ab65288fd161fe114eb0309d93` |
| `summary.json` | 3204 | `85607ece1dbd25275d6f8bd9ff2678c21589342e3b8b72863d993b62840acafe` |
| `run_http_acceptance.py` | 13811 | `fe057a8e7f8fe393d568d55d33a5b0d8ef49f22b74106562f2687b75f343c207` |

本地路径：`D:\CTF\.local-data\mvp-writeup-acceptance\`（`.local-data/` 已被 `.gitignore` 忽略，不进入 PR）。
执行数据目录：`%TEMP%\mvp-writeup-http\data`（独立临时目录）。

## 4. 复现

```powershell
cd D:\CTF\backend
$env:CTF_DATA_DIR='C:\Users\28746\AppData\Local\Temp\mvp-writeup-http\data'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8800 --log-level warning
# 另一终端：
$env:MVP_ROOT='C:\Users\28746\AppData\Local\Temp\mvp-writeup-http'
$env:MVP_BASE='http://127.0.0.1:8800'
cd $env:MVP_ROOT
python run_http_acceptance.py
# 期望输出 "HTTP ACCEPTANCE OK" 并生成 evidence/{transcript.json,summary.json,*.zip}
```
