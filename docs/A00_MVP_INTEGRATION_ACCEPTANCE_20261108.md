# A00 / MVP 整合验收补充记录

- 日期：2026-11-08
- 仓库：`Sunset-Sunrise-Sun/CTF`
- 分支：`feat/p1-2-a00-integration`
- 本记录用于补充 A00 原始报告，不改写历史测试报告，也不替代后续人工演示验收。

## 1. 当前 PR 与提交关系

| 项目 | 当前状态 |
|---|---|
| PR #6（A00 整合） | Open / Draft，未合并 |
| PR #7（MVP 后端） | 已合并至 A00 分支 |
| PR #8（MVP 前端 C5） | 已合并至 A00 分支 |
| MVP 代码 HEAD（run #40 对应提交） | `8439fcc73bd2da0b5bd9a09d79fa1c1772b89609` |
| PR #6 base | `docs/p1-2-tool-lifecycle-design` |

PR #7 的合并提交为 `f2e8461380c0d7fbe175a8865ee403d8a29ab64e`；PR #8 的合并提交为 `8439fcc73bd2da0b5bd9a09d79fa1c1772b89609`。

PR #6 原描述中的 `96152b7a66e16d726d50bebb4d833167b140e19c` 是较早的 A00 证据提交，不再是当前分支 HEAD。原 A00 文件树、祖先与回归记录仍作为历史基线证据保留，不应将它们误读为已经在当前 MVP HEAD 上重新执行的测试。

## 2. 当前 HEAD 的 GitHub Actions

工作流： [P0 checks / run #40](https://github.com/Sunset-Sunrise-Sun/CTF/actions/runs/42462865171)

运行关联的 MVP 代码 HEAD 为 `8439fcc73bd2da0b5bd9a09d79fa1c1772b89609`，结论为 `success`。此后仅追加了文档状态更正提交；本轮未改动业务源码。

| Job | 实际结果 | 说明 |
|---|---:|---|
| backend | 200 passed, 2 skipped | Ruff 通过；pytest 全量通过 |
| frontend | 41 passed | npm test 通过；生产构建通过 |

后端 2 个跳过项不计作通过：一个是 Windows 符号链接权限受限用例，另一个是默认关闭的真实模型测试（需显式设置 `CTF_RUN_LIVE_MODEL=1`）。CI 日志另有一条 Starlette 关于 httpx/TestClient 的弃用警告；不影响本次成功结论，但应在依赖升级时处理。

当前 CI 工作流没有运行 Playwright E2E。PR #8 的 C5 文档记录了 11 个 Windows + Edge 本地真实浏览器用例通过；该结果属于独立本地验收证据，不应表述成 GitHub Actions 已覆盖的测试。

## 3. 代码与接口复核范围

本次静态复核对照了当前分支的 `frontend/src/App.vue`、`frontend/src/api.ts`、`backend/app/main.py`、`backend/app/tools.py`、`backend/app/providers.py` 及 OpenAPI 契约。

检查覆盖项目配置、比赛规则、题目、导入记录、导入文件、证据、人工操作记录、事件、完整性、Writeup 初稿/人工稿、最终导出和工具能力状态等前后端调用路径。抽查到的前端 API 路径均能在后端路由中找到对应实现；本次属于源码接口对照，不等同于逐接口手工运行验收。

安全边界复核：
- `/api/health` 报告 `execution_enabled=false`、`model_network_enabled=false`。
- `/api/tools` 返回空工具列表，执行关闭。
- `DisabledBroker` 在 P0 中保持禁用；没有据此声称工具执行生命周期已实现。
- 当前实现未提供身份认证。部署应限于可信本机环境，不应直接暴露到公网或不可信局域网。

## 4. 当前验收结论与未完成事项

**代码整合和自动化测试证据：通过本轮复核。** 当前 HEAD 的 CI 为成功，前后端主要调用路径静态对照未发现明显接口错配，PR #7/#8 的功能实现已经进入 A00 整合分支。

**最终交付验收：尚未完成。** 仍需在隔离环境进行一次端到端人工演示，使用合成数据验证：

1. 启动前后端并创建项目、配置规则；
2. 创建题目，导入合成 ZIP 并浏览文件；
3. 上传证据并填写人工操作记录；
4. 查看事件时间线、执行完整性检查；
5. 生成、编辑、保存人工稿；
6. 刷新页面，确认服务器人工稿恢复；
7. 导出 ZIP，检查 Manifest、文件内容及 SHA256SUMS。

演示不得依赖真实比赛 Flag，不启用模型联网或工具执行。完成演示前，不将项目描述为已完成最终验收。

## 5. 历史证据的解释规则

- `docs/a00/README.md`、`docs/a00/REGRESSION.md`、`docs/a00/COMPATIBILITY.md` 保留 A00 固定基线整合时的历史提交和实际输出。
- `docs/MVP_BACKEND_TEST_REPORT.md`、`docs/MVP_FRONTEND_C5.md` 等文件分别记录各自阶段的实现与测试，不应将不同阶段的数字相加并宣称为一次统一测试。
- 当前 HEAD 的统一 CI 结果以本记录第 2 节的 run #40 为准。
- 本补充记录只更新交付事实和验收边界，不修改应用源码、冻结 KAT、数据库迁移或历史测试输出。

**本记录不批准 PR #6 合并，也不启动 A01。PR #6 继续保持 Open / Draft，等待人工演示验收及维护者后续决定。**
