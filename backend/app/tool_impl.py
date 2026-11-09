"""Pure-stdlib read-only analysis tools for the CTF workbench.

Every function receives already-validated arguments and an absolute challenge
workspace root.  These functions never write files, never execute challenge
binaries, never open network sockets, and never run arbitrary shell commands.
They are also the last line of defence for workspace containment: the parent
process validates paths when a proposal is created/approved, and the tool runner
process re-validates them here before touching the filesystem.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import stat as stat_module
import urllib.parse
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

MAX_TEXT_BYTES = 4 * 1024 * 1024
MAX_OUTPUT_CHARS = 64_000
MAX_STRING_LENGTH = 500
_FILE_ATTRIBUTE_REPARSE_POINT = getattr(
    stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0
)

# Windows device names are resolved by the OS even under an otherwise
# contained directory, so they must never reach an open() call.
_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class ToolError(ValueError):
    """A tool execution error that is safe to report back to the caller."""


class LinkStatus(Enum):
    """Explicit result of a link/reparse-point inspection.

    ``MISSING`` is deliberately distinct from ``NORMAL`` so callers can decide
    per scenario whether absence is acceptable.  An inspection *failure* is not
    represented by any enum value: `_link_status` raises ``ToolError`` instead,
    so no caller can accidentally treat an unreadable path as safe.
    """

    NORMAL = "normal"
    LINK = "link"
    MISSING = "missing"


def _link_status(path: Path) -> LinkStatus:
    """Classify a path without ever returning a safe result on inspection error.

    - ``FileNotFoundError`` -> ``MISSING`` (caller decides; missing is not a
      link and is not a permission failure).
    - ``PermissionError`` -> ``ToolError`` (fail closed).
    - any other ``OSError`` -> ``ToolError`` (fail closed).
    - symlink, Windows reparse point or junction -> ``LINK``.
    """
    try:
        info = path.lstat()
    except FileNotFoundError:
        return LinkStatus.MISSING
    except PermissionError:
        raise ToolError("path inspection denied") from None
    except OSError:
        raise ToolError("path inspection failed") from None
    if stat_module.S_ISLNK(info.st_mode):
        return LinkStatus.LINK
    if getattr(info, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT:
        return LinkStatus.LINK
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction):
        try:
            if is_junction():
                return LinkStatus.LINK
        except FileNotFoundError:
            return LinkStatus.MISSING
        except PermissionError:
            raise ToolError("path inspection denied") from None
        except OSError:
            raise ToolError("path inspection failed") from None
    return LinkStatus.NORMAL


def _is_link_like(path: Path) -> bool:
    """Return True only for a confirmed link/reparse point.

    Missing paths are False (not links); inspection errors raise ``ToolError``
    rather than returning False, which is the fail-closed replacement for the
    former ``except OSError: return False`` behaviour.
    """
    return _link_status(path) is LinkStatus.LINK


def _reject_symlink(path: Path, *, missing_ok: bool = True) -> None:
    status = _link_status(path)
    if status is LinkStatus.LINK:
        raise ToolError("symbolic links are not allowed in the tool workspace")
    if status is LinkStatus.MISSING and not missing_ok:
        raise ToolError("path does not exist")


def _checked_root(root: Path) -> Path:
    """Validate the challenge workspace root itself before resolving it.

    The root is checked with ``lstat`` first, because resolving a junction would
    hide the fact that the workspace itself points outside the data root.  A
    missing, unreadable (permission/other OSError) or link-like root is rejected.
    """
    requested = Path(root)
    if not requested.is_absolute():
        raise ToolError("workspace root must be absolute")
    status = _link_status(requested)
    if status is LinkStatus.LINK:
        raise ToolError("symbolic links are not allowed in the tool workspace")
    if status is LinkStatus.MISSING:
        raise ToolError("workspace root is not readable")
    try:
        resolved = requested.resolve(strict=True)
    except FileNotFoundError:
        raise ToolError("workspace root is not readable") from None
    except PermissionError:
        raise ToolError("workspace root access denied") from None
    except (OSError, RuntimeError):
        raise ToolError("workspace root is not readable") from None
    try:
        is_directory = resolved.is_dir()
    except OSError:
        raise ToolError("workspace root is not readable") from None
    if not is_directory:
        raise ToolError("workspace root is not a directory")
    return resolved


def _resolve(root: Path, relative: str) -> Path:
    """Resolve a workspace-relative path, refusing every escape and link."""
    if not isinstance(relative, str) or not relative:
        raise ToolError("file path is required")
    if "\x00" in relative:
        raise ToolError("path outside challenge workspace")
    part = Path(relative)
    if part.is_absolute() or part.drive or ".." in part.parts or ":" in relative:
        raise ToolError("path outside challenge workspace")
    for component in part.parts:
        if component in {"", ".", ".."}:
            continue
        if component != component.strip() or component.endswith("."):
            raise ToolError("path outside challenge workspace")
        if component.split(".")[0].strip().upper() in _RESERVED_NAMES:
            raise ToolError("path outside challenge workspace")
    checked_root = _checked_root(root)
    try:
        candidate = (checked_root / part).resolve()
    except FileNotFoundError:
        # The target itself may not exist yet; the component check below still
        # inspects every existing ancestor and the tool reports "not found".
        candidate = checked_root / part
    except PermissionError:
        raise ToolError("path access denied") from None
    except (OSError, RuntimeError):
        raise ToolError("path inspection failed") from None
    if not candidate.is_relative_to(checked_root):
        raise ToolError("path outside challenge workspace")
    # Refuse links anywhere below the workspace root, even ones that happen to
    # resolve back inside it: evidence paths must be real files.
    current = checked_root
    for component in part.parts:
        if component in {"", ".", ".."}:
            continue
        current = current / component
        _reject_symlink(current)
    return candidate


def resolve_workspace_path(root: Path, relative: str) -> Path:
    """Public boundary check shared by the service and the tool runner.

    Raises ``ToolError`` for any absolute/drive/colon/``..`` path, Windows
    device name, symbolic link/junction/reparse point, or path that resolves
    outside the challenge workspace root.  It does not require the target to
    exist; callers that need a file use ``_read``/``_sha256`` which report
    "file not found".
    """
    return _resolve(root, relative)


def _read(path: Path, limit: int = MAX_TEXT_BYTES) -> bytes:
    if not path.is_file():
        raise ToolError("file not found")
    try:
        with path.open("rb") as handle:
            return handle.read(limit)
    except OSError:
        raise ToolError("file is not readable") from None


def _sha256(path: Path) -> tuple[str, int]:
    if not path.is_file():
        raise ToolError("file not found")
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
    except OSError:
        raise ToolError("file is not readable") from None
    return digest.hexdigest(), size


def _format(head: bytes, path: Path) -> str:
    if head.startswith(b"\x7fELF"):
        return "ELF"
    if head.startswith(b"MZ"):
        return "PE/Windows executable"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG image"
    if head.startswith(b"\xff\xd8\xff"):
        return "JPEG image"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "GIF image"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "WebP image"
    if head.startswith(b"%PDF"):
        return "PDF document"
    if head.startswith(b"PK\x03\x04"):
        return "ZIP-compatible container"
    if b"\x00" not in head:
        return "text or text-like data"
    return f"unidentified binary ({path.suffix.lower() or 'no extension'})"


def file_inspect(arguments: dict, root: Path) -> dict:
    path = _resolve(root, arguments["path"])
    head = _read(path, 4096)
    digest, size = _sha256(path)
    return {
        "path": arguments["path"],
        "format": _format(head, path),
        "size": size,
        "sha256": digest,
        "head_hex": head[:64].hex(),
        "is_text": b"\x00" not in head,
    }


def sha256(arguments: dict, root: Path) -> dict:
    path = _resolve(root, arguments["path"])
    digest, size = _sha256(path)
    return {"path": arguments["path"], "sha256": digest, "size": size}


def stat(arguments: dict, root: Path) -> dict:
    path = _resolve(root, arguments["path"])
    try:
        info = path.stat()
    except OSError:
        raise ToolError("file not found") from None
    kind = "directory" if path.is_dir() else "file" if path.is_file() else "other"
    return {
        "path": arguments["path"],
        "kind": kind,
        "size": info.st_size,
        "mtime_utc": datetime.fromtimestamp(
            info.st_mtime, tz=timezone.utc
        ).isoformat(),
        "mode": oct(info.st_mode & 0o777),
    }


def strings(arguments: dict, root: Path) -> dict:
    path = _resolve(root, arguments["path"])
    data = _read(path)
    minimum = int(arguments.get("min_length", 4))
    maximum = int(arguments.get("max_strings", 50))
    found: list[str] = []
    seen: set[str] = set()
    for value in re.findall(rb"[ -~]{%d,}" % minimum, data):
        text = value.decode("ascii", errors="ignore")[:MAX_STRING_LENGTH]
        if text and text not in seen:
            seen.add(text)
            found.append(text)
        if len(found) >= maximum:
            break
    return {
        "path": arguments["path"],
        "min_length": minimum,
        "count": len(found),
        "strings": found,
    }


def _walk_error(error: OSError) -> None:
    """Fail closed when os.walk cannot inspect a directory.

    A vanished directory (FileNotFoundError) is a normal race and may be
    skipped; permission errors or any other inspection failure abort the tool.
    """
    if isinstance(error, FileNotFoundError):
        return
    if isinstance(error, PermissionError):
        raise ToolError("directory listing denied") from None
    raise ToolError("directory listing failed") from None


def _pruned_dirnames(directory: str, names: list[str]) -> list[str]:
    """Keep only confirmed real directories; links/pruned/missing are removed."""
    kept: list[str] = []
    for name in names:
        status = _link_status(Path(directory, name))
        if status is LinkStatus.LINK:
            continue
        if status is LinkStatus.MISSING:
            continue
        kept.append(name)
    return kept


def _entry_size(target: Path) -> int | None:
    """Return a file size or None for a vanished file; errors fail closed."""
    try:
        return target.stat().st_size
    except FileNotFoundError:
        return None
    except PermissionError:
        raise ToolError("file metadata denied") from None
    except OSError:
        raise ToolError("file metadata failed") from None


def list_files(arguments: dict, root: Path) -> dict:
    relative = arguments.get("path", ".")
    # Keep the lexical root for the display path and the resolved root for
    # containment; ``_checked_root`` refuses a junction/reparse-point workspace.
    workspace_root = _checked_root(root)
    base = _resolve(workspace_root, relative)
    base_status = _link_status(base)
    if base_status is LinkStatus.LINK:
        raise ToolError("symbolic links are not allowed in the tool workspace")
    if base_status is LinkStatus.MISSING:
        raise ToolError("directory not found")
    try:
        base_is_dir = base.is_dir()
    except OSError:
        raise ToolError("directory inspection failed") from None
    if not base_is_dir:
        raise ToolError("directory not found")
    recursive = bool(arguments.get("recursive", False))
    maximum = int(arguments.get("max_entries", 200))
    entries: list[dict] = []
    if recursive:
        # onerror is required: the default os.walk ignores permission errors,
        # which would silently return a partial (safe-looking) listing.
        iterator = os.walk(base, followlinks=False, onerror=_walk_error)
        for directory, dirnames, filenames in iterator:
            # os.walk(followlinks=False) does not necessarily recognise NTFS
            # junctions as links, so prune every reparse point explicitly before
            # it can be descended into.
            dirnames[:] = _pruned_dirnames(directory, dirnames)
            for name in filenames:
                target = Path(directory, name)
                status = _link_status(target)
                if status is not LinkStatus.NORMAL:
                    continue
                size = _entry_size(target)
                if size is None:
                    continue
                entries.append(
                    {"path": str(target.relative_to(workspace_root)), "size": size}
                )
                if len(entries) >= maximum:
                    break
            if len(entries) >= maximum:
                break
    else:
        try:
            children = sorted(base.iterdir(), key=lambda item: item.name)
        except FileNotFoundError:
            raise ToolError("directory not found") from None
        except PermissionError:
            raise ToolError("directory listing denied") from None
        except OSError:
            raise ToolError("directory listing failed") from None
        for target in children:
            status = _link_status(target)
            if status is not LinkStatus.NORMAL:
                continue
            try:
                target_is_dir = target.is_dir()
            except OSError:
                raise ToolError("directory inspection failed") from None
            if target_is_dir:
                entries.append(
                    {
                        "path": str(target.relative_to(workspace_root)),
                        "kind": "directory",
                        "size": 0,
                    }
                )
            else:
                size = _entry_size(target)
                if size is None:
                    continue
                entries.append(
                    {
                        "path": str(target.relative_to(workspace_root)),
                        "kind": "file",
                        "size": size,
                    }
                )
            if len(entries) >= maximum:
                break
    return {
        "path": relative,
        "recursive": recursive,
        "count": len(entries),
        "entries": entries,
    }


def image_info(arguments: dict, root: Path) -> dict:
    path = _resolve(root, arguments["path"])
    data = _read(path, 256 * 1024)
    try:
        size = path.stat().st_size
    except OSError:
        raise ToolError("file not found") from None
    result: dict = {"path": arguments["path"], "size": size}
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        result.update(
            {
                "format": "PNG",
                "width": int.from_bytes(data[16:20], "big"),
                "height": int.from_bytes(data[20:24], "big"),
            }
        )
    elif data.startswith((b"GIF87a", b"GIF89a")) and len(data) >= 10:
        result.update(
            {
                "format": "GIF",
                "width": int.from_bytes(data[6:8], "little"),
                "height": int.from_bytes(data[8:10], "little"),
            }
        )
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        result.update({"format": "WebP"})
    elif data.startswith(b"\xff\xd8\xff"):
        result.update({"format": "JPEG"})
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            if marker in {0xC0, 0xC1, 0xC2}:
                result.update(
                    {
                        "height": int.from_bytes(data[index + 5 : index + 7], "big"),
                        "width": int.from_bytes(data[index + 7 : index + 9], "big"),
                    }
                )
                break
            if index + 3 >= len(data):
                break
            length = int.from_bytes(data[index + 2 : index + 4], "big")
            index += 2 + length
    else:
        raise ToolError("unsupported or unrecognized image format")
    return result


def text_decode(arguments: dict, root: Path) -> dict:
    path = _resolve(root, arguments["path"])
    data = _read(path, 128 * 1024)
    encoding = arguments.get("encoding", "base64")
    try:
        raw = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise ToolError("input is not UTF-8 text") from None
    try:
        if encoding == "base64":
            decoded = base64.b64decode(raw, validate=True)
            text = decoded.decode("utf-8", errors="replace")
        elif encoding == "hex":
            text = bytes.fromhex(raw.strip()).decode("utf-8", errors="replace")
        elif encoding == "url":
            text = urllib.parse.unquote(raw)
        else:
            raise ToolError("unsupported encoding")
    except (ValueError, UnicodeDecodeError):
        raise ToolError("input could not be decoded with the selected encoding") from None
    return {
        "path": arguments["path"],
        "encoding": encoding,
        "output": text[:MAX_OUTPUT_CHARS],
        "truncated": len(text) > MAX_OUTPUT_CHARS,
        "output_size": len(text),
    }


TOOLS = {
    "file_inspect": file_inspect,
    "sha256": sha256,
    "stat": stat,
    "strings": strings,
    "list_files": list_files,
    "image_info": image_info,
    "text_decode": text_decode,
}


def dispatch(tool_name: str, arguments: dict, root: Path) -> dict:
    """Run one whitelisted tool and bound the serialised result size."""
    if not isinstance(tool_name, str) or tool_name not in TOOLS:
        raise ToolError("unknown tool")
    if not isinstance(arguments, dict):
        raise ToolError("arguments must be an object")
    output = TOOLS[tool_name](arguments, root)
    encoded = str(output)
    if len(encoded) > MAX_OUTPUT_CHARS:
        output = {
            "truncated": True,
            "output_chars": len(encoded),
            "output": encoded[:MAX_OUTPUT_CHARS],
        }
    return output
