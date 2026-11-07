# A00 固定基线整合证据

本 PR 仅整合固定 P1-1（含 P0.1）并交付回归证据，等待独立验收；没有启动 A01。

## 分支与历史

- 新分支：`feat/p1-2-a00-integration`；目标：`docs/p1-2-tool-lifecycle-design`。
- 固定设计父提交：`00e9436a73d33e01b1a288334b7c08a48661e42e`。
- 固定 P1-1 父提交：`778bad7c6db0f4412ce3c55bca0c24b78ad66905`。
- 发布的双父整合提交：`e581144c68bf05932334decc4babc9b61a764bb5`。
- 整合文件树：`9bdb4dae5ba811b2770e5445a57820b1ba427692`；后续证据提交只增加本目录文档。
- P0.1 `ed4850dc17601a9e8177c12c95d1281e072cccd4` 是 P1-1 的祖先，二者 merge-base 就是 P0.1。
- 设计与 P1-1 的 merge-base：`575f3d06c66770ab37269e19e078691cd9a9a9f7`。
- 整合后，设计和 P1-1 都是 HEAD 的祖先；完整命令见 [ancestry.txt](ancestry.txt)。
- PR #5 分支仍是 `23f5387f1b144dbac5c6ffefdef17b37e5d21abd`，未纳入本次整合；没有改动任何既有 PR 的源分支或描述。

## 整合和冲突记录

开始时原检出在 PR #5 提交，工作区干净。执行远程 fetch，然后从固定设计提交创建新分支，再执行 `git merge --no-ff --no-commit 778bad7c6db0f4412ce3c55bca0c24b78ad66905`。Git 未报告冲突，`git ls-files -u` 为空；没有手工解决文本冲突。

Git HTTPS fetch/push 在本机连接超时，未将失败记录为成功；见 [fetch.txt](fetch.txt)。通过已连接 GitHub API 独立核实远程 PR #1/#2/#3/#5 的固定 head，并创建新分支、复用已有 blob 创建同一 tree、创建双父提交、以 expected_sha 检查快进更新。未使用 force push。

本地未发布候选合并提交 `20e501f7b9019f77723a0d02adea939f2f7d4574` 与发布提交具有相同有序父提交和相同 tree，仅提交者元数据不同。候选保留于本地 `refs/a00/unpublished-local-merge`。本地以精确 Git 对象 SHA 校验导入发布提交后同步新分支，没有改变工作树文件，也没有重写任何已发布历史。本文所有回归均重新在发布的整合提交上执行。

Windows 全局 `core.autocrlf=true` 原会改变检出字节。确认无用户修改后，本仓库本地设置 `core.autocrlf=false`，将检出恢复为 Git blob 原始字节并刷新索引；没有修改任何被提交 blob 或 KAT expected。

## 文件完整性

整合前设计树 14 个文件，整合后 56 个文件。相对设计基线为 42 个新增文件和 README 更新，共 43 个文件、7943 行新增；完整文件树和变更清单见 [tree-before.txt](tree-before.txt)、[tree-after-integration.txt](tree-after-integration.txt)、[tree-diff.txt](tree-diff.txt)。证据文档是额外的 docs/a00 文件。

固定 P1-1 的全部 47 个文件，其 mode 与 Git blob SHA 均与整合树一致。设计原有 14 个文件中，13 个完全保留，README 为 P1-1 原版。没有第二套 Store/Event/ArtifactStore，没有遗漏后端、测试、前端、001/002、CI、脚本、原设计与测试报告。所有 Python 生产代码、测试代码和 API 契约直接继承固定 P1-1，未另行修改。

依赖文件是源提交已有的 `backend/pyproject.toml`（直接依赖精确版本）和 `frontend/package-lock.json`。源提交没有根目录 pyproject.toml，也没有 Python 传递依赖锁文件；本次没有虚构或新增锁文件。此次实际环境见 [environment.txt](environment.txt)。

## 历史兼容性

