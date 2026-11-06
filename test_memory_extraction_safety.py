import json
import os
import tempfile
import unittest
from unittest import mock

from memory import memory_core


class MemoryExtractionSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="memory_extract_safety_")
        self.path_patch = mock.patch.object(
            memory_core, "MEMORY_FILE", os.path.join(self.tmp, "brain_memory.json")
        )
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)

    def test_corrupt_memory_raises_instead_of_becoming_empty(self):
        with open(memory_core.MEMORY_FILE, "w", encoding="utf-8") as f:
            f.write("{ broken")
        with self.assertRaises(memory_core.MemoryReadError):
            memory_core.load_entries_for_fact_extraction()

    def test_valid_memory_returns_entries(self):
        expected = [{"id": "one", "text": "stable fact"}]
        with open(memory_core.MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump({"version": 2, "entries": expected}, f)
        self.assertEqual(memory_core.load_entries_for_fact_extraction(), expected)

    def test_compare_and_swap_refuses_stale_refinement(self):
        entry = {
            "id": "entry1", "timestamp": "2026-01-01 00:00:00",
            "text": "current fact", "category": "facts",
            "importance": 0.5, "source": "user", "topics": [],
        }
        with open(memory_core.MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump({"version": 2, "entries": [entry]}, f)
        result = memory_core.update_memory_entry(
            "entry1", {"text": "stale replacement"}, expected_text="older fact"
        )
        self.assertTrue(result.startswith("MEMORY_UPDATE_CONFLICT"))
        with open(memory_core.MEMORY_FILE, "r", encoding="utf-8") as f:
            self.assertEqual(json.load(f)["entries"][0]["text"], "current fact")


if __name__ == "__main__":
    unittest.main(verbosity=2)
