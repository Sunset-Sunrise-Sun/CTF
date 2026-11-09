# P0 统一整合未解决问题 / 非目标

- 日期：2026-11-09
- 分支：`feat/p0-unified-ai-tools`（未提交、未推送、未合并）
- 以下问题不影响本轮 P0 声明范围，但必须在进入真实题目/生产前处理或明确接受。

## 1. 必须由独立审查/后续阶段确认

1. **真实 DeepSeek 联网与合成连通性**：未执行；需要真实 API Key、合法网络环境和明确授权。当前所有模型调用为 MockTransport/浏览器路由替身。
2. **真实题目多轮工具申请与最终实战验收**：未执行；不得把本轮合成闭环当作比赛平台验证。
3. **单用户安全边界**：无认证/授权，`approving_user` 可伪造；服务只应绑定回环。多用户配置隔离（第二阶段 API 设置页）未实现，不能宣称多用户安全隔离。
4. **OS 级工具沙箱**：当前是应用层 workspace 路径检查 + 固定只读 runner；没有容器/低权限账户/网络命名空间。TOCTOU 与同机直接调用 runner 的风险仍在（见安全报告）。
5. **文件符号链接权限用例**：5 个 pytest skip 因 Windows 当前账户无创建 symlink 权限；本轮已新增并实际执行 Windows junction/reparse point 的 recursive/flat/workspace-root 用例（全部通过，不 skip），但文件 symlink 用例仍需在有权限环境补跑。

## 2. 功能缺口

6. 工具失败/超时只记录 `error` 文本，不保存 stderr/stdout Artifact；若需要“失败原始输出”证据，应新增失败 Artifact 策略。
7. 工具执行并发限制是进程内 `BoundedSemaphore(2)`；多进程部署不叠加。当前单进程边界。
8. 相同工具输出字节按内容寻址去重，不重复写 `artifact_added` 事件；元数据与 `tool_finished.artifact_ids` 仍完整。
9. `expire_stale`/执行过期比较以 ISO 字符串 + 逐行 parse 复核；外部写入非 `+00:00` 偏移的数据以复核为准。
10. 模型调用与工具状态跨两个 SQLite 文件，无法跨库原子提交；通过 `call_id` 关联、失败标记 incomplete 和启动恢复避免“冒充成功”，但存在短暂跨库可见性窗口。
11. `unknown` 审计调用永久保持 unknown，没有人工决议/补救接口；当前设计是 fail-closed、导出 incomplete。
12. `/api/model/calls` 返回本数据目录全部调用（前端按题目过滤）；若未来多用户/多项目部署需要分页与更强隔离。
13. `/ai/chat` 正文没有独立 ASGI body-size 上限，超大 JSON 会先被 FastAPI 缓冲再触发 32 KB 文本/180 KB Provider 预算检查；如需抗大包 DoS，应加 body 限制。
14. 旧业务全量 E2E（固定 8000/5173）未运行；本轮运行隔离 AI E2E（18002/15174、独立数据根）。
15. Playwright bundled Chromium 离线不可用；E2E 用系统 Edge，CI 默认 chromium 路径未验证。
16. 前端存在既有审计缺口 FE-01/FE-02（exportZip 多次 await 后切题、草稿导出快照），本轮只对 chat/refresh/model-calls/tool-panel 增加代次保护，未改这两处。
17. Flag 面板放在 AI 区域；DeepSeek 候选放在 Writeup 标签页。功能一致，位置差异已记录。
18. 历史文档（A00/MVP 等）仍描述 `execution_enabled=false`；本轮新增 `docs/P0_UNIFIED_*` 为当前事实来源，历史文档保留为历史记录。

## 3. 迁移/兼容性

19. 本分支从 PR #9 基线重新应用 Codex P0 + 工具迁移，迁移文件为 `003_tool_approvals.sql`；若要在已运行 DeepSeek 候选 `003_model_audit.sql`/`004_tool_approvals.sql` 的开发数据库上直接升级，需要单独迁移方案（本分支不读取旧 `model_calls` 表，也不承诺该库可直接复用）。
20. 旧 `backend/app/tools.py` 的 `DisabledBroker` 仍保留为历史接口；当前 `ToolService` 是实际执行路径，`/api/tools` 返回真实 catalog。
21. `docs/contracts.json` 覆盖 Pydantic 契约；manifest/ZIP 的 JSON 结构由 `export.py` 定义，未单独生成 JSON Schema（已在本报告与架构文档记录字段）。

## 4. 本轮明确非目标

- 不实现任意 Shell/Python/网络/写工具；不实现自动 Flag 提交或平台扫描。
- 不实现多用户认证、远程部署、外部审计签名。
- 不修改原 8000/8001/8002/5173/5174 服务、不修改 PR #9 远端、不提交/推送/合并。
- 不进行真实 DeepSeek 调用、不读取/复制真实 API Key、不使用真实比赛附件。
