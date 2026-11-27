import contextlib
import io
import unittest
from unittest import mock

import brain


def _tool(name):
    return {"type": "function", "function": {"name": name, "parameters": {}}}


class OperatingModeDispatchTests(unittest.TestCase):
    def test_mode_command_updates_session_policy_and_prompt(self):
        original = brain.ACTIVE_MODE
        messages = [{"role": "system", "content": "base"}]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                result = brain.handle_mode_command("режим исследование", messages)
            self.assertTrue(result["ok"])
            self.assertEqual(brain.ACTIVE_MODE, "research")
            mode_messages = [m for m in messages if m.get("name") == "operating_mode"]
            self.assertEqual(len(mode_messages), 1)
        finally:
            brain.ACTIVE_MODE = original

    def test_hallucinated_hidden_tool_is_blocked_at_execution(self):
        original = brain.ACTIVE_MODE
        brain.ACTIVE_MODE = "research"
        tool_call = {
            "id": "call-1",
            "function": {"name": "write_file", "arguments": '{"path":"x","content":"y"}'},
        }
        try:
            with mock.patch.object(brain, "get_tool_definitions", return_value=[_tool("read_file")]):
                with mock.patch.object(
                    brain, "controller_execute",
                    side_effect=[
                        (True, {"answer": "", "tool_calls": [tool_call]}),
                        (True, {"answer": "The write was blocked."}),
                    ],
                ):
                    with mock.patch.object(brain, "tool_bridge_has_calls", side_effect=[True, False]):
                        with mock.patch.object(brain, "tool_bridge_execute_call") as execute:
                            with mock.patch.object(brain, "tool_bridge_log"):
                                ok, result = brain.run_with_tools(
                                    {"model": "test-model", "layer": "API"},
                                    [{"role": "user", "content": "write something"}],
                                    _executed_calls=set(),
                                    _denied_tools=set(),
                                    _tool_results={},
                                    allowed_tool_names={"read_file", "write_file"},
                                )
            self.assertTrue(ok)
            self.assertEqual(result["answer"], "The write was blocked.")
            execute.assert_not_called()
        finally:
            brain.ACTIVE_MODE = original


if __name__ == "__main__":
    unittest.main(verbosity=2)
