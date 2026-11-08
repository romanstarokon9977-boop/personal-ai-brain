import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENROUTER_API_KEY", "ci-dummy-key-not-a-secret")

import brain
import autonomy_controller


class ToolBridgeAutonomyIntegrationTests(unittest.TestCase):
    def _run_tool_request(self, name, arguments, answer="да"):
        calls = {"model": 0}
        model_inputs = []
        autonomy_decisions = []
        real_decide = autonomy_controller.decide

        def recording_decide(tool_name, params, registry):
            decision = real_decide(tool_name, params, registry)
            autonomy_decisions.append((tool_name, params, decision))
            return decision

        def fake_model(route, messages, tools=None):
            calls["model"] += 1
            model_inputs.append([dict(message) for message in messages])
            if calls["model"] == 1:
                return True, {
                    "answer": "",
                    "tool_calls": [{
                        "id": "autonomy-test-call",
                        "function": {
                            "name": name,
                            "arguments": __import__("json").dumps(arguments),
                        },
                    }],
                    "model": "test-model",
                    "provider": "test",
                    "time": 0.01,
                }
            return True, {
                "answer": "Тестовый финальный ответ.",
                "model": "test-model",
                "provider": "test",
                "time": 0.01,
            }

        with (
            patch.object(brain, "controller_execute", side_effect=fake_model),
            patch.object(brain, "get_tool_definitions", return_value=[]),
            patch.object(brain, "tool_bridge_log", return_value=None),
            patch.object(
                brain,
                "tool_bridge_execute_call",
                return_value={"ok": True, "result": "mock-result", "error": None},
            ) as execute,
            patch.object(
                autonomy_controller, "decide", side_effect=recording_decide
            ) as decide,
            patch("builtins.input", return_value=answer) as prompt,
        ):
            result = brain.run_with_tools(
                {"model": "test-model", "layer": "API"},
                [{"role": "user", "content": "Проверь действие"}],
            )
        return result, execute, prompt, decide, model_inputs, autonomy_decisions

    def test_read_only_allowlisted_tool_runs_without_prompt(self):
        result, execute, prompt, decide, model_inputs, decisions = self._run_tool_request(
            "read_file", {"path": "~/personal_ai_brain/README.md"}
        )
        self.assertTrue(result[0])
        execute.assert_called_once()
        prompt.assert_not_called()

    def test_fixed_path_memory_audit_runs_without_prompt(self):
        result, execute, prompt, decide, model_inputs, decisions = self._run_tool_request(
            "memory_audit", {}
        )
        self.assertTrue(result[0])
        execute.assert_called_once()
        prompt.assert_not_called()
        self.assertEqual(
            decisions[0][2].decision, autonomy_controller.AutonomyDecision.AUTO
        )

    def test_run_tests_executes_without_confirmation_prompt(self):
        result, execute, prompt, decide, model_inputs, decisions = self._run_tool_request(
            "run_tests", {"scope": "targeted", "test": "test_brain.py"}
        )
        self.assertTrue(result[0])
        execute.assert_called_once()
        prompt.assert_not_called()
        self.assertEqual(len(decisions), 1)
        self.assertEqual(
            decisions[0][2].decision, autonomy_controller.AutonomyDecision.AUTO
        )
        self.assertEqual(decisions[0][2].reason, "LOW_RISK_BOUNDED_TEST_RUN")

    def test_memory_audit_uses_native_dispatch_not_mcp(self):
        expected = {"ok": True, "result": {"total_entries": 38}, "error": None}
        with (
            patch.object(brain, "audit_memory", return_value=expected) as audit,
            patch.object(brain.mcp_bridge, "mcp_is_alive") as mcp_alive,
            patch.object(brain.mcp_bridge, "mcp_call") as mcp_call,
        ):
            result = brain._tool_execute_impl("memory_audit", {})

        self.assertEqual(result, expected)
        audit.assert_called_once_with()
        mcp_alive.assert_not_called()
        mcp_call.assert_not_called()

    def test_mutating_tool_requires_confirmation_and_denial_prevents_execution(self):
        result, execute, prompt, decide, model_inputs, decisions = self._run_tool_request(
            "write_file",
            {"path": "~/personal_ai_brain/new.txt", "content": "data"},
            answer="нет",
        )
        self.assertTrue(result[0])
        execute.assert_not_called()
        prompt.assert_called_once()

    def test_mutating_tool_executes_only_after_affirmative_confirmation(self):
        result, execute, prompt, decide, model_inputs, decisions = self._run_tool_request(
            "write_file",
            {"path": "~/personal_ai_brain/new.txt", "content": "data"},
            answer="да",
        )
        self.assertTrue(result[0])
        execute.assert_called_once()
        prompt.assert_called_once()

    def test_unknown_tool_is_blocked_without_prompt_or_execution(self):
        result, execute, prompt, decide, model_inputs, decisions = self._run_tool_request(
            "unregistered_tool", {"payload": "x"}
        )
        self.assertTrue(result[0])
        execute.assert_not_called()
        prompt.assert_not_called()

        # Simulate a model returning a tool call that was not advertised in
        # the API schema. The real autonomy gate must reject it explicitly.
        self.assertEqual(len(decisions), 1)
        tool_name, params, decision = decisions[0]
        self.assertEqual(tool_name, "unregistered_tool")
        self.assertEqual(params, {"payload": "x"})
        self.assertEqual(decision.decision, autonomy_controller.AutonomyDecision.BLOCK)
        self.assertEqual(decision.reason, "UNKNOWN_TOOL")

        returned_tool_messages = [
            message for message in model_inputs[1]
            if message.get("role") == "tool"
        ]
        self.assertTrue(
            any("AUTONOMY_BLOCKED: UNKNOWN_TOOL" in message.get("content", "")
                for message in returned_tool_messages),
            "Tool Bridge must return the controller's explicit BLOCK reason",
        )


if __name__ == "__main__":
    unittest.main()
