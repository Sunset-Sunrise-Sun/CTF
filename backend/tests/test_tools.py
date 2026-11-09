"""Tests for the P0 unified tool subsystem (approval and execution are separate).

All data is synthetic: no network, no real model API key, no challenge binary is
executed.  The restricted runner is exercised over its stdin/stdout JSON
protocol.  Tests use ``tmp_path`` for every store/workspace/artifact root.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import tool_system
from app.artifacts import ArtifactStore
from app.main import create_app
from app.model_calls import ModelCallJournal, ModelCallRecord
from app.models import Challenge, now
from app.store import Store
from app.tool_registry import (
    TOOL_SPECS,
    ToolValidationError,
    catalog,
    validate_arguments,
)
from app.tool_system import (
    ToolConflict,
    ToolNotFound,
    ToolPermissionError,
    ToolService,
)
from app.workspace import Workspace

SAMPLE_BYTES = (
    b"\x7fELF\x02\x01\x01"
    + b"\x00" * 11
    + b" SYNTHETIC_TOOL_MARKER_1234567890 "
)
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (16).to_bytes(
    4, "big"
) + (8).to_bytes(4, "big") + b"\x08\x02\x00\x00\x00" + b"\x00" * 9
BASE64_TEXT = base64.b64encode(b"DECODED_SYNTHETIC_TEXT").decode("ascii")
HEX_TEXT = b"DECODED_SYNTHETIC_TEXT".hex().encode("ascii")


def _canonical(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: dict) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _create_windows_junction(link: Path, target: Path) -> None:
    """Create a real NTFS junction; fail rather than skip on a capable host."""
    if sys.platform != "win32":
        pytest.skip("junction is a Windows reparse point")
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        shell=False,
        text=True,
    )
    if completed.returncode != 0:
        # Do not hide a failed setup as a passing/skipped security test.
        pytest.fail(
            "junction creation failed on Windows: "
            + (completed.stderr or completed.stdout or "unknown error")
        )


def _remove_windows_junction(link: Path) -> None:
    if sys.platform == "win32" and link.exists():
        subprocess.run(
            ["cmd", "/c", "rmdir", str(link)], capture_output=True, shell=False
        )


class Env:
    def __init__(self, tmp_path: Path, *, level: str = "A2") -> None:
        self.store = Store(tmp_path / "workbench.sqlite3")
        self.workspace = Workspace(tmp_path / "challenges")
        self.artifacts = ArtifactStore(tmp_path / "artifacts")
        self.journal = ModelCallJournal(tmp_path / "model-audit.sqlite3")
        self.cid = str(uuid.uuid4())
        self.store.create(
            Challenge(
                challenge_id=self.cid,
                name="Synthetic tools",
                category="Misc",
                ai_usage_level=level,
            )
        )
        self.root = self.workspace.challenge(self.cid)
        self.root.mkdir(parents=True)
        (self.root / "samples").mkdir()
        (self.root / "samples/sample.elf").write_bytes(SAMPLE_BYTES)
        (self.root / "samples/pixel.png").write_bytes(PNG_BYTES)
        (self.root / "samples/b64.txt").write_bytes(BASE64_TEXT.encode("ascii"))
        (self.root / "samples/hex.txt").write_bytes(HEX_TEXT)
        (self.root / "samples/plain.txt").write_bytes(b"SYNTHETIC plain text")
        self.call_id = str(uuid.uuid4())
        self.journal.start(
            ModelCallRecord(
                call_id=self.call_id,
                challenge_id=self.cid,
                provider_id="synthetic-provider",
                model_id="synthetic-model",
                purpose="challenge_chat",
                synthetic=False,
                data_scope="challenge_selected",
                requested_at=now(),
            )
        )
        self.service = ToolService(
            self.store, self.workspace, self.artifacts, self.journal
        )

    def events(self, cid: str | None = None) -> list:
        return self.store.events(cid or self.cid)

    def event_types(self, cid: str | None = None) -> list[str]:
        return [event.event_type for event in self.events(cid)]

    def db(self, sql: str, params: tuple = ()):  # pragma: no cover - helper
        with self.store.connect() as db:
            return db.execute(sql, params).fetchall()

    def artifact_rows(self) -> list:
        return self.db(
            "SELECT artifact_id FROM artifacts WHERE challenge_id=?", (self.cid,)
        )

    def execute_sql(self, sql: str, params: tuple = ()) -> None:
        with self.store.connect() as db:
            db.execute(sql, params)

    def propose(self, *, tool_name="file_inspect", arguments=None, **kwargs):
        if kwargs.get("proposed_by", "agent") == "agent" and "model_call_id" not in kwargs:
            kwargs["model_call_id"] = self.call_id
        return self.service.propose(
            self.cid,
            tool_name=tool_name,
            arguments=arguments or {"path": "samples/sample.elf"},
            reason=kwargs.pop("reason", "Synthetic inspection"),
            **kwargs,
        )

    def approved(self, *, tool_name="file_inspect", arguments=None, **kwargs):
        proposal = self.propose(tool_name=tool_name, arguments=arguments, **kwargs)
        return self.service.approve(self.cid, proposal.proposal_id, "synthetic-user")

    def artifact_text(self, sha256: str) -> str:
        return self.artifacts.read_verified(sha256).decode("utf-8")

    def workspace_snapshot(self) -> dict[str, bytes]:
        return {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


@pytest.fixture
def env_a1(tmp_path):
    return Env(tmp_path, level="A1")


# ----------------------------------------------------------------------
# registry
# ----------------------------------------------------------------------
def test_registry_is_fixed_seven_read_only_tools():
    names = [spec.name for spec in TOOL_SPECS.values()]
    assert names == [
        "file_inspect",
        "sha256",
        "stat",
        "strings",
        "list_files",
        "image_info",
        "text_decode",
    ]
    assert catalog() and all(
        item["read_only"] is True
        and item["requires_approval"] is True
        and item["risk_level"] == "low"
        for item in catalog()
    )
    json.dumps(catalog())  # must stay JSON serialisable for GET /api/tools
    forbidden = {"shell", "exec", "python", "network", "http", "write", "delete"}
    assert not forbidden & set(names)
    # Strict argument validation.
    assert validate_arguments(
        "strings", {"path": "a", "min_length": 8, "max_strings": 5}
    ) == {"path": "a", "min_length": 8, "max_strings": 5}
    for bad in (
        ("shell", {"cmd": "whoami"}),
        ("file_inspect", {"path": "a", "unknown": 1}),
        ("file_inspect", {}),
        ("strings", {"path": "a", "min_length": 1}),
        ("strings", {"path": "a", "max_strings": 10_000}),
        ("list_files", {"recursive": "yes"}),
        ("text_decode", {"path": "a", "encoding": "rot13"}),
        ("sha256", "not-an-object"),
    ):
        with pytest.raises(ToolValidationError):
            validate_arguments(*bad)


# ----------------------------------------------------------------------
# proposal lifecycle
# ----------------------------------------------------------------------
def test_proposal_does_not_execute_and_is_audited(env):
    proposal = env.propose()
    assert proposal.status == "pending"
    assert proposal.proposed_by == "agent"
    assert proposal.arguments == {"path": "samples/sample.elf"}
    assert proposal.model_call_id == env.call_id
    assert proposal.artifact_ids == []
    assert proposal.decision_event_id is None
    assert env.artifact_rows() == []
    assert env.event_types() == ["tool_proposed"]
    payload = env.events()[0].payload
    assert payload["proposal_id"] == proposal.proposal_id
    assert payload["model_call_id"] == env.call_id
    assert payload["requires_approval"] is True
    assert payload["execution_performed"] is False
    assert env.store.verify(env.cid)["valid"]
    assert [item.proposal_id for item in env.service.list(env.cid)] == [
        proposal.proposal_id
    ]
    # Stored argument digest is the canonical JSON digest.
    rows = env.db(
        "SELECT arguments_sha256, status FROM tool_proposals WHERE proposal_id=?",
        (proposal.proposal_id,),
    )
    assert rows[0][0] == _digest(proposal.arguments)


def test_approve_then_execute_are_separate_and_chained(env):
    proposal = env.propose()
    approved = env.service.approve(
        env.cid, proposal.proposal_id, "synthetic-user", "synthetic approval"
    )
    assert approved.status == "approved"
    assert approved.approval_id
    assert approved.approved_by == "synthetic-user"
    assert approved.decision_event_id
    assert env.event_types() == ["tool_proposed", "tool_approved"]
    assert env.artifact_rows() == []
    approval_event = env.events()[-1]
    assert approval_event.event_id == approved.decision_event_id
    assert approval_event.actor == "user"
    assert approval_event.payload["approval_id"] == approved.approval_id

    executed = env.service.execute(env.cid, proposal.proposal_id)
    assert executed.status == "succeeded"
    assert executed.execution_id
    assert executed.started_event_id and executed.finished_event_id
    assert executed.output_artifact_id
    assert executed.artifact_ids == [executed.output_artifact_id]
    assert executed.output_sha256 and executed.output_size and executed.output_size > 0
    assert executed.output_summary and "format" in executed.output_summary
    assert executed.error is None
    assert env.event_types() == [
        "tool_proposed",
        "tool_approved",
        "tool_started",
        "artifact_added",
        "tool_finished",
    ]
    assert env.store.verify(env.cid)["valid"]

    artifact = env.artifacts.read_verified(executed.output_sha256)
    assert hashlib.sha256(artifact).hexdigest() == executed.output_sha256
    output = json.loads(artifact)
    assert output["format"] == "ELF"
    assert output["size"] == len(SAMPLE_BYTES)
    finished = env.events()[-1]
    assert finished.payload["execution_id"] == executed.execution_id
    assert finished.payload["artifact_ids"] == executed.artifact_ids
    assert finished.artifact_ids == executed.artifact_ids
    assert finished.payload["output_artifact_id"] == executed.output_artifact_id
    artifact_event = env.events()[-2]
    assert artifact_event.event_type == "artifact_added"
    assert artifact_event.payload["evidence_kind"] == "execution_output"
    assert artifact_event.payload["proposal_id"] == proposal.proposal_id
    # Artifact metadata row was inserted in the final transaction.
    rows = env.db(
        "SELECT artifact_id, sha256, original_filename FROM artifacts WHERE challenge_id=?",
        (env.cid,),
    )
    assert rows == [
        (
            executed.output_artifact_id,
            executed.output_sha256,
            f"tool-{proposal.proposal_id}-{executed.execution_id}.json",
        )
    ]


def test_execute_requires_approval_and_is_single_use(env):
    proposal = env.propose()
    with pytest.raises(ToolConflict) as excinfo:
        env.service.execute(env.cid, proposal.proposal_id)
    assert excinfo.value.status == "pending"
    assert "tool_started" not in env.event_types()

    env.service.approve(env.cid, proposal.proposal_id, "synthetic-user")
    with pytest.raises(ToolConflict):
        env.service.approve(env.cid, proposal.proposal_id, "synthetic-user")

    env.service.execute(env.cid, proposal.proposal_id)
    with pytest.raises(ToolConflict):
        env.service.execute(env.cid, proposal.proposal_id)
    assert env.event_types().count("tool_started") == 1
    assert env.event_types().count("tool_finished") == 1


def test_reject_and_cancel_prevent_execution(env):
    rejected = env.propose(reason="reject fixture")
    result = env.service.reject(
        env.cid, rejected.proposal_id, "synthetic-user", "not needed"
    )
    assert result.status == "rejected"
    assert result.decision_event_id
    assert env.event_types() == ["tool_proposed", "tool_rejected"]
    assert env.events()[-1].payload["rejecting_user"] == "synthetic-user"
    with pytest.raises(ToolConflict):
        env.service.approve(env.cid, rejected.proposal_id, "synthetic-user")
    with pytest.raises(ToolConflict):
        env.service.execute(env.cid, rejected.proposal_id)

    cancelled = env.propose(reason="cancel fixture")
    result = env.service.cancel(env.cid, cancelled.proposal_id, "synthetic-user")
    assert result.status == "cancelled"
    assert result.decision_event_id
    assert env.events()[-1].event_type == "tool_cancelled"
    assert "tool_started" not in env.event_types()
    assert "tool_finished" not in env.event_types()


# ----------------------------------------------------------------------
# expiry
# ----------------------------------------------------------------------
def _expire(env: Env, proposal_id: str) -> None:
    env.execute_sql(
        "UPDATE tool_proposals SET expires_at='2000-01-01T00:00:00+00:00' "
        "WHERE proposal_id=?",
        (proposal_id,),
    )


def test_expired_pending_cannot_be_approved(env):
    proposal = env.propose()
    _expire(env, proposal.proposal_id)
    with pytest.raises(ToolConflict) as excinfo:
        env.service.approve(env.cid, proposal.proposal_id, "synthetic-user")
    assert excinfo.value.status == "expired"
    current = env.service.get(env.cid, proposal.proposal_id)
    assert current.status == "expired"
    assert current.decision_event_id
    assert env.event_types()[-1] == "tool_expired"
    assert env.events()[-1].payload["reason"] == "approval_expired"
    assert env.store.verify(env.cid)["valid"]


def test_expired_approval_cannot_execute(env):
    proposal = env.approved()
    _expire(env, proposal.proposal_id)
    with pytest.raises(ToolConflict) as excinfo:
        env.service.execute(env.cid, proposal.proposal_id)
    assert excinfo.value.status == "expired"
    assert env.service.get(env.cid, proposal.proposal_id).status == "expired"
    assert env.event_types()[-1] == "tool_expired"
    assert "tool_started" not in env.event_types()
    assert env.store.verify(env.cid)["valid"]


def test_expire_stale_sweeps_pending_and_approved(env):
    pending = env.propose(reason="stale pending")
    approved = env.approved(reason="stale approved")
    _expire(env, pending.proposal_id)
    _expire(env, approved.proposal_id)
    result = env.service.expire_stale()
    assert result == {"expired": 2}
    assert env.service.get(env.cid, pending.proposal_id).status == "expired"
    assert env.service.get(env.cid, approved.proposal_id).status == "expired"
    assert env.event_types().count("tool_expired") == 2
    assert env.service.expire_stale() == {"expired": 0}
    assert env.store.verify(env.cid)["valid"]


# ----------------------------------------------------------------------
# parameter tampering
# ----------------------------------------------------------------------
def test_parameter_tampering_after_approval_is_refused(env):
    proposal = env.approved()
    tampered = {"path": "samples/plain.txt"}
    env.execute_sql(
        "UPDATE tool_proposals SET arguments_json=? WHERE proposal_id=?",
        (_canonical(tampered), proposal.proposal_id),
    )
    with pytest.raises(ToolConflict) as excinfo:
        env.service.execute(env.cid, proposal.proposal_id)
    assert excinfo.value.code == "arguments_changed"
    assert excinfo.value.status == "expired"
    current = env.service.get(env.cid, proposal.proposal_id)
    assert current.status == "expired"
    assert env.events()[-1].event_type == "tool_expired"
    assert env.events()[-1].payload["reason"] == "arguments_changed"
    assert "tool_started" not in env.event_types()
    assert env.store.verify(env.cid)["valid"]


def test_parameter_tampering_before_approval_is_refused(env):
    proposal = env.propose()
    env.execute_sql(
        "UPDATE tool_proposals SET arguments_json=? WHERE proposal_id=?",
        (_canonical({"path": "samples/plain.txt"}), proposal.proposal_id),
    )
    with pytest.raises(ToolConflict) as excinfo:
        env.service.approve(env.cid, proposal.proposal_id, "synthetic-user")
    assert excinfo.value.code == "arguments_changed"
    assert env.service.get(env.cid, proposal.proposal_id).status == "expired"


# ----------------------------------------------------------------------
# workspace boundary
# ----------------------------------------------------------------------
def test_workspace_boundary_and_schema_are_enforced(env, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside")
    invalid_arguments = [
        {"path": "../outside.txt"},
        {"path": str(outside)},
        {"path": "C:/Windows/win.ini"},
        {"path": "samples/../samples/sample.elf"},
        {"path": "samples/a:b"},
        {"path": "NUL"},
        {"path": "CON.txt"},
        {"path": "samples"},
        {"path": "samples/missing.elf"},
        {"path": "samples/sample.elf", "unknown": 1},
    ]
    for arguments in invalid_arguments:
        with pytest.raises(ToolValidationError):
            env.propose(arguments=arguments)
    with pytest.raises(ToolValidationError):
        env.propose(tool_name="shell", arguments={"cmd": "whoami"})
    with pytest.raises(ToolValidationError):
        env.propose(reason="")
    assert env.events() == []
    assert env.store.verify(env.cid)["valid"]

    link = env.root / "samples/link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this host")
    with pytest.raises(ToolValidationError):
        env.propose(arguments={"path": "samples/link.txt"})
    assert env.events() == []


def test_windows_junction_escape_is_rejected(env, tmp_path):
    """A directory junction is a reparse point; it must not escape the workspace."""
    outside_dir = tmp_path / "outside-dir"
    outside_dir.mkdir()
    (outside_dir / "secret.txt").write_bytes(b"synthetic outside secret")
    junction = env.root / "samples/junction"
    _create_windows_junction(junction, outside_dir)
    try:
        with pytest.raises(ToolValidationError):
            env.propose(arguments={"path": "samples/junction/secret.txt"})
        with pytest.raises(ToolValidationError):
            env.propose(tool_name="list_files", arguments={"path": "samples/junction"})
        assert env.events() == []
        runner = Path(tool_system.__file__).with_name("tool_runner.py")
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(runner)],
            input=json.dumps(
                {
                    "tool_name": "file_inspect",
                    "arguments": {"path": "samples/junction/secret.txt"},
                    "root": str(env.root),
                }
            ).encode("utf-8"),
            capture_output=True,
            timeout=30,
            shell=False,
        )
        assert json.loads(result.stdout.decode("utf-8"))["ok"] is False
    finally:
        _remove_windows_junction(junction)


def test_windows_junction_listing_prunes_external_recursive_and_flat(env, tmp_path):
    """Both list_files modes must prune a junction and never expose its target."""
    outside_dir = tmp_path / "outside-listing"
    outside_dir.mkdir()
    (outside_dir / "outside-secret.txt").write_bytes(b"OUTSIDE_SECRET_CONTENT")
    junction = env.root / "samples/external-link"
    _create_windows_junction(junction, outside_dir)
    try:
        # recursive=true must not descend into the junction at all.
        recursive = env.approved(
            tool_name="list_files",
            arguments={"path": "samples", "recursive": True, "max_entries": 100},
        )
        recursive_result = env.service.execute(env.cid, recursive.proposal_id)
        assert recursive_result.status == "succeeded"
        recursive_output = env.artifacts.read_verified(recursive_result.output_sha256)
        text = recursive_output.decode("utf-8")
        assert "outside-secret.txt" not in text
        assert "external-link" not in text

        # recursive=false must omit the junction entry itself.
        flat = env.approved(
            tool_name="list_files",
            arguments={"path": "samples", "recursive": False, "max_entries": 100},
        )
        flat_result = env.service.execute(env.cid, flat.proposal_id)
        assert flat_result.status == "succeeded"
        flat_text = env.artifacts.read_verified(flat_result.output_sha256).decode(
            "utf-8"
        )
        assert "external-link" not in flat_text
        assert "outside-secret.txt" not in flat_text

        # The external file itself remains unreadable through every entry point.
        with pytest.raises(ToolValidationError):
            env.propose(arguments={"path": "samples/external-link/outside-secret.txt"})
        runner = Path(tool_system.__file__).with_name("tool_runner.py")
        for tool_name, args in (
            ("file_inspect", {"path": "samples/external-link/outside-secret.txt"}),
            ("strings", {"path": "samples/external-link/outside-secret.txt"}),
            ("list_files", {"path": "samples/external-link", "recursive": True}),
        ):
            result = subprocess.run(
                [sys.executable, "-I", "-B", str(runner)],
                input=json.dumps(
                    {"tool_name": tool_name, "arguments": args, "root": str(env.root)}
                ).encode("utf-8"),
                capture_output=True,
                timeout=30,
                shell=False,
            )
            payload = json.loads(result.stdout.decode("utf-8"))
            assert payload["ok"] is False
            assert "OUTSIDE_SECRET_CONTENT" not in json.dumps(payload)
    finally:
        _remove_windows_junction(junction)


def test_windows_workspace_root_junction_is_rejected(env, tmp_path):
    """The challenge workspace root itself must not be a junction."""
    outside_dir = tmp_path / "outside-root"
    outside_dir.mkdir()
    (outside_dir / "root-secret.txt").write_bytes(b"ROOT_OUTSIDE_SECRET")
    cid = str(uuid.uuid4())
    env.store.create(
        Challenge(
            challenge_id=cid,
            name="Synthetic root junction",
            category="Misc",
            ai_usage_level="A2",
        )
    )
    challenge_root = env.workspace.root / cid
    _create_windows_junction(challenge_root, outside_dir)
    try:
        with pytest.raises(ToolValidationError):
            env.service.propose(
                cid,
                tool_name="list_files",
                arguments={"path": ".", "recursive": True},
                reason="root junction must be rejected",
                proposed_by="user",
            )
        assert env.store.events(cid) == []
        runner = Path(tool_system.__file__).with_name("tool_runner.py")
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(runner)],
            input=json.dumps(
                {
                    "tool_name": "list_files",
                    "arguments": {"path": ".", "recursive": True},
                    "root": str(challenge_root),
                }
            ).encode("utf-8"),
            capture_output=True,
            timeout=30,
            shell=False,
        )
        payload = json.loads(result.stdout.decode("utf-8"))
        assert payload["ok"] is False
        assert "root-secret.txt" not in json.dumps(payload)
        assert "ROOT_OUTSIDE_SECRET" not in json.dumps(payload)
    finally:
        _remove_windows_junction(challenge_root)


def test_cross_challenge_isolation(env):
    other_cid = str(uuid.uuid4())
    env.store.create(
        Challenge(
            challenge_id=other_cid,
            name="Synthetic other",
            category="Misc",
            ai_usage_level="A2",
        )
    )
    env.workspace.challenge(other_cid).mkdir(parents=True)
    proposal = env.propose()
    assert env.service.list(other_cid) == []
    with pytest.raises(ToolNotFound):
        env.service.get(other_cid, proposal.proposal_id)
    with pytest.raises(ToolNotFound):
        env.service.approve(other_cid, proposal.proposal_id, "synthetic-user")
    with pytest.raises(ToolNotFound):
        env.service.execute(other_cid, proposal.proposal_id)
    assert env.store.events(other_cid) == []
    # The owner can still proceed; the row is bound to its challenge.
    env.service.approve(env.cid, proposal.proposal_id, "synthetic-user")
    assert env.service.execute(env.cid, proposal.proposal_id).status == "succeeded"


# ----------------------------------------------------------------------
# A2 gating and model-call binding
# ----------------------------------------------------------------------
def test_a0_a1_levels_are_denied(tmp_path):
    for level in ("unknown", "A0", "A1"):
        env = Env(tmp_path / level, level=level)
        with pytest.raises(ToolPermissionError):
            env.propose()
        assert env.events() == []


def test_downgrade_after_proposal_blocks_approve_and_execute(env):
    proposal = env.propose()
    challenge = env.store.get(env.cid)
    downgraded = challenge.model_copy(update={"ai_usage_level": "A1"})
    env.execute_sql(
        "UPDATE challenges SET body=? WHERE challenge_id=?",
        (downgraded.model_dump_json(), env.cid),
    )
    with pytest.raises(ToolPermissionError):
        env.service.approve(env.cid, proposal.proposal_id, "synthetic-user")
    with pytest.raises(ToolPermissionError):
        env.service.execute(env.cid, proposal.proposal_id)
    # A1 may still clean up a proposal by rejecting/cancelling it.
    assert env.service.reject(
        env.cid, proposal.proposal_id, "synthetic-user"
    ).status == "rejected"

    unknown = challenge.model_copy(update={"ai_usage_level": "unknown"})
    env.execute_sql(
        "UPDATE challenges SET body=? WHERE challenge_id=?",
        (unknown.model_dump_json(), env.cid),
    )
    with pytest.raises(ToolPermissionError):
        env.service.reject(env.cid, proposal.proposal_id, "synthetic-user")


def test_agent_proposal_requires_challenge_bound_model_call(env):
    with pytest.raises(ToolValidationError):
        env.propose(proposed_by="agent", model_call_id=None)
    with pytest.raises(ToolConflict) as excinfo:
        env.propose(proposed_by="agent", model_call_id=str(uuid.uuid4()))
    assert excinfo.value.code == "model_call_not_bound"
    proposal = env.propose(proposed_by="agent", model_call_id=env.call_id)
    assert proposal.model_call_id == env.call_id
    assert env.events()[0].payload["model_call_id"] == env.call_id
    # A manual (user) proposal may omit the model call.
    manual = env.propose(proposed_by="user")
    assert manual.model_call_id is None


def test_create_many_empty_batch_is_noop_but_nonempty_is_gated(tmp_path):
    """The AI chat transaction calls create_many([]) even when tools are denied."""
    env = Env(tmp_path, level="A1")
    with env.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert env.service.create_many(db, env.cid, []) == []
    assert env.service.list(env.cid) == []
    assert env.events() == []
    forged = [
        {
            "proposal_id": str(uuid.uuid4()),
            "challenge_id": env.cid,
            "model_call_id": env.call_id,
            "tool_name": "sha256",
            "arguments": {"path": "samples/sample.elf"},
            "arguments_sha256": _digest({"path": "samples/sample.elf"}),
            "reason": "forged at A1",
            "risk_level": "low",
            "proposed_by": "agent",
            "proposed_at": now(),
            "expires_at": now(),
        }
    ]
    with pytest.raises(ToolPermissionError), env.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        env.service.create_many(db, env.cid, forged)
    assert env.service.list(env.cid) == []
    assert env.events() == []


def test_prepare_and_create_many_are_separate_and_atomic(env):
    prepared = env.service.prepare(
        env.cid,
        [
            {
                "tool_name": "sha256",
                "arguments": {"path": "samples/sample.elf"},
                "reason": "AI requested hash",
            }
        ],
        env.call_id,
    )
    assert len(prepared) == 1
    item = prepared[0]
    for key in (
        "proposal_id",
        "tool_name",
        "arguments",
        "arguments_sha256",
        "reason",
        "risk_level",
        "expires_at",
        "model_call_id",
        "proposed_by",
    ):
        assert key in item
    assert item["proposed_by"] == "agent"
    assert item["model_call_id"] == env.call_id
    assert item["arguments_sha256"] == _digest(item["arguments"])
    # prepare must not write anything.
    assert env.service.list(env.cid) == []
    assert env.events() == []

    with env.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        records = env.service.create_many(db, env.cid, prepared)
    assert [record.proposal_id for record in records] == [item["proposal_id"]]
    assert env.event_types() == ["tool_proposed"]
    assert env.store.verify(env.cid)["valid"]

    # create_many rejects prepared arguments modified after prepare.
    tampered = [dict(item)]
    tampered[0]["proposal_id"] = str(uuid.uuid4())
    tampered[0]["arguments"] = {"path": "samples/plain.txt"}
    with pytest.raises(ToolConflict) as excinfo, env.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        env.service.create_many(db, env.cid, tampered)
    assert excinfo.value.code == "arguments_changed"

    # A failure inside the caller transaction rolls back every inserted row+event.
    duplicate = [dict(item)]
    duplicate[0]["proposal_id"] = str(uuid.uuid4())
    with pytest.raises(ToolConflict), env.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        env.service.create_many(db, env.cid, duplicate + duplicate)
    assert len(env.service.list(env.cid)) == 1
    assert env.event_types() == ["tool_proposed"]


# ----------------------------------------------------------------------
# execution outcomes
# ----------------------------------------------------------------------
def test_timeout_is_recorded(env, monkeypatch):
    monkeypatch.setattr(tool_system, "EXECUTION_TIMEOUT_SECONDS", 1e-9)
    proposal = env.approved(tool_name="list_files", arguments={"path": "."})
    executed = env.service.execute(env.cid, proposal.proposal_id)
    assert executed.status == "timed_out"
    assert executed.output_artifact_id is None
    assert executed.artifact_ids == []
    assert "timed out" in (executed.error or "")
    finished = env.events()[-1]
    assert finished.event_type == "tool_finished"
    assert finished.payload["status"] == "timed_out"
    assert "artifact_added" not in env.event_types()
    assert env.store.verify(env.cid)["valid"]


def test_failed_execution_is_recorded(env):
    proposal = env.approved(
        tool_name="image_info", arguments={"path": "samples/sample.elf"}
    )
    executed = env.service.execute(env.cid, proposal.proposal_id)
    assert executed.status == "failed"
    assert executed.output_artifact_id is None
    assert executed.error
    assert env.events()[-1].payload["status"] == "failed"
    assert env.store.verify(env.cid)["valid"]


def test_output_is_bounded_and_read_only(env):
    before = env.workspace_snapshot()
    proposal = env.approved(
        tool_name="strings",
        arguments={
            "path": "samples/sample.elf",
            "min_length": 8,
            "max_strings": 5,
        },
    )
    executed = env.service.execute(env.cid, proposal.proposal_id)
    assert executed.status == "succeeded"
    output = json.loads(env.artifact_text(executed.output_sha256))
    assert len(output["strings"]) <= 5
    assert any("SYNTHETIC_TOOL_MARKER" in value for value in output["strings"])
    assert executed.output_size < 64 * 1024
    # The tool did not mutate the workspace.
    assert env.workspace_snapshot() == before


def test_all_seven_tools_execute_read_only(env):
    before = env.workspace_snapshot()
    cases = [
        ("file_inspect", {"path": "samples/sample.elf"}),
        ("sha256", {"path": "samples/sample.elf"}),
        ("stat", {"path": "samples/sample.elf"}),
        ("strings", {"path": "samples/sample.elf", "max_strings": 3}),
        ("list_files", {"path": ".", "recursive": False}),
        ("image_info", {"path": "samples/pixel.png"}),
        ("text_decode", {"path": "samples/b64.txt", "encoding": "base64"}),
    ]
    for tool_name, arguments in cases:
        proposal = env.approved(tool_name=tool_name, arguments=arguments)
        executed = env.service.execute(env.cid, proposal.proposal_id)
        assert executed.status == "succeeded", (tool_name, executed.error)
        assert executed.output_artifact_id
        json.loads(env.artifact_text(executed.output_sha256))
    assert env.workspace_snapshot() == before
    assert env.store.verify(env.cid)["valid"]
    assert env.event_types().count("tool_finished") == len(cases)


def test_runner_revalidates_its_own_boundary(env, tmp_path):
    runner = Path(tool_system.__file__).with_name("tool_runner.py")

    def run(payload: dict) -> dict:
        completed = subprocess.run(
            [sys.executable, "-I", "-B", str(runner)],
            input=json.dumps(payload).encode("utf-8"),
            capture_output=True,
            timeout=30,
            shell=False,
        )
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout.decode("utf-8"))

    root = str(env.root)
    good = run(
        {
            "tool_name": "file_inspect",
            "arguments": {"path": "samples/sample.elf"},
            "root": root,
        }
    )
    assert good["ok"] is True and good["output"]["format"] == "ELF"
    assert good["output"]["size"] == len(SAMPLE_BYTES)

    for payload in (
        {
            "tool_name": "file_inspect",
            "arguments": {"path": "../outside.txt"},
            "root": root,
        },
        {
            "tool_name": "file_inspect",
            "arguments": {"path": str(tmp_path / "outside.txt")},
            "root": root,
        },
        {"tool_name": "shell", "arguments": {"cmd": "whoami"}, "root": root},
        {
            "tool_name": "file_inspect",
            "arguments": {"path": "samples/sample.elf"},
            "root": "relative/root",
        },
        {
            "tool_name": "file_inspect",
            "arguments": {"path": "samples/sample.elf"},
            "root": root,
            "extra": "ignored?",
        },
    ):
        assert run(payload)["ok"] is False, payload


# ----------------------------------------------------------------------
# crash recovery and atomic rollback
# ----------------------------------------------------------------------
def _add_trigger(env: Env, name: str, event_type: str) -> None:
    env.execute_sql(
        f"CREATE TRIGGER {name} BEFORE INSERT ON events "
        f"WHEN json_extract(NEW.body, '$.event_type') = '{event_type}' "
        f"BEGIN SELECT RAISE(ABORT, 'synthetic reject {event_type}'); END;"
    )


def _drop_trigger(env: Env, name: str) -> None:
    env.execute_sql(f"DROP TRIGGER IF EXISTS {name}")


def test_claim_event_failure_rolls_back_state(env):
    proposal = env.approved()
    _add_trigger(env, "reject_tool_started", "tool_started")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            env.service.execute(env.cid, proposal.proposal_id)
    finally:
        _drop_trigger(env, "reject_tool_started")
    stored = env.service.get(env.cid, proposal.proposal_id)
    assert stored.status == "approved"  # state row rolled back with the event
    assert stored.execution_id is None
    assert stored.started_at is None
    assert "tool_started" not in env.event_types()
    assert env.store.verify(env.cid)["valid"]


def test_finalize_event_failure_rolls_back_artifact_and_finish(env):
    proposal = env.approved()
    _add_trigger(env, "reject_tool_finished", "tool_finished")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            env.service.execute(env.cid, proposal.proposal_id)
    finally:
        _drop_trigger(env, "reject_tool_finished")
    stored = env.service.get(env.cid, proposal.proposal_id)
    # The claim committed atomically with tool_started; finalization rolled back.
    assert stored.status == "running"
    assert "tool_finished" not in env.event_types()
    assert "artifact_added" not in env.event_types()
    assert env.artifact_rows() == []
    assert env.store.verify(env.cid)["valid"]

    recovered = env.service.recover_interrupted()
    assert recovered == {"recovered": 1}
    stored = env.service.get(env.cid, proposal.proposal_id)
    assert stored.status == "failed"
    assert stored.error == "interrupted_during_execution"
    finished = env.events()[-1]
    assert finished.event_type == "tool_finished"
    assert finished.payload["recovered"] is True
    assert finished.payload["status"] == "failed"
    assert env.store.verify(env.cid)["valid"]


def test_artifact_event_failure_rolls_back_metadata(env):
    proposal = env.approved()
    _add_trigger(env, "reject_artifact_added", "artifact_added")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            env.service.execute(env.cid, proposal.proposal_id)
    finally:
        _drop_trigger(env, "reject_artifact_added")
    assert env.service.get(env.cid, proposal.proposal_id).status == "running"
    assert env.artifact_rows() == []
    assert "artifact_added" not in env.event_types()
    assert "tool_finished" not in env.event_types()
    env.service.recover_interrupted()
    assert env.service.get(env.cid, proposal.proposal_id).status == "failed"


def test_recover_interrupted_running_claim(env):
    proposal = env.approved()
    execution_id = str(uuid.uuid4())
    event = env.store.append(
        env.cid,
        "tool",
        "tool_started",
        {
            "proposal_id": proposal.proposal_id,
            "execution_id": execution_id,
            "tool_name": "file_inspect",
        },
    )
    env.execute_sql(
        "UPDATE tool_proposals SET status='running', execution_id=?, started_at=?, "
        "started_event_id=? WHERE proposal_id=?",
        (execution_id, now(), event.event_id, proposal.proposal_id),
    )
    assert env.service.recover_interrupted() == {"recovered": 1}
    stored = env.service.get(env.cid, proposal.proposal_id)
    assert stored.status == "failed"
    assert stored.error == "interrupted_during_execution"
    assert stored.finished_event_id
    finished = env.events()[-1]
    assert finished.event_type == "tool_finished"
    assert finished.payload["recovered"] is True
    assert finished.payload["execution_id"] == execution_id
    assert env.service.recover_interrupted() == {"recovered": 0}
    assert env.store.verify(env.cid)["valid"]


# ----------------------------------------------------------------------
# HTTP surface (Lead-wired endpoints)
# ----------------------------------------------------------------------
def _api_challenge(client, level="A2"):
    response = client.post(
        "/api/challenges",
        json={"name": "Synthetic tools", "category": "Misc", "ai_usage_level": level},
    )
    assert response.status_code == 201, response.text
    return response.json()["challenge_id"]


def _api_write_file(client, cid, relative="samples/sample.elf"):
    root = client.app.state.workspace.challenge(cid)
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(SAMPLE_BYTES)


def test_api_split_approve_and_execute(tmp_path):
    with TestClient(create_app(tmp_path / "data")) as client:
        cid = _api_challenge(client)
        _api_write_file(client, cid)
        assert len(client.get("/api/tools").json()["tools"]) == 7
        created = client.post(
            f"/api/challenges/{cid}/tool-proposals",
            json={
                "tool_name": "file_inspect",
                "arguments": {"path": "samples/sample.elf"},
                "reason": "synthetic API proposal",
            },
        )
        assert created.status_code == 201, created.text
        pid = created.json()["proposal_id"]
        assert created.json()["status"] == "pending"

        too_early = client.post(
            f"/api/challenges/{cid}/tool-proposals/{pid}/execute"
        )
        assert too_early.status_code == 409

        approved = client.post(
            f"/api/challenges/{cid}/tool-proposals/{pid}/approve",
            json={"approving_user": "synthetic-user", "note": "approve fixture"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        assert approved.json()["approval_id"]

        executed = client.post(
            f"/api/challenges/{cid}/tool-proposals/{pid}/execute"
        )
        assert executed.status_code == 200, executed.text
        result = executed.json()
        assert result["status"] == "succeeded"
        assert result["output_artifact_id"]
        assert result["output_sha256"]
        assert result["execution_id"]
        assert result["artifact_ids"] == [result["output_artifact_id"]]

        events = client.get(f"/api/challenges/{cid}/events").json()
        assert [event["event_type"] for event in events] == [
            "tool_proposed",
            "tool_approved",
            "tool_started",
            "artifact_added",
            "tool_finished",
        ]
        assert client.get(f"/api/challenges/{cid}/integrity").json()["valid"]


def test_api_tool_endpoints_deny_a1_and_isolate_challenges(tmp_path):
    with TestClient(create_app(tmp_path / "data")) as client:
        a1 = _api_challenge(client, "A1")
        _api_write_file(client, a1)
        denied = client.post(
            f"/api/challenges/{a1}/tool-proposals",
            json={
                "tool_name": "file_inspect",
                "arguments": {"path": "samples/sample.elf"},
                "reason": "denied",
            },
        )
        assert denied.status_code == 403

        cid = _api_challenge(client)
        _api_write_file(client, cid)
        pid = client.post(
            f"/api/challenges/{cid}/tool-proposals",
            json={
                "tool_name": "sha256",
                "arguments": {"path": "samples/sample.elf"},
                "reason": "isolation fixture",
            },
        ).json()["proposal_id"]
        other = _api_challenge(client)
        assert client.get(f"/api/challenges/{other}/tool-proposals").json() == []
        assert (
            client.get(
                f"/api/challenges/{other}/tool-proposals/{pid}"
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/challenges/{other}/tool-proposals/{pid}/approve",
                json={"approving_user": "synthetic-user"},
            ).status_code
            == 404
        )
