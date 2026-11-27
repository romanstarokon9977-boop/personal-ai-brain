"""Explicit operating modes with enforced model-visible tool allowlists."""
from __future__ import annotations

MODE_ALIASES = {
    "conversation": "conversation", "chat": "conversation", "общение": "conversation",
    "research": "research", "исследование": "research",
    "programming": "programming", "программирование": "programming",
    "learning": "learning", "обучение": "learning",
    "autonomous": "autonomous", "автономный": "autonomous",
    "автономное исполнение": "autonomous",
}
READ_ONLY_TOOLS = frozenset({
    "read_file", "file_search", "directory_list", "directory_tree",
    "get_file_info", "read_multiple_files", "read_text_file", "list_directory",
    "list_allowed_directories", "search_files", "read_pdf", "read_docx",
    "web_fetch", "git_inspect", "self_inspection", "self_improvement_report",
    "memory_audit", "tool_catalog", "solution_library",
})
PROGRAMMING_TOOLS = READ_ONLY_TOOLS | frozenset({
    "write_file", "file_edit", "run_tests", "propose_tool", "module_improvement",
})
AUTONOMOUS_TOOLS = PROGRAMMING_TOOLS | frozenset({"notify_user", "briefing_set"})
MODE_TOOL_ALLOWLISTS = {
    "conversation": None,
    "research": READ_ONLY_TOOLS,
    "programming": PROGRAMMING_TOOLS,
    "learning": READ_ONLY_TOOLS - {"web_fetch"},
    "autonomous": AUTONOMOUS_TOOLS,
}
MODE_INSTRUCTIONS = {
    "conversation": "Режим общения: отвечай прямо и используй доступные инструменты только когда они действительно нужны. Сохраняй действующие разрешения.",
    "research": "Режим исследования: собирай и сопоставляй сведения. Используй только инструменты чтения; не изменяй файлы, настройки или внешние системы.",
    "programming": "Режим программирования: сначала изучи текущую реализацию, затем делай узкие изменения и запускай тесты. Любая запись или изменение требует действующего подтверждения; не обходи политику автономности.",
    "learning": "Режим обучения: объясняй по шагам, проверяй понимание и предлагай упражнения. Инструменты только для чтения; ничего не изменяй.",
    "autonomous": "Режим автономного исполнения: выполняй только явно запущенный сохранённый план, соблюдай ограничения шагов и верификацию. Запись файлов требует действующего подтверждения. Shell и публикация исключены из набора инструментов этого режима.",
}
MODE_LABELS = {
    "conversation": "общение", "research": "исследование",
    "programming": "программирование", "learning": "обучение",
    "autonomous": "автономное исполнение",
}


def normalize_mode(value: str) -> str | None:
    return MODE_ALIASES.get(value.strip().lower()) if isinstance(value, str) else None


def filter_tool_definitions(tool_definitions: list, mode: str) -> list:
    normalized = normalize_mode(mode) or "conversation"
    allowed = MODE_TOOL_ALLOWLISTS[normalized]
    source = tool_definitions if isinstance(tool_definitions, list) else []
    if allowed is None:
        return list(source)
    return [
        item for item in source
        if isinstance(item, dict)
        and item.get("function", {}).get("name") in allowed
    ]


def mode_instruction(mode: str) -> str:
    return MODE_INSTRUCTIONS[normalize_mode(mode) or "conversation"]


def mode_label(mode: str) -> str:
    return MODE_LABELS[normalize_mode(mode) or "conversation"]
