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
AiUsageLevel = Literal["A0", "A1", "A2", "unknown"]
EvidenceKind = Literal[
    "challenge_archive",
    "analysis",
    "execution",
    "execution_output",
    "flag_capture",
    "platform_verification",
    "source_code",
    "other",
]


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
    # Extensions are optional with defaults so historical challenge JSON that
    # predates them keeps loading and validating unchanged.
    ai_usage_level: AiUsageLevel = "unknown"
    score: int | None = Field(default=None, ge=0, le=1_000_000)
    competition_name: str | None = Field(default=None, max_length=200)


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
    "challenge_imported",
    "manual_operation_recorded",
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
    # A normal note is never treated as the core solving approach.  Only an
    # explicit kind="approach" note fills the Writeup approach section.
    kind: Literal["note", "approach"] = "note"


class Artifact(Model):
    artifact_id: str = Field(default_factory=uid)
    challenge_id: str
    sha256: str
    size: int = Field(ge=0)
    media_type: str
    original_filename: str
    ingested_at: str = Field(default_factory=now)
    source_event_id: str


class ArtifactView(Artifact):
    """Artifact plus evidence metadata stored on its artifact_added event.

    Historical artifacts whose event payload predates evidence classification
    default to ``other`` with no claimed capture time.
    """

    evidence_kind: EvidenceKind = "other"
    capture_time_claim: str | None = None
    source_event_type: str = "artifact_added"
    source_event_sequence: int | None = None


class Project(Model):
    project_id: str = Field(default_factory=uid)
    project_name: str = Field(min_length=1, max_length=200)
    competition_name: str = Field(default="", max_length=200)
    competition_type: str = Field(default="", max_length=100)
    rules_filename: str | None = None
    rules_sha256: str | None = None
    rules_size: int | None = Field(default=None, ge=0)
    rules_ingested_at: str | None = None
    ai_policy_summary: str = Field(default="", max_length=4000)


class ProjectUpdate(Model):
    project_name: str | None = Field(default=None, min_length=1, max_length=200)
    competition_name: str | None = Field(default=None, max_length=200)
    competition_type: str | None = Field(default=None, max_length=100)
    ai_policy_summary: str | None = Field(default=None, max_length=4000)


class ManualOperationCreate(Model):
    command: str = Field(min_length=1, max_length=4000)
    working_directory: str = Field(min_length=1, max_length=500)
    purpose: str = Field(min_length=1, max_length=500)
    exit_code: int | None = None
    result_note: str = Field(min_length=1, max_length=4000)
    started_at_claim: str | None = Field(default=None, max_length=64)
    finished_at_claim: str | None = Field(default=None, max_length=64)


class ImportFile(Model):
    relative_path: str = Field(min_length=1, max_length=1000)
    size: int = Field(ge=0)
    sha256: str
    media_type: str


class ImportRecord(Model):
    import_id: str
    challenge_id: str
    original_artifact_id: str
    original_filename: str
    extracted_file_count: int = Field(ge=0)
    total_uncompressed_size: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
    created_at: str
    manifest_sha256: str
    # Additive verification state: an unverified record is reported, never used.
    manifest_verified: bool = True
    integrity_error: str | None = None


class ImportDetail(ImportRecord):
    files: list[ImportFile] = Field(default_factory=list)


class ImportResult(ImportDetail):
    original_artifact: ArtifactView
    import_event_id: str


class WriteupPreview(Model):
    markdown: str
    missing_requirements: list[str] = Field(default_factory=list)
    event_count: int = Field(ge=0)
    artifact_count: int = Field(ge=0)
    completeness: Literal["complete", "incomplete"]
    warnings: list[str] = Field(default_factory=list)


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
