import hashlib
import os
import shutil
import sqlite3
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import get_args
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from .artifacts import (
    DEFAULT_MAX_ARTIFACT_BYTES,
    ArtifactIntegrityError,
    ArtifactPathError,
    ArtifactStore,
    ArtifactTooLarge,
    detect_media_type,
)
from .export import build_export_archive
from .imports import (
    ImportIssue,
    ImportLimits,
    ManifestIntegrityError,
    ZipValidationError,
    bind_manifest,
    discard_staged_import,
    import_directory,
    imported_file,
    install_staged_import,
    read_manifest,
    record_from_event,
    scan_imports,
    stage_archive,
)
from .models import (
    ArtifactView,
    Challenge,
    ChallengeCreate,
    Event,
    EvidenceKind,
    FlagConfirmationCreate,
    ImportDetail,
    ImportRecord,
    ImportResult,
    ManualOperationCreate,
    ModelServiceNetworkUpdate,
    ModelServiceStatus,
    ModelServiceUpdate,
    NoteCreate,
    Project,
    ProjectUpdate,
    ToolDecisionRequest,
    ToolProposalCreate,
    ToolProposalRecord,
    WriteupDraft,
    WriteupDraftSave,
    WriteupPreview,
)
from .project import ProjectNotConfiguredError, ProjectStore, ProjectValidationError
from .writeups import (
    DEFAULT_MAX_WRITEUP_BYTES,
    WriteupConflictError,
    WriteupIntegrityError,
    WriteupNotFoundError,
    WriteupStore,
    WriteupTooLargeError,
    WriteupValidationError,
)
from .store import Store
from .workspace import Workspace
from .writeup import build_writeup_preview
from .model_calls import ModelCallJournal, ModelCallRecords, disclosure_calls, safe_error_code
from .ai_assistant import AIChatRequest, AIChatResponse, AIConnectivityTestRequest, AIConnectivityTestResponse, ask_challenge, model_network_enabled, redact_sensitive, test_deepseek_connection
from .ai_policy import (
    attachment_content_allowed,
    model_calls_allowed,
    tool_execution_allowed,
    tool_proposals_allowed,
)
from .providers import ProviderError
from .model_service import ModelServiceError, ModelServiceSettings
from .tool_registry import ToolValidationError, catalog
from .tool_system import (
    ToolConflict,
    ToolNotFound,
    ToolPermissionError,
    ToolService,
)

# Multipart framing (boundary, per-part headers, filename) is allowed on top of
# the declared upload limit; the file bytes themselves stay capped exactly.
MULTIPART_OVERHEAD_BYTES = 64 * 1024
DEFAULT_RULES_MAX_BYTES = 50 * 1024 * 1024
EVIDENCE_KINDS = frozenset(get_args(EvidenceKind))


class ArtifactBodyTooLarge(Exception):
    """Raised by the ASGI body limiter when a chunked upload exceeds the cap."""


def _declared_content_length(scope) -> int | None:
    for name, value in scope.get("headers", ()):
        if name.lower() == b"content-length":
            text = value.decode("latin-1").strip()
            return int(text) if text.isdigit() else None
    return None


class ArtifactBodyLimitMiddleware:
    """Reject oversized multipart upload bodies before they are buffered.

    FastAPI/Starlette parse and spool the whole multipart body before the
    endpoint can enforce the per-file byte limit.  This ASGI middleware checks
    the declared Content-Length first and also counts chunked bodies, so a
    request that cannot fit the limit is refused without being buffered.
    """

    def __init__(self, app, max_body_bytes: int):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send):
        if (
            scope.get("type") != "http"
            or scope.get("method") != "POST"
            or not self._is_limited_upload(scope.get("path", ""))
        ):
            await self.app(scope, receive, send)
            return
        declared = _declared_content_length(scope)
        if declared is not None and declared > self.max_body_bytes:
            response = JSONResponse(
                {"detail": "Upload exceeds the size limit"}, status_code=413
            )
            await response(scope, receive, send)
            return
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise ArtifactBodyTooLarge
            return message

        await self.app(scope, limited_receive, send)

    @staticmethod
    def _is_limited_upload(path: str) -> bool:
        if path == "/api/project/rules":
            return True
        return path.startswith("/api/challenges/") and (
            path.endswith("/artifacts") or path.endswith("/imports")
        )


async def _artifact_body_too_large(request, exc):
    return JSONResponse({"detail": "Upload exceeds the size limit"}, status_code=413)


WRITEUP_JSON_OVERHEAD_BYTES = 64 * 1024


