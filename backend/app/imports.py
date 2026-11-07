"""Safe ZIP import for a challenge workspace.

The archive is validated against explicit budgets, extracted into a staging
directory on the same filesystem, hashed file by file, and only then installed
atomically as ``<challenge workspace>/imports/<import_id>/``.  No imported file
is ever executed or recursively extracted, and a failed import leaves no
partially installed directory behind.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import stat
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from uuid import UUID, uuid4

from .artifacts import detect_media_type
from .models import ImportDetail, ImportFile, ImportRecord, now

DEFAULT_MAX_FILES = 2000
DEFAULT_MAX_FILE_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 200 * 1024 * 1024
DEFAULT_MAX_COMPRESSION_RATIO = 200.0
_READ_CHUNK = 1024 * 1024
_HEAD_SIZE = 4096
_MAX_RELATIVE_PATH = 1000
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


class ZipValidationError(ValueError):
    """Raised when an archive violates a safety rule or an import budget."""


@dataclass(frozen=True)
class ImportLimits:
    max_files: int = DEFAULT_MAX_FILES
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES
    max_compression_ratio: float = DEFAULT_MAX_COMPRESSION_RATIO

    def __post_init__(self) -> None:
        for name in ("max_files", "max_file_bytes", "max_total_bytes"):
            value = getattr(self, name)
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_compression_ratio <= 0:
            raise ValueError("max_compression_ratio must be positive")

    @classmethod
    def from_env(cls) -> "ImportLimits":
        return cls(
            max_files=_env_int("CTF_IMPORT_MAX_FILES", DEFAULT_MAX_FILES),
            max_file_bytes=_env_int(
                "CTF_IMPORT_MAX_FILE_BYTES", DEFAULT_MAX_FILE_BYTES
            ),
            max_total_bytes=_env_int(
                "CTF_IMPORT_MAX_TOTAL_BYTES", DEFAULT_MAX_TOTAL_BYTES
            ),
            max_compression_ratio=_env_float(
                "CTF_IMPORT_MAX_COMPRESSION_RATIO",
                DEFAULT_MAX_COMPRESSION_RATIO,
            ),
        )


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number") from None
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


@dataclass(frozen=True)
class ImportManifest:
    import_id: str
    challenge_id: str
    original_artifact_id: str
    original_filename: str
    extracted_file_count: int
    total_uncompressed_size: int
    warnings: list[str]
    created_at: str
    manifest_sha256: str = ""
    files: list[ImportFile] = field(default_factory=list)

    def record(self) -> ImportRecord:
        return ImportRecord(
            import_id=self.import_id,
            challenge_id=self.challenge_id,
            original_artifact_id=self.original_artifact_id,
            original_filename=self.original_filename,
            extracted_file_count=self.extracted_file_count,
            total_uncompressed_size=self.total_uncompressed_size,
            warnings=list(self.warnings),
            created_at=self.created_at,
            manifest_sha256=self.manifest_sha256,
        )

    def detail(self) -> ImportDetail:
        return ImportDetail(**self.record().model_dump(), files=list(self.files))

    def payload(self) -> dict:
        """Import summary recorded on the challenge_imported event."""
        return {
            "import_id": self.import_id,
            "challenge_id": self.challenge_id,
            "original_artifact_id": self.original_artifact_id,
            "original_filename": self.original_filename,
            "extracted_file_count": self.extracted_file_count,
            "total_uncompressed_size": self.total_uncompressed_size,
            "warnings": list(self.warnings),
            "created_at": self.created_at,
            "manifest_sha256": self.manifest_sha256,
        }

    def canonical_bytes(self) -> bytes:
        data = self.payload()
        data["files"] = [item.model_dump() for item in self.files]
        return json.dumps(
            data,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")


def _normalise_member_name(raw: str) -> str:
    """Normalise one archive member and reject unsafe or ambiguous names."""
    if not isinstance(raw, str) or not raw:
        raise ZipValidationError("Archive member has an empty name")
    if "\x00" in raw:
        raise ZipValidationError("Archive member name contains a NUL byte")
    name = raw.replace("\\", "/")
    if name.startswith("/"):
        raise ZipValidationError(f"Absolute path rejected: {raw!r}")
    if _DRIVE_PREFIX.match(name):
        raise ZipValidationError(f"Windows drive path rejected: {raw!r}")
    parts: list[str] = []
    for part in name.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ZipValidationError(f"Path traversal rejected: {raw!r}")
        if ":" in part:
            raise ZipValidationError(f"Alternate data stream rejected: {raw!r}")
        if any(ord(character) < 32 or ord(character) == 127 for character in part):
            raise ZipValidationError(f"Control character rejected: {raw!r}")
        if part.endswith((" ", ".")):
            raise ZipValidationError(f"Trailing space or dot rejected: {raw!r}")
        if part.casefold() in _WINDOWS_RESERVED:
            raise ZipValidationError(f"Reserved device name rejected: {raw!r}")
        parts.append(part)
    if not parts:
        raise ZipValidationError(f"Archive member has no usable name: {raw!r}")
    relative = "/".join(parts)
    if len(relative) > _MAX_RELATIVE_PATH:
        raise ZipValidationError("Archive member path is too long")
    return relative


def _validate_archive(
    data: bytes, limits: ImportLimits
) -> tuple[list[tuple[zipfile.ZipInfo, str]], list[str]]:
    if not data:
        raise ZipValidationError("Uploaded archive is empty")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError):
        raise ZipValidationError("Uploaded file is not a valid ZIP archive") from None
    with archive:
        infos = archive.infolist()
        max_entries = limits.max_files * 2 + 100
        if len(infos) > max_entries:
            raise ZipValidationError(
                f"Archive contains too many entries (limit {max_entries})"
            )
        files_by_case: dict[str, str] = {}
        dirs_by_case: dict[str, str] = {}
        entries: list[tuple[zipfile.ZipInfo, str]] = []
        warnings: list[str] = []
        total_uncompressed = 0
        total_compressed = 0
        for info in infos:
            if info.flag_bits & 0x1:
                raise ZipValidationError("Encrypted ZIP archives are not supported")
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise ZipValidationError(
                    f"Symbolic link entry rejected: {info.filename!r}"
                )
            if info.is_dir():
                try:
                    relative = _normalise_member_name(info.filename)
                except ZipValidationError as error:
                    if "no usable name" in str(error):
                        continue
                    raise
                key = relative.casefold()
                if key in dirs_by_case:
                    raise ZipValidationError(f"Duplicate directory path: {relative!r}")
                if key in files_by_case:
                    raise ZipValidationError(
                        f"File and directory path conflict: {relative!r}"
                    )
                dirs_by_case[key] = relative
                continue
            if mode and (mode & 0o170000) and not stat.S_ISREG(mode):
                # Only reject entries that explicitly declare a non-regular
                # file type; plain permission bits (e.g. 0o600) carry no type.
                raise ZipValidationError(
                    f"Special file entry rejected: {info.filename!r}"
                )
            relative = _normalise_member_name(info.filename)
            key = relative.casefold()
            if key in files_by_case:
                if files_by_case[key] == relative:
                    raise ZipValidationError(f"Duplicate path: {relative!r}")
                raise ZipValidationError(
                    "Case-insensitive path conflict: "
                    f"{files_by_case[key]!r} vs {relative!r}"
                )
            if key in dirs_by_case:
                raise ZipValidationError(
                    f"File and directory path conflict: {relative!r}"
                )
            if info.file_size > limits.max_file_bytes:
                raise ZipValidationError(
                    f"File exceeds the uncompressed size limit: {relative!r}"
                )
            if info.file_size > 0 and info.compress_size <= 0:
                raise ZipValidationError(f"Suspicious compression ratio: {relative!r}")
            if (
                info.compress_size > 0
                and info.file_size / info.compress_size > limits.max_compression_ratio
            ):
                raise ZipValidationError(f"Suspicious compression ratio: {relative!r}")
            if len(entries) + 1 > limits.max_files:
                raise ZipValidationError(
                    f"Archive exceeds the file count limit ({limits.max_files})"
                )
            total_uncompressed += info.file_size
            total_compressed += info.compress_size
            if total_uncompressed > limits.max_total_bytes:
                raise ZipValidationError(
                    "Archive exceeds the total uncompressed size limit"
                )
            if (
                total_compressed > 0
                and total_uncompressed / total_compressed > limits.max_compression_ratio
            ):
                raise ZipValidationError("Suspicious overall compression ratio")
            files_by_case[key] = relative
            entries.append((info, relative))
            if relative.casefold().endswith(".zip"):
                warnings.append(f"Nested archive was not extracted: {relative}")
        for relative in files_by_case.values():
            parts = relative.split("/")
            for index in range(1, len(parts)):
                ancestor = "/".join(parts[:index])
                if ancestor.casefold() in files_by_case:
                    raise ZipValidationError(
                        f"File path is used as a directory: {ancestor!r}"
                    )
        return entries, warnings


@dataclass
class StagedImport:
    """Validated extraction staged inside the challenge workspace."""

    staging: Path
    challenge_id: str
    import_id: str
    created_at: str
    extracted_file_count: int
    total_uncompressed_size: int
    warnings: list[str]
    files: list[ImportFile]


def stage_archive(
    data: bytes,
    *,
    challenge_id: str,
    workspace_challenge: Path,
    limits: ImportLimits,
) -> StagedImport:
    """Validate and extract an archive into a staging directory.

    Nothing is installed until :func:`install_staged_import` succeeds; any
    failure removes the staging directory so no partial import remains.
    """
    entries, warnings = _validate_archive(data, limits)
    import_id = str(uuid4())
    created_at = now()
    staging = workspace_challenge / f".import-staging-{uuid4().hex}"
    files: list[ImportFile] = []
    total_size = 0
    try:
        staging.mkdir(parents=True)
        archive = zipfile.ZipFile(io.BytesIO(data))
        with archive:
            for info, relative in entries:
                target = staging.joinpath(*relative.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                size = 0
                head = b""
                with archive.open(info) as source, target.open("xb") as destination:
                    while True:
                        chunk = source.read(_READ_CHUNK)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > limits.max_file_bytes:
                            raise ZipValidationError(
                                f"File exceeds the uncompressed size limit: {relative!r}"
                            )
                        if size > info.file_size:
                            raise ZipValidationError(
                                f"Uncompressed size mismatch: {relative!r}"
                            )
                        digest.update(chunk)
                        if len(head) < _HEAD_SIZE:
                            head += chunk[: _HEAD_SIZE - len(head)]
                        destination.write(chunk)
                if size != info.file_size:
                    raise ZipValidationError(
                        f"Uncompressed size mismatch: {relative!r}"
                    )
                total_size += size
                if total_size > limits.max_total_bytes:
                    raise ZipValidationError(
                        "Archive exceeds the total uncompressed size limit"
                    )
                files.append(
                    ImportFile(
                        relative_path=relative,
                        size=size,
                        sha256=digest.hexdigest(),
                        media_type=detect_media_type(head),
                    )
                )
        return StagedImport(
            staging=staging,
            challenge_id=challenge_id,
            import_id=import_id,
            created_at=created_at,
            extracted_file_count=len(files),
            total_uncompressed_size=total_size,
            warnings=sorted(set(warnings)),
            files=sorted(files, key=lambda item: item.relative_path),
        )
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def install_staged_import(
    staged: StagedImport,
    *,
    original_artifact_id: str,
    original_filename: str,
) -> ImportManifest:
    """Write the manifest and atomically install the staged extraction."""
    import_root = staged.staging.parent / "imports"
    final = import_root / staged.import_id
    manifest = ImportManifest(
        import_id=staged.import_id,
        challenge_id=staged.challenge_id,
        original_artifact_id=original_artifact_id,
        original_filename=original_filename,
        extracted_file_count=staged.extracted_file_count,
        total_uncompressed_size=staged.total_uncompressed_size,
        warnings=list(staged.warnings),
        created_at=staged.created_at,
        files=list(staged.files),
    )
    manifest = replace(
        manifest,
        manifest_sha256=hashlib.sha256(manifest.canonical_bytes()).hexdigest(),
    )
    try:
        (staged.staging / "manifest.json").write_bytes(manifest.canonical_bytes())
        import_root.mkdir(parents=True, exist_ok=True)
        if final.exists():
            raise ZipValidationError("Import identifier collision")
        os.replace(staged.staging, final)
    except BaseException:
        shutil.rmtree(staged.staging, ignore_errors=True)
        raise
    return manifest


def discard_staged_import(staged: StagedImport) -> None:
    shutil.rmtree(staged.staging, ignore_errors=True)


def installed_import_directory(
    workspace_challenge: Path, import_id: str
) -> Path | None:
    directory = workspace_challenge / "imports" / import_id
    return directory if directory.is_dir() else None


def _manifest_from_json(path: Path) -> ImportManifest:
    data = json.loads(path.read_text(encoding="utf-8"))
    return ImportManifest(
        import_id=data["import_id"],
        challenge_id=data["challenge_id"],
        original_artifact_id=data["original_artifact_id"],
        original_filename=data["original_filename"],
        extracted_file_count=int(data["extracted_file_count"]),
        total_uncompressed_size=int(data["total_uncompressed_size"]),
        warnings=list(data.get("warnings", [])),
        created_at=data["created_at"],
        manifest_sha256=data.get("manifest_sha256", ""),
        files=[ImportFile.model_validate(item) for item in data.get("files", [])],
    )


def read_manifest(import_directory: Path) -> ImportManifest:
    try:
        return _manifest_from_json(import_directory / "manifest.json")
    except (OSError, ValueError, KeyError):
        raise ZipValidationError("Stored import manifest is unreadable") from None


def list_imports(workspace_challenge: Path) -> list[ImportManifest]:
    parent = workspace_challenge / "imports"
    if not parent.is_dir():
        return []
    manifests: list[ImportManifest] = []
    for child in parent.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        try:
            manifests.append(read_manifest(child))
        except ZipValidationError:
            continue
    manifests.sort(key=lambda item: (item.created_at, item.import_id), reverse=True)
    return manifests


def import_directory(workspace_challenge: Path, import_id: str) -> Path:
    try:
        valid = str(UUID(import_id)) == import_id
    except ValueError:
        raise KeyError(import_id) from None
    if not valid:
        raise KeyError(import_id)
    directory = (workspace_challenge / "imports" / import_id).resolve()
    root = (workspace_challenge / "imports").resolve()
    if not directory.is_relative_to(root) or not directory.is_dir():
        raise KeyError(import_id)
    return directory


def imported_file_path(
    workspace_challenge: Path, manifest: ImportManifest, relative_path: str
) -> Path:
    """Resolve a manifest-listed file; no arbitrary workspace paths are served."""
    if not any(item.relative_path == relative_path for item in manifest.files):
        raise KeyError(relative_path)
    root = import_directory(workspace_challenge, manifest.import_id)
    candidate = root.joinpath(*relative_path.split("/"))
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise KeyError(relative_path)
    if candidate.is_symlink() or not resolved.is_file():
        raise KeyError(relative_path)
    return resolved
