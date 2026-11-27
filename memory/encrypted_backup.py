"""Authenticated encrypted export bundles for important local Brain state.

Requires the maintained cryptography package. No fallback cipher is
implemented. Decryption writes to a new staging directory only; it never
modifies live stores.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from typing import Optional

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:  # pragma: no cover - exercised in environments without optional crypto
    AESGCM = None

_MAGIC = b"PABKENC1"
_VERSION = 1
_KDF_N = 2 ** 15
_KDF_R = 8
_KDF_P = 1
_SALT_BYTES = 16
_NONCE_BYTES = 12
_KEY_BYTES = 32
_MAX_SOURCE_BYTES = 64 * 1024 * 1024
_MAX_BUNDLE_BYTES = 192 * 1024 * 1024
_MAX_HEADER_BYTES = 4096
_REQUIRED_FILES = {"memory.json", "tasks.json"}
_OPTIONAL_FILES = {"module_state.json"}


class EncryptedBackupError(ValueError):
    """Encrypted export is unavailable, invalid, unsafe, or unauthenticated."""


def _require_crypto():
    if AESGCM is None:
        raise EncryptedBackupError("CRYPTOGRAPHY_NOT_INSTALLED")


def _validate_passphrase(passphrase: str) -> bytes:
    if not isinstance(passphrase, str) or len(passphrase) < 12 or not passphrase.strip():
        raise EncryptedBackupError("PASSPHRASE_TOO_SHORT")
    if len(passphrase) > 1024:
        raise EncryptedBackupError("PASSPHRASE_TOO_LONG")
    return passphrase.encode("utf-8")


def _derive_key(passphrase: bytes, salt: bytes) -> bytes:
    try:
        return hashlib.scrypt(
            passphrase, salt=salt, n=_KDF_N, r=_KDF_R, p=_KDF_P,
            dklen=_KEY_BYTES, maxmem=128 * 1024 * 1024,
        )
    except Exception as exc:
        raise EncryptedBackupError("KEY_DERIVATION_FAILED") from exc


def _atomic_create(path: str, content: bytes) -> str:
    target = os.path.abspath(path)
    directory = os.path.dirname(target)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    if os.path.lexists(target):
        raise EncryptedBackupError("DESTINATION_ALREADY_EXISTS")
    try:
        # Reserve the destination exclusively, then atomically replace our
        # placeholder with a fully fsynced temporary file in the same directory.
        reservation_fd = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        os.close(reservation_fd)
    except FileExistsError as exc:
        raise EncryptedBackupError("DESTINATION_ALREADY_EXISTS") from exc
    except OSError as exc:
        raise EncryptedBackupError("ENCRYPTED_EXPORT_WRITE_FAILED") from exc

    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".pab_export_", suffix=".tmp", dir=directory)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
        try:
            os.chmod(target, 0o600)
            dir_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
        return target
    except Exception as exc:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        try:
            os.unlink(target)
        except OSError:
            pass
        raise EncryptedBackupError("ENCRYPTED_EXPORT_WRITE_FAILED") from exc


def _read_source(
    path: str,
    label: str,
    *,
    required: bool = True,
    max_bytes: int = _MAX_SOURCE_BYTES,
) -> Optional[bytes]:
    if not path:
        if required:
            raise EncryptedBackupError(label + "_PATH_REQUIRED")
        return None
    if os.path.islink(path):
        raise EncryptedBackupError(label + "_SYMLINK_REJECTED")
    try:
        metadata = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        if required:
            raise EncryptedBackupError(label + "_MISSING")
        return None
    except OSError as exc:
        raise EncryptedBackupError(label + "_UNREADABLE") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise EncryptedBackupError(label + "_NOT_REGULAR_FILE")
    if metadata.st_size > max_bytes:
        raise EncryptedBackupError(label + "_TOO_LARGE")
    try:
        with open(path, "rb") as handle:
            raw = handle.read(max_bytes + 1)
    except OSError as exc:
        raise EncryptedBackupError(label + "_UNREADABLE") from exc
    if len(raw) > max_bytes:
        raise EncryptedBackupError(label + "_TOO_LARGE")
    return raw


def _validate_memory(raw: bytes) -> None:
    from memory.backup_restore import _validate_payload
    try:
        _validate_payload(raw)
    except Exception as exc:
        raise EncryptedBackupError("MEMORY_SCHEMA_INVALID") from exc


def _validate_tasks(raw: bytes) -> None:
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise EncryptedBackupError("TASK_SCHEMA_INVALID") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise EncryptedBackupError("TASK_SCHEMA_INVALID")
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        raise EncryptedBackupError("TASK_SCHEMA_INVALID")
    seen = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise EncryptedBackupError("TASK_SCHEMA_INVALID")
        identifier = task.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise EncryptedBackupError("TASK_SCHEMA_INVALID")
        if task.get("status") not in {"pending", "active", "completed", "interrupted"}:
            raise EncryptedBackupError("TASK_SCHEMA_INVALID")
        seen.add(identifier)


def _validate_modules(raw: bytes) -> None:
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise EncryptedBackupError("MODULE_STATE_SCHEMA_INVALID") from exc
    if (
        not isinstance(data, dict)
        or set(data) != {"version", "updated_at", "disabled"}
        or data.get("version") != 1
        or not isinstance(data.get("updated_at"), str)
        or not data.get("updated_at")
        or not isinstance(data.get("disabled"), list)
        or any(not isinstance(item, str) or not item for item in data.get("disabled", []))
        or len(data.get("disabled", [])) != len(set(data.get("disabled", [])))
    ):
        raise EncryptedBackupError("MODULE_STATE_SCHEMA_INVALID")


def _build_archive(memory_raw: bytes, task_raw: bytes, module_raw: Optional[bytes]) -> bytes:
    files = {"memory.json": memory_raw, "tasks.json": task_raw}
    if module_raw is not None:
        files["module_state.json"] = module_raw
    manifest = {
        "format": "personal-ai-brain-backup",
        "version": _VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": {
            name: {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            for name, raw in sorted(files.items())
        },
    }
    output = io.BytesIO()
    try:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True, separators=(",", ":")))
            for name, raw in files.items():
                archive.writestr(name, raw)
    except Exception as exc:
        raise EncryptedBackupError("BACKUP_ARCHIVE_BUILD_FAILED") from exc
    result = output.getvalue()
    if len(result) > _MAX_BUNDLE_BYTES:
        raise EncryptedBackupError("BACKUP_BUNDLE_TOO_LARGE")
    return result


def _encrypt(plaintext: bytes, passphrase: str) -> bytes:
    _require_crypto()
    password = _validate_passphrase(passphrase)
    salt = os.urandom(_SALT_BYTES)
    nonce = os.urandom(_NONCE_BYTES)
    header = {
        "version": _VERSION,
        "cipher": "AES-256-GCM",
        "kdf": "scrypt",
        "n": _KDF_N,
        "r": _KDF_R,
        "p": _KDF_P,
        "salt": salt.hex(),
        "nonce": nonce.hex(),
    }
    header_raw = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("ascii")
    aad = _MAGIC + len(header_raw).to_bytes(4, "big") + header_raw
    ciphertext = AESGCM(_derive_key(password, salt)).encrypt(nonce, plaintext, aad)
    return aad + ciphertext


def _decrypt(encrypted: bytes, passphrase: str) -> bytes:
    _require_crypto()
    password = _validate_passphrase(passphrase)
    if not isinstance(encrypted, bytes) or len(encrypted) < len(_MAGIC) + 4 + 16:
        raise EncryptedBackupError("ENCRYPTED_BACKUP_TRUNCATED")
    if encrypted[:len(_MAGIC)] != _MAGIC:
        raise EncryptedBackupError("ENCRYPTED_BACKUP_MAGIC_INVALID")
    header_length = int.from_bytes(encrypted[len(_MAGIC):len(_MAGIC) + 4], "big")
    header_start = len(_MAGIC) + 4
    header_end = header_start + header_length
    if header_length <= 0 or header_length > _MAX_HEADER_BYTES or header_end + 16 > len(encrypted):
        raise EncryptedBackupError("ENCRYPTED_BACKUP_HEADER_INVALID")
    header_raw = encrypted[header_start:header_end]
    try:
        header = json.loads(header_raw.decode("ascii"))
    except Exception as exc:
        raise EncryptedBackupError("ENCRYPTED_BACKUP_HEADER_INVALID") from exc
    expected = {
        "version": _VERSION, "cipher": "AES-256-GCM", "kdf": "scrypt",
        "n": _KDF_N, "r": _KDF_R, "p": _KDF_P,
    }
    if not isinstance(header, dict) or any(header.get(key) != value for key, value in expected.items()):
        raise EncryptedBackupError("ENCRYPTED_BACKUP_PARAMETERS_UNSUPPORTED")
    try:
        salt = bytes.fromhex(header["salt"])
        nonce = bytes.fromhex(header["nonce"])
    except (KeyError, TypeError, ValueError) as exc:
        raise EncryptedBackupError("ENCRYPTED_BACKUP_HEADER_INVALID") from exc
    if len(salt) != _SALT_BYTES or len(nonce) != _NONCE_BYTES:
        raise EncryptedBackupError("ENCRYPTED_BACKUP_HEADER_INVALID")
    aad = encrypted[:header_end]
    try:
        return AESGCM(_derive_key(password, salt)).decrypt(nonce, encrypted[header_end:], aad)
    except Exception as exc:
        raise EncryptedBackupError("BACKUP_AUTHENTICATION_FAILED") from exc


def create_encrypted_backup(
    memory_file: str,
    task_file: str,
    destination: str,
    passphrase: str,
    module_state_file: Optional[str] = None,
) -> dict:
    """Create a password-encrypted portable backup without deleting plaintext sources."""
    memory_raw = _read_source(memory_file, "MEMORY")
    task_raw = _read_source(task_file, "TASKS", required=False)
    module_raw = _read_source(module_state_file, "MODULE_STATE", required=False) if module_state_file else None
    _validate_memory(memory_raw)
    if task_raw is None:
        task_raw = b'{"schema_version":1,"tasks":[]}'
    _validate_tasks(task_raw)
    if module_raw is not None:
        _validate_modules(module_raw)

    sources = [os.path.abspath(item) for item in (memory_file, task_file, module_state_file) if item]
    if os.path.abspath(destination) in sources:
        raise EncryptedBackupError("DESTINATION_MATCHES_SOURCE")
    archive = _build_archive(memory_raw, task_raw, module_raw)
    encrypted = _encrypt(archive, passphrase)
    target = _atomic_create(destination, encrypted)
    return {
        "ok": True,
        "encrypted_file": target,
        "encrypted_bytes": len(encrypted),
        "included": ["memory.json", "tasks.json"] + (["module_state.json"] if module_raw is not None else []),
        "plaintext_sources_preserved": True,
    }


def _validate_archive(archive_raw: bytes) -> dict:
    if len(archive_raw) > _MAX_BUNDLE_BYTES:
        raise EncryptedBackupError("BACKUP_BUNDLE_TOO_LARGE")
    try:
        with zipfile.ZipFile(io.BytesIO(archive_raw), "r") as archive:
            names = archive.namelist()
            allowed = {"manifest.json"} | _REQUIRED_FILES | _OPTIONAL_FILES
            if len(names) != len(set(names)) or set(names) - allowed:
                raise EncryptedBackupError("BACKUP_ARCHIVE_CONTENT_INVALID")
            if not _REQUIRED_FILES.issubset(set(names)) or "manifest.json" not in names:
                raise EncryptedBackupError("BACKUP_ARCHIVE_INCOMPLETE")
            total_size = sum(info.file_size for info in archive.infolist())
            if total_size > _MAX_BUNDLE_BYTES:
                raise EncryptedBackupError("BACKUP_ARCHIVE_EXPANSION_LIMIT")
            files = {name: archive.read(name) for name in names if name != "manifest.json"}
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
    except EncryptedBackupError:
        raise
    except Exception as exc:
        raise EncryptedBackupError("BACKUP_ARCHIVE_INVALID") from exc

    if (
        not isinstance(manifest, dict)
        or manifest.get("format") != "personal-ai-brain-backup"
        or manifest.get("version") != _VERSION
        or not isinstance(manifest.get("files"), dict)
        or set(manifest["files"]) != set(files)
    ):
        raise EncryptedBackupError("BACKUP_MANIFEST_INVALID")
    for name, raw in files.items():
        entry = manifest["files"].get(name)
        if not isinstance(entry, dict):
            raise EncryptedBackupError("BACKUP_MANIFEST_INVALID")
        digest = hashlib.sha256(raw).hexdigest()
        if entry.get("size_bytes") != len(raw) or not hmac.compare_digest(str(entry.get("sha256", "")), digest):
            raise EncryptedBackupError("BACKUP_CONTENT_CHECKSUM_MISMATCH")
    _validate_memory(files["memory.json"])
    _validate_tasks(files["tasks.json"])
    if "module_state.json" in files:
        _validate_modules(files["module_state.json"])
    return {"manifest": manifest, "files": files}


def inspect_encrypted_backup(encrypted_file: str, passphrase: str) -> dict:
    """Authenticate and validate an encrypted backup; return metadata only."""
    raw = _read_source(encrypted_file, "ENCRYPTED_BACKUP", max_bytes=_MAX_BUNDLE_BYTES + _MAX_HEADER_BYTES + 32)
    archive = _validate_archive(_decrypt(raw, passphrase))
    return {
        "ok": True,
        "created_at": archive["manifest"].get("created_at"),
        "files": sorted(archive["files"]),
        "encrypted_bytes": len(raw),
        "authenticated": True,
    }


def decrypt_backup_to_directory(
    encrypted_file: str,
    destination_dir: str,
    passphrase: str,
) -> dict:
    """Decrypt to a new private staging directory; never restore live stores."""
    raw = _read_source(encrypted_file, "ENCRYPTED_BACKUP", max_bytes=_MAX_BUNDLE_BYTES + _MAX_HEADER_BYTES + 32)
    archive = _validate_archive(_decrypt(raw, passphrase))
    target = os.path.abspath(destination_dir)
    if os.path.lexists(target):
        raise EncryptedBackupError("STAGING_DIRECTORY_ALREADY_EXISTS")
    try:
        os.makedirs(target, mode=0o700, exist_ok=False)
        for name, content in archive["files"].items():
            path = os.path.join(target, name)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        return {
            "ok": True,
            "staging_directory": target,
            "restored_files": sorted(archive["files"]),
            "live_stores_modified": False,
        }
    except Exception as exc:
        shutil.rmtree(target, ignore_errors=True)
        if isinstance(exc, EncryptedBackupError):
            raise
        raise EncryptedBackupError("BACKUP_STAGING_WRITE_FAILED") from exc
