# P1-2A 实施启动审查包

日期：2026-11-07。设计/分支基线：`00e9436a73d33e01b1a288334b7c08a48661e42e`。
本轮只新增本目录六份文档；没有创建生产模块、SQL migration、真实模型/工具入口或实际审计密钥。所列接口、文件和任务均为待审实施方案，不是已实现能力。

| 交付 | 文档 |
|---|---|
| 仓库现状、接口核对与冲突 | [REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md) |
| 文件级方案、模块依赖图、接口边界 | [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) |
| 迁移顺序、约束、原子事务、恢复 | [MIGRATION_PLAN.md](MIGRATION_PLAN.md) |
| P1-2A 分工、依赖、验收及后续范围 | [TASK_BREAKDOWN.md](TASK_BREAKDOWN.md) |
| 已执行测试、环境、命令及局限 | [TEST_BASELINE.md](TEST_BASELINE.md) |

## 当前必须先审查的事项

1. PR #3 当前仅含设计与离线 KAT，**没有 backend/frontend/001/002**。P0.1 与 P1-1 仍在独立未合并分支；实施分支没有自动整合它们。
2. 现有 public Store.append/add_artifact 各自拥有事务，不能被串联成工具完成事务。后续需要审核内部同连接事务助手的修改边界，保持 P1-1 public 接口与去重/来源语义。
3. 设计建议的 003/004 存在模型来源外键的建表依赖。建议把 model_requests 等最小前置身份表放入003、其余模型流表放入004，服务只在两者完整升级后启动；待审核，不擅自调整协议或应用迁移。
4. 旧 Provider.stream 丢失协议结束证明，不能直接包一层审计就保证完整性。先设计受信观察接口和 FakeStreamSource；真实网络仍关闭。
5. execution_enabled=false、DisabledBroker 不变、Provider 网络默认关闭；FakeRunner/SyntheticKeyring 仅测试注入，不注册为应用默认能力。

本包提交到 `feat/p1-2-implementation`，Draft PR 目标为 `docs/p1-2-tool-lifecycle-design`。不修改 main、PR #1/#2/#3 的分支或既有文件，不合并 PR。等待 ChatGPT 独立审查任务拆分后，才按任务逐个交 DeepSeek 开发；本轮不启动开发任务。
