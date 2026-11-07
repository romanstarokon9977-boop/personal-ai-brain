import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENROUTER_API_KEY", "ci-dummy-key-not-a-secret")

import brain
import autonomy_controller


class ToolBridgeAutonomyIntegrationTests(unittest.TestCase):
    def _run_tool_request(self, name, arguments, answer="да"):
        calls = {"model": 0}

        def fake_model(route, messages, tools=None):
            calls["model"] += 1
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

        with patch.object(brain, "controller_execute", side_effect=fake_model), \
             patch.object(brain, "get_tool_definitions", return_value=[]), \
             patch.object(brain, "tool_bridge_log", return_value=None), \
             patch.object(brain, "tool_bridge_execute_call",
                          return_value={"ok": True, "result": "mock-result", "error": None}) as execute, \
             patch("builtins.input", return_value=answer) as prompt:
            result = brain.run_with_tools(
                {"model": "test-model", "layer": "API"},
                [{"role": "user", "content": "Проверь действие"}],
            )
        return result, execute, prompt

    def test_read_only_allowlisted_tool_runs_without_prompt(self):
        result, execute, prompt = self._run_tool_request(
            "read_file", {"path": "~/personal_ai_brain/README.md"}
        )
        self.assertTrue(result[0])
        execute.assert_called_once()
        prompt.assert_not_called()

    def test_mutating_tool_requires_confirmation_and_denial_prevents_execution(self):
        result, execute, prompt = self._run_tool_request(
            "write_file",
            {"path": "~/personal_ai_brain/new.txt", "content": "data"},
            answer="нет",
        )
        self.assertTrue(result[0])
        execute.assert_not_called()
        prompt.assert_called_once()

    def test_mutating_tool_executes_only_after_affirmative_confirmation(self):
        result, execute, prompt = self._run_tool_request(
            "write_file",
            {"path": "~/personal_ai_brain/new.txt", "content": "data"},
            answer="да",
        )
        self.assertTrue(result[0])
        execute.assert_called_once()
        prompt.assert_called_once()

    def test_unknown_tool_is_blocked_without_prompt_or_execution(self):
        result, execute, prompt = self._run_tool_request(
            "unregistered_tool", {"payload": "x"}
        )
        self.assertTrue(result[0])
        execute.assert_not_called()
        prompt.assert_not_called()


if __name__ == "__main__":
    unittest.main()
