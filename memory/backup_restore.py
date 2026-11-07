"""Verified memory snapshots and atomic restore operations."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time


class MemoryBackupError(Exception):
    """A memory snapshot is missing, corrupt, unsafe, or cannot be restored."""


def _validate_payload(raw: bytes) -> dict:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise MemoryBackupError("BACKUP_JSON_INVALID") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("version") not in (1, 2)
        or not isinstance(payload.get("entries"), list)
    ):
        raise MemoryBackupError("BACKUP_STRUCTURE_INVALID")
    identifiers = []
    for item in payload["entries"]:
        if not isinstance(item, dict):
            raise MemoryBackupError("BACKUP_ENTRY_INVALID")
        identifier = item.get("id")
        if identifier is not None:
            if not isinstance(identifier, str) or not identifier:
                raise MemoryBackupError("BACKUP_ENTRY_ID_INVALID")
            identifiers.append(identifier)
    if len(identifiers) != len(set(identifiers)):
        raise MemoryBackupError("BACKUP_DUPLICATE_ENTRY_ID")
    return payload


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_atomic(path: str, content: bytes) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".memory_snapshot_", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            dir_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def create_snapshot(memory_file: str, backup_dir: str, keep: int = 10) -> str:
    """Create a JSON-valid snapshot with a SHA-256 sidecar before a memory write."""
    if not os.path.isfile(memory_file):
        raise MemoryBackupError("MEMORY_SOURCE_MISSING")
    try:
        with open(memory_file, "rb") as handle:
            raw = handle.read()
        _validate_payload(raw)
    except MemoryBackupError:
        raise
    except Exception as exc:
        raise MemoryBackupError("MEMORY_SOURCE_READ_FAILED") from exc

    os.makedirs(backup_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    name = f"brain_memory_{stamp}.json"
    target = os.path.join(backup_dir, name)
    if os.path.exists(target) or os.path.exists(target + ".sha256"):
        import uuid
        name = f"brain_memory_{stamp}_{uuid.uuid4().hex[:6]}.json"
        target = os.path.join(backup_dir, name)

    _write_atomic(target, raw)
    digest = _sha256(raw)
    manifest = f"{digest}  {name}\n".encode("utf-8")
    try:
        _write_atomic(target + ".sha256", manifest)
        with open(target, "rb") as handle:
            copied = handle.read()
        if _sha256(copied) != digest:
            raise MemoryBackupError("SNAPSHOT_COPY_CHECKSUM_MISMATCH")
        _validate_payload(copied)
    except Exception:
        for path in (target, target + ".sha256"):
            try:
                os.unlink(path)
            except OSError:
                pass
        raise

    snapshots = sorted(
        os.path.join(backup_dir, item)
        for item in os.listdir(backup_dir)
        if item.startswith("brain_memory_") and item.endswith(".json")
    )
    for old in snapshots[:max(0, len(snapshots) - max(1, int(keep)))]:
        for path in (old, old + ".sha256"):
            try:
                os.unlink(path)
            except OSError:
                pass
    return target


def verify_snapshot(backup_file: str, backup_dir: str) -> dict:
    """Verify path confinement, SHA-256 sidecar, JSON schema, and entry IDs."""
    root = os.path.realpath(backup_dir)
    target = os.path.realpath(backup_file)
    if os.path.commonpath((root, target)) != root or os.path.dirname(target) != root:
        raise MemoryBackupError("BACKUP_PATH_OUTSIDE_BACKUP_DIR")
    if not target.endswith(".json") or not os.path.isfile(target):
        raise MemoryBackupError("BACKUP_FILE_NOT_FOUND")
    try:
        with open(target, "rb") as handle:
            raw = handle.read()
        with open(target + ".sha256", "r", encoding="utf-8") as handle:
            line = handle.read().strip()
    except Exception as exc:
        raise MemoryBackupError("BACKUP_OR_MANIFEST_READ_FAILED") from exc
    parts = line.split()
    if len(parts) != 2 or parts[1] != os.path.basename(target):
        raise MemoryBackupError("BACKUP_MANIFEST_INVALID")
    actual = _sha256(raw)
    if not __import__("hmac").compare_digest(actual, parts[0].lower()):
        raise MemoryBackupError("BACKUP_CHECKSUM_MISMATCH")
    payload = _validate_payload(raw)
    return {
        "ok": True,
        "sha256": actual,
        "version": payload["version"],
        "entries": len(payload["entries"]),
        "backup_file": target,
    }


def restore_snapshot(memory_file: str, backup_file: str, backup_dir: str, keep: int = 10) -> dict:
    """Verify first, snapshot the current valid target, then atomically restore."""
    verified = verify_snapshot(backup_file, backup_dir)
    with open(backup_file, "rb") as handle:
        raw = handle.read()
    payload = _validate_payload(raw)

    if os.path.exists(memory_file):
        try:
            with open(memory_file, "rb") as handle:
                current_raw = handle.read()
            _validate_payload(current_raw)
        except MemoryBackupError:
            pass
        else:
            create_snapshot(memory_file, backup_dir, keep=keep)

    _write_atomic(memory_file, raw)
    with open(memory_file, "rb") as handle:
        restored = handle.read()
    if _sha256(restored) != verified["sha256"]:
        raise MemoryBackupError("RESTORE_CHECKSUM_MISMATCH")
    restored_payload = _validate_payload(restored)
    if restored_payload != payload:
        raise MemoryBackupError("RESTORE_CONTENT_MISMATCH")
    return {
        "ok": True,
        "restored_sha256": verified["sha256"],
        "entries": len(restored_payload["entries"]),
        "backup_file": os.path.realpath(backup_file),
    }
