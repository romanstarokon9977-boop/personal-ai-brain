"""Persistent task lifecycle and checkpoint storage for Personal AI Brain.

The store is local runtime state. Writes are atomic and malformed files are
never silently replaced.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1
TASK_STATUSES = {"pending", "active", "completed", "interrupted"}
DEFAULT_STORE = Path(__file__).resolve().with_name("tasks.json")


class TaskManagerError(ValueError):
    """Raised for invalid task operations or an unreadable task store."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TaskManager:
    """Small JSON-backed task manager with atomic persistence."""

    def __init__(self, store_path: Optional[os.PathLike | str] = None):
        self.store_path = Path(store_path) if store_path else DEFAULT_STORE

    def _read(self) -> Dict[str, Any]:
        if not self.store_path.exists():
            return {"schema_version": SCHEMA_VERSION, "tasks": []}
        try:
            with self.store_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as error:
            raise TaskManagerError(f"Не удалось прочитать хранилище задач: {error}") from error
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
            raise TaskManagerError("Неподдерживаемый формат хранилища задач")
        if not isinstance(data.get("tasks"), list):
            raise TaskManagerError("Поле tasks должно быть списком")
        seen = set()
        for task in data["tasks"]:
            if not isinstance(task, dict) or not isinstance(task.get("id"), str):
                raise TaskManagerError("Обнаружена некорректная запись задачи")
            if task["id"] in seen:
                raise TaskManagerError("Обнаружены повторяющиеся ID задач")
            seen.add(task["id"])
            if task.get("status") not in TASK_STATUSES:
                raise TaskManagerError(f"Некорректный статус задачи {task['id']}")
        return data

    def _write(self, data: Dict[str, Any]) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=self.store_path.name + ".", suffix=".tmp",
            dir=str(self.store_path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.store_path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    def list_tasks(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        if status is not None and status not in TASK_STATUSES:
            raise TaskManagerError(f"Неизвестный статус: {status}")
        tasks = self._read()["tasks"]
        selected = [task for task in tasks if status is None or task["status"] == status]
        return sorted(selected, key=lambda item: item.get("updated_at", ""), reverse=True)

    def get_task(self, task_id: str) -> Dict[str, Any]:
        task = next((item for item in self._read()["tasks"] if item["id"] == task_id), None)
        if task is None:
            raise TaskManagerError(f"Задача не найдена: {task_id}")
        return task

    def create_task(
        self,
        title: str,
        details: str = "",
        plan: Optional[Dict[str, Any]] = None,
        checkpoint: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not isinstance(title, str) or not title.strip():
            raise TaskManagerError("Название задачи не может быть пустым")
        data = self._read()
        now = _now()
        task = {
            "id": uuid.uuid4().hex[:8],
            "title": title.strip(),
            "details": str(details or "").strip(),
            "status": "pending",
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "completed_at": None,
            "interrupted_at": None,
            "progress_note": "",
            "checkpoint": checkpoint if isinstance(checkpoint, dict) else {},
            "plan": plan,
            "history": [{"at": now, "event": "created"}],
        }
        data["tasks"].append(task)
        self._write(data)
        return task

    def _change(self, task_id: str, event: str, allowed: set, status: Optional[str] = None):
        data = self._read()
        task = next((item for item in data["tasks"] if item["id"] == task_id), None)
        if task is None:
            raise TaskManagerError(f"Задача не найдена: {task_id}")
        if task["status"] not in allowed:
            raise TaskManagerError(
                f"Нельзя выполнить действие «{event}» для статуса {task['status']}"
            )
        now = _now()
        if status:
            task["status"] = status
        task["updated_at"] = now
        task.setdefault("history", []).append({"at": now, "event": event})
        if status == "active" and not task.get("started_at"):
            task["started_at"] = now
        if status == "completed":
            task["completed_at"] = now
        if status == "interrupted":
            task["interrupted_at"] = now
        self._write(data)
        return task

    def start_task(self, task_id: str) -> Dict[str, Any]:
        return self._change(task_id, "resumed" if self.get_task(task_id)["status"] == "interrupted" else "started",
                            {"pending", "interrupted"}, "active")

    def interrupt_task(self, task_id: str) -> Dict[str, Any]:
        return self._change(task_id, "interrupted", {"pending", "active"}, "interrupted")

    def complete_task(self, task_id: str) -> Dict[str, Any]:
        return self._change(task_id, "completed", {"pending", "active", "interrupted"}, "completed")

    def update_progress(
        self,
        task_id: str,
        note: Optional[str] = None,
        checkpoint: Optional[Dict[str, Any]] = None,
        plan: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        data = self._read()
        task = next((item for item in data["tasks"] if item["id"] == task_id), None)
        if task is None:
            raise TaskManagerError(f"Задача не найдена: {task_id}")
        if task["status"] == "completed":
            raise TaskManagerError("Нельзя обновлять завершённую задачу")
        if note is not None:
            task["progress_note"] = str(note).strip()
        if checkpoint is not None:
            if not isinstance(checkpoint, dict):
                raise TaskManagerError("checkpoint должен быть объектом")
            task["checkpoint"] = checkpoint
        if plan is not None:
            if not isinstance(plan, dict):
                raise TaskManagerError("plan должен быть объектом")
            task["plan"] = plan
        now = _now()
        task["updated_at"] = now
        task.setdefault("history", []).append({"at": now, "event": "checkpoint_saved"})
        self._write(data)
        return task

    def recover_active_tasks(self) -> List[Dict[str, Any]]:
        """Mark tasks left active by a previous Brain process as interrupted."""
        data = self._read()
        recovered = []
        now = _now()
        for task in data["tasks"]:
            if task["status"] == "active":
                task["status"] = "interrupted"
                task["interrupted_at"] = now
                task["updated_at"] = now
                task.setdefault("history", []).append({
                    "at": now, "event": "recovered_after_restart"
                })
                recovered.append(task)
        if recovered:
            self._write(data)
        return recovered


_manager = TaskManager()


def list_tasks(status: Optional[str] = None):
    return _manager.list_tasks(status)


def get_task(task_id: str):
    return _manager.get_task(task_id)


def create_task(title: str, details: str = "", plan=None, checkpoint=None):
    return _manager.create_task(title, details, plan, checkpoint)


def start_task(task_id: str):
    return _manager.start_task(task_id)


def interrupt_task(task_id: str):
    return _manager.interrupt_task(task_id)


def complete_task(task_id: str):
    return _manager.complete_task(task_id)


def update_progress(task_id: str, note=None, checkpoint=None, plan=None):
    return _manager.update_progress(task_id, note, checkpoint, plan)


def recover_active_tasks():
    return _manager.recover_active_tasks()
