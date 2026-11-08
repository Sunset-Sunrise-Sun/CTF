# P0 测试报告 — 2026-11-07

环境：Windows PowerShell；Python 3.14；FastAPI 0.142.2；Vue 3.5.45；Vite 7.3.7。

| 检查 | 结果 |
|---|---|
| python -m pytest -q | 23 passed, 2 skipped |
| python -m ruff check app tests | passed |
| npm run build | vue-tsc 与 Vite 生产构建通过 |
| npm audit | 0 vulnerabilities（依赖升级后） |

已验证五类题目、独立状态、回溯笔记和服务端时间、禁止客户端伪造 actor/time、404/422、迁移幂等、SQL 触发器、20 次并发追加及连续序列、修改/删除/重排序/插入式哈希破坏/尾部删除检测、路径穿越、模型工具调用转换与禁用执行器、三类兼容 Adapter、Anthropic 明确未实现、能力降级/切换、429/401/500、超时、SSE 文本聚合。

跳过：Windows 未授予符号链接创建权限；真实 Provider 测试未提供显式联网配置与合法凭证。
W07 的事件链基础覆盖已完成，W08 模型/工具边界有基础测试；W01–W10 完整 Writeup 验收未完成，不将其报告为通过。
CI 已配置 Ubuntu Python 3.11 和 Node 22；远程 CI 结果以 PR 页面实际状态为准。
