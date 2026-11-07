# P1-2 R1–R4 最终设计收敛记录

日期：2026-11-07。本次 R4 内容指纹修订父提交：89be6021aa9022ca484dc6c663d3409f20437d5d；此前收敛父提交：8c4073975bc25c2b50ad2a18ee768ce6547080c8。分支：docs/p1-2-tool-lifecycle-design；延续 PR #3，不修改 main 或 PR #1/#2。

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
| 模型流批 | batch_id PK；UNIQUE(request_id,first_sequence)；event_id UNIQUE；连续区间 CHECK | 受信层按实际候选内容重算 content_fingerprint 和 batch_digest 后幂等；仅旧回执不等于内容重验；同 first/重叠仍拒绝 |
| 内部内容序号 | request 内 chunk_sequence，从 1 单调递增 | 不作为 DB 行主键；batch_first_sequence 不另立字段 |
| 缺口 | gap_id PK；同题 request/event FK | 精确范围或未知尾部；不可由补造批消除；不把 gap 当进度 |
| 终结 | request_id PK；terminal_event_id UNIQUE；CAS | 至多一条 model_call，禁止第二终结和终结后新批 |

批 row/event/state/head 原子；批不重叠检查不能仅依赖起点唯一键；已声明 gap 区间不能补插批。终结实际接收总数、持久覆盖数、批数分别命名；丢失挥发接收状态时总数 null + 下界 + unknown_tail，不从最后批推断完整。

## 上一轮收敛变更（历史记录，非本轮文件清单）

1. docs/P1_TOOL_LIFECYCLE_DESIGN.md：统一正文（§3–§5、§6 取消约束、§8、§9、§10及版本/引用）。
2. docs/P1_TOOL_LIFECYCLE_REVIEW_ADDENDUM.md：替换为不覆盖正文的 R1–R4 索引。
3. docs/P1_TOOL_LIFECYCLE_CONVERGENCE.md：本次对照及一致性检查记录。

## 未实现、未测试

未新增或修改 Python/前端代码、SQL 迁移、执行接口或网络入口。未执行真实工具或模型调用，未应用所提 schema，未运行 S01–S08/L/A/C 测试，也未验证 SQLite 触发器、并发时序、API 返回、限额性能或故障恢复。Mermaid 仅做源文本结构核对，未用渲染器验证。上述“检查一致”仅为文档审查结论，不是运行测试通过。

PR 描述同步更新，保持 Draft，等待独立验收；本轮不授权实施或合并。



## 前次 R4 内容完整性修订：修改前后（历史记录）

| 项目 | 修改前 | 修改后 |
|---|---|---|
| batch_digest 语义 | 只覆盖 ID/区间/计数/时间等元数据，不覆盖内容 | HMAC-SHA256 认证全部批元数据与 content_fingerprint 的组合 |
| 内容绑定 | 同长度不同文本无法区分 | 独立 content_fingerprint 覆盖实际公开内容/工具增量、片段边界/顺序/序号与上下文 |
| 持久化 | 元数据摘要，无正文 | 仍无正文，增加 fingerprint_version/key_id/content_fingerprint；两 tag 均不截断 |
| 重启 | 查同 digest 容易误称同内容重验 | 旧回执认证与带真实候选字节的内容重验分离；无字节只能 receipt_only |
| 密钥与恢复 | 未定义 | 专用 32 字节随机 K，OS 密封持久化；请求固定 key/version/dataset；轮换 draining→verify-only；旧 key 丢失/撤销不可验证且不降级 |
| schema / S07 | 仅 metadata digest 与笼统重放用例 | 保持唯一批 PK，加版本/指纹/key 清单与 dataset 身份；S07 覆盖同元数据异内容、重启与密钥生命周期 |

### 完整性指纹定义（规范来源：正文 §8.1.1）

- J 为正文 canonical JSON 的 UTF-8 字节；F(b)=U64BE(len(b))||b。
- C 绑定 fingerprint_version、key_id、audit_dataset_id、challenge_id、request_id、batch_id、first_sequence、last_sequence、chunk_count。
- R_i 是每个 chunk_sequence 的公开文本与按原序排列的工具增量的规范投影；包含原始 function.arguments 字符串片段和 call id，不解析重编码参数，不正规化字符串；不保存 R_i。
- content_fingerprint=hex(HMAC-SHA256(K, F(content-domain)||F(J(C))||F(R_first)||...||F(R_last)))。
- M 是全部批元数据加上下文/版本/key_id/content_fingerprint，排除 batch_digest 自身及 Event envelope。
- batch_digest=hex(HMAC-SHA256(K, F(batch-domain)||F(J(M))))。两个 domain 精确值分别是 ASCII 的 CTF/model-stream/content/v1 和 CTF/model-stream/batch/v1，使用完整 256-bit 输出。

