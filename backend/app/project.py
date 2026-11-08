"""Single local project configuration and competition rules file.

The project is one JSON document under the data root, written atomically.  The
rules file itself is stored in the existing content-addressed artifact store and
referenced by SHA-256, so repeating an upload of the same bytes deduplicates and
a tampered blob is detected on download.  No database migration is used.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from .artifacts import ArtifactStore
from .models import Project, ProjectUpdate, now


class ProjectNotConfiguredError(ValueError):
    """Raised when project-scoped data is requested before the project exists."""


class ProjectValidationError(ValueError):
    """Raised when a project update cannot produce a valid project."""


class ProjectStore:
    def __init__(self, root: Path, artifacts: ArtifactStore):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "project.json"
        self.artifacts = artifacts
        self.lock = threading.Lock()

    def get(self) -> Project | None:
        with self.lock:
            return self._read()

    def _read(self) -> Project | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return Project.model_validate(data)
        except (OSError, ValueError):
            raise ProjectValidationError(
                "Project configuration is unreadable or invalid"
            ) from None

    def update(self, body: ProjectUpdate) -> Project:
        with self.lock:
            current = self._read()
            if current is None:
                if not body.project_name:
                    raise ProjectValidationError(
                        "project_name is required to create the project"
                    )
                current = Project(project_name=body.project_name)
            changes = {
                name: value
                for name, value in (
                    ("project_name", body.project_name),
                    ("competition_name", body.competition_name),
                    ("competition_type", body.competition_type),
                    ("ai_policy_summary", body.ai_policy_summary),
                )
                if value is not None
            }
            updated = current.model_copy(update=changes)
            self._write(updated)
            return updated

    def ingest_rules(self, stream: BinaryIO, *, filename: str | None) -> Project:
        with self.lock:
            project = self._read()
            if project is None:
                raise ProjectNotConfiguredError(
                    "Create the project before uploading competition rules"
                )
            ingested = self.artifacts.ingest(stream, filename=filename)
            updated = project.model_copy(
                update={
                    "rules_filename": ingested.original_filename,
                    "rules_sha256": ingested.sha256,
                    "rules_size": ingested.size,
                    "rules_ingested_at": now(),
                }
            )
            self._write(updated)
            return updated

    def read_rules(self) -> tuple[Project, bytes]:
        with self.lock:
            project = self._read()
            if project is None or not project.rules_sha256:
                raise ProjectNotConfiguredError(
                    "Competition rules have not been uploaded"
                )
            sha256 = project.rules_sha256
        # Read outside the configuration lock; the blob is immutable.
        return project, self.artifacts.read_verified(sha256)

    def _write(self, project: Project) -> None:
        payload = project.model_dump_json()
        temp = self.path.with_name(f".project-{uuid4().hex}.json.tmp")
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
        except BaseException:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
            raise
