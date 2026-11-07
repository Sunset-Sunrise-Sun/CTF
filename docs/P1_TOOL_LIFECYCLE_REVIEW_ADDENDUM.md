# P1-2 Review R1–R4 收敛索引

版本：0.2，2026-11-07。修订父基线：8c4073975bc25c2b50ad2a18ee768ce6547080c8。

[原设计正文](P1_TOOL_LIFECYCLE_DESIGN.md) 是统一规范来源。本补充文档只提供 R1–R4 的定位和核对，不再覆盖正文，也不保留第二套 API、状态机或数据库主键。发现歧义应修正文档后再冻结实现，不允许实现方任选一种解释。所有接口均未实现，测试清单未运行。

| Review | 收敛位置 | 统一结果 |
|---|---|---|
| R1 取消语义 | 正文 §3 图、§3.1 矩阵、§4 API、§5 payload | PROPOSED 支持直接取消；APPROVED 未领取直接取消；已领取先意图后确认；启动许可不等于启动；RUNNING 依据真实终止结果。actor/HTTP/重放以 §3.1 为唯一矩阵 |
| R2 调度失败 | 正文 §3.2、§3 转换表、§5 tool_dispatch_failed | 已 claim 且可信确认未 spawn 才 FAILED_TO_START；claim 前拒绝无执行事件；启动不明 UNKNOWN |
| R3 终止竞争 | 正文 §3.2、§5 完成语义 | 依据单调时间和实际退出/终止因果，不以服务到达顺序决定；timed_out 与最终 TIMED_OUT 一致；证据不够 UNKNOWN |
| R4 批次流审计 | 正文 §8.1–8.4、§9 S01–S08、§10 兼容性 | 内部逐内容帧编号，持久化只有 model_stream_progress 连续区间批；batch_id PK、UNIQUE(request_id,first_sequence)，无逐 chunk 表/主键；终结接收数与持久覆盖分离，缺口显式 |

R1：响应统一为 CancelView。首次 200 表示直接未执行取消；202 只是取消意图。相同幂等请求重放首次 HTTP/响应；不同键但同用户同资源同取消操作也重放，不追加事件。不能通过迟到的取消把自然退出改为 CANCELLED，不能把 UNKNOWN 当作已停止。当前状态另用 GET 查询。

R4：chunk_sequence 是内部接收序号；batch_first_sequence 仅为 first_sequence 的描述性同义词，不是另一字段/主键。批 chunk_count=last-first+1；终结 chunk_count=received_chunk_count（实际接收总数，未知则二者 null），persisted_chunk_count 是批覆盖并集大小，persisted_batch_count 是批数。具体累计字段、gap 与未知尾部按正文 §8.2，schema 和幂等按 §8.3，不能将三种计数互换。

服务端批大小、等待时长、接收总数/字节/请求时长限额统一记录在请求审计。最后批次在成功/取消/失败前有界 flush；不能写入的部分显式 audit gap 或未知尾部，不假称已落盘。complete 需要 protocol_complete 与 audit_complete 同时成立。

验收仍限文档：本次检查不代表代码可运行、SQLite 约束已应用或测试通过。详见 [收敛检查记录](P1_TOOL_LIFECYCLE_CONVERGENCE.md)。PR 保持 Draft，等待独立验收；不下发实现，不开启模型网络或真实工具执行。
