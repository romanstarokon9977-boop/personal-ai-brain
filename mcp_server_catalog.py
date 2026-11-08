"""Declarative MCP server catalog. Registration never starts a process."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MCPServerSpec:
    server_id: str
    display_name: str
    transport: str
    command: str
    args: tuple[str, ...]
    required_permissions: tuple[str, ...]
    enabled: bool = False


class MCPServerCatalog:
    def __init__(self):
        self._servers: dict[str, MCPServerSpec] = {}

    def register(self, spec: MCPServerSpec) -> None:
        if not isinstance(spec, MCPServerSpec):
            raise TypeError("INVALID_MCP_SERVER_SPEC")
        if not re.fullmatch(r"[a-z][a-z0-9_-]{1,47}", spec.server_id):
            raise ValueError("INVALID_MCP_SERVER_ID")
        if spec.enabled is not False:\n            raise ValueError("MCP_SERVER_MUST_START_DISABLED")\n        if not isinstance(spec.display_name, str) or not spec.display_name.strip():\n            raise ValueError("INVALID_MCP_DISPLAY_NAME")\n        if spec.transport != "stdio":
            raise ValueError("UNSUPPORTED_MCP_TRANSPORT")
        if not spec.command or not isinstance(spec.command, str):
            raise ValueError("INVALID_MCP_COMMAND")
        if not isinstance(spec.args, tuple) or any(not isinstance(x, str) for x in spec.args):
            raise ValueError("INVALID_MCP_ARGS")
        if not isinstance(spec.required_permissions, tuple) or any(not isinstance(x, str) or not x for x in spec.required_permissions):
            raise ValueError("INVALID_MCP_PERMISSIONS")
        # Existing registrations cannot be silently replaced.
        if spec.server_id in self._servers:
            raise ValueError("MCP_SERVER_ALREADY_REGISTERED")
        self._servers[spec.server_id] = spec

    def get(self, server_id: str):
        return self._servers.get(server_id)

    def list_servers(self) -> list[dict]:
        return [
            {
                "server_id": item.server_id,
                "display_name": item.display_name,
                "transport": item.transport,
                "command": item.command,
                "args": list(item.args),
                "required_permissions": list(item.required_permissions),
                "enabled": item.enabled,
                "activation_requires_confirmation": True,
                "started": False,
            }
            for item in sorted(self._servers.values(), key=lambda x: x.server_id)
        ]