class WriteupBodyLimitMiddleware:
    """Cap Writeup draft PUT bodies by declared and actual received bytes.

    The 1 MiB limit applies to the UTF-8 content, not the JSON envelope, so a
    small fixed overhead is allowed.  A chunked request has no Content-Length,
    so the body is buffered up to the cap before routing and replayed to the
    application.  Exceeding the cap is answered with 413 directly: raising an
    exception during body parsing would be converted to a generic 400 by
    FastAPI's request body reader.
    """

    def __init__(self, app, max_body_bytes: int):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send):
        if (
            scope.get("type") != "http"
            or scope.get("method") != "PUT"
            or not self._is_writeup_draft(scope.get("path", ""))
        ):
            await self.app(scope, receive, send)
            return
        declared = _declared_content_length(scope)
        if declared is not None and declared > self.max_body_bytes:
            response = JSONResponse(
                {"detail": "Writeup request body exceeds the size limit"},
                status_code=413,
            )
            await response(scope, receive, send)
            return
        chunks: list[bytes] = []
        received = 0
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                sent_disconnect = False

                async def disconnect_receive():
                    nonlocal sent_disconnect
                    sent_disconnect = True
                    return {"type": "http.disconnect"}

                await self.app(scope, disconnect_receive, send)
                return
            chunk = message.get("body", b"")
            received += len(chunk)
            if received > self.max_body_bytes:
                response = JSONResponse(
                    {"detail": "Writeup request body exceeds the size limit"},
                    status_code=413,
                )
                await response(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        replayed = False

        async def replay_receive():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)

    @staticmethod
    def _is_writeup_draft(path: str) -> bool:
        return path.startswith("/api/challenges/") and path.endswith("/writeup/draft")


def _positive(configured: int | None, env_name: str, default: int) -> int:
    if configured is None:
        raw = os.environ.get(env_name)
        configured = int(raw) if raw else default
    if configured <= 0:
        raise ValueError(f"{env_name} must be positive")
    return configured


