"""Privacy-preserving append-only audit journal for tool execution events.

Only authorization metadata and coarse outcomes are recorded. Tool arguments,
memory text, prompts, tool outputs, credentials and filesystem contents are
intentionally excluded.
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

_DEFAULT_PATH = os.path.join(
    os.path.expanduser("~"), ".personal_ai_brain", "audit", "actions.jsonl"
)
_LOCK = threading.Lock()
_SAFE_CODE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,79}")


def _code(value: object, fallback: str = "UNKNOWN") -> str:
    text = str(value or "")
    upper = text.upper()
    if any(marker in upper for marker in ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "API_KEY", "APIKEY")):
        return "REDACTED"
    if not _SAFE_CODE.fullmatch(text):
        return fallback
    return text.upper()


def record_tool_event(
    tool_name: str,
    decision: str,
    permission_source: str,
    authorization_reason: str,
    outcome: str,
    error_code: Optional[str] = None,
    elapsed_ms: Optional[int] = None,
    *,
    kind: str = "tool_execution",
    path: Optional[str] = None,
) -> dict:
    """Append one bounded metadata-only event; never serialize caller data."""
    if not isinstance(tool_name, str) or not tool_name.strip():
        return {"ok": False, "error": "INVALID_TOOL_NAME"}
    if elapsed_ms is not None and (
        isinstance(elapsed_ms, bool) or not isinstance(elapsed_ms, int) or elapsed_ms < 0
    ):
        elapsed_ms = None

    event = {
        "schema": 1,
        "event_id": uuid.uuid4().hex,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": _code(kind, "TOOL_EXECUTION"),
        "tool": _code(tool_name, "UNKNOWN_TOOL"),
        "decision": _code(decision),
        "permission_source": _code(permission_source),
        "authorization_reason": _code(authorization_reason),
        "outcome": "SUCCESS" if outcome == "SUCCESS" else "FAILED",
        "error_code": _code(error_code) if error_code else None,
        "elapsed_ms": elapsed_ms,
    }
    encoded = (json.dumps(event, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
    target = os.path.abspath(path or _DEFAULT_PATH)
    directory = os.path.dirname(target)

    try:
        with _LOCK:
            os.makedirs(directory, mode=0o700, exist_ok=True)
            try:
                os.chmod(directory, 0o700)
            except OSError:
                pass
            flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(target, flags, 0o600)
            try:
                try:
                    os.fchmod(fd, 0o600)
                except OSError:
                    pass
                written = os.write(fd, encoded)
                if written != len(encoded):
                    raise OSError("AUDIT_SHORT_WRITE")
                os.fsync(fd)
            finally:
                os.close(fd)
        return {"ok": True, "event_id": event["event_id"]}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}
