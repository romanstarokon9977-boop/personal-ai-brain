"""
Интеграционный тест self_inspection через штатный маршрут brain.tool_execute.

Изолированный. Не запускает реальные внешние процессы:
- subprocess.run замокан до импорта brain.
- mcp_bridge.mcp_is_alive → False (MCP не стартует).
- requests/socket не вызываются (self_inspection их не использует).
- Termux API не вызывается.

Не изменяет файлы проекта. Не трогает сеть, MCP, Termux API.
"""

import importlib.util
import os
import unittest
from unittest import mock


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
BRAIN_PATH = os.path.join(PROJECT_ROOT, "brain.py")


def _fake_subprocess_run(args, **kwargs):
    """Фейковый subprocess.run — не запускает реальные процессы."""
    m = mock.MagicMock()
    m.stderr = ""
    if isinstance(args, list) and args[:1] == ["git"]:
        if "rev-parse" in args and "--symbolic-full-name" in args:
            m.returncode = 0
            m.stdout = "origin/main\\n"
        elif "rev-parse" in args and "--abbrev-ref" in args:
            m.returncode = 0
            m.stdout = "main\n"
        elif "rev-parse" in args and "--short" in args:
            m.returncode = 0
            m.stdout = "abc1234\n"
        elif "rev-list" in args:
            m.returncode = 0
            m.stdout = "0\n"
        elif "status" in args:
            m.returncode = 0
            m.stdout = ""
        else:
            m.returncode = 128
            m.stdout = ""
    else:
        m.returncode = 128
        m.stdout = ""
    return m


class IntegrationSelfInspectionTest(unittest.TestCase):

    brain = None

    @classmethod
    def setUpClass(cls):
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise unittest.SkipTest("OPENROUTER_API_KEY not set")
        with mock.patch("subprocess.run", side_effect=_fake_subprocess_run):
            spec = importlib.util.spec_from_file_location("brain", BRAIN_PATH)
            brain = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(brain)
            cls.brain = brain

    def _call(self, tool_name, params):
        with mock.patch("subprocess.run", side_effect=_fake_subprocess_run), \
             mock.patch.object(self.brain.mcp_bridge, "mcp_is_alive", return_value=False):
            return self.brain.tool_execute(tool_name, params)

    # T1
    def test_01_unknown_tool_routing_error(self):
        """Маршрутизация: неизвестный инструмент → UNKNOWN_TOOL."""
        r = self._call("nonexistent_tool_zzz", {})
        self.assertIsInstance(r, dict)
        self.assertFalse(r["ok"])
        self.assertIn("UNKNOWN_TOOL", r["error"])
        self.assertEqual(r["tool"], "nonexistent_tool_zzz")
        self.assertIn("elapsed", r)
        self.assertIn("error_type", r)

    # T2
    def test_02_self_inspection_structure(self):
        """Успех маршрутизации: структура с ok/error/result/tool/elapsed/error_type."""
        r = self._call("self_inspection", {})
        self.assertIsInstance(r, dict)
        for k in ("ok", "error", "result", "tool", "elapsed", "error_type"):
            self.assertIn(k, r, "missing key: " + k)
        self.assertEqual(r["tool"], "self_inspection")
        self.assertIsInstance(r["elapsed"], (int, float))
        # Если ok=False — это COLLECT_FAILED, не ошибка маршрутизации
        if not r["ok"]:
            self.assertNotIn("UNKNOWN_TOOL", r["error"])
            self.assertNotIn("PATH_OUTSIDE_ALLOWED_DIR", r["error"])

    # T3
    def test_03_project_root_not_from_params(self):
        """project_root из params не передаётся в collect()."""
        r1 = self._call("self_inspection", {})
        r2 = self._call("self_inspection", {"project_root": "/etc"})
        if r1.get("ok") and r2.get("ok") and r1.get("result") and r2.get("result"):
            pr1 = r1["result"].get("project_root")
            pr2 = r2["result"].get("project_root")
            self.assertEqual(pr1, pr2, "project_root различается между вызовами")
            self.assertNotEqual(pr2, "/etc", "project_root взят из params — нарушение")

    # T4
    def test_04_subprocess_only_git(self):
        """subprocess.run вызывался только с git-командами."""
        with mock.patch("subprocess.run", side_effect=_fake_subprocess_run) as spy, \
             mock.patch.object(self.brain.mcp_bridge, "mcp_is_alive", return_value=False):
            self.brain.tool_execute("self_inspection", {})
        for call_args in spy.call_args_list:
            args = None
            if call_args[0]:
                args = call_args[0][0]
            elif "args" in call_args[1]:
                args = call_args[1]["args"]
            if isinstance(args, list) and args:
                self.assertEqual(args[0], "git", "non-git subprocess: " + repr(args))

    # T5
    def test_05_diagnostic_vs_routing_error(self):
        """Ошибка диагностики отличается от ошибки маршрутизации."""
        r_normal = self._call("self_inspection", {})
        r_unknown = self._call("nonexistent_tool_zzz", {})
        if not r_normal.get("ok"):
            self.assertNotIn("UNKNOWN_TOOL", r_normal.get("error") or "")
        self.assertIn("UNKNOWN_TOOL", r_unknown.get("error") or "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
