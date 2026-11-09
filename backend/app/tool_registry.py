"""Fixed whitelist of seven read-only local tools plus strict argument validation.

There is no pluggable registry and no user-supplied tool name reaches execution:
``TOOL_SPECS`` is a module constant.  Every tool is read-only and requires an
explicit human approval before it may run.  No entry provides a shell, arbitrary
Python evaluation, network access, or a write primitive.
"""
from __future__ import annotations

from dataclasses import dataclass


class ToolValidationError(ValueError):
    """Argument or tool-name problem; maps to HTTP 422."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    risk_level: str
    parameters: dict
    read_only: bool = True
    requires_approval: bool = True


TOOL_SPECS: dict[str, ToolSpec] = {
    "file_inspect": ToolSpec(
        "file_inspect",
        "Identify a workspace file's format, size, SHA-256 and header bytes without executing it.",
        "low",
        {
            "path": {"type": "string", "required": True, "max_length": 1000},
        },
    ),
    "sha256": ToolSpec(
        "sha256",
        "Compute the SHA-256 and size of a workspace file.",
        "low",
        {"path": {"type": "string", "required": True, "max_length": 1000}},
    ),
    "stat": ToolSpec(
        "stat",
        "Show file kind, size, modification time and mode inside the challenge workspace.",
        "low",
        {"path": {"type": "string", "required": True, "max_length": 1000}},
    ),
    "strings": ToolSpec(
        "strings",
        "Extract bounded printable ASCII strings from a workspace file.",
        "low",
        {
            "path": {"type": "string", "required": True, "max_length": 1000},
            "min_length": {"type": "integer", "min": 4, "max": 64, "default": 4},
            "max_strings": {"type": "integer", "min": 1, "max": 200, "default": 50},
        },
    ),
    "list_files": ToolSpec(
        "list_files",
        "List files under a workspace directory (bounded, no symlink traversal).",
        "low",
        {
            "path": {"type": "string", "required": False, "max_length": 1000, "default": "."},
            "recursive": {"type": "boolean", "required": False, "default": False},
            "max_entries": {"type": "integer", "min": 1, "max": 500, "default": 200},
        },
    ),
    "image_info": ToolSpec(
        "image_info",
        "Read PNG/JPEG/GIF/WebP dimensions and format from a workspace image.",
        "low",
        {"path": {"type": "string", "required": True, "max_length": 1000}},
    ),
    "text_decode": ToolSpec(
        "text_decode",
        "Decode a workspace text file as base64, hex or URL encoding.",
        "low",
        {
            "path": {"type": "string", "required": True, "max_length": 1000},
            "encoding": {
                "type": "string",
                "required": False,
                "enum": ["base64", "hex", "url"],
                "default": "base64",
            },
        },
    ),
}


def validate_arguments(tool_name: str, arguments: object) -> dict:
    """Validate arguments against the fixed schema and return normalised values.

    Unknown tools, unknown arguments, wrong types, out-of-range integers and
    missing required values are all rejected.  Defaults are applied so the
    stored/approved arguments are exactly what execution will use.
    """
    if not isinstance(tool_name, str):
        raise ToolValidationError("tool name must be a string")
    spec = TOOL_SPECS.get(tool_name)
    if spec is None:
        raise ToolValidationError("unknown tool")
    if not isinstance(arguments, dict):
        raise ToolValidationError("arguments must be an object")
    unknown = set(arguments) - set(spec.parameters)
    if unknown:
        raise ToolValidationError("unknown argument: " + ", ".join(sorted(unknown)))
    result: dict = {}
    for name, rule in spec.parameters.items():
        value = arguments.get(name, rule.get("default"))
        if value is None:
            if rule.get("required"):
                raise ToolValidationError(f"missing required argument: {name}")
            continue
        kind = rule["type"]
        if kind == "string":
            if not isinstance(value, str) or not 1 <= len(value) <= rule.get(
                "max_length", 1000
            ):
                raise ToolValidationError(f"invalid string argument: {name}")
            if "\x00" in value:
                raise ToolValidationError(f"invalid string argument: {name}")
            if "enum" in rule and value not in rule["enum"]:
                raise ToolValidationError(f"invalid value for {name}")
        elif kind == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ToolValidationError(f"invalid integer argument: {name}")
            if value < rule.get("min", 0) or value > rule.get("max", 2**31):
                raise ToolValidationError(f"integer out of range: {name}")
        elif kind == "boolean":
            if not isinstance(value, bool):
                raise ToolValidationError(f"invalid boolean argument: {name}")
        else:  # pragma: no cover - registry is a constant, so this cannot happen
            raise ToolValidationError("unsupported schema type")
        result[name] = value
    return result


def catalog() -> list[dict]:
    """Return the public, fixed tool catalogue (no executable is exposed)."""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "risk_level": spec.risk_level,
            "read_only": spec.read_only,
            "requires_approval": spec.requires_approval,
            "parameters": spec.parameters,
        }
        for spec in TOOL_SPECS.values()
    ]
