"""Strict, non-executing module manifest contract and dependency validator.

This module validates declarations only. It never imports entrypoints, enables
modules, registers tools, or grants permissions.
"""
from __future__ import annotations

import re
from typing import Any

SCHEMA_VERSION = 1
SUPPORTED_API_VERSION = 1
_MODULE_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
_ENTRYPOINT = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")

CAPABILITIES = frozenset({
    "filesystem.read", "filesystem.write",
    "memory.read", "memory.write",
    "tasks.read", "tasks.write",
    "network.fetch", "notifications.send",
    "process.execute", "publish", "models.call", "tools.register",
})
PERMISSIONS = CAPABILITIES
_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}
_PERMISSION_RISK = {
    "filesystem.read": "low", "memory.read": "low", "tasks.read": "low",
    "network.fetch": "medium", "models.call": "medium",
    "filesystem.write": "medium", "memory.write": "medium", "tasks.write": "medium",
    "notifications.send": "medium", "tools.register": "medium",
    "process.execute": "high", "publish": "high",
}
_ALLOWED_FIELDS = {
    "schema_version", "module_id", "name", "version", "api_version",
    "entrypoint", "description", "capabilities", "dependencies",
    "permissions", "risk", "auto_enable",
}


class ModuleManifestError(ValueError):
    """Module declaration is invalid or incompatible."""


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = _SEMVER.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise ModuleManifestError("INVALID_SEMVER")
    return tuple(int(part) for part in match.groups())


def validate_manifest(raw: Any) -> dict:
    if not isinstance(raw, dict):
        raise ModuleManifestError("MANIFEST_NOT_OBJECT")
    unknown = set(raw) - _ALLOWED_FIELDS
    if unknown:
        raise ModuleManifestError("UNKNOWN_MANIFEST_FIELDS")
    if type(raw.get("schema_version")) is not int or raw.get("schema_version") != SCHEMA_VERSION:
        raise ModuleManifestError("UNSUPPORTED_SCHEMA_VERSION")
    if type(raw.get("api_version")) is not int or raw.get("api_version") != SUPPORTED_API_VERSION:
        raise ModuleManifestError("UNSUPPORTED_MODULE_API")
    module_id = raw.get("module_id")
    if not isinstance(module_id, str) or not _MODULE_ID.fullmatch(module_id):
        raise ModuleManifestError("INVALID_MODULE_ID")
    name = raw.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        raise ModuleManifestError("INVALID_MODULE_NAME")
    _version_tuple(raw.get("version"))
    entrypoint = raw.get("entrypoint")
    if (
        not isinstance(entrypoint, str)
        or not _ENTRYPOINT.fullmatch(entrypoint)
        or ".." in entrypoint
    ):
        raise ModuleManifestError("INVALID_ENTRYPOINT")
    description = raw.get("description")
    if not isinstance(description, str) or not 8 <= len(description.strip()) <= 500:
        raise ModuleManifestError("INVALID_DESCRIPTION")

    capabilities = raw.get("capabilities")
    permissions = raw.get("permissions")
    if not isinstance(capabilities, list) or not isinstance(permissions, list):
        raise ModuleManifestError("CAPABILITIES_AND_PERMISSIONS_REQUIRED")
    if any(not isinstance(item, str) for item in capabilities + permissions):
        raise ModuleManifestError("INVALID_CAPABILITY_OR_PERMISSION")
    if len(capabilities) != len(set(capabilities)) or len(permissions) != len(set(permissions)):
        raise ModuleManifestError("DUPLICATE_CAPABILITY_OR_PERMISSION")
    if set(capabilities) - CAPABILITIES or set(permissions) - PERMISSIONS:
        raise ModuleManifestError("UNKNOWN_CAPABILITY_OR_PERMISSION")
    if not set(capabilities).issubset(set(permissions)):
        raise ModuleManifestError("CAPABILITY_WITHOUT_PERMISSION")

    risk = raw.get("risk")
    if risk not in _RISK_ORDER:
        raise ModuleManifestError("INVALID_RISK_LEVEL")
    required_risk = max(
        (_RISK_ORDER[_PERMISSION_RISK[item]] for item in permissions),
        default=0,
    )
    if _RISK_ORDER[risk] < required_risk:
        raise ModuleManifestError("RISK_UNDERCLASSIFIED")
    if raw.get("auto_enable", False) is not False:
        raise ModuleManifestError("AUTO_ENABLE_FORBIDDEN")

    dependencies = raw.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise ModuleManifestError("INVALID_DEPENDENCIES")
    normalized_dependencies = []
    seen = set()
    for dependency in dependencies:
        if not isinstance(dependency, dict) or set(dependency) != {"module_id", "minimum_version"}:
            raise ModuleManifestError("INVALID_DEPENDENCY")
        dep_id = dependency["module_id"]
        if not isinstance(dep_id, str) or not _MODULE_ID.fullmatch(dep_id) or dep_id == module_id:
            raise ModuleManifestError("INVALID_DEPENDENCY_ID")
        _version_tuple(dependency["minimum_version"])
        if dep_id in seen:
            raise ModuleManifestError("DUPLICATE_DEPENDENCY")
        seen.add(dep_id)
        normalized_dependencies.append({
            "module_id": dep_id,
            "minimum_version": dependency["minimum_version"],
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "module_id": module_id,
        "name": name.strip(),
        "version": raw["version"],
        "api_version": SUPPORTED_API_VERSION,
        "entrypoint": entrypoint,
        "description": description.strip(),
        "capabilities": sorted(capabilities),
        "dependencies": sorted(normalized_dependencies, key=lambda item: item["module_id"]),
        "permissions": sorted(permissions),
        "risk": risk,
        "auto_enable": False,
    }


def validate_catalog(manifests: list[Any]) -> dict:
    """Validate dependency graph and return a dependency-first load proposal."""
    if not isinstance(manifests, list):
        raise ModuleManifestError("CATALOG_NOT_LIST")
    validated = [validate_manifest(item) for item in manifests]
    by_id = {}
    for manifest in validated:
        module_id = manifest["module_id"]
        if module_id in by_id:
            raise ModuleManifestError("DUPLICATE_MODULE_ID")
        by_id[module_id] = manifest

    for manifest in validated:
        for dependency in manifest["dependencies"]:
            target = by_id.get(dependency["module_id"])
            if target is None:
                raise ModuleManifestError("DEPENDENCY_MISSING")
            if _version_tuple(target["version"]) < _version_tuple(dependency["minimum_version"]):
                raise ModuleManifestError("DEPENDENCY_VERSION_UNSATISFIED")

    visiting = set()
    visited = set()
    order = []

    def visit(module_id: str):
        if module_id in visiting:
            raise ModuleManifestError("DEPENDENCY_CYCLE")
        if module_id in visited:
            return
        visiting.add(module_id)
        for dependency in by_id[module_id]["dependencies"]:
            visit(dependency["module_id"])
        visiting.remove(module_id)
        visited.add(module_id)
        order.append(module_id)

    for module_id in sorted(by_id):
        visit(module_id)
    return {
        "ok": True,
        "module_count": len(by_id),
        "dependency_order": order,
        "modules": [by_id[module_id] for module_id in order],
        "enabled": False,
        "executed": False,
    }
