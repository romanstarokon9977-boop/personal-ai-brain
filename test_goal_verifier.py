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

    def test_file_edit_missing_readback_fails(self):
        result = goal_verifier.verify_goal_result(
            "Edit file", "file_edit",
            {"path": self.path, "new_text": "expected"},
            {"ok": True, "verifier": {"postcondition": "PASS"}},
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["reasons"][0].startswith("EDIT_READBACK_FAILED:"))

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

    def test_git_status_with_matching_operation_and_branch_header_passes(self):
        result = goal_verifier.verify_goal_result(
            "Check repository status", "git_inspect", {"operation": "status"},
            {"ok": True, "result": "## main...origin/main", "error": None, "operation": "status"},
        )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["verified"])
        self.assertIn("GIT_STATUS_OPERATION_AND_OUTPUT_CONFIRMED", result["reasons"])

    def test_git_status_without_branch_header_fails_closed(self):
        result = goal_verifier.verify_goal_result(
            "Check repository status", "git_inspect", {"operation": "status"},
            {"ok": True, "result": "safe output", "error": None, "operation": "status"},
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("GIT_STATUS_OUTPUT_NOT_CONFIRMED", result["reasons"])

    def test_git_status_operation_mismatch_fails(self):
        result = goal_verifier.verify_goal_result(
            "Check repository status", "git_inspect", {"operation": "status"},
            {"ok": True, "result": "## main", "error": None, "operation": "diff"},
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("GIT_OPERATION_MISMATCH", result["reasons"])

    def test_git_status_missing_operation_metadata_is_uncertain(self):
        result = goal_verifier.verify_goal_result(
            "Check repository status", "git_inspect", {"operation": "status"},
            {"ok": True, "result": "## main", "error": None},
        )
        self.assertEqual(result["status"], "UNCERTAIN")
        self.assertIn("GIT_STATUS_OPERATION_UNCONFIRMED", result["reasons"])

    def test_git_status_truncated_output_fails_closed(self):
        result = goal_verifier.verify_goal_result(
            "Check repository status", "git_inspect", {"operation": "status"},
            {"ok": True, "result": "## main\\n... [OUTPUT_TRUNCATED]", "error": None, "operation": "status"},
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("GIT_STATUS_OUTPUT_TRUNCATED", result["reasons"])

    def test_other_git_inspection_operations_remain_uncertain(self):
        result = goal_verifier.verify_goal_result(
            "Inspect diff", "git_inspect", {"operation": "diff"},
            {"ok": True, "result": "diff --stat", "error": None, "operation": "diff"},
        )
        self.assertEqual(result["status"], "UNCERTAIN")
        self.assertIn("GIT_OPERATION_POSTCONDITION_UNSUPPORTED", result["reasons"])

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

    def test_extract_error_code_from_wrapped_tool_error(self):
        self.assertEqual(
            goal_verifier.extract_error_code(
                "SOLUTION_LIBRARY_OPERATION_FAILED: VERIFICATION_REFERENCE_NOT_DECLARED"
            ),
            "VERIFICATION_REFERENCE_NOT_DECLARED",
        )
        self.assertEqual(goal_verifier.extract_error_code("TIMEOUT"), "TIMEOUT")
        self.assertIsNone(goal_verifier.extract_error_code("operation failed"))
        self.assertIsNone(goal_verifier.extract_error_code(None))

    def test_failed_tool_extracts_root_code_when_metadata_field_is_missing(self):
        result = goal_verifier.verify_goal_result(
            "Verify solution candidate", "solution_library", {},
            {
                "ok": False,
                "error": "SOLUTION_LIBRARY_OPERATION_FAILED: VERIFICATION_REFERENCE_NOT_DECLARED",
            },
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("TOOL_EXECUTION_NOT_SUCCESSFUL", result["reasons"])
        self.assertIn(
            "TOOL_ERROR_CODE:VERIFICATION_REFERENCE_NOT_DECLARED",
            result["reasons"],
        )

    def test_failed_tool_preserves_machine_readable_root_error_code(self):
        result = goal_verifier.verify_goal_result(
            "Verify solution candidate", "solution_library", {},
            {
                "ok": False,
                "error": "SOLUTION_LIBRARY_OPERATION_FAILED: VERIFICATION_REFERENCE_NOT_DECLARED",
                "error_code": "VERIFICATION_REFERENCE_NOT_DECLARED",
            },
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("TOOL_EXECUTION_NOT_SUCCESSFUL", result["reasons"])
        self.assertIn(
            "TOOL_ERROR_CODE:VERIFICATION_REFERENCE_NOT_DECLARED",
            result["reasons"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
