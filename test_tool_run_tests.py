#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for isolated Test Runner failure handling.

No real test process is started: subprocess.run is mocked.
"""

import os
os.environ.setdefault("OPENROUTER_API_KEY", "dummy_for_test")

import sys
import subprocess
import unittest
from unittest import mock


class _FakeMM:
    def get_status(self, name):
        return "enabled"

    def is_enabled(self, name):
        return True

    def list_disabled(self):
        return []

    def load_state(self, force=False):
        return None

    def state_health(self):
        return "ok"


sys.modules["module_manager"] = _FakeMM()

import brain  # noqa: E402


class TestToolRunTests(unittest.TestCase):
    def test_first_test_timeout_is_reported_without_crashing(self):
        with mock.patch.object(brain, "TEST_WHITELIST", ("slow_test.py",)), \
             mock.patch.object(
                 brain.subprocess, "run",
                 side_effect=subprocess.TimeoutExpired("python", 180),
             ):
            result = brain.tool_run_tests({"scope": "full"})

        self.assertFalse(result["ok"])
        entry = result["result"]["per_test"][0]
        self.assertTrue(entry["timeout"])
        self.assertEqual(entry["classification"], "code")
        self.assertEqual(entry["tail"], "TIMEOUT 180s")
        self.assertEqual(result["result"]["code_fails"][0]["test"], "slow_test.py")

    def test_timeout_does_not_inherit_previous_environment_failure(self):
        first = subprocess.CompletedProcess(
            args=["python", "first.py"], returncode=1,
            stdout="", stderr="ConnectionError: temporary network issue",
        )
        with mock.patch.object(brain, "TEST_WHITELIST", ("first.py", "second.py")), \
             mock.patch.object(
                 brain.subprocess, "run",
                 side_effect=[first, subprocess.TimeoutExpired("python", 180)],
             ):
            result = brain.tool_run_tests({"scope": "full"})

        entries = result["result"]["per_test"]
        self.assertEqual(entries[0]["classification"], "environment")
        self.assertEqual(entries[1]["classification"], "code")
        self.assertEqual(entries[1]["tail"], "TIMEOUT 180s")
        self.assertEqual(len(result["result"]["env_fails"]), 1)
        self.assertEqual(len(result["result"]["code_fails"]), 1)

    def test_spawn_error_does_not_inherit_previous_environment_failure(self):
        first = subprocess.CompletedProcess(
            args=["python", "first.py"], returncode=1,
            stdout="", stderr="ConnectionError: temporary network issue",
        )
        with mock.patch.object(brain, "TEST_WHITELIST", ("first.py", "second.py")), \
             mock.patch.object(
                 brain.subprocess, "run",
                 side_effect=[first, OSError("process could not start")],
             ):
            result = brain.tool_run_tests({"scope": "full"})

        entries = result["result"]["per_test"]
        self.assertEqual(entries[0]["classification"], "environment")
        self.assertEqual(entries[1]["classification"], "code")
        self.assertIn("SPAWN ERROR", entries[1]["tail"])
        self.assertEqual(len(result["result"]["env_fails"]), 1)
        self.assertEqual(len(result["result"]["code_fails"]), 1)

    def test_unknown_targeted_test_is_rejected_before_spawn(self):
        with mock.patch.object(brain.subprocess, "run") as run_mock:
            result = brain.tool_run_tests({
                "scope": "targeted", "test": "../../unexpected.py"
            })

        self.assertFalse(result["ok"])
        self.assertIn("UNKNOWN_TEST", result["error"])
        run_mock.assert_not_called()

    def test_p3_2_4_semantic_guardrails_is_whitelisted_and_targeted(self):
        test_name = "test_p3_2_4_semantic_guardrails.py"
        completed = subprocess.CompletedProcess(
            args=[sys.executable, test_name],
            returncode=0,
            stdout="Ran 10 tests",
            stderr="",
        )
        with mock.patch.object(
            brain.subprocess, "run", return_value=completed
        ) as run_mock:
            result = brain.tool_run_tests({
                "scope": "targeted", "test": test_name
            })

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["total"], 1)
        self.assertEqual(result["result"]["passed"], 1)
        run_mock.assert_called_once_with(
            [sys.executable, test_name],
            capture_output=True,
            text=True,
            timeout=180,
        )

    def test_p3_2_4_5_semantic_guard_safety_is_whitelisted_and_targeted(self):
        test_name = "test_p3_2_4_5_semantic_guard_safety.py"
        completed = subprocess.CompletedProcess(
            args=[sys.executable, test_name],
            returncode=0,
            stdout="Ran 7 tests",
            stderr="",
        )
        with mock.patch.object(
            brain.subprocess, "run", return_value=completed
        ) as run_mock:
            result = brain.tool_run_tests({
                "scope": "targeted", "test": test_name
            })

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["total"], 1)
        self.assertEqual(result["result"]["passed"], 1)
        run_mock.assert_called_once_with(
            [sys.executable, test_name],
            capture_output=True,
            text=True,
            timeout=180,
        )

    def test_invalid_scope_is_rejected_before_spawn(self):
        with mock.patch.object(brain.subprocess, "run") as run_mock:
            result = brain.tool_run_tests({"scope": "arbitrary"})

        self.assertFalse(result["ok"])
        self.assertIn("BAD_SCOPE", result["error"])
        run_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
