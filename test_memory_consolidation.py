"""Tests for review-first, loss-aware memory consolidation."""
import copy
import os
import tempfile
import unittest
from unittest import mock

from memory import memory_core
from memory.consolidation import (
    ConsolidationError,
    apply_consolidation,
    find_consolidation_candidates,
)


def entry(identifier, text, category="facts", importance=5, **extra):
    value = {
        "id": identifier,
        "timestamp": "2026-01-01 10:00:00",
        "text": text,
        "category": category,
        "importance": importance,
        "source": "user",
        "topics": [],
    }
    value.update(extra)
    return value


class ConsolidationPureTests(unittest.TestCase):
    def test_exact_duplicates_are_candidates_without_mutation(self):
        original = [
            entry("a", "Роман использует Termux на Android"),
            entry("b", "роман   использует termux на android"),
        ]
        before = copy.deepcopy(original)
        groups = find_consolidation_candidates(original)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["entry_ids"], ["a", "b"])
        self.assertEqual(original, before)

    def test_similar_entries_need_same_category_and_preserve_conflicts(self):
        entries = [
            entry("a", "Пользователь предпочитает короткие ответы без лишней воды", "preferences"),
            entry("b", "Пользователь предпочитает короткие ответы без лишней воды и вступлений", "preferences"),
            entry("c", "Пользователь предпочитает короткие ответы без лишней воды", "facts"),
            entry("d", "Пользователь предпочитает не короткие ответы без лишней воды", "preferences"),
        ]
        groups = find_consolidation_candidates(entries, min_similarity=0.65)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["entry_ids"], ["a", "b"])

    def test_distinct_numbers_are_not_grouped(self):
        entries = [
            entry("a", "Пользователь использует 4 GB памяти на устройстве"),
            entry("b", "Пользователь использует 8 GB памяти на устройстве"),
        ]
        self.assertEqual(find_consolidation_candidates(entries), [])

    def test_apply_requires_nonempty_text_and_unchanged_snapshot(self):
        entries = [entry("a", "первый важный факт для памяти"), entry("b", "первый важный факт для памяти")]
        candidate = find_consolidation_candidates(entries)[0]
        with self.assertRaises(ConsolidationError):
            apply_consolidation(entries, candidate, " ")
        changed = copy.deepcopy(entries)
        changed[0]["text"] = "изменено после preview"
        with self.assertRaisesRegex(ConsolidationError, "STALE_CONSOLIDATION_CANDIDATE"):
            apply_consolidation(changed, candidate, "объединённый факт")

    def test_apply_keeps_full_source_records_and_metadata(self):
        entries = [
            entry("a", "пользователь работает в Termux на Android", importance=6, topics=["termux"], detail="first"),
            entry("b", "пользователь работает в Termux на Android", importance=9, topics=["android", "termux"], detail="second"),
            entry("c", "отдельная запись"),
        ]
        candidate = find_consolidation_candidates(entries)[0]
        result = apply_consolidation(entries, candidate, "Пользователь работает в Termux на Android.")
        self.assertEqual(len(result), 2)
        merged = result[0]
        self.assertEqual(merged["id"], "a")
        self.assertEqual(merged["importance"], 9)
        self.assertEqual(merged["topics"], ["termux", "android"])
        self.assertEqual(merged["source"], "consolidated")
        self.assertEqual([x["detail"] for x in merged["consolidation_sources"]], ["first", "second"])
        self.assertEqual(entries[0]["text"], "пользователь работает в Termux на Android")


class ConsolidationPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="memory_consolidation_")
        self.path_patch = mock.patch.object(memory_core, "MEMORY_FILE", os.path.join(self.tmp, "memory.json"))
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.file_patch = mock.patch.object(
            memory_core, "__file__", os.path.join(self.tmp, "memory", "memory_core.py")
        )
        self.file_patch.start()
        self.addCleanup(self.file_patch.stop)
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def _read_bytes(self):
        with open(memory_core.MEMORY_FILE, "rb") as handle:
            return handle.read()

    def _write(self, entries):
        with open(memory_core.MEMORY_FILE, "w", encoding="utf-8") as handle:
            import json
            json.dump({"version": 2, "entries": entries}, handle, ensure_ascii=False)

    def test_preview_is_read_only_and_apply_uses_existing_backup_pipeline(self):
        entries = [entry("a", "пользователь работает в Termux на Android"), entry("b", "пользователь работает в Termux на Android")]
        self._write(entries)
        before = self._read_bytes()
        groups = memory_core.preview_memory_consolidation()
        self.assertEqual(len(groups), 1)
        self.assertEqual(self._read_bytes(), before)
        result = memory_core.apply_memory_consolidation(groups[0], "Пользователь работает в Termux на Android.")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["remaining_entries"], 1)
        import json
        with open(memory_core.MEMORY_FILE, "r", encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertEqual(len(saved["entries"]), 1)
        self.assertEqual(len(saved["entries"][0]["consolidation_sources"]), 2)
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "backups_memory")))

    def test_corrupt_memory_is_not_treated_as_empty_or_modified(self):
        with open(memory_core.MEMORY_FILE, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        before = self._read_bytes()
        with self.assertRaises(memory_core.MemoryReadError):
            memory_core.preview_memory_consolidation()
        self.assertEqual(self._read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
