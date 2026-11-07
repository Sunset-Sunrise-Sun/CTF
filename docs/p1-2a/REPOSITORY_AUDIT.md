# 仓库现状审计

## 1. 远程与工作区

已通过 Git fetch 更新远程 refs，并用 GitHub PR API 交叉核对：

| 基线 | 分支/PR | head / 状态 |
|---|---|---|
| P1-2 设计 | docs/p1-2-tool-lifecycle-design / #3 | 00e9436a73d33e01b1a288334b7c08a48661e42e；open、Draft |
| P0.1 | feat/framework-scaffold / #1 | ed4850dc17601a9e8177c12c95d1281e072cccd4；open、未合并 |
| P1-1 | feat/p1-evidence-storage / #2 | 778bad7c6db0f4412ce3c55bca0c24b78ad66905；open、未合并；base为P0分支 |
| KAT结构边界 | fix/kat-json-structure-limits / #4 | a577e9ce245423adf3e50cfaeb71d00d28db89d6；已squash合并 |
| PR #4 合并 | PR #3 祖先 | cb3a1114614a185258083e1a17f5c17bc058e5a1 |
| main | main | 575f3d06c66770ab37269e19e078691cd9a9a9f7；未修改 |

`git merge-base --is-ancestor cb3a111... HEAD` 返回0；P1-1 head对设计HEAD的祖先检查返回1。

当前聊天根目录及旧 work/CTF 是前期任务的非 Git 快照，不将它们误报为干净 checkout。没有找到已附着 worktree。新建专用 checkout `work/p1-2a-audit`，未覆盖已有文件；旧快照保持不动。初次无checkout clone的删除显示来自尚未物化的空index/工作树，切换分支后物化完成，`git status --porcelain=v1`为空。

前两次普通 clone连接重置；缩小为单分支/filter=blob:none后成功，再执行完整远程分支 fetch：

```text
git -c http.version=HTTP/1.1 fetch --prune origin '+refs/heads/*:refs/remotes/origin/*'
git switch -c feat/p1-2-implementation origin/docs/p1-2-tool-lifecycle-design
git rev-parse HEAD
# 00e9436a73d33e01b1a288334b7c08a48661e42e
git status --porcelain=v1
# 空；本包编辑前没有未提交修改
```

无 AGENTS.md。当前设计分支只有 README、设计/审计文档、scripts/kat 和tests/fixtures；没有 backend、frontend、pyproject.toml、package.json 或迁移。P0/P1-1 的检查和测试来自各自固定commit的独立快照，不声称它们已集成到PR #3。

## 2. 已核对的代码接口

以下生产接口来源均为 P1-1 head（包含P0.1）；不能直接从设计分支 import。

