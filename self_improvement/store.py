"""Bounded, private stores for quality events and verified solutions."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
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


def _private_lock_path(path: str) -> str:
    """Return a stable lock path inside Termux's private home, not shared storage."""
    home = os.path.abspath(os.path.expanduser("~"))
    if not os.path.isdir(home):
        raise ValueError("PRIVATE_LOCK_HOME_UNAVAILABLE")
    lock_dir = os.path.join(home, ".cache", "personal_ai_brain", "locks")
    os.makedirs(lock_dir, mode=0o700, exist_ok=True)
    os.chmod(lock_dir, 0o700)
    identity = os.path.abspath(os.path.expanduser(path)).encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()
    return os.path.join(lock_dir, digest + ".lock")


@contextmanager
def _locked_store(path: str):
    """Serialize read-modify-write operations using a private-filesystem lock."""
    lock_path = _private_lock_path(path)
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(lock_path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


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

        # A successful write is not reported until the same file can be
        # reopened and the exact event is present in the persisted payload.
        persisted = _read_json(self.path, "events")["events"]
        if not any(
            item.get("id") == event["id"]
            and item.get("created_at") == event["created_at"]
            and item.get("evidence_code") == event["evidence_code"]
            and item.get("category") == event["category"]
            and item.get("outcome") == event["outcome"]
            for item in persisted
        ):
            raise ValueError("EVENT_WRITE_VERIFICATION_FAILED")
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
                      conditions: list[str], limitations: list[str],
                      compatibility: list[str] | None = None,
                      test_references: list[str] | None = None) -> dict:
        if not all(isinstance(x, str) and x.strip() for x in (name, problem, algorithm)):
            raise ValueError("INVALID_SOLUTION")
        compatibility = [] if compatibility is None else compatibility
        test_references = [] if test_references is None else test_references
        for field, value, max_items, max_length in (
            ("conditions", conditions, 30, 500),
            ("limitations", limitations, 30, 500),
            ("compatibility", compatibility, 20, 200),
            ("test_references", test_references, 20, 300),
        ):
            if (
                not isinstance(value, list)
                or len(value) > max_items
                or any(
                    not isinstance(item, str)
                    or not item.strip()
                    or len(item) > max_length
                    for item in value
                )
            ):
                raise ValueError("INVALID_" + field.upper())
        with _locked_store(self.path):
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
                "conditions": [x.strip() for x in conditions],
                "limitations": [x.strip() for x in limitations],
                "compatibility": [x.strip() for x in compatibility],
                "test_references": [x.strip() for x in test_references],
                "status": "CANDIDATE",
                "verification": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            data["solutions"].append(record)
            _write_private_json(self.path, data)
            persisted = _read_json(self.path, "solutions")["solutions"]
            saved = next((item for item in persisted if item.get("id") == record["id"]), None)
            if saved != record:
                raise ValueError("SOLUTION_WRITE_VERIFICATION_FAILED")
            return dict(saved)

    def verify(self, solution_id: int, evidence: dict) -> dict:
        if isinstance(solution_id, bool) or not isinstance(solution_id, int) or solution_id < 1:
            raise ValueError("INVALID_SOLUTION_ID")
        if not isinstance(evidence, dict) or not evidence:
            raise ValueError("VERIFICATION_EVIDENCE_REQUIRED")
        test_run = evidence.get("test_run")
        passed = evidence.get("passed")
        if not isinstance(test_run, str) or not test_run.strip() or passed is not True:
            raise ValueError("VERIFICATION_EVIDENCE_INSUFFICIENT")
        with _locked_store(self.path):
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
            persisted = _read_json(self.path, "solutions")["solutions"]
            saved = next((item for item in persisted if item.get("id") == solution_id), None)
            if saved != record:
                raise ValueError("SOLUTION_WRITE_VERIFICATION_FAILED")
            return dict(saved)

    def set_status(self, solution_id: int, status: str) -> dict:
        if isinstance(solution_id, bool) or not isinstance(solution_id, int) or solution_id < 1:
            raise ValueError("INVALID_SOLUTION_ID")
        if status not in {"DEPRECATED", "REJECTED"}:
            raise ValueError("INVALID_SOLUTION_STATUS")
        with _locked_store(self.path):
            data = _read_json(self.path, "solutions")
            record = next((item for item in data["solutions"] if item.get("id") == solution_id), None)
            if record is None:
                raise ValueError("SOLUTION_NOT_FOUND")
            record["status"] = status
            _write_private_json(self.path, data)
            persisted = _read_json(self.path, "solutions")["solutions"]
            saved = next((item for item in persisted if item.get("id") == solution_id), None)
            if saved != record:
                raise ValueError("SOLUTION_WRITE_VERIFICATION_FAILED")
            return dict(saved)

    def list_solutions(self, status: str | None = None) -> list[dict]:
        if status is not None and status not in _SOLUTION_STATUSES:
            raise ValueError("INVALID_SOLUTION_STATUS")
        with _locked_store(self.path):
            records = _read_json(self.path, "solutions")["solutions"]
            return [dict(item) for item in records if status is None or item.get("status") == status]

