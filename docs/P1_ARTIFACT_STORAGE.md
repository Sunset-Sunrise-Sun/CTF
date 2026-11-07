# P1-1 附件与证据存储设计说明

版本：1.0  
日期：2026-11-07  
分支：`feat/p1-evidence-storage`  
基线：`ed4850dc17601a9e8177c12c95d1281e072cccd4`（`feat/framework-scaffold`）

## 1. 范围

本轮只实现「附件上传 → SHA-256 → 内容寻址存储 → SQLite 元数据 → `artifact_added` 事件关联 → 列表/查询/下载」。
不实现工具执行、自动解题、Writeup 生成、前端改造、附件自动解压；不修改 `main` 分支，不修改已有事件历史。

已交付能力：

- `POST /api/challenges/{cid}/artifacts` 上传（multipart 字段 `file`），服务端计算 SHA-256、大小、嗅探媒体类型；
- 内容寻址存储于 `<data_root>/artifacts/sha256/<aabb>/.../<sha256>`；
- SQLite `artifacts` 表持久化元数据，迁移 `002_artifacts.sql`；
- 每次新建 Artifact 原子地追加一条 `artifact_added` 事件，事件与 Artifact 双向关联；
- 附件列表、元数据查询、下载、完整性校验接口；
- 同内容去重（同题幂等返回既有 Artifact；跨题独立 `artifact_id`、共享单份 blob）；
- 原始证据不可修改/删除（无写接口、SQLite 触发器、blob 只读属性、下载时哈希校验）；
- 服务重启后数据、事件链、下载均可用。

## 2. 数据模型与关联

```text
Challenge (challenges 表)
  challenge_id ─┐
                │ 1
                ▼ N
Artifact (artifacts 表)                         Event (events 表, append-only)
  artifact_id  <──── payload.artifact_id ───────  artifact_added 事件
  challenge_id ────────────────────────────────► challenge_id
  source_event_id ─────────────────────────────► event_id（1:1 来源事件）
  sha256 / size / media_type / original_filename / ingested_at
```

- 一个 Challenge 拥有多个 Artifact；不同题目即使内容相同也各有独立 Artifact 行（独立 `artifact_id`）。
- 每个 Artifact 恰好对应一条 `artifact_added` 事件（`source_event_id`），该事件的 `artifact_ids` 为 `[artifact_id]`，payload 只含 `artifact_id/sha256/size/media_type`，不含文件内容。数据库层用 `source_event_id UNIQUE` 与 `(challenge_id, source_event_id) → events(challenge_id, event_id)` 联合外键强制该一对一关系及同题归属。
- 事件哈希链沿用 P0 规则：`event_hash = SHA256(canonical(Event - event_hash))`，`previous_event_hash` 指向前一条；`artifacts` 参与 FK 但事件 payload 不写回历史，保证「不修改现有事件历史」。

数据库约束（`002_artifacts.sql`）：

```sql
CREATE UNIQUE INDEX events_challenge_event ON events(challenge_id, event_id);
CREATE TABLE artifacts (
 artifact_id TEXT PRIMARY KEY,
 challenge_id TEXT NOT NULL REFERENCES challenges(challenge_id),
 sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
 size INTEGER NOT NULL CHECK(size >= 0),
 media_type TEXT NOT NULL CHECK(length(media_type) > 0),
 original_filename TEXT NOT NULL CHECK(length(original_filename) > 0),
 ingested_at TEXT NOT NULL,
 source_event_id TEXT NOT NULL UNIQUE,
 UNIQUE(challenge_id, sha256),
 FOREIGN KEY (challenge_id, source_event_id)
  REFERENCES events(challenge_id, event_id)
);
CREATE INDEX artifacts_by_challenge ON artifacts(challenge_id);
CREATE TRIGGER artifacts_no_update BEFORE UPDATE ON artifacts BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER artifacts_no_delete BEFORE DELETE ON artifacts BEGIN SELECT RAISE(ABORT, 'append-only'); END;
```

- `UNIQUE(challenge_id, sha256)` 保证同题同内容只有一条 Artifact；跨题不冲突。
- `source_event_id UNIQUE` 与联合外键 `(challenge_id, source_event_id) → events(challenge_id, event_id)` 共同保证来源事件与 Artifact **严格一对一且属于同一 Challenge**：同一个事件不能成为两个 Artifact 的来源，Artifact 也不能引用其他题目的事件；`events_challenge_event` 复合唯一索引作为该联合外键的父键。
- 事件与 Artifact 的写入仍在同一 SQLite 事务内完成（先事件、后 Artifact），因此约束不会造成「事件已写入但 Artifact 未写入」的中间状态；失败整体回滚。
- 升级到 `002_artifacts.sql` 时按 `schema_migrations` 顺序增量应用，无需重建 P0 数据。该迁移在 PR 合并前经过关联约束修正；对已应用旧版 002 的本地开发数据库，需要重建数据目录（未发布迁移，不影响 P0 生产数据）。

