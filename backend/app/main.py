import os
import sqlite3
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.responses import JSONResponse

from .artifacts import (
    DEFAULT_MAX_ARTIFACT_BYTES,
    ArtifactIntegrityError,
    ArtifactPathError,
    ArtifactStore,
    ArtifactTooLarge,
)
from .models import Artifact, Challenge, ChallengeCreate, Event, NoteCreate
from .store import Store
from .workspace import Workspace

# Multipart framing (boundary, per-part headers, filename) is allowed on top of
# the declared artifact limit; the file bytes themselves stay capped exactly.
MULTIPART_OVERHEAD_BYTES = 64 * 1024


class ArtifactBodyTooLarge(Exception):
    """Raised by the ASGI body limiter when a chunked upload exceeds the cap."""


def _declared_content_length(scope) -> int | None:
    for name, value in scope.get("headers", ()):
        if name.lower() == b"content-length":
            text = value.decode("latin-1").strip()
            return int(text) if text.isdigit() else None
    return None


class ArtifactBodyLimitMiddleware:
    """Reject oversized artifact upload bodies before multipart buffering.

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
            or not self._is_artifact_upload(scope.get("path", ""))
        ):
            await self.app(scope, receive, send)
            return
        declared = _declared_content_length(scope)
        if declared is not None and declared > self.max_body_bytes:
            response = JSONResponse(
                {"detail": "Artifact exceeds the size limit"}, status_code=413
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
    def _is_artifact_upload(path: str) -> bool:
        return path.startswith("/api/challenges/") and path.endswith("/artifacts")


async def _artifact_body_too_large(request, exc):
    return JSONResponse({"detail": "Artifact exceeds the size limit"}, status_code=413)


def _artifact_limit(configured: int | None) -> int:
    if configured is None:
        raw = os.environ.get("CTF_MAX_ARTIFACT_BYTES")
        configured = int(raw) if raw else DEFAULT_MAX_ARTIFACT_BYTES
    if configured <= 0:
        raise ValueError("max_artifact_bytes must be positive")
    return configured


def _content_disposition(filename: str, artifact_id: str) -> str:
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace('"', "_")
    return (
        f'attachment; filename="{ascii_name or artifact_id}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )


def create_app(
    data_root: Path | None = None, max_artifact_bytes: int | None = None
) -> FastAPI:
    root = data_root or Path(os.environ.get("CTF_DATA_DIR", "../.local-data"))
    artifact_limit = _artifact_limit(max_artifact_bytes)

    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(root / "workbench.sqlite3")
        app.state.workspace = Workspace(root / "challenges")
        app.state.artifacts = ArtifactStore(
            root / "artifacts", max_bytes=artifact_limit
        )
        yield

    app = FastAPI(title="CTF Agent Workbench", version="0.1.0", lifespan=lifespan)
    app.state.max_artifact_bytes = artifact_limit
    app.state.artifact_lock = threading.Lock()
    app.add_middleware(
        ArtifactBodyLimitMiddleware,
        max_body_bytes=artifact_limit + MULTIPART_OVERHEAD_BYTES,
    )
    app.add_exception_handler(ArtifactBodyTooLarge, _artifact_body_too_large)

    def exists(cid):
        try:
            return app.state.store.get(cid)
        except KeyError:
            raise HTTPException(404, "Challenge not found") from None

    def artifact_or_404(cid: str, artifact_id: str) -> Artifact:
        exists(cid)
        try:
            return app.state.store.artifact(cid, artifact_id)
        except KeyError:
            # Unknown artifact and artifact of another challenge are both 404
            # so the API does not confirm the existence of foreign evidence.
            raise HTTPException(404, "Artifact not found") from None

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "execution_enabled": False,
            "model_network_enabled": False,
            "artifact_max_bytes": app.state.max_artifact_bytes,
        }

    @app.get("/api/challenges", response_model=list[Challenge])
    def challenges():
        return app.state.store.challenges()

    @app.post("/api/challenges", response_model=Challenge, status_code=201)
    def create(body: ChallengeCreate):
        challenge = Challenge(**body.model_dump())
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

    @app.post(
        "/api/challenges/{cid}/artifacts",
        response_model=Artifact,
        status_code=201,
    )
    def upload_artifact(
        cid: str, response: Response, file: UploadFile = File(...)
    ) -> Artifact:
        exists(cid)
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
                )
            except sqlite3.Error:
                # The blob was written before metadata.  Remove it only when no
                # committed artifact references the same content, so shared blobs
                # and prior evidence are never destroyed by a failed upload.
                discard_orphan_blob()
                raise HTTPException(
                    500, "Artifact metadata persistence failed; no record was created"
                ) from None
            except Exception:
                # Any other persistence failure must not leave untracked bytes.
                discard_orphan_blob()
                raise HTTPException(
                    500, "Artifact metadata persistence failed; no record was created"
                ) from None
        if event is None:
            response.status_code = 200
            response.headers["X-Artifact-Deduplicated"] = "true"
        else:
            response.headers["X-Artifact-Deduplicated"] = "false"
        return artifact

    @app.get("/api/challenges/{cid}/artifacts", response_model=list[Artifact])
    def list_artifacts(cid: str):
        exists(cid)
        return app.state.store.artifacts(cid)

    @app.get("/api/challenges/{cid}/artifacts/{artifact_id}", response_model=Artifact)
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

    @app.get("/api/tools")
    def tools():
        return {"tools": [], "execution_enabled": False, "max_active_containers": 3}

    return app


app = create_app()
