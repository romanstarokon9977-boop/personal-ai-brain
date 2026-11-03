"""
Module Manager v0 — автономный модуль управления статусом инструментов Brain.

Не импортирует brain.py, tool_registry.py, mcp_bridge.py, self_inspection.py.
Не запускает MCP, не управляет процессами.
Не читает секреты и config.py.
Не создаёт module_state.json автоматически.

Спецификация: C.1.0.1 – C.1.0.6. Инварианты I1–I12.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
from typing import Optional

__all__ = [
    "state_health",
    "get_status",
    "is_enabled",
    "list_disabled",
    "enable",
    "disable",
    "recover_to_fresh",
    "load_state",
]


# === Paths (module-level; могут быть переопределены в тестах) ===

_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(_DIR, "module_state.json")
TMP_PATH = os.path.join(_DIR, "module_state.json.tmp")

SCHEMA_VERSION = 1


# === Internal state ===

_state_health: str = "first_run"
_disabled: Optional[set] = None
_loaded_once: bool = False


# === Helpers ===

def _utc_ts_compact() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256_file(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _choose_backup_name() -> str:
    base = STATE_PATH + ".corrupt_" + _utc_ts_compact()
    candidate = base
    n = 1
    while os.path.exists(candidate):
        candidate = f"{base}_{n}"
        n += 1
    return candidate


def _choose_stale_name() -> str:
    base = TMP_PATH + ".stale_" + _utc_ts_compact()
    candidate = base
    n = 1
    while os.path.exists(candidate):
        candidate = f"{base}_{n}"
        n += 1
    return candidate


# === Validation & serialization (single source of truth) ===

def _validate_state_bytes(raw: bytes) -> bool:
    """Full schema v0 validation. Strict top-level keys."""
    if not isinstance(raw, (bytes, bytearray)):
        return False
    try:
        text = raw.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        return False
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    if set(data.keys()) != {"version", "updated_at", "disabled"}:
        return False
    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        return False
    if version != SCHEMA_VERSION:
        return False
    updated_at = data.get("updated_at")
    if not isinstance(updated_at, str) or not updated_at:
        return False
    disabled = data.get("disabled")
    if not isinstance(disabled, list):
        return False
    seen = set()
    for item in disabled:
        if not isinstance(item, str) or not item:
            return False
        if item in seen:
            return False
        seen.add(item)
    return True


def _serialize_state(disabled_set) -> bytes:
    """Normalize: dedup + sort. Return UTF-8 bytes of valid v0 payload."""
    normalized = sorted(
        {x for x in disabled_set if isinstance(x, str) and x}
    )
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "version": SCHEMA_VERSION,
        "updated_at": now,
        "disabled": normalized,
    }
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return text.encode("utf-8")


# === load_state ===

def load_state(force: bool = False) -> None:
    """Re-derive state strictly from disk. Single source of truth."""
    global _state_health, _disabled, _loaded_once
    if not force and _loaded_once:
        return
    _loaded_once = True

    # 1. .tmp overrides everything -> corrupt
    if os.path.exists(TMP_PATH):
        _state_health = "corrupt"
        _disabled = None
        return

    # 2. target missing -> first_run
    if not os.path.exists(STATE_PATH):
        _state_health = "first_run"
        _disabled = set()
        return

    # 3. target unreadable
    try:
        with open(STATE_PATH, "rb") as f:
            raw = f.read()
    except OSError:
        _state_health = "unreadable"
        _disabled = None
        return

    # 4. schema validation
    if not _validate_state_bytes(raw):
        _state_health = "corrupt"
        _disabled = None
        return

    # 5. ok
    try:
        parsed = json.loads(raw.decode("utf-8"))
        _disabled = set(parsed["disabled"])
    except Exception:
        _state_health = "corrupt"
        _disabled = None
        return
    _state_health = "ok"


# === Public API ===

def state_health() -> str:
    return _state_health


def get_status(name: str) -> str:
    if not isinstance(name, str) or not name:
        return "indeterminate"
    if _state_health == "ok":
        if _disabled is not None and name in _disabled:
            return "disabled"
        return "enabled"
    if _state_health == "first_run":
        return "enabled"
    return "indeterminate"


def is_enabled(name: str) -> bool:
    return get_status(name) == "enabled"


def list_disabled():
    if _state_health in ("ok", "first_run"):
        return sorted(_disabled) if _disabled else []
    return None


# === Atomic write ===

def _cleanup_tmp_if_target_unchanged(old_sha, old_absent) -> None:
    target_exists = os.path.exists(STATE_PATH)
    if old_absent and not target_exists:
        _safe_unlink(TMP_PATH)
        return
    if (not old_absent) and old_sha is not None:
        if _sha256_file(STATE_PATH) == old_sha:
            _safe_unlink(TMP_PATH)


def _write_state_atomic(new_disabled: set) -> bool:
    """Atomic write. Returns True only on confirmed success.

    Never opens STATE_PATH in write modes. Only tmp + os.replace.
    Leaves .tmp on disk when target cannot be positively identified as old.
    """
    # Q1: pre-existing .tmp is anomaly
    if os.path.exists(TMP_PATH):
        return False

    try:
        data = _serialize_state(new_disabled)
    except Exception:
        return False

    old_absent = not os.path.exists(STATE_PATH)
    old_sha = None
    if not old_absent:
        old_sha = _sha256_file(STATE_PATH)
        if old_sha is None:
            return False

    # --- touched_fs becomes True ---

    # Write tmp + fsync
    try:
        with open(TMP_PATH, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        _cleanup_tmp_if_target_unchanged(old_sha, old_absent)
        return False

    # Read back and full-schema validate
    try:
        with open(TMP_PATH, "rb") as f:
            tmp_bytes = f.read()
    except OSError:
        return False
    if tmp_bytes != data:
        return False
    if not _validate_state_bytes(tmp_bytes):
        return False

    # Attempt atomic replace
    replace_error = None
    try:
        os.replace(TMP_PATH, STATE_PATH)
    except OSError as e:
        replace_error = e

    if replace_error is None:
        return True

    # --- Ambiguous result: classify by disk state ---
    tmp_present = os.path.exists(TMP_PATH)

    try:
        with open(STATE_PATH, "rb") as f:
            cur_bytes = f.read()
    except FileNotFoundError:
        if old_absent and tmp_present:
            _safe_unlink(TMP_PATH)
            return False
        return False
    except OSError:
        return False

    if old_sha is not None and hashlib.sha256(cur_bytes).hexdigest() == old_sha:
        if tmp_present:
            _safe_unlink(TMP_PATH)
        return False

    if cur_bytes == data:
        if tmp_present:
            return False  # fail-closed per I1
        return True

    return False


# === enable / disable ===

def _apply_op(name: str, action: str) -> bool:
    if _state_health in ("corrupt", "unreadable"):
        return False
    if not isinstance(name, str) or not name:
        return False
    if os.path.exists(TMP_PATH):
        return False

    current = set(_disabled) if _disabled is not None else set()
    new_set = set(current)
    if action == "enable":
        new_set.discard(name)
    elif action == "disable":
        new_set.add(name)
    else:
        return False

    if new_set == current:
        return True  # idempotent, no write, no touched_fs

    ok = _write_state_atomic(new_set)
    load_state(force=True)
    if not ok:
        return False
    if _state_health == "ok" and _disabled == new_set:
        return True
    return False


def enable(name: str) -> bool:
    return _apply_op(name, "enable")


def disable(name: str) -> bool:
    return _apply_op(name, "disable")


# === recover_to_fresh ===

def _try_validate_target() -> bool:
    try:
        with open(STATE_PATH, "rb") as f:
            raw = f.read()
    except (FileNotFoundError, OSError):
        return False
    return _validate_state_bytes(raw)


def _move_tmp_aside_if_present() -> bool:
    if not os.path.exists(TMP_PATH):
        return True
    stale = _choose_stale_name()
    try:
        os.rename(TMP_PATH, stale)
        return True
    except OSError:
        return False


def recover_to_fresh(confirm: bool = False) -> bool:
    if confirm is not True:
        return False
    if _state_health not in ("corrupt", "unreadable"):
        return False

    # Special case: valid target + stale .tmp -> keep target
    if _try_validate_target():
        if not _move_tmp_aside_if_present():
            load_state(force=True)
            return False
        load_state(force=True)
        return _state_health == "ok"

    # Full recovery. Move any .tmp aside first.
    if not _move_tmp_aside_if_present():
        load_state(force=True)
        return False

    # Classify current target
    target_bytes = None
    target_status = "missing"
    try:
        with open(STATE_PATH, "rb") as f:
            target_bytes = f.read()
        target_status = "readable"
    except FileNotFoundError:
        target_status = "missing"
    except OSError:
        target_status = "unreadable"

    fresh = _serialize_state(set())

    if target_status in ("readable", "missing"):
        # Branch A
        if target_status == "readable":
            backup = _choose_backup_name()
            try:
                with open(backup, "xb") as f:
                    f.write(target_bytes)
                    f.flush()
                    os.fsync(f.fileno())
            except OSError:
                load_state(force=True)
                return False
            try:
                with open(backup, "rb") as f:
                    bk = f.read()
            except OSError:
                load_state(force=True)
                return False
            if bk != target_bytes:
                load_state(force=True)
                return False

        try:
            with open(TMP_PATH, "wb") as f:
                f.write(fresh)
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            load_state(force=True)
            return False
        try:
            with open(TMP_PATH, "rb") as f:
                tmp_bytes = f.read()
        except OSError:
            load_state(force=True)
            return False
        if not _validate_state_bytes(tmp_bytes):
            load_state(force=True)
            return False

        try:
            os.replace(TMP_PATH, STATE_PATH)
        except OSError:
            load_state(force=True)
            return False
        load_state(force=True)
        return _state_health == "ok"

    # Branch B: unreadable
    try:
        with open(TMP_PATH, "wb") as f:
            f.write(fresh)
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        load_state(force=True)
        return False
    try:
        with open(TMP_PATH, "rb") as f:
            tmp_bytes = f.read()
    except OSError:
        load_state(force=True)
        return False
    if not _validate_state_bytes(tmp_bytes):
        load_state(force=True)
        return False

    backup = _choose_backup_name()
    try:
        os.rename(STATE_PATH, backup)
    except OSError:
        load_state(force=True)
        return False
    try:
        os.rename(TMP_PATH, STATE_PATH)
    except OSError:
        try:
            os.rename(backup, STATE_PATH)
        except OSError:
            pass
        load_state(force=True)
        return False

    load_state(force=True)
    return _state_health == "ok"


# === Bootstrap ===

load_state(force=True)
