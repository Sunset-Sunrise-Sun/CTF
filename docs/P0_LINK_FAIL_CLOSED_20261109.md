# P0 最后一轮安全整改：链接检查 fail-open 修复

- 日期：2026-11-09
- 工作区：`D:\CTF-worktrees\unified`
- 分支：`feat/p0-unified-ai-tools`
- 基准 HEAD：`30eeed6dcc180ae21b5648f25047c5889e3c434a`
- 范围：仅修复 `backend/app/tool_impl.py` 中 `_is_link_like()` 在 `lstat()` 异常时返回 `False` 的 fail-open 问题，并为失败路径补测试
- 状态：整改完成，**未 commit、未 push、未 merge**；等待独立复审
- 未使用真实 API Key、真实题目或 Flag；未操作现有验收服务

## 1. 修复设计

原实现：

```python
try:
    info = path.lstat()
except OSError:
    return False          # fail-open：无法确认是否为链接时被当作安全
```

新实现使用明确的安全结果枚举：

```python
class LinkStatus(Enum):
    NORMAL = "normal"
    LINK = "link"
    MISSING = "missing"

def _link_status(path) -> LinkStatus:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return LinkStatus.MISSING
    except PermissionError:
        raise ToolError("path inspection denied")
    except OSError:
        raise ToolError("path inspection failed")
    ...
```

关键规则：

1. **普通文件/目录** → `NORMAL`。
2. **symlink / NTFS junction / 任意 Windows reparse point** → `LINK`。
3. **不存在** → `MISSING`；由调用场景决定（例如目标文件缺失返回 `file not found`）。
4. **PermissionError 或其他 OSError** → 直接 `ToolError`，**没有安全返回值**。
5. `_is_link_like()` 仅作为兼容包装：只有确认 `LINK` 才返回 True；`MISSING` 返回 False；检查异常必须抛出 `ToolError`。

## 2. 全链路 fail-closed 覆盖

- `_checked_root()`：先 `_link_status` 检查 workspace root；`MISSING`、`LINK`、`PermissionError`、其他 `OSError`、`resolve(strict=True)` 异常全部 `ToolError`。
- `_resolve()`：root 通过 `_checked_root`；`resolve()` 的 `PermissionError/OSError/RuntimeError` 全部转换为 `ToolError`；每个路径组件用 `_link_status`，异常拒绝。
- `list_files()`：
  - base 的 `_link_status`/`is_dir()` 异常拒绝；
  - 递归遍历使用 `os.walk(..., onerror=_walk_error)`：默认 `os.walk` 会吞掉权限错误，现在 `PermissionError`/其他 `OSError` 直接 `ToolError`；
  - 递归目录名用 `_pruned_dirnames()` 逐个 `_link_status`；递归文件、非递归目录/文件均检查；
  - 文件 `stat()` 的 `PermissionError/OSError` 全部 `ToolError`，不再 `continue`。
- 七个工具：全部经 `_resolve`，因此 root/组件检查异常均拒绝；`_read`/`_sha256`/`stat`/`image_info` 等自身 I/O 异常也转为 `ToolError`。
- 直接 `tool_runner`：root 先经 `resolve_workspace_path`，再以词法 root 调用 `dispatch`；root lstat 异常时 runner 输出 `{"ok": false}`，不会读取内容。

## 3. 新增测试

`backend/tests/test_tool_link_fail_closed.py`（14 个用例）：

- `_link_status` 明确区分 NORMAL/MISSING/LINK/异常；`_is_link_like` 在 Permission/OSError 时抛 `ToolError`。
- workspace root lstat 抛 PermissionError/OSError → 拒绝，且 `Path.open` 从未被调用。
- 路径组件 lstat 抛 PermissionError/OSError → 拒绝，且无内容读取。
- 递归枚举目录 `sub`、递归文件 `sub/nested.txt`、根文件 `inside.txt` 的 lstat 失败 → 全部拒绝。
- 非递归目录/文件 lstat 失败 → 拒绝。
- 七个工具逐一在 lstat PermissionError 下失败，且未打开任何文件。
- 不存在文件仍返回 scoped `file not found`，不把缺失误判为权限失败。
- 直接 `tool_runner.main()` 入口在 root lstat PermissionError 下输出 `ok=false`，无内容读取。

Windows Junction 实机测试保留并通过：
- `test_windows_junction_escape_is_rejected`
- `test_windows_junction_listing_prunes_external_recursive_and_flat`
- `test_windows_workspace_root_junction_is_rejected`

## 4. 验证结果

| 检查 | 结果 | 日志 |
|---|---|---|
| 后端全量 pytest | **290 passed, 7 skipped, 0 failed** | `verification/final-fail-closed-20261109/backend-pytest.log` |
| Ruff | **All checks passed** | `verification/final-fail-closed-20261109/ruff.log` |
| Junction 专项 | **3 passed，无 junction skip** | `verification/final-fail-closed-20261109/junction-tests.log` |
| 新增 fail-closed 专项 | **14 passed** | `verification/final-fail-closed-20261109/link-fail-closed-tests.log` |

7 个 skip 仍全部为环境限制：5 个 Windows symlink 权限、1 个工具文件 symlink 权限、1 个真实 Provider opt-in。**没有 junction/reparse 用例被跳过，也没有 lstat 失败用例被跳过。**

## 5. 真实后端 vs Mock 边界

本轮新增/运行的全部测试使用真实 `tool_impl`/`tool_runner`/SQLite 路径，不涉及模型 Provider；模型相关全量测试仍使用既有 MockTransport，未进行真实 DeepSeek 联网。前端、HTTP acceptance、故障注入沿用上一轮已保存证据，本轮未修改相关代码。

## 6. 交付物与复现

- 本报告：`docs/P0_LINK_FAIL_CLOSED_20261109.md`
- 增量 diff：`verification/final-fail-closed-20261109/incremental.diff`（相对上一轮整改候选）
- 完整 diff：`verification/final-fail-closed-20261109/complete.diff`（相对基准 `30eeed6`）
- SHA-256 清单：`verification/final-fail-closed-20261109/SHA256SUMS`
- 原始日志：`verification/final-fail-closed-20261109/`

```powershell
cd D:\CTF-worktrees\unified\backend
$env:CTF_MODEL_NETWORK_ENABLED='false'
$env:CTF_RUN_LIVE_MODEL='0'
python -B -m pytest -q -rs -p no:cacheprovider --basetemp "$env:TEMP\p0-failclosed-basetemp"
python -m ruff check app tests
python -B -m pytest -q -rs tests/test_tools.py -k junction --basetemp "$env:TEMP\p0-junction"
python -B -m pytest -q -rs tests/test_tool_link_fail_closed.py --basetemp "$env:TEMP\p0-link-failclosed"
```

## 7. 停止条件

仅完成本轮 `_is_link_like` fail-open 修复与验证。**停止，等待独立复审。** 不提交、不推送、不合并；不声称独立验收通过。
