# P1-1 修复报告：Artifact 与 Event 关联约束

日期：2026-11-07  
分支：`feat/p1-evidence-storage`  
PR：#2 https://github.com/Sunset-Sunrise-Sun/CTF/pull/2 （Draft，目标 `feat/framework-scaffold`）  
修复提交：`9a7a94ea8d8af9e0a4cda7d50fc8a2ea0bfe43d3`

## 1. 问题（独立验收发现）

`002_artifacts.sql` 中的来源事件外键为：

```sql
source_event_id TEXT NOT NULL REFERENCES events(event_id)
```

它只保证来源事件存在，缺少两类数据库级约束：

1. 同一个 `event_id` 可以被多个 Artifact 引用，`Artifact ↔ Event` 不是严格一对一；
2. 没有约束 Artifact 的来源事件必须属于同一个 Challenge，跨题引用在 DB 层不会被拒绝。

## 2. 根因

初版只考虑了「事件存在性」外键，没有把关联基数（1:1）和归属（同题）表达为数据库约束；应用层写入路径虽然总是新建事件并带同一 `challenge_id`，但直接 SQL 写入或未来复用 `Store.add_artifact` 的代码可以绕过。

## 3. 修复内容

更新尚未合并的 `backend/app/migrations/002_artifacts.sql`（未修改 `main`，未新增 003）：

```sql
-- 联合外键的父键：events 上的复合唯一索引
CREATE UNIQUE INDEX events_challenge_event ON events(challenge_id, event_id);

CREATE TABLE artifacts (
 ...
 source_event_id TEXT NOT NULL UNIQUE,
 UNIQUE(challenge_id, sha256),
 FOREIGN KEY (challenge_id, source_event_id)
  REFERENCES events(challenge_id, event_id)
);
```

- `source_event_id UNIQUE`：一个事件最多关联一个 Artifact，Artifact ↔ 来源事件严格一对一。
- `(challenge_id, source_event_id) → events(challenge_id, event_id)`：来源事件必须与 Artifact 属于同一 Challenge，跨题引用触发 `FOREIGN KEY constraint failed`。
- `events_challenge_event` 复合唯一索引：SQLite 要求联合外键的父键有对应唯一索引；`event_id` 本身已是主键，该索引不改变现有事件行为。
- 保留原有 `UNIQUE(challenge_id, sha256)` 去重约束、`artifacts_no_update` / `artifacts_no_delete` 触发器、`challenge_id` 外键与事件哈希链逻辑。
- 应用代码无需改动：`Store.add_artifact` 仍在同一事务内先写 `artifact_added` 事件，再写引用该事件、同一挑战的 Artifact 行，自然满足新约束；上传、去重、跨题同内容独立 ID、事件链行为不变。

实测约束效果（临时库直接 SQL）：

```text
同一 event 再插第二个 Artifact → sqlite3.IntegrityError: UNIQUE constraint failed: artifacts.source_event_id
用 A 题事件在 B 题插 Artifact → sqlite3.IntegrityError: FOREIGN KEY constraint failed
失败写入后两题事件链仍为 {"valid": true, "earliest_affected_sequence": null}
```

## 4. 新增测试（`backend/tests/test_artifacts.py`）

| 测试 | 覆盖点 |
|---|---|
| `test_source_event_is_unique_per_artifact` | 同一 `event_id` 不允许关联两个 Artifact（`UNIQUE`），且失败后列表与事件链不变。 |
| `test_artifact_cannot_reference_other_challenge_event` | Artifact 不允许引用其他 Challenge 的事件（联合外键 `FOREIGN KEY`），跨题列表仍为空、两题链均有效。 |
| `test_constraints_keep_upload_dedupe_and_cross_challenge_behavior` | 正常上传 201；同题重复上传 200 且不新增事件；跨题同内容 201、独立 `artifact_id`、独立来源事件、单份 blob；两题事件链有效。 |
| `test_migration_preserves_p0_data_and_adds_relation_constraints` | 用仅应用 `001_initial.sql` 的 P0 数据库验证升级：原挑战/事件可读、哈希链 valid、`schema_migrations` 为 001+002、`events_challenge_event` 索引与联合外键存在；升级后通过 API 仍可读 P0 数据并成功上传新 Artifact。 |

完整事件哈希链：上述测试与既有 A01–A12、W07 类篡改测试全部保持通过（`GET /api/challenges/{cid}/integrity` 与 `Store.verify` 均为 valid）。

## 5. 迁移兼容性

- 本修复只针对**尚未合并**的 `002_artifacts.sql`，因此不需要新增迁移，也不修改 `main` 分支已发布内容。
- 对只有 P0（001）数据的数据库：启动时按 `schema_migrations` 增量应用 002，P0 挑战与事件原样保留（新增测试已覆盖）。
- 对已经用旧版 002 建过库的本地开发数据目录：`schema_migrations` 已记录 002，SQLite 不会重放修改后的文件；需要删除/重建该本地开发数据目录（本轮未发布迁移，不涉及生产或验收环境）。该限制已写入设计文档第 2 节。

## 6. 验证结果

本地（Windows PowerShell，Python 3.14.7）：

| 检查 | 结果 |
|---|---|
| `python -m pytest -q` | **75 passed, 3 skipped, 0 failed**（5.94s） |
| `python -m pytest -q tests/test_artifacts.py` | **47 passed, 1 skipped, 0 failed**（4.13s） |
| `python -m ruff check app tests` | **All checks passed** |
| `python -m ruff format --check app tests` | **13 files already formatted** |

跳过项与上一轮一致（Windows 无符号链接权限；P0 既有 Provider 凭证跳过）。

远程 CI（修复提交 `9a7a94e`）：

| 运行 | 事件 | 结果 |
|---|---|---|
| https://github.com/Sunset-Sunrise-Sun/CTF/actions/runs/42369281970 | push | **success**（backend / frontend） |
| https://github.com/Sunset-Sunrise-Sun/CTF/actions/runs/42369286696 | pull_request | **success**（backend / frontend） |

本报告所在文档提交会触发同一 `P0 checks` workflow，PR 最终 head 结果以 PR Checks 页面为准。

## 7. 范围与未做事项

- 未修改 `main`，未合并 PR。
- 未新增/修改 API 契约，未改动上传、去重、下载、事件链实现。
- 未开展其他 P1 模块（工具执行、Writeup、前端接入）。
- 未把「来源事件必须是 `artifact_added` 且 payload.artifact_id 指向本 Artifact」做成数据库触发器；该语义仍由 `Store.add_artifact` 保证（本轮验收要求为 1:1 与同题归属两类约束）。
