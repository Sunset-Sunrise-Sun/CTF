# Migration 与事务设计（待审核，未创建SQL）

## 1. 依赖 gate 与版本布局

前置必须是经审核的P1-1 schema 001+002；PR #3当前没有这些文件或应用代码。本轮不新建数据库，不应用迁移。既有001/002内容、Event canonical与Artifact public语义冻结。

设计 §6/§8.3建议003_tool_lifecycle和004_model_audit，但工具model来源FK依赖model_requests，004又涉及工具提案。推荐实现文件职责如下；这是建表顺序的实施提案，不改变事件/字段协议，待独立审查后才能落SQL：

| 迁移 | 表/约束 | 依赖处理 |
|---|---|---|
| 003_tool_lifecycle.sql | audit_datasets、audit_key_versions元数据清单、最小model_requests身份表、request_dedup；工具proposal/decision/cancel/execution/transitions/state/event_links/capture/output表 | model_requests提前提供(challenge_id,request_id)父键；不生成任何真实key或model请求。已有artifacts补(challenge_id,artifact_id)唯一索引 |
| 004_model_audit.sql | model_stream_progress、model_stream_gaps、model_terminals、model_state；stream区间/terminal guard；依赖terminal完整性的模型来源提案guard | 所有父表已建后才装跨模块guard；应用只在两迁移齐备且FK/schema校验通过后启动 |

003完成而004失败时不启动新服务，不执行任何工具/模型写入；重启按schema_migrations已提交版本重试004。单迁移DDL+marker原子，保留当前Store机制；不承诺把两文件当作一次原子事务。不得以“旧backend只认识001/002”继续服务新schema，旧EventType解析也不兼容新生命周期；不支持应用降级，恢复应使用停机前一致备份。

## 2. 主键、关联与状态约束

| 对象 | 必须约束 |
|---|---|
| proposals | proposal_id PK，(cid,pid) UNIQUE；origin与request_id/call_id同时空/同时非空；模型partial UNIQUE(cid,request_id,call_id)；提案摘要不可变 |
| decisions/cancel_operations | 每proposal一条decision；每proposal一条user取消操作，记录首次响应；不可UPDATE/DELETE；同题event/proposal FK |
| executions | execution_id PK，proposal_id UNIQUE；claim_nonce仅hash、owner/lease；拒绝/无批准不可claim；lease过期不允许再spawn |
| transitions/event_links | event_id唯一，同题proposal/execution/Event联合FK；proposed/decision/start/finish一次性唯一；重复interrupted按occurrence_id，不能全phase唯一 |
| tool_state | proposal_id PK，state/revision/latest_event_id；CAS from_state/revision，事件和投影同事务 |
| capture_segments | capture_id PK，UNIQUE(execution_id,role,segment_sequence)，source为tool_output_captured；只追加版本，不覆盖prefix |
| output_links | PK(execution_id,role)，Artifact与finished event同题FK；两role允许同Artifact；最终事务写一次 |
| model_requests | request_id PK，(cid,request_id) UNIQUE，start_event_id UNIQUE；dataset/key/version固定，不保存请求正文/API Key |
| stream_progress | batch_id PK，UNIQUE(request_id,first_sequence)，event_id UNIQUE；count=last-first+1；区间不重叠；typed整数/64hex/version/key绑定 |
| stream_gaps | gap_id PK，UNIQUE(request_id,first_sequence)，已知范围/未知尾部互斥；不可与批或gap重叠，未知上界视为无界 |
| model_terminals/state | 每request一个终结，terminal event唯一；state可变CAS，终结后禁新progress/gap；历史当前校验状态不回写terminal |
| dedup | PK(cid,principal,operation,key)；摘要覆盖method+规范route含cid/pid+canonical body，不存秘密；同键异资源冲突 |

所有不可变关系表与Event禁止UPDATE/DELETE/REPLACE绕过；继续foreign_keys=ON、recursive_triggers=ON。跨行合法转换、proposal批准、同题artifact、先started再finished、stream terminal与区间累计均需受控SQL/服务联合校验，不能宣称SQLite自动验证JSON body与关系列一致。

Capture/output链接避免循环：先artifact_added Event，再Artifact；再tool_output_captured及capture关系；最后tool_finished Event，再引用它的output links/转换/state。FK引用已经插入的关系，JSON中的未来ID由服务在提交前校验，不新增反向Event JSON FK，不要求破坏P1-1 source_event_id严格一对一。

## 3. 同连接事务接点

AuditUnitOfWork是操作事务的唯一owner，连接来自现有Store配置；内部助手接收db参数且禁止commit/BEGIN。不得在UnitOfWork中调用public append/add_artifact/get等重新开连接，再用外层commit假装原子。提供同连接get_challenge/state/artifact/sequence查询。

后续提取 `_add_artifact_in_tx(db,cid,metadata,actor)`：复用同题同hash查重、来源唯一逻辑，返回既有(Artifact,None)或新(Artifact,Event)；public add_artifact仍自行开事务并以actor=user调用，原签名不变。工具路径新Artifact的actor=tool，但命中旧Artifact时不重写其source_event_id。

`_append_event`只增加可选event_refs内部参数，默认空，保持旧调用与Event hash bytes。不能对历史body进行重排/规范化更新。模型C/R_i/M的ctf-cjson-int-v1是另一投影，不替换Event现行canonical。

## 4. 必须在实现任务验证的迁移/故障矩阵

- 从仅001、已有001/002且有合成Challenge/Event/Artifact的DB升级；逐字节比对历史body/hash/下载bytes，保留dedup/source。
- 003/004各SQL中途故障、marker故障、重启重试；004失败后服务启动拒绝，不能部分开放。
- FK/索引检查与插入跨题负例；JSON与关系错配服务拒绝；同请求并发CAS、重复claim/start/finish/terminal拒绝。
- 原子完成每个insert后注入异常：无半个state/head/Event/Artifact/dedup响应；文件blob残留只走安全恢复/引用清理，不误删共享证据。
- REPLACE/UPDATE/DELETE、未知schema版本启动、旧应用降级拒绝、两个连接题目序列竞争。
- 输出同bytes/空bytes两role去重；恢复UNKNOWN只追加capture版本，不能改历史或重执行。

这些是未来测试要求，本轮没有创建003/004或声称它们已运行通过。建表职责分配与跨模块guard应由ChatGPT先审，再交DeepSeek实现。
