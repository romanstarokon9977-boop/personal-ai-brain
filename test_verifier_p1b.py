"""Регрессионные тесты политики отката P1-B для Verifier."""

import os
import tempfile
import unittest
from unittest.mock import patch

import verifier


class TestVerifierP1BRollback(unittest.TestCase):
    def _prepare_target(self, temp_dir):
        target = os.path.join(temp_dir, "target.py")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("new_value = 2\n")
        return target

    def test_targeted_test_failure_restores_old_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = self._prepare_target(temp_dir)
            result = verifier.verify_file_edit(
                real_path=target,
                old_content="old_value = 1\n",
                new_content="new_value = 2\n",
                test_name="test_example.py",
                test_runner=lambda _: {"ok": False, "error": "assertion failed"},
            )
            with open(target, "r", encoding="utf-8") as handle:
                restored = handle.read()

        self.assertEqual(restored, "old_value = 1\n")
        self.assertFalse(result["ok"])
        self.assertEqual(result["targeted_test"]["status"], "FAIL")
        self.assertTrue(result["rollback"])
        self.assertFalse(any(error.startswith("ROLLBACK_FAILED:") for error in result["errors"]))

    def test_targeted_test_runner_exception_restores_old_content(self):
        def failing_runner(_):
            raise RuntimeError("runner crashed")

        with tempfile.TemporaryDirectory() as temp_dir:
            target = self._prepare_target(temp_dir)
            result = verifier.verify_file_edit(
                real_path=target,
                old_content="old_value = 1\n",
                new_content="new_value = 2\n",
                test_name="test_example.py",
                test_runner=failing_runner,
            )
            with open(target, "r", encoding="utf-8") as handle:
                restored = handle.read()

        self.assertEqual(restored, "old_value = 1\n")
        self.assertFalse(result["ok"])
        self.assertEqual(result["targeted_test"]["status"], "ERROR")
        self.assertTrue(result["rollback"])

    def test_targeted_test_pass_keeps_new_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = self._prepare_target(temp_dir)
            result = verifier.verify_file_edit(
                real_path=target,
                old_content="old_value = 1\n",
                new_content="new_value = 2\n",
                test_name="test_example.py",
                test_runner=lambda _: {"ok": True},
            )
            with open(target, "r", encoding="utf-8") as handle:
                current = handle.read()

        self.assertEqual(current, "new_value = 2\n")
        self.assertTrue(result["ok"])
        self.assertEqual(result["targeted_test"]["status"], "PASS")
        self.assertFalse(result["rollback"])

    def test_rollback_failure_is_reported_explicitly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = self._prepare_target(temp_dir)
            with patch("builtins.open", side_effect=OSError("storage unavailable")):
                result = verifier.verify_file_edit(
                    real_path=target,
                    old_content="old_value = 1\n",
                    new_content="new_value = 2\n",
                    test_name="test_example.py",
                    test_runner=lambda _: {"ok": False},
                )

        self.assertFalse(result["ok"])
        self.assertFalse(result["rollback"])
        self.assertTrue(any(error.startswith("ROLLBACK_FAILED:") for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
