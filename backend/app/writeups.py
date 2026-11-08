"""Per-challenge human-edited Writeup persistence.

The saved draft is a human-authored document, stored as a versioned JSON
sidecar under the data root (no database migration).  It is deliberately not an
event: saving a draft never creates tool execution, observation, or AI records.
Each save is optimistically versioned so a stale editor cannot silently
overwrite a newer draft.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from pathlib import Path
from uuid import UUID, uuid4

from .models import WriteupDraft, WriteupDraftSave, now

DEFAULT_MAX_WRITEUP_BYTES = 1_048_576
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class WriteupNotFoundError(KeyError):
    """Raised when no human draft has been saved for the challenge."""


class WriteupConflictError(Exception):
    """Raised when base_version does not match the stored version.

    ``current`` is the latest stored draft, or ``None`` when the client expected
    an existing draft but none exists (for example after losing local state).
    """

    def __init__(self, current: WriteupDraft | None):
        self.current = current
        super().__init__("Writeup version conflict")


class WriteupIntegrityError(ValueError):
    """Raised when a stored draft cannot be verified against its metadata."""


class WriteupTooLargeError(ValueError):
    """Raised when the human draft exceeds the configured byte limit."""


class WriteupValidationError(ValueError):
    """Raised when the human draft content is not acceptable."""


class WriteupStore:
    def __init__(self, root: Path, max_bytes: int = DEFAULT_MAX_WRITEUP_BYTES):
        if max_bytes <= 0:
            raise ValueError("max_writeup_bytes must be positive")
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self.lock = threading.Lock()

    def _path(self, challenge_id: str) -> Path:
        try:
            valid = str(UUID(challenge_id)) == challenge_id
        except ValueError:
            valid = False
        if not valid:
            raise WriteupValidationError("Invalid challenge ID")
        candidate = self.root / f"{challenge_id}.json"
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(self.root):
            raise WriteupValidationError("Path outside writeup store")
        return candidate

    def load(self, challenge_id: str) -> WriteupDraft:
        with self.lock:
            return self._load(challenge_id)

    def _load(self, challenge_id: str) -> WriteupDraft:
        path = self._path(challenge_id)
        if not path.exists():
            raise WriteupNotFoundError(challenge_id)
        if path.is_symlink():
            raise WriteupIntegrityError("Saved writeup is a symbolic link")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise WriteupIntegrityError("Saved writeup is unreadable") from None
        if not isinstance(data, dict):
            raise WriteupIntegrityError("Saved writeup has an invalid shape")
        try:
            draft = WriteupDraft.model_validate(data)
        except ValueError:
            raise WriteupIntegrityError("Saved writeup metadata is invalid") from None
        if draft.challenge_id != challenge_id:
            raise WriteupIntegrityError("Saved writeup belongs to another challenge")
        content_bytes = draft.content.encode("utf-8")
        if (
            len(content_bytes) != draft.size
            or hashlib.sha256(content_bytes).hexdigest() != draft.sha256
        ):
            raise WriteupIntegrityError(
                "Saved writeup content does not match its recorded SHA-256"
            )
        return draft

    def save(self, challenge_id: str, body: WriteupDraftSave) -> WriteupDraft:
        content = body.content
        if not content.strip():
            raise WriteupValidationError("Writeup content must not be empty")
        content_bytes = content.encode("utf-8")
        if len(content_bytes) > self.max_bytes:
            raise WriteupTooLargeError(
                f"Writeup content exceeds the {self.max_bytes} byte limit"
            )
        with self.lock:
            current: WriteupDraft | None
            try:
                current = self._load(challenge_id)
            except WriteupNotFoundError:
                current = None
            current_version = current.version if current is not None else 0
            if body.base_version != current_version:
                raise WriteupConflictError(current)
            draft = WriteupDraft(
                challenge_id=challenge_id,
                content=content,
                version=current_version + 1,
                sha256=hashlib.sha256(content_bytes).hexdigest(),
                size=len(content_bytes),
                saved_at=now(),
            )
            self._write(draft)
            return draft

    def _write(self, draft: WriteupDraft) -> None:
        path = self._path(draft.challenge_id)
        temp = path.with_name(f".writeup-{uuid4().hex}.json.tmp")
        payload = draft.model_dump_json()
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        except BaseException:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
            raise
        # Best effort directory sync so the rename is durable across a crash.
        # Some platforms cannot open a directory this way; ignore that case.
        try:
            directory = os.open(self.root, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(directory)
        except OSError:
            pass
        finally:
            os.close(directory)
