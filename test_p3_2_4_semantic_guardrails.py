"""Adversarial regression fixtures for guarded P3.2 semantic consolidation."""
import json
import os
import tempfile
import unittest
from unittest import mock

from memory import memory_core
from memory.guarded_semantic_consolidation import find_guarded_semantic_consolidation_candidates
from memory.fact_frame_extractor import extract_fact_frames


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


def semantic_groups(left, right):
    entries = [entry("left", left), entry("right", right)]
    # Maximally similar vectors cannot bypass the independent FactFrame guard.
    return find_guarded_semantic_consolidation_candidates(
        entries,
        lambda texts: [[1.0, 0.0] for _ in texts],
        extract_fact_frames,
        min_similarity=0.99,
    )


class SemanticGuardrailRegressionTests(unittest.TestCase):
    def test_true_paraphrase_remains_a_candidate(self):
        groups = semantic_groups(
            "Роман проживает в Германии",
            "Роман живёт в Германии",
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["entry_ids"], ["left", "right"])

    def test_explicit_number_conflict_is_excluded(self):
        self.assertEqual(
            semantic_groups(
                "Роман использует 8 GB оперативной памяти",
                "Роман использует 12 GB оперативной памяти",
            ),
            [],
        )

    def test_explicit_negation_conflict_is_excluded(self):
        self.assertEqual(
            semantic_groups(
                "Роман использует облачное хранилище",
                "Роман не использует облачное хранилище",
            ),
            [],
        )

    def test_implicit_opposite_values_must_not_be_grouped(self):
        self.assertEqual(
            semantic_groups(
                "Сервер доступен для подключения",
                "Сервер недоступен для подключения",
            ),
            [],
        )

    def test_different_entities_must_not_be_grouped(self):
        self.assertEqual(
            semantic_groups(
                "Роман использует Termux для разработки",
                "Мария использует Termux для разработки",
            ),
            [],
        )

    def test_numeric_values_with_swapped_roles_must_not_be_grouped(self):
        self.assertEqual(
            semantic_groups(
                "Устройство имеет 8 GB RAM и 256 GB storage",
                "Устройство имеет 256 GB RAM и 8 GB storage",
            ),
            [],
        )

    def test_same_number_with_different_units_must_not_be_grouped(self):
        self.assertEqual(
            semantic_groups(
                "Объём хранилища составляет 8 GB",
                "Объём хранилища составляет 8 TB",
            ),
            [],
        )

    def test_presence_and_absence_without_negation_token_must_not_be_grouped(self):
        self.assertEqual(
            semantic_groups(
                "Резервное копирование активно",
                "Резервное копирование отключено",
            ),
            [],
        )

    def test_causally_related_independent_facts_must_not_be_grouped(self):
        self.assertEqual(
            semantic_groups(
                "Перегрев смартфона увеличивает скорость разряда батареи",
                "Повышенная температура ускоряет износ аккумулятора",
            ),
            [],
        )

    def test_topically_related_distinct_facts_must_not_be_grouped(self):
        self.assertEqual(
            semantic_groups(
                "Роман изучает Python для анализа данных",
                "Роман изучает английский язык для общения",
            ),
            [],
        )


class IngestionGuardrailRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p3_2_4_guardrails_")
        self.memory_path = os.path.join(self.tmp, "memory.json")
        self.path_patch = mock.patch.object(
            memory_core, "MEMORY_FILE", self.memory_path
        )
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def _write_memory(self, entries):
        with open(self.memory_path, "w", encoding="utf-8") as handle:
            json.dump({"version": 2, "entries": entries}, handle, ensure_ascii=False)

    def test_lexical_overlap_must_not_rewrite_distinct_numeric_fact(self):
        original = entry(
            "existing",
            "Роман использует 8 GB памяти на Poco F6",
        )
        self._write_memory([original])
        captured = {}

        def capture_save(data):
            captured["data"] = data

        with mock.patch.object(memory_core, "_save_raw", side_effect=capture_save):
            result = memory_core.add_memory(
                "Роман использует 12 GB памяти на Poco F6 во время поездок",
                category="facts",
                source="user",
            )

        self.assertTrue(result.startswith("Сохранено"), result)
        self.assertEqual(len(captured["data"]["entries"]), 2)
        self.assertEqual(captured["data"]["entries"][0]["text"], original["text"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
