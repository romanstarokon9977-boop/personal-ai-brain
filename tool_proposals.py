"""Human-reviewed tool proposal and non-executable code-draft generation."""
from __future__ import annotations

import keyword
import re
from typing import Any

_ALLOWED_RISKS = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


def create_tool_proposal(name: str, purpose: str, capability: str, risk: str,
                         required_permissions: list[str], constraints: list[str],
                         acceptance_tests: list[str]) -> dict:
    """Validate requirements and return a proposal; never writes or activates it."""
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,47}", name) or keyword.iskeyword(name):
        raise ValueError("INVALID_TOOL_NAME")
    for field, value in (("purpose", purpose), ("capability", capability)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("INVALID_" + field.upper())
    if risk not in _ALLOWED_RISKS:
        raise ValueError("INVALID_RISK")
    for field, value in (("required_permissions", required_permissions),
                         ("constraints", constraints), ("acceptance_tests", acceptance_tests)):
        if not isinstance(value, list) or not value or any(not isinstance(x, str) or not x.strip() for x in value):
            raise ValueError("INVALID_" + field.upper())
    return {
        "status": "PROPOSED",
        "name": name,
        "purpose": purpose.strip(),
        "capability": capability.strip(),
        "risk": risk,
        "required_permissions": list(dict.fromkeys(required_permissions)),
        "constraints": list(dict.fromkeys(constraints)),
        "acceptance_tests": list(dict.fromkeys(acceptance_tests)),
        "approval_required": True,
        "implementation_applied": False,
        "activation_allowed": False,
    }


def render_python_stub(proposal: dict) -> str:
    """Prepare inert source text only; it is not written, imported or executed."""
    if not isinstance(proposal, dict) or proposal.get("status") != "PROPOSED":
        raise ValueError("INVALID_PROPOSAL")
    name = proposal.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,47}", name):
        raise ValueError("INVALID_TOOL_NAME")
    return (
        '"""Draft only. Requires review, tests and explicit approval before integration."""\n'
        f'def {name}(params):\n'
        '    """Unimplemented tool proposal; performs no side effects."""\n'
        '    return {"ok": False, "error": "NOT_IMPLEMENTED", "result": None}\n'
    )
