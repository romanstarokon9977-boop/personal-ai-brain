import os
import tempfile
import unittest
from unittest import mock

import verifier


class VerifyFilePostconditionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="verifier_postcondition_")
        self.file_path = os.path.join(self.tmp, "target.txt")
        self.file_patch = mock.patch.object(
            verifier, "__file__", os.path.join(self.tmp, "verifier.py")
        )
        self.file_patch.start()
        self.addCleanup(self.file_patch.stop)

    def test_exact_persisted_content_passes(self):
        with open(self.file_path, "w", encoding="utf-8") as f:
            f.write("new content")
        result = verifier.verify_file_edit(self.file_path, "old content", "new content")
        self.assertTrue(result["ok"])
        self.assertEqual(result["postcondition"], "PASS")
        self.assertFalse(result["rollback"])

    def test_read_error_fails_and_attempts_rollback(self):
        with open(self.file_path, "w", encoding="utf-8") as f:
            f.write("new content")
        real_open = open
        failed = {"done": False}

        def fail_first_target_read(path, mode="r", *args, **kwargs):
            if path == self.file_path and mode == "r" and not failed["done"]:
                failed["done"] = True
                raise PermissionError("mock read failure")
            return real_open(path, mode, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=fail_first_target_read):
            result = verifier.verify_file_edit(
                self.file_path, "old content", "new content"
            )
        self.assertFalse(result["ok"])
        self.assertIn("POSTCONDITION_READ_FAILED", result["errors"][0])
        self.assertTrue(result["rollback"])
        with real_open(self.file_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "old content")

    def test_mismatch_fails_and_restores_old_content(self):
        with open(self.file_path, "w", encoding="utf-8") as f:
            f.write("unexpected content")
        result = verifier.verify_file_edit(self.file_path, "old content", "expected content")
        self.assertFalse(result["ok"])
        self.assertIn("POSTCONDITION_CONTENT_MISMATCH", result["errors"])
        self.assertTrue(result["rollback"])
        with open(self.file_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "old content")


if __name__ == "__main__":
    unittest.main(verbosity=2)
