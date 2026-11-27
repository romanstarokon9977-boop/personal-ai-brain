"""Read-only integrity inventory for Personal AI Brain runtime state.

The audit never repairs, rewrites, exports, or deletes data. It reports only
safe labels, status codes, sizes and SHA-256 fingerprints. Secret-bearing
configuration files are explicitly excluded from content inspection.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import stat
from typing import Callable, Dict, Optional

_MAX_INSPECT_BYTES = 64 * 1024 * 1024
_ALLOWED_TASK_STATUSES = {"pending", "active", "completed", "interrupted"}


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_payload(raw: bytes):
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return None


def validate_memory_payload(raw: bytes) -> bool:
    data = _json_payload(raw)
    if not isinstance(data, dict) or data.get("version") not in (1, 2):
        return False
    entries = data.get("entries")
    if not isinstance(entries, list):
        return False
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            return False
        identifier = entry.get("id")
        if identifier is not None:
            if not isinstance(identifier, str) or not identifier or identifier in seen:
                return False
            seen.add(identifier)
    return True


def validate_task_payload(raw: bytes) -> bool:
    data = _json_payload(raw)
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        return False
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        return False
    seen = set()
    for task in tasks:
        if not isinstance(task, dict):
            return False
        identifier = task.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            return False
        if task.get("status") not in _ALLOWED_TASK_STATUSES:
            return False
        seen.add(identifier)
    return True


def validate_module_state(raw: bytes) -> bool:
    data = _json_payload(raw)
    if not isinstance(data, dict):
        return False
    if set(data) != {"version", "updated_at", "disabled"}:
        return False
    if data.get("version") != 1:
        return False
    if not isinstance(data.get("updated_at"), str) or not data["updated_at"]:
        return False
    disabled = data.get("disabled")
    return (
        isinstance(disabled, list)
        and all(isinstance(item, str) and item for item in disabled)
        and len(disabled) == len(set(disabled))
    )


def inspect_file(
    label: str,
    path: str,
    *,
    validator: Optional[Callable[[bytes], bool]] = None,
    expected_sha256: Optional[str] = None,
) -> dict:
    """Inspect one explicitly supplied file without exposing its path/content."""
    result = {
        "label": str(label),
        "status": "UNKNOWN",
        "size_bytes": None,
        "sha256": None,
        "baseline": "NOT_CONFIGURED" if expected_sha256 is None else "NOT_CHECKED",
    }
    try:
        if os.path.islink(path):
            result["status"] = "UNSAFE_SYMLINK"
            return result
        metadata = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode):
            result["status"] = "NOT_REGULAR_FILE"
            return result
        result["size_bytes"] = metadata.st_size
        if metadata.st_size > _MAX_INSPECT_BYTES:
            result["status"] = "TOO_LARGE"
            return result
        with open(path, "rb") as handle:
            raw = handle.read(_MAX_INSPECT_BYTES + 1)
        if len(raw) > _MAX_INSPECT_BYTES:
            result["status"] = "TOO_LARGE"
            return result
        digest = _sha256(raw)
        result["sha256"] = digest
        if expected_sha256 is not None:
            if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
                result["status"] = "INVALID_BASELINE"
                result["baseline"] = "INVALID"
                return result
            if digest.lower() != expected_sha256.lower():
                result["status"] = "CHANGED"
                result["baseline"] = "MISMATCH"
                return result
            result["baseline"] = "MATCH"
        if validator is not None and not validator(raw):
            result["status"] = "INVALID"
            return result
        result["status"] = "OK"
        return result
    except FileNotFoundError:
        result["status"] = "MISSING"
    except PermissionError:
        result["status"] = "UNREADABLE"
    except OSError:
        result["status"] = "READ_ERROR"
    except Exception:
        result["status"] = "CHECK_ERROR"
    return result


def inspect_backup_directory(backup_dir: str) -> dict:
    """Verify every known memory snapshot and its SHA-256 sidecar."""
    result = {
        "status": "OK",
        "snapshot_count": 0,
        "verified_count": 0,
        "invalid_count": 0,
        "orphan_manifest_count": 0,
    }
    if not os.path.isdir(backup_dir):
        result["status"] = "NO_BACKUP_DIRECTORY"
        return result
    try:
        from memory.backup_restore import verify_snapshot

        snapshots = sorted(glob.glob(os.path.join(backup_dir, "brain_memory_*.json")))
        manifests = sorted(glob.glob(os.path.join(backup_dir, "brain_memory_*.json.sha256")))
        snapshot_set = {os.path.abspath(item) for item in snapshots}
        for manifest in manifests:
            source = manifest[:-7]
            if os.path.abspath(source) not in snapshot_set:
                result["orphan_manifest_count"] += 1
        for snapshot in snapshots:
            result["snapshot_count"] += 1
            if os.path.islink(snapshot) or os.path.islink(snapshot + ".sha256"):
                result["invalid_count"] += 1
                continue
            try:
                verify_snapshot(snapshot, backup_dir)
                result["verified_count"] += 1
            except Exception:
                result["invalid_count"] += 1
        if result["invalid_count"] or result["orphan_manifest_count"]:
            result["status"] = "INVALID_BACKUPS"
        elif not snapshots:
            result["status"] = "NO_SNAPSHOTS"
        return result
    except Exception:
        result["status"] = "CHECK_ERROR"
        return result


def collect_integrity_report(
    *,
    project_root: str,
    memory_file: str,
    task_file: str,
    module_state_file: str,
    backup_dir: str,
    baseline: Optional[Dict[str, str]] = None,
) -> dict:
    """Collect a read-only inventory; baseline hashes are supplied by caller."""
    baseline = baseline if isinstance(baseline, dict) else {}
    code_files = (
        ("brain", os.path.join(project_root, "brain.py")),
        ("tool_registry", os.path.join(project_root, "tool_registry.py")),
        ("verifier", os.path.join(project_root, "verifier.py")),
        ("memory_core", os.path.join(project_root, "memory", "memory_core.py")),
        ("task_manager", os.path.join(project_root, "task_manager.py")),
        ("module_manager", os.path.join(project_root, "module_manager.py")),
        ("self_inspection", os.path.join(project_root, "self_inspection.py")),
    )
    files = [
        inspect_file(label, path, expected_sha256=baseline.get(label))
        for label, path in code_files
    ]
    stores = [
        inspect_file("memory_store", memory_file, validator=validate_memory_payload),
        inspect_file("task_store", task_file, validator=validate_task_payload),
        inspect_file("module_state", module_state_file, validator=validate_module_state),
    ]
    backups = inspect_backup_directory(backup_dir)
    all_files = files + stores
    failures = [
        item for item in all_files
        if item["status"] not in {"OK", "MISSING"}
    ]
    missing_stores = [
        item["label"] for item in stores
        if item["status"] == "MISSING"
    ]
    warnings = []
    if any(item["baseline"] == "NOT_CONFIGURED" for item in files):
        warnings.append("CODE_BASELINE_NOT_CONFIGURED")
    if missing_stores:
        warnings.append("RUNTIME_STORE_MISSING")
    if backups["status"] in {"NO_BACKUP_DIRECTORY", "NO_SNAPSHOTS"}:
        warnings.append("BACKUP_SET_NOT_AVAILABLE")
    if backups["status"] not in {"OK", "NO_BACKUP_DIRECTORY", "NO_SNAPSHOTS"}:
        failures.append({"label": "memory_backups", "status": backups["status"]})

    return {
        "ok": not failures,
        "status": "FAIL" if failures else ("WARNING" if warnings else "OK"),
        "files": all_files,
        "backups": backups,
        "warnings": warnings,
        "failures": [
            {"label": item["label"], "status": item["status"]}
            for item in failures
        ],
        "secret_configuration": "SKIPPED_BY_POLICY",
        "read_only": True,
    }


def collect_runtime_integrity_report() -> dict:
    """Resolve standard Brain paths lazily and return a read-only report."""
    import memory.memory_core as memory_core
    import task_manager
    import module_manager

    project_root = os.path.dirname(os.path.abspath(memory_core.__file__))
    project_root = os.path.dirname(project_root)
    backup_dir = os.path.join(project_root, "backups_memory")
    return collect_integrity_report(
        project_root=project_root,
        memory_file=memory_core.MEMORY_FILE,
        task_file=str(task_manager.DEFAULT_STORE),
        module_state_file=module_manager.STATE_PATH,
        backup_dir=backup_dir,
    )
