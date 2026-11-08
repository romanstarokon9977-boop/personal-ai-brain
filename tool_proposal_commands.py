"""Direct-user CLI for reviewing and queueing proposal preparation.

These commands are not model-callable. State changes require a second exact
confirmation phrase typed directly at the terminal.
"""
from __future__ import annotations

from typing import Any, Callable


def _one_line(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _show_record(record: dict, output_fn: Callable[[str], None]) -> None:
    proposal = record["proposal"]
    output_fn(f"ID: {record.get('short_id', record['id'])}")
    output_fn(f"Статус: {record['status']}")
    output_fn(f"Инструмент: {proposal.get('name', '')}")
    output_fn(f"Назначение: {_one_line(proposal.get('purpose'))}")
    output_fn(f"Риск: {proposal.get('risk', 'UNKNOWN')}")
    output_fn(f"Возможность: {_one_line(proposal.get('capability'))}")
    output_fn("Разрешения: " + ", ".join(proposal.get("required_permissions", [])))
    output_fn("Ограничения: " + "; ".join(_one_line(x, 120) for x in proposal.get("constraints", [])))
    output_fn("Проверки: " + "; ".join(_one_line(x, 120) for x in proposal.get("acceptance_tests", [])))
    if record.get("implementation_requested_at"):
        output_fn(f"Запрос подготовки: {record['implementation_requested_at']}")
    output_fn("Реализация применена: НЕТ | Активация разрешена: НЕТ")


def _resolve_record(manager: Any, reference: str,
                    output_fn: Callable[[str], None]) -> dict | None:
    try:
        return manager.get(reference)
    except ValueError as error:
        if str(error) != "AMBIGUOUS_PROPOSAL_REFERENCE":
            raise
        matches = manager.find(reference)
        output_fn("Найдено несколько предложений; укажи короткий ID:")
        for record in matches:
            output_fn(
                f"{record.get('short_id', record['id'])} | "
                f"{record['proposal'].get('name', '')} | {record['status']}"
            )
        return False


def handle_proposal_command(command: str, manager: Any,
                            input_fn: Callable[[str], str] = input,
                            output_fn: Callable[[str], None] = print) -> bool:
    normalized = " ".join(str(command or "").strip().split())
    if normalized != "предложения" and not normalized.startswith("предложение "):
        return False
    if manager is None:
        output_fn("Хранилище предложений недоступно; операция остановлена.")
        return True
    try:
        if normalized == "предложения":
            records = manager.list_proposals()
            if not records:
                output_fn("Сохранённых предложений пока нет.")
                return True
            output_fn(f"Предложений: {len(records)}")
            for record in records:
                proposal = record["proposal"]
                output_fn(f"{record.get('short_id', record['id'])} | {record['status']} | {proposal.get('name', '')} | {proposal.get('risk', 'UNKNOWN')} | {_one_line(proposal.get('purpose'), 100)}")
            return True
        parts = normalized.split()
        if len(parts) == 2:
            record = _resolve_record(manager, parts[1], output_fn)
            if record is False:
                return True
            if record is None:
                output_fn("Предложение с таким ID или названием не найдено.")
            else:
                _show_record(record, output_fn)
            return True
        if len(parts) != 3 or parts[1] not in {"одобрить", "отклонить", "подготовить"}:
            output_fn(
                "Формат: предложение <ID> | предложение одобрить <ID> | "
                "предложение отклонить <ID> | предложение подготовить <ID>"
            )
            return True
        action, proposal_id = parts[1], parts[2]
        record = _resolve_record(manager, proposal_id, output_fn)
        if record is False:
            return True
        if record is None:
            output_fn("Предложение с таким ID или названием не найдено.")
            return True

        if action == "подготовить":
            if record.get("status") != "APPROVED":
                output_fn(
                    "Подготовка невозможна: требуется статус APPROVED; "
                    f"текущий статус {record.get('status')}."
                )
                return True
            confirmation_id = record.get("short_id", record["id"])
            expected = f"ПОДГОТОВИТЬ РЕАЛИЗАЦИЮ {confirmation_id}"
            output_fn(
                f"Запрос подготовки: {record['proposal'].get('name', '')} ({confirmation_id}). "
                "Будет сохранён только запрос; код и файлы не изменятся."
            )
        else:
            if record.get("status") != "PROPOSED":
                output_fn(f"Решение невозможно: текущий статус {record.get('status')}.")
                return True
            decision = "APPROVED" if action == "одобрить" else "REJECTED"
            phrase = "ОДОБРИТЬ" if action == "одобрить" else "ОТКЛОНИТЬ"
            confirmation_id = record.get("short_id", record["id"])
            expected = f"{phrase} {confirmation_id}"
            output_fn(
                f"Проверка решения: {record['proposal'].get('name', '')} ({confirmation_id}). "
                "Изменится только статус."
            )

        try:
            answer = input_fn(f"Для подтверждения введи точно: {expected}\n> ")
        except (KeyboardInterrupt, EOFError):
            output_fn("Операция отменена.")
            return True
        if not isinstance(answer, str) or answer.strip().casefold() != expected.casefold():
            output_fn("Подтверждение не совпало. Изменений нет.")
            return True

        if action == "подготовить":
            updated = manager.request_implementation(record["id"])
            output_fn(f"Запрос подготовки сохранён: {updated['status']}.")
            output_fn(
                "Код не создан и не изменён; тесты не запускались; "
                "инструмент не зарегистрирован и не активирован."
            )
        else:
            updated = manager.review(record["id"], decision)
            output_fn(f"Решение сохранено: {updated['status']}.")
            output_fn("Реализация не создана; инструмент не зарегистрирован и не активирован.")
        return True
    except (ValueError, OSError) as error:
        output_fn(f"Операция остановлена: {error}")
        return True
