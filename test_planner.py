import unittest
from unittest.mock import Mock

import planner


class PlannerValidationTests(unittest.TestCase):
    def setUp(self):
        self.raw_steps = [
            {
                "id": "step_build",
                "title": "Сборка",
                "description": "Собрать итоговый результат",
                "depends_on": ["step_prepare"],
                "acceptance_criteria": ["Артефакт создан", "Проверка пройдена"],
            },
            {
                "id": "step_prepare",
                "title": "Подготовка",
                "description": "Подготовить входные данные",
                "depends_on": [],
                "acceptance_criteria": ["Входные данные проверены"],
            },
        ]

    def test_topological_order_respects_dependencies(self):
        plan = planner.validate_plan("Создать результат", self.raw_steps)
        self.assertEqual(
            [step["id"] for step in plan["steps"]],
            ["step_prepare", "step_build"],
        )

    def test_missing_dependency_is_rejected(self):
        raw = [dict(self.raw_steps[0], depends_on=["unknown"])]
        with self.assertRaises(planner.PlanValidationError):
            planner.validate_plan("Цель", raw)

    def test_cycle_is_rejected(self):
        raw = [
            dict(self.raw_steps[0], depends_on=["step_prepare"]),
            dict(self.raw_steps[1], depends_on=["step_build"]),
        ]
        with self.assertRaises(planner.PlanValidationError):
            planner.validate_plan("Цель", raw)

    def test_duplicate_ids_are_rejected(self):
        raw = [self.raw_steps[0], dict(self.raw_steps[1], id="step_build")]
        with self.assertRaises(planner.PlanValidationError):
            planner.validate_plan("Цель", raw)

    def test_missing_acceptance_criteria_is_rejected(self):
        raw = [dict(self.raw_steps[0], acceptance_criteria=[])]
        with self.assertRaises(planner.PlanValidationError):
            planner.validate_plan("Цель", raw)

    def test_invalid_json_is_rejected(self):
        with self.assertRaises(planner.PlanValidationError):
            planner.parse_plan_response("not json", "Цель")

    def test_fenced_json_is_parsed(self):
        payload = {
            "steps": [{
                "id": "step_1",
                "title": "Анализ",
                "description": "Проверить исходные данные",
                "depends_on": [],
                "acceptance_criteria": ["Отчёт содержит вывод"],
            }]
        }
        plan = planner.parse_plan_response(
            "```json\n" + __import__("json").dumps(payload, ensure_ascii=False)
            + "\n```",
            "Проверить данные",
        )
        self.assertEqual(plan["steps"][0]["id"], "step_1")

    def test_generation_uses_callback_and_returns_validated_plan(self):
        response = {
            "answer": (
                '{"steps":[{"id":"step_1","title":"Анализ",'
                '"description":"Изучить входные данные","depends_on":[],'
                '"acceptance_criteria":["Составлен перечень требований"]}]}'
            )
        }
        callback = Mock(return_value=(True, response))
        result = planner.generate_plan("Изучить проект", callback, "test-model")
        self.assertTrue(result["ok"])
        self.assertEqual(result["plan"]["goal"], "Изучить проект")
        callback.assert_called_once()

    def test_generation_does_not_silently_create_fallback_plan(self):
        callback = Mock(return_value=(True, {"answer": "не JSON"}))
        result = planner.generate_plan(
            "Сложная задача", callback, "test-model", max_attempts=1
        )
        self.assertFalse(result["ok"])
        self.assertIsNone(result["plan"])
        self.assertIn("INVALID_PLAN", result["error"])

    def test_only_ready_steps_are_returned(self):
        plan = planner.validate_plan("Цель", self.raw_steps)
        self.assertEqual(
            [step["id"] for step in planner.get_ready_steps(plan)],
            ["step_prepare"],
        )

    def test_step_cannot_start_before_dependencies(self):
        plan = planner.validate_plan("Цель", self.raw_steps)
        with self.assertRaises(planner.PlanValidationError):
            planner.start_step(plan, "step_build")

    def test_step_completion_requires_all_criteria_and_evidence(self):
        plan = planner.validate_plan("Цель", self.raw_steps)
        planner.start_step(plan, "step_prepare")
        with self.assertRaises(planner.PlanValidationError):
            planner.complete_step(
                plan,
                "step_prepare",
                {"AC1": {"passed": True, "evidence": ""}},
            )
        planner.complete_step(
            plan,
            "step_prepare",
            {"AC1": {"passed": True, "evidence": "Проверка входных данных: PASS"}},
        )
        self.assertEqual(plan["steps"][0]["status"], "completed")
        self.assertEqual(
            [step["id"] for step in planner.get_ready_steps(plan)],
            ["step_build"],
        )

    def test_plan_becomes_completed_only_after_every_step(self):
        plan = planner.validate_plan("Цель", self.raw_steps)
        planner.start_step(plan, "step_prepare")
        planner.complete_step(
            plan, "step_prepare",
            {"AC1": {"passed": True, "evidence": "Подтверждение"}},
        )
        planner.start_step(plan, "step_build")
        planner.complete_step(
            plan, "step_build",
            {
                "AC1": {"passed": True, "evidence": "Артефакт существует"},
                "AC2": {"passed": True, "evidence": "Тесты: PASS"},
            },
        )
        self.assertEqual(plan["status"], "completed")

    def test_unknown_or_extra_criterion_result_is_rejected(self):
        plan = planner.validate_plan("Цель", self.raw_steps)
        planner.start_step(plan, "step_prepare")
        with self.assertRaises(planner.PlanValidationError):
            planner.complete_step(
                plan, "step_prepare",
                {
                    "AC1": {"passed": True, "evidence": "Есть"},
                    "AC2": {"passed": True, "evidence": "Лишнее"},
                },
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
