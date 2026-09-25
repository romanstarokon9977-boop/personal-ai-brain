#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tool Registry — централизованный реестр инструментов Brain.
Независимый модуль. Не импортирует brain.py.

Этап 1: Регистрация, дедупликация, приоритеты, security policy.
"""

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable


# ============================================================
# Enums & Constants
# ============================================================

class ToolSource(Enum):
    NATIVE = "NATIVE"
    MCP = "MCP"


class RiskLevel(Enum):
    LOW = "LOW"           # read, list, search, info
    MEDIUM = "MEDIUM"     # write, edit, mkdir
    HIGH = "HIGH"         # move, network
    CRITICAL = "CRITICAL" # shell


# Разрешённая директория для security policy
_ALLOWED_BASE = os.path.realpath(os.path.expanduser("~/personal_ai_brain"))


# ============================================================
# ToolDefinition
# ============================================================

@dataclass
class ToolDefinition:
    name: str
    source: ToolSource
    capability: str
    priority: int = 50
    risk: RiskLevel = RiskLevel.LOW
    duplicate_group: Optional[str] = None
    executor: Optional[Callable] = None
    description: str = ""
    parameters: dict = field(default_factory=dict)


# ============================================================
# Security Policy
# ============================================================

def _resolve_path(p: str) -> str:
    """Канонический путь: expanduser → abspath → realpath."""
    return os.path.realpath(os.path.abspath(os.path.expanduser(p)))


def is_safe_path(p: str) -> bool:
    """
    Проверяет, что путь находится внутри _ALLOWED_BASE.
    Использует canonical path + containment (не просто startswith).
    """
    if not p or not isinstance(p, str):
        return False
    resolved = _resolve_path(p)
    # Containment: разрешённый базовый путь должен быть префиксом
    # Добавляем os.sep чтобы /home/brain не матчил /home/brain_evil
    return resolved == _ALLOWED_BASE or resolved.startswith(_ALLOWED_BASE + os.sep)


def security_check(tool_name: str, params: dict, registry: "ToolRegistry") -> tuple:
    """
    Проверяет параметры инструмента ДО выполнения.
    Возвращает (allowed: bool, reason: str).
    """
    tool = registry.get(tool_name)
    if tool is None:
        return False, f"UNKNOWN_TOOL: {tool_name}"

    # Проверяемые ключи путей
    path_keys = ("path", "source", "destination", "dir_path")
    # Для read_multiple_files: список путей
    list_path_keys = ("paths",)

    for key in path_keys:
        p = params.get(key)
        if p and isinstance(p, str):
            if not is_safe_path(p):
                return False, f"PATH_OUTSIDE_ALLOWED_DIR: {key}={p}"

    for key in list_path_keys:
        paths = params.get(key)
        if isinstance(paths, list):
            for i, p in enumerate(paths):
                if isinstance(p, str) and not is_safe_path(p):
                    return False, f"PATH_OUTSIDE_ALLOWED_DIR: {key}[{i}]={p}"

    return True, "ALLOWED"


# ============================================================
# ToolRegistry
# ============================================================

class ToolRegistry:
    """Централизованный реестр инструментов."""

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition):
        """Регистрирует инструмент."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Возвращает ToolDefinition по имени или None."""
        return self._tools.get(name)

    def all_tools(self) -> list[ToolDefinition]:
        """Все зарегистрированные инструменты."""
        return list(self._tools.values())

    def resolve(self, name: str) -> Optional[ToolDefinition]:
        """
        Находит инструмент по имени.
        В будущем: fallback по capability если основной недоступен.
        """
        return self._tools.get(name)

    def get_tools_for_model(self) -> list[dict]:
        """
        Возвращает дедуплицированный список инструментов для модели.
        Правило: в каждой duplicate_group выбирается инструмент
        с наивысшим priority. Инструменты без группы включаются всегда.
        Формат: OpenAI-compatible function definitions.
        """
        # Группируем по duplicate_group
        groups: dict[str, list[ToolDefinition]] = {}
        ungrouped: list[ToolDefinition] = []

        for tool in self._tools.values():
            if tool.duplicate_group:
                groups.setdefault(tool.duplicate_group, []).append(tool)
            else:
                ungrouped.append(tool)

        # Из каждой группы берём лучший по priority
        selected: list[ToolDefinition] = list(ungrouped)
        for group_tools in groups.values():
            best = max(group_tools, key=lambda t: t.priority)
            selected.append(best)

        # Сортируем: native сначала, потом по имени
        selected.sort(key=lambda t: (0 if t.source == ToolSource.NATIVE else 1, t.name))

        # Конвертируем в OpenAI format
        result = []
        for tool in selected:
            result.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters if tool.parameters else {
                        "type": "object", "properties": {}
                    },
                }
            })
        return result

    def security_check(self, tool_name: str, params: dict) -> tuple:
        """Проверка безопасности перед выполнением."""
        return security_check(tool_name, params, self)


