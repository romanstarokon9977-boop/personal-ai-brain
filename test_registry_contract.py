#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Registry Contract Test — проверяет, что ToolRegistry выдаёт
контракт, совместимый с brain.py get_tool_definitions().

НЕ импортирует brain.py. НЕ изменяет brain.py.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from tool_registry import (
    create_default_registry, ToolSource, RiskLevel, ToolDefinition
)

passed = 0
failed = 0


def check(label: str, condition: bool, detail: str = ""):
    global passed, failed
    status = "✅" if condition else "❌"
    if condition:
        passed += 1
    else:
        failed += 1
    msg = f"  {status} {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)


print("=" * 64)
print("     REGISTRY CONTRACT TEST")
print("=" * 64)

reg = create_default_registry()
model_tools = reg.get_tools_for_model()
all_tools = reg.all_tools()

# ============================================================
# [A] Формат вывода для модели
# ============================================================
print("\n[A] Output Format (OpenAI-compatible)")

check("get_tools_for_model returns list", isinstance(model_tools, list))
check("All items are dicts", all(isinstance(t, dict) for t in model_tools))
check("All items have type=function",
      all(t.get("type") == "function" for t in model_tools))
check("All items have function.name",
      all("name" in t.get("function", {}) for t in model_tools))
check("All items have function.description",
      all("description" in t.get("function", {}) for t in model_tools))
check("All items have function.parameters",
      all("parameters" in t.get("function", {}) for t in model_tools))

# ============================================================
# [B] Дедупликация: Native побеждает MCP в каждой группе
# ============================================================
print("\n[B] Deduplication Contract")

model_names = {t["function"]["name"] for t in model_tools}

# Группы где Native должен победить
dedup_checks = [
    ("fs_read",   "read_file",       "read_text_file"),
    ("fs_edit",   "file_edit",       "edit_file"),
    ("fs_list",   "directory_list",  "list_directory"),
    ("fs_search", "file_search",     "search_files"),
]

for group, native_name, mcp_name in dedup_checks:
    check(f"{group}: native '{native_name}' IN model list",
          native_name in model_names)
    check(f"{group}: MCP '{mcp_name}' NOT in model list",
          mcp_name not in model_names)

# ============================================================
# [C] MCP-only инструменты ДОЛЖНЫ быть в модели
# ============================================================
print("\n[C] MCP-only Tools Present")

mcp_only_expected = [
    "directory_tree", "move_file", "create_directory",
    "get_file_info", "read_multiple_files", "list_allowed_directories",
]
for name in mcp_only_expected:
    check(f"MCP-only '{name}' in model list", name in model_names)

# ============================================================
# [D] Native-unique инструменты ДОЛЖНЫ быть в модели
# ============================================================
print("\n[D] Native-unique Tools Present")

native_unique = ["shell", "web_fetch", "read_pdf", "read_docx"]
for name in native_unique:
    check(f"Native-unique '{name}' in model list", name in model_names)

# ============================================================
# [E] MCP-дубликаты СОХРАНЕНЫ в Registry (для fallback)
# ============================================================
print("\n[E] MCP Duplicates Retained in Registry (Fallback Ready)")

mcp_dup_names = ["read_text_file", "edit_file", "list_directory", "search_files"]
for name in mcp_dup_names:
    t = reg.get(name)
    check(f"MCP dup '{name}' still in Registry", t is not None)
    if t:
        check(f"  └─ source=MCP", t.source == ToolSource.MCP)
        check(f"  └─ duplicate_group set", t.duplicate_group is not None)

# ============================================================
# [F] Общее количество
# ============================================================
print("\n[F] Counts")

# В модели: 12 native + 7 MCP-only = 19
expected_model_count = 19
check(f"Model sees exactly {expected_model_count} tools",
      len(model_tools) == expected_model_count,
      f"actual={len(model_tools)}")

# В Registry: все 23
check(f"Registry holds all 23 tools",
      len(all_tools) == 23,
      f"actual={len(all_tools)}")

# Разница = 4 MCP-дубликата, которые не видны модели
hidden = len(all_tools) - len(model_tools)
check(f"Hidden (fallback-ready) = 4", hidden == 4, f"actual={hidden}")

# ============================================================
# [G] Risk levels assigned correctly
# ============================================================
print("\n[G] Risk Levels")

risk_expectations = {
    "shell": RiskLevel.CRITICAL,
    "read_file": RiskLevel.LOW,
    "write_file": RiskLevel.MEDIUM,
    "file_edit": RiskLevel.MEDIUM,
    "directory_list": RiskLevel.LOW,
    "file_search": RiskLevel.LOW,
    "web_fetch": RiskLevel.HIGH,
    "move_file": RiskLevel.HIGH,
    "create_directory": RiskLevel.MEDIUM,
    "directory_tree": RiskLevel.LOW,
    "get_file_info": RiskLevel.LOW,
}

for name, expected_risk in risk_expectations.items():
    t = reg.get(name)
    if t:
        check(f"'{name}' risk={expected_risk.value}",
              t.risk == expected_risk,
              f"actual={t.risk.value}")
    else:
        check(f"'{name}' exists", False, "NOT FOUND")

# ============================================================
# [H] Capability mapping
# ============================================================
print("\n[H] Capability Mapping")

cap_expectations = {
    "read_file": "filesystem.read",
    "write_file": "filesystem.write",
    "file_edit": "filesystem.edit",
    "directory_list": "filesystem.list",
    "file_search": "filesystem.search",
    "directory_tree": "filesystem.tree",
    "move_file": "filesystem.move",
    "create_directory": "filesystem.mkdir",
    "get_file_info": "filesystem.info",
    "shell": "system.shell",
    "web_fetch": "network.fetch",
}

for name, expected_cap in cap_expectations.items():
    t = reg.get(name)
    if t:
        check(f"'{name}' capability='{expected_cap}'",
              t.capability == expected_cap,
              f"actual={t.capability}")
    else:
        check(f"'{name}' exists", False, "NOT FOUND")

# ============================================================
# [I] Source correctness
# ============================================================
print("\n[I] Source Correctness")

for t in all_tools:
    expected = ToolSource.NATIVE if t.priority == 100 else ToolSource.MCP
    check(f"'{t.name}' source={expected.value}",
          t.source == expected,
          f"actual={t.source.value}")

# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 64)
total = passed + failed
print(f"  RESULTS: {passed}/{total} passed, {failed} failed")
if failed == 0:
    print("  🎉 REGISTRY CONTRACT VERIFIED")
else:
    print(f"  ⚠️  {failed} CONTRACT VIOLATIONS")
print("=" * 64)
