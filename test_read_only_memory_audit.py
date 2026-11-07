import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from memory import read_only_audit


class ReadOnlyMemoryAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="memory_audit_")
        self.path_patch = mock.patch.object(
            read_only_audit, "MEMORY_FILE",
            os.path.join(self.tmp.name, "brain_memory.json"),
        )
        self.path_patch.start()

    def tearDown(self):
        self.path_patch.stop()
        self.tmp.cleanup()

    def _write(self, payload):
        with open(read_only_audit.MEMORY_FILE, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_returns_aggregate_counts_without_exposing_personal_text(self):
        self._write({
            "version": 2,
            "entries": [
                {
                    "id": "a", "text": "PRIVATE_SENTINEL_TEXT",
                    "category": "preferences", "memory_type": "permanent",
                    "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-02T00:00:00",
                    "source_date": "2026-01-01", "provenance": {"source": "private"},
                    "source": "user", "confidence": 1.0, "change_history": [],
                    "status": "active",
                },
                {
                    "id": "b", "text": "ANOTHER_PRIVATE_SENTINEL",
                    "category": "facts", "memory_type": "temporary",
                    "created_at": "2020-01-01T00:00:00", "timestamp": "2020-01-01T00:00:00",
                    "status": "archived",
                },
                {
                    "id": "c", "category": "facts", "status": "superseded",
                    "change_history": [{"action": "update"}],
                },
            ],
        })
        before = Path(read_only_audit.MEMORY_FILE).read_bytes()
        result = read_only_audit.audit_memory()
        after = Path(read_only_audit.MEMORY_FILE).read_bytes()

        self.assertTrue(result["ok"])
        report = result["result"]
        self.assertEqual(report["total_entries"], 3)
        self.assertEqual(report["effective_memory_types"],
                         {"permanent": 1, "long_term": 1, "temporary": 1})
        self.assertEqual(report["entries_without_explicit_memory_type"], 1)
        self.assertEqual(report["status_counts"]["archived"], 1)
        self.assertEqual(report["status_counts"]["superseded"], 1)
        self.assertEqual(report["metadata_field_counts"]["provenance"], 1)
        self.assertEqual(report["metadata_field_counts"]["change_history_nonempty"], 1)
        self.assertNotIn("PRIVATE_SENTINEL_TEXT", repr(result))
        self.assertNotIn("ANOTHER_PRIVATE_SENTINEL", repr(result))
        self.assertEqual(before, after)

    def test_missing_file_is_not_created(self):
        result = read_only_audit.audit_memory()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "MEMORY_FILE_NOT_FOUND")
        self.assertFalse(os.path.exists(read_only_audit.MEMORY_FILE))

    def test_invalid_json_fails_without_returning_content(self):
        with open(read_only_audit.MEMORY_FILE, "w", encoding="utf-8") as handle:
            handle.write("PERSONAL_SECRET {")
        result = read_only_audit.audit_memory()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "MEMORY_JSON_INVALID")
        self.assertNotIn("PERSONAL_SECRET", repr(result))

    def test_invalid_entry_shape_fails_closed(self):
        self._write({"version": 2, "entries": ["not-an-entry"]})
        result = read_only_audit.audit_memory()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "MEMORY_ENTRY_INVALID")

    def test_expired_active_temporary_is_counted_but_not_archived(self):
        self._write({
            "version": 2,
            "entries": [{
                "id": "expired", "category": "facts",
                "memory_type": "temporary", "status": "active",
                "created_at": "2000-01-01T00:00:00",
                "expires_at": "2000-01-08T00:00:00",
            }],
        })
        before = open(read_only_audit.MEMORY_FILE, "rb").read()
        result = read_only_audit.audit_memory()
        after = open(read_only_audit.MEMORY_FILE, "rb").read()
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["expired_temporary_active"], 1)
        self.assertEqual(result["result"]["status_counts"]["archived"], 0)
        self.assertEqual(before, after)

    def test_malformed_legacy_category_does_not_crash_audit(self):
        self._write({"version": 2, "entries": [{"category": [], "status": "active"}]})
        result = read_only_audit.audit_memory()
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["effective_memory_types"]["long_term"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
