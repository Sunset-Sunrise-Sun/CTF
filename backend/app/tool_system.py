"""Human-approved, read-only local tool proposals, approvals and execution.

Safety model
------------
* The model (or a user) can only create a ``pending`` proposal.  A proposal
  executes solely after a *separate* human approve action, and only when the
  challenge's AI usage level is A2 at the time of the decision.
* Approved arguments are frozen: the stored ``arguments_sha256`` and
  ``approved_arguments_sha256`` must still match the stored argument JSON before
  execution; otherwise the proposal is atomically marked ``expired``.
* Everything happens in a fixed, isolated subprocess: ``[python, -I, -B,
  tool_runner.py]``, ``shell=False``, minimal environment, 15 s timeout and a
  bounded output.  There is no shell, network, write or arbitrary-Python tool.
* Every state transition commits the ``tool_proposals`` row and its
  append-only challenge event in one ``BEGIN IMMEDIATE`` transaction.  Tool
  output bytes are ingested into the content-addressed ArtifactStore before the
  final transaction, which records ``artifact_added`` + ``tool_finished`` +
  the row update together.

Traceability chain:
    model_call_id -> proposal_id -> approval_id -> execution_id
      -> decision_event_id / started_event_id / finished_event_id
      -> artifact_ids
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import tool_impl
from .ai_policy import policy_for
from .artifacts import ArtifactStore
from .models import Challenge, ToolProposalRecord, now, uid
from .store import Store
from .tool_registry import (
    TOOL_SPECS,
    ToolValidationError,
    catalog,
    validate_arguments,
)
from .workspace import Workspace

PROPOSAL_TTL = timedelta(minutes=30)
EXECUTION_TIMEOUT_SECONDS = 15
MAX_OUTPUT_BYTES = 256 * 1024
OUTPUT_SUMMARY_CHARS = 1000
MAX_REASON_CHARS = 1000
MAX_USER_CHARS = 200
MAX_NOTE_CHARS = 2000
EXECUTION_SLOTS = threading.BoundedSemaphore(2)
INTERRUPTED_ERROR = "interrupted_during_execution"

TOOL_COLUMNS = (
    "proposal_id, challenge_id, model_call_id, tool_name, arguments_json, "
    "arguments_sha256, reason, risk_level, status, proposed_by, proposed_at, "
    "expires_at, approval_id, approved_by, approved_at, approved_arguments_sha256, "
    "decision_note, decision_event_id, execution_id, started_at, finished_at, "
    "started_event_id, finished_event_id, output_artifact_id, output_sha256, "
    "output_size, output_summary, artifact_ids, error"
)

_PROPOSAL_INSERT_COLUMNS = (
    "proposal_id, challenge_id, model_call_id, tool_name, arguments_json, "
    "arguments_sha256, reason, risk_level, status, proposed_by, proposed_at, expires_at"
)


class ToolNotFound(KeyError):
    """Unknown proposal or a proposal that belongs to another challenge (404)."""


class ToolConflict(Exception):
    """State-machine conflict, duplicate decision or stale approval (409)."""

    def __init__(self, message: str, *, status: str | None = None, code: str = "tool_state_conflict"):
        super().__init__(message)
        self.status = status
        self.code = code


class ToolPermissionError(PermissionError):
    """The challenge AI usage level forbids this tool action (403)."""

    def __init__(self, code: str = "ai_usage_not_permitted"):
        super().__init__("AI usage level does not permit this tool action")
        self.code = code


def _canonical(arguments: dict) -> str:
    return json.dumps(
        arguments,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _arguments_digest(arguments: dict) -> str:
    return hashlib.sha256(_canonical(arguments).encode("utf-8")).hexdigest()


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _is_expired(value: str) -> bool:
    parsed = _parse_time(value)
    return parsed is None or parsed <= datetime.now(timezone.utc)


def _clean_reason(reason: object) -> str:
    if not isinstance(reason, str):
        raise ToolValidationError("reason must be a string")
    cleaned = reason.strip()
    if not 1 <= len(cleaned) <= MAX_REASON_CHARS:
        raise ToolValidationError("reason must be 1..1000 characters")
    return cleaned


def _clean_user(user: object) -> str:
    if not isinstance(user, str):
        raise ToolValidationError("user must be a string")
    cleaned = user.strip()
    if not 1 <= len(cleaned) <= MAX_USER_CHARS:
        raise ToolValidationError("user must be 1..200 characters")
    return cleaned


def _clean_note(note: object) -> str | None:
    if note is None:
        return None
    if not isinstance(note, str):
        raise ToolValidationError("note must be a string")
    cleaned = note.strip()
    if not cleaned:
        return None
    if len(cleaned) > MAX_NOTE_CHARS:
        raise ToolValidationError("note must be at most 2000 characters")
    return cleaned


def _record(row) -> ToolProposalRecord:
    raw_artifacts = json.loads(row[27]) if row[27] else []
    if not isinstance(raw_artifacts, list):
        raw_artifacts = []
    return ToolProposalRecord(
        proposal_id=row[0],
        challenge_id=row[1],
        model_call_id=row[2],
        tool_name=row[3],
        arguments=json.loads(row[4]),
        reason=row[6],
        risk_level=row[7],
        status=row[8],
        proposed_by=row[9],
        proposed_at=row[10],
        expires_at=row[11],
        approval_id=row[12],
        approved_by=row[13],
        approved_at=row[14],
        decision_note=row[16],
        decision_event_id=row[17],
        execution_id=row[18],
        started_at=row[19],
        finished_at=row[20],
        started_event_id=row[21],
        finished_event_id=row[22],
        artifact_ids=raw_artifacts,
        output_artifact_id=row[23],
        output_sha256=row[24],
        output_size=row[25],
        output_summary=row[26],
        error=row[28],
    )


class ToolService:
    def __init__(
        self,
        store: Store,
        workspace: Workspace,
        artifacts: ArtifactStore,
        model_calls=None,
        ttl: timedelta = PROPOSAL_TTL,
    ):
        self.store = store
        self.workspace = workspace
        self.artifacts = artifacts
        self.model_calls = model_calls
        self.ttl = ttl

    # ------------------------------------------------------------------
    # policy gates
    # ------------------------------------------------------------------
    def _challenge(self, cid: str) -> Challenge:
        return self.store.get(cid)

    def _require_proposal_allowed(self, cid: str) -> Challenge:
        challenge = self._challenge(cid)
        if not policy_for(challenge.ai_usage_level).tool_proposals:
            raise ToolPermissionError()
        return challenge

    def _require_execution_allowed(self, cid: str) -> Challenge:
        challenge = self._challenge(cid)
        if not policy_for(challenge.ai_usage_level).tool_execution:
            raise ToolPermissionError()
        return challenge

    def _require_cleanup_allowed(self, cid: str) -> Challenge:
        challenge = self._challenge(cid)
        if str(challenge.ai_usage_level) in {"unknown", "A0"}:
            raise ToolPermissionError()
        return challenge

    def _require_model_call(self, cid: str, model_call_id: object) -> str:
        if not isinstance(model_call_id, str) or not model_call_id:
            raise ToolValidationError("AI tool proposals require model_call_id")
        if self.model_calls is None:
            raise ToolConflict(
                "Model call journal is unavailable", code="audit_unavailable"
            )
        try:
            records = self.model_calls.records(cid)
        except Exception:
            raise ToolConflict(
                "Model call journal is unavailable", code="audit_unavailable"
            ) from None
        if not any(getattr(record, "call_id", None) == model_call_id for record in records):
            raise ToolConflict(
                "model_call_id does not belong to this challenge",
                code="model_call_not_bound",
            )
        return model_call_id

    # ------------------------------------------------------------------
    # argument / workspace validation
    # ------------------------------------------------------------------
    def _validate(self, cid: str, tool_name: str, arguments: object) -> dict:
        validated = validate_arguments(tool_name, arguments)
        # Lexical root: tool_impl rejects a challenge directory that is itself
        # a junction/reparse point instead of silently following it.
        root = self.workspace.challenge_lexical(cid)
        path = validated.get("path")
        if path is not None:
            self._check_workspace_path(root, path, directory=tool_name == "list_files")
        return validated

    @staticmethod
    def _check_workspace_path(root: Path, relative: str, *, directory: bool) -> None:
        try:
            candidate = tool_impl.resolve_workspace_path(root, relative)
        except tool_impl.ToolError as error:
            raise ToolValidationError(str(error)) from None
        if not candidate.exists():
            raise ToolValidationError("path does not exist in the challenge workspace")
        if directory:
            if not candidate.is_dir():
                raise ToolValidationError("path is not a directory")
        elif candidate.is_dir():
            raise ToolValidationError("path is a directory, not a file")

    # ------------------------------------------------------------------
    # proposal creation
    # ------------------------------------------------------------------
    def _new_proposal_values(
        self,
        cid: str,
        validated: dict,
        *,
        tool_name: str,
        reason: str,
        proposed_by: str,
        model_call_id: str | None,
    ) -> dict:
        return {
            "challenge_id": cid,
            "model_call_id": model_call_id,
            "tool_name": tool_name,
            "arguments": validated,
            "arguments_json": _canonical(validated),
            "arguments_sha256": _arguments_digest(validated),
            "reason": reason,
            "risk_level": TOOL_SPECS[tool_name].risk_level,
            "status": "pending",
            "proposed_by": proposed_by,
            "proposed_at": now(),
            "expires_at": (datetime.now(timezone.utc) + self.ttl).isoformat(),
        }

    def _insert_proposal(self, db, cid: str, values: dict) -> ToolProposalRecord:
        """Insert the row and its tool_proposed event inside the caller's tx."""
        proposal_id = values["proposal_id"]
        db.execute(
            "INSERT INTO tool_proposals (" + _PROPOSAL_INSERT_COLUMNS + ") "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                proposal_id,
                cid,
                values["model_call_id"],
                values["tool_name"],
                values["arguments_json"],
                values["arguments_sha256"],
                values["reason"],
                values["risk_level"],
                values["status"],
                values["proposed_by"],
                values["proposed_at"],
                values["expires_at"],
            ),
        )
        self.store.append_event(
            db,
            cid,
            "agent" if values["proposed_by"] == "agent" else "user",
            "tool_proposed",
            {
                "proposal_id": proposal_id,
                "model_call_id": values["model_call_id"],
                "tool_name": values["tool_name"],
                "arguments": values["arguments"],
                "reason": values["reason"],
                "risk_level": values["risk_level"],
                "proposed_by": values["proposed_by"],
                "requires_approval": True,
                "execution_performed": False,
            },
        )
        return _record(self._row(db, cid, proposal_id))

    def propose(
        self,
        cid: str,
        tool_name: str,
        arguments: dict,
        reason: str,
        proposed_by: str = "agent",
        model_call_id: str | None = None,
    ) -> ToolProposalRecord:
        """Create a pending proposal; never executes anything."""
        self._require_proposal_allowed(cid)
        if proposed_by not in {"agent", "user"}:
            raise ToolValidationError("proposed_by must be 'agent' or 'user'")
        cleaned_reason = _clean_reason(reason)
        validated = self._validate(cid, tool_name, arguments)
        if proposed_by == "agent":
            if not model_call_id:
                raise ToolValidationError("AI tool proposals require model_call_id")
            self._require_model_call(cid, model_call_id)
        elif model_call_id is not None:
            self._require_model_call(cid, model_call_id)
        values = self._new_proposal_values(
            cid,
            validated,
            tool_name=tool_name,
            reason=cleaned_reason,
            proposed_by=proposed_by,
            model_call_id=model_call_id,
        )
        values["proposal_id"] = uid()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._insert_proposal(db, cid, values)
        return self.get(cid, values["proposal_id"])

    def prepare(
        self, cid: str, raw_proposals: object, model_call_id: str
    ) -> list[dict]:
        """Validate AI tool proposals without writing to the database.

        The returned dicts already carry server-generated ``proposal_id`` and
        ``expires_at`` so the AI chat transaction can record the IDs on its
        ``agent_message`` before calling :meth:`create_many` in that same
        transaction.
        """
        self._require_proposal_allowed(cid)
        if not isinstance(raw_proposals, list):
            raise ToolValidationError("tool_proposals must be a list")
        self._require_model_call(cid, model_call_id)
        prepared: list[dict] = []
        for raw in raw_proposals:
            if not isinstance(raw, dict):
                raise ToolValidationError("tool proposal must be an object")
            unknown = set(raw) - {"tool_name", "arguments", "reason"}
            if unknown:
                raise ToolValidationError(
                    "unknown tool proposal field: " + ", ".join(sorted(unknown))
                )
            tool_name = raw.get("tool_name")
            if not isinstance(tool_name, str):
                raise ToolValidationError("tool_name must be a string")
            reason = _clean_reason(raw.get("reason"))
            validated = self._validate(cid, tool_name, raw.get("arguments", {}))
            values = self._new_proposal_values(
                cid,
                validated,
                tool_name=tool_name,
                reason=reason,
                proposed_by="agent",
                model_call_id=model_call_id,
            )
            values["proposal_id"] = uid()
            prepared.append(values)
        return prepared

    def create_many(self, db, cid: str, prepared: object) -> list[ToolProposalRecord]:
        """Insert prepared proposals and their events in the caller's transaction."""
        if not isinstance(prepared, list):
            raise ToolValidationError("prepared proposals must be a list")
        if not prepared:
            # The AI chat transaction always calls this to keep the answer and
            # its proposals atomic; an empty batch is a no-op at any AI level.
            return []
        # Fail closed if the challenge level was lowered between prepare and the
        # AI transaction commit: read the row through the caller's connection.
        row = db.execute(
            "SELECT body FROM challenges WHERE challenge_id=?", (cid,)
        ).fetchone()
        if row is None:
            raise ToolNotFound(cid)
        challenge = Challenge.model_validate_json(row[0])
        if not policy_for(challenge.ai_usage_level).tool_proposals:
            raise ToolPermissionError()
        records: list[ToolProposalRecord] = []
        seen_ids: set[str] = set()
        for item in prepared:
            if not isinstance(item, dict):
                raise ToolValidationError("prepared proposal must be an object")
            proposal_id = item.get("proposal_id")
            if not isinstance(proposal_id, str) or not proposal_id:
                raise ToolValidationError("prepared proposal is missing proposal_id")
            if proposal_id in seen_ids:
                raise ToolConflict("duplicate proposal_id in one batch")
            seen_ids.add(proposal_id)
            model_call_id = item.get("model_call_id")
            self._require_model_call(cid, model_call_id)
            tool_name = item.get("tool_name")
            if not isinstance(tool_name, str):
                raise ToolValidationError("tool_name must be a string")
            arguments = item.get("arguments", {})
            validated = self._validate(cid, tool_name, arguments)
            computed_sha = _arguments_digest(validated)
            prepared_sha = item.get("arguments_sha256")
            if prepared_sha is not None and prepared_sha != computed_sha:
                raise ToolConflict(
                    "Prepared proposal arguments were modified",
                    code="arguments_changed",
                )
            values = self._new_proposal_values(
                cid,
                validated,
                tool_name=tool_name,
                reason=_clean_reason(item.get("reason")),
                proposed_by="agent",
                model_call_id=model_call_id,
            )
            values["proposal_id"] = proposal_id
            if item.get("expires_at"):
                # Keep the prepared expiry so the ID/expiry recorded on the
                # agent_message match the stored proposal.
                values["expires_at"] = str(item["expires_at"])
            if db.execute(
                "SELECT 1 FROM tool_proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone():
                raise ToolConflict("proposal_id already exists", code="duplicate_proposal")
            records.append(self._insert_proposal(db, cid, values))
        return records

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------
    def _row(self, db, cid: str, proposal_id: str):
        row = db.execute(
            "SELECT " + TOOL_COLUMNS + " FROM tool_proposals "
            "WHERE proposal_id=? AND challenge_id=?",
            (proposal_id, cid),
        ).fetchone()
        if row is None:
            raise ToolNotFound(proposal_id)
        return row

    def get(self, cid: str, proposal_id: str) -> ToolProposalRecord:
        self._challenge(cid)
        with self.store.connect() as db:
            row = self._row(db, cid, proposal_id)
        return _record(row)

    def list(self, cid: str) -> list[ToolProposalRecord]:
        self._challenge(cid)
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT " + TOOL_COLUMNS + " FROM tool_proposals "
                "WHERE challenge_id=? ORDER BY proposed_at DESC, proposal_id DESC",
                (cid,),
            ).fetchall()
        return [_record(row) for row in rows]

    # ------------------------------------------------------------------
    # decisions (approve / reject / cancel)
    # ------------------------------------------------------------------
    def _mark_expired(self, db, cid: str, row, reason: str):
        """Atomically expire a pending/approved proposal and record the event."""
        expired_at = now()
        event = self.store.append_event(
            db,
            cid,
            "system",
            "tool_expired",
            {
                "proposal_id": row[0],
                "model_call_id": row[2],
                "tool_name": row[3],
                "reason": reason,
                "expired_at": expired_at,
                "execution_performed": False,
            },
        )
        db.execute(
            "UPDATE tool_proposals SET status='expired', error=?, decision_event_id=?, "
            "finished_at=? WHERE proposal_id=? AND challenge_id=? "
            "AND status IN ('pending', 'approved')",
            (reason, event.event_id, expired_at, row[0], cid),
        )
        return event

    def approve(
        self, cid: str, proposal_id: str, user: str, note: str | None = None
    ) -> ToolProposalRecord:
        self._require_execution_allowed(cid)
        acting_user = _clean_user(user)
        decision_note = _clean_note(note)
        expired_now = False
        tampered = False
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, cid, proposal_id)
            status = row[8]
            if status == "expired":
                raise ToolConflict(
                    "Tool approval has expired", status="expired", code="expired"
                )
            if status != "pending":
                raise ToolConflict(
                    f"Tool proposal is {status}, not pending", status=status
                )
            if _is_expired(row[11]):
                self._mark_expired(db, cid, row, "approval_expired")
                expired_now = True
            else:
                try:
                    stored_arguments = json.loads(row[4])
                except (TypeError, ValueError):
                    stored_arguments = None
                if not isinstance(stored_arguments, dict) or (
                    _arguments_digest(stored_arguments) != row[5]
                ):
                    self._mark_expired(db, cid, row, "arguments_changed")
                    tampered = True
                else:
                    approval_id = uid()
                    approved_at = now()
                    cursor = db.execute(
                        "UPDATE tool_proposals SET status='approved', approval_id=?, "
                        "approved_by=?, approved_at=?, approved_arguments_sha256=?, "
                        "decision_note=? WHERE proposal_id=? AND challenge_id=? "
                        "AND status='pending'",
                        (
                            approval_id,
                            acting_user,
                            approved_at,
                            row[5],
                            decision_note,
                            proposal_id,
                            cid,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise ToolConflict(
                            "Tool proposal was already decided", status=status
                        )
                    event = self.store.append_event(
                        db,
                        cid,
                        "user",
                        "tool_approved",
                        {
                            "proposal_id": proposal_id,
                            "model_call_id": row[2],
                            "tool_name": row[3],
                            "approval_id": approval_id,
                            "approving_user": acting_user,
                            "arguments_sha256": row[5],
                            "note": decision_note,
                            "execution_performed": False,
                        },
                    )
                    db.execute(
                        "UPDATE tool_proposals SET decision_event_id=? "
                        "WHERE proposal_id=?",
                        (event.event_id, proposal_id),
                    )
        if expired_now:
            raise ToolConflict(
                "Tool approval has expired", status="expired", code="expired"
            )
        if tampered:
            raise ToolConflict(
                "Tool arguments changed after proposal; approval refused",
                status="expired",
                code="arguments_changed",
            )
        return self.get(cid, proposal_id)

    def _decide(
        self,
        cid: str,
        proposal_id: str,
        *,
        user: str,
        note: str | None,
        target: str,
        event_type: str,
        event_actor_key: str,
    ) -> ToolProposalRecord:
        self._require_cleanup_allowed(cid)
        acting_user = _clean_user(user)
        decision_note = _clean_note(note)
        expired_now = False
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, cid, proposal_id)
            status = row[8]
            if status == "expired":
                raise ToolConflict(
                    "Tool approval has expired", status="expired", code="expired"
                )
            if status != "pending":
                raise ToolConflict(
                    f"Tool proposal is {status}, not pending", status=status
                )
            if _is_expired(row[11]):
                self._mark_expired(db, cid, row, "approval_expired")
                expired_now = True
            else:
                cursor = db.execute(
                    "UPDATE tool_proposals SET status=?, decision_note=? "
                    "WHERE proposal_id=? AND challenge_id=? AND status='pending'",
                    (target, decision_note, proposal_id, cid),
                )
                if cursor.rowcount != 1:
                    raise ToolConflict(
                        "Tool proposal was already decided", status=status
                    )
                event = self.store.append_event(
                    db,
                    cid,
                    "user",
                    event_type,
                    {
                        "proposal_id": proposal_id,
                        "model_call_id": row[2],
                        "tool_name": row[3],
                        event_actor_key: acting_user,
                        "note": decision_note,
                        "execution_performed": False,
                    },
                )
                db.execute(
                    "UPDATE tool_proposals SET decision_event_id=? WHERE proposal_id=?",
                    (event.event_id, proposal_id),
                )
        if expired_now:
            raise ToolConflict(
                "Tool approval has expired", status="expired", code="expired"
            )
        return self.get(cid, proposal_id)

    def reject(
        self, cid: str, proposal_id: str, user: str, note: str | None = None
    ) -> ToolProposalRecord:
        return self._decide(
            cid,
            proposal_id,
            user=user,
            note=note,
            target="rejected",
            event_type="tool_rejected",
            event_actor_key="rejecting_user",
        )

    def cancel(
        self, cid: str, proposal_id: str, user: str, note: str | None = None
    ) -> ToolProposalRecord:
        return self._decide(
            cid,
            proposal_id,
            user=user,
            note=note,
            target="cancelled",
            event_type="tool_cancelled",
            event_actor_key="cancelled_by",
        )

    # ------------------------------------------------------------------
    # execution
    # ------------------------------------------------------------------
    def _run(
        self, cid: str, tool_name: str, arguments: dict
    ) -> tuple[str, dict | None, str | None]:
        """Run one whitelisted tool in the restricted subprocess."""
        # Pass the lexical challenge directory, not its resolved target, so the
        # runner can reject a workspace root that is itself a link/reparse point.
        root = self.workspace.challenge_lexical(cid)
        runner = Path(__file__).with_name("tool_runner.py")
        payload = json.dumps(
            {"tool_name": tool_name, "arguments": arguments, "root": str(root)},
            ensure_ascii=False,
        )
        env = {
            key: os.environ[key]
            for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP")
            if key in os.environ
        }
        try:
            with EXECUTION_SLOTS:
                completed = subprocess.run(
                    [sys.executable, "-I", "-B", str(runner)],
                    input=payload.encode("utf-8"),
                    capture_output=True,
                    timeout=EXECUTION_TIMEOUT_SECONDS,
                    env=env,
                    shell=False,
                )
        except subprocess.TimeoutExpired:
            return (
                "timed_out",
                None,
                f"tool execution timed out after {EXECUTION_TIMEOUT_SECONDS:g} seconds",
            )
        except OSError:
            return "failed", None, "tool subprocess could not be started"
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", "replace")[:2000]
            return "failed", None, f"runner exited {completed.returncode}: {stderr}"
        if len(completed.stdout) > MAX_OUTPUT_BYTES:
            return "failed", None, "runner output exceeded the configured limit"
        try:
            result = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return "failed", None, "runner returned invalid JSON"
        if not isinstance(result, dict):
            return "failed", None, "runner returned an invalid result"
        if not result.get("ok"):
            return "failed", None, str(result.get("error", "tool failed"))[:2000]
        output = result.get("output")
        if not isinstance(output, dict):
            return "failed", None, "runner returned an invalid tool result"
        return "succeeded", output, None

    def execute(self, cid: str, proposal_id: str) -> ToolProposalRecord:
        """Claim an approved proposal, run it, then finalize atomically."""
        self._require_execution_allowed(cid)
        expired_now = False
        tampered = False
        invalid = False
        execution_id: str | None = None
        started_event_id: str | None = None
        tool_name: str | None = None
        arguments: dict | None = None
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, cid, proposal_id)
            status = row[8]
            if status == "running":
                raise ToolConflict(
                    "Tool proposal is already running", status="running", code="already_running"
                )
            if status == "expired":
                raise ToolConflict(
                    "Tool approval has expired", status="expired", code="expired"
                )
            if status != "approved":
                raise ToolConflict(
                    f"Tool proposal is {status}, not approved", status=status
                )
            if _is_expired(row[11]):
                self._mark_expired(db, cid, row, "approval_expired")
                expired_now = True
            else:
                try:
                    stored_arguments = json.loads(row[4])
                except (TypeError, ValueError):
                    stored_arguments = None
                computed = (
                    _arguments_digest(stored_arguments)
                    if isinstance(stored_arguments, dict)
                    else None
                )
                if computed is None or computed != row[5] or computed != row[15]:
                    self._mark_expired(db, cid, row, "arguments_changed")
                    tampered = True
                else:
                    try:
                        validated = self._validate(cid, row[3], stored_arguments)
                    except ToolValidationError:
                        self._mark_expired(db, cid, row, "tool_validation_failed")
                        invalid = True
                    else:
                        execution_id = uid()
                        started_at = now()
                        cursor = db.execute(
                            "UPDATE tool_proposals SET status='running', execution_id=?, "
                            "started_at=? WHERE proposal_id=? AND challenge_id=? "
                            "AND status='approved'",
                            (execution_id, started_at, proposal_id, cid),
                        )
                        if cursor.rowcount != 1:
                            raise ToolConflict(
                                "Tool proposal was already claimed",
                                code="already_claimed",
                            )
                        event = self.store.append_event(
                            db,
                            cid,
                            "tool",
                            "tool_started",
                            {
                                "proposal_id": proposal_id,
                                "model_call_id": row[2],
                                "tool_name": row[3],
                                "approval_id": row[12],
                                "execution_id": execution_id,
                                "arguments_sha256": row[5],
                                "started_at": started_at,
                            },
                        )
                        db.execute(
                            "UPDATE tool_proposals SET started_event_id=? "
                            "WHERE proposal_id=?",
                            (event.event_id, proposal_id),
                        )
                        tool_name = row[3]
                        arguments = validated
                        started_event_id = event.event_id
        if expired_now:
            raise ToolConflict(
                "Tool approval has expired", status="expired", code="expired"
            )
        if tampered:
            raise ToolConflict(
                "Tool arguments changed after approval; execution refused",
                status="expired",
                code="arguments_changed",
            )
        if invalid:
            raise ToolConflict(
                "Tool arguments failed validation before execution",
                status="expired",
                code="validation_failed",
            )
        if execution_id is None or tool_name is None or arguments is None or (
            started_event_id is None
        ):
            raise ToolConflict("Tool proposal could not be claimed")

        status, output, error = self._run(cid, tool_name, arguments)
        self._finalize(
            cid,
            proposal_id,
            execution_id=execution_id,
            started_event_id=started_event_id,
            tool_name=tool_name,
            status=status,
            output=output,
            error=error,
        )
        return self.get(cid, proposal_id)

    def _artifact_filename(self, proposal_id: str, execution_id: str) -> str:
        return f"tool-{proposal_id}-{execution_id}.json"

    def _finalize(
        self,
        cid: str,
        proposal_id: str,
        *,
        execution_id: str,
        started_event_id: str,
        tool_name: str,
        status: str,
        output: dict | None,
        error: str | None,
    ) -> None:
        output_artifact_id: str | None = None
        output_sha256: str | None = None
        output_size: int | None = None
        output_summary: str | None = None
        artifact_ids: tuple[str, ...] = ()
        artifact_event = None
        if status == "succeeded" and output is not None:
            encoded = json.dumps(
                output,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            )
            data = encoded.encode("utf-8")
            if len(data) > MAX_OUTPUT_BYTES:
                # Defensive bound: the impl already caps tool output, but never
                # store an unbounded model-influenced blob as evidence.
                status = "succeeded"
                error = None
                output = {
                    "truncated": True,
                    "output_sha256": hashlib.sha256(data).hexdigest(),
                    "output_size": len(data),
                }
                encoded = json.dumps(
                    output, sort_keys=True, ensure_ascii=False, allow_nan=False
                )
                data = encoded.encode("utf-8")
            try:
                ingested = self.artifacts.ingest(
                    io.BytesIO(data),
                    filename=self._artifact_filename(proposal_id, execution_id),
                )
            except Exception:
                status = "failed"
                error = "tool output could not be stored as an artifact"
                output = None
            else:
                output_sha256 = ingested.sha256
                output_size = ingested.size
                output_summary = encoded[:OUTPUT_SUMMARY_CHARS]
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, cid, proposal_id)
            if row[8] != "running" or row[18] != execution_id:
                raise ToolConflict(
                    "Tool execution state changed before finalization",
                    status=row[8],
                    code="execution_state_changed",
                )
            if output is not None and output_sha256 is not None:
                artifact, artifact_event = self.store.add_artifact_with_db(
                    db,
                    cid,
                    sha256=output_sha256,
                    size=output_size,
                    media_type="application/json",
                    original_filename=self._artifact_filename(
                        proposal_id, execution_id
                    ),
                    evidence_kind="execution_output",
                    actor="tool",
                    payload_extra={
                        "proposal_id": proposal_id,
                        "model_call_id": row[2],
                        "execution_id": execution_id,
                        "tool_name": tool_name,
                        "source": "tool_execution",
                        "execution_performed": True,
                    },
                )
                output_artifact_id = artifact.artifact_id
                artifact_ids = (artifact.artifact_id,)
            finished_at = now()
            finished_event = self.store.append_event(
                db,
                cid,
                "tool",
                "tool_finished",
                {
                    "proposal_id": proposal_id,
                    "model_call_id": row[2],
                    "tool_name": tool_name,
                    "approval_id": row[12],
                    "execution_id": execution_id,
                    "started_event_id": started_event_id,
                    "status": status,
                    "output_artifact_id": output_artifact_id,
                    "artifact_ids": list(artifact_ids),
                    "output_sha256": output_sha256,
                    "output_size": output_size,
                    "output_summary": output_summary,
                    "error": error,
                    "recovered": False,
                    "finished_at": finished_at,
                },
                artifact_ids=artifact_ids,
            )
            db.execute(
                "UPDATE tool_proposals SET status=?, finished_at=?, "
                "finished_event_id=?, output_artifact_id=?, output_sha256=?, "
                "output_size=?, output_summary=?, artifact_ids=?, error=? "
                "WHERE proposal_id=? AND challenge_id=? AND status='running'",
                (
                    status,
                    finished_at,
                    finished_event.event_id,
                    output_artifact_id,
                    output_sha256,
                    output_size,
                    output_summary,
                    json.dumps(list(artifact_ids)) if artifact_ids else None,
                    error,
                    proposal_id,
                    cid,
                ),
            )

    # ------------------------------------------------------------------
    # startup recovery / expiry sweep
    # ------------------------------------------------------------------
    def _find(self, where: str, params: tuple = ()) -> list[tuple[str, str]]:
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT challenge_id, proposal_id FROM tool_proposals WHERE " + where,
                params,
            ).fetchall()
        return [(row[0], row[1]) for row in rows]

    def recover_interrupted(self) -> dict:
        """Mark every ``running`` proposal failed after a process restart.

        A crash between the (atomic) claim and finalization leaves the proposal
        ``running`` with a ``tool_started`` event.  Recovery writes the missing
        ``tool_finished`` event and the state change in one transaction.
        """
        recovered = 0
        for cid, proposal_id in self._find("status='running'"):
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = self._row(db, cid, proposal_id)
                if row[8] != "running":
                    continue
                finished_at = now()
                event = self.store.append_event(
                    db,
                    cid,
                    "tool",
                    "tool_finished",
                    {
                        "proposal_id": proposal_id,
                        "model_call_id": row[2],
                        "tool_name": row[3],
                        "approval_id": row[12],
                        "execution_id": row[18],
                        "started_event_id": row[21],
                        "status": "failed",
                        "output_artifact_id": None,
                        "artifact_ids": [],
                        "output_sha256": None,
                        "output_size": None,
                        "output_summary": None,
                        "error": INTERRUPTED_ERROR,
                        "recovered": True,
                        "finished_at": finished_at,
                    },
                )
                db.execute(
                    "UPDATE tool_proposals SET status='failed', finished_at=?, "
                    "finished_event_id=?, error=? WHERE proposal_id=? "
                    "AND challenge_id=? AND status='running'",
                    (
                        finished_at,
                        event.event_id,
                        INTERRUPTED_ERROR,
                        proposal_id,
                        cid,
                    ),
                )
                recovered += 1
        return {"recovered": recovered}

    def expire_stale(self) -> dict:
        """Expire pending/approved proposals whose approval window has passed."""
        expired = 0
        for cid, proposal_id in self._find(
            "status IN ('pending', 'approved') AND expires_at <= ?", (now(),)
        ):
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = self._row(db, cid, proposal_id)
                if row[8] not in {"pending", "approved"}:
                    continue
                if not _is_expired(row[11]):
                    continue
                self._mark_expired(db, cid, row, "approval_expired")
                expired += 1
        return {"expired": expired}


__all__ = [
    "ToolService",
    "ToolNotFound",
    "ToolConflict",
    "ToolPermissionError",
    "ToolValidationError",
    "catalog",
]
