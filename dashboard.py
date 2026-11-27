"""Compact, read-only mobile dashboard view model and renderer."""
from __future__ import annotations


def build_dashboard_snapshot(
    *,
    router_state,
    memory_status,
    tasks,
    tools,
    enabled_tool_names,
    local_processes,
    mcp_alive,
    candidate_count=None,
) -> dict:
    """Build a bounded summary; never include prompts, paths, memory text or secrets."""
    router_state = router_state if isinstance(router_state, dict) else {}
    memory_status = memory_status if isinstance(memory_status, dict) else {}
    tasks = tasks if isinstance(tasks, list) else []
    tools = tools if isinstance(tools, (list, tuple, set)) else []
    enabled = set(enabled_tool_names or [])
    process_names = [
        str(name)[:32] for name in (local_processes or [])
        if isinstance(name, str)
    ]

    task_statuses = {"pending": 0, "active": 0, "interrupted": 0, "completed": 0}
    priorities = {"critical": 0, "high": 0, "normal": 0, "low": 0}
    for task in tasks:
        if not isinstance(task, dict):
            continue
        status = task.get("status")
        priority = task.get("priority", "normal")
        if status in task_statuses:
            task_statuses[status] += 1
        if priority in priorities:
            priorities[priority] += 1

    categories = memory_status.get("categories", {})
    if not isinstance(categories, dict):
        categories = {}
    safe_categories = {
        str(name)[:24]: count
        for name, count in categories.items()
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0
    }

    model = router_state.get("active_model") or "не выбрана"
    provider = router_state.get("active_provider") or "неизвестен"
    return {
        "brain": "RUNNING",
        "model": str(model).split("/")[-1][:48],
        "provider": str(provider)[:32],
        "requests": max(0, int(router_state.get("total_requests", 0) or 0)),
        "successes": max(0, int(router_state.get("successful_requests", 0) or 0)),
        "failures": max(0, int(router_state.get("failed_requests", 0) or 0)),
        "free_models": max(0, len(router_state.get("models", []) or [])),
        "memory_total": max(0, int(memory_status.get("total", 0) or 0)),
        "memory_categories": safe_categories,
        "task_total": len(tasks),
        "task_statuses": task_statuses,
        "task_priorities": priorities,
        "tools_total": len(tools),
        "tools_enabled": sum(1 for tool in tools if getattr(tool, "name", tool) in enabled),
        "local_processes": process_names,
        "mcp_alive": bool(mcp_alive),
        "candidate_count": (
            candidate_count
            if isinstance(candidate_count, int) and not isinstance(candidate_count, bool)
            and candidate_count >= 0
            else None
        ),
    }


def render_dashboard(snapshot: dict) -> str:
    """Render a compact, small-screen-friendly status panel."""
    if not isinstance(snapshot, dict):
        return "ПАНЕЛЬ BRAIN\nНет данных."
    statuses = snapshot.get("task_statuses", {})
    priorities = snapshot.get("task_priorities", {})
    categories = snapshot.get("memory_categories", {})
    category_text = ", ".join(
        f"{name}:{count}" for name, count in sorted(categories.items())
    ) or "нет данных"
    process_names = snapshot.get("local_processes", [])
    processes = ", ".join(process_names) if process_names else "нет"
    candidate_count = snapshot.get("candidate_count")
    candidates = str(candidate_count) if candidate_count is not None else "н/д"
    return "\n".join([
        "╔════ PERSONAL AI BRAIN ════╗",
        f"Система: {snapshot.get('brain', 'UNKNOWN')}",
        f"Модель: {snapshot.get('model', 'н/д')}",
        f"Провайдер: {snapshot.get('provider', 'н/д')}",
        (
            "Запросы: "
            f"{snapshot.get('successes', 0)}/{snapshot.get('requests', 0)} OK"
            f" · ошибок {snapshot.get('failures', 0)}"
        ),
        f"Free-моделей: {snapshot.get('free_models', 0)}",
        (
            f"Память: {snapshot.get('memory_total', 0)} записей"
            f" · {category_text}"
        ),
        (
            f"Задачи: {snapshot.get('task_total', 0)}"
            f" · ожид. {statuses.get('pending', 0)}"
            f" · актив. {statuses.get('active', 0)}"
            f" · пауза {statuses.get('interrupted', 0)}"
            f" · готово {statuses.get('completed', 0)}"
        ),
        (
            "Приоритеты: "
            f"critical {priorities.get('critical', 0)}"
            f" · high {priorities.get('high', 0)}"
        ),
        (
            f"Инструменты: {snapshot.get('tools_enabled', 0)}"
            f"/{snapshot.get('tools_total', 0)} включено"
        ),
        f"Кандидаты памяти: {candidates}",
        f"Локальные процессы: {processes}",
        f"MCP filesystem: {'работает' if snapshot.get('mcp_alive') else 'остановлен'}",
        "╚════════════════════════════╝",
    ])