## 3. 存储布局与内容寻址

```text
<data_root>/
  workbench.sqlite3            # 挑战、事件、事件头、artifacts 元数据
  artifacts/
    .staging/                  # 仅存放上传中的临时文件，成功后清空
    sha256/
      <sha[0:2]>/
        <sha[2:4]>/
          <sha256>             # 文件字节，只读
  challenges/<challenge_id>/   # P0 工作区目录（本轮未使用）
```

- 路径完全由服务端计算的 64 位小写十六进制 SHA-256 派生，客户端文件名、Content-Type、任何路径参数都不参与路径构造。
- 先写 `<root>/artifacts/.staging/upload-*.part`，边读边算哈希、边限制大小；完成后 `os.replace` 原子安装到最终路径，再尽力设置只读属性，最后删除 staging 临时文件（失败路径同样删除）。
- 已存在同 digest blob 时：校验其大小与哈希，一致则复用并删除临时文件；不一致（被篡改/截断）则用本次校验过的上传字节恢复。
- 下载时重新读取 blob 并复算 SHA-256，不一致或缺失返回 409，不返回被篡改的字节。

## 4. 上传流程与一致性

```text
请求 → ASGI 入口体积上限（Content-Length 预检 + chunked 字节计数，超限 413，不进入 multipart 解析）
  → 校验挑战存在 → 全局单进程上传锁
  → ArtifactStore.ingest：流式读入 staging，超限即 413，计算 sha256/size/嗅探 media_type
  → Store.add_artifact：BEGIN IMMEDIATE 内
        查重（challenge_id, sha256）→ 命中则返回既有 Artifact，无新事件
        未命中：追加 artifact_added 事件 + event_heads + 插入 artifacts 行（同一事务）
  → DB 失败：事务回滚；若该 sha256 已无任何 Artifact 引用则删除孤立 blob，返回 500，不留元数据
  → 成功：201（新建，X-Artifact-Deduplicated: false）或 200（去重，X-Artifact-Deduplicated: true）
```

一致性策略：

1. blob 先落盘、元数据后入库；任何「有元数据、无内容」的情况都不会由正常写入产生。
2. 元数据与事件在同一 SQLite 事务内提交，二者要么都写入、要么都不写入。
3. DB 失败时按引用计数清理孤立 blob；被其它 Artifact（例如另一题同内容）引用的 blob 永不删除。这是 best-effort 补偿：若引用计数查询本身也失败，则保留 blob（宁可留下可回收的孤立文件，也不误删共享证据）。
4. 上传锁把「blob 安装 + 元数据提交 + 失败清理」串行化，避免同内容并发上传在 Windows 只读覆盖与失败清理上的竞态。该锁是单进程的，跨进程同时写同一 data 目录不在本版本支持范围（见已知限制）。
5. 服务重启后所有状态来自 SQLite + 磁盘 blob，无内存态依赖；事件链 `verify` 仍有效。
6. FastAPI/Starlette 会在进入端点前解析整个 multipart 请求体，因此应用层「读到超限才 413」不足以阻止请求体先被 spool 到临时盘。为此在 ASGI 中间件层增加入口限额：先检查 `Content-Length`，超限直接 413 且不进入解析；对 chunked（无 `Content-Length`）请求包装 `receive` 计数字节，超过「文件上限 + 64 KiB multipart 余量」立即中止并返回 413。该中间件只作用于 `POST /api/challenges/{cid}/artifacts`，不影响其它 API。

## 5. API 契约

| 方法 | 路径 | 成功响应 | 主要错误 |
|---|---|---|---|
| POST | `/api/challenges/{cid}/artifacts` | 201 新建 / 200 去重，Artifact；头 `X-Artifact-Deduplicated` | 404 题目不存在；413 超限；500 存储/元数据失败 |
| GET | `/api/challenges/{cid}/artifacts` | 200 `Artifact[]`，按上传顺序 | 404 题目不存在 |
| GET | `/api/challenges/{cid}/artifacts/{aid}` | 200 Artifact | 404 题目/Artifact 不存在或不属于该题 |
| GET | `/api/challenges/{cid}/artifacts/{aid}/content` | 200 原始字节；`Content-Type` 为服务端嗅探值、`X-Content-Type-Options: nosniff`、`Content-Disposition: attachment` | 404 归属/存在性；409 内容缺失或被篡改 |
| GET | `/api/challenges/{cid}/artifacts/{aid}/integrity` | 200 `{artifact_id, sha256, valid}` | 404 归属/存在性 |
| GET | `/api/health` | 200，含 `artifact_max_bytes` | — |

