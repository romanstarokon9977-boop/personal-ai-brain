import unittest
from unittest import mock

from memory import fact_extractor


class FactRefinementSafetyTests(unittest.TestCase):
    def test_refinement_is_queued_for_confirmation(self):
        candidate = {
            "text": "a more complete stable fact",
            "category": "facts",
            "source": "user_claim",
            "confidence": 0.9,
        }
        existing = {"id": "entry-1", "text": "old stable fact"}
        with mock.patch.object(fact_extractor, "detect_fact_candidate", return_value=candidate), \
             mock.patch.object(fact_extractor, "validate_stability", return_value=(True, "OK")), \
             mock.patch.object(fact_extractor, "check_duplicate_or_refinement", return_value=("REFINEMENT", existing)):
            result = fact_extractor.process_extraction_flow("user says fact", "", [existing])
        self.assertEqual(result["action"], "ENQUEUE_UPDATE")
        self.assertEqual(result["target_entry_id"], "entry-1")
        self.assertEqual(result["expected_old_text"], "old stable fact")
        self.assertEqual(result["fact"], candidate)


if __name__ == "__main__":
    unittest.main(verbosity=2)
