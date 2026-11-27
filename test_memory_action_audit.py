import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import memory.memory_core as memory_core


class MemoryActionAuditTests(unittest.TestCase):
    def test_memory_store_write_is_audited_without_memory_text(self):
        with tempfile.TemporaryDirectory() as root:
            memory_path = Path(root) / "memory.json"
            audit_path = Path(root) / "audit.jsonl"
            with patch.object(memory_core, "MEMORY_FILE", str(memory_path)), patch(
                "action_audit._DEFAULT_PATH", str(audit_path)
            ):
                memory_core._save_raw({
                    "version": 2,
                    "entries": [{"id": "test-id", "text": "PRIVATE_MEMORY_TEXT"}],
                })
            rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["kind"], "MEMORY_MUTATION")
            self.assertEqual(rows[0]["tool"], "MEMORY.STORE_WRITE")
            self.assertNotIn("PRIVATE_MEMORY_TEXT", audit_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
