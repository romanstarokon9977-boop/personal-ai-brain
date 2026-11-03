"""P1-C regression tests for Self Inspection diagnostics.

Isolated temporary directories only. No real Git commands or project state writes.
"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import self_inspection


class ModuleManagerDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="si_p1c_mm_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, name, data):
        path = os.path.join(self.root, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_first_run_is_reported_without_creating_state(self):
        result = self_inspection._module_manager_state(self.root)
        self.assertEqual(result["status"], "first_run")
        self.assertFalse(result["state_exists"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "module_state.json")))

    def test_valid_state_reports_count_but_not_tool_names(self):
        payload = {"version": 1, "updated_at": "2026-11-03T00:00:00Z",
                   "disabled": ["shell", "read_file"]}
        self._write("module_state.json", json.dumps(payload).encode("utf-8"))
        result = self_inspection._module_manager_state(self.root)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["disabled_count"], 2)
        self.assertNotIn("disabled", result)
        self.assertNotIn("shell", repr(result))

    def test_invalid_schema_is_corrupt(self):
        payload = {"version": 1, "updated_at": "x",
                   "disabled": ["shell", "shell"]}
        self._write("module_state.json", json.dumps(payload).encode("utf-8"))
        result = self_inspection._module_manager_state(self.root)
        self.assertEqual(result["status"], "corrupt")
        self.assertEqual(result["error"], "SCHEMA_INVALID")
        self.assertIsNone(result["disabled_count"])

    def test_tmp_presence_overrides_valid_state(self):
        payload = {"version": 1, "updated_at": "x", "disabled": []}
        self._write("module_state.json", json.dumps(payload).encode("utf-8"))
        self._write("module_state.json.tmp", b"pending")
        result = self_inspection._module_manager_state(self.root)
        self.assertEqual(result["status"], "corrupt")
        self.assertEqual(result["error"], "TMP_PRESENT")

    def test_unreadable_state_is_reported(self):
        path = self._write("module_state.json", b"{}")
        real_open = open

        def blocked_open(target, mode="r", *args, **kwargs):
            if os.fspath(target) == path and "r" in mode:
                raise PermissionError("blocked")
            return real_open(target, mode, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=blocked_open):
            result = self_inspection._module_manager_state(self.root)
        self.assertEqual(result["status"], "unreadable")
        self.assertEqual(result["error"], "STATE_READ_ERROR")

    def test_symlink_outside_project_is_not_read(self):
        outside_dir = tempfile.mkdtemp(prefix="si_p1c_out_")
        outside = os.path.join(outside_dir, "state.json")
        try:
            with open(outside, "wb") as f:
                f.write(json.dumps({"version": 1, "updated_at": "x",
                                    "disabled": ["secret_tool"]}).encode())
            link = os.path.join(self.root, "module_state.json")
            try:
                os.symlink(outside, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks not supported")
            result = self_inspection._module_manager_state(self.root)
            self.assertEqual(result["status"], "indeterminate")
            self.assertEqual(result["error"], "OUTSIDE_PROJECT_ROOT")
            self.assertIsNone(result["disabled_count"])
        finally:
            shutil.rmtree(outside_dir, ignore_errors=True)


class GitUpstreamDiagnosticsTests(unittest.TestCase):
    def _run(self, upstream="origin/feature/p1c", ahead="3", behind="2"):
        calls = []

        def fake_run(args, **kwargs):
            calls.append(list(args))
            m = mock.MagicMock()
            m.returncode = 0
            m.stdout = ""
            if args == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
                m.stdout = "feature/p1c\n"
            elif args == ["git", "rev-parse", "--short", "HEAD"]:
                m.stdout = "abc1234\n"
            elif "--symbolic-full-name" in args:
                if upstream is None:
                    m.returncode = 128
                else:
                    m.stdout = upstream + "\n"
            elif args[:2] == ["git", "rev-list"]:
                range_arg = args[-1]
                if range_arg.endswith("..HEAD"):
                    m.stdout = ahead + "\n"
                elif range_arg.startswith("HEAD.."):
                    m.stdout = behind + "\n"
                else:
                    m.returncode = 128
            elif args[:2] == ["git", "status"]:
                m.stdout = ""
            else:
                m.returncode = 128
            return m

        with mock.patch("subprocess.run", side_effect=fake_run):
            state = self_inspection._git_state(tempfile.gettempdir())
        return state, calls

    def test_uses_configured_upstream_not_origin_main(self):
        state, calls = self._run("origin/feature/p1c", "4", "1")
        self.assertEqual(state["upstream"], "origin/feature/p1c")
        self.assertEqual(state["tracking_status"], "ok")
        self.assertEqual(state["ahead_of_upstream"], 4)
        self.assertEqual(state["behind_of_upstream"], 1)
        self.assertEqual(state["ahead_of_origin"], 4)
        self.assertEqual(state["behind_origin"], 1)
        self.assertFalse(any("origin/main" in str(args) for args in calls))

    def test_non_origin_upstream_does_not_fill_origin_aliases(self):
        state, _ = self._run("upstream/release", "2", "5")
        self.assertEqual(state["upstream"], "upstream/release")
        self.assertEqual(state["ahead_of_upstream"], 2)
        self.assertEqual(state["behind_of_upstream"], 5)
        self.assertIsNone(state["ahead_of_origin"])
        self.assertIsNone(state["behind_origin"])

    def test_missing_upstream_is_explicit_and_not_compared_to_main(self):
        state, calls = self._run(None)
        self.assertEqual(state["tracking_status"], "not_configured")
        self.assertEqual(state["upstream_error"], "UPSTREAM_NOT_CONFIGURED")
        self.assertIsNone(state["ahead_of_upstream"])
        self.assertIsNone(state["behind_of_upstream"])
        self.assertFalse(any(args[:2] == ["git", "rev-list"] for args in calls))

    def test_collect_exposes_module_manager_and_upstream_gap(self):
        with mock.patch.object(self_inspection, "INSPECTED_FILES", ()), \
             mock.patch.object(self_inspection, "_git_state", return_value={
                 "available": True, "tracking_status": "not_configured"
             }):
            report = self_inspection.collect(project_root=tempfile.gettempdir())
        self.assertTrue(report["ok"])
        self.assertIn("module_manager", report["result"])
        self.assertIn(
            "git_upstream_not_configured",
            report["result"]["diagnostics"]["inconclusive"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
