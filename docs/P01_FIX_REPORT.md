# P0.1 修复证据与变更清单

目标：feat/framework-scaffold，延续 PR #1；未修改 main，未合并 PR。

## 修复

- recorded_complete 默认状态为 internal_error，仅在 complete 正常返回后赋 success。
- 单独捕获 asyncio.CancelledError，记录 cancelled 后 bare raise；ProviderError 记录原 code 后 bare raise；其他 Exception 记录 internal_error 后 bare raise。
- 唯一 finally 审计写入点，保持四个元数据字段；不存储异常正文、完整请求、响应或 API Key。
- ToolProposal 新增可选 call_id（兼容旧数据和非模型提案）；模型转换始终保留原 call_id，proposal_id 仍独立生成。

## 本地验证（2026-11-07）

- `python -m pytest -q`：28 passed, 2 skipped。
- `python -m ruff check app tests`：All checks passed。
- 5 个新增测试用例：正常返回、ProviderError、RuntimeError、真正 task.cancel()、多个 ToolCall 的关联及 JSON 序列化往返。
- 四种审计路径均验证只有一条 model_call、精确状态、元数据字段白名单及哈希链有效。失败和取消路径不能记录为 success；异常路径验证原始实例向上传递。
- 原有测试保持通过。两项跳过仍为 Windows 符号链接权限和真实 Provider 凭证测试；本轮无真实模型联网测试。
- 未新增工具执行、模型网络 API、附件上传或 Writeup 生成器。

## 变更文件

1. backend/app/providers.py：审计状态处理、ToolCall ID 转换。
2. backend/app/models.py：ToolProposal.call_id。
3. backend/tests/test_model_audit.py：审计与来源关联回归测试。
4. docs/contracts.json：同步 ToolProposal JSON Schema。
5. docs/MODEL_PROVIDERS.md：补充审计与 call_id 契约。
6. docs/P01_FIX_REPORT.md：本修复报告。

远程 CI 结果以 PR #1 对应修复提交的检查状态为准。