# ============================================================
# Default Registration
# ============================================================

def create_default_registry() -> ToolRegistry:
    """Создаёт Registry с дефолтными Native + MCP инструментами."""
    reg = ToolRegistry()

    # --- NATIVE tools (priority=100) ---
    native_tools = [
        ToolDefinition(
            name="shell", source=ToolSource.NATIVE,
            capability="system.shell", priority=100,
            risk=RiskLevel.CRITICAL, duplicate_group=None,
            description="Выполнить разрешённую команду Termux.",
            parameters={"type": "object", "properties": {
                "command": {"type": "string", "description": "Команда Termux."}
            }, "required": ["command"]},
        ),
        ToolDefinition(
            name="read_file", source=ToolSource.NATIVE,
            capability="filesystem.read", priority=100,
            risk=RiskLevel.LOW, duplicate_group="fs_read",
            description="Прочитать содержимое текстового файла из разрешённой директории. Поддерживает чтение диапазона строк через start_line/end_line (1-based, включительно). Если диапазон не указан — читается весь файл. Используй этот инструмент для ЛЮБой задачи, требующей знать содержимое файла. Всегда вызывай этот инструмент вместо отказа или shell-команд, если нужны данные из файла.",
            parameters={"type": "object", "properties": {
                "path": {"type": "string", "description": "Путь к файлу."},
                "start_line": {"type": "integer", "description": "Первая строка диапазона (1-based, включительно). Необязательный."},
                "end_line": {"type": "integer", "description": "Последняя строка диапазона (1-based, включительно). Необязательный."},
            }, "required": ["path"]},
        ),
        ToolDefinition(
            name="write_file", source=ToolSource.NATIVE,
            capability="filesystem.write", priority=100,
            risk=RiskLevel.MEDIUM, duplicate_group="fs_write",
            description="Создать новый файл. Перезапись запрещена.",
            parameters={"type": "object", "properties": {
                "path": {"type": "string"}, "content": {"type": "string"}
            }, "required": ["path", "content"]},
        ),
        ToolDefinition(
            name="file_edit", source=ToolSource.NATIVE,
            capability="filesystem.edit", priority=100,
            risk=RiskLevel.MEDIUM, duplicate_group="fs_edit",
            description="Точечно заменить фрагмент файла.",
            parameters={"type": "object", "properties": {
                "path": {"type": "string"}, "old_text": {"type": "string"},
                "new_text": {"type": "string"}, "test": {"type": "string"}
            }, "required": ["path", "old_text", "new_text"]},
        ),
        ToolDefinition(
            name="directory_list", source=ToolSource.NATIVE,
            capability="filesystem.list", priority=100,
            risk=RiskLevel.LOW, duplicate_group="fs_list",
            description="Показать содержимое директории.",
            parameters={"type": "object", "properties": {
                "path": {"type": "string"}
            }, "required": ["path"]},
        ),
        ToolDefinition(
            name="file_search", source=ToolSource.NATIVE,
            capability="filesystem.search", priority=100,
            risk=RiskLevel.LOW, duplicate_group="fs_search",
            description="Найти текст в файле или директории.",
            parameters={"type": "object", "properties": {
                "query": {"type": "string"}, "path": {"type": "string"}
            }, "required": ["query", "path"]},
        ),
        ToolDefinition(
            name="web_fetch", source=ToolSource.NATIVE,
            capability="network.fetch", priority=100,
            risk=RiskLevel.HIGH, duplicate_group=None,
            description="Получить текст веб-страницы по URL.",
            parameters={"type": "object", "properties": {
                "url": {"type": "string"}, "max_chars": {"type": "integer"}
            }, "required": ["url"]},
        ),
        ToolDefinition(
            name="read_pdf", source=ToolSource.NATIVE,
            capability="filesystem.read_pdf", priority=100,
            risk=RiskLevel.LOW, duplicate_group=None,
            description="Прочитать текст из PDF.",
            parameters={"type": "object", "properties": {
                "path": {"type": "string"}
            }, "required": ["path"]},
        ),
        ToolDefinition(
            name="read_docx", source=ToolSource.NATIVE,
            capability="filesystem.read_docx", priority=100,
            risk=RiskLevel.LOW, duplicate_group=None,
            description="Прочитать текст из DOCX.",
            parameters={"type": "object", "properties": {
                "path": {"type": "string"}
            }, "required": ["path"]},
        ),
    ]

    # --- MCP tools (priority=50, только уникальные) ---
    mcp_tools = [
        ToolDefinition(
            name="directory_tree", source=ToolSource.MCP,
            capability="filesystem.tree", priority=50,
            risk=RiskLevel.LOW, duplicate_group=None,
            description="Рекурсивное дерево файлов (JSON).",
            parameters={"type": "object", "properties": {
                "path": {"type": "string"}
            }, "required": ["path"]},
        ),
        ToolDefinition(
            name="move_file", source=ToolSource.MCP,
            capability="filesystem.move", priority=50,
            risk=RiskLevel.HIGH, duplicate_group=None,
            description="Переместить или переименовать файл/директорию.",
            parameters={"type": "object", "properties": {
                "source": {"type": "string"}, "destination": {"type": "string"}
            }, "required": ["source", "destination"]},
        ),
        ToolDefinition(
            name="create_directory", source=ToolSource.MCP,
            capability="filesystem.mkdir", priority=50,
            risk=RiskLevel.MEDIUM, duplicate_group=None,
            description="Создать директорию.",
            parameters={"type": "object", "properties": {
                "path": {"type": "string"}
            }, "required": ["path"]},
        ),
        ToolDefinition(
            name="get_file_info", source=ToolSource.MCP,
            capability="filesystem.info", priority=50,
            risk=RiskLevel.LOW, duplicate_group=None,
            description="Метаданные файла/директории.",
            parameters={"type": "object", "properties": {
                "path": {"type": "string"}
            }, "required": ["path"]},
        ),
        ToolDefinition(
            name="read_multiple_files", source=ToolSource.MCP,
            capability="filesystem.multi_read", priority=50,
            risk=RiskLevel.LOW, duplicate_group=None,
            description="Прочитать несколько файлов одновременно.",
            parameters={"type": "object", "properties": {
                "paths": {"type": "array", "items": {"type": "string"}}
            }, "required": ["paths"]},
        ),
        ToolDefinition(
            name="list_allowed_directories", source=ToolSource.MCP,
            capability="security.discovery", priority=50,
            risk=RiskLevel.LOW, duplicate_group=None,
            description="Список разрешённых директорий MCP-сервера.",
            parameters={"type": "object", "properties": {}},
        ),
        # MCP-дубликаты (низкий приоритет, будут отфильтрованы)
        ToolDefinition(
            name="read_text_file", source=ToolSource.MCP,
            capability="filesystem.read", priority=50,
            risk=RiskLevel.LOW, duplicate_group="fs_read",
            description="Read text file (MCP).",
            parameters={"type": "object", "properties": {
                "path": {"type": "string"}
            }, "required": ["path"]},
        ),
        ToolDefinition(
            name="edit_file", source=ToolSource.MCP,
            capability="filesystem.edit", priority=50,
            risk=RiskLevel.MEDIUM, duplicate_group="fs_edit",
            description="Line-based edit (MCP).",
            parameters={"type": "object", "properties": {
                "path": {"type": "string"}, "edits": {"type": "array"}
            }, "required": ["path", "edits"]},
        ),
        ToolDefinition(
            name="list_directory", source=ToolSource.MCP,
            capability="filesystem.list", priority=50,
            risk=RiskLevel.LOW, duplicate_group="fs_list",
            description="List directory (MCP).",
            parameters={"type": "object", "properties": {
                "path": {"type": "string"}
            }, "required": ["path"]},
        ),
        ToolDefinition(
            name="search_files", source=ToolSource.MCP,
            capability="filesystem.search", priority=50,
            risk=RiskLevel.LOW, duplicate_group="fs_search",
            description="Search files by pattern (MCP).",
            parameters={"type": "object", "properties": {
                "pattern": {"type": "string"}, "path": {"type": "string"}
            }, "required": ["pattern", "path"]},
        ),
    ]

    # Device tools (Termux:API) - NATIVE priority=100, bez duplicate_group.
    # Audit #10 DEVICE_TOOLS: uvedomleniya i TTS (vidimy tol'ko API-backendam,
    # LOCAL idet mimo tools po early-return v run_with_tools).
    native_tools.extend([
        ToolDefinition(
            name="notify_user", source=ToolSource.NATIVE,
            capability="device.notify", priority=100,
            risk=RiskLevel.LOW, duplicate_group=None,
            description="Отправить системное уведомление Android. Используй, когда пользователь просит напомнить или уведомить о чём-то.",
            parameters={"type": "object", "properties": {
                "title": {"type": "string", "description": "Заголовок уведомления (до 64 символов)."},
                "message": {"type": "string", "description": "Текст уведомления (до 512 символов)."},
            }, "required": ["title", "message"]},
        ),
        ToolDefinition(
            name="briefing_set", source=ToolSource.NATIVE,
            capability="device.briefing_conf", priority=100,
            risk=RiskLevel.LOW, duplicate_group=None,
            description="Управление утренним брифингом: включить/выключить/сменить режим/задать час старта. Вызывай, когда пользователь просит включить, отключить брифинг или изменить его время.",
            parameters={"type": "object", "properties": {
                "action": {"type": "string", "description": "on | off | mode-auto | mode-morning_evening | set-morning", "enum": ["on", "off", "mode-auto", "mode-morning_evening", "set-morning"]},
                "hour": {"type": "string", "description": "Час старта утреннего брифинга (0-23), только для set-morning."},
            }, "required": ["action"]},
        ),
        ToolDefinition(
            name="run_tests", source=ToolSource.NATIVE,
            capability="test.run", priority=100,
            risk=RiskLevel.LOW, duplicate_group=None,
            description="Запуск тестов проекта (whitelist 9 файлов). scope=full — весь suite; scope=targeted + test=<имя из whitelist> — один тест. Возвращает JSON: passed/failed/env_fails (сеть/сервисы) / code_fails (логика). Вызывай для проверки работоспособности после изменений.",
            parameters={"type": "object", "properties": {
                "scope": {"type": "string", "enum": ["full", "targeted"], "description": "full = все 9 тестов; targeted = один"},
                "test": {"type": "string", "description": "имя тест-файла из whitelist, только для targeted"},
            }, "required": ["scope"]},
        ),
        ToolDefinition(
            name="tts_speak", source=ToolSource.NATIVE,
            capability="device.tts", priority=100,
            risk=RiskLevel.LOW, duplicate_group=None,
            description="Озвучить текст вслух через синтез речи Android. Используй только по явной просьбе пользователя озвучить ответ.",
            parameters={"type": "object", "properties": {
                "text": {"type": "string", "description": "Текст для озвучивания (до 512 символов)."},
            }, "required": ["text"]},
        ),
    ])

    for t in native_tools + mcp_tools:
        reg.register(t)

    return reg


