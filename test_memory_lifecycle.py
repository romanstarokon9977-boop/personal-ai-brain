import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from unittest import mock

from memory import memory_core
from memory.lifecycle import (
    active_entries,
    archive_expired_entries,
    initialize_entry_metadata,
)


class MemoryLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="memory_lifecycle_")
        self.path_patch = mock.patch.object(
            memory_core, "MEMORY_FILE", os.path.join(self.tmp, "brain_memory.json")
        )
        self.path_patch.start()
        self.file_patch = mock.patch.object(
            memory_core, "__file__", os.path.join(self.tmp, "memory", "memory_core.py")
        )
        self.file_patch.start()

    def tearDown(self):
        self.file_patch.stop()
        self.path_patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_retention_defaults_are_conservative_and_distinct(self):
        permanent = initialize_entry_metadata({"category": "arch_rules", "timestamp": "2026-01-01 00:00:00"})
        long_term = initialize_entry_metadata({"category": "facts", "timestamp": "2026-01-01 00:00:00"})
        temporary = initialize_entry_metadata(
            {"category": "facts", "timestamp": "2026-01-01 00:00:00"},
            memory_type="temporary",
        )
        self.assertEqual(permanent["memory_type"], "permanent")
        self.assertNotIn("expires_at", permanent)
        self.assertEqual(long_term["memory_type"], "long_term")
        self.assertEqual(long_term["review_at"], "2027-01-01T00:00:00")
        self.assertEqual(temporary["memory_type"], "temporary")
        self.assertEqual(temporary["expires_at"], "2026-01-08T00:00:00")

    def test_expired_temporary_is_archived_not_deleted(self):
        entries = [{
            "id": "temp-1", "text": "temporary note",
            "category": "facts", "memory_type": "temporary",
            "timestamp": "2026-01-01T00:00:00",
            "expires_at": "2026-01-08T00:00:00",
        }, {
            "id": "permanent-1", "text": "permanent rule",
            "category": "arch_rules", "memory_type": "permanent",
            "timestamp": "2025-01-01T00:00:00",
        }]
        archived, count = archive_expired_entries(entries, now=datetime(2026, 1, 9))
        self.assertEqual(count, 1)
        self.assertEqual(len(archived), 2)
        self.assertEqual(archived[0]["status"], "archived")
        self.assertEqual(archived[0]["change_history"][-1]["action"], "retention_archive")
        self.assertEqual([item["id"] for item in active_entries(archived, now=datetime(2026, 1, 9))], ["permanent-1"])
        self.assertEqual(entries[0].get("status"), None)

    def test_load_memory_archives_expired_temporary_entries(self):
        expired = {
            "id": "expired-1", "timestamp": "2026-01-01T00:00:00",
            "created_at": "2026-01-01T00:00:00",
            "text": "temporary context that is no longer active",
            "category": "facts", "memory_type": "temporary",
            "expires_at": "2026-01-08T00:00:00",
            "source": "user", "confidence": 0.9,
        }
        with open(memory_core.MEMORY_FILE, "w", encoding="utf-8") as handle:
            json.dump({"version": 2, "entries": [expired]}, handle)
        loaded = memory_core.load_memory()
        self.assertEqual(len(loaded["entries"]), 1)
        self.assertEqual(loaded["entries"][0]["status"], "archived")
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "backups_memory")))

    def test_add_and_refine_preserves_provenance_and_change_history(self):
        with open(memory_core.MEMORY_FILE, "w", encoding="utf-8") as handle:
            json.dump({"version": 2, "entries": []}, handle)
        result = memory_core.add_memory(
            "Пользователь использует отдельную тестовую среду для проверки памяти.",
            category="facts", source="user_explicit", confidence=1.0,
            memory_type="permanent",
        )
        self.assertTrue(result.startswith("Сохранено в"))
        before = memory_core._load_raw()["entries"][0]
        original_created = before["created_at"]
        original_source_date = before["source_date"]
        updated = memory_core.update_memory_entry(
            before["id"],
            {
                "text": "Пользователь использует отдельную тестовую среду для проверки жизненного цикла памяти.",
                "source": "user_confirmed",
                "confidence": 0.95,
            },
            expected_text=before["text"],
        )
        self.assertTrue(updated.startswith("Обновлена запись"))
        after = memory_core._load_raw()["entries"][0]
        self.assertEqual(after["created_at"], original_created)
        self.assertEqual(after["source_date"], original_source_date)
        self.assertEqual(after["source"], "user_confirmed")
        self.assertEqual(after["provenance"]["source"], "user_confirmed")
        self.assertEqual(len(after["change_history"]), 1)
        self.assertEqual(after["change_history"][0]["before"]["text"], before["text"])
        self.assertEqual(after["change_history"][0]["after"]["text"], after["text"])

    def test_contradictory_fact_supersedes_instead_of_erasing_old_record(self):
        old = {
            "id": "old-fact", "timestamp": "2026-01-01 00:00:00",
            "text": "старый подтверждённый факт о настройке памяти",
            "category": "facts", "importance": 5, "source": "user",
            "confidence": 0.9, "topics": [],
        }
        with open(memory_core.MEMORY_FILE, "w", encoding="utf-8") as handle:
            json.dump({"version": 2, "entries": [old]}, handle)
        with mock.patch.object(memory_core, "_find_similar_entry", return_value=None), \
             mock.patch.object(memory_core, "_find_contradictions", side_effect=lambda entries, text: [entries[0]]):
            result = memory_core.add_memory(
                "новый подтверждённый факт о настройке памяти",
                category="facts", source="user_explicit",
            )
        self.assertTrue(result.startswith("Сохранено в"))
        entries = memory_core._load_raw()["entries"]
        self.assertEqual(len(entries), 2)
        previous = next(item for item in entries if item["id"] == "old-fact")
        self.assertEqual(previous["status"], "superseded")
        self.assertTrue(previous["superseded_by"])
        self.assertEqual(previous["change_history"][-1]["action"], "fact_superseded")


if __name__ == "__main__":
    unittest.main(verbosity=2)
