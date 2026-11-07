"""Dynamic safety tests for P3.2.4.5 semantic guardrails.

These tests exercise only the pure semantic guard API. They never call
memory_core, touch canonical memory, or create temporary files.
"""
import builtins
import copy
import io
import os
import sqlite3
import unittest
from dataclasses import FrozenInstanceError
from unittest import mock

import memory.semantic_guardrails as guard_module
from memory.semantic_guardrails import FactFrame, GuardDecision, analyze_fact_pair


def record(text, category="facts"):
    return {"id": text[:12], "text": text, "category": category}


def frame(**overrides):
    values = {
        "subject": "roman",
        "predicate": "uses",
        "polarity": "affirmed",
        "state": "enabled",
        "value": 8,
        "unit": "gb",
        "semantic_role": "ram",
        "interval_start": "2026-01-01",
        "interval_end": "2026-12-31",
        "modality": "asserted",
        "details": "",
        "provenance": "user",
    }
    values.update(overrides)
    return FactFrame(**values)


class SemanticGuardSafetyTests(unittest.TestCase):
    def test_fact_frame_is_immutable(self):
        item = frame()
        with self.assertRaises(FrozenInstanceError):
            item.subject = "other"

    def test_guard_decision_is_immutable_and_uses_immutable_collections(self):
        result = analyze_fact_pair(record("same"), record("same"))
        self.assertIsInstance(result, GuardDecision)
        self.assertIsInstance(result.reason_codes, tuple)
        self.assertIsInstance(result.evidence, tuple)
        with self.assertRaises(FrozenInstanceError):
            result.relation = "CONTRADICTION"

    def test_input_records_and_mapping_frames_are_not_mutated(self):
        left_record = record("left fact")
        right_record = record("right fact")
        left_frame = {
            "subject": "roman",
            "predicate": "uses",
            "polarity": "affirmed",
            "state": "enabled",
            "value": 8,
            "unit": "gb",
            "semantic_role": "ram",
            "interval_start": "2026-01-01",
            "interval_end": "2026-12-31",
            "modality": "asserted",
            "details": "",
            "provenance": "user",
        }
        right_frame = copy.deepcopy(left_frame)
        right_frame["details"] = "deployment context"
        before = copy.deepcopy((left_record, right_record, left_frame, right_frame))

        analyze_fact_pair(left_record, right_record, left_frame, right_frame)

        self.assertEqual(
            (left_record, right_record, left_frame, right_frame),
            before,
        )

    def test_uncertain_is_fail_closed_and_never_an_apply_instruction(self):
        result = analyze_fact_pair(
            record("fact A"),
            record("fact B"),
            frame(provenance=None),
            frame(),
        )
        self.assertEqual(result.relation, "UNCERTAIN")
        self.assertEqual(result.decision, "UNCERTAIN")
        self.assertIn("PROVENANCE_UNKNOWN", result.reason_codes)
        self.assertNotIn("APPLY", result.decision)
        self.assertNotIn("MERGE", result.decision)
        self.assertNotIn("DELETE", result.decision)

    def test_duplicate_and_refinement_are_review_only_not_mutations(self):
        duplicate = analyze_fact_pair(record("a"), record("b"), frame(), frame())
        refinement = analyze_fact_pair(
            record("a"),
            record("b"),
            frame(details=""),
            frame(details="deployment context"),
        )
        self.assertEqual(duplicate.decision, "CANDIDATE_FOR_REVIEW")
        self.assertEqual(refinement.decision, "CANDIDATE_FOR_REVIEW")
        self.assertFalse(hasattr(guard_module, "apply_decision"))
        self.assertFalse(hasattr(guard_module, "merge_records"))
        self.assertFalse(hasattr(guard_module, "delete_record"))
        self.assertFalse(hasattr(guard_module, "persist_decision"))

    def test_guard_calls_do_not_perform_file_or_database_io(self):
        left = record("fact A")
        right = record("fact B")
        left_frame = frame(provenance=None)
        right_frame = frame()

        forbidden = AssertionError("semantic guard attempted an I/O side effect")
        with (
            mock.patch.object(builtins, "open", side_effect=forbidden),
            mock.patch.object(io, "open", side_effect=forbidden),
            mock.patch.object(os, "remove", side_effect=forbidden),
            mock.patch.object(os, "unlink", side_effect=forbidden),
            mock.patch.object(os, "replace", side_effect=forbidden),
            mock.patch.object(os, "rename", side_effect=forbidden),
            mock.patch.object(sqlite3, "connect", side_effect=forbidden),
        ):
            uncertain = analyze_fact_pair(left, right, left_frame, right_frame)
            duplicate = analyze_fact_pair(record("same"), record("same"))

        self.assertEqual(uncertain.decision, "UNCERTAIN")
        self.assertEqual(duplicate.decision, "CANDIDATE_FOR_REVIEW")

    def test_module_has_no_memory_persistence_dependency(self):
        forbidden_names = {
            "memory_core", "sqlite3", "json", "subprocess", "Path",
        }
        self.assertTrue(forbidden_names.isdisjoint(vars(guard_module)))
        self.assertFalse(hasattr(guard_module, "add_memory"))
        self.assertFalse(hasattr(guard_module, "save_memory"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
