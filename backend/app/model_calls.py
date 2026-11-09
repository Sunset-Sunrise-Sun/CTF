"""Application model gateway and append-only, content-free call journal.

The separate journal has no Challenge foreign key: synthetic connectivity calls
are system operations, never invented challenge events. A durable start precedes
the outbound request; an unmatched start is reported as unknown after a crash.
"""

from __future__ import annotations

import asyncio
import os
import re
import sqlite3
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import Field

from .models import Model, now
from .providers import ModelRequest, ModelResponse, ProviderError


SECRET_PATTERNS = [
    re.compile(
        r"(?i)(api[_-]?key|access[_-]?token|password|passwd|secret)\s*[:=]\s*['\"]?[^\s'\"]{6,}"
    ),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
]


def redact_sensitive(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED_SECRET]", text)
    return text


def model_network_enabled(settings=None) -> bool:
    """Environment opt-in or the persisted explicit network switch.

    The environment variable remains the operator/CLI override.  The workbench
    setting is read from the per-installation settings object; an absent or
    unreadable setting fail-closes to disabled.
    """
    if os.environ.get("CTF_MODEL_NETWORK_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True
    if settings is None:
        return False
    try:
        return bool(settings.network_enabled)
    except Exception:
        return False


class ModelCallRecord(Model):
    call_id: str
    challenge_id: str | None
    provider_id: str
    model_id: str
    purpose: Literal["challenge_chat", "synthetic_connectivity"]
    synthetic: bool
    data_scope: str
    requested_at: str
    completed_at: str | None = None
    response_status: str = "unknown"
    error_category: str | None = None
    usage: dict[str, int] | None = None


class ModelCallRecords(Model):
    calls: list[ModelCallRecord] = Field(default_factory=list)


PROVIDER_ERROR_CODES = frozenset(
    {
        "rate_limited",
        "timeout",
        "transport_error",
        "authentication",
        "upstream_error",
        "invalid_response",
        "empty_response",
        "missing_credentials",
        "unsupported_capability",
        "adapter_not_implemented",
        "unexpected_tool_calls",
        "response_limit_exceeded",
        "invalid_provider_configuration",
        "audit_unavailable",
        "model_network_disabled",
        "tool_requests_disabled",
        "context_limit_exceeded",
        "ai_usage_not_permitted",
        "attachment_confirmation_required",
        "attachments_not_permitted",
        "context_integrity_error",
        "unsupported_evidence",
        "evidence_selection_changed",
        "duplicate_evidence_selection",
        "config_invalid",
        "env_key_custom_base_url_not_authorized",
    }
)


def safe_error_code(error: ProviderError) -> str:
    return error.code if error.code in PROVIDER_ERROR_CODES else "provider_error"


class ModelCallJournal:
    """Schema v1 of a dedicated database, not migration 003/004 of Store."""

    def __init__(self, path: Path):
        if path.anchor and not path.is_absolute():
            raise ProviderError("audit_unavailable")
        # Retain the lexical path. Normalizing '..' first could hide a link.
        self._requested_path = path if path.is_absolute() else Path.cwd() / path
        self.path = self._checked_path()

    @staticmethod
    def _reject_link(path: Path) -> None:
        try:
            info = path.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ProviderError("audit_unavailable")

    def _checked_path(self) -> Path:
        raw = self._requested_path
        try:
            for component in (*reversed(raw.parents), raw):
                self._reject_link(component)
            resolved = raw.resolve()
            if resolved != Path(os.path.normpath(raw)):
                raise ProviderError("audit_unavailable")
            for suffix in ("-journal", "-wal", "-shm"):
                self._reject_link(resolved.with_name(resolved.name + suffix))
            return resolved
        except (OSError, RuntimeError):
            raise ProviderError("audit_unavailable") from None

    def _initialize(self):
        path = self._checked_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise ProviderError("audit_unavailable") from None
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            tables = {
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            if (version, tables) not in (
                (0, set()),
                (1, {"call_starts", "call_finishes"}),
            ):
                raise ProviderError("audit_unavailable")
            if version == 1:
                return
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS call_starts (
                    call_id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS call_finishes (
                    call_id TEXT PRIMARY KEY REFERENCES call_starts(call_id),
                    body TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS starts_no_update BEFORE UPDATE ON call_starts
                    BEGIN SELECT RAISE(ABORT, 'append only'); END;
                CREATE TRIGGER IF NOT EXISTS starts_no_delete BEFORE DELETE ON call_starts
                    BEGIN SELECT RAISE(ABORT, 'append only'); END;
                CREATE TRIGGER IF NOT EXISTS finishes_no_update BEFORE UPDATE ON call_finishes
                    BEGIN SELECT RAISE(ABORT, 'append only'); END;
                CREATE TRIGGER IF NOT EXISTS finishes_no_delete BEFORE DELETE ON call_finishes
                    BEGIN SELECT RAISE(ABORT, 'append only'); END;
                PRAGMA user_version=1;
                COMMIT;
            """)

    @contextmanager
    def connect(self):
        try:
            db = sqlite3.connect(self._checked_path(), timeout=15)
            try:
                db.execute("PRAGMA foreign_keys=ON")
                db.execute("PRAGMA recursive_triggers=ON")
                db.execute("PRAGMA synchronous=FULL")
                with db:
                    yield db
            finally:
                db.close()
        except (sqlite3.Error, OSError) as error:
            raise ProviderError("audit_unavailable") from error

    def start(self, record: ModelCallRecord) -> None:
        self._initialize()
        with self.connect() as db:
            db.execute(
                "INSERT INTO call_starts VALUES (?, ?)",
                (record.call_id, record.model_dump_json()),
            )

    def finish(self, record: ModelCallRecord) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO call_finishes VALUES (?, ?)",
                (record.call_id, record.model_dump_json()),
            )

    def records(self, challenge_id: str | None = None) -> list[ModelCallRecord]:
        if not self._checked_path().exists():
            return []
        with self.connect() as db:
            rows = db.execute(
                "SELECT COALESCE(f.body,s.body) FROM call_starts s "
                "LEFT JOIN call_finishes f USING(call_id) "
                "WHERE ? IS NULL OR json_extract(s.body, '$.challenge_id') = ? "
                "ORDER BY s.rowid",
                (challenge_id, challenge_id),
            ).fetchall()
        try:
            records = [ModelCallRecord.model_validate_json(row[0]) for row in rows]
        except ValueError:
            raise ProviderError("audit_unavailable") from None
        return records


async def audited_complete(
    provider,
    request: ModelRequest,
    journal: ModelCallJournal,
    *,
    challenge_id: str | None = None,
    store=None,
    purpose="synthetic_connectivity",
    synthetic=True,
    data_scope="synthetic_only",
    settings=None,
) -> ModelResponse:
    if not model_network_enabled(settings):
        raise ProviderError("model_network_disabled")
    if request.tools:
        raise ProviderError("tool_requests_disabled")
    try:
        endpoint = urlsplit(provider.config.base_url)
        secure = endpoint.scheme == "https" or (
            endpoint.scheme == "http"
            and endpoint.hostname in {"localhost", "127.0.0.1", "::1"}
        )
        if (
            not secure
            or not endpoint.hostname
            or endpoint.username is not None
            or endpoint.query
            or endpoint.fragment
        ):
            raise ValueError
    except ValueError:
        raise ProviderError("invalid_provider_configuration") from None

    record = ModelCallRecord(
        call_id=str(uuid4()),
        challenge_id=challenge_id,
        provider_id=redact_sensitive(provider.config.provider_id),
        model_id=redact_sensitive(provider.config.model_id),
        purpose=purpose,
        synthetic=synthetic,
        data_scope=data_scope,
        requested_at=now(),
    )
    # Fail closed before sending if the start cannot be persisted.
    journal.start(record)
    response = None
    try:
        response = await provider.complete(request)
        record.usage = response.usage
        if not response.text.strip() or response.tool_calls:
            raise ProviderError(
                "empty_response"
                if not response.text.strip()
                else "unexpected_tool_calls"
            )
    except BaseException as error:
        record.response_status = (
            "cancelled"
            if isinstance(error, asyncio.CancelledError)
            else safe_error_code(error)
            if isinstance(error, ProviderError)
            else "internal_error"
        )
        record.error_category = record.response_status
        record.completed_at = now()
        try:
            _finish(journal, record, store)
        except Exception:
            # Keep the original error and durable unmatched start; no false success.
            error.add_note(
                "Model audit finalization failed; inspect the pending call journal"
            )
        raise
    record.response_status = "success"
    record.completed_at = now()
    _finish(journal, record, store)
    response.audit_call_id = record.call_id
    return response


def _finish(journal, record, store):
    journal.finish(record)
    if store is not None and record.challenge_id is not None:
        try:
            store.append(
                record.challenge_id, "system", "model_call", record.model_dump()
            )
        except Exception:
            # Provider success remains in the journal, but delivery is not success.
            raise ProviderError("audit_unavailable") from None


def disclosure_calls(events, records=None) -> list[dict]:
    """Merge journal facts with legacy events, counting a call ID only once."""
    result = {r.call_id: r.model_dump() for r in (records or [])}
    recorded_answers = set()
    for event in events:
        call_id = event.payload.get("call_id")
        if (
            event.event_type == "agent_message"
            and event.actor == "agent"
            and isinstance(call_id, str)
        ):
            recorded_answers.add(call_id)
        if event.event_type != "model_call":
            continue
        key = call_id or "legacy:" + event.event_id
        if key not in result:
            result[key] = {
                k: event.payload[k]
                for k in (
                    "provider_id",
                    "model_id",
                    "requested_at",
                    "response_status",
                    "purpose",
                    "data_scope",
                    "synthetic",
                    "error_category",
                    "completed_at",
                    "usage",
                )
                if k in event.payload
            }
            result[key]["call_id"] = key
        result[key]["event_id"] = event.event_id
    for call_id, call in result.items():
        if (
            call.get("purpose") == "challenge_chat"
            and call.get("response_status") == "success"
        ):
            call["delivery_status"] = (
                "recorded" if call_id in recorded_answers else "not_recorded"
            )
    return sorted(
        result.values(),
        key=lambda call: (str(call.get("requested_at", "")), call["call_id"]),
    )


def disclosure_lines(calls) -> list[str]:
    if not calls:
        return ["- 本题记录中没有模型调用；这不证明工作台之外未使用 AI。"]
    success = sum(c.get("response_status") == "success" for c in calls)
    unknown = sum(c.get("response_status") == "unknown" for c in calls)
    cancelled = sum(c.get("response_status") == "cancelled" for c in calls)
    failed = len(calls) - success - unknown - cancelled
    lines = [
        f"- 本题模型调用共 {len(calls)} 次：成功 {success}，失败 {failed}，取消 {cancelled}，未确定 {unknown}。",
        "- 以下仅为模型通信记录，不证明建议已执行或结论已验证。",
    ]
    for c in calls:

        def label(value):
            return (
                str(value)
                .replace("\n", " ")
                .replace("\r", " ")
                .replace("|", "\\|")[:200]
            )

        lines.append(
            "- 调用 "
            + label(c.get("call_id", "legacy"))
            + "："
            + "；".join(
                label(c.get(k, "未记录"))
                for k in (
                    "provider_id",
                    "model_id",
                    "requested_at",
                    "purpose",
                    "data_scope",
                    "response_status",
                )
            )
            + ("；合成测试" if c.get("synthetic") else "；题目分析")
            + (
                "；事件 " + label(c["event_id"])
                if c.get("event_id")
                else "；独立审计账本记录"
            )
            + (
                "；模型已响应，回答未入事件"
                if c.get("delivery_status") == "not_recorded"
                else ""
            )
        )
    return lines
