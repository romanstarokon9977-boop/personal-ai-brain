"""Tests for the actual Tool Bridge result contract."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENROUTER_API_KEY", "ci-dummy-key-not-a-secret")

import verifier
import brain


class VerifyToolResultTests(unittest.TestCase):
    def test_valid_success(self):
        result = verifier.verify_tool_result(
            "read_file",
            {"ok": True, "result": "", "error": None, "tool": "read_file", "elapsed": 0.0},
        )
        self.assertTrue(result["valid"])
        self.assertEqual(result["status"], "PASS")

    def test_valid_failure(self):
        result = verifier.verify_tool_result(
            "shell",
            {"ok": False, "result": None, "error": "COMMAND_NOT_ALLOWED"},
        )
        self.assertTrue(result["valid"])

    def test_rejects_non_object(self):
        result = verifier.verify_tool_result("shell", "success")
        self.assertFalse(result["valid"])
        self.assertIn("RESULT_NOT_OBJECT", result["errors"])

    def test_rejects_non_boolean_ok(self):
        result = verifier.verify_tool_result(
            "shell", {"ok": "true", "result": "done", "error": None}
        )
        self.assertIn("OK_FLAG_NOT_BOOLEAN", result["errors"])

    def test_rejects_success_without_payload_key(self):
        result = verifier.verify_tool_result(
            "shell", {"ok": True, "error": None}
        )
        self.assertIn("SUCCESS_RESULT_MISSING", result["errors"])

    def test_rejects_failure_without_error(self):
        result = verifier.verify_tool_result(
            "shell", {"ok": False, "result": None, "error": " "}
        )
        self.assertIn("FAILURE_ERROR_MISSING", result["errors"])

    def test_rejects_contradictory_success(self):
        result = verifier.verify_tool_result(
            "shell", {"ok": True, "result": "done", "error": "FAILED"}
        )
        self.assertIn("SUCCESS_HAS_ERROR", result["errors"])

    def test_rejects_wrong_tool_metadata(self):
        result = verifier.verify_tool_result(
            "shell", {"ok": True, "result": "done", "error": None, "tool": "read_file"}
        )
        self.assertIn("TOOL_NAME_MISMATCH", result["errors"])

    def test_rejects_invalid_elapsed(self):
        result = verifier.verify_tool_result(
            "shell", {"ok": True, "result": "done", "error": None, "elapsed": float("nan")}
        )
        self.assertIn("INVALID_ELAPSED", result["errors"])

    def test_rejects_invalid_error_type(self):
        result = verifier.verify_tool_result(
            "shell", {"ok": False, "result": None, "error": "FAILED", "error_type": 7}
        )
        self.assertIn("INVALID_ERROR_TYPE", result["errors"])

    def test_tool_bridge_fails_closed_on_malformed_result(self):
        call = {
            "id": "call_test",
            "function": {"name": "test_tool", "arguments": "{}"},
        }
        with patch.object(brain, "tool_execute", return_value={"ok": True}):
            result = brain.tool_bridge_execute_call(call)
        self.assertIs(result["ok"], False)
        self.assertIn("TOOL_RESULT_CONTRACT_INVALID", result["error"])
        self.assertFalse(result["verification"]["valid"])

    def test_tool_bridge_marks_valid_result(self):
        call = {
            "id": "call_test",
            "function": {"name": "test_tool", "arguments": "{}"},
        }
        raw = {"ok": True, "result": "completed", "error": None}
        with patch.object(brain, "tool_execute", return_value=raw):
            result = brain.tool_bridge_execute_call(call)
        self.assertIs(result["ok"], True)
        self.assertEqual(result["result"], "completed")
        self.assertTrue(result["verification"]["valid"])


if __name__ == "__main__":
    unittest.main()
