import os
import tempfile
import unittest

import goal_verifier


class GoalVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="goal_verifier_")
        self.addCleanup(self.temp_dir.cleanup)
        self.path = os.path.join(self.temp_dir.name, "result.txt")

    def test_write_file_exact_persisted_content_passes(self):
        expected = "requested content\n"
        with open(self.path, "w", encoding="utf-8") as stream:
            stream.write(expected)
        result = goal_verifier.verify_goal_result(
            "Create the requested file", "write_file",
            {"path": self.path, "content": expected},
            {"ok": True, "result": "created"},
        )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["verified"])

    def test_write_file_content_mismatch_fails(self):
        with open(self.path, "w", encoding="utf-8") as stream:
            stream.write("different")
        result = goal_verifier.verify_goal_result(
            "Create the requested file", "write_file",
            {"path": self.path, "content": "expected"},
            {"ok": True, "result": "created"},
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("WRITE_CONTENT_MISMATCH", result["reasons"])

    def test_write_file_missing_file_fails(self):
        result = goal_verifier.verify_goal_result(
            "Create the requested file", "write_file",
            {"path": self.path, "content": "expected"},
            {"ok": True, "result": "created"},
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["reasons"][0].startswith("WRITE_READBACK_FAILED:"))

    def test_file_edit_requires_existing_postcondition_and_replacement(self):
        with open(self.path, "w", encoding="utf-8") as stream:
            stream.write("before after")
        result = goal_verifier.verify_goal_result(
            "Replace before with after", "file_edit",
            {"path": self.path, "old_text": "before", "new_text": "after"},
            {"ok": True, "verifier": {"postcondition": "PASS"}},
        )
        self.assertEqual(result["status"], "PASS")

    def test_file_edit_replacement_mismatch_fails(self):
        with open(self.path, "w", encoding="utf-8") as stream:
            stream.write("unexpected")
        result = goal_verifier.verify_goal_result(
            "Edit file", "file_edit",
            {"path": self.path, "new_text": "expected"},
            {"ok": True, "verifier": {"postcondition": "PASS"}},
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("EDIT_REPLACEMENT_NOT_FOUND", result["reasons"])

    def test_file_edit_missing_postcondition_fails(self):
        with open(self.path, "w", encoding="utf-8") as stream:
            stream.write("after")
        result = goal_verifier.verify_goal_result(
            "Edit file", "file_edit",
            {"path": self.path, "new_text": "after"},
            {"ok": True, "verifier": {"postcondition": "SKIP"}},
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("FILE_EDIT_POSTCONDITION_NOT_CONFIRMED", result["reasons"])

    def test_unsupported_tool_is_uncertain_not_false_pass(self):
        result = goal_verifier.verify_goal_result(
            "Search for a value", "file_search", {"query": "value"},
            {"ok": True, "result": "found"},
        )
        self.assertEqual(result["status"], "UNCERTAIN")
        self.assertFalse(result["verified"])

    def test_missing_goal_is_uncertain(self):
        result = goal_verifier.verify_goal_result(
            "", "write_file", {"path": self.path, "content": ""},
            {"ok": True, "result": "created"},
        )
        self.assertEqual(result["status"], "UNCERTAIN")
        self.assertIn("USER_GOAL_UNAVAILABLE", result["reasons"])

    def test_failed_tool_is_fail(self):
        result = goal_verifier.verify_goal_result(
            "Create file", "write_file", {},
            {"ok": False, "error": "WRITE_ERROR"},
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("TOOL_EXECUTION_NOT_SUCCESSFUL", result["reasons"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
