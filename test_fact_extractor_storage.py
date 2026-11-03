import json
import os
import tempfile
import unittest
from unittest import mock

from memory import fact_extractor as fe


class FactExtractorStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = fe.CANDIDATES_PATH
        fe.CANDIDATES_PATH = os.path.join(self.temp_dir.name, "candidates.json")

    def tearDown(self):
        fe.CANDIDATES_PATH = self.original_path
        self.temp_dir.cleanup()

    def read_raw(self):
        with open(fe.CANDIDATES_PATH, "rb") as f:
            return f.read()

    def write_raw(self, raw):
        with open(fe.CANDIDATES_PATH, "wb") as f:
            f.write(raw)

    def sample_fact(self, text="Пользователь предпочитает подробные технические объяснения."):
        return {
            "text": text,
            "category": "preferences",
            "source": "user_stated",
            "confidence": 0.85,
        }

    def test_save_candidate_creates_unique_ids_and_round_trips(self):
        fact = self.sample_fact()
        self.assertTrue(fe.save_candidate(fact))
        self.assertTrue(fe.save_candidate(fact))

        candidates = fe.load_candidates()
        self.assertEqual(len(candidates), 2)
        self.assertNotEqual(candidates[0]["id"], candidates[1]["id"])
        self.assertEqual(candidates[0]["text"], fact["text"])
        self.assertTrue(os.path.exists(fe.CANDIDATES_PATH))

    def test_corrupt_json_is_preserved_by_all_mutations(self):
        corrupt = b'{"candidates": ['
        self.write_raw(corrupt)

        self.assertFalse(fe.save_candidate(self.sample_fact()))
        self.assertFalse(fe.clear_candidates())
        self.assertFalse(fe.remove_candidate("cand_missing"))
        self.assertIsNone(fe.get_candidate("cand_missing"))
        self.assertEqual(self.read_raw(), corrupt)

    def test_invalid_structure_is_preserved(self):
        invalid_payloads = (
            b'[]',
            b'{"candidates": {}}',
            b'{"candidates": [{"id": "x"}]}',
            b'{"candidates": [{"id": "x", "text": "fact"}, {"id": "x", "text": "duplicate"}]}',
        )
        for raw in invalid_payloads:
            with self.subTest(raw=raw):
                self.write_raw(raw)
                self.assertFalse(fe.save_candidate(self.sample_fact()))
                self.assertFalse(fe.clear_candidates())
                self.assertEqual(self.read_raw(), raw)

    def test_get_candidate_does_not_consume_and_remove_is_explicit(self):
        self.assertTrue(fe.save_candidate(self.sample_fact()))
        candidate = fe.load_candidates()[0]

        self.assertEqual(fe.get_candidate(candidate["id"])["id"], candidate["id"])
        self.assertEqual(len(fe.load_candidates()), 1)

        self.assertTrue(fe.remove_candidate(candidate["id"]))
        self.assertEqual(fe.load_candidates(), [])
        self.assertFalse(fe.remove_candidate(candidate["id"]))

    def test_atomic_replace_failure_preserves_previous_file(self):
        self.assertTrue(fe.save_candidate(self.sample_fact()))
        original = self.read_raw()

        with mock.patch.object(fe.os, "replace", side_effect=OSError("simulated replace failure")):
            self.assertFalse(fe.save_candidate(self.sample_fact("Другой устойчивый факт пользователя.")))

        self.assertEqual(self.read_raw(), original)
        leftovers = [
            name for name in os.listdir(self.temp_dir.name)
            if name.endswith(".tmp")
        ]
        self.assertEqual(leftovers, [])

    def test_missing_queue_is_a_valid_empty_state(self):
        self.assertEqual(fe.load_candidates(), [])
        self.assertTrue(fe.clear_candidates())
        self.assertTrue(fe.save_candidate(self.sample_fact()))
        self.assertEqual(len(fe.load_candidates()), 1)

    def test_invalid_fact_is_not_written(self):
        self.assertFalse(fe.save_candidate(None))
        self.assertFalse(fe.save_candidate({"text": "   "}))
        self.assertFalse(os.path.exists(fe.CANDIDATES_PATH))


if __name__ == "__main__":
    unittest.main()
