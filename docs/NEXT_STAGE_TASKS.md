# 下一阶段任务单与文件所有权

日期：2026-11-09。Codex 负责审查、工程集成、测试与证据；DeepSeek 负责下列业务模块实现。本清单没有冒称已将任务发送到某个 DeepSeek 会话，也没有将其他模型称为 DeepSeek。

## 固定起点与保护

- 远端 PR #9：`30eeed6dcc180ae21b5648f25047c5889e3c434a`，Draft，目标 feat/p1-2-a00-integration。
- 本地工程分支：`codex/ai-workbench-convergence`，独立 managed worktree，未提交/推送；精确内容以交付 integration.patch、untracked 文件和 SHA256SUMS 为准，不能只用 HEAD 标识未提交快照。
- 已集成用户原始确认隔离补丁，SHA-256 `475702f29ee38a64b4a36451eb4cec48812f89acb92ab894f5fb5dcee248326e`。原补丁、原修改目录及验收服务不改动。
- 不把人工验收目录或 8000/8001/8002/5173/5174 当测试资源；服务进程只核查、不停止。
- 每阶段开始记录 base SHA、完整 diff 摘要及工作区状态；不改 main，不重写历史，提交/推送/合并均待确认。
- 真实模型只可在明确授权后使用固定合成提示。当前测试强制关闭真实联网，不读取真实 Key。

## 分阶段实施与检查点

| ID / 主责 | 文件边界 | 交付与退出条件 |
|---|---|---|
| C00 / Codex | 本文、FRONTEND_AUDIT、权限契约、隔离证据；既有补丁涉及的 8 文件；schema_cli 与契约一致性测试 | 核验补丁/基准、独立集成、重新执行基线及补丁测试；保持未提交 |
| AI-S01 / DeepSeek | ai_assistant.py、providers.py、model_cli.py、ai_smoke_cli.py、main.py 模型路由；对应 tests | 统一联网开关、确认、绝对数据目录及临时隔离；引入共享调用 ID/目的/合成标记/可用 usage；网络关闭所有入口零请求；不得破坏 recorded_complete 异常及取消语义 |
| AI-S02 / DeepSeek | writeup.py、export.py、对应 tests | 从真实调用事件统计成功/失败/取消及 Provider/model/用途；无调用不宣称调用；工具/人工/建议独立；ZIP 三者一致及全量哈希；禁止重写历史事件 |
| AI-S03 / DeepSeek | ai_assistant.py、models.py 中确有需要的 DTO、对应 tests | 落实 AI_PERMISSION_CONTRACT；完整请求预算含系统/问题/历史/分隔符；不可信内容放数据消息，不拼进系统授权；超限明确处理，不能先发送后检查 |
| AI-S04 / DeepSeek + Codex 复核 | schema_cli.py、openapi.json、contracts.json、API 文档及测试 | 同步所有 AI schema/错误码；测试生成结果与运行时一致；旧前端兼容边界说明；脱敏覆盖名称和文件名 |
| FE-S01 / DeepSeek | App.vue、useChallenge 等最小新增模块、单元/浏览器 tests | 修复 FE-01/02/03 竞态；所有写请求和下载固定 cid，所有 UI 回写校验请求代次；不重写全 App |
| FE-S02 / DeepSeek | AI/Writeup 必要子组件及 composables；App 仅接线 | 分批拆分，保留草稿迁移、版本冲突、双窗口与最终 ZIP；每模块独立回归 |
| T-D01 / DeepSeek 设计，Codex 审查 | 新工具设计/安全文档、待审 schema；不接执行器 | 对齐冻结状态机、原子事务、幂等、可信审批身份、注册版本/路径/哈希、崩溃 UNKNOWN；迁移编号先核实 003/004 规划，不能在 AI 审计阶段抢占 |
| T-I01 / DeepSeek | 经 T-D01 认可的 registry / lifecycle / audit / runner / migration / tests | 首批只读：file_inspect、strings、sha256、stat、list_files；固定执行器与独立 Schema；无 shell、无任意 Python、无网络；审批后才执行；默认关闭、DisabledBroker 保留 |
| T-I02 / DeepSeek | 工具 API、AI structured proposal 转换、审批 UI、tests | request_id/call_id/proposal_id 全链绑定；拒绝/取消/超时/并发重复与结果回传；模型消息不是输出 Artifact；无请求完整性证明不转提案 |
| EV-I01 / DeepSeek | 事件、证据、Writeup/导出对应模块及 tests | 真实 stdout/stderr 字节、SHA 与 tool_finished 绑定；失败保留输出；敏感导出不改原始证据；模型和人工不能冒充执行 |
| C01 / Codex | 独立回归/演示脚本、报告、截图、ZIP、校验和 | 固定候选快照运行全部检查、合成闭环、验证导出哈希；真实联网与离线测试分开；独立验收前不得标整体完成 |

AI-S01/02 可拆成独立候选补丁，但共享 providers/main.py 不允许并行覆盖；按明确父快照顺序交付。AI-S03 必须读取用户已批准的权限契约。FE-S02 等待 FE-S01 和 AI schema 稳定。工具实现等待 T-D01 安全审查；不能跳过可信审批身份或用多个 public Store 调用冒充事务。

## 必须先交设计、不能自行绕过的决策

1. `/api/model/test` 没有 Challenge，现有 Event 要求 Challenge 外键。选择系统级审计账本的 schema/保留策略及其与题目 model_call 的关联后再实现；不能虚构题目事件，也不能无审计发送。全局账本不得让同一调用变成两次计费统计。
2. 审计不可写时禁止新的外发；已收到响应但审计失败不能返回普通成功。崩溃后的 started/unknown 语义需设计，不能只靠 finally 保证断电审计。
3. 当前服务无认证，前端传 actor=user 不证明真人批准。启用任何生产工具前明确本地可信审批与 CSRF/Origin 边界；未完成继续 execution_enabled=false。
4. 冻结 P1-2 是 at-most-once dispatch，不承诺 exactly-once。状态投影与 Event 原子提交；真实进程启动与 SQLite 之间故障保留 UNKNOWN，不重放执行。
5. 本轮不把离线 stream-content-v1 KAT 当作生产 streaming 审计。若实现流式接收，另按冻结协议逐项验收；本阶段可继续 buffered complete，明确能力不足。

## 各补丁交接格式

每次交付：父快照/分支/工作区状态；完整 diff（含新增文件）；文件所有权；接口差异；当前测试命令/原始输出；新增/跳过/失败数及原因；synthetic 数据说明；SHA256SUMS；已知风险。当前用户要求提交与推送待确认，因此未提交时提供可复原补丁和哈希，不能编造新 commit SHA。

## 当前完成判据

工程隔离、补丁核验、前端审查和实际回归可以由 Codex 独立交付。AI-S01–EV-I01 尚须 DeepSeek 实现并交接，不能将任务单当成功能。真实 Key/连通性未验收、审计披露未闭环、生产工具禁用时整体结论必须 NO-GO；只允许继续隔离合成开发验证。