# ============================================================
# Тестовый блок
# ============================================================

if __name__ == "__main__":
    print("=" * 64)
    print("       TOOL REGISTRY — ISOLATED TEST SUITE")
    print("=" * 64)

    reg = create_default_registry()
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

    # --- Test 1: Registration ---
    print("\n[1] Registration")
    all_t = reg.all_tools()
    check("Total tools registered", len(all_t) == 21, f"{len(all_t)}")

    # --- Test 2: Duplicate groups ---
    print("\n[2] Duplicate Groups")
    model_tools = reg.get_tools_for_model()
    model_names = {t["function"]["name"] for t in model_tools}

    # fs_read: native read_file (100) wins over MCP read_text_file (50)
    check("fs_read → native read_file selected",
          "read_file" in model_names and "read_text_file" not in model_names)

    # fs_edit: native file_edit wins over MCP edit_file
    check("fs_edit → native file_edit selected",
          "file_edit" in model_names and "edit_file" not in model_names)

    # fs_list: native directory_list wins over MCP list_directory
    check("fs_list → native directory_list selected",
          "directory_list" in model_names and "list_directory" not in model_names)

    # fs_search: native file_search wins over MCP search_files
    check("fs_search → native file_search selected",
          "file_search" in model_names and "search_files" not in model_names)

    # Unique MCP tools should be present
    check("MCP directory_tree included", "directory_tree" in model_names)
    check("MCP move_file included", "move_file" in model_names)
    check("MCP create_directory included", "create_directory" in model_names)
    check("MCP get_file_info included", "get_file_info" in model_names)
    check("MCP read_multiple_files included", "read_multiple_files" in model_names)

    # --- Test 3: Priority ordering ---
    print("\n[3] Priority & Ordering")
    check("Native tools before MCP in output",
          model_tools[0]["function"]["name"] in {"shell", "read_file", "write_file",
                                                   "file_edit", "directory_list",
                                                   "file_search", "web_fetch",
                                                   "read_pdf", "read_docx"})

    # --- Test 4: Security — safe paths ---
    print("\n[4] Security Policy — ALLOW")
    base = os.path.expanduser("~/personal_ai_brain")

    ok, reason = reg.security_check("read_file", {"path": f"{base}/brain.py"})
    check("Safe path: brain.py", ok, reason)

    ok, reason = reg.security_check("read_file", {"path": "."})
    check("Safe path: '.'", ok, reason)

    ok, reason = reg.security_check("directory_tree", {"path": f"{base}/mcp_servers"})
    check("Safe path: subdir", ok, reason)

    # --- Test 5: Security — traversal attacks ---
    print("\n[5] Security Policy — DENY")

    ok, reason = reg.security_check("read_file", {"path": "/etc/passwd"})
    check("DENY /etc/passwd", not ok, reason)

    ok, reason = reg.security_check("read_file", {"path": "../../etc/passwd"})
    check("DENY ../../etc/passwd", not ok, reason)

    ok, reason = reg.security_check("read_file", {"path": f"{base}/../../../etc/passwd"})
    check("DENY traversal via base prefix", not ok, reason)

    ok, reason = reg.security_check("move_file", {
        "source": f"{base}/test.txt",
        "destination": "/tmp/stolen.txt"
    })
    check("DENY move destination outside", not ok, reason)

    ok, reason = reg.security_check("move_file", {
        "source": "/etc/passwd",
        "destination": f"{base}/stolen.txt"
    })
    check("DENY move source outside", not ok, reason)

    # --- Test 6: Security — list paths ---
    print("\n[6] Security Policy — List Paths")
    ok, reason = reg.security_check("read_multiple_files", {
        "paths": [f"{base}/brain.py", f"{base}/mcp_bridge.py"]
    })
    check("ALLOW safe paths list", ok, reason)

    ok, reason = reg.security_check("read_multiple_files", {
        "paths": [f"{base}/brain.py", "/etc/shadow"]
    })
    check("DENY mixed paths list", not ok, reason)

    # --- Test 7: Unknown tool ---
    print("\n[7] Edge Cases")
    ok, reason = reg.security_check("nonexistent_tool", {"path": "."})
    check("DENY unknown tool", not ok, reason)

    # --- Test 8: Resolve ---
    print("\n[8] Resolution")
    t = reg.resolve("directory_tree")
    check("Resolve directory_tree", t is not None and t.source == ToolSource.MCP)

    t = reg.resolve("read_file")
    check("Resolve read_file → NATIVE", t is not None and t.source == ToolSource.NATIVE)

    t = reg.resolve("nonexistent")
    check("Resolve nonexistent → None", t is None)

    # --- Summary ---
    print("\n" + "=" * 64)
    total = passed + failed
    print(f"  RESULTS: {passed}/{total} passed, {failed} failed")
    if failed == 0:
        print("  🎉 ALL TESTS PASSED")
    else:
        print(f"  ⚠️  {failed} TESTS FAILED")
    print("=" * 64)
