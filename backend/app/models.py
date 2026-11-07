from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field


def uid() -> str:
    return str(uuid4())


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


Category = Literal["Misc", "Crypto", "Pwn", "Web", "Reverse"]
SolveStatus = Literal["unknown", "candidate", "verified"]
WriteupStatus = Literal["not_generated", "incomplete", "review_required", "complete"]


class Scope(Model):
    network_enabled: bool = False
    allowed_targets: list[str] = Field(default_factory=list)
    profile: Literal["XSWCTF"] = "XSWCTF"
    max_active_containers: int = Field(default=3, ge=0, le=3)


class ChallengeCreate(Model):
    name: str = Field(min_length=1, max_length=200)
    category: Category
    description: str = ""
    source: Literal["warmup", "practice", "competition"] = "practice"
    scope: Scope = Field(default_factory=Scope)


class Challenge(ChallengeCreate):
    challenge_id: str = Field(default_factory=uid)
    status: Literal["active", "archived"] = "active"
    solve_status: SolveStatus = "unknown"
    writeup_status: WriteupStatus = "not_generated"
    created_at: str = Field(default_factory=now)


EventType = Literal[
    "note",
    "agent_message",
    "hypothesis",
    "plan",
    "tool_proposed",
    "tool_approved",
    "tool_rejected",
    "tool_started",
    "tool_finished",
    "command_started",
    "command_finished",
    "artifact_added",
    "finding",
    "verification",
    "limitation",
    "model_call",
]


class Event(Model):
    event_id: str = Field(default_factory=uid)
    challenge_id: str
    sequence: int = Field(ge=1)
    occurred_at: str = Field(default_factory=now)
    actor: Literal["user", "agent", "tool", "system"]
    event_type: EventType
    payload: dict[str, Any]
    artifact_ids: list[str] = Field(default_factory=list)
    event_refs: list[str] = Field(default_factory=list)
    previous_event_hash: str
    event_hash: str = ""


class NoteCreate(Model):
    text: str = Field(min_length=1, max_length=10000)
    retrospective: bool = False
    correction_of: str | None = None


class Artifact(Model):
    artifact_id: str = Field(default_factory=uid)
    challenge_id: str
    sha256: str
    size: int = Field(ge=0)
    media_type: str
    original_filename: str
    ingested_at: str = Field(default_factory=now)
    source_event_id: str


class ToolProposal(Model):
    proposal_id: str = Field(default_factory=uid)
    call_id: str | None = None
    challenge_id: str
    tool_name: str
    arguments: dict[str, Any]
    scope: Scope
    proposed_at: str = Field(default_factory=now)


class ToolApproval(Model):
    proposal_id: str
    approving_user: str
    approved: bool
    decided_at: str = Field(default_factory=now)


class ToolStarted(Model):
    proposal_id: str
    executable: str
    executable_version: str | None = None
    argv: list[str]
    cwd: str
    environment_allowlist: list[str]
    started_at: str


class ToolExecutionResult(Model):
    proposal_id: str
    started_event_id: str
    finished_event_id: str
    ended_at: str
    exit_code: int | None
    timed_out: bool
    stdout_artifact_id: str
    stderr_artifact_id: str
    stdout_sha256: str
    stderr_sha256: str


class Finding(Model):
    text: str
    event_ids: list[str] = Field(min_length=1)
    artifact_ids: list[str] = Field(default_factory=list)


class Hypothesis(Model):
    text: str
    status: Literal["unverified", "supported", "refuted"] = "unverified"
    event_ids: list[str] = Field(default_factory=list)


class Verification(Finding):
    method: str
    result: Literal["unknown", "passed", "failed"]


class WriteupStatement(Model):
    kind: Literal["observation", "hypothesis", "conclusion", "retrospective", "gap"]
    text: str
    event_ids: list[str]
    artifact_ids: list[str] = Field(default_factory=list)


class Writeup(Model):
    challenge_id: str
    solve_status: SolveStatus
    writeup_status: WriteupStatus
    statements: list[WriteupStatement]
    generated_at: str = Field(default_factory=now)
