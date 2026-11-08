"""Persistent, inert lifecycle management for proposed Brain tools.

This module stores proposal metadata only. It never writes source code, imports
modules, mutates ToolRegistry, changes module state, or activates tools.
Callers must enforce interactive human confirmation before approve/reject.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any

_STORE_VERSION = 1
_MAX_STORE_BYTES = 1_000_000
_MAX_PROPOSALS = 500
_RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
_FORBIDDEN_CAPABILITIES = {
    "system.root", "security.bypass", "credential.export", "secret.read",
}
_ALLOWED_STATUSES = {"PROPOSED", "APPROVED", "REJECTED", "IMPLEMENTATION_REQUESTED"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _registry_definitions(registry: Any) -> list[Any]:
    if registry is None or not callable(getattr(registry, "all_tools", None)):
        raise ValueError("REGISTRY_UNAVAILABLE")
    try:
        definitions = registry.all_tools()
    except Exception as exc:
        raise ValueError("REGISTRY_UNAVAILABLE") from exc
    if not isinstance(definitions, list):
        raise ValueError("INVALID_REGISTRY")
    return definitions


class ToolProposalManager:
    """Manage proposal metadata in an explicitly supplied JSON file.

    The store path is never inferred and parent directories are never created.
    The manager is intentionally not wired to runtime tool registration.
    """

    def __init__(self, store_path: str, registry: Any):
        if not isinstance(store_path, str) or not store_path.strip():
            raise ValueError("INVALID_STORE_PATH")
        self.store_path = os.path.abspath(os.path.expanduser(store_path))
        self.registry = registry
        self._definitions = _registry_definitions(registry)
        self._known_names = {
            item.name for item in self._definitions
            if isinstance(getattr(item, "name", None), str)
        }
        self._known_permissions = set(self._known_names)
        self._permission_risks: dict[str, str] = {}
        for item in self._definitions:
            name = getattr(item, "name", None)
            capability = getattr(item, "capability", None)
            risk = getattr(getattr(item, "risk", None), "value", None)
            if isinstance(risk, str) and risk in _RISK_ORDER:
                if isinstance(name, str):
                    self._permission_risks[name] = risk
                if isinstance(capability, str) and capability:
                    self._known_permissions.add(capability)
                    self._permission_risks[capability] = risk

    def _empty_store(self) -> dict:
        return {"version": _STORE_VERSION, "proposals": []}

    def _load(self) -> dict:
        if not os.path.exists(self.store_path):
            return self._empty_store()
        try:
            if os.path.getsize(self.store_path) > _MAX_STORE_BYTES:
                raise ValueError("STORE_TOO_LARGE")
            with open(self.store_path, "r", encoding="utf-8") as stream:
                data = json.load(stream)
        except ValueError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("STORE_UNREADABLE") from exc
        if (
            not isinstance(data, dict)
            or data.get("version") != _STORE_VERSION
            or not isinstance(data.get("proposals"), list)
            or len(data["proposals"]) > _MAX_PROPOSALS
        ):
            raise ValueError("INVALID_STORE_SCHEMA")
        seen_ids = set()
        for item in data["proposals"]:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("id"), str)
                or item["id"] in seen_ids
                or item.get("status") not in _ALLOWED_STATUSES
                or not isinstance(item.get("proposal"), dict)
            ):
                raise ValueError("INVALID_STORE_RECORD")
            if item["status"] == "IMPLEMENTATION_REQUESTED" and (
                not isinstance(item.get("implementation_requested_at"), str)
                or not item["implementation_requested_at"]
                or item["proposal"].get("implementation_applied") is not False
                or item["proposal"].get("activation_allowed") is not False
            ):
                raise ValueError("INVALID_IMPLEMENTATION_REQUEST_RECORD")
            seen_ids.add(item["id"])
        return data

    def _write(self, data: dict) -> None:
        parent = os.path.dirname(self.store_path) or os.curdir
        if not os.path.isdir(parent):
            raise ValueError("STORE_PARENT_MISSING")
        encoded = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        if len(encoded.encode("utf-8")) > _MAX_STORE_BYTES:
            raise ValueError("STORE_TOO_LARGE")
        fd, temp_path = tempfile.mkstemp(prefix=".tool-proposals-", suffix=".tmp", dir=parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self.store_path)
            try:
                os.chmod(self.store_path, 0o600)
            except OSError:
                pass
        except Exception:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise

    def _validate_proposal(self, proposal: dict) -> None:
        if not isinstance(proposal, dict) or proposal.get("status") != "PROPOSED":
            raise ValueError("INVALID_PROPOSAL")
        name = proposal.get("name")
        if not isinstance(name, str) or not name or name in self._known_names:
            raise ValueError("TOOL_NAME_CONFLICT_OR_INVALID")
        if proposal.get("risk") not in _RISK_ORDER:
            raise ValueError("INVALID_RISK")
        capability = proposal.get("capability")
        if not isinstance(capability, str) or not capability.strip():
            raise ValueError("INVALID_CAPABILITY")
        if capability in _FORBIDDEN_CAPABILITIES:
            raise ValueError("FORBIDDEN_CAPABILITY")
        execution_scope = proposal.get("execution_scope", "external_resources")
        if not isinstance(execution_scope, str) or execution_scope not in {"arguments_only", "external_resources"}:
            raise ValueError("INVALID_EXECUTION_SCOPE")
        permissions = proposal.get("required_permissions")
        if (
            not isinstance(permissions, list)
            or any(
                not isinstance(value, str) or not value.strip()
                or value not in self._known_permissions
                for value in permissions
            )
        ):
            raise ValueError("UNKNOWN_REQUIRED_PERMISSION")
        if execution_scope == "arguments_only" and permissions:
            raise ValueError("ARGUMENTS_ONLY_REQUIRES_EMPTY_PERMISSIONS")
        requested_risk = _RISK_ORDER[proposal["risk"]]
        for permission in permissions:
            permission_risk = self._permission_risks.get(permission)
            if permission_risk is not None and requested_risk < _RISK_ORDER[permission_risk]:
                raise ValueError("PROPOSAL_RISK_BELOW_PERMISSION_RISK")
        for field in ("purpose", "constraints", "acceptance_tests"):
            value = proposal.get(field)
            if field == "purpose":
                valid = isinstance(value, str) and bool(value.strip())
            else:
                valid = isinstance(value, list) and bool(value) and all(
                    isinstance(entry, str) and entry.strip() for entry in value
                )
            if not valid:
                raise ValueError("INVALID_" + field.upper())
        if proposal.get("implementation_applied") is not False:
            raise ValueError("IMPLEMENTATION_MUST_REMAIN_INERT")
        if proposal.get("activation_allowed") is not False:
            raise ValueError("ACTIVATION_MUST_REMAIN_DISABLED")
        if proposal.get("approval_required") is not True:
            raise ValueError("APPROVAL_REQUIRED")

    def create(self, proposal: dict) -> dict:
        """Persist a validated proposal as PROPOSED metadata only."""
        self._validate_proposal(proposal)
        data = self._load()
        if len(data["proposals"]) >= _MAX_PROPOSALS:
            raise ValueError("PROPOSAL_LIMIT_REACHED")
        if any(
            item["proposal"].get("name") == proposal["name"]
            for item in data["proposals"]
        ):
            raise ValueError("DUPLICATE_PROPOSAL_NAME")
        record = {
            "id": uuid.uuid4().hex,
            "status": "PROPOSED",
            "created_at": _utc_now(),
            "reviewed_at": None,
            "review_note": None,
            "proposal": json.loads(json.dumps(proposal, ensure_ascii=False)),
        }
        data["proposals"].append(record)
        self._write(data)
        return json.loads(json.dumps(record, ensure_ascii=False))

    def list_proposals(self, status: str | None = None) -> list[dict]:
        """Return copies of records; never exposes mutable store state."""
        if status is not None and status not in _ALLOWED_STATUSES:
            raise ValueError("INVALID_STATUS_FILTER")
        records = self._load()["proposals"]
        if status is not None:
            records = [item for item in records if item["status"] == status]
        return json.loads(json.dumps(records, ensure_ascii=False))

    def get(self, proposal_id: str) -> dict | None:
        if not isinstance(proposal_id, str) or not proposal_id:
            raise ValueError("INVALID_PROPOSAL_ID")
        for item in self._load()["proposals"]:
            if item["id"] == proposal_id:
                return json.loads(json.dumps(item, ensure_ascii=False))
        return None

    def review(self, proposal_id: str, decision: str, note: str = "") -> dict:
        """Record an explicit review decision; approval does not implement/activate."""
        if decision not in {"APPROVED", "REJECTED"}:
            raise ValueError("INVALID_REVIEW_DECISION")
        if not isinstance(note, str) or len(note) > 1000:
            raise ValueError("INVALID_REVIEW_NOTE")
        data = self._load()
        for item in data["proposals"]:
            if item["id"] == proposal_id:
                if item["status"] != "PROPOSED":
                    raise ValueError("PROPOSAL_ALREADY_REVIEWED")
                item["status"] = decision
                item["reviewed_at"] = _utc_now()
                item["review_note"] = note.strip() or None
                # Review is metadata only: these invariants never change.
                item["proposal"]["implementation_applied"] = False
                item["proposal"]["activation_allowed"] = False
                self._write(data)
                return json.loads(json.dumps(item, ensure_ascii=False))
        raise ValueError("PROPOSAL_NOT_FOUND")

    def request_implementation(self, proposal_id: str, note: str = "") -> dict:
        """Queue an explicitly requested implementation-preparation step.

        This is metadata only. It does not generate or write code, run tests,
        register a tool, grant permissions, or activate anything.
        """
        if not isinstance(proposal_id, str) or not proposal_id:
            raise ValueError("INVALID_PROPOSAL_ID")
        if not isinstance(note, str) or len(note) > 1000:
            raise ValueError("INVALID_IMPLEMENTATION_REQUEST_NOTE")
        data = self._load()
        for item in data["proposals"]:
            if item["id"] == proposal_id:
                if item["status"] != "APPROVED":
                    raise ValueError("IMPLEMENTATION_REQUIRES_APPROVED_PROPOSAL")
                proposal = item["proposal"]
                if (
                    proposal.get("implementation_applied") is not False
                    or proposal.get("activation_allowed") is not False
                ):
                    raise ValueError("IMPLEMENTATION_INVARIANT_VIOLATION")
                item["status"] = "IMPLEMENTATION_REQUESTED"
                item["implementation_requested_at"] = _utc_now()
                item["implementation_request_note"] = note.strip() or None
                self._write(data)
                return json.loads(json.dumps(item, ensure_ascii=False))
        raise ValueError("PROPOSAL_NOT_FOUND")