class ImprovementProposalStore:
    """Persistent inert proposals for module/architecture improvements."""

    def __init__(self, path: str):
        if not isinstance(path, str) or not path.strip():
            raise ValueError("INVALID_STORE_PATH")
        self.path = os.path.abspath(os.path.expanduser(path))

    def create(self, proposal: dict) -> dict:
        if not isinstance(proposal, dict) or proposal.get("status") != "PROPOSED":
            raise ValueError("INVALID_IMPROVEMENT_PROPOSAL")
        if proposal.get("implementation_applied") is not False or proposal.get("activation_allowed") is not False:
            raise ValueError("IMPROVEMENT_PROPOSAL_MUST_REMAIN_INERT")
        with _locked_store(self.path):
            data = _read_json(self.path, "proposals")
            if len(data["proposals"]) >= _MAX_RECORDS:
                raise ValueError("IMPROVEMENT_PROPOSAL_LIMIT_REACHED")
            record = dict(proposal)
            record["id"] = f"M-{len(data['proposals']) + 1:03d}"
            record["review_status"] = "PENDING"
            data["proposals"].append(record)
            _write_private_json(self.path, data)

            persisted = _read_json(self.path, "proposals")["proposals"]
            saved = next((item for item in persisted if item.get("id") == record["id"]), None)
            if saved != record:
                raise ValueError("IMPROVEMENT_PROPOSAL_WRITE_VERIFICATION_FAILED")
            return dict(saved)

    def list_proposals(self, review_status: str | None = None) -> list[dict]:
        if review_status is not None and review_status not in {"PENDING", "APPROVED", "REJECTED"}:
            raise ValueError("INVALID_IMPROVEMENT_REVIEW_STATUS")
        records = _read_json(self.path, "proposals")["proposals"]
        return [dict(item) for item in records if review_status is None or item.get("review_status") == review_status]

    def review(self, reference: str, decision: str) -> dict:
        if not isinstance(reference, str) or not reference.strip():
            raise ValueError("INVALID_IMPROVEMENT_REFERENCE")
        if decision not in {"APPROVED", "REJECTED"}:
            raise ValueError("INVALID_IMPROVEMENT_DECISION")
        with _locked_store(self.path):
            data = _read_json(self.path, "proposals")
            record = next((item for item in data["proposals"] if item.get("id") == reference), None)
            if record is None:
                raise ValueError("IMPROVEMENT_PROPOSAL_NOT_FOUND")
            if record.get("review_status") != "PENDING":
                raise ValueError("IMPROVEMENT_PROPOSAL_ALREADY_REVIEWED")
            record["review_status"] = decision
            record["reviewed_at"] = datetime.now(timezone.utc).isoformat()
            record["implementation_applied"] = False
            record["activation_allowed"] = False
            _write_private_json(self.path, data)

            persisted = _read_json(self.path, "proposals")["proposals"]
            saved = next((item for item in persisted if item.get("id") == reference), None)
            if saved != record:
                raise ValueError("IMPROVEMENT_PROPOSAL_REVIEW_VERIFICATION_FAILED")
            return dict(saved)
