"""Tests for embedding-assisted, review-first semantic consolidation."""
import copy
import os
import tempfile
import unittest
from unittest import mock

from memory import memory_core
from memory.semantic_consolidation import (
    SemanticConsolidationError,
    find_semantic_consolidation_candidates,
)


def entry(identifier, text, category="facts"):
    return {
        "id": identifier,
        "timestamp": "2026-01-01 10:00:00",
        "text": text,
        "category": category,
        "importance": 5,
        "source": "user",
        "topics": [],
    }


class SemanticCandidateTests(unittest.TestCase):
    def test_different_wording_can_match_by_embedding(self):
        entries = [
            entry("a", "Роман живёт в Германии"),
            entry("b", "Roman resides in Deutschland"),
        ]
        before = copy.deepcopy(entries)
        vectors = {
            entries[0]["text"]: [1.0, 0.0, 0.0],
            entries[1]["text"]: [0.99, 0.01, 0.0],
        }
        groups = find_semantic_consolidation_candidates(
            entries, lambda texts: [vectors[text] for text in texts]
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["entry_ids"], ["a", "b"])
        self.assertEqual(groups[0]["match_type"], "semantic_embedding")
        self.assertEqual(entries, before)

    def test_category_number_and_negation_conflicts_are_excluded(self):
        entries = [
            entry("a", "Пользователь использует 8 GB памяти"),
            entry("b", "Пользователь применяет 4 GB памяти"),
            entry("c", "Пользователь использует память без облака"),
            entry("d", "Пользователь использует память в облаке"),
            entry("e", "Пользователь использует память", "preferences"),
        ]
        vectors = [[1.0, 0.0] for _ in entries]
        groups = find_semantic_consolidation_candidates(
            entries, lambda texts: vectors, min_similarity=0.99
        )
        self.assertEqual(groups, [])

    def test_complete_link_prevents_similarity_chaining(self):
        entries = [entry("a", "факт A"), entry("b", "факт B"), entry("c", "факт C")]
        vectors = [
            [1.0, 0.0],
            [0.9, 0.435889894],
            [0.9, -0.435889894],
        ]
        groups = find_semantic_consolidation_candidates(
            entries, lambda texts: vectors, min_similarity=0.8
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["entry_ids"], ["a", "b"])

    def test_bad_embedding_count_fails_closed(self):
        entries = [entry("a", "один факт"), entry("b", "другой факт")]
        with self.assertRaisesRegex(SemanticConsolidationError, "EMBEDDING_COUNT_MISMATCH"):
            find_semantic_consolidation_candidates(entries, lambda texts: [[1.0, 0.0]])

    def test_dimension_mismatch_and_non_finite_vectors_fail_closed(self):
        entries = [entry("a", "первый факт"), entry("b", "второй факт")]
        with self.assertRaisesRegex(SemanticConsolidationError, "EMBEDDING_DIMENSION_MISMATCH"):
            find_semantic_consolidation_candidates(entries, lambda texts: [[1.0, 0.0], [1.0]])
        with self.assertRaisesRegex(SemanticConsolidationError, "NON_FINITE_EMBEDDING_VALUE"):
            find_semantic_consolidation_candidates(entries, lambda texts: [[1.0, 0.0], [float("nan"), 1.0]])

    def test_provider_failure_is_not_silently_converted_to_no_candidates(self):
        entries = [entry("a", "первый факт"), entry("b", "второй факт")]
        def broken_provider(texts):
            raise RuntimeError("offline")
        with self.assertRaisesRegex(SemanticConsolidationError, "EMBEDDING_PROVIDER_FAILED"):
            find_semantic_consolidation_candidates(entries, broken_provider)

    def test_duplicate_ids_are_rejected(self):
        entries = [entry("same", "первый факт"), entry("same", "второй факт")]
        with self.assertRaisesRegex(SemanticConsolidationError, "DUPLICATE_ENTRY_ID"):
            find_semantic_consolidation_candidates(entries, lambda texts: [[1.0], [1.0]])


class SemanticMemoryCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="semantic_memory_")
        self.path_patch = mock.patch.object(
            memory_core, "MEMORY_FILE", os.path.join(self.tmp, "memory.json")
        )
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def test_memory_core_preview_is_read_only(self):
        import json
        entries = [
            entry("a", "Роман живёт в Германии"),
            entry("b", "Roman resides in Deutschland"),
        ]
        with open(memory_core.MEMORY_FILE, "w", encoding="utf-8") as handle:
            json.dump({"version": 2, "entries": entries}, handle, ensure_ascii=False)
        with open(memory_core.MEMORY_FILE, "rb") as handle:
            before = handle.read()
        vectors = [[1.0, 0.0], [0.99, 0.01]]
        groups = memory_core.preview_semantic_memory_consolidation(
            lambda texts: vectors
        )
        with open(memory_core.MEMORY_FILE, "rb") as handle:
            after = handle.read()
        self.assertEqual(len(groups), 1)
        self.assertEqual(before, after)

    def test_missing_embedding_provider_does_not_fall_back_to_lexical_guess(self):
        with self.assertRaisesRegex(SemanticConsolidationError, "EMBEDDING_PROVIDER_REQUIRED"):
            find_semantic_consolidation_candidates(
                [entry("a", "первый факт"), entry("b", "первый факт")], None
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