`Artifact` 响应字段：`artifact_id, challenge_id, sha256, size, media_type, original_filename, ingested_at, source_event_id`。
未提供任何修改/删除 Artifact 的 API；对上述资源使用 `PUT/PATCH/DELETE` 返回 405。

错误消息不包含文件字节、原始文件名或磁盘路径。下载跨题目与不存在均返回 404，不区分二者，避免泄漏其他题目证据是否存在。

## 6. 安全设计对照

| 要求 | 实现 |
|---|---|
| 默认 50 MB | `DEFAULT_MAX_ARTIFACT_BYTES = 50 * 1024 * 1024`；两层限制：ASGI 入口按 `Content-Length`/chunked 字节计数预检（超限直接 413，不缓冲），`ArtifactStore.ingest` 流式读取时再精确累计（超限删除 staging、不落元数据）；`CTF_MAX_ARTIFACT_BYTES` / `create_app(max_artifact_bytes=...)` 可配置。 |
| 不信任客户端 MIME | 完全忽略 multipart 的 Content-Type；`detect_media_type` 按魔数（PNG/JPEG/GIF/PDF/ZIP/GZIP/7z/RAR/ELF/PE/TAR）与 UTF-8 文本嗅探，其余为 `application/octet-stream`。下载时回写服务端嗅探值并加 `nosniff`。 |
| 不用用户文件名作路径 | 路径由 sha256 派生；`sanitize_filename` 仅取 basename、去控制字符与 Windows 保留字符、截断 255，供显示/下载头使用。 |
| 拒绝路径穿越 | 挑战/附件 ID 只做数据库查询；存储路径用正则校验 64 位十六进制后拼接，`_guard` 用 `resolve()` + `is_relative_to(root)` 拒绝逃逸。文件名中的 `../`、`\`、`:` 被清理，不影响路径。 |
| 拒绝符号链接逃逸 | `_guard` 在写入/读取/清理前解析符号链接，目标一旦位于 storage root 之外即抛 `ArtifactPathError`。 |
| 不自动解压 | 实现只写字节，不解压、不执行、不解析容器；ZIP 上传后仅存在原 blob。 |
| 下载验证题目归属 | 元数据查询与下载均以 `(challenge_id, artifact_id)` 双条件查询；跨题返回 404。 |
| 敏感内容不进日志 | 应用不记录文件内容、文件名或字节；事件 payload 仅含元数据；异常统一为通用 HTTP 错误。 |
| 文件/DB 写入失败一致性 | 见第 4 节：入口限额 + blob 先行 + DB 事务原子 + 失败按引用清理未引用 blob + 上传锁串行化；写入侧仅用普通 INSERT，并以 `PRAGMA recursive_triggers=ON` 阻断 `INSERT OR REPLACE` 绕过 append-only 触发器。 |
| 不启用真实工具执行 | `tools.py`/注册表未改动，`/api/tools` 仍返回空注册表与 `execution_enabled: false`。 |

## 7. A01–A12 验收矩阵

| 编号 | 验收点 | 对应测试 |
|---|---|---|
| A01 | 上传成功、SHA-256 正确、元数据完整 | `test_a01_...` |
| A02 | 内容寻址布局、原始文件名不成路径、staging 清空 | `test_a02_...` |
| A03 | SQLite 元数据持久化与不可改触发器 | `test_a03_...` |
| A04 | 每次新建恰一条 `artifact_added` 事件、去重不新增 | `test_a04_...` |
| A05 | Artifact–Challenge–Event 三方关联 | `test_a05_...` |
| A06 | 附件列表（顺序、题目隔离） | `test_a06_...` |
| A07 | 元数据查询（200/404、跨题 404） | `test_a07_...` |
| A08 | 下载与题目归属校验、响应头、内容一致 | `test_a08_...` |
| A09 | 同内容去重（同题幂等、跨题独立 ID、单份 blob） | `test_a09_...` |
| A10 | 原始证据不可修改/删除（API 405、DB 触发器、篡改检测） | `test_a10_...` |
| A11 | 默认 50MB 限制、可配置限制下 413 且无残留 | `test_a11_...` |
| A12 | 服务重启后数据仍可用 | `test_a12_...` |

额外必需测试：重复上传、跨题目访问、文件篡改、数据库故障一致性、服务重启持久化、事件哈希链、并发重复上传；另有文件名穿越、MIME 伪造、符号链接逃逸、不解压、敏感日志、空文件等安全用例，均位于 `backend/tests/test_artifacts.py`。

## 8. 已知限制

1. **单进程假设**：上传锁只在单个 Python 进程内有效。多 worker/multi-process 同时写同一 data 目录时，并发去重与失败清理的竞态不由本版本保证；本地单用户服务按单进程运行。
2. **TOCTOU**：所有路径检查是应用级边界，检查与文件访问之间理论存在时间窗；没有 OS 级沙箱。下载采用「读入内存后校验再返回」，把校验与返回之间的窗口缩到最小，但内存占用最高为单个文件大小（默认 ≤50 MB）。
3. **无身份认证**：本地单用户服务，任何能访问回环端口的人都能调用 API；不要暴露到其他主机。题目归属校验只防跨题误用，不是多用户授权模型。
4. **哈希链的威胁模型**：链只能检测未重算哈希的偶然修改/简单篡改；拥有数据库与文件系统完全控制权的人可以重写整条链与事件头。没有外部签名/检查点。
5. **孤立 blob**：若数据库整体不可用，失败上传的 blob 无法通过引用计数确认，可能留下孤立文件（不会产生元数据行）；可通过下载 409/完整性接口发现内容问题，但缺少自动垃圾回收端点。非 `sqlite3` 的意外持久化异常已按同一引用计数规则做 best-effort 清理。
6. **multipart 解析层限制**：即使有入口限额，Starlette 仍会为通过预检的请求解析 multipart；本服务未限制 file part 数量（Starlette 默认最多 1000 个）。入口限额按请求总字节数封顶（`文件上限 + 64 KiB`），因此多 part 也无法成倍放大磁盘占用；但恶意客户端仍可能用多个小 part 触发解析开销。上传接口只采纳最后一个 `file` part。
7. **无 Range/断点续传**：下载一次性返回全部字节，不支持 HTTP Range。
8. **存储布局固定**：blob 路径由 sha256 推导，若未来改变布局需迁移旧数据。
9. **无文件预览/解压**：按设计不解压、不渲染附件；前端在本轮未接入附件上传（P1-1 只交付后端证据存储能力）。
10. **`original_filename` 仅作展示**：下载头使用清理后的文件名；若客户端需要原始 Unicode 名，使用 `filename*`；该字段不参与路径或去重。
11. **Windows 扩展路径**：存储根守卫对 `\\?\` 扩展路径前缀做规范化，避免并发解析时把合法路径误判为越界；该处理是防御性兼容，不改变 POSIX 行为。
12. **本地数据库控制者仍可 DROP TRIGGER**：`PRAGMA recursive_triggers=ON` 只堵住 `INSERT OR REPLACE` 静默替换行；能直接写 SQLite 文件的人依然可以移除触发器，这与第 4 条威胁模型一致。

## 9. SHA-256 校验示例

以下为本地单机实测（Windows PowerShell，`CTF_DATA_DIR=D:\CTF\.local-data\p1-demo`，`uvicorn` 监听 `127.0.0.1:8765`），附件内容为自造合成文本，不含任何比赛材料。

1）构造合成附件并在本机独立计算哈希（88 字节，UTF-8 无 BOM）：

```powershell
$content = "P1-1 synthetic attachment for SHA-256 demonstration`nNo real challenge material is used.`n"
[System.IO.File]::WriteAllText('D:\CTF\.local-data\p1-demo\synthetic-attachment.txt', $content, [System.Text.UTF8Encoding]::new($false))
(Get-FileHash 'D:\CTF\.local-data\p1-demo\synthetic-attachment.txt' -Algorithm SHA256).Hash.ToLower()
```

实测输出：

```text
f8286ce66fa6d06d3cd6ba8c7683780d98e6c84832a2d19bd5371ab6bda7b2c8
```

2）上传时故意声明错误的客户端 Content-Type（`text/html`），服务端忽略并使用嗅探结果 `text/plain`：

```powershell
curl.exe -sS -X POST "http://127.0.0.1:8765/api/challenges/$cid/artifacts" `
  -F "file=@D:\CTF\.local-data\p1-demo\synthetic-attachment.txt;type=text/html"
```

