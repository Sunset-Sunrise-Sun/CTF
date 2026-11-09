"""Fail-closed lstat coverage for the read-only tool boundary.

A path inspection must have exactly three safe outcomes: normal, link/reparse
point, or missing.  Permission/other OSError must raise ToolError and must never
be treated as "not a link"; these tests inject such failures at the workspace
root, a path component, recursive enumeration and the direct runner entry.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from app import tool_impl, tool_runner


def make_workspace(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "challenge"
    root.mkdir()
    (root / "inside.txt").write_bytes(b"INSIDE_SECRET_CONTENT")
    (root / "sub").mkdir()
    (root / "sub" / "nested.txt").write_bytes(b"NESTED_SECRET_CONTENT")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "outside-secret.txt").write_bytes(b"OUTSIDE_SECRET_CONTENT")
    return root, outside


def same_path(left: Path, right: Path) -> bool:
    return str(left).casefold() == str(right).casefold()


def patch_lstat(monkeypatch, failing: Path, error: BaseException) -> None:
    original = Path.lstat

    def fake_lstat(self: Path):
        if same_path(self, failing):
            raise error
        return original(self)

    monkeypatch.setattr(Path, "lstat", fake_lstat)


def patch_open_tracking(monkeypatch, attempts: list[Path]) -> None:
    original_open = Path.open

    def tracked_open(self: Path, *args, **kwargs):
        attempts.append(self)
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracked_open)


def test_link_status_distinguishes_missing_link_and_inspection_failure(
    tmp_path, monkeypatch
):
    root, _ = make_workspace(tmp_path)
    assert tool_impl._link_status(root / "inside.txt") is tool_impl.LinkStatus.NORMAL
    assert tool_impl._link_status(root / "missing.txt") is tool_impl.LinkStatus.MISSING
    assert tool_impl._is_link_like(root / "missing.txt") is False

    patch_lstat(monkeypatch, root / "inside.txt", PermissionError("synthetic"))
    with pytest.raises(tool_impl.ToolError, match="inspection denied"):
        tool_impl._link_status(root / "inside.txt")
    with pytest.raises(tool_impl.ToolError, match="inspection denied"):
        tool_impl._is_link_like(root / "inside.txt")

    patch_lstat(monkeypatch, root / "inside.txt", OSError("synthetic I/O failure"))
    with pytest.raises(tool_impl.ToolError, match="inspection failed"):
        tool_impl._link_status(root / "inside.txt")


@pytest.mark.parametrize("error", [PermissionError("denied"), OSError("broken")])
def test_workspace_root_inspection_failure_is_fail_closed(
    tmp_path, monkeypatch, error
):
    root, _ = make_workspace(tmp_path)
    reads: list[Path] = []
    patch_open_tracking(monkeypatch, reads)
    patch_lstat(monkeypatch, root, error)
    with pytest.raises(tool_impl.ToolError):
        tool_impl.resolve_workspace_path(root, "inside.txt")
    assert reads == []  # nothing was opened after the failed inspection


@pytest.mark.parametrize("error", [PermissionError("denied"), OSError("broken")])
def test_component_inspection_failure_is_fail_closed(tmp_path, monkeypatch, error):
    root, _ = make_workspace(tmp_path)
    reads: list[Path] = []
    patch_open_tracking(monkeypatch, reads)
    patch_lstat(monkeypatch, root / "inside.txt", error)
    with pytest.raises(tool_impl.ToolError):
        tool_impl.resolve_workspace_path(root, "inside.txt")
    assert reads == []


@pytest.mark.parametrize(
    "failing",
    ["sub", "sub/nested.txt", "inside.txt"],
)
def test_recursive_listing_inspection_failure_is_fail_closed(
    tmp_path, monkeypatch, failing
):
    root, _ = make_workspace(tmp_path)
    patch_lstat(monkeypatch, root / failing, PermissionError("synthetic denial"))
    with pytest.raises(tool_impl.ToolError):
        tool_impl.list_files({"path": ".", "recursive": True}, root)


@pytest.mark.parametrize("failing", ["sub", "inside.txt"])
def test_flat_listing_inspection_failure_is_fail_closed(
    tmp_path, monkeypatch, failing
):
    root, _ = make_workspace(tmp_path)
    patch_lstat(monkeypatch, root / failing, OSError("synthetic I/O failure"))
    with pytest.raises(tool_impl.ToolError):
        tool_impl.list_files({"path": ".", "recursive": False}, root)


def test_recursive_oswalk_scandir_permission_error_is_fail_closed(tmp_path, monkeypatch):
    root, _ = make_workspace(tmp_path)
    import os

    original_scandir = os.scandir

    def fake_scandir(path):
        if same_path(Path(path), root / "sub"):
            raise PermissionError("synthetic scandir denial")
        return original_scandir(path)

    monkeypatch.setattr(os, "scandir", fake_scandir)
    with pytest.raises(tool_impl.ToolError, match="directory listing denied"):
        tool_impl.list_files({"path": ".", "recursive": True}, root)


def test_all_seven_tools_fail_closed_on_lstat_permission_error(tmp_path, monkeypatch):
    root, _ = make_workspace(tmp_path)
    reads: list[Path] = []
    patch_open_tracking(monkeypatch, reads)
    patch_lstat(monkeypatch, root / "inside.txt", PermissionError("synthetic denial"))
    calls = [
        ("file_inspect", {"path": "inside.txt"}),
        ("sha256", {"path": "inside.txt"}),
        ("stat", {"path": "inside.txt"}),
        ("strings", {"path": "inside.txt"}),
        ("list_files", {"path": "."}),
        ("image_info", {"path": "inside.txt"}),
        ("text_decode", {"path": "inside.txt", "encoding": "base64"}),
    ]
    for tool_name, arguments in calls:
        with pytest.raises(tool_impl.ToolError):
            tool_impl.dispatch(tool_name, arguments, root)
    assert reads == []
    assert all("INSIDE_SECRET_CONTENT" not in str(call) for call in calls)


def test_missing_file_remains_a_scoped_not_found_error(tmp_path):
    root, _ = make_workspace(tmp_path)
    with pytest.raises(tool_impl.ToolError, match="file not found"):
        tool_impl.dispatch("file_inspect", {"path": "missing.txt"}, root)
    with pytest.raises(tool_impl.ToolError, match="directory not found"):
        tool_impl.dispatch(
            "list_files", {"path": "missing-dir", "recursive": True}, root
        )


class _FakeStdin:
    def __init__(self, payload: bytes):
        self.buffer = io.BytesIO(payload)


def _run_runner_in_process(monkeypatch, capsys, payload: dict) -> dict:
    monkeypatch.setattr(
        sys,
        "stdin",
        _FakeStdin(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
    )
    with pytest.raises(SystemExit):
        tool_runner.main()
    output = capsys.readouterr().out
    return json.loads(output)


def test_direct_runner_fails_closed_on_root_lstat_permission(
    tmp_path, monkeypatch, capsys
):
    root, _ = make_workspace(tmp_path)
    reads: list[Path] = []
    patch_open_tracking(monkeypatch, reads)
    patch_lstat(monkeypatch, root, PermissionError("synthetic denial"))
    payload = _run_runner_in_process(
        monkeypatch,
        capsys,
        {
            "tool_name": "file_inspect",
            "arguments": {"path": "inside.txt"},
            "root": str(root),
        },
    )
    assert payload["ok"] is False
    assert reads == []
    assert "INSIDE_SECRET_CONTENT" not in json.dumps(payload)
