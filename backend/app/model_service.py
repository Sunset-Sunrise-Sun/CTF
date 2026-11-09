"""Local model-service configuration and OS-protected API key storage.

Non-secret settings (provider base URL, model id, network switch) live in a
small JSON file under the workbench data directory.  The API key is never put in
that file, the workbench database, events, writeups or exports.  On Windows it
is encrypted with user-scoped DPAPI (CryptProtectData) and stored as a separate
binary blob; another Windows user cannot decrypt it.

This is a single-user, local-first deployment.  The data directory is isolated
per installation, and the encrypted key is bound to the current Windows user.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_BASE_URL = "https://api.deepseek.com"
# Official DeepSeek API identifier. The public product name is V4.1 Flash;
# the API model id remains deepseek-flash.
DEFAULT_MODEL_ID = "deepseek-flash"
DEFAULT_MODEL_NAME = "DeepSeek-V4.1-Flash"
MODEL_ID_TO_NAME = {
    "deepseek-flash": "DeepSeek-V4.1-Flash",
    "deepseek-v4-pro": "DeepSeek-V4-Pro",
}
MODEL_NAME_TO_ID = {
    "DeepSeek-V4.1-Flash": "deepseek-flash",
    "DeepSeek-V4-Pro": "deepseek-v4-pro",
}
CONFIG_FILENAME = "model-service.json"
SECRET_FILENAME = "model-service.secret"
SECRET_MAGIC = b"CTFW-DPAPI-1\n"
DPAPI_ENTROPY = b"ctf-workbench-model-service-v1"
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_MODEL_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,128}$")


class ModelServiceError(ValueError):
    """A safe-to-report settings/credential error (never contains the key)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class CredentialStoreUnavailable(ModelServiceError):
    def __init__(self):
        super().__init__("credential_store_unavailable")


class CredentialStoreError(ModelServiceError):
    def __init__(self):
        super().__init__("credential_store_error")


def _env_network_enabled() -> bool:
    return os.environ.get("CTF_MODEL_NETWORK_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _env_key_name() -> str:
    return os.environ.get("CTF_MODEL_API_KEY_ENV", "DEEPSEEK_API_KEY")


def _env_key() -> str | None:
    value = os.environ.get(_env_key_name())
    return value if value else None


def _env_base_url() -> str:
    return os.environ.get("CTF_MODEL_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _env_model_id() -> str:
    raw = os.environ.get("CTF_MODEL_ID", DEFAULT_MODEL_ID)
    try:
        return _resolve_model_id(raw)
    except ModelServiceError:
        # Preserve an invalid/unknown value here; Provider construction will
        # fail closed with invalid_provider_configuration.
        return raw


def _dpapi_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        ctypes.WinDLL("crypt32", use_last_error=True)
        ctypes.WinDLL("kernel32", use_last_error=True)
    except (AttributeError, OSError):
        return False
    return True


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    return (
        _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))),
        buffer,
    )


def _dpapi_protect(plaintext: bytes) -> bytes:
    if not _dpapi_available():
        raise CredentialStoreUnavailable()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_wchar_p,
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    in_blob, in_buffer = _blob(plaintext)
    entropy_blob, entropy_buffer = _blob(DPAPI_ENTROPY)
    out_blob = _DATA_BLOB()
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        0x1,  # CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(out_blob),
    )
    # Keep buffers alive through the native call.
    del in_buffer, entropy_buffer
    if not ok:
        raise CredentialStoreError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


def _dpapi_unprotect(ciphertext: bytes) -> bytes:
    if not _dpapi_available():
        raise CredentialStoreUnavailable()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    in_blob, in_buffer = _blob(ciphertext)
    entropy_blob, entropy_buffer = _blob(DPAPI_ENTROPY)
    out_blob = _DATA_BLOB()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        0x1,
        ctypes.byref(out_blob),
    )
    del in_buffer, entropy_buffer
    if not ok:
        raise CredentialStoreError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


def _validate_base_url(value: object) -> str:
    if not isinstance(value, str):
        raise ModelServiceError("invalid_base_url")
    cleaned = value.strip().rstrip("/")
    if not cleaned or len(cleaned) > 2048 or any(ch in cleaned for ch in "\r\n\x00"):
        raise ModelServiceError("invalid_base_url")
    try:
        parsed = urlsplit(cleaned)
    except ValueError:
        raise ModelServiceError("invalid_base_url") from None
    secure = parsed.scheme == "https" or (
        parsed.scheme == "http" and parsed.hostname in _LOOPBACK_HOSTS
    )
    if (
        not secure
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ModelServiceError("invalid_base_url")
    return cleaned


def _validate_model_id(value: object) -> str:
    if not isinstance(value, str):
        raise ModelServiceError("invalid_model_id")
    cleaned = value.strip()
    if not _MODEL_RE.fullmatch(cleaned):
        raise ModelServiceError("invalid_model_id")
    return cleaned


def _resolve_model_id(value: object) -> str:
    """Map a known public model name to the official API model id.

    A blank field means the default model; unknown non-blank custom IDs are
    preserved (after normal validation) rather than rewritten.
    """
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return DEFAULT_MODEL_ID
        if cleaned in MODEL_NAME_TO_ID:
            return MODEL_NAME_TO_ID[cleaned]
    return _validate_model_id(value)


def model_display_name(model_id: str) -> str:
    return MODEL_ID_TO_NAME.get(model_id, model_id)


def _validate_api_key(value: object) -> str:
    if not isinstance(value, str):
        raise ModelServiceError("invalid_api_key")
    cleaned = value.strip()
    if not 8 <= len(cleaned) <= 512 or any(ch in cleaned for ch in "\r\n\x00"):
        raise ModelServiceError("invalid_api_key")
    return cleaned


def _atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}-", suffix=".part"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