def _content_disposition(
    filename: str, fallback_id: str, *, disposition: str = "attachment"
) -> str:
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace('"', "_")
    return (
        f'{disposition}; filename="{ascii_name or fallback_id}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )


def _parse_claim(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, f"{field} must be an ISO 8601 timestamp") from None
    return text


def _claim_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _cleanup_export(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def create_app(
    data_root: Path | None = None,
    max_artifact_bytes: int | None = None,
    rules_max_bytes: int | None = None,
    max_writeup_bytes: int | None = None,
    import_limits: ImportLimits | None = None,
) -> FastAPI:
    root = data_root or Path(os.environ.get("CTF_DATA_DIR", "../.local-data"))
    artifact_limit = _positive(
        max_artifact_bytes, "CTF_MAX_ARTIFACT_BYTES", DEFAULT_MAX_ARTIFACT_BYTES
    )
    rules_limit = _positive(
        rules_max_bytes, "CTF_RULES_MAX_BYTES", DEFAULT_RULES_MAX_BYTES
    )
    writeup_limit = _positive(
        max_writeup_bytes, "CTF_MAX_WRITEUP_BYTES", DEFAULT_MAX_WRITEUP_BYTES
    )
    import_budget = import_limits or ImportLimits.from_env()
    max_upload_body = max(artifact_limit, rules_limit) + MULTIPART_OVERHEAD_BYTES

    @asynccontextmanager
    async def lifespan(app):
        app.state.model_calls = ModelCallJournal(root / "model-audit.sqlite3")
        app.state.model_settings = ModelServiceSettings(root)
        app.state.store = Store(root / "workbench.sqlite3")
        app.state.workspace = Workspace(root / "challenges")
        app.state.artifacts = ArtifactStore(
            root / "artifacts", max_bytes=artifact_limit
        )
        rules_store = ArtifactStore(root / "artifacts", max_bytes=rules_limit)
        app.state.project = ProjectStore(root, rules_store)
        app.state.writeups = WriteupStore(root / "writeups", max_bytes=writeup_limit)
        app.state.import_limits = import_budget
        app.state.tools = ToolService(
            app.state.store,
            app.state.workspace,
            app.state.artifacts,
            app.state.model_calls,
        )
        # A crash may leave a proposal in "running"; reconcile it before serving
        # requests so a new client never observes an execution that cannot finish.
        app.state.tools.recover_interrupted()
        app.state.tools.expire_stale()
        yield

    app = FastAPI(title="CTF Agent Workbench", version="0.3.0", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        path = request.url.path
        if path.endswith("/ai/chat") or path in {
            "/api/model/test",
            "/api/model/settings",
        }:
            return JSONResponse(status_code=422, content={"detail": [
                {"loc": [redact_sensitive(part) if isinstance(part, str) else part for part in item["loc"]],
                 "type": item["type"], "msg": redact_sensitive(item["msg"])}
                for item in error.errors()
            ]})
        return await request_validation_exception_handler(request, error)
    app.state.max_artifact_bytes = artifact_limit
    app.state.rules_max_bytes = rules_limit
    app.state.max_writeup_bytes = writeup_limit
    app.state.import_limits = import_budget
    app.state.artifact_lock = threading.Lock()
    app.add_middleware(
        ArtifactBodyLimitMiddleware,
        max_body_bytes=max_upload_body,
    )
    app.add_middleware(
        WriteupBodyLimitMiddleware,
        max_body_bytes=writeup_limit + WRITEUP_JSON_OVERHEAD_BYTES,
    )
    app.add_exception_handler(ArtifactBodyTooLarge, _artifact_body_too_large)

    def exists(cid):
        try:
            return app.state.store.get(cid)
        except KeyError:
            raise HTTPException(404, "Challenge not found") from None

    def artifact_or_404(cid: str, artifact_id: str) -> ArtifactView:
        exists(cid)
        try:
            return app.state.store.artifact_view(cid, artifact_id)
        except KeyError:
            # Unknown artifact and artifact of another challenge are both 404
            # so the API does not confirm the existence of foreign evidence.
            raise HTTPException(404, "Artifact not found") from None

    def project_or_404() -> Project:
        project = app.state.project.get()
        if project is None:
            raise HTTPException(404, "Project is not configured")
        return project

    @app.get("/api/health")
    def health():
        limits = app.state.import_limits
        return {
            "status": "ok",
            # Arbitrary shell/code execution remains disabled; only the fixed
            # read-only tool catalog can be approved and executed.
            "execution_enabled": False,
            "read_only_tool_execution_enabled": True,
            "tool_count": len(catalog()),
            "model_network_enabled": model_network_enabled(
                app.state.model_settings
            ),
            "artifact_max_bytes": app.state.max_artifact_bytes,
            "rules_max_bytes": app.state.rules_max_bytes,
            "writeup_max_bytes": app.state.max_writeup_bytes,
            "manual_execution_mode": "manual_external",
            "import_limits": {
                "max_files": limits.max_files,
                "max_file_bytes": limits.max_file_bytes,
                "max_total_bytes": limits.max_total_bytes,
                "max_compression_ratio": limits.max_compression_ratio,
            },
        }

    # ------------------------------------------------------------------
    # project configuration and competition rules
    # ------------------------------------------------------------------
    @app.get("/api/project", response_model=Project)
    def get_project():
        return project_or_404()

    @app.put("/api/project", response_model=Project)
    def put_project(body: ProjectUpdate):
        try:
            return app.state.project.update(body)
        except ProjectValidationError as error:
            raise HTTPException(422, str(error)) from None

    @app.post("/api/project/rules", response_model=Project)
    def upload_rules(file: UploadFile = File(...)):
        try:
            with app.state.artifact_lock:
                project = app.state.project.ingest_rules(
                    file.file, filename=file.filename
                )
        except ArtifactTooLarge:
            raise HTTPException(413, "Rules file exceeds the size limit") from None
        except ProjectNotConfiguredError as error:
            raise HTTPException(409, str(error)) from None
        except ProjectValidationError:
            raise HTTPException(500, "Project configuration is unreadable") from None
        except OSError:
            raise HTTPException(500, "Rules file storage failed") from None
        finally:
            file.file.close()
        return project

    @app.get("/api/project/rules/content")
    def rules_content():
        try:
            project, data = app.state.project.read_rules()
        except ProjectNotConfiguredError as error:
            raise HTTPException(404, str(error)) from None
        except (ArtifactIntegrityError, ArtifactPathError):
            raise HTTPException(409, "Rules file failed its integrity check") from None
        media_type = detect_media_type(data[:4096])
        return Response(
            content=data,
            media_type=media_type,
            headers={
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": _content_disposition(
                    project.rules_filename or "rules.pdf", project.project_id
                ),
            },
        )

    # ------------------------------------------------------------------
    # challenges
    # ------------------------------------------------------------------
    @app.get("/api/challenges", response_model=list[Challenge])
    def challenges():
        return app.state.store.challenges()

    @app.post("/api/challenges", response_model=Challenge, status_code=201)
    def create(body: ChallengeCreate):
        values = body.model_dump()
        if values.get("competition_name") is None:
            project = app.state.project.get()
            if project is not None and project.competition_name:
                values["competition_name"] = project.competition_name
        challenge = Challenge(**values)
        app.state.workspace.challenge(challenge.challenge_id).mkdir()
        app.state.store.create(challenge)
        return challenge

    @app.get("/api/challenges/{cid}/events", response_model=list[Event])
    def events(cid: str):
        exists(cid)
        return app.state.store.events(cid)

    @app.post("/api/challenges/{cid}/notes", response_model=Event, status_code=201)
    def note(cid: str, body: NoteCreate):
        exists(cid)
        if body.correction_of and body.correction_of not in {
            e.event_id for e in app.state.store.events(cid)
        }:
            raise HTTPException(422, "Correction must reference an existing event")
        return app.state.store.append(cid, "user", "note", body.model_dump())

    @app.get("/api/challenges/{cid}/integrity")
    def integrity(cid: str):
        exists(cid)
        return app.state.store.verify(cid)

    # ------------------------------------------------------------------
    # evidence artifacts
    # ------------------------------------------------------------------
    @app.post(
        "/api/challenges/{cid}/artifacts",
        response_model=ArtifactView,
        status_code=201,
    )
    def upload_artifact(
        cid: str,
        response: Response,
        file: UploadFile = File(...),
        evidence_kind: str | None = Form(default=None),
        capture_time_claim: str | None = Form(default=None),
    ) -> ArtifactView:
        exists(cid)
        if evidence_kind is not None and evidence_kind not in EVIDENCE_KINDS:
            raise HTTPException(
                422,
                "evidence_kind must be one of: " + ", ".join(sorted(EVIDENCE_KINDS)),
            )
        claim = _parse_claim(capture_time_claim, "capture_time_claim")
        artifacts: ArtifactStore = app.state.artifacts
        # A single-process local service serialises blob installation, metadata
        # commit, and orphan cleanup so a failed upload cannot race a concurrent
        # upload of the same content.  Cross-process concurrent ingestion of one
        # data directory is not supported (documented limitation).
        with app.state.artifact_lock:
            try:
                ingested = artifacts.ingest(file.file, filename=file.filename)
            except ArtifactTooLarge:
                raise HTTPException(413, "Artifact exceeds the size limit") from None
            except ArtifactPathError:
                raise HTTPException(400, "Invalid artifact storage path") from None
            except OSError:
                raise HTTPException(500, "Artifact storage failed") from None
            finally:
                file.file.close()

            def discard_orphan_blob() -> None:
                # Best-effort compensation: keep the blob when any committed
                # artifact still references it.
                try:
                    if app.state.store.count_artifacts_with_sha(ingested.sha256) == 0:
                        artifacts.discard(ingested.sha256)
                except Exception:
                    pass

            try:
                artifact, event = app.state.store.add_artifact(
                    cid,
                    sha256=ingested.sha256,
                    size=ingested.size,
                    media_type=ingested.media_type,
                    original_filename=ingested.original_filename,
                    evidence_kind=evidence_kind,
                    capture_time_claim=claim,
                )
            except sqlite3.Error:
                discard_orphan_blob()
                raise HTTPException(
                    500, "Artifact metadata persistence failed; no record was created"
                ) from None
            except Exception:
                discard_orphan_blob()
                raise HTTPException(
                    500, "Artifact metadata persistence failed; no record was created"
                ) from None
        if event is None:
            response.status_code = 200
            response.headers["X-Artifact-Deduplicated"] = "true"
        else:
            response.headers["X-Artifact-Deduplicated"] = "false"
        return app.state.store.artifact_view(cid, artifact.artifact_id)

    @app.get("/api/challenges/{cid}/artifacts", response_model=list[ArtifactView])
    def list_artifacts(cid: str):
        exists(cid)
        return app.state.store.artifact_views(cid)

    @app.get(
        "/api/challenges/{cid}/artifacts/{artifact_id}",
        response_model=ArtifactView,
    )
    def artifact_metadata(cid: str, artifact_id: str):
        return artifact_or_404(cid, artifact_id)

    @app.get("/api/challenges/{cid}/artifacts/{artifact_id}/content")
    def download_artifact(cid: str, artifact_id: str):
        artifact = artifact_or_404(cid, artifact_id)
        try:
            data = app.state.artifacts.read_verified(artifact.sha256)
        except (ArtifactIntegrityError, ArtifactPathError):
            raise HTTPException(
                409, "Artifact content failed its integrity check"
            ) from None
        return Response(
            content=data,
            media_type=artifact.media_type,
            headers={
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": _content_disposition(
                    artifact.original_filename, artifact.artifact_id
                ),
            },
        )

    @app.get("/api/challenges/{cid}/artifacts/{artifact_id}/integrity")
    def artifact_integrity(cid: str, artifact_id: str):
        artifact = artifact_or_404(cid, artifact_id)
        return {
            "artifact_id": artifact.artifact_id,
            "sha256": artifact.sha256,
            "valid": app.state.artifacts.verify(artifact.sha256),
        }

    # ------------------------------------------------------------------
    # challenge ZIP import
    # ------------------------------------------------------------------
    @app.post(
        "/api/challenges/{cid}/imports",
        response_model=ImportResult,
        status_code=201,
    )
    def import_challenge(cid: str, file: UploadFile = File(...)):
        exists(cid)
        workspace_challenge = app.state.workspace.challenge(cid)
        limits: ImportLimits = app.state.import_limits
        artifacts: ArtifactStore = app.state.artifacts
        with app.state.artifact_lock:
            try:
                ingested = artifacts.ingest(file.file, filename=file.filename)
            except ArtifactTooLarge:
                raise HTTPException(
                    413, "Archive exceeds the artifact size limit"
                ) from None
            except ArtifactPathError:
                raise HTTPException(400, "Invalid artifact storage path") from None
            except OSError:
                raise HTTPException(500, "Artifact storage failed") from None
            finally:
                file.file.close()

            def discard_blob() -> None:
                try:
                    if app.state.store.count_artifacts_with_sha(ingested.sha256) == 0:
                        artifacts.discard(ingested.sha256)
                except Exception:
                    pass

            try:
                data = artifacts.read_verified(ingested.sha256)
            except (ArtifactIntegrityError, ArtifactPathError):
                discard_blob()
                raise HTTPException(
                    500, "Uploaded archive could not be read back"
                ) from None
            try:
                staged = stage_archive(
                    data,
                    challenge_id=cid,
                    workspace_challenge=workspace_challenge,
                    limits=limits,
                )
            except ZipValidationError as error:
                discard_blob()
                raise HTTPException(422, str(error)) from None
            except OSError:
                discard_blob()
                raise HTTPException(500, "Archive extraction failed") from None
            try:
                artifact, _artifact_event = app.state.store.add_artifact(
                    cid,
                    sha256=ingested.sha256,
                    size=ingested.size,
                    media_type=ingested.media_type,
                    original_filename=ingested.original_filename,
                    evidence_kind="challenge_archive",
                )
            except Exception:
                discard_staged_import(staged)
                discard_blob()
                raise HTTPException(
                    500, "Artifact metadata persistence failed"
                ) from None
            installed: Path | None = None
            try:
                manifest = install_staged_import(
                    staged,
                    original_artifact_id=artifact.artifact_id,
                    original_filename=ingested.original_filename,
                )
                installed = workspace_challenge / "imports" / manifest.import_id
                event = app.state.store.append(
                    cid,
                    "user",
                    "challenge_imported",
                    manifest.payload(),
                    artifact_ids=(artifact.artifact_id,),
                )
            except Exception:
                if installed is not None:
                    shutil.rmtree(installed, ignore_errors=True)
                discard_staged_import(staged)
                raise HTTPException(
                    500, "Import could not be completed and was not recorded"
                ) from None
        view = app.state.store.artifact_view(cid, artifact.artifact_id)
        return ImportResult(
            **manifest.detail().model_dump(),
            original_artifact=view,
            import_event_id=event.event_id,
        )

    @app.get("/api/challenges/{cid}/imports", response_model=list[ImportRecord])
    def imports_list(cid: str):
        exists(cid)
        workspace_challenge = app.state.workspace.challenge(cid)
        events = app.state.store.events(cid)
        if not app.state.store.verify(cid).get("valid"):
            raise HTTPException(
                409,
                "Event chain integrity check failed; import manifests are not trusted",
            )
        manifests, issues = scan_imports(workspace_challenge, events, cid)
        records = [manifest.record() for manifest in manifests]
        events_by_import = {
            event.payload.get("import_id"): event
            for event in events
            if event.event_type == "challenge_imported"
        }
        for issue in issues:
            event = events_by_import.get(issue.import_id)
            if event is not None:
                records.append(record_from_event(event, cid, issue.reason))
            else:
                records.append(
                    ImportRecord(
                        import_id=issue.import_id,
                        challenge_id=cid,
                        original_artifact_id="",
                        original_filename="",
                        extracted_file_count=0,
                        total_uncompressed_size=0,
                        warnings=[],
                        created_at="",
                        manifest_sha256="",
                        manifest_verified=False,
                        integrity_error=issue.reason,
                    )
                )
        return records

    def verified_import_or_409(cid: str, import_id: str):
        """Return only a self-verified, event-bound manifest or raise 404/409."""
        workspace_challenge = app.state.workspace.challenge(cid)
        if not app.state.store.verify(cid).get("valid"):
            raise HTTPException(
                409,
                "Event chain integrity check failed; import manifests are not trusted",
            )
        events = app.state.store.events(cid)
        try:
            directory = import_directory(workspace_challenge, import_id)
        except KeyError:
            raise HTTPException(404, "Import not found") from None
        try:
            manifest = read_manifest(directory)
            bind_manifest(manifest, events, cid)
        except ManifestIntegrityError as error:
            raise HTTPException(409, str(error)) from None
        return manifest

    @app.get(
        "/api/challenges/{cid}/imports/{import_id}",
        response_model=ImportDetail,
    )
    def import_detail(cid: str, import_id: str):
        exists(cid)
        return verified_import_or_409(cid, import_id).detail()

    @app.get("/api/challenges/{cid}/imports/{import_id}/files/{relative_path:path}")
    def import_file(cid: str, import_id: str, relative_path: str):
        exists(cid)
        workspace_challenge = app.state.workspace.challenge(cid)
        manifest = verified_import_or_409(cid, import_id)
        try:
            target, entry = imported_file(workspace_challenge, manifest, relative_path)
        except KeyError:
            raise HTTPException(404, "Imported file not found") from None
        try:
            data = target.read_bytes()
        except OSError:
            raise HTTPException(404, "Imported file not found") from None
        # Re-verify the delivered bytes against the verified manifest; a
        # modified, truncated or replaced file is never returned to the client.
        if len(data) != entry.size or hashlib.sha256(data).hexdigest() != entry.sha256:
            raise HTTPException(
                409, "Imported file failed its integrity check"
            ) from None
        filename = target.name
        return Response(
            content=data,
            media_type=detect_media_type(data[:4096]),
            headers={
                "X-Content-Type-Options": "nosniff",
                "X-Imported-File-Integrity": "sha256-verified",
                "Content-Disposition": _content_disposition(
                    filename, manifest.import_id, disposition="inline"
                ),
            },
        )

    # ------------------------------------------------------------------
    # Explicitly confirmed AI-assisted analysis (suggestions only; no execution)
    @app.get("/api/model/status")
    def model_status():
        snapshot = app.state.model_settings.snapshot()
        return {
            "network_enabled": snapshot["network_enabled"],
            "provider": "deepseek",
            "model_id": redact_sensitive(snapshot["model_id"]),
            "credentials_configured": snapshot["key_configured"],
            "key_source": snapshot["key_source"],
            "key_storage_available": snapshot["key_storage_available"],
            "config_error": snapshot["config_error"],
            "execution_enabled": False,
        }

    # ------------------------------------------------------------------
    # Per-installation model service settings (API key never returned)
    # ------------------------------------------------------------------
    def model_settings_status() -> ModelServiceStatus:
        return ModelServiceStatus(**app.state.model_settings.snapshot())

    def settings_error(error: ModelServiceError):
        code = getattr(error, "code", "invalid_config")
        if code in {
            "credential_store_unavailable",
            "credential_store_error",
        }:
            raise HTTPException(503, {"code": code}) from None
        raise HTTPException(422, {"code": code}) from None

    @app.get("/api/model/settings", response_model=ModelServiceStatus)
    def get_model_settings():
        return model_settings_status()

    @app.put("/api/model/settings", response_model=ModelServiceStatus)
    def put_model_settings(body: ModelServiceUpdate):
        try:
            app.state.model_settings.save(
                base_url=body.base_url,
                model_id=body.model_id,
                api_key=body.api_key,
                clear_api_key=body.clear_api_key,
                authorize_env_key_custom_base_url=(
                    body.authorize_env_key_custom_base_url
                ),
            )
        except ModelServiceError as error:
            settings_error(error)
        except OSError:
            raise HTTPException(500, {"code": "settings_write_failed"}) from None
        return model_settings_status()

    @app.put("/api/model/network", response_model=ModelServiceStatus)
    def put_model_network(body: ModelServiceNetworkUpdate):
        try:
            app.state.model_settings.set_network(body.network_enabled)
        except OSError:
            raise HTTPException(500, {"code": "settings_write_failed"}) from None
        return model_settings_status()

    def model_call_records(cid=None):
        try:
            return app.state.model_calls.records(cid)
        except ProviderError:
            raise HTTPException(503, {"code": "audit_unavailable"}) from None

    @app.get("/api/model/calls", response_model=ModelCallRecords)
    def list_model_calls():
        return ModelCallRecords(calls=model_call_records())

    def model_error(error):
        status = {
            "missing_credentials": 503, "model_network_disabled": 503,
            "audit_unavailable": 503, "credential_store_unavailable": 503,
            "credential_store_error": 503, "config_invalid": 503,
            "env_key_custom_base_url_not_authorized": 403,
            "ai_usage_not_permitted": 403,
            "attachments_not_permitted": 403, "attachment_confirmation_required": 400,
            "rate_limited": 429, "timeout": 504, "context_limit_exceeded": 413,
            "evidence_selection_changed": 409, "context_integrity_error": 409,
            "unsupported_evidence": 422, "duplicate_evidence_selection": 422,
            "invalid_provider_configuration": 503,
        }.get(error.code, 502)
        return HTTPException(status, {"code": safe_error_code(error)})

    @app.post("/api/model/test", response_model=AIConnectivityTestResponse)
    async def model_connectivity_test(body: AIConnectivityTestRequest):
        if not body.confirm_synthetic_request:
            raise HTTPException(400, "Explicit confirmation is required for the synthetic connectivity request")
        if app.state.model_settings.config_error is not None:
            raise model_error(ProviderError("config_invalid"))
        if not model_network_enabled(app.state.model_settings):
            raise model_error(ProviderError("model_network_disabled"))
        try:
            response = await test_deepseek_connection(
                app.state.model_calls, settings=app.state.model_settings
            )
        except ProviderError as error:
            raise model_error(error) from None
        except Exception:
            raise HTTPException(502, {"code": "internal_error"}) from None
        return {
            "success": True,
            "provider": redact_sensitive(response.provider_id),
            "model_id": redact_sensitive(response.model_id),
            "call_id": response.audit_call_id,
            "sent_synthetic_content_only": True,
        }

    @app.post("/api/challenges/{cid}/ai/chat", response_model=AIChatResponse, status_code=201)
    async def ai_chat(cid: str, body: AIChatRequest):
        challenge = exists(cid)
        if not body.confirm_external_processing:
            raise HTTPException(400, "Explicit confirmation is required before challenge content is sent to the model")
        if body.consent_challenge_id != cid:
            raise HTTPException(
                409,
                "External-processing confirmation does not belong to this challenge",
            )
        if app.state.model_settings.config_error is not None:
            raise model_error(ProviderError("config_invalid"))
        if not model_network_enabled(app.state.model_settings):
            raise model_error(ProviderError("model_network_disabled"))
        if not model_calls_allowed(challenge.ai_usage_level):
            raise model_error(ProviderError("ai_usage_not_permitted"))
        if (
            (body.selected_files or body.selected_artifacts)
            and not attachment_content_allowed(challenge.ai_usage_level)
        ):
            raise model_error(ProviderError("attachments_not_permitted"))
        try:
            response, answer, included, scope, prepared = await ask_challenge(
                challenge=challenge,
                project=app.state.project.get(),
                store=app.state.store,
                workspace_challenge=app.state.workspace.challenge(cid),
                artifact_store=app.state.artifacts,
                body=body,
                journal=app.state.model_calls,
                tool_service=app.state.tools,
                settings=app.state.model_settings,
            )
        except ProviderError as error:
            raise model_error(error) from None
        except ValueError:
            raise model_error(ProviderError("context_integrity_error")) from None
        except Exception:
            raise HTTPException(502, {"code": "internal_error"}) from None
        provider_id = redact_sensitive(response.provider_id)
        model_id = redact_sensitive(response.model_id)
        # The answer event, the pending proposal rows and their tool_proposed
        # events are one transaction: an AI answer cannot claim a proposal that
        # was never durably recorded, and vice versa.
        try:
            with app.state.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                event = app.state.store.append_event(
                    db,
                    cid,
                    "agent",
                    "agent_message",
                    {
                        "provider_id": provider_id,
                        "model_id": model_id,
                        "question": redact_sensitive(body.question),
                        "answer": answer,
                        "included_files": included,
                        "consent_challenge_id": body.consent_challenge_id,
                        "call_id": response.audit_call_id,
                        "context_scope": scope,
                        "verification_status": "unverified_suggestion",
                        "execution_performed": False,
                        "tool_proposal_ids": [
                            item.get("proposal_id") for item in prepared
                        ],
                    },
                )
                proposals = (
                    app.state.tools.create_many(db, cid, prepared)
                    if prepared
                    else []
                )
        except Exception:
            raise HTTPException(503, {
                "code": "ai_response_persistence_failed",
                "message": f"模型已返回响应，但未能确认回答和工具申请已保存。调用 ID {response.audit_call_id}。",
                "call_id": response.audit_call_id,
                "response_status": "success",
            }) from None
        return AIChatResponse(
            event_id=event.event_id,
            answer=answer,
            call_id=response.audit_call_id,
            provider_id=provider_id,
            model_id=model_id,
            included_files=included,
            tool_proposals=proposals,
        )

    # manual execution records
    # ------------------------------------------------------------------
    @app.post(
        "/api/challenges/{cid}/manual-operations",
        response_model=Event,
        status_code=201,
    )
    def manual_operation(cid: str, body: ManualOperationCreate):
        exists(cid)
        started = _parse_claim(body.started_at_claim, "started_at_claim")
        finished = _parse_claim(body.finished_at_claim, "finished_at_claim")
        if (
            started is not None
            and finished is not None
            and _claim_datetime(finished) < _claim_datetime(started)
        ):
            raise HTTPException(
                422, "finished_at_claim must not be earlier than started_at_claim"
            )
        payload = {
            "command": body.command,
            "working_directory": body.working_directory,
            "purpose": body.purpose,
            "exit_code": body.exit_code,
            "result_note": body.result_note,
            "started_at_claim": started,
            "finished_at_claim": finished,
            "execution_mode": "manual_external",
            "execution_verified": False,
            "record_source": "user_manual_entry",
        }
        return app.state.store.append(cid, "user", "manual_operation_recorded", payload)

    # ------------------------------------------------------------------
    # Writeup draft and complete evidence export
    # ------------------------------------------------------------------
    def build_preview(
        cid: str,
        challenge: Challenge,
        *,
        events=None,
        integrity=None,
        calls=None,
        tool_proposals=None,
    ) -> WriteupPreview:
        if events is None:
            events = app.state.store.events(cid)
        if integrity is None:
            integrity = app.state.store.verify(cid)
        if calls is None:
            calls = disclosure_calls(events, model_call_records(cid))
        if tool_proposals is None:
            tool_proposals = app.state.tools.list(cid)
        artifacts = app.state.store.artifact_views(cid)
        project = app.state.project.get()
        return build_writeup_preview(
            challenge,
            events,
            artifacts,
            project,
            app.state.artifacts.read_verified,
            integrity,
            calls,
            tool_proposals=tool_proposals,
        )

    @app.get("/api/challenges/{cid}/writeup/preview", response_model=WriteupPreview)
    def writeup_preview(cid: str):
        challenge = exists(cid)
        return build_preview(cid, challenge)

    @app.get("/api/challenges/{cid}/writeup/draft", response_model=WriteupDraft)
    def get_writeup_draft(cid: str):
        exists(cid)
        try:
            return app.state.writeups.load(cid)
        except WriteupNotFoundError:
            raise HTTPException(404, "Writeup draft not found") from None
        except WriteupIntegrityError as error:
            raise HTTPException(409, str(error)) from None

    @app.put("/api/challenges/{cid}/writeup/draft", response_model=WriteupDraft)
    def save_writeup_draft(cid: str, body: WriteupDraftSave, response: Response):
        exists(cid)
        try:
            draft = app.state.writeups.save(cid, body)
        except WriteupTooLargeError as error:
            raise HTTPException(413, str(error)) from None
        except WriteupValidationError as error:
            raise HTTPException(422, str(error)) from None
        except WriteupIntegrityError as error:
            raise HTTPException(
                409,
                "Saved writeup cannot be updated safely: " + str(error),
            ) from None
        except WriteupConflictError as error:
            raise HTTPException(
                409,
                detail={
                    "message": (
                        "Writeup version conflict; reload the latest draft "
                        "before saving"
                    ),
                    "current": (
                        error.current.model_dump()
                        if error.current is not None
                        else None
                    ),
                },
            ) from None
        response.status_code = 201 if draft.version == 1 else 200
        return draft

    @app.get("/api/challenges/{cid}/export")
    def export_dossier(cid: str):
        challenge = exists(cid)
        workspace_challenge = app.state.workspace.challenge(cid)
        events = app.state.store.events(cid)
        integrity = app.state.store.verify(cid)
        # One snapshot feeds the preview, the ZIP, ai_disclosure.md and the
        # manifest, so all exported counts and records are internally consistent.
        calls = disclosure_calls(events, model_call_records(cid))
        tool_proposals = app.state.tools.list(cid)
        preview = build_preview(
            cid,
            challenge,
            events=events,
            integrity=integrity,
            calls=calls,
            tool_proposals=tool_proposals,
        )
        manifests, import_issues = scan_imports(workspace_challenge, events, cid)
        human_writeup: WriteupDraft | None = None
        writeup_integrity_error: str | None = None
        try:
            human_writeup = app.state.writeups.load(cid)
        except WriteupNotFoundError:
            human_writeup = None
        except (WriteupIntegrityError, WriteupValidationError) as error:
            human_writeup = None
            writeup_integrity_error = str(error)
        if not integrity.get("valid"):
            import_issues = [
                ImportIssue(
                    import_id=manifest.import_id,
                    reason=(
                        "Event chain integrity check failed; manifest binding is "
                        "not trusted"
                    ),
                )
                for manifest in manifests
            ] + import_issues
            manifests = []
        try:
            result = build_export_archive(
                data_root=root,
                challenge=challenge,
                project=app.state.project.get(),
                events=events,
                artifacts=app.state.store.artifact_views(cid),
                manifests=manifests,
                import_issues=import_issues,
                artifact_store=app.state.artifacts,
                workspace_challenge=workspace_challenge,
                generated_writeup_markdown=preview.markdown,
                human_writeup=human_writeup,
                writeup_integrity_error=writeup_integrity_error,
                completeness=preview.completeness,
                missing_requirements=preview.missing_requirements,
                writeup_warnings=preview.warnings,
                integrity=integrity,
                model_calls=calls,
                tool_proposals=tool_proposals,
            )
        except OSError:
            raise HTTPException(500, "Evidence archive export failed") from None
        return FileResponse(
            result.path,
            media_type="application/zip",
            filename=f"writeup-{cid}.zip",
            headers={"X-Dossier-Completeness": result.completeness},
            background=BackgroundTask(_cleanup_export, result.path),
        )

    # ------------------------------------------------------------------
    # fixed read-only local tools (human approval + explicit execution)
    # ------------------------------------------------------------------
    def require_tool_policy(challenge: Challenge):
        if not tool_proposals_allowed(challenge.ai_usage_level):
            raise HTTPException(403, {"code": "ai_usage_not_permitted"})
        if not tool_execution_allowed(challenge.ai_usage_level):
            raise HTTPException(403, {"code": "ai_usage_not_permitted"})

    def tool_call(action):
        try:
            return action()
        except ToolNotFound:
            raise HTTPException(404, "Tool proposal not found") from None
        except ToolPermissionError as error:
            raise HTTPException(
                403, {"code": getattr(error, "code", "ai_usage_not_permitted")}
            ) from None
        except ToolConflict as error:
            raise HTTPException(
                409,
                {
                    "message": str(error),
                    "status": error.status,
                    "code": getattr(error, "code", None),
                },
            ) from None
        except ToolValidationError as error:
            raise HTTPException(422, str(error)) from None
        except ProviderError as error:
            raise model_error(error) from None

    @app.get("/api/tools")
    def tools():
        return {
            "tools": catalog(),
            "execution_enabled": False,
            "read_only_tool_execution_enabled": True,
            "read_only": True,
            "requires_human_approval": True,
            "max_active_containers": 0,
        }

    @app.get(
        "/api/challenges/{cid}/tool-proposals",
        response_model=list[ToolProposalRecord],
    )
    def list_tool_proposals(cid: str):
        exists(cid)
        return app.state.tools.list(cid)

    @app.post(
        "/api/challenges/{cid}/tool-proposals",
        response_model=ToolProposalRecord,
        status_code=201,
    )
    def create_tool_proposal(cid: str, body: ToolProposalCreate):
        challenge = exists(cid)
        require_tool_policy(challenge)
        return tool_call(
            lambda: app.state.tools.propose(
                cid,
                tool_name=body.tool_name,
                arguments=body.arguments,
                reason=body.reason,
                proposed_by="user",
                model_call_id=body.model_call_id,
            )
        )

    @app.get(
        "/api/challenges/{cid}/tool-proposals/{pid}",
        response_model=ToolProposalRecord,
    )
    def get_tool_proposal(cid: str, pid: str):
        exists(cid)
        return tool_call(lambda: app.state.tools.get(cid, pid))

    @app.post(
        "/api/challenges/{cid}/tool-proposals/{pid}/approve",
        response_model=ToolProposalRecord,
    )
    def approve_tool_proposal(cid: str, pid: str, body: ToolDecisionRequest):
        challenge = exists(cid)
        require_tool_policy(challenge)
        return tool_call(
            lambda: app.state.tools.approve(
                cid, pid, user=body.approving_user, note=body.note
            )
        )

    @app.post(
        "/api/challenges/{cid}/tool-proposals/{pid}/execute",
        response_model=ToolProposalRecord,
    )
    def execute_tool_proposal(cid: str, pid: str):
        challenge = exists(cid)
        require_tool_policy(challenge)
        return tool_call(lambda: app.state.tools.execute(cid, pid))

    @app.post(
        "/api/challenges/{cid}/tool-proposals/{pid}/reject",
        response_model=ToolProposalRecord,
    )
    def reject_tool_proposal(cid: str, pid: str, body: ToolDecisionRequest):
        exists(cid)
        return tool_call(
            lambda: app.state.tools.reject(
                cid, pid, user=body.approving_user, note=body.note
            )
        )

    @app.post(
        "/api/challenges/{cid}/tool-proposals/{pid}/cancel",
        response_model=ToolProposalRecord,
    )
    def cancel_tool_proposal(cid: str, pid: str, body: ToolDecisionRequest):
        exists(cid)
        return tool_call(
            lambda: app.state.tools.cancel(
                cid, pid, user=body.approving_user, note=body.note
            )
        )

    # ------------------------------------------------------------------
    # human Flag confirmation (hash and length only, never plaintext)
    # ------------------------------------------------------------------
    @app.post(
        "/api/challenges/{cid}/flag-confirmation",
        response_model=Event,
        status_code=201,
    )
    def confirm_flag(cid: str, body: FlagConfirmationCreate):
        exists(cid)
        flag_digest = hashlib.sha256(body.flag.encode("utf-8")).hexdigest()
        return app.state.store.append(
            cid,
            "user",
            "flag_confirmed",
            {
                "flag_sha256": flag_digest,
                "flag_length": len(body.flag),
                "confirmed_by": body.confirmed_by,
                "note": body.note,
                "source": "manual_user_confirmation",
                "platform_verified": False,
            },
        )

    return app


app = create_app()
