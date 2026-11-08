"""Central risk-based authorization policy for model-requested tools.

The policy is deliberately conservative:
- AUTO is limited to explicitly named, read-only tools with LOW risk.
- CONFIRM covers every other registered tool.
- BLOCK covers unknown tools, invalid metadata, and forbidden capabilities.

This module has no UI or execution side effects. The caller owns confirmation.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from tool_registry import RiskLevel, ToolSource


class AutonomyDecision(str, Enum):
    AUTO = "AUTO"
    CONFIRM = "CONFIRM"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class AutonomyResult:
    decision: AutonomyDecision
    reason: str
    tool_name: str


# Exact allowlist: never infer automatic permission from LOW risk alone.
AUTO_READ_ONLY_TOOLS = frozenset({
    "read_file",
    "directory_list",
    "file_search",
    "read_pdf",
    "read_docx",
    "directory_tree",
    "get_file_info",
    "read_multiple_files",
    "list_allowed_directories",
    "read_text_file",
    "list_directory",
    "search_files",
    "self_inspection",
    "memory_audit",
    "git_inspect",
})

AUTO_READ_ONLY_CAPABILITIES = frozenset({
    "filesystem.read",
    "filesystem.list",
    "filesystem.search",
    "filesystem.read_pdf",
    "filesystem.read_docx",
    "filesystem.tree",
    "filesystem.info",
    "filesystem.multi_read",
    "security.discovery",
    "diagnostics.inspection",
    "memory.audit.read",
    "git.repository.inspect",
})

# These capabilities are never executable through model tool calling.
BLOCKED_CAPABILITIES = frozenset({
    "system.root",
    "security.bypass",
    "credential.export",
    "secret.read",
})


def decide(tool_name: str, params: Any, registry: Any) -> AutonomyResult:
    """Return AUTO, CONFIRM, or BLOCK using registry metadata and strict allowlists."""
    name = tool_name if isinstance(tool_name, str) else ""
    if not name or not isinstance(params, dict):
        return AutonomyResult(AutonomyDecision.BLOCK, "INVALID_TOOL_REQUEST", name)

    if registry is None or not callable(getattr(registry, "get", None)):
        return AutonomyResult(AutonomyDecision.BLOCK, "REGISTRY_UNAVAILABLE", name)

    definition = registry.get(name)
    if definition is None:
        return AutonomyResult(AutonomyDecision.BLOCK, "UNKNOWN_TOOL", name)

    capability = getattr(definition, "capability", None)
    risk = getattr(definition, "risk", None)
    if not isinstance(capability, str) or not capability:
        return AutonomyResult(AutonomyDecision.BLOCK, "INVALID_TOOL_CAPABILITY", name)
    if capability in BLOCKED_CAPABILITIES:
        return AutonomyResult(AutonomyDecision.BLOCK, "FORBIDDEN_CAPABILITY", name)
    if not isinstance(risk, RiskLevel):
        return AutonomyResult(AutonomyDecision.BLOCK, "INVALID_TOOL_RISK", name)
    if not isinstance(getattr(definition, "source", None), ToolSource):
        return AutonomyResult(AutonomyDecision.BLOCK, "INVALID_TOOL_SOURCE", name)

    # Test Runner is a bounded, fixed-whitelist operation. A task that
    # invokes run_tests is treated as authorization to run that test scope;
    # the runner still enforces its own whitelist, scope validation, and timeout.
    if (
        name == "run_tests"
        and capability == "test.run"
        and risk.value == "LOW"
        and definition.source == ToolSource.NATIVE
    ):
        return AutonomyResult(
            AutonomyDecision.AUTO, "LOW_RISK_BOUNDED_TEST_RUN", name
        )

    if (
        name in AUTO_READ_ONLY_TOOLS
        and capability in AUTO_READ_ONLY_CAPABILITIES
        and risk.value == "LOW"
    ):
        return AutonomyResult(AutonomyDecision.AUTO, "ALLOWLISTED_READ_ONLY_LOW_RISK", name)

    # Registered tools not explicitly proven read-only always require consent.
    return AutonomyResult(
        AutonomyDecision.CONFIRM,
        f"RISK_{risk.value}_REQUIRES_USER_CONFIRMATION",
        name,
    )