class ModelServiceSettings:
    """Thread-safe settings facade; never exposes the secret in snapshots."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.config_path = self.root / CONFIG_FILENAME
        self.secret_path = self.root / SECRET_FILENAME
        self._lock = threading.RLock()
        self._config, self._config_error = self._load_config()
        # Only persisted configuration counts.  Environment-only operation
        # keeps the existing env-provider path (and its tests/monkeypatches)
        # untouched; saving config or a key marks this installation configured.
        self._configured = self.config_path.exists() or self.secret_path.exists()

    @property
    def base_url(self) -> str:
        return str(self._config["base_url"])

    @property
    def model_id(self) -> str:
        return str(self._config["model_id"])

    @property
    def network_setting(self) -> bool:
        return bool(self._config["network_enabled"])

    @property
    def network_enabled(self) -> bool:
        return _env_network_enabled() or self.network_setting

    @property
    def network_env_override(self) -> bool:
        return _env_network_enabled()

    @property
    def config_error(self) -> str | None:
        return self._config_error

    @property
    def custom_base_url(self) -> bool:
        return self.base_url.rstrip("/") != DEFAULT_BASE_URL.rstrip("/")

    @property
    def env_key_custom_base_url_authorized(self) -> bool:
        if self.secret_path.exists() or _env_key() is None:
            return False
        return (
            self.custom_base_url
            and self._config.get("env_key_authorized_base_url") == self.base_url
        )

    @property
    def env_key_custom_base_url_authorization_required(self) -> bool:
        return (
            not self.secret_path.exists()
            and _env_key() is not None
            and self.custom_base_url
            and not self.env_key_custom_base_url_authorized
        )

    @property
    def is_configured(self) -> bool:
        return self._configured

    def _load_config(self) -> tuple[dict, str | None]:
        default = {
            "base_url": _env_base_url(),
            "model_id": _env_model_id(),
            # The persisted switch starts off; the env var is an operator
            # override reflected separately in network_env_override.
            "network_enabled": False,
            # An environment-variable key may only be sent to this exact
            # custom base URL after an explicit user authorization.
            "env_key_authorized_base_url": None,
        }
        if not self.config_path.exists():
            return default, None
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError
            base_url = _validate_base_url(
                payload.get("base_url", DEFAULT_BASE_URL)
            )
            model_id = _resolve_model_id(
                payload.get("model_id", DEFAULT_MODEL_ID)
            )
            network = payload.get("network_enabled") is True
            authorized = payload.get("env_key_authorized_base_url")
            if authorized is not None:
                authorized = _validate_base_url(authorized)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return default, "invalid_config"
        return {
            "base_url": base_url,
            "model_id": model_id,
            "network_enabled": network,
            "env_key_authorized_base_url": authorized,
        }, None

    def _write_config(self) -> None:
        payload = {
            "schema": "ctf-workbench-model-service/1",
            "base_url": self._config["base_url"],
            "model_id": self._config["model_id"],
            "network_enabled": bool(self._config["network_enabled"]),
            "env_key_authorized_base_url": self._config.get(
                "env_key_authorized_base_url"
            ),
        }
        _atomic_write(
            self.config_path,
            json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"),
        )

    def _read_secret(self) -> bytes:
        try:
            return self.secret_path.read_bytes()
        except FileNotFoundError:
            raise ModelServiceError("missing_credentials") from None
        except OSError:
            raise CredentialStoreError() from None

    def load_api_key(self) -> str | None:
        with self._lock:
            if self.secret_path.exists():
                blob = self._read_secret()
                if not blob.startswith(SECRET_MAGIC):
                    raise CredentialStoreError()
                try:
                    return _dpapi_unprotect(blob[len(SECRET_MAGIC) :]).decode("utf-8")
                except UnicodeDecodeError:
                    raise CredentialStoreError() from None
            return _env_key()

    def _key_status(self) -> tuple[str | None, str | None]:
        if self.secret_path.exists():
            try:
                self.load_api_key()
            except ModelServiceError as error:
                return None, error.code
            return "settings", None
        if _env_key():
            return "environment", None
        return None, None

    def snapshot(self) -> dict:
        with self._lock:
            key_source, key_error = self._key_status()
            return {
                "provider": "deepseek",
                "base_url": self.base_url,
                "default_base_url": DEFAULT_BASE_URL,
                "model_id": self.model_id,
                "model_name": model_display_name(self.model_id),
                "default_model_id": DEFAULT_MODEL_ID,
                "default_model_name": DEFAULT_MODEL_NAME,
                "key_configured": key_source is not None,
                "key_source": key_source,
                "key_storage_available": _dpapi_available(),
                "key_error": key_error,
                "config_error": self._config_error,
                "network_enabled": self.network_enabled,
                "network_setting": self.network_setting,
                "network_env_override": self.network_env_override,
                "env_key_custom_base_url_authorized": (
                    self.env_key_custom_base_url_authorized
                ),
                "env_key_custom_base_url_authorization_required": (
                    self.env_key_custom_base_url_authorization_required
                ),
            }

    def save(
        self,
        *,
        base_url: object | None = None,
        model_id: object | None = None,
        api_key: object | None = None,
        clear_api_key: bool = False,
        authorize_env_key_custom_base_url: bool = False,
    ) -> dict:
        with self._lock:
            if api_key is not None and clear_api_key:
                raise ModelServiceError("api_key_conflict")
            new_base = self._config["base_url"] if base_url is None else _validate_base_url(base_url)
            new_model = self._config["model_id"] if model_id is None else _resolve_model_id(model_id)
            cleaned_key = None if api_key is None else _validate_api_key(api_key)
            old_config = self._config.copy()
            old_config_error = self._config_error
            old_configured = self._configured
            old_config_bytes = (
                self.config_path.read_bytes() if self.config_path.exists() else None
            )
            old_secret_bytes = (
                self.secret_path.read_bytes() if self.secret_path.exists() else None
            )
            # Determine the post-save key source before writing anything.  An
            # env key may only be sent to a custom base URL when the user has
            # explicitly authorized *that exact* URL; changing the URL never
            # inherits authorization from the previous URL.
            will_have_secret = (
                cleaned_key is not None
                or (
                    api_key is None
                    and not clear_api_key
                    and self.secret_path.exists()
                )
            )
            will_use_env_key = not will_have_secret and _env_key() is not None
            custom_base = new_base.rstrip("/") != DEFAULT_BASE_URL.rstrip("/")
            previous_authorization = self._config.get("env_key_authorized_base_url")
            if will_use_env_key and custom_base:
                if authorize_env_key_custom_base_url:
                    authorization = new_base
                elif (
                    new_base == old_config["base_url"]
                    and previous_authorization == new_base
                ):
                    authorization = new_base
                else:
                    authorization = None
            else:
                authorization = None
            # Prepare the DPAPI blob before touching either persisted file.
            prepared_secret: bytes | None = None
            if cleaned_key is not None:
                if not _dpapi_available():
                    raise CredentialStoreUnavailable()
                try:
                    prepared_secret = SECRET_MAGIC + _dpapi_protect(
                        cleaned_key.encode("utf-8")
                    )
                except CredentialStoreError:
                    raise
            config_written = False
            secret_changed = False
            try:
                self._config = {
                    "base_url": new_base,
                    "model_id": new_model,
                    "network_enabled": bool(self._config["network_enabled"]),
                    "env_key_authorized_base_url": authorization,
                }
                # Do not clear the old config_error until the new config has
                # actually been persisted.
                self._write_config()
                config_written = True
                if clear_api_key:
                    secret_changed = True
                    try:
                        self.secret_path.unlink()
                    except FileNotFoundError:
                        pass
                elif prepared_secret is not None:
                    secret_changed = True
                    _atomic_write(self.secret_path, prepared_secret)
                self._config_error = None
                self._configured = True
            except BaseException:
                # Restore the complete in-memory state first.  Files that were
                # not replaced are left untouched; only a successful config
                # write or secret change is compensated.
                self._config = old_config
                self._config_error = old_config_error
                self._configured = old_configured
                if config_written:
                    if old_config_bytes is None:
                        try:
                            self.config_path.unlink()
                        except FileNotFoundError:
                            pass
                    else:
                        _atomic_write(self.config_path, old_config_bytes)
                if secret_changed:
                    if old_secret_bytes is None:
                        try:
                            self.secret_path.unlink()
                        except FileNotFoundError:
                            pass
                    else:
                        _atomic_write(self.secret_path, old_secret_bytes)
                raise
            return self.snapshot()

    def set_network(self, enabled: bool) -> dict:
        with self._lock:
            old = bool(self._config["network_enabled"])
            self._config["network_enabled"] = bool(enabled)
            try:
                self._write_config()
                self._configured = True
            except BaseException:
                self._config["network_enabled"] = old
                raise
            return self.snapshot()

    def provider_values(self) -> tuple[str, str, str | None, str]:
        """Return (base_url, model_id, inline_key, api_key_env_name)."""
        if self._config_error is not None:
            raise ModelServiceError("config_invalid")
        key = self.load_api_key()
        if key is not None and not self.secret_path.exists():
            if self.custom_base_url and not self.env_key_custom_base_url_authorized:
                raise ModelServiceError(
                    "env_key_custom_base_url_not_authorized"
                )
        return self.base_url, self.model_id, key, _env_key_name()
