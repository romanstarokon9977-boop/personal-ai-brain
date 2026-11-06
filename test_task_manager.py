import json
import tempfile
import unittest
from pathlib import Path

from task_manager import TaskManager, TaskManagerError


class TaskManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = Path(self.temp_dir.name) / "tasks.json"
        self.manager = TaskManager(self.store)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_and_persist_task(self):
        task = self.manager.create_task("Подготовить релиз", "Проверить тесты")
        loaded = TaskManager(self.store).get_task(task["id"])
        self.assertEqual(loaded["status"], "pending")
        self.assertEqual(loaded["details"], "Проверить тесты")
        self.assertEqual(loaded["history"][-1]["event"], "created")

    def test_lifecycle_pending_active_interrupted_resumed_completed(self):
        task = self.manager.create_task("Задача")
        self.assertEqual(self.manager.start_task(task["id"])["status"], "active")
        self.assertEqual(self.manager.interrupt_task(task["id"])["status"], "interrupted")
        self.assertEqual(self.manager.start_task(task["id"])["status"], "active")
        self.assertEqual(self.manager.complete_task(task["id"])["status"], "completed")

    def test_restart_recovers_active_task_without_losing_checkpoint(self):
        task = self.manager.create_task(
            "План", plan={"steps": [{"id": "s1", "status": "pending"}]},
            checkpoint={"step_id": "s1", "note": "Начать проверку"},
        )
        self.manager.start_task(task["id"])
        recovered = TaskManager(self.store).recover_active_tasks()
        self.assertEqual([item["id"] for item in recovered], [task["id"]])
        loaded = self.manager.get_task(task["id"])
        self.assertEqual(loaded["status"], "interrupted")
        self.assertEqual(loaded["checkpoint"]["step_id"], "s1")
        self.assertEqual(loaded["plan"]["steps"][0]["id"], "s1")
        self.assertEqual(loaded["history"][-1]["event"], "recovered_after_restart")

    def test_recovery_does_not_change_pending_or_completed_tasks(self):
        pending = self.manager.create_task("Ожидает")
        done = self.manager.create_task("Готово")
        self.manager.complete_task(done["id"])
        self.assertEqual(self.manager.recover_active_tasks(), [])
        self.assertEqual(self.manager.get_task(pending["id"])["status"], "pending")
        self.assertEqual(self.manager.get_task(done["id"])["status"], "completed")

    def test_progress_checkpoint_survives_reload(self):
        task = self.manager.create_task("Работа")
        self.manager.start_task(task["id"])
        self.manager.update_progress(
            task["id"], note="Проверен первый модуль",
            checkpoint={"last_completed": "module_1"},
        )
        loaded = TaskManager(self.store).get_task(task["id"])
        self.assertEqual(loaded["progress_note"], "Проверен первый модуль")
        self.assertEqual(loaded["checkpoint"]["last_completed"], "module_1")

    def test_filter_and_unknown_task(self):
        active = self.manager.create_task("Активная")
        self.manager.start_task(active["id"])
        self.manager.create_task("Ожидающая")
        self.assertEqual(len(self.manager.list_tasks("active")), 1)
        with self.assertRaises(TaskManagerError):
            self.manager.get_task("missing")

    def test_invalid_transitions_are_rejected(self):
        task = self.manager.create_task("Тест")
        with self.assertRaises(TaskManagerError):
            self.manager.complete_task("missing")
        self.manager.complete_task(task["id"])
        with self.assertRaises(TaskManagerError):
            self.manager.start_task(task["id"])
        with self.assertRaises(TaskManagerError):
            self.manager.update_progress(task["id"], note="Изменение после завершения")

    def test_corrupt_store_is_not_overwritten(self):
        self.store.write_text("{broken", encoding="utf-8")
        with self.assertRaises(TaskManagerError):
            self.manager.create_task("Не перезаписывать")
        self.assertEqual(self.store.read_text(encoding="utf-8"), "{broken")

    def test_empty_title_is_rejected(self):
        with self.assertRaises(TaskManagerError):
            self.manager.create_task("   ")


if __name__ == "__main__":
    unittest.main(verbosity=2)
