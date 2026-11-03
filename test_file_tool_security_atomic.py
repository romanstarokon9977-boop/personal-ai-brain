#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Focused regression tests for Brain file-tool security and atomic writes."""

import os
import stat
import tempfile
import unittest
from unittest.mock import patch

import brain
import verifier


class FileToolSecurityAtomicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.temp.name)
        self.external = tempfile.TemporaryDirectory()
        self.allowed_patch = patch.object(brain, "FILES_ALLOWED_DIRS", (self.root,))
        self.allowed_patch.start()
        self.file_patch = patch.object(brain, "__file__", os.path.join(self.root, "brain.py"))
        self.file_patch.start()
        self.verifier_file_patch = patch.object(
            verifier, "__file__", os.path.join(self.root, "verifier.py")
        )
        self.verifier_file_patch.start()

    def tearDown(self):
        self.verifier_file_patch.stop()
        self.file_patch.stop()
        self.allowed_patch.stop()
        self.external.cleanup()
        self.temp.cleanup()

    def test_directory_list_hides_secret_and_external_symlink_entries(self):
        with open(os.path.join(self.root, "visible.txt"), "w", encoding="utf-8") as f:
            f.write("visible")
        with open(os.path.join(self.root, ".env"), "w", encoding="utf-8") as f:
            f.write("TOKEN=secret")
        outside = os.path.join(self.external.name, "outside.txt")
        with open(outside, "w", encoding="utf-8") as f:
            f.write("outside")
        try:
            os.symlink(outside, os.path.join(self.root, "outside-link.txt"))
        except (OSError, NotImplementedError):
            pass

        result = brain.tool_directory_list(self.root)

        self.assertTrue(result["ok"], result)
        self.assertIn("visible.txt", result["result"])
        self.assertNotIn(".env", result["result"])
        self.assertNotIn("outside-link.txt", result["result"])

    def test_file_search_skips_secret_files_and_external_symlinks(self):
        with open(os.path.join(self.root, "visible.txt"), "w", encoding="utf-8") as f:
            f.write("needle public")
        with open(os.path.join(self.root, ".env"), "w", encoding="utf-8") as f:
            f.write("needle SECRET_TOKEN")
        outside = os.path.join(self.external.name, "outside.txt")
        with open(outside, "w", encoding="utf-8") as f:
            f.write("needle OUTSIDE_SECRET")
        try:
            os.symlink(outside, os.path.join(self.root, "outside-link.txt"))
        except (OSError, NotImplementedError):
            pass

        result = brain.tool_file_search("needle", self.root)

        self.assertTrue(result["ok"], result)
        self.assertIn("visible.txt", result["result"])
        self.assertNotIn("SECRET_TOKEN", result["result"])
        self.assertNotIn("OUTSIDE_SECRET", result["result"])

    def test_file_edit_rejects_secret_path_without_modifying_it(self):
        secret = os.path.join(self.root, ".env")
        with open(secret, "w", encoding="utf-8") as f:
            f.write("TOKEN=unchanged")

        result = brain.tool_file_edit(secret, "unchanged", "changed")

        self.assertFalse(result["ok"])
        with open(secret, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "TOKEN=unchanged")

    def test_file_edit_uses_verified_atomic_write(self):
        target = os.path.join(self.root, "module.py")
        with open(target, "w", encoding="utf-8") as f:
            f.write("value = 1\n")

        result = brain.tool_file_edit(target, "value = 1", "value = 2")

        self.assertTrue(result["ok"], result)
        with open(target, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "value = 2\n")
        self.assertEqual(result["verifier"]["py_compile"], "PASS")
        backup_dir = os.path.join(self.root, ".backups")
        backups = os.listdir(backup_dir)
        self.assertEqual(len(backups), 2)
        self.assertTrue(any(name.startswith("module.py.bak_") for name in backups))
        self.assertTrue(any(name.startswith("module.py.diff_") for name in backups))

    def test_atomic_write_preserves_mode(self):
        target = os.path.join(self.root, "mode.txt")
        with open(target, "w", encoding="utf-8") as f:
            f.write("old")
        os.chmod(target, 0o640)

        verifier.atomic_write_text(target, "new")

        self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o640)
        with open(target, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "new")

    def test_atomic_replace_failure_keeps_original_and_cleans_temp(self):
        target = os.path.join(self.root, "stable.txt")
        with open(target, "w", encoding="utf-8") as f:
            f.write("original")

        with patch("verifier.os.replace", side_effect=OSError("simulated replace failure")):
            with self.assertRaises(OSError):
                verifier.atomic_write_text(target, "replacement")

        with open(target, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "original")
        self.assertEqual(os.listdir(self.root), ["stable.txt"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
