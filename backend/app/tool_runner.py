"""Restricted subprocess entry point for one whitelisted read-only tool.

The parent process validates the tool name and arguments first.  This runner is
started as ``python -I -B app/tool_runner.py`` with ``shell=False`` and a
minimal environment, speaks only JSON over stdin/stdout, re-validates the
workspace containment boundary with stdlib code, and never interprets a shell
string.  It has no network, write or arbitrary-execution capability.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MAX_REQUEST_BYTES = 64 * 1024
_ALLOWED_KEYS = {"tool_name", "arguments", "root"}

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tool_impl import ToolError, dispatch, resolve_workspace_path  # noqa: E402


def _fail(message: str) -> None:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    raise SystemExit(0)


def main() -> None:
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            _fail("invalid runner request")
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        _fail("invalid runner request")
        return
    if not isinstance(payload, dict) or set(payload) - _ALLOWED_KEYS:
        _fail("invalid runner request")
    tool_name = payload.get("tool_name")
    arguments = payload.get("arguments")
    root_value = payload.get("root")
    if not isinstance(tool_name, str) or not isinstance(arguments, dict):
        _fail("invalid runner request")
    if not isinstance(root_value, str) or not root_value:
        _fail("invalid runner request")
    requested_root = Path(root_value)
    # Absolute only: a relative root would depend on the child's cwd.
    if not requested_root.is_absolute():
        _fail("invalid runner request")
    try:
        # Refuses a symlink/junction/reparse-point root, non-directories, and
        # non-existent roots before any tool can open a child path.
        root = resolve_workspace_path(requested_root, ".")
    except ToolError:
        _fail("invalid runner request")
        return
    if not root.is_dir():
        _fail("invalid runner request")
    try:
        # Pass the lexical root as well: dispatch re-checks the root itself, so
        # a direct runner invocation cannot hide a junction behind a resolved
        # path.  dispatch() performs its own containment and link checks.
        output = dispatch(tool_name, arguments, requested_root)
        print(json.dumps({"ok": True, "output": output}, ensure_ascii=False))
    except ToolError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
