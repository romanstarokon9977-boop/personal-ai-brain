import unittest

from memory.fact_extractor import resolve_candidate_id


class CandidateIdResolutionTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            {"id": "cand_20261106_120000_abcdef123456"},
            {"id": "cand_20261106_120001_abcdef999999"},
        ]

    def test_exact_id(self):
        full = self.items[0]["id"]
        self.assertEqual(resolve_candidate_id(full, self.items), (full, None))

    def test_unique_prefix(self):
        self.assertEqual(
            resolve_candidate_id("cand_20261106_120000", self.items),
            (self.items[0]["id"], None),
        )

    def test_ambiguous_prefix_rejected(self):
        self.assertEqual(
            resolve_candidate_id("cand_20261106", self.items),
            (None, "CANDIDATE_ID_AMBIGUOUS"),
        )

    def test_unknown_and_empty_rejected(self):
        self.assertEqual(resolve_candidate_id("missing", self.items), (None, "CANDIDATE_NOT_FOUND"))
        self.assertEqual(resolve_candidate_id(" ", self.items), (None, "EMPTY_ID"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
