#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for paused model self-modification and full-suite approval."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import brain


class ToolBridgeSelfModificationGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.temp.name)
        self.allowed_patch = patch.object(brain, "FILES_ALLOWED_DIRS", (self.root,))
        self.allowed_patch.start()
        self.execute_patch = patch.object(
            brain, "tool_execute",
            return_value={"ok": True, "result": "executed", "error": None},
        )
        self.mock_execute = self.execute_patch.start()

    def tearDown(self):
        self.execute_patch.stop()
        self.allowed_patch.stop()
        self.temp.cleanup()

    def call_tool(self, name, params):
        return brain.tool_bridge_execute_call({
            "id": "test-call",
            "function": {
                "name": name,
                "arguments": json.dumps(params),
            },
        })

    def test_model_write_file_cannot_create_python_source(self):
        target = os.path.join(self.root, "new_module.py")
        result = self.call_tool("write_file", {"path": target, "content": "x = 1\n"})
        self.assertFalse(result["ok"])
        self.assertIn("SELF_MODIFICATION_PAUSED", result["error"])
        self.mock_execute.assert_not_called()
        self.assertFalse(os.path.exists(target))

    def test_model_file_edit_cannot_change_python_source(self):
        target = os.path.join(self.root, "brain.py")
        with open(target, "w", encoding="utf-8") as stream:
            stream.write("SAFE = True\n")
        result = self.call_tool(
            "file_edit",
            {"path": target, "old_text": "True", "new_text": "False"},
        )
        self.assertFalse(result["ok"])
        self.assertIn("SELF_MODIFICATION_PAUSED", result["error"])
        self.mock_execute.assert_not_called()
        with open(target, "r", encoding="utf-8") as stream:
            self.assertEqual(stream.read(), "SAFE = True\n")

    def test_dynamic_file_writer_cannot_create_python_source(self):
        target = os.path.join(self.root, "module.pyi")
        result = self.call_tool(
            "mcp__filesystem__write_file",
            {"path": target, "content": "def run() -> None: ...\n"},
        )
        self.assertFalse(result["ok"])
        self.assertIn("SELF_MODIFICATION_PAUSED", result["error"])
        self.mock_execute.assert_not_called()

    def test_model_can_still_write_ordinary_text_file(self):
        target = os.path.join(self.root, "notes.txt")
        result = self.call_tool("write_file", {"path": target, "content": "note"})
        self.assertTrue(result["ok"], result)
        self.mock_execute.assert_called_once_with(
            "write_file", {"path": target, "content": "note"}
        )

    def test_full_test_run_denied_without_explicit_approval(self):
        with patch("builtins.input", return_value="n"):
            result = self.call_tool("run_tests", {"scope": "full"})
        self.assertFalse(result["ok"])
        self.assertIn("USER_DENIED", result["error"])
        self.mock_execute.assert_not_called()

    def test_full_test_run_passes_internal_approval_only_after_yes(self):
        with patch("builtins.input", return_value="y"):
            result = self.call_tool(
                "run_tests",
                {"scope": "full", "_user_confirmed_full": True},
            )
        self.assertTrue(result["ok"], result)
        self.mock_execute.assert_called_once()
        called_name, called_params = self.mock_execute.call_args.args
        self.assertEqual(called_name, "run_tests")
        self.assertIs(called_params["_user_confirmed_full"], True)

    def test_full_test_runner_rejects_direct_unconfirmed_call(self):
        with patch.object(brain.subprocess, "run") as run_mock:
            result = brain.tool_run_tests({"scope": "full"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "FULL_TESTS_REQUIRE_USER_CONFIRMATION")
        run_mock.assert_not_called()

    def test_missing_scope_does_not_default_to_full_suite(self):
        with patch.object(brain.subprocess, "run") as run_mock:
            result = brain.tool_run_tests({})
        self.assertFalse(result["ok"])
        self.assertTrue(result["error"].startswith("UNKNOWN_TEST:"))
        run_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
