import unittest
from unittest.mock import patch

import brain


class ToolBridgeFailureGuardTests(unittest.TestCase):
    def _run(self, tool_calls, tool_results, final_answer):
        model_call = {"count": 0}

        def fake_controller_execute(route, messages, tools=None):
            model_call["count"] += 1
            index = model_call["count"] - 1
            if index < len(tool_calls):
                return True, {
                    "answer": "",
                    "tool_calls": [tool_calls[index]],
                    "model": "test-model",
                    "provider": "test",
                    "time": 0.1,
                }
            return True, {
                "answer": final_answer,
                "model": "test-model",
                "provider": "test",
                "time": 0.1,
            }

        auto = brain.autonomy_controller.AutonomyResult(
            brain.autonomy_controller.AutonomyDecision.AUTO,
            "TEST_ALLOW",
            "git_inspect",
        )
        with (
            patch.object(brain, "controller_execute", side_effect=fake_controller_execute),
            patch.object(brain, "tool_bridge_execute_call", side_effect=tool_results),
            patch.object(brain, "get_tool_definitions", return_value=[]),
            patch.object(brain.autonomy_controller, "decide", return_value=auto),
        ):
            return brain.run_with_tools(
                {"model": "test-model", "layer": "API"},
                [{"role": "user", "content": "Проверь состояние репозитория"}],
            )

    @staticmethod
    def _call(operation, call_id):
        import json
        return {
            "id": call_id,
            "function": {
                "name": "git_inspect",
                "arguments": json.dumps({"operation": operation}),
            },
        }

    def test_failed_tool_cannot_be_overridden_by_success_claim(self):
        ok, result = self._run(
            [self._call("invalid", "call-fail")],
            [{
                "ok": False,
                "result": None,
                "error": "GIT_INSPECT_OPERATION_FAILED: INVALID_OPERATION",
                "error_code": "INVALID_OPERATION",
                "goal_verification": {
                    "status": "FAIL",
                    "reasons": [
                        "TOOL_EXECUTION_NOT_SUCCESSFUL",
                        "TOOL_ERROR_CODE:INVALID_OPERATION",
                    ],
                },
            }],
            "Операция успешно выполнена. Всё готово.",
        )

        self.assertTrue(ok)
        self.assertEqual(result["tool_execution_status"], "failed_or_unverified")
        self.assertTrue(result["model_answer_suppressed"])
        self.assertIn("не подтверждена", result["answer"])
        self.assertNotIn("успешно выполнена", result["answer"].lower())
        self.assertEqual(result["tool_failure"]["error_code"], "INVALID_OPERATION")

    def test_uncertain_goal_verification_is_not_reported_as_success(self):
        ok, result = self._run(
            [self._call("status", "call-uncertain")],
            [{
                "ok": True,
                "result": "## main",
                "error": None,
                "goal_verification": {
                    "status": "UNCERTAIN",
                    "reasons": ["INSUFFICIENT_EVIDENCE"],
                },
            }],
            "Все необходимые действия выполнены.",
        )

        self.assertTrue(ok)
        self.assertEqual(result["tool_execution_status"], "failed_or_unverified")
        self.assertTrue(result["model_answer_suppressed"])
        self.assertIn("UNCERTAIN", result["answer"])
        self.assertNotIn("Все необходимые действия выполнены", result["answer"])

    def test_later_verified_tool_success_allows_final_answer(self):
        ok, result = self._run(
            [
                self._call("invalid", "call-first"),
                self._call("status", "call-second"),
            ],
            [
                {
                    "ok": False,
                    "result": None,
                    "error": "INVALID_OPERATION",
                    "error_code": "INVALID_OPERATION",
                    "goal_verification": {
                        "status": "FAIL",
                        "reasons": ["TOOL_EXECUTION_NOT_SUCCESSFUL"],
                    },
                },
                {
                    "ok": True,
                    "result": "## main",
                    "error": None,
                    "goal_verification": {
                        "status": "PASS",
                        "reasons": ["READ_ONLY_STATE_CONFIRMED"],
                    },
                },
            ],
            "Состояние репозитория успешно проверено.",
        )

        self.assertTrue(ok)
        self.assertEqual(result["answer"], "Состояние репозитория успешно проверено.")
        self.assertNotIn("model_answer_suppressed", result)


if __name__ == "__main__":
    unittest.main()
