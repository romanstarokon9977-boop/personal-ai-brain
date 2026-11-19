"""Integration tests for Module Manager v0 in Brain (C.1.2).

All tests use an isolated temporary directory for Module Manager state.
Real module_state.json in project root is never touched.
No MCP process, no external network, no real publications.
"""

import builtins
import json
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

import module_manager
import tool_registry


class Base(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="mm_int_")
        self.state_path = os.path.join(self.tmpdir, "module_state.json")
        self.tmp_path = os.path.join(self.tmpdir, "module_state.json.tmp")
        self._p1 = mock.patch.object(module_manager, "STATE_PATH", self.state_path)
        self._p2 = mock.patch.object(module_manager, "TMP_PATH", self.tmp_path)
        self._p1.start()
        self._p2.start()
        module_manager._loaded_once = False
        module_manager._state_health = "first_run"
        module_manager._disabled = None
        module_manager.load_state(force=True)

        import brain
        self.brain = brain

        # Ensure no MCP side effects during model-list building.
        self._p3 = mock.patch.object(self.brain.mcp_bridge, "mcp_is_alive",
                                     return_value=False)
        self._p3.start()

    def tearDown(self):
        self._p3.stop()
        self._p1.stop()
        self._p2.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class TestFilterForModel(Base):
    def _names(self, tools):
        return [t["function"]["name"] for t in tools]

    def test_01_first_run_shows_full_list(self):
        names = self._names(self.brain.get_tool_definitions())
        self.assertIn("shell", names)
        self.assertIn("read_file", names)

    def test_02_disabled_tool_filtered_from_model(self):
        self.assertTrue(module_manager.disable("shell"))
        names = self._names(self.brain.get_tool_definitions())
        self.assertNotIn("shell", names)
        self.assertIn("read_file", names)

    def test_03_corrupt_state_blocks_all_tools_for_model(self):
        with open(self.state_path, "wb") as f:
            f.write(b"not-json")
        module_manager.load_state(force=True)
        self.assertEqual(self.brain.get_tool_definitions(), [])

    def test_04_unreadable_state_blocks_all_tools_for_model(self):
        with open(self.state_path, "wb") as f:
            f.write(json.dumps({"version": 1, "updated_at": "x",
                                "disabled": []}).encode())
        real_open = builtins.open

        def failing_open(path, mode="r", *a, **kw):
            if path == self.state_path and "r" in mode:
                raise PermissionError("mock")
            return real_open(path, mode, *a, **kw)

        with mock.patch("builtins.open", side_effect=failing_open):
            module_manager.load_state(force=True)
        self.assertEqual(self.brain.get_tool_definitions(), [])


