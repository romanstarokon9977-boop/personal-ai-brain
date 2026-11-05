"""Regression tests for the default ToolRegistry model contract.

These tests are read-only: they construct an in-memory registry and do not
import brain.py, start MCP, access the network, or touch user data.
"""
import unittest

from tool_registry import ToolSource, create_default_registry


EXPECTED_REGISTRY_NAMES = {
    "publish_cpa_gadget",
    "shell",
    "read_file",
    "write_file",
    "file_edit",
    "directory_list",
    "file_search",
    "web_fetch",
    "read_pdf",
    "read_docx",
    "directory_tree",
    "move_file",
    "create_directory",
    "get_file_info",
    "read_multiple_files",
    "list_allowed_directories",
    "read_text_file",
    "edit_file",
    "list_directory",
    "search_files",
    "notify_user",
    "briefing_set",
    "run_tests",
    "tts_speak",
    "self_inspection",
}

EXPECTED_MODEL_NAMES = EXPECTED_REGISTRY_NAMES - {
    "read_text_file",
    "edit_file",
    "list_directory",
    "search_files",
}


class ToolRegistryContractTests(unittest.TestCase):
    def setUp(self):
        self.registry = create_default_registry()
        self.registered = self.registry.all_tools()
        self.model_tools = self.registry.get_tools_for_model()
        self.model_names = {
            item["function"]["name"] for item in self.model_tools
        }

    def test_default_registry_contains_expected_tools(self):
        names = {tool.name for tool in self.registered}
        self.assertEqual(names, EXPECTED_REGISTRY_NAMES)
        self.assertEqual(len(self.registered), 25)

    def test_model_receives_expected_deduplicated_tool_set(self):
        self.assertEqual(self.model_names, EXPECTED_MODEL_NAMES)
        self.assertEqual(len(self.model_tools), 21)
        self.assertEqual(len(self.model_names), len(self.model_tools))

    def test_four_mcp_duplicates_remain_registered_for_fallback(self):
        hidden_names = {
            "read_text_file",
            "edit_file",
            "list_directory",
            "search_files",
        }
        registered = {tool.name: tool for tool in self.registered}
        self.assertTrue(hidden_names.isdisjoint(self.model_names))
        for name in hidden_names:
            with self.subTest(tool=name):
                tool = registered[name]
                self.assertEqual(tool.source, ToolSource.MCP)
                self.assertIsNotNone(tool.duplicate_group)
                self.assertIsNotNone(self.registry.get(name))

    def test_model_tool_definitions_follow_openai_function_schema(self):
        for item in self.model_tools:
            with self.subTest(tool=item):
                self.assertEqual(item.get("type"), "function")
                function = item.get("function")
                self.assertIsInstance(function, dict)
                self.assertTrue(function.get("name"))
                self.assertIsInstance(function.get("description"), str)
                self.assertIsInstance(function.get("parameters"), dict)
                self.assertEqual(
                    function["parameters"].get("type"),
                    "object",
                )

    def test_native_tools_win_duplicate_groups_by_priority(self):
        for group in ("fs_read", "fs_edit", "fs_list", "fs_search"):
            with self.subTest(group=group):
                members = [
                    tool for tool in self.registered
                    if tool.duplicate_group == group
                ]
                self.assertEqual(len(members), 2)
                winner = max(members, key=lambda tool: tool.priority)
                self.assertEqual(winner.source, ToolSource.NATIVE)
                self.assertIn(winner.name, self.model_names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
