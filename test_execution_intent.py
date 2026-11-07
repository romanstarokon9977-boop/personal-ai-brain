import unittest

from execution_intent import is_plan_only_request


class PlanOnlyIntentTests(unittest.TestCase):
    def test_explicit_wait_instruction_blocks_execution(self):
        self.assertTrue(
            is_plan_only_request(
                "Сначала проанализируй цель, затем построй план. "
                "Пока не приступай к выполнению шагов."
            )
        )

    def test_plan_only_phrases_are_recognized(self):
        phrases = (
            "Только составь план безопасной диагностики.",
            "Сделай план без исполнения.",
            "Не выполняй действия и не запускай инструменты.",
            "Пока не начинай.",
            "Подготовь только план.",
        )
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertTrue(is_plan_only_request(phrase))

    def test_case_whitespace_and_yo_normalization(self):
        self.assertTrue(is_plan_only_request("  ПОКА   НЕ ПРИСТУПАЙ  "))
        self.assertTrue(is_plan_only_request("Только составь план; не выполняй."))

    def test_normal_execution_goal_is_not_plan_only(self):
        self.assertFalse(
            is_plan_only_request(
                "Исполни план: проверь доступность компонентов и количество записей."
            )
        )

    def test_empty_or_non_string_input_is_not_plan_only(self):
        self.assertFalse(is_plan_only_request(""))
        self.assertFalse(is_plan_only_request(None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
