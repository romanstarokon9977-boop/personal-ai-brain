"""Strictly read-only, privacy-preserving audit of the canonical memory JSON.

This module intentionally does not import Memory Core: its load path may create
or migrate files and may archive expired records. The public tool accepts no
path argument and reads only the fixed canonical store.
"""
from __future__ import annotations

import json
import os
import stat

from memory.lifecycle import is_expired


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
        or type(payload.get("version")) is not int
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
        explicit_type = entry.get("memory_type")
        if isinstance(explicit_type, str) and explicit_type in types:
            memory_type = explicit_type
        else:
            category = entry.get("category")
            memory_type = (
                "permanent"
                if isinstance(category, str)
                and category in {"preferences", "brain_info", "arch_rules", "dev_rules"}
                else "long_term"
            )
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



def inspect_memory_entry(entry_id: str) -> dict:
    """Inspect exactly one memory record and its provenance without writing."""
    import re

    if (
        not isinstance(entry_id, str)
        or not re.fullmatch(r"[0-9a-fA-F-]{4,36}", entry_id.strip())
    ):
        return {"ok": False, "result": None, "error": "MEMORY_ENTRY_ID_INVALID"}

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
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
        or type(payload.get("version")) is not int
        or payload.get("version") not in (1, 2)
        or not isinstance(payload.get("entries"), list)
    ):
        return {"ok": False, "result": None, "error": "MEMORY_STRUCTURE_INVALID"}
    if any(not isinstance(item, dict) for item in payload["entries"]):
        return {"ok": False, "result": None, "error": "MEMORY_ENTRY_INVALID"}

    query = entry_id.strip().lower()
    matches = [
        item for item in payload["entries"]
        if isinstance(item.get("id"), str) and item["id"].lower().startswith(query)
    ]
    if not matches:
        return {"ok": False, "result": None, "error": "MEMORY_ENTRY_NOT_FOUND"}
    if len(matches) != 1:
        return {
            "ok": False, "result": None,
            "error": "MEMORY_ENTRY_ID_AMBIGUOUS",
            "match_count": len(matches),
        }

    entry = matches[0]
    provenance = entry.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    history = entry.get("change_history")
    safe_history = []
    if isinstance(history, list):
        for change in history[-10:]:
            if not isinstance(change, dict):
                continue
            before = change.get("before")
            after = change.get("after")
            changed_fields = set()
            if isinstance(before, dict):
                changed_fields.update(str(key) for key in before)
            if isinstance(after, dict):
                changed_fields.update(str(key) for key in after)
            safe_history.append({
                "changed_at": change.get("changed_at"),
                "action": change.get("action"),
                "actor": change.get("actor"),
                "changed_fields": sorted(changed_fields),
            })

    confidence = entry.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        confidence = provenance.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        confidence = None

    result = {
        "id": entry.get("id"),
        "text": entry.get("text") if isinstance(entry.get("text"), str) else "",
        "category": entry.get("category", "facts"),
        "importance": entry.get("importance"),
        "source": entry.get("source", provenance.get("source")),
        "confidence": confidence,
        "memory_type": entry.get("memory_type"),
        "status": entry.get("status", "active"),
        "created_at": entry.get("created_at", entry.get("timestamp")),
        "updated_at": entry.get("updated_at", entry.get("timestamp")),
        "source_date": entry.get("source_date", provenance.get("source_date")),
        "provenance": {
            key: provenance.get(key)
            for key in ("source", "source_date", "confidence", "last_verified_at")
            if key in provenance
        },
        "topics": [
            topic for topic in entry.get("topics", [])[:30]
            if isinstance(topic, str)
        ] if isinstance(entry.get("topics"), list) else [],
        "change_history": safe_history,
        "change_history_total": len(history) if isinstance(history, list) else 0,
        "expires_at": entry.get("expires_at"),
        "review_at": entry.get("review_at"),
    }
    return {"ok": True, "result": result, "error": None}
