"""Isolated tests for the fact-extractor candidate queue.

All filesystem operations use a temporary directory. The real Brain memory
and candidate queue are never accessed.
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import memory.fact_extractor as fact_extractor


class TestCandidateQueue(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="brain_candidate_queue_")
        self.queue_path = os.path.join(self.tmpdir, "brain_memory_candidates.json")
        self.path_patch = mock.patch.object(fact_extractor, "CANDIDATES_PATH", self.queue_path)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)

    def _write_raw(self, raw):
        with open(self.queue_path, "w", encoding="utf-8") as f:
            f.write(raw)

    def _read_bytes(self):
        with open(self.queue_path, "rb") as f:
            return f.read()

    def test_missing_queue_is_empty(self):
        self.assertEqual(fact_extractor.load_candidates(), [])
        self.assertTrue(fact_extractor.save_candidate({"text": "first fact"}))
        self.assertEqual(len(fact_extractor.load_candidates()), 1)

    def test_ids_are_unique_for_rapid_additions(self):
        self.assertTrue(fact_extractor.save_candidate({"text": "first fact"}))
        self.assertTrue(fact_extractor.save_candidate({"text": "second fact"}))
        candidates = fact_extractor.load_candidates()
        self.assertEqual(len(candidates), 2)
        self.assertNotEqual(candidates[0]["id"], candidates[1]["id"])

    def test_corrupt_json_is_not_overwritten_by_save(self):
        self._write_raw('{"candidates": [')
        before = self._read_bytes()
        self.assertFalse(fact_extractor.save_candidate({"text": "new fact"}))
        self.assertEqual(self._read_bytes(), before)

    def test_invalid_structure_is_not_overwritten(self):
        self._write_raw('{"items": []}')
        before = self._read_bytes()
        self.assertEqual(fact_extractor.load_candidates(), [])
        self.assertFalse(fact_extractor.save_candidate({"text": "new fact"}))
        self.assertEqual(self._read_bytes(), before)

    def test_invalid_candidate_entry_is_rejected(self):
        self._write_raw('{"candidates": ["not-an-object"]}')
        before = self._read_bytes()
        self.assertFalse(fact_extractor.save_candidate({"text": "new fact"}))
        self.assertFalse(fact_extractor.clear_candidates())
        self.assertEqual(self._read_bytes(), before)

    def test_approve_removes_only_selected_candidate(self):
        self.assertTrue(fact_extractor.save_candidate({"text": "first fact"}))
        self.assertTrue(fact_extractor.save_candidate({"text": "second fact"}))
        candidates = fact_extractor.load_candidates()
        selected = candidates[0]
        approved = fact_extractor.approve_candidate(selected["id"])
        self.assertEqual(approved["text"], "first fact")
        remaining = fact_extractor.load_candidates()
        self.assertEqual([item["text"] for item in remaining], ["second fact"])

    def test_failed_atomic_replace_preserves_original_queue(self):
        self.assertTrue(fact_extractor.save_candidate({"text": "existing fact"}))
        before = self._read_bytes()
        with mock.patch.object(fact_extractor.os, "replace", side_effect=OSError("mock replace")):
            self.assertFalse(fact_extractor.save_candidate({"text": "new fact"}))
        self.assertEqual(self._read_bytes(), before)
        self.assertFalse(any(name.endswith(".tmp") for name in os.listdir(self.tmpdir)))

    def test_clear_candidates_uses_validated_atomic_write(self):
        self.assertTrue(fact_extractor.save_candidate({"text": "existing fact"}))
        self.assertTrue(fact_extractor.clear_candidates())
        self.assertEqual(fact_extractor.load_candidates(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
