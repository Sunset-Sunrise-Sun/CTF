# P0 API 与数据契约

完整可调用 API 见 `openapi.json`（由 FastAPI 导出）；扩展域模型见 `contracts.json` 和 backend/app/models.py。

| 方法 | 路径 | 结果 |
|---|---|---|
| GET | /api/health | 本地服务和禁用能力状态 |
| GET / POST | /api/challenges | Challenge[] / Challenge (201) |
| GET | /api/challenges/{cid}/events | 按 sequence 排序 Event[] |
| POST | /api/challenges/{cid}/notes | NoteCreate -> Event (201) |
| GET | /api/challenges/{cid}/integrity | valid, earliest_affected_sequence |
| GET | /api/tools | 空工具注册表、禁用执行、容器上限 |

无更新/删除事件端点。不存在题目返回 404，非法类别或额外输入字段返回 422。
NoteCreate 只接受 text、retrospective、correction_of（同题已有事件 ID）。更正仍为新事件。
工具生命周期保留 tool_proposed、tool_approved/tool_rejected、tool_started、tool_finished 四阶段；也保留架构早期 command_started/finished 类型，但不将其自动映射或伪造成真实执行。
Finding/Hypothesis/Verification/Writeup 均为后续模块的强类型契约。实际执行结果必须关联开始/结束事件与 stdout/stderr 证据及哈希。

## 规范化与完整性
每个题目从 sequence=1 开始，创世 previous_event_hash 为 64 个 0。
event_hash = SHA256(UTF-8(json.dumps(event 去除 event_hash, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)))。
时间由服务生成 UTC ISO8601，canonical JSON 对字符串不额外进行 Unicode normalization。payload 禁止 NaN/Infinity。哈希覆盖事件所有其他字段，包括前序哈希和证据引用。
追加操作使用 BEGIN IMMEDIATE + 唯一题目序列，数据库触发器禁止更新/删除；事件头记录可检测尾部删除。校验按序列重算，返回最早受影响序列。
这只能检测未重算哈希的篡改。拥有数据库/文件系统控制权的用户可以改写整条链和事件头；不存在外部签名或检查点，不构成对机器所有者的密码学证明。

## Writeup 不变量
模型消息/假设与工具结果分离；solve_status 和 writeup_status 不互相推导。
未来生成器只能消费有序事件、关联证据、元数据和标记的回溯笔记；每一事实步骤引用事件/证据 ID，缺失步骤显示 **[证据缺失：该步骤未被工作台记录]**。
P0 无生成器/导出接口，不能由最后 Flag 或会话文本推导已执行步骤。
