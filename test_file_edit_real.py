#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Real file_edit integration tests with isolated, self-cleaning fixtures."""

import importlib.util
import os
import shutil
import tempfile
import unittest
import uuid


PROJECT_ROOT = os.path.dirname(os.path.realpath(__file__))
BRAIN_PATH = os.path.join(PROJECT_ROOT, "brain.py")

_spec = importlib.util.spec_from_file_location("brain_file_edit_test", BRAIN_PATH)
brain = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(brain)


class FileEditRealTests(unittest.TestCase):
    def setUp(self):
        self.backup_dir = os.path.join(PROJECT_ROOT, ".backups")
        self.backup_dir_existed = os.path.isdir(self.backup_dir)
        self.backup_entries_before = (
            set(os.listdir(self.backup_dir)) if self.backup_dir_existed else set()
        )

        self.temp_dir = tempfile.mkdtemp(
            prefix=".test_file_edit_real_",
            dir=PROJECT_ROOT,
        )
        self.target_name = f"target_{uuid.uuid4().hex}.txt"
        self.target_path = os.path.join(self.temp_dir, self.target_name)

        # Two exact duplicate lines and one unique function declaration.
        self.original_content = (
            'print("Hello, world!")\n'
            'print("Hello, world!")\n'
            'def hello():\n'
            '    return "hello"\n'
        )
        # unittest executes cleanups even when setup or an assertion fails.
        self.addCleanup(self._cleanup_artifacts)

        with open(self.target_path, "w", encoding="utf-8") as target:
            target.write(self.original_content)

    def _cleanup_artifacts(self):
        cleanup_errors = []

        try:
            if os.path.isdir(self.backup_dir):
                prefix = self.target_name + "."
                for entry in os.listdir(self.backup_dir):
                    if (
                        entry.startswith(prefix)
                        and entry not in self.backup_entries_before
                    ):
                        artifact = os.path.join(self.backup_dir, entry)
                        if os.path.isfile(artifact):
                            os.remove(artifact)
                if not self.backup_dir_existed and not os.listdir(self.backup_dir):
                    os.rmdir(self.backup_dir)
        except Exception as error:
            cleanup_errors.append(f"backup cleanup: {error}")

        try:
            if os.path.isdir(self.temp_dir):
                shutil.rmtree(self.temp_dir)
        except Exception as error:
            cleanup_errors.append(f"temporary directory cleanup: {error}")

        if cleanup_errors:
            raise RuntimeError("; ".join(cleanup_errors))

    def _edit(self, old_text, new_text):
        return brain.tool_execute(
            "file_edit",
            {
                "path": self.target_path,
                "old_text": old_text,
                "new_text": new_text,
            },
        )

    def test_zero_matches_are_rejected_without_modification(self):
        result = self._edit(
            "this text is deliberately absent xyz123",
            "replacement",
        )

        self.assertFalse(result.get("ok"), result)
        self.assertIn("EDIT_REQUIRES_EXACTLY_ONE_MATCH", result.get("error", ""))
        with open(self.target_path, "r", encoding="utf-8") as target:
            self.assertEqual(target.read(), self.original_content)

    def test_multiple_matches_are_rejected_without_modification(self):
        result = self._edit(
            'print("Hello, world!")',
            'print("Changed")',
        )

        self.assertFalse(result.get("ok"), result)
        self.assertIn("EDIT_REQUIRES_EXACTLY_ONE_MATCH", result.get("error", ""))
        with open(self.target_path, "r", encoding="utf-8") as target:
            self.assertEqual(target.read(), self.original_content)

    def test_single_match_is_replaced_and_verified(self):
        result = self._edit("def hello():", "def hello_renamed():")

        self.assertTrue(result.get("ok"), result)
        with open(self.target_path, "r", encoding="utf-8") as target:
            updated_content = target.read()

        self.assertIn("def hello_renamed():", updated_content)
        self.assertNotIn("def hello():", updated_content)
        self.assertEqual(
            result.get("verifier", {}).get("postcondition"),
            "PASS",
            result,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
