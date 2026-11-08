"""Tests for guarded, review-first semantic consolidation."""
import copy
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from memory import memory_core
from memory.guarded_semantic_consolidation import (
    GuardedSemanticConsolidationError,
    find_guarded_semantic_consolidation_candidates,
)
from memory.semantic_guardrails import FactFrame


def entry(identifier, text, **extra):
    result = {
        "id": identifier,
        "timestamp": "2026-01-01T10:00:00",
        "text": text,
        "category": "facts",
        "importance": 5,
        "source": "user",
        "topics": ["test"],
        "status": "active",
    }
    result.update(extra)
    return result


def frame(**overrides):
    values = {
        "subject": "roman",
        "predicate": "resides_in",
        "polarity": "affirmed",
        "state": "current",
        "value": "germany",
        "unit": "country",
        "semantic_role": "location",
        "interval_start": "2026-01-01",
        "interval_end": "2026-12-31",
        "modality": "asserted",
        "details": "",
        "provenance": "user",
    }
    values.update(overrides)
    return FactFrame(**values)


class GuardedSemanticCandidateTests(unittest.TestCase):
    def setUp(self):
        self.entries = [
            entry("a", "Роман проживает в Германии"),
            entry("b", "Роман живёт в Германии"),
        ]
        self.vectors = lambda texts: [[1.0, 0.0] for _ in texts]

    def test_paraphrase_requires_and_passes_structured_fact_guard(self):
        before = copy.deepcopy(self.entries)
        result = find_guarded_semantic_consolidation_candidates(
            self.entries,
            self.vectors,
            lambda records: {item["id"]: frame() for item in records},
        )
        self.assertEqual(len(result), 1)
        candidate = result[0]
        self.assertEqual(candidate["entry_ids"], ["a", "b"])
        self.assertEqual(candidate["candidate_policy"], "guarded_semantic_review_only")
        self.assertEqual(candidate["guard_decisions"][0]["relation"], "DUPLICATE")
        self.assertEqual(
            candidate["guard_decisions"][0]["decision"],
            "CANDIDATE_FOR_REVIEW",
        )
        self.assertEqual(self.entries, before)

    def test_numeric_conflict_is_rejected_even_with_identical_embeddings(self):
        entries = [
            entry("a", "Устройство использует 8 GB RAM"),
            entry("b", "Устройство использует 8 GB RAM"),
        ]
        frames = {
            "a": frame(predicate="has_ram", value=8, unit="gb", semantic_role="ram"),
            "b": frame(predicate="has_ram", value=12, unit="gb", semantic_role="ram"),
        }
        result = find_guarded_semantic_consolidation_candidates(
            entries, self.vectors, lambda records: frames
        )
        self.assertEqual(result, [])

    def test_different_subjects_are_rejected(self):
        result = find_guarded_semantic_consolidation_candidates(
            self.entries,
            self.vectors,
            lambda records: {
                "a": frame(subject="roman"),
                "b": frame(subject="maria"),
            },
        )
        self.assertEqual(result, [])

    def test_missing_frame_fails_closed(self):
        result = find_guarded_semantic_consolidation_candidates(
            self.entries,
            self.vectors,
            lambda records: {"a": frame()},
        )
        self.assertEqual(result, [])

    def test_archived_and_superseded_entries_are_not_sent_to_providers(self):
        entries = self.entries + [
            entry("archived", "Роман живёт в Германии", status="archived"),
            entry("superseded", "Роман живёт в Германии", superseded_by="a"),
        ]
        seen = {}

        def embed(texts):
            seen["embed_count"] = len(texts)
            return [[1.0, 0.0] for _ in texts]

        def extract(records):
            seen["frame_ids"] = [item["id"] for item in records]
            return {item["id"]: frame() for item in records}

        result = find_guarded_semantic_consolidation_candidates(
            entries, embed, extract
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(seen["embed_count"], 2)
        self.assertEqual(seen["frame_ids"], ["a", "b"])

    def test_fact_frame_provider_failure_is_explicit(self):
        def broken(records):
            raise RuntimeError("provider offline")

        with self.assertRaisesRegex(
            GuardedSemanticConsolidationError, "FACT_FRAME_PROVIDER_FAILED"
        ):
            find_guarded_semantic_consolidation_candidates(
                self.entries, self.vectors, broken
            )

    def test_malformed_fact_frame_result_is_rejected(self):
        with self.assertRaisesRegex(
            GuardedSemanticConsolidationError, "INVALID_FACT_FRAME_RESULT"
        ):
            find_guarded_semantic_consolidation_candidates(
                self.entries, self.vectors, lambda records: []
            )

    def test_provider_receives_copies_not_live_entry_objects(self):
        before = copy.deepcopy(self.entries)

        def mutate(records):
            records[0]["text"] = "provider mutation"
            return {item["id"]: frame() for item in records}

        find_guarded_semantic_consolidation_candidates(
            self.entries, self.vectors, mutate
        )
        self.assertEqual(self.entries, before)


class GuardedSemanticMemoryCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="guarded_semantic_memory_")
        self.memory_path = os.path.join(self.tmp, "memory.json")
        self.path_patch = mock.patch.object(
            memory_core, "MEMORY_FILE", self.memory_path
        )
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def _write(self, entries):
        with open(self.memory_path, "w", encoding="utf-8") as handle:
            json.dump({"version": 2, "entries": entries}, handle, ensure_ascii=False)

    def test_preview_is_read_only_and_returns_guarded_candidates(self):
        entries = [
            entry("a", "Роман проживает в Германии"),
            entry("b", "Роман живёт в Германии"),
        ]
        self._write(entries)
        with open(self.memory_path, "rb") as handle:
            before = handle.read()

        result = memory_core.preview_guarded_semantic_memory_consolidation(
            lambda texts: [[1.0, 0.0] for _ in texts],
            lambda records: {item["id"]: frame() for item in records},
        )

        with open(self.memory_path, "rb") as handle:
            after = handle.read()
        self.assertEqual(len(result), 1)
        self.assertEqual(before, after)

    def test_guarded_candidate_uses_existing_explicit_apply_and_keeps_sources(self):
        entries = [
            entry("a", "Роман проживает в Германии"),
            entry("b", "Роман живёт в Германии"),
        ]
        self._write(entries)
        candidate = memory_core.preview_guarded_semantic_memory_consolidation(
            lambda texts: [[1.0, 0.0] for _ in texts],
            lambda records: {item["id"]: frame() for item in records},
        )[0]

        # The existing protected apply path is invoked explicitly in this test
        # against a temporary file; no canonical memory is accessed.
        with mock.patch.object(memory_core, "_backup_memory_snapshot", return_value="test-backup"):
            result = memory_core.apply_memory_consolidation(
                candidate, "Роман проживает в Германии."
            )

        self.assertTrue(result["ok"], result)
        with open(self.memory_path, "r", encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertEqual(len(saved["entries"]), 1)
        consolidated = saved["entries"][0]
        self.assertEqual(
            [item["id"] for item in consolidated["consolidation_sources"]],
            ["a", "b"],
        )
        self.assertEqual(
            [item["text"] for item in consolidated["consolidation_sources"]],
            [item["text"] for item in entries],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