| 接口/文件 | 实际实现 | 后续接点与限制 |
|---|---|---|
| backend/app/models.py | Challenge五分类、Event完整envelope、Artifact、ToolProposal.call_id可空、ToolApproval、ToolStarted/Result等 | 缺 request_id/execution_id、完整生命周期状态/typed payload；旧EventType未包含全部新事件 |
| Store.__init__/connect | 扫描001/002；WAL，foreign_keys=ON，recursive_triggers=ON，sqlite连接timeout15秒 | 当前启动没有新schema完整性gate；未来迁移后不能由旧服务继续误读新EventType |
| Store._append_event(db,cid,actor,type,payload,artifact_ids=()) | 调用者事务内写Event、分配题目sequence、更新event_heads与hash | 没有event_refs入参；未来只扩展内部助手，不更改历史hash规则 |
| Store.append(...) | 自行获取连接、BEGIN IMMEDIATE，调用_append_event | 不能在另一个AuditStore事务中调用此public方法 |
| Store.add_artifact(cid,*,sha256,size,media_type,original_filename) | 返回(Artifact,Event或None)；自有事务，同题同SHA查重，新建artifact_added actor=user | 去重命中无新Artifact/来源事件；不能给每次工具输出重写source_event_id |
| Store.artifact(cid,aid) | 题目归属查询 | 完成事务内应使用同连接查询，不另开public读取连接拼凑一致性 |
| ArtifactStore.ingest(BinaryIO,filename=...) | 写staging、SHA256、大小/MIME、blob安装、尽力只读，返回IngestedArtifact | 原始字节不变，文件名不作路径；单Artifact默认50MiB |
| ArtifactStore.read_verified(sha) | 复算digest后返回bytes | 工具输出需在SQL前复核；锁顺序artifact_lock→SQLite，IO不放写事务内 |
| ModelProvider.complete/stream | 统一通信Protocol；三类兼容Chat Completions，Anthropic明确未实现 | 通信层不执行工具；真实调用未执行 |
| proposals(response,cid,scope) | call_id保留、每次重新生成proposal_id | 不是持久化幂等；缺request_id，需要新提案登记服务去重 |
| recorded_complete | success/ProviderError.code/internal_error/cancelled；finally一次model_call | 没有请求开始事件；审计写入失败仍可能覆盖原调用异常 |
| OpenAICompatibleAdapter.stream | 内容及tool片段累积；DONE break；自然EOF也返回response；旧异常统一transport_error | 缺终结证明、finish_reason、完整内容块元数据与严格入口预算；不能直接当AuditedStreamSource |
| DisabledBroker | 空registry，未批准拒绝，已批准仍拒绝 | 必须继续保持；不把FakeRunner装入真实broker |
| main.py | 单用户回环服务、无可信审批身份；health execution/model_network=false | 未来审批/调度不得仅信客户端字符串或回环可达；本轮不加路由 |

## 3. SQLite 基线

001：challenges(body JSON)、events(event_id PK,cid FK,sequence UNIQUE per cid,body JSON)、event_heads；events UPDATE/DELETE触发器禁止修改。

002：artifacts；UNIQUE(challenge_id,sha256)，source_event_id UNIQUE，(challenge_id,source_event_id)联合FK到events；不可更新/删除。events新增(challenge_id,event_id)唯一索引。`recursive_triggers=ON`堵住REPLACE删除触发器绕过。

SQLite JSON body和关系投影的一致性目前靠服务校验；不能宣称FK会自动检查JSON payload。新状态/幂等/事件索引必须原子提交并支持重放验证；事件头能检测未重算hash的尾删，但不是对本机owner的外部密码学证明。

## 4. 冲突、缺口与审查 gate

| ID | 等级/性质 | 证据与处理 |
|---|---|---|
| G01 | 实施前置阻断 | PR #3不含P0/P1-1。待独立审查确定整合权限与版本；不自动merge/cherry-pick，不复制另一份生产Store/Event来绕过依赖 |
| G02 | 实施前置接口缺口 | public Store事务不能组合；需批准内部同连接助手和AuditUnitOfWork改动方案，public语义冻结 |
| G03 | 迁移建表依赖 | 003工具模型来源FK需要model_requests；004模型审计与tool proposal又互相引用。按MIGRATION_PLAN建议分配前置身份表，待审，不创建SQL |
| G04 | Provider设计适配缺口 | 旧stream不能提供DONE/finish/原始入口计数。先定义FakeStreamSource/观察契约；生产旧adapter不得被包装成“完整可信”响应 |
| G05 | 已知参考实现局限 | 非结构组合错误如重复键+float/NaN仍有跨语言错误优先级差异；既有195条已冻结，不擅改expected，未列情况待独立规范任务 |
| G06 | 部署/认证前置 | 无可信用户身份/隔离器/密钥backend，故真实审批/调度/模型审计生产路径继续禁用；仅测试注入 |

推荐整合方式供审查：P1-1已包含P0.1，未来若获授权，可在实施分支整合经验收的P1-1固定版本而不重复移植P0；PR #1/#2/#3的分支不由此任务改写。当前只是文档提案。后续若基线发生变化，必须重做接口差异与测试记录。
