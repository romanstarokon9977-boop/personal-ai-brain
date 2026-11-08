"""Read-only unified catalog view over the existing ToolRegistry."""
from __future__ import annotations

from typing import Any

from autonomy_controller import decide


def build_tool_catalog(registry: Any) -> list[dict]:
    """Describe registered tools and their actual authorization decision.

    No permission is inferred from descriptions. The existing autonomy policy
    remains authoritative; this function is inventory-only.
    """
    if registry is None or not callable(getattr(registry, "all_tools", None)):
        return []
    catalog = []
    for tool in registry.all_tools():
        name = getattr(tool, "name", None)
        if not isinstance(name, str) or not name:
            continue
        decision = decide(name, {}, registry)
        risk = getattr(getattr(tool, "risk", None), "value", "INVALID")
        source = getattr(getattr(tool, "source", None), "value", "INVALID")
        catalog.append({
            "name": name,
            "description": str(getattr(tool, "description", "") or ""),
            "capability": str(getattr(tool, "capability", "") or ""),
            "source": source,
            "risk": risk,
            "parameters": getattr(tool, "parameters", {}) if isinstance(getattr(tool, "parameters", {}), dict) else {},
            "authorization": decision.decision.value,
            "authorization_reason": decision.reason,
            "requires_user_confirmation": decision.decision.value == "CONFIRM",
            "limitations": [
                "Catalog metadata is descriptive; it does not grant execution permission.",
                "Path checks, module state, tool-specific validation and postcondition verification remain separate controls.",
            ],
        })
    return sorted(catalog, key=lambda item: item["name"])


def get_tool_entry(registry: Any, name: str) -> dict | None:
    if not isinstance(name, str) or not name:
        return None
    return next((item for item in build_tool_catalog(registry) if item["name"] == name), None)
