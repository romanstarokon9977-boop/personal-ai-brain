"""Memory retention and provenance primitives.

Policy is intentionally non-destructive:
- permanent: no automatic expiry; retained until an explicit user action.
- long_term: retained indefinitely, reviewed after 365 days.
- temporary: archived after 7 days; never automatically hard-deleted.

Legacy entries are classified lazily. Merely reading memory does not rewrite it.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
from typing import Any

MEMORY_TYPES = {"permanent", "long_term", "temporary"}
RETENTION_DAYS = {"permanent": None, "long_term": None, "temporary": 7}
REVIEW_DAYS = {"permanent": None, "long_term": 365, "temporary": None}


def _now(value: datetime | None = None) -> datetime:
    return value or datetime.now()


def _stamp(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def _parse_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def infer_memory_type(entry: dict) -> str:
    explicit = entry.get("memory_type")
    if explicit in MEMORY_TYPES:
        return explicit
    category = entry.get("category")
    if category in {"preferences", "brain_info", "arch_rules", "dev_rules"}:
        return "permanent"
    return "long_term"


def initialize_entry_metadata(
    entry: dict,
    *,
    memory_type: str | None = None,
    source_date: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Add lifecycle/provenance metadata without discarding legacy fields."""
    if not isinstance(entry, dict):
        raise ValueError("INVALID_MEMORY_ENTRY")
    current = _now(now)
    current_stamp = _stamp(current)
    created_at = entry.get("created_at") or entry.get("timestamp") or current_stamp
    selected_type = memory_type or infer_memory_type(entry)
    if selected_type not in MEMORY_TYPES:
        raise ValueError("INVALID_MEMORY_TYPE")

    entry.setdefault("created_at", created_at)
    entry.setdefault("updated_at", entry.get("timestamp") or current_stamp)
    entry.setdefault("source_date", source_date or created_at)
    entry["memory_type"] = selected_type
    entry.setdefault("status", "active")
    entry.setdefault("change_history", [])

    confidence = entry.get("confidence", 1.0)
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        confidence = 0.0
    confidence = max(0.0, min(1.0, float(confidence)))
    entry["confidence"] = confidence

    source = entry.get("source", "unknown")
    provenance = entry.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    provenance.setdefault("source", source)
    provenance.setdefault("source_date", entry["source_date"])
    provenance.setdefault("confidence", confidence)
    entry["provenance"] = provenance

    if selected_type == "temporary":
        if not entry.get("expires_at"):
            base = _parse_date(created_at) or current
            entry["expires_at"] = _stamp(base + timedelta(days=RETENTION_DAYS["temporary"]))
        entry.pop("review_at", None)
    elif selected_type == "long_term":
        entry.pop("expires_at", None)
        if not entry.get("review_at"):
            base = _parse_date(created_at) or current
            entry["review_at"] = _stamp(base + timedelta(days=REVIEW_DAYS["long_term"]))
    else:
        entry.pop("expires_at", None)
        entry.pop("review_at", None)
    return entry


def update_entry_with_history(
    entry: dict,
    updates: dict,
    *,
    action: str = "update",
    actor: str = "user",
    now: datetime | None = None,
) -> bool:
    """Apply an update and append before/after provenance when values change."""
    if not isinstance(entry, dict) or not isinstance(updates, dict):
        raise ValueError("INVALID_MEMORY_UPDATE")
    current = _now(now)
    current_stamp = _stamp(current)
    initialize_entry_metadata(entry, now=current)
    before = {key: copy.deepcopy(entry.get(key)) for key in updates}
    changed = {key: value for key, value in updates.items() if before.get(key) != value}
    if not changed:
        return False
    history = entry.get("change_history")
    if not isinstance(history, list):
        history = []
    history.append({
        "changed_at": current_stamp,
        "action": str(action),
        "actor": str(actor),
        "before": {key: before[key] for key in changed},
        "after": copy.deepcopy(changed),
    })
    entry["change_history"] = history
    entry.update(copy.deepcopy(changed))
    entry["updated_at"] = current_stamp
    entry["timestamp"] = current_stamp
    if "source" in changed or "confidence" in changed:
        provenance = entry.get("provenance")
        if not isinstance(provenance, dict):
            provenance = {}
        provenance.update({
            "source": entry.get("source", "unknown"),
            "confidence": entry.get("confidence", 0.0),
            "last_verified_at": current_stamp,
        })
        entry["provenance"] = provenance
    return True


def is_expired(entry: dict, now: datetime | None = None) -> bool:
    if infer_memory_type(entry) != "temporary":
        return False
    expires = _parse_date(entry.get("expires_at"))
    if expires is None:
        created = _parse_date(entry.get("created_at") or entry.get("timestamp"))
        if created is None:
            return False
        expires = created + timedelta(days=RETENTION_DAYS["temporary"])
    current = _now(now)
    if expires.tzinfo is not None:
        expires = expires.replace(tzinfo=None)
    return expires <= current.replace(tzinfo=None)


def archive_expired_entries(entries: list, now: datetime | None = None) -> tuple[list, int]:
    """Return a copied list with expired temporary entries archived, never deleted."""
    if not isinstance(entries, list):
        raise ValueError("INVALID_MEMORY_ENTRIES")
    current = _now(now)
    result = copy.deepcopy(entries)
    archived = 0
    for entry in result:
        if not isinstance(entry, dict) or entry.get("status") in {"archived", "superseded"}:
            continue
        if is_expired(entry, current):
            update_entry_with_history(
                entry,
                {"status": "archived", "archived_at": _stamp(current)},
                action="retention_archive",
                actor="retention_policy",
                now=current,
            )
            archived += 1
    return result, archived


def active_entries(entries: list, now: datetime | None = None) -> list:
    """Filter archived, superseded, and expired records from model context."""
    current = _now(now)
    return [
        entry for entry in entries
        if isinstance(entry, dict)
        and entry.get("status", "active") not in {"archived", "superseded"}
        and not is_expired(entry, current)
    ]
