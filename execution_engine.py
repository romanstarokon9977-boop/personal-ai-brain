"""Bounded multi-step execution orchestration for Personal AI Brain.

Coordinates the existing Planner, Tool Bridge and Verifier through callbacks.
It never executes tools directly and never treats an uncertain result as success.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import planner
import tool_error_handler


SAFE_RETRY_TOOLS = frozenset({
    "read_file", "directory_list", "file_search", "read_pdf", "read_docx",
    "directory_tree", "get_file_info", "read_multiple_files",
    "list_allowed_directories", "read_text_file", "list_directory", "search_files",
})
AUTO_APPROVED_TOOLS = SAFE_RETRY_TOOLS

_TRANSIENT_ERRORS = (
    "TIMEOUT", "CONNECTION_ERROR", "CONNECTION RESET", "MCP CALL TIMEOUT",
    "HTTP_429", "HTTP_500", "HTTP_502", "HTTP_503", "HTTP_504", "LOCAL_TIMEOUT",
)


def classify_retry(tool_name: str, error: Any) -> Dict[str, str]:
    """Use the shared error taxonomy; retries remain limited to known read-only tools."""
    name = str(tool_name or "")
    if name not in SAFE_RETRY_TOOLS:
        return {"decision": "HUMAN_REQUIRED", "reason": "NON_IDEMPOTENT_OR_UNKNOWN_TOOL"}
    classified = tool_error_handler.classify_tool_error(
        error, tool_name=name, side_effecting=False
    )
    if classified["retryable"]:
        return {
            "decision": "RETRY_SAFE",
            "reason": "TRANSIENT_READ_ONLY_" + classified["category"],
        }
    return {
        "decision": "STOP",
        "reason": "NON_TRANSIENT_FAILURE_" + classified["category"],
    }


def _tool_results(outcome: Dict[str, Any]) -> List[Dict[str, Any]]:
    values = outcome.get("tool_results", [])
    if not isinstance(values, list):
        return []
    return [item for item in values if isinstance(item, dict)]


def _failed_tool_results(outcome: Dict[str, Any]) -> List[Dict[str, Any]]:
    failed = []
    for item in _tool_results(outcome):
        result = item.get("result")
        if not isinstance(result, dict) or result.get("ok") is not True:
            failed.append(item)
    return failed


def _snapshot(plan: Dict[str, Any]) -> Dict[str, Any]:
    completed = [
        step["id"] for step in plan.get("steps", [])
        if step.get("status") == "completed"
    ]
    pending = [
        step["id"] for step in plan.get("steps", [])
        if step.get("status") != "completed"
    ]
    return {"completed_steps": completed, "pending_steps": pending}


def run_multistep(
    goal: str,
    plan: Dict[str, Any],
    execute_step: Callable[[Dict[str, Any]], Dict[str, Any]],
    verify_step: Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
    persist: Optional[Callable[[str, Dict[str, Any], Optional[Dict[str, Any]], Dict[str, Any]], Any]] = None,
    max_safe_retries: int = 1,
) -> Dict[str, Any]:
    """Run a validated plan sequentially, checkpointing every transition.

    execute_step returns {ok, answer, tool_results:[{tool_name, params, result}]}.
    verify_step returns {status: PASS|FAIL|UNCERTAIN, evidence:{AC1: {...}}}.
    """
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("Цель исполнения не задана")
    if not isinstance(plan, dict) or not isinstance(plan.get("steps"), list):
        raise ValueError("План исполнения имеет неверный формат")
    if not callable(execute_step) or not callable(verify_step):
        raise ValueError("Не заданы callbacks исполнения и проверки")
    if isinstance(max_safe_retries, bool) or not isinstance(max_safe_retries, int) or max_safe_retries < 0:
        raise ValueError("max_safe_retries должен быть целым числом >= 0")

    events: List[Dict[str, Any]] = []
    retries_used = 0

    def stop(status: str, reason: str, step: Optional[Dict[str, Any]] = None):
        snapshot = _snapshot(plan)
        return {
            "status": status,
            "goal": goal.strip(),
            "current_step": step.get("id") if isinstance(step, dict) else None,
            "reason": reason,
            "retries_used": retries_used,
            "events": list(events),
            "plan": plan,
            **snapshot,
        }

    def save(event: str, step: Optional[Dict[str, Any]], detail: Dict[str, Any]):
        events.append({
            "event": event,
            "step_id": step.get("id") if isinstance(step, dict) else None,
            "detail": dict(detail),
        })
        if persist is None:
            return True
        try:
            persist(event, plan, step, detail)
            return True
        except Exception as error:
            events.append({
                "event": "persistence_error",
                "step_id": step.get("id") if isinstance(step, dict) else None,
                "detail": {"error": type(error).__name__},
            })
            return False

    steps = plan["steps"]
    if not 1 <= len(steps) <= planner.MAX_PLAN_STEPS:
        raise ValueError("Число шагов плана выходит за допустимые пределы")
    ids = [step.get("id") for step in steps if isinstance(step, dict)]
    if len(ids) != len(steps) or len(ids) != len(set(ids)):
        raise ValueError("План содержит некорректные или повторяющиеся ID шагов")
    allowed_statuses = {"pending", "in_progress", "completed"}
    for step in steps:
        if step.get("status") not in allowed_statuses:
            raise ValueError("План содержит неизвестный статус шага")
        if not isinstance(step.get("depends_on"), list) or not isinstance(step.get("acceptance_criteria"), list):
            raise ValueError("План содержит некорректные зависимости или критерии")

    for step in steps:
        if step.get("status") == "completed":
            continue
        if step.get("status") == "in_progress":
            save("paused", step, {"reason": "STEP_ALREADY_IN_PROGRESS_REQUIRES_RECONCILIATION"})
            return stop("paused", "STEP_ALREADY_IN_PROGRESS_REQUIRES_RECONCILIATION", step)

        ready_ids = {item["id"] for item in planner.get_ready_steps(plan)}
        if step.get("status") != "pending" or step.get("id") not in ready_ids:
            save("paused", step, {"reason": "DEPENDENCIES_NOT_SATISFIED"})
            return stop("paused", "DEPENDENCIES_NOT_SATISFIED", step)

        try:
            planner.start_step(plan, step["id"])
        except planner.PlanValidationError as error:
            save("paused", step, {"reason": str(error)})
            return stop("paused", "PLAN_TRANSITION_REJECTED", step)

        if not save("step_started", step, {"description": step.get("description", "")}):
            return stop("paused", "CHECKPOINT_WRITE_FAILED", step)

        try:
            outcome = execute_step(step)
        except Exception as error:
            save("paused", step, {"reason": "STEP_EXECUTOR_EXCEPTION", "error": type(error).__name__})
            return stop("paused", "STEP_EXECUTOR_EXCEPTION", step)

        if not isinstance(outcome, dict):
            save("paused", step, {"reason": "INVALID_EXECUTOR_RESULT"})
            return stop("paused", "INVALID_EXECUTOR_RESULT", step)

        failed = _failed_tool_results(outcome)
        if failed:
            retry_candidate = len(_tool_results(outcome)) == 1 and len(failed) == 1
            decision = {"decision": "HUMAN_REQUIRED", "reason": "MULTIPLE_OR_MIXED_TOOL_RESULTS"}
            if retry_candidate:
                failed_result = failed[0].get("result") or {}
                decision = classify_retry(
                    failed[0].get("tool_name"),
                    failed_result.get("error"),
                )
            if decision["decision"] == "RETRY_SAFE" and retries_used < max_safe_retries:
                retries_used += 1
                if not save("safe_retry", step, {
                    "tool": failed[0].get("tool_name"),
                    "reason": decision["reason"],
                    "attempt": retries_used,
                }):
                    return stop("paused", "CHECKPOINT_WRITE_FAILED", step)
                try:
                    outcome = execute_step(step)
                except Exception as error:
                    save("paused", step, {"reason": "RETRY_EXECUTOR_EXCEPTION", "error": type(error).__name__})
                    return stop("paused", "RETRY_EXECUTOR_EXCEPTION", step)
                if not isinstance(outcome, dict) or _failed_tool_results(outcome):
                    save("paused", step, {"reason": "SAFE_RETRY_FAILED"})
                    return stop("paused", "SAFE_RETRY_FAILED", step)
            else:
                if decision["decision"] == "HUMAN_REQUIRED":
                    reason = "HUMAN_REQUIRED_AFTER_AMBIGUOUS_SIDE_EFFECT"
                elif decision["decision"] == "RETRY_SAFE":
                    reason = "SAFE_RETRY_LIMIT_REACHED"
                else:
                    reason = "NON_TRANSIENT_TOOL_FAILURE"
                save("paused", step, {
                    "reason": reason,
                    "tool": failed[0].get("tool_name"),
                    "retry_decision": decision["decision"],
                })
                return stop("paused", reason, step)

        if outcome.get("ok") is not True:
            reason = str(outcome.get("error") or "STEP_EXECUTION_FAILED")
            save("paused", step, {"reason": reason})
            return stop("paused", reason, step)

        try:
            verification = verify_step(step, outcome)
        except Exception as error:
            save("paused", step, {"reason": "VERIFIER_EXCEPTION", "error": type(error).__name__})
            return stop("paused", "VERIFIER_EXCEPTION", step)

        if not isinstance(verification, dict):
            verification = {"status": "UNCERTAIN", "reason": "INVALID_VERIFIER_RESULT"}

        status = verification.get("status")
        if status != "PASS":
            reason = str(verification.get("reason") or (
                "VERIFICATION_FAILED" if status == "FAIL" else "HUMAN_VERIFICATION_REQUIRED"
            ))
            save("paused", step, {"reason": reason, "verification_status": status})
            return stop("paused", reason, step)

        evidence = verification.get("evidence")
        try:
            planner.complete_step(plan, step["id"], evidence)
        except planner.PlanValidationError as error:
            save("paused", step, {"reason": "ACCEPTANCE_CRITERIA_NOT_PROVEN", "error": str(error)})
            return stop("paused", "ACCEPTANCE_CRITERIA_NOT_PROVEN", step)

        if not save("step_verified", step, {
            "verification_status": "PASS",
            "evidence_count": len(evidence),
        }):
            return stop("paused", "CHECKPOINT_WRITE_FAILED", step)

    if all(step.get("status") == "completed" for step in steps):
        plan["status"] = "completed"
        if not save("execution_completed", None, {"goal": goal.strip()}):
            return stop("paused", "CHECKPOINT_WRITE_FAILED")
        return stop("completed", "ALL_STEPS_VERIFIED")

    return stop("paused", "UNFINISHED_STEPS")


def format_report(report: Dict[str, Any]) -> str:
    labels = {"completed": "ЗАВЕРШЕНО", "paused": "ПРИОСТАНОВЛЕНО", "failed": "ОШИБКА"}
    lines = [
        "ОТЧЁТ МНОГОШАГОВОГО ИСПОЛНЕНИЯ",
        f"Цель: {report.get('goal', '')}",
        f"Статус: {labels.get(report.get('status'), report.get('status', 'UNKNOWN'))}",
        f"Подтверждено шагов: {len(report.get('completed_steps', []))}",
        f"Осталось шагов: {len(report.get('pending_steps', []))}",
    ]
    if report.get("current_step"):
        lines.append(f"Текущий шаг: {report['current_step']}")
    if report.get("reason"):
        lines.append(f"Причина/следующее действие: {report['reason']}")
    if report.get("retries_used"):
        lines.append(f"Безопасных повторов: {report['retries_used']}")
    return "\n".join(lines)
