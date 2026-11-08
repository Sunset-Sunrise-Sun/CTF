"""Content-addressed evidence artifact storage.

Bytes are stored under a path derived from their SHA-256 digest, never under a
client-supplied filename.  Stored bytes are immutable: a changed file is a new
artifact.  The original filename is retained only as display metadata, so path
traversal in a filename cannot influence where bytes are written.

This module deliberately does not extract, execute, or interpret uploaded
files.  It only writes bytes, hashes them, and sniffs a media type from the
leading bytes (any client-provided Content-Type is ignored).
"""

from __future__ import annotations

import codecs
import hashlib
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

DEFAULT_MAX_ARTIFACT_BYTES = 50 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024
_HEAD_SIZE = 4096
_DIGEST = re.compile(r"^[0-9a-f]{64}$")

# Media types are detected from leading bytes, in this order, not from the
# filename or the client's declared Content-Type.
_MAGIC_PREFIXES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF-", "application/pdf"),
    (b"PK\x03\x04", "application/zip"),
    (b"PK\x05\x06", "application/zip"),
    (b"PK\x07\x08", "application/zip"),
    (b"\x1f\x8b", "application/gzip"),
    (b"7z\xbc\xaf\x27\x1c", "application/x-7z-compressed"),
    (b"Rar!\x1a\x07\x00", "application/vnd.rar"),
    (b"Rar!\x1a\x07\x01\x00", "application/vnd.rar"),
    (b"\x7fELF", "application/x-elf"),
    (b"MZ", "application/vnd.microsoft.portable-executable"),
)


class ArtifactTooLarge(ValueError):
    """Raised when an upload exceeds the configured byte limit."""


class ArtifactIntegrityError(ValueError):
    """Raised when stored bytes are missing or do not match the digest."""


class ArtifactPathError(ValueError):
    """Raised when a storage path is invalid or escapes the storage root."""


@dataclass(frozen=True)
class IngestedArtifact:
    sha256: str
    size: int
    media_type: str
    original_filename: str


def sanitize_filename(filename: str | None) -> str:
    """Return a display-only basename; never used as a storage path."""
    if not filename:
        return "upload.bin"
    basename = str(filename).replace("\\", "/").split("/")[-1]
    cleaned = "".join(
        character
        for character in basename
        if character.isprintable() and character not in ':*?"<>|'
    ).strip()
    if not cleaned or cleaned in {".", ".."}:
        return "upload.bin"
    return cleaned[:255]


def detect_media_type(head: bytes) -> str:
    """Return a server-detected media type from the first bytes of the file."""
    for magic, media_type in _MAGIC_PREFIXES:
        if head.startswith(magic):
            return media_type
    if len(head) >= 262 and head[257:262] == b"ustar":
        return "application/x-tar"
    if head and b"\x00" not in head:
        decoder = codecs.getincrementaldecoder("utf-8")()
        try:
            decoder.decode(head, final=False)
        except UnicodeDecodeError:
            pass
        else:
            return "text/plain"
    return "application/octet-stream"


def _strip_extended_prefix(path: str) -> str:
    """Normalise Windows extended-length paths for containment comparison."""
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[len("\\\\?\\UNC\\") :]
    if path.startswith("\\\\?\\"):
        return path[len("\\\\?\\") :]
    if path.startswith("\\??\\"):
        return path[len("\\??\\") :]
    return path


