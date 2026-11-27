import unittest
from mode_manager import filter_tool_definitions, mode_instruction, mode_label, normalize_mode


def tool(name):
    return {"type": "function", "function": {"name": name, "parameters": {}}}


class OperatingModeTests(unittest.TestCase):
    def test_russian_and_english_aliases(self):
        self.assertEqual(normalize_mode("общение"), "conversation")
        self.assertEqual(normalize_mode("research"), "research")
        self.assertEqual(normalize_mode("программирование"), "programming")
        self.assertEqual(normalize_mode("обучение"), "learning")
        self.assertEqual(normalize_mode("автономное исполнение"), "autonomous")
        self.assertIsNone(normalize_mode("unknown"))

    def test_conversation_preserves_current_tool_surface(self):
        tools = [tool("shell"), tool("write_file"), tool("read_file")]
        self.assertEqual(filter_tool_definitions(tools, "conversation"), tools)

    def test_research_and_learning_are_read_only(self):
        tools = [tool("read_file"), tool("web_fetch"), tool("write_file"), tool("shell")]
        self.assertEqual([x["function"]["name"] for x in filter_tool_definitions(tools, "research")], ["read_file", "web_fetch"])
        self.assertEqual([x["function"]["name"] for x in filter_tool_definitions(tools, "learning")], ["read_file"])

    def test_programming_and_autonomous_allow_confirmed_writes_but_not_shell(self):
        tools = [tool("read_file"), tool("write_file"), tool("file_edit"), tool("run_tests"), tool("shell"), tool("publish_cpa_gadget")]
        for mode in ("programming", "autonomous"):
            names = {x["function"]["name"] for x in filter_tool_definitions(tools, mode)}
            self.assertTrue({"write_file", "file_edit", "run_tests"}.issubset(names))
            self.assertNotIn("shell", names)
            self.assertNotIn("publish_cpa_gadget", names)

    def test_instructions_are_distinct(self):
        self.assertEqual(len({mode_instruction(m) for m in ("conversation", "research", "programming", "learning", "autonomous")}), 5)
        self.assertEqual(mode_label("autonomous"), "автономное исполнение")


if __name__ == "__main__":
    unittest.main(verbosity=2)