定义保护解析后未改写的公开内容投影字节，不声称保护 TCP/SSE wire 原貌或私有推理。完整公式、投影字段、缺失/null 区别、版本拒绝规则和密钥恢复均以正文为准；不是另起算法方案。

### 幂等性验证矩阵（设计检查，未运行）

| 场景 | 规定行为 |
|---|---|
| 同 batch_id、实际内容/冻结元数据相同 | 重算两 HMAC 后返回原事件，无新事件/计数 |
| 同元数据但同长度不同文本/工具参数/call id | 内容 tag 不同，409 batch_replay_conflict，零写入 |
| 内容块边界/次序/序号或 request/batch/dataset 被替换 | 上下文与长度前缀绑定，拒绝；跨题统一 404 |
| 新 batch_id 重占旧 first/重叠区间 | 唯一与 overlap 约束拒绝，不因有合法 tag 而放行 |
| 重启恢复旧 key，存在真实候选字节 | 按旧版本原上下文重算；同内容幂等，不同内容冲突 |
| 重启仅有已提交元数据/tag | 只验证 batch_digest/Event 绑定，receipt_only、content_reverified=false；不能接受复制 tag 当新内容证明 |
| 未提交缓冲丢失 | 无法恢复正文，gap/unknown_tail，不重发模型补造 |
| key 丢失/权限失效/撤销/算法版本不支持 | 明确不可验证/失败关闭，不生成替代 key 或回退元数据比较 |

### 本次静态一致性检查

文档人工对照与声明扫描范围：§8.1 投影/公式/冻结字段；§8.2 批事件与累计统计；§8.3 唯一 schema/重放矩阵；S07；本记录。

- batch_digest 不再被定义为“仅元数据即可校验不同内容”；两 tag、domain、key_id 和上下文一致。
- row 与进度事件同步包含版本/key/content_fingerprint/batch_digest，PK 仍为 batch_id，保留 UNIQUE(request_id,first_sequence)，没有第二套逐块主键。
- 请求事件固定 key/version/dataset；terminal 保留相同关联和 fingerprinted_batch_count；密钥实体不存 secret，未创建实际 key。
- 静态区分 receiver_computed_at_ingest、receipt_only/metadata_binding_valid 和 content_reverified；不因重启缺正文而声称完成内容重验。
- 相同冻结批重试不使用重试时间；候选写入必须从受信层实际字节重算，不接受复制旧 tag；回执查询不追加事件/计数。
- 正文、补充索引的批 PK/序号/计数规则保留；补充文档继续引用正文，不新增另一套指纹算法。
- 仅检查文本声明、公式字段及围栏配对；没有运行 HMAC 测试向量或密码学实现，没有执行 S07/SQLite/故障恢复测试，不把本节当作测试通过报告。

### 前次 R4 内容指纹修改文件（历史记录）

1. docs/P1_TOOL_LIFECYCLE_DESIGN.md：§8.1–§8.3、schema、S07 和版本。
2. docs/P1_TOOL_LIFECYCLE_CONVERGENCE.md：修改前后差异、公式索引、幂等矩阵与静态检查。

本轮不修改补充索引，不新增 Python/SQL Migration，不运行模型或工具。尚待实现的 OS keystore backend、密钥备份恢复、HMAC/序列化与攻击性重放测试均未实现/验证。PR #3 保持 Draft，等待独立复审；不授权下发实现或合并。



## R4 数值类型与规范序列化收尾

本轮父基线：6ad319ad147fa94e37bea183745fa91271f14b93。只解决确定性，不改变 HMAC 两层结构、批主键、取消流程或执行能力。

### 数据契约核对与修改前后差异

已核对 P1-1 固定提交的 models.py、providers.py、store.py：Event.sequence=ge1 int，Artifact.size=ge0 int；时间 str/UTC now().isoformat()；Python sort_keys/minimal separators/ensure_ascii=false/allow_nan=false；tool arguments 完整对象与 stream 参数片段字符串是两种不同边界。