class ArtifactStore:
    """Filesystem side of the evidence store: write once, verify on read."""

    def __init__(self, root: Path, max_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES):
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.max_bytes = max_bytes
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.staging = self.root / ".staging"
        self.staging.mkdir(parents=True, exist_ok=True)
        self._guard(self.staging)

    def _guard(self, path: Path) -> Path:
        """Resolve a path and refuse anything that escapes the storage root.

        Resolution follows symlinks/junctions, so a linked component that
        points outside the storage root is rejected instead of followed.
        Windows may return an extended-length ``\\\\?\\`` path when resolution
        races a concurrent rename; that prefix is stripped before comparing.
        """
        resolved = path.resolve(strict=False)
        if not self._contains(resolved):
            raise ArtifactPathError("Artifact path outside storage root")
        return resolved

    def _contains(self, candidate: Path) -> bool:
        child = os.path.normcase(_strip_extended_prefix(str(candidate)))
        parent = os.path.normcase(_strip_extended_prefix(str(self.root)))
        try:
            return os.path.commonpath([child, parent]) == parent
        except ValueError:  # Different drives on Windows.
            return False

    def blob_path(self, sha256: str) -> Path:
        if not _DIGEST.match(sha256):
            raise ArtifactPathError("Invalid SHA-256 digest")
        candidate = self.root / "sha256" / sha256[:2] / sha256[2:4] / sha256
        self._guard(candidate)
        return candidate

    def ingest(self, stream: BinaryIO, *, filename: str | None) -> IngestedArtifact:
        """Stream bytes to a temp file, hash them, then install the blob.

        The returned object contains only metadata; the caller persists it and
        creates the linked event.  A staging file is always removed on failure.
        """
        digest = hashlib.sha256()
        size = 0
        head = b""
        descriptor, temp_name = tempfile.mkstemp(
            dir=self.staging, prefix="upload-", suffix=".part"
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                while True:
                    chunk = stream.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise ArtifactTooLarge("Artifact exceeds size limit")
                    digest.update(chunk)
                    if len(head) < _HEAD_SIZE:
                        head += chunk[: _HEAD_SIZE - len(head)]
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            sha256 = digest.hexdigest()
            destination = self.blob_path(sha256)
            destination.parent.mkdir(parents=True, exist_ok=True)
            self._guard(destination)
            self._install(temp_name, destination, sha256, size)
            return IngestedArtifact(
                sha256=sha256,
                size=size,
                media_type=detect_media_type(head),
                original_filename=sanitize_filename(filename),
            )
        except BaseException:
            self._unlink(temp_name)
            raise

    def _install(
        self, temp_name: str, destination: Path, sha256: str, size: int
    ) -> None:
        if destination.exists():
            if self._blob_matches(destination, sha256, size):
                self._unlink(temp_name)
                return
            # A pre-existing blob that no longer matches its digest was
            # tampered with or truncated; restore the verified upload bytes.
            self._make_writable(destination)
        try:
            os.replace(temp_name, destination)
        except OSError:
            # A concurrent installer may have won the race and marked the blob
            # read-only on platforms where replacing a read-only file fails.
            if destination.exists() and self._blob_matches(destination, sha256, size):
                self._unlink(temp_name)
                return
            raise
        self._make_read_only(destination)

    @staticmethod
    def _blob_matches(path: Path, sha256: str, size: int) -> bool:
        try:
            if path.stat().st_size != size:
                return False
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
                    digest.update(chunk)
            return digest.hexdigest() == sha256
        except OSError:
            return False

    def read_verified(self, sha256: str) -> bytes:
        """Return blob bytes only after verifying them against the digest."""
        path = self.blob_path(sha256)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            raise ArtifactIntegrityError("Artifact content is missing") from None
        except OSError:
            raise ArtifactIntegrityError("Artifact content is unreadable") from None
        if hashlib.sha256(data).hexdigest() != sha256:
            raise ArtifactIntegrityError("Artifact content does not match its digest")
        return data

    def verify(self, sha256: str) -> bool:
        try:
            self.read_verified(sha256)
        except (ArtifactIntegrityError, ArtifactPathError):
            return False
        return True

    def discard(self, sha256: str) -> None:
        """Remove a blob; callers must first confirm no metadata references it."""
        path = self.blob_path(sha256)
        self._make_writable(path)
        self._unlink(path)

    @staticmethod
    def _unlink(path: str | Path) -> None:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass

    @staticmethod
    def _make_read_only(path: Path) -> None:
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        except OSError:
            pass

    @staticmethod
    def _make_writable(path: Path) -> None:
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
