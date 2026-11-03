"""Регрессионные тесты безопасности P1-A для Verifier."""

import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import verifier


class TestVerifierP1ASecurity(unittest.TestCase):
    def test_check_import_does_not_execute_module_code(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            marker = os.path.join(temp_dir, "executed.txt")
            code = (
                "from pathlib import Path\n"
                + "Path(" + repr(marker) + ").write_text('executed')\n"
            )

            result = verifier.check_import(code)

            self.assertTrue(result["ok"])
            self.assertIsNone(result["module"])
            self.assertFalse(os.path.exists(marker))
            self.assertTrue(result["warnings"])
            self.assertEqual(result["import_count"], 1)

    def test_check_import_rejects_invalid_syntax_without_execution(self):
        result = verifier.check_import("import os\nif True print('bad')")

        self.assertFalse(result["ok"])
        self.assertIsNone(result["module"])
        self.assertTrue(result["errors"])

    def test_diff_save_error_fails_closed_and_skips_later_checks(self):
        test_runner = Mock(return_value={"ok": True})

        with tempfile.TemporaryDirectory() as temp_dir:
            target = os.path.join(temp_dir, "target.py")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("new = 2\n")

            with patch("verifier.os.makedirs", side_effect=OSError("storage unavailable")):
                result = verifier.verify_file_edit(
                    real_path=target,
                    old_content="old = 1\n",
                    new_content="new = 2\n",
                    test_name="test_example.py",
                    test_runner=test_runner,
                )

            with open(target, "r", encoding="utf-8") as handle:
                restored_content = handle.read()

        self.assertEqual(restored_content, "old = 1\n")
        self.assertFalse(result["ok"])
        self.assertIsNone(result["diff_saved"])
        self.assertEqual(result["py_compile"], "SKIP")
        self.assertEqual(result["targeted_test"]["status"], "SKIP")
        self.assertTrue(result["rollback"])
        self.assertTrue(any(error.startswith("DIFF_SAVE_ERROR:") for error in result["errors"]))
        test_runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