实测响应（节选）：

```json
{
  "artifact_id": "c36173ab-eabd-44e5-9661-892912c3cabb",
  "challenge_id": "d4553417-08d6-4a98-98a9-586980adfb90",
  "sha256": "f8286ce66fa6d06d3cd6ba8c7683780d98e6c84832a2d19bd5371ab6bda7b2c8",
  "size": 88,
  "media_type": "text/plain",
  "original_filename": "synthetic-attachment.txt",
  "ingested_at": "2026-11-07T11:06:53.672980+00:00",
  "source_event_id": "395633b1-a6df-4cdc-8c4d-475f09bf32f1"
}
```

3）按 SHA-256 定位内容寻址 blob 并再次独立校验：

```powershell
$sha = 'f8286ce66fa6d06d3cd6ba8c7683780d98e6c84832a2d19bd5371ab6bda7b2c8'
$blob = "D:\CTF\.local-data\p1-demo\artifacts\sha256\$($sha.Substring(0,2))\$($sha.Substring(2,2))\$sha"
(Get-FileHash $blob -Algorithm SHA256).Hash.ToLower()
(Get-Item $blob).Length
```

实测输出（与上传前本地哈希、API 返回的 `sha256` 三者一致）：

```text
f8286ce66fa6d06d3cd6ba8c7683780d98e6c84832a2d19bd5371ab6bda7b2c8
88
```

