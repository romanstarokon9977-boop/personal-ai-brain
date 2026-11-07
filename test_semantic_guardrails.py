"""Adversarial tests for the pure P3.2.4.4 semantic guard module."""
import copy
import unittest

from memory.semantic_guardrails import FactFrame, SemanticGuardError, analyze_fact_pair


def record(text, category="facts"):
    return {"id": text[:12], "text": text, "category": category}


def frame(**overrides):
    values = {
        "subject": "roman", "predicate": "uses", "polarity": "affirmed",
        "state": "enabled", "value": 8, "unit": "gb", "semantic_role": "ram",
        "interval_start": "2026-01-01", "interval_end": "2026-12-31",
        "modality": "asserted", "details": "", "provenance": "user",
    }
    values.update(overrides)
    return FactFrame(**values)


class SemanticGuardPositiveTests(unittest.TestCase):
    def test_identical_complete_frames_are_review_candidates(self):
        result = analyze_fact_pair(record("same wording"), record("different wording"), frame(), frame())
        self.assertEqual((result.relation, result.decision), ("DUPLICATE", "CANDIDATE_FOR_REVIEW"))
        self.assertIn("FRAME_MATCH", result.reason_codes)

    def test_compatible_additional_detail_is_refinement_candidate(self):
        left = frame(details="")
        right = frame(details="deployment context")
        result = analyze_fact_pair(record("fact"), record("more detailed fact"), left, right)
        self.assertEqual((result.relation, result.decision), ("REFINEMENT", "CANDIDATE_FOR_REVIEW"))

    def test_unrelated_extra_details_remain_uncertain(self):
        result = analyze_fact_pair(
            record("fact"), record("another fact"),
            frame(details="production environment"),
            frame(details="personal preference"),
        )
        self.assertEqual(result.decision, "UNCERTAIN")

    def test_exact_normalized_text_without_frames_is_review_only(self):
        result = analyze_fact_pair(record("Роман живёт в Германии"), record(" роман   живёт в Германии "))
        self.assertEqual(result.relation, "DUPLICATE")
        self.assertEqual(result.decision, "CANDIDATE_FOR_REVIEW")


class SemanticGuardAdversarialTests(unittest.TestCase):
    def test_different_subjects_are_independent(self):
        result = analyze_fact_pair(record("a"), record("b"), frame(), frame(subject="maria"))
        self.assertEqual((result.relation, result.decision), ("RELATED_INDEPENDENT", "SEPARATE"))
        self.assertIn("SUBJECT_MISMATCH", result.reason_codes)

    def test_different_predicates_are_independent(self):
        result = analyze_fact_pair(record("a"), record("b"), frame(), frame(predicate="owns"))
        self.assertEqual(result.relation, "RELATED_INDEPENDENT")

    def test_opposite_polarity_is_contradiction(self):
        result = analyze_fact_pair(record("a"), record("b"), frame(), frame(polarity="negated"))
        self.assertEqual(result.relation, "CONTRADICTION")
        self.assertEqual(result.decision, "SEPARATE")

    def test_presence_absence_state_conflict_is_contradiction(self):
        result = analyze_fact_pair(record("a"), record("b"), frame(), frame(state="disabled"))
        self.assertEqual(result.relation, "CONTRADICTION")

    def test_swapped_numeric_roles_are_not_merged(self):
        left = frame(value=8, semantic_role="ram")
        right = frame(value=256, semantic_role="storage")
        result = analyze_fact_pair(record("a"), record("b"), left, right)
        self.assertEqual(result.relation, "CONTRADICTION")
        self.assertIn("VALUE_CONFLICT", result.reason_codes)

    def test_same_number_with_different_units_is_not_merged(self):
        result = analyze_fact_pair(record("a"), record("b"), frame(unit="gb"), frame(unit="tb"))
        self.assertEqual(result.relation, "CONTRADICTION")
        self.assertIn("UNIT_CONFLICT", result.reason_codes)

    def test_different_dates_are_not_silently_merged(self):
        left = frame(interval_start="2026-01-01", interval_end="2026-01-31")
        right = frame(interval_start="2026-03-01", interval_end="2026-03-31")
        result = analyze_fact_pair(record("a"), record("b"), left, right)
        self.assertEqual((result.relation, result.decision), ("RELATED_INDEPENDENT", "SEPARATE"))

    def test_incomplete_interval_is_uncertain(self):
        result = analyze_fact_pair(record("a"), record("b"), frame(interval_end=None), frame())
        self.assertEqual(result.decision, "UNCERTAIN")
        self.assertIn("INTERVAL_INCOMPLETE", result.reason_codes)

    def test_modality_mismatch_is_uncertain(self):
        result = analyze_fact_pair(record("a"), record("b"), frame(modality="must"), frame(modality="may"))
        self.assertEqual(result.decision, "UNCERTAIN")
        self.assertIn("MODALITY_MISMATCH", result.reason_codes)

    def test_unknown_required_attributes_fail_closed(self):
        result = analyze_fact_pair(record("a"), record("b"), frame(subject=None), frame(subject=None))
        self.assertEqual((result.relation, result.decision), ("UNCERTAIN", "UNCERTAIN"))

    def test_one_missing_frame_is_uncertain(self):
        result = analyze_fact_pair(record("a"), record("b"), frame(), None)
        self.assertEqual(result.decision, "UNCERTAIN")
        self.assertIn("FRAME_MISSING", result.reason_codes)

    def test_missing_provenance_is_uncertain(self):
        result = analyze_fact_pair(
            record("a"), record("b"),
            frame(provenance=None), frame(),
        )
        self.assertEqual(result.decision, "UNCERTAIN")
        self.assertIn("PROVENANCE_UNKNOWN", result.reason_codes)

    def test_causally_or_topically_related_text_is_not_proof(self):
        result = analyze_fact_pair(
            record("перегрев ускоряет разряд батареи"),
            record("температура ускоряет износ аккумулятора"),
        )
        self.assertEqual((result.relation, result.decision), ("UNCERTAIN", "UNCERTAIN"))

    def test_category_mismatch_is_separate(self):
        result = analyze_fact_pair(record("a", "facts"), record("b", "preferences"), frame(), frame())
        self.assertEqual(result.relation, "RELATED_INDEPENDENT")
        self.assertIn("CATEGORY_MISMATCH", result.reason_codes)

    def test_input_records_are_not_mutated(self):
        left, right = record("same"), record("same")
        before = copy.deepcopy((left, right))
        analyze_fact_pair(left, right, frame(), frame())
        self.assertEqual((left, right), before)

    def test_decision_is_immutable(self):
        result = analyze_fact_pair(record("same"), record("same"))
        with self.assertRaises(Exception):
            result.relation = "CONTRADICTION"

    def test_unknown_frame_fields_are_rejected(self):
        with self.assertRaisesRegex(SemanticGuardError, "UNKNOWN_LEFT_FRAME_FIELDS"):
            analyze_fact_pair(record("a"), record("b"), {"subject": "x", "surprise": "yes"}, frame())

    def test_malformed_record_fails_closed_with_error(self):
        with self.assertRaisesRegex(SemanticGuardError, "INVALID_LEFT_TEXT"):
            analyze_fact_pair({"text": ""}, record("b"))

    def test_non_finite_numeric_values_are_rejected(self):
        with self.assertRaisesRegex(SemanticGuardError, "INVALID_LEFT_VALUE"):
            analyze_fact_pair(record("a"), record("b"), frame(value=float("nan")), frame())


if __name__ == "__main__":
    unittest.main(verbosity=2)
