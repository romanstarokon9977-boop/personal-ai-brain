"""Детерминированный планировщик задач Personal AI Brain.

Модуль строит проверяемый DAG-план, упорядочивает шаги по зависимостям
и отслеживает критерии завершения. Он НЕ исполняет инструменты и код.
"""
import json
import re
import time
from typing import Any, Callable, Dict, List, Optional


MAX_PLAN_STEPS = 12
MAX_CRITERIA_PER_STEP = 10
_PLAN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


PLAN_SYSTEM_PROMPT = """Ты — планировщик задач Personal AI Brain.
Верни только один JSON-объект, без Markdown и пояснений:
{
  "steps": [
    {
      "id": "step_1",
      "title": "Краткое название",
      "description": "Конкретный проверяемый результат шага",
      "depends_on": [],
      "acceptance_criteria": [
        "Однозначный критерий, по которому можно проверить результат"
      ]
    }
  ]
}
Правила:
- От 1 до 12 практически полезных шагов.
- Каждый шаг должен иметь уникальный id, title, description.
- depends_on содержит id шагов, которые должны завершиться раньше.
- Не создавай циклические зависимости.
- Указывай только реальные зависимости; независимые шаги могут идти параллельно.
- Для каждого шага укажи от 1 до 10 конкретных acceptance_criteria.
- Критерии должны описывать наблюдаемый результат, а не намерение.
- Не считай шаг выполненным и не заявляй о выполнении действий.
- Не включай команды или инструменты для самостоятельного исполнения.
- Сначала учитывай существующую архитектуру Personal AI Brain: brain.py как точку интеграции, Task Detector, Model Controller/роутер моделей, Memory Core, Context Manager, Tool Bridge/MCP, Tool Registry и Verifier/Goal Verifier.
- Предпочитай повторное использование существующих модулей и интерфейсов; не предлагай дублирующие подсистемы.
- Не предлагай новую векторную БД как обязательное решение; также не навязывай отдельный бэкенд, новый фреймворк или замену текущего стека.
- Новую инфраструктуру допускай только если задача действительно требует её и в плане есть отдельный шаг обоснования, сравнения альтернатив, оценки ресурсов и явного согласования с владельцем проекта.
- Не утверждай, что возможности уже реализованы, если это не подтверждено входным контекстом. Если текущее состояние компонента неизвестно, включи проверку/аудит до проектирования изменений.
- Сохраняй принцип управления проектом: ИИ предлагает, владелец проекта утверждает, исполнитель применяет, тесты подтверждают.
"""


class PlanValidationError(ValueError):
    """План не соответствует контракту или содержит некорректный DAG."""


