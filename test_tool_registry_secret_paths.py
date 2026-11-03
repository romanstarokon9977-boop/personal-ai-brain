#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for secret-path enforcement in the tool registry."""

import os
import tempfile
import unittest
from unittest.mock import patch

import tool_registry


class ToolRegistrySecretPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.temp.name)
        self.base_patch = patch.object(tool_registry, "_ALLOWED_BASE", self.root)
        self.base_patch.start()
        self.registry = tool_registry.create_default_registry()

    def tearDown(self):
        self.base_patch.stop()
        self.temp.cleanup()

    def test_rejects_secret_names_at_any_path_depth(self):
        secret_paths = (
            os.path.join(self.root, ".env"),
            os.path.join(self.root, ".env.production", "nested.txt"),
            os.path.join(self.root, "config", "credentials-prod.json"),
            os.path.join(self.root, "certs", "server.pem"),
            os.path.join(self.root, "keys", "identity.key"),
        )
        for path in secret_paths:
            with self.subTest(path=path):
                self.assertFalse(tool_registry.is_safe_path(path))

    def test_allows_regular_project_files(self):
        path = os.path.join(self.root, "modules", "helper.py")
        self.assertTrue(tool_registry.is_safe_path(path))

    def test_read_multiple_files_rejects_secret_member(self):
        safe = os.path.join(self.root, "module.py")
        secret = os.path.join(self.root, "config", ".env.local")
        ok, reason = self.registry.security_check(
            "read_multiple_files", {"paths": [safe, secret]}
        )
        self.assertFalse(ok)
        self.assertIn("PATH_OUTSIDE_ALLOWED_DIR", reason)

    def test_read_file_rejects_nested_credentials_path(self):
        path = os.path.join(self.root, "private", "credentials.json")
        ok, reason = self.registry.security_check("read_file", {"path": path})
        self.assertFalse(ok)
        self.assertIn("PATH_OUTSIDE_ALLOWED_DIR", reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)
