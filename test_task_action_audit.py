import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from task_manager import TaskManager


class TaskActionAuditTests(unittest.TestCase):
    def test_task_mutation_is_audited_without_task_payload(self):
        with tempfile.TemporaryDirectory() as root:
            store = Path(root) / "tasks.json"
            audit_path = Path(root) / "audit.jsonl"
            with patch("action_audit._DEFAULT_PATH", str(audit_path)):
                manager = TaskManager(store)
                manager.create_task("PRIVATE_TASK_TITLE")
            rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["kind"], "TASK_LIFECYCLE")
            self.assertEqual(rows[0]["tool"], "TASK.CREATE")
            self.assertNotIn("PRIVATE_TASK_TITLE", audit_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
