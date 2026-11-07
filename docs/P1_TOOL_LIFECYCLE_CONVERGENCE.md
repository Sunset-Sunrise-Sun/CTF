# P1-2 R1–R4 最终设计收敛记录

日期：2026-11-07。父提交：8c4073975bc25c2b50ad2a18ee768ce6547080c8。分支：docs/p1-2-tool-lifecycle-design；延续 PR #3，不修改 main 或 PR #1/#2。

## R1–R4 对照

| Review | 原问题 | 文档修订 | 文档检查结论 |
|---|---|---|---|
| R1 | 原文拒绝未审批取消，补充文档允许；图/API/actor 不同 | §3 增 PROPOSED→CANCELLED；§3.1 给出七类阶段矩阵与重放优先级；§4 CancelView/HTTP；§5 取消事件字段与 actor | 图、矩阵、API、payload 和补充索引逐项对照一致 |
| R2 | 调度失败边界需保留 | §3.2 合入 FAILED_TO_START 唯一映射，明确 actor=system、claim 前无执行事件 | 无 claim 不产 dispatch_failed；无法证明未启动 UNKNOWN；已有 start 不回退 |
| R3 | 超时/取消/自然退出的事实竞争 | §3.2 合入单调时间、退出/终止因果规则，约束 timed_out 和 reason | 意图不等于结果；自然退出保留真实 exit code；不确定 UNKNOWN |
| R4 | 逐块事件/主键与批次设计冲突 | 整体重写 §8；替换 Mermaid、批事件/schema/累计/gap；S01–S08 和 §10 同步 | 只保留一套批持久化契约，撤销逐 chunk 新写入契约 |

## 状态机与事件契约一致性检查（静态文档核对）

- PROPOSED 取消：图有直达 CANCELLED；矩阵/API 200；payload tool_cancelled_before_start、actor=user、refs=proposed；无审批或执行事件。
- APPROVED 未领取：图直达 CANCELLED；200；同事件 actor=user、refs=approved；无 execution。
- 已 claim 无许可：图 APPROVED 自环（意图）；202；tool_cancel_requested/user；许可 CAS 拒绝后 system 确认 before_start。不能直接假定已停止。
- 已获许可未收开始回执：202；先意图；确认未 spawn 才 before_start，已启动则真实 started 后进入 RUNNING，无法确认 UNKNOWN。
- RUNNING：图自环（意图）；202；取消致终止才 finished/tool/CANCELLED；自然退出 SUCCEEDED/FAILED；失联 system/interrupted/UNKNOWN。
- 同一取消重试：原 HTTP/CancelView；不新建事件。新请求在其他终态/UNKNOWN 为 409；有原操作则优先重放，GET 查询最新状态。
- 审批、调度、开始、完成的原始证据边界保留；取消不创造假的 started/finished。R2/R3 已并入正文，不靠附录覆盖解释。
- 流式图的内部接收动作无逐块 Event，持久化自环名为 model_stream_progress；终结是一条 model_call，成功并非默认状态。

## 数据库主键与幂等性检查（静态文档核对）

| 对象 | 唯一设计 | 重试/冲突 |
|---|---|---|
| 用户写请求 | challenge+principal+operation+key；摘要覆盖 method、路由资源 ID、canonical body | 相同重放；跨提案/异请求 409 |
| 取消操作 | 每 proposal 一条有效 user 取消意图或直接取消（互斥）；确认另有独立事件 | 同用户同资源重试无新意图；其他用户不可借用 |
| 模型流批 | batch_id PK；UNIQUE(request_id,first_sequence)；event_id UNIQUE；连续区间 CHECK | 同 batch/digest 查回原事件；异载荷、同 first、重叠均拒绝 |
| 内部内容序号 | request 内 chunk_sequence，从 1 单调递增 | 不作为 DB 行主键；batch_first_sequence 不另立字段 |
| 缺口 | gap_id PK；同题 request/event FK | 精确范围或未知尾部；不可由补造批消除；不把 gap 当进度 |
| 终结 | request_id PK；terminal_event_id UNIQUE；CAS | 至多一条 model_call，禁止第二终结和终结后新批 |

批 row/event/state/head 原子；批不重叠检查不能仅依赖起点唯一键；已声明 gap 区间不能补插批。终结实际接收总数、持久覆盖数、批数分别命名；丢失挥发接收状态时总数 null + 下界 + unknown_tail，不从最后批推断完整。

## 变更文件（仅设计 Markdown）

1. docs/P1_TOOL_LIFECYCLE_DESIGN.md：统一正文（§3–§5、§6 取消约束、§8、§9、§10及版本/引用）。
2. docs/P1_TOOL_LIFECYCLE_REVIEW_ADDENDUM.md：替换为不覆盖正文的 R1–R4 索引。
3. docs/P1_TOOL_LIFECYCLE_CONVERGENCE.md：本次对照及一致性检查记录。

## 未实现、未测试

未新增或修改 Python/前端代码、SQL 迁移、执行接口或网络入口。未执行真实工具或模型调用，未应用所提 schema，未运行 S01–S08/L/A/C 测试，也未验证 SQLite 触发器、并发时序、API 返回、限额性能或故障恢复。Mermaid 仅做源文本结构核对，未用渲染器验证。上述“检查一致”仅为文档审查结论，不是运行测试通过。

PR 描述同步更新，保持 Draft，等待独立验收；本轮不授权实施或合并。