| 项目 | 修改前 | 修改后（正文 §8.1.1） |
|---|---|---|
| 字段类型 | “字段类型符合 schema”但未穷举数值域 | b：C 9 字段、M 16 字段及所有 R_i 嵌套字段；正整数/非负/索引各有范围，缺失/null 明确 |
| 数值 | JSON 库可能合并 1/1.0/1e0 或强转字符串 | token 级严格整数；SAFE_MAX=2^53−1、INDEX_MAX=2^31−1；bool/负零/超界/非有限数拒绝，不能强转 |
| Canonical | Python 参数近似描述 | c：UTF-8 无 BOM、scalar 键序、完整转义/空白/最短整数规则、缺失/null、Unicode/surrogate/重复键规则 |
| 时间 | 仅 UTC，精度未冻结 | d：新 M 固定 YYYY-MM-DDTHH:MM:SS.ffffff+00:00，六位微秒，拒绝省略/偏移/Z/闰秒；旧 Event 原字节不动 |
| KAT | 仅同长度异内容/重启等关系测试 | e：固定合成 key、V1–V3/固定变体、canonical 字节样例、完整 golden 输出文件要求和 K01–K11；没有计算 MAC 或宣称运行通过 |
| S07/入库边界 | 未明确跨库数值/格式差异 | 链接 K01–K11，SQL/Pydantic affinity/coercion 不能代替源 token 校验；不创建迁移 |

### 新增类型/Canonical/时间规范索引

- 正整数 first/last/chunk_count/chunk_sequence：1..9007199254740991；choice_index/tool.index：0..2147483647；content_bytes_delta/tool_delta_count：0..9007199254740991。仍受较小运行限额约束，不扩大容量。
- bool、float/指数 token、字符串数字、负零、NaN/Infinity、越界均拒绝；tool.function.arguments 内部出现数字仍是未经改写的字符串正文，不对其做 HMAC 外层整数转换。
- C/M 字段闭合清单与 R_i 可选/null 规则见正文表；terminal.chunk_count 的 0/null 恢复语义不受批正整数规则影响。
- 对象按解码后 Unicode scalar 排序，数组不排序；完整 JSON 字符串转义、最短十进制、UTF-8/长度 framing、重复键先验拒绝均由 profile 冻结，不由库默认行为决定。
- 新 M 时间固定六位微秒 +00:00；旧 now().isoformat() 在零微秒时省略小数依旧合法，不重算历史事件哈希。输入校验不把非规范时间悄悄归一化；可信接收层生成后冻结。

### Known-Answer Test 设计与未完成边界

固定公开 synthetic key 为 hex 000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f，非真实审计密钥，不调用随机生成器。正文提供固定 C/R_i/M 非 tag 字段的 V1 中文文本、V2 工具片段、V3 转义输入及固定变体。

未来 golden 文件必须预先冻结完整 J(C)/R_i/J(M) 与 F 拼接消息 hex、两个完整 MAC hex、每个非法输入的唯一预期码；Python 和至少一种非 Python 参考实现独立生成比对、复核后冻结，被测实现不能运行时生成自己的 expected。

本轮给出可人工读出的 canonical R_1 期望、中文/emoji 编码、各变体的预期同/异/拒绝关系；**没有计算完整 MAC/golden framing，也未实现 HMAC 或生成实际审计 key**。实际 golden 文件待实现阶段生成；当前不可宣称已有可执行 KAT 或跨语言验证通过。

### 静态一致性检查结果

已对照正文定义、公式输入、字段表、schema 建议和 S07：C/M 分别封闭为 9/16 字段，R_i 各层明确必需/可选/null；相同字段类型与范围一致；每个时间字段指向唯一格式；序列化 profile 不取代 Event 哈希；KAT key/输入/expected 设计要求与未运行标记齐全。批主键和 HMAC 域字符串未改变。

自动文本扫描仅核对声明/链接/围栏和指定文档路径；数值/时间/转义的设计审查不是 HMAC、JSON 库或数据库运行测试。未运行 K01–K11、S07、SQL/并发恢复或真实模型/工具调用，未渲染 Mermaid。完整黄金 MAC 尚未产出，仍待独立复审。

本次 11 项静态/样例检查结果一致：C 九字段、展开 M 十六字段、V1/V2/V3 的输入 UTF-8 长度分别为 4/10/18、K01–K11 清单齐全、整数边界声明、Canonical 规则声明、时间格式声明、golden 未计算标记、Markdown 围栏配对。样例检查只读取固定 JSON 展示块并核对字段/字节数，不是跨语言 Canonical 或 HMAC 向量运行。

### 本轮修改文件

1. docs/P1_TOOL_LIFECYCLE_DESIGN.md：版本、§8.1.1 完整确定性规范/KAT、§8.3 入库边界说明、S07。
2. docs/P1_TOOL_LIFECYCLE_CONVERGENCE.md：契约核对、差异、规范索引、KAT 设计边界与静态检查。

不修改 main、PR #1/#2、Python 功能代码或迁移；不启用模型/工具；PR #3 保持 Draft，未合并。旧轮次检查记录只作历史记录，不表示本轮已获独立验收。
