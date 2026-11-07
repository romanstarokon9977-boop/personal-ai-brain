"""Strictly read-only, privacy-preserving audit of the canonical memory JSON.

This module intentionally does not import Memory Core: its load path may create
or migrate files and may archive expired records. The public tool accepts no
path argument and reads only the fixed canonical store.
"""
from __future__ import annotations

import json
import os
import stat

from memory.lifecycle import infer_memory_type, is_expired


MEMORY_FILE = "/storage/emulated/0/Documents/AI_Brain/brain_memory.json"
MAX_MEMORY_BYTES = 8 * 1024 * 1024


def audit_memory() -> dict:
    """Return aggregate metadata only; never expose entry text or source values."""
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(MEMORY_FILE, flags)
    except FileNotFoundError:
        return {"ok": False, "result": None, "error": "MEMORY_FILE_NOT_FOUND"}
    except OSError:
        return {"ok": False, "result": None, "error": "MEMORY_FILE_OPEN_FAILED"}

    try:
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                return {"ok": False, "result": None, "error": "MEMORY_NOT_REGULAR_FILE"}
            if info.st_size > MAX_MEMORY_BYTES:
                return {"ok": False, "result": None, "error": "MEMORY_FILE_TOO_LARGE"}
            raw = handle.read(MAX_MEMORY_BYTES + 1)
    except OSError:
        return {"ok": False, "result": None, "error": "MEMORY_FILE_READ_FAILED"}

    if len(raw) > MAX_MEMORY_BYTES:
        return {"ok": False, "result": None, "error": "MEMORY_FILE_TOO_LARGE"}

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"ok": False, "result": None, "error": "MEMORY_JSON_INVALID"}

    if (
        not isinstance(payload, dict)
        or payload.get("version") not in (1, 2)
        or not isinstance(payload.get("entries"), list)
    ):
        return {"ok": False, "result": None, "error": "MEMORY_STRUCTURE_INVALID"}

    entries = payload["entries"]
    if any(not isinstance(entry, dict) for entry in entries):
        return {"ok": False, "result": None, "error": "MEMORY_ENTRY_INVALID"}

    types = {"permanent": 0, "long_term": 0, "temporary": 0}
    fields = {
        "created_at": 0,
        "updated_at": 0,
        "source_date": 0,
        "provenance": 0,
        "source": 0,
        "confidence": 0,
        "change_history": 0,
        "change_history_nonempty": 0,
    }
    statuses = {"active": 0, "archived": 0, "superseded": 0, "other": 0}
    missing_memory_type = 0
    expired_temporary_active = 0

    for entry in entries:
        memory_type = infer_memory_type(entry)
        types[memory_type] += 1
        if "memory_type" not in entry:
            missing_memory_type += 1

        for field in ("created_at", "updated_at", "source_date", "provenance",
                      "source", "confidence", "change_history"):
            if field in entry:
                fields[field] += 1
        history = entry.get("change_history")
        if isinstance(history, list) and history:
            fields["change_history_nonempty"] += 1

        status_value = entry.get("status", "active")
        if status_value in ("active", "archived", "superseded"):
            statuses[status_value] += 1
        else:
            statuses["other"] += 1

        if (
            status_value == "active"
            and memory_type == "temporary"
            and is_expired(entry)
        ):
            expired_temporary_active += 1

    result = {
        "memory_version": payload["version"],
        "total_entries": len(entries),
        "effective_memory_types": types,
        "entries_without_explicit_memory_type": missing_memory_type,
        "metadata_field_counts": fields,
        "status_counts": statuses,
        "expired_temporary_active": expired_temporary_active,
        "retention_policy": {
            "permanent": "no automatic expiry",
            "long_term": "retained; review after 365 days",
            "temporary": "archive after 7 days; never auto-delete",
        },
        "automatic_archive_during_load_memory": True,
        "audit_mode": "read_only",
    }
    return {"ok": True, "result": result, "error": None}