class TestPreExecution(Base):
    def test_10_first_run_allows_known_tool(self):
        with mock.patch.object(self.brain, "_tool_execute_impl",
                               return_value={"ok": True, "result": "m",
                                             "error": None}) as m:
            res = self.brain.tool_execute("read_file", {"path": "x"})
        m.assert_called_once()
        self.assertTrue(res["ok"])

    def test_10b_existing_error_type_does_not_suppress_root_error_code(self):
        wrapped_error = (
            "SOLUTION_LIBRARY_OPERATION_FAILED: "
            "VERIFICATION_REFERENCE_NOT_DECLARED"
        )
        with mock.patch.object(
            self.brain,
            "_tool_execute_impl",
            return_value={
                "ok": False,
                "result": None,
                "error": wrapped_error,
                "error_type": "TOOL_ERROR",
            },
        ):
            result = self.brain.tool_execute("solution_library", {"operation": "verify"})

        self.assertEqual(result["error_type"], "TOOL_ERROR")
        self.assertEqual(
            result["error_code"],
            "VERIFICATION_REFERENCE_NOT_DECLARED",
        )

    def test_11_disabled_tool_blocked_before_impl(self):
        self.assertTrue(module_manager.disable("read_file"))
        with mock.patch.object(self.brain, "_tool_execute_impl",
                               return_value={"ok": True, "result": "m",
                                             "error": None}) as m:
            res = self.brain.tool_execute("read_file", {"path": "x"})
        m.assert_not_called()
        self.assertFalse(res["ok"])
        self.assertIn("MODULE_DISABLED", res["error"])
        self.assertIn("read_file", res["error"])

    def test_12_corrupt_state_blocks_before_impl(self):
        with open(self.state_path, "wb") as f:
            f.write(b"junk")
        module_manager.load_state(force=True)
        with mock.patch.object(self.brain, "_tool_execute_impl",
                               return_value={"ok": True, "result": "m",
                                             "error": None}) as m:
            res = self.brain.tool_execute("read_file", {"path": "x"})
        m.assert_not_called()
        self.assertFalse(res["ok"])
        self.assertIn("MODULE_STATE_INDETERMINATE", res["error"])

    def test_13_unreadable_state_blocks_before_impl(self):
        with open(self.state_path, "wb") as f:
            f.write(json.dumps({"version": 1, "updated_at": "x",
                                "disabled": []}).encode())
        real_open = builtins.open

        def failing_open(path, mode="r", *a, **kw):
            if path == self.state_path and "r" in mode:
                raise PermissionError("mock")
            return real_open(path, mode, *a, **kw)

        with mock.patch("builtins.open", side_effect=failing_open):
            module_manager.load_state(force=True)
        with mock.patch.object(self.brain, "_tool_execute_impl",
                               return_value={"ok": True, "result": "m",
                                             "error": None}) as m:
            res = self.brain.tool_execute("read_file", {"path": "x"})
        m.assert_not_called()
        self.assertIn("MODULE_STATE_INDETERMINATE", res["error"])

    def test_14_publish_cpa_gadget_respects_disabled(self):
        self.assertTrue(module_manager.disable("publish_cpa_gadget"))
        res = self.brain.tool_execute("publish_cpa_gadget", {})
        self.assertFalse(res["ok"])
        self.assertIn("MODULE_DISABLED: publish_cpa_gadget", res["error"])

    def test_15_publish_cpa_gadget_respects_corrupt(self):
        with open(self.state_path, "wb") as f:
            f.write(b"junk")
        module_manager.load_state(force=True)
        res = self.brain.tool_execute("publish_cpa_gadget", {})
        self.assertFalse(res["ok"])
        self.assertIn("MODULE_STATE_INDETERMINATE", res["error"])

    def test_16_empty_name_blocked(self):
        with mock.patch.object(self.brain, "_tool_execute_impl",
                               return_value={"ok": True, "result": "m",
                                             "error": None}) as m:
            res = self.brain.tool_execute("", {})
        m.assert_not_called()
        self.assertFalse(res["ok"])


class TestSecurityStillRuns(Base):
    def test_20_path_check_still_blocks_after_mm_pass(self):
        res = self.brain.tool_execute("read_file", {"path": "/etc/passwd"})
        self.assertFalse(res["ok"])
        self.assertIn("PATH_OUTSIDE_ALLOWED_DIR", res["error"])


class TestDynamicMcpTool(Base):
    def test_30_dynamic_mcp_tool_can_be_disabled(self):
        fake = tool_registry.ToolDefinition(
            name="fake_mcp_tool_xyz",
            source=tool_registry.ToolSource.MCP,
            capability="mcp.dynamic",
            priority=50,
            risk=tool_registry.RiskLevel.LOW,
            description="fake",
            parameters={"type": "object", "properties": {}},
        )
        self.brain.REGISTRY.register(fake)
        try:
            names = [t["function"]["name"]
                     for t in self.brain.get_tool_definitions()]
            self.assertIn("fake_mcp_tool_xyz", names)

            self.assertTrue(module_manager.disable("fake_mcp_tool_xyz"))
            names = [t["function"]["name"]
                     for t in self.brain.get_tool_definitions()]
            self.assertNotIn("fake_mcp_tool_xyz", names)

            with mock.patch.object(self.brain, "_tool_execute_impl",
                                   return_value={"ok": True, "result": "m",
                                                 "error": None}) as m:
                res = self.brain.tool_execute("fake_mcp_tool_xyz", {})
            m.assert_not_called()
            self.assertIn("MODULE_DISABLED", res["error"])
        finally:
            self.brain.REGISTRY._tools.pop("fake_mcp_tool_xyz", None)


class TestNoImplBypass(Base):
    def test_40_only_call_site_for_impl_is_tool_execute(self):
        """Static check: exactly one call site of _tool_execute_impl.

        Combined with the runtime tests above (11-16), this proves no
        code path reaches the internal handler without Module Manager.
        """
        with open("brain.py", "r", encoding="utf-8") as f:
            src = f.read()
        defs = src.count("def _tool_execute_impl(")
        calls = re.findall(r"(?<!def[ ])_tool_execute_impl[(]", src)
        self.assertEqual(defs, 1)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