核验脚本及输出见 [COMPATIBILITY.md](COMPATIBILITY.md) 和 [compatibility.json](compatibility.json)。所有数据库和附件均为临时目录中的合成数据，没有触碰历史用户数据库。

1. 从固定 P0 提交直接加载 Event 模型、canonical 与 digest，按原始 001 建库、写入固定时间/ID 的中文合成事件。整合代码应用 002 后，原 Event body UTF-8 字节、canonical 字节、event_hash、event_heads 均不变，hash chain 有效。
2. 用固定 P1-1 Store 源码创建已有 Artifact 数据库及内容寻址合成 blob，再由整合后的应用打开、下载和重复上传。challenges/events/event_heads/artifacts/schema_migrations 所有行完全不变；source_event_id 不变；同 Challenge 相同 SHA256 返回已有 Artifact，不新增事件；下载字节 SHA256 一致。
3. 整合应用创建的新合成 Artifact 经重启再去重，事件、head、Artifact 全部行不变，artifact_added 事件包含该 artifact_id，Artifact 回指真实 source_event_id。
4. 001/002 SQL 文件及 Store/Artifact/API/Provider 模块原 blob 不变，因此约束、触发器、序列化和接口签名未改变。实际全量回归包含跨 Challenge FK、source_event_id 唯一、递归 REPLACE 不可绕过 append-only、升级保留事件、并发去重等既有测试。

固定历史合成事件 hash：`05c9cc5912383e872e9d6379b5ef06c33699cd5b6fcaccfeef342ad46aa24d02`；原 body SHA256：`9b7be21db6f92c6ddfadf33891384babf84ff17344c13c9b7dac5489080baf19`。

## 实际回归结果

见 [REGRESSION.md](REGRESSION.md) 中的实际命令、退出码和完整输出；运行位置均是实际 A00 分支的整合工作树，日志逐项标注发布整合 HEAD，没有引用旧快照测试。

| 检查 | 结果 |
| --- | --- |
| P0/P0.1 原有三个后端测试文件 | 28 passed，2 skipped |
| P1-1 后端全量（包含 P0） | 75 passed，3 skipped |
| Ruff（app/tests） | 通过 |
| npm ci | 成功；保留 npm 的 esbuild 安装脚本提示 |
| TypeScript | 通过 |
| 前端生产构建 | 通过 |
| Python 离线 KAT | 195 frozen cases + 6 fresh-process checks 通过 |
| Node.js 离线 KAT | 195 frozen cases + 6 fresh-process checks 通过 |
| 跨语言比较 | 195 exact results；56 正向、139 精确错误码；全部字节一致 |
| 原 KAT SHA256SUMS | 4/4 一致 |
| 合成历史兼容性检查 | 通过 |

跳过项：Windows 无符号链接创建权限的两个用例、显式禁用的真实模型用例（P0 子集只有其中一个符号链接用例）。未把跳过项算作通过。没有在本机验证 Linux/CI、真实 Provider 或真实工具；离线 KAT 通过不代表生产流式审计或 HMAC 已实现。

验证辅助脚本开发过程中曾使用错误的 `/download` URL（实际为 `/content`），并出现 Windows SQLite 临时文件清理句柄问题；修正检查脚本路径并显式关闭连接后重跑成功。首次前端日志打印还遇到终端 GBK 无法打印勾号，设置日志捕获进程 UTF-8 后重跑构建成功。以上均未修改应用源码，最终日志为实际重新运行结果。

## 范围边界与验收状态

迁移目录只有 `001_initial.sql`、`002_artifacts.sql`；未创建 003/004，未开发 ToolLifecycleService、AuditStore、ModelStreamAuditService 或其他 P1-2 业务逻辑。DisabledBroker 保持原版禁用；实际 health 返回 execution_enabled=false、model_network_enabled=false。没有调用真实模型、执行工具、使用比赛附件、生成真实审计密钥或修改冻结 KAT。

本 PR 保持 Draft，等待 ChatGPT 对实际 diff、回归和数据兼容性独立审查。A00 是基线整合交付，不将自检替代独立验收；停止在此，不启动 A01。