4）下载校验：下载字节的哈希与本地文件一致，响应头为 `X-Content-Type-Options: nosniff`、`Content-Type: text/plain; charset=utf-8`、`Content-Disposition: attachment; filename="synthetic-attachment.txt"`，下载后 `Get-FileHash` 比较结果为 `True`。
5）同内容重复上传返回 HTTP 200、同一 `artifact_id`，事件列表仍只有 1 条 `artifact_added`，事件链 `{"valid": true, "earliest_affected_sequence": null}`；`source_event_id=395633b1-a6df-4cdc-8c4d-475f09bf32f1` 与事件 `event_id` 一致。

## 10. 复现

```powershell
cd backend
python -m pytest -q
python -m ruff check app tests
```

或使用仓库脚本 `scripts/check.ps1`。

## 11. 独立安全审查记录

实现完成后由独立审查员（只读代码、临时目录跑对抗用例、未修改仓库）复核了 15 项安全/一致性要求，结论为「无严重 blocker，可提交 Draft PR」。审查发现并已在本分支修复/加固：

| 级别 | 发现 | 处理 |
|---|---|---|
| 中 M1 | FastAPI 在端点前已完整解析 multipart，50MB 限制只在缓冲后生效，2MB/50MB 请求会在 413/404 前先落临时盘；多 file part 可放大临时盘占用。 | 新增 ASGI 中间件 `ArtifactBodyLimitMiddleware`：`Content-Length` 预检 + chunked 字节计数（上限 = 文件上限 + 64 KiB），超限直接 413 且不进入解析；文档第 4/6/8 节同步说明；新增 2 个中间件测试。 |
| 低 L1 | Windows 并发 ingest 时 `Path.resolve` 偶发返回 `\\?\` 扩展路径，导致存储根守卫误判越界；孤立场景下下载可能 500。 | `_guard` 比较前剥离扩展路径前缀；下载/完整性把 `ArtifactPathError` 映射为受控 409/`valid=false`；新增 Windows junction 逃逸测试。 |
| 低 L2 | 非 `sqlite3.Error` 的意外持久化异常会留下孤立 blob。 | 上传端点对所有持久化异常执行「引用计数为 0 才删除」的 best-effort 补偿。 |
| 信息 L3 | `INSERT OR REPLACE` 不触发 DELETE 触发器，可静默替换 artifacts 行。 | 连接统一启用 `PRAGMA recursive_triggers=ON`；新增回归测试断言 REPLACE 被 append-only 触发器拒绝。 |
| 信息 L4/L5 | 上传锁为 per-app 实例锁；下载整文件入内存。 | 已作为单进程/内存占用限制写入第 8 节，属本地单用户服务的既定边界。 |

审查员还实测覆盖：文件名穿越/CRLF/Unicode/超长、MIME 伪造与 XSS、ZIP 不解压、跨题 404 不泄露、50MB 限额与无残留、API/DB/文件不可变性、blob 篡改/删除/截断检测与修复、DB 故障一致性、并发去重与事件链、日志泄密、目录 junction 逃逸，均符合预期。

