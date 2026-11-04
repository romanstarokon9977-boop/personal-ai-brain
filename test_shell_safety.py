#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Isolated safety tests for shell command handling in brain.py.

Covers tool_shell (multi-line injection, control chars) and
_classify_shell_call (pre-execution classification).

Tests are written for the POST-patch version of brain.py:
- FORBIDDEN_SHELL_CHARS constant must exist.
- tool_shell must reject "\n" and "\r" with MULTILINE_COMMAND_NOT_ALLOWED.
- tool_shell must reject all control chars from FORBIDDEN_SHELL_CHARS.
- _classify_shell_call must return REJECT for multi-line commands.

BEFORE the patch is applied, most tests will fail:
- FORBIDDEN_SHELL_CHARS does not exist yet -> AttributeError (expected).
- multi-line commands are NOT rejected -> ok=True where ok=False expected (expected).

This is by design: the test file verifies the NEW code, not the old.

Does NOT call real shell. subprocess.run is mocked everywhere.
Does NOT modify brain.py, memory, or any project file.

Run (after patch):
    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_shell_safety -v
"""

import os

# Bypass brain.py:166 sys.exit(1) when OPENROUTER_API_KEY is missing.
os.environ.setdefault("OPENROUTER_API_KEY", "dummy_for_test")

import sys
import unittest
from unittest import mock


class _FakeMM:
    """Minimal module_manager stub (same pattern as test_fallback_dedup)."""

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


def _mock_ok():
    """Mock subprocess.CompletedProcess."""
    return mock.Mock(returncode=0, stdout="ok", stderr="")


class TestShellSafety(unittest.TestCase):
    """P0.1.3 (planned): multi-line injection protection in tool_shell."""

    # ------------------------------------------------------------------
    # tool_shell — multiline and control chars (must NOT call subprocess)
    # ------------------------------------------------------------------

    def test_shell_rejects_newline(self):
        with mock.patch.object(brain.subprocess, "run", return_value=_mock_ok()) as m:
            result = brain.tool_shell("ls\nsleep 3600")
            self.assertFalse(result["ok"], f"must reject, got: {result}")
            self.assertEqual(result["error"], "MULTILINE_COMMAND_NOT_ALLOWED",
                             f"unexpected error: {result['error']!r}")
            m.assert_not_called()

    def test_shell_rejects_carriage_return(self):
        with mock.patch.object(brain.subprocess, "run", return_value=_mock_ok()) as m:
            result = brain.tool_shell("ls\rpkill brain")
            self.assertFalse(result["ok"], f"must reject, got: {result}")
            self.assertEqual(result["error"], "MULTILINE_COMMAND_NOT_ALLOWED",
                             f"unexpected error: {result['error']!r}")
            m.assert_not_called()

    def test_shell_rejects_null_byte(self):
        # NUL is not whitespace: cmd_clean.split()[0] == "ls\0extra"
        # -> COMMAND_NOT_ALLOWED fires BEFORE forbidden-chars check.
        # We only verify: rejected, subprocess.run NOT called.
        with mock.patch.object(brain.subprocess, "run", return_value=_mock_ok()) as m:
            result = brain.tool_shell("ls\0extra")
            self.assertFalse(result["ok"], f"must reject, got: {result}")
            m.assert_not_called()

    def test_shell_rejects_semicolon(self):
        with mock.patch.object(brain.subprocess, "run", return_value=_mock_ok()) as m:
            result = brain.tool_shell("ls; whoami")
            self.assertFalse(result["ok"], f"must reject, got: {result}")
            m.assert_not_called()

    def test_shell_rejects_all_control_chars_from_constant(self):
        # Requires FORBIDDEN_SHELL_CHARS to exist (post-patch).
        self.assertTrue(hasattr(brain, "FORBIDDEN_SHELL_CHARS"),
                        "FORBIDDEN_SHELL_CHARS must exist after patch")
        for ch in brain.FORBIDDEN_SHELL_CHARS:
            with self.subTest(char=repr(ch)):
                with mock.patch.object(brain.subprocess, "run", return_value=_mock_ok()) as m:
                    result = brain.tool_shell(f"ls{ch}whoami")
                    self.assertFalse(result["ok"],
                                     f"char {ch!r} not rejected; result={result}")
                    m.assert_not_called()

    # ------------------------------------------------------------------
    # tool_shell — positive cases (single-line whitelist must work)
    # ------------------------------------------------------------------

    def test_shell_accepts_single_line_whitelist(self):
        for cmd in ("ls -la", "pwd", "df -h"):
            with self.subTest(cmd=cmd):
                with mock.patch.object(brain.subprocess, "run", return_value=_mock_ok()) as m:
                    result = brain.tool_shell(cmd)
                    self.assertTrue(result["ok"],
                                    f"should accept {cmd!r}, got: {result}")
                    m.assert_called_once()

    def test_shell_rejects_unknown_command(self):
        with mock.patch.object(brain.subprocess, "run", return_value=_mock_ok()) as m:
            result = brain.tool_shell("rm -rf /")
            self.assertFalse(result["ok"], f"must reject, got: {result}")
            self.assertIn("COMMAND_NOT_ALLOWED", result["error"])
            m.assert_not_called()

    # ------------------------------------------------------------------
    # _classify_shell_call — multiline / whitelist / file-reading
    # ------------------------------------------------------------------

    def test_classify_rejects_newline(self):
        decision, reason = brain._classify_shell_call("ls\nsleep 3600")
        self.assertEqual(decision, "REJECT", f"unexpected: {decision!r}")
        self.assertEqual(reason, "MULTILINE_COMMAND_NOT_ALLOWED",
                         f"unexpected reason: {reason!r}")

    def test_classify_rejects_carriage_return(self):
        decision, reason = brain._classify_shell_call("ls\rpkill")
        self.assertEqual(decision, "REJECT", f"unexpected: {decision!r}")
        self.assertEqual(reason, "MULTILINE_COMMAND_NOT_ALLOWED",
                         f"unexpected reason: {reason!r}")

    def test_classify_accepts_single_line_whitelist(self):
        decision, reason = brain._classify_shell_call("ls -la")
        self.assertEqual(decision, "AUTO_OK", f"unexpected: {decision!r}, reason: {reason!r}")

    def test_classify_accepts_file_reading_inside(self):
        decision, reason = brain._classify_shell_call(
            "cat /storage/emulated/0/Documents/x.txt"
        )
        self.assertEqual(decision, "AUTO_OK", f"unexpected: {decision!r}, reason: {reason!r}")
        self.assertIn("file-read inside allowed dirs", reason)

    def test_classify_needs_confirm_for_file_outside(self):
        decision, reason = brain._classify_shell_call("cat /etc/passwd")
        self.assertEqual(decision, "NEEDS_CONFIRM",
                         f"unexpected: {decision!r}, reason: {reason!r}")
        self.assertIn("PATH_OUTSIDE_ALLOWED_DIRS", reason)

    # ------------------------------------------------------------------
    # Constant validation
    # ------------------------------------------------------------------

    def test_forbidden_shell_chars_full(self):
        self.assertTrue(hasattr(brain, "FORBIDDEN_SHELL_CHARS"),
                        "FORBIDDEN_SHELL_CHARS must exist after patch")
        expected = {
            ";", "&", "|", "`", "$", ">", "<",           # shell operators
            "\n", "\r", "\0", "\t", "\v", "\f",          # control chars
        }
        actual = set(brain.FORBIDDEN_SHELL_CHARS)
        self.assertEqual(actual, expected,
                         f"missing: {expected - actual}; extra: {actual - expected}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