def _require_text(value: Any, field: str, step_id: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlanValidationError(f"{step_id}: поле {field} должно быть непустой строкой")
    return value.strip()


def _topological_order(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Стабильная топологическая сортировка; обнаруживает циклы."""
    by_id = {step["id"]: step for step in steps}
    indegree = {step["id"]: len(step["depends_on"]) for step in steps}
    dependents = {step["id"]: [] for step in steps}
    for step in steps:
        for dependency in step["depends_on"]:
            dependents[dependency].append(step["id"])

    ordered = []
    # Канонический tie-break: среди всех одновременно готовых шагов
    # выбираем ID в лексикографическом порядке, независимо от порядка JSON.
    ready = sorted(step["id"] for step in steps if indegree[step["id"]] == 0)
    while ready:
        current = ready.pop(0)
        ordered.append(by_id[current])
        for child in sorted(dependents[current]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
        ready.sort()

    if len(ordered) != len(steps):
        raise PlanValidationError("Обнаружен цикл зависимостей")
    return ordered


def validate_plan(goal: str, raw_steps: Any) -> Dict[str, Any]:
    """Проверяет схему, ссылки и DAG; возвращает нормализованный план."""
    if not isinstance(goal, str) or not goal.strip():
        raise PlanValidationError("Цель задачи не задана")
    if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= MAX_PLAN_STEPS:
        raise PlanValidationError(f"Число шагов должно быть от 1 до {MAX_PLAN_STEPS}")

    normalized = []
    seen = set()
    for index, raw in enumerate(raw_steps, 1):
        if not isinstance(raw, dict):
            raise PlanValidationError(f"Шаг {index}: ожидался объект")
        step_id = _require_text(raw.get("id"), "id", f"step_{index}")
        if not _PLAN_ID_RE.fullmatch(step_id):
            raise PlanValidationError(f"{step_id}: недопустимый формат id")
        if step_id in seen:
            raise PlanValidationError(f"Повторяющийся id: {step_id}")
        seen.add(step_id)

        title = _require_text(raw.get("title"), "title", step_id)
        description = _require_text(raw.get("description"), "description", step_id)
        dependencies = raw.get("depends_on", [])
        if not isinstance(dependencies, list) or any(not isinstance(x, str) for x in dependencies):
            raise PlanValidationError(f"{step_id}: depends_on должен быть списком id")
        if len(dependencies) != len(set(dependencies)):
            raise PlanValidationError(f"{step_id}: повторяющаяся зависимость")
        if step_id in dependencies:
            raise PlanValidationError(f"{step_id}: шаг не может зависеть от самого себя")

        criteria = raw.get("acceptance_criteria")
        if (not isinstance(criteria, list)
                or not 1 <= len(criteria) <= MAX_CRITERIA_PER_STEP):
            raise PlanValidationError(
                f"{step_id}: требуется от 1 до {MAX_CRITERIA_PER_STEP} критериев"
            )
        normalized_criteria = []
        for criterion_index, criterion in enumerate(criteria, 1):
            text = _require_text(criterion, "acceptance_criteria", step_id)
            normalized_criteria.append({
                "id": f"AC{criterion_index}",
                "description": text,
            })

        normalized.append({
            "id": step_id,
            "title": title,
            "description": description,
            "depends_on": list(dependencies),
            "acceptance_criteria": normalized_criteria,
            "status": "pending",
            "evidence": {},
        })

    for step in normalized:
        missing = [dep for dep in step["depends_on"] if dep not in seen]
        if missing:
            raise PlanValidationError(
                f"{step['id']}: неизвестные зависимости: {', '.join(missing)}"
            )

    ordered = _topological_order(normalized)
    return {
        "schema_version": 1,
        "goal": goal.strip(),
        "status": "pending",
        "steps": ordered,
    }


def parse_plan_response(response_text: str, goal: str) -> Dict[str, Any]:
    """Извлекает JSON-план из ответа модели и строго валидирует его."""
    if not isinstance(response_text, str) or not response_text.strip():
        raise PlanValidationError("Модель вернула пустой ответ")

    text = response_text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.I | re.S)
    if fenced:
        text = fenced.group(1).strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise PlanValidationError(f"Некорректный JSON: {error.msg}") from error

    if not isinstance(payload, dict) or "steps" not in payload:
        raise PlanValidationError("Ожидался JSON-объект с полем steps")
    return validate_plan(goal, payload["steps"])


def generate_plan(
    goal: str,
    ask_model_func: Callable,
    model_id: str,
    max_attempts: int = 2,
    sleep_func: Callable = time.sleep,
) -> Dict[str, Any]:
    """Запрашивает и валидирует план. Никакие шаги не исполняются."""
    if not isinstance(goal, str) or not goal.strip():
        return {"ok": False, "plan": None, "error": "EMPTY_GOAL"}
    if not callable(ask_model_func):
        return {"ok": False, "plan": None, "error": "INVALID_MODEL_CALLBACK"}

    messages = [
        {"role": "system", "content": PLAN_SYSTEM_PROMPT},
        {"role": "user", "content": f"Построй план для цели:\n{goal.strip()}"},
    ]
    last_error = "PLAN_GENERATION_FAILED"
    attempts = max(1, min(int(max_attempts), 3))

    for attempt in range(attempts):
        try:
            ok, result = ask_model_func(model_id, messages)
            if ok and isinstance(result, dict):
                response = result.get("answer") or result.get("content") or ""
                try:
                    plan = parse_plan_response(response, goal)
                    return {"ok": True, "plan": plan, "error": None}
                except PlanValidationError as error:
                    last_error = f"INVALID_PLAN: {error}"
            else:
                last_error = str((result or {}).get("error", "MODEL_REQUEST_FAILED"))
        except Exception as error:
            last_error = f"MODEL_CALLBACK_ERROR: {type(error).__name__}"

        if attempt + 1 < attempts:
            sleep_func(1 + attempt)

    return {"ok": False, "plan": None, "error": last_error}


def get_ready_steps(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Возвращает pending-шаги, чьи зависимости уже завершены."""
    steps = plan.get("steps", [])
    completed = {s["id"] for s in steps if s.get("status") == "completed"}
    return [
        step for step in steps
        if step.get("status") == "pending"
        and all(dep in completed for dep in step.get("depends_on", []))
    ]


def start_step(plan: Dict[str, Any], step_id: str) -> Dict[str, Any]:
    """Переводит только доступный шаг в in_progress."""
    step = next((s for s in plan.get("steps", []) if s.get("id") == step_id), None)
    if step is None:
        raise PlanValidationError(f"Неизвестный шаг: {step_id}")
    if step.get("status") != "pending":
        raise PlanValidationError(f"{step_id}: шаг не находится в pending")
    ready_ids = {s["id"] for s in get_ready_steps(plan)}
    if step_id not in ready_ids:
        raise PlanValidationError(f"{step_id}: зависимости ещё не завершены")
    step["status"] = "in_progress"
    plan["status"] = "in_progress"
    return step


def complete_step(
    plan: Dict[str, Any],
    step_id: str,
    criterion_results: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Завершает шаг только при PASS каждого критерия с непустым evidence."""
    step = next((s for s in plan.get("steps", []) if s.get("id") == step_id), None)
    if step is None:
        raise PlanValidationError(f"Неизвестный шаг: {step_id}")
    if step.get("status") != "in_progress":
        raise PlanValidationError(f"{step_id}: сначала необходимо начать шаг")
    if not isinstance(criterion_results, dict):
        raise PlanValidationError("Результаты критериев должны быть объектом")

    expected = {c["id"] for c in step["acceptance_criteria"]}
    if set(criterion_results) != expected:
        raise PlanValidationError("Набор результатов не совпадает с критериями шага")

    evidence = {}
    for criterion_id in sorted(expected):
        result = criterion_results[criterion_id]
        if not isinstance(result, dict) or result.get("passed") is not True:
            raise PlanValidationError(f"{criterion_id}: критерий не подтверждён")
        proof = result.get("evidence")
        if not isinstance(proof, str) or not proof.strip():
            raise PlanValidationError(f"{criterion_id}: отсутствует evidence")
        evidence[criterion_id] = proof.strip()

    step["evidence"] = evidence
    step["status"] = "completed"
    plan["status"] = (
        "completed"
        if all(s.get("status") == "completed" for s in plan.get("steps", []))
        else "in_progress"
    )
    return step


def format_plan(plan: Dict[str, Any]) -> str:
    """Форматирует план для текстового интерфейса Brain."""
    lines = [f"ПЛАН: {plan['goal']}", f"Статус: {plan['status']}"]
    for index, step in enumerate(plan["steps"], 1):
        deps = ", ".join(step["depends_on"]) or "нет"
        lines.extend([
            f"{index}. [{step['status']}] {step['title']} ({step['id']})",
            f"   Задача: {step['description']}",
            f"   Зависимости: {deps}",
            "   Критерии завершения:",
        ])
        lines.extend(
            f"   - {criterion['id']}: {criterion['description']}"
            for criterion in step["acceptance_criteria"]
        )
    lines.append("Шаги не выполнялись: это план, а не команда на исполнение.")
    return "\n".join(lines)
