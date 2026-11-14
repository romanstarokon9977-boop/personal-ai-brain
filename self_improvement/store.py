"""Bounded, private stores for quality events and verified solutions."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

_MAX_STORE_BYTES = 2_000_000
_MAX_RECORDS = 5000
_SOLUTION_STATUSES = {"CANDIDATE", "VERIFIED", "DEPRECATED", "REJECTED"}


def _write_private_json(path: str, payload: dict) -> None:
    parent = os.path.dirname(path) or os.curdir
    if not os.path.isdir(parent):
        raise ValueError("STORE_PARENT_MISSING")
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if len(encoded.encode("utf-8")) > _MAX_STORE_BYTES:
        raise ValueError("STORE_TOO_LARGE")
    fd, temp_path = tempfile.mkstemp(prefix=".self-improvement-", suffix=".tmp", dir=parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def _read_json(path: str, expected_key: str) -> dict:
    if not os.path.exists(path):
        return {"version": 1, expected_key: []}
    try:
        if os.path.getsize(path) > _MAX_STORE_BYTES:
            raise ValueError("STORE_TOO_LARGE")
        with open(path, "r", encoding="utf-8") as stream:
            data = json.load(stream)
    except ValueError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("STORE_UNREADABLE") from exc
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get(expected_key), list):
        raise ValueError("INVALID_STORE_SCHEMA")
    if len(data[expected_key]) > _MAX_RECORDS:
        raise ValueError("STORE_RECORD_LIMIT")
    return data


class ImprovementEventStore:
    """Explicit event capture; never hooks or scrapes conversation history."""

    def __init__(self, path: str):
        if not isinstance(path, str) or not path.strip():
            raise ValueError("INVALID_STORE_PATH")
        self.path = os.path.abspath(os.path.expanduser(path))

    def add(self, category: str, outcome: str, source: str,
            evidence_code: str = "") -> dict:
        if not isinstance(category, str) or not category.strip() or len(category) > 80:
            raise ValueError("INVALID_EVENT_CATEGORY")
        if outcome not in {"pass", "fail", "uncertain", "user_preference"}:
            raise ValueError("INVALID_EVENT_OUTCOME")
        if not isinstance(source, str) or not source.strip() or len(source) > 80:
            raise ValueError("INVALID_EVENT_SOURCE")
        if not isinstance(evidence_code, str) or len(evidence_code) > 120:
            raise ValueError("INVALID_EVIDENCE_CODE")
        data = _read_json(self.path, "events")
        if len(data["events"]) >= _MAX_RECORDS:
            raise ValueError("EVENT_LIMIT_REACHED")
        event = {
            "id": len(data["events"]) + 1,
            "category": category.strip().upper(),
            "outcome": outcome,
            "source": source.strip(),
            "evidence_code": evidence_code.strip(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        data["events"].append(event)
        _write_private_json(self.path, data)
        return dict(event)

    def list_events(self) -> list[dict]:
        return [dict(item) for item in _read_json(self.path, "events")["events"]]


class SolutionLibrary:
    """Stores reusable knowledge, not executable code or permission grants."""

    def __init__(self, path: str):
        if not isinstance(path, str) or not path.strip():
            raise ValueError("INVALID_STORE_PATH")
        self.path = os.path.abspath(os.path.expanduser(path))

    def add_candidate(self, name: str, problem: str, algorithm: str,
                      conditions: list[str], limitations: list[str]) -> dict:
        if not all(isinstance(x, str) and x.strip() for x in (name, problem, algorithm)):
            raise ValueError("INVALID_SOLUTION")
        for field, value in (("conditions", conditions), ("limitations", limitations)):
            if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
                raise ValueError("INVALID_" + field.upper())
        data = _read_json(self.path, "solutions")
        if len(data["solutions"]) >= _MAX_RECORDS:
            raise ValueError("SOLUTION_LIMIT_REACHED")
        if any(item.get("name", "").casefold() == name.casefold() for item in data["solutions"]):
            raise ValueError("DUPLICATE_SOLUTION")
        record = {
            "id": len(data["solutions"]) + 1,
            "name": name.strip()[:160],
            "problem": problem.strip()[:1000],
            "algorithm": algorithm.strip()[:4000],
            "conditions": [x[:500] for x in conditions[:30]],
            "limitations": [x[:500] for x in limitations[:30]],
            "status": "CANDIDATE",
            "verification": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        data["solutions"].append(record)
        _write_private_json(self.path, data)
        return dict(record)

    def verify(self, solution_id: int, evidence: dict) -> dict:
        if isinstance(solution_id, bool) or not isinstance(solution_id, int) or solution_id < 1:
            raise ValueError("INVALID_SOLUTION_ID")
        if not isinstance(evidence, dict):
            raise ValueError("VERIFICATION_EVIDENCE_REQUIRED")
        test_run = evidence.get("test_run")
        passed = evidence.get("passed")
        if not isinstance(test_run, str) or not test_run.strip() or passed is not True:
            raise ValueError("VERIFICATION_EVIDENCE_INSUFFICIENT")
        data = _read_json(self.path, "solutions")
        record = next((item for item in data["solutions"] if item.get("id") == solution_id), None)
        if record is None:
            raise ValueError("SOLUTION_NOT_FOUND")
        if record.get("status") != "CANDIDATE":
            raise ValueError("SOLUTION_NOT_CANDIDATE")
        record["status"] = "VERIFIED"
        record["verification"] = {
            "test_run": test_run[:300],
            "passed": True,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_private_json(self.path, data)
        return dict(record)

    def set_status(self, solution_id: int, status: str) -> dict:
        if isinstance(solution_id, bool) or not isinstance(solution_id, int) or solution_id < 1:
            raise ValueError("INVALID_SOLUTION_ID")
        if status not in {"DEPRECATED", "REJECTED"}:
            raise ValueError("INVALID_SOLUTION_STATUS")
        data = _read_json(self.path, "solutions")
        record = next((item for item in data["solutions"] if item.get("id") == solution_id), None)
        if record is None:
            raise ValueError("SOLUTION_NOT_FOUND")
        record["status"] = status
        _write_private_json(self.path, data)
        return dict(record)

    def list_solutions(self, status: str | None = None) -> list[dict]:
        if status is not None and status not in _SOLUTION_STATUSES:
            raise ValueError("INVALID_SOLUTION_STATUS")
        records = _read_json(self.path, "solutions")["solutions"]
        return [dict(item) for item in records if status is None or item.get("status") == status]
