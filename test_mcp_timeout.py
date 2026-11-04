#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Isolated runtime test for mcp_bridge._read_response (v3).

Imports only mcp_bridge. Does not start MCP server, does not call real tools.
Uses real subprocess.Popen(["python3", "-c", ...]) for pipe simulation.

Tests are written for the POST-patch version of MCPBridge (v3: select + os.read
+ permanent buffer + _needs_restart flag). Before the patch is applied, most
tests will fail with AttributeError — this is expected (they verify NEW code).

Run (after patch):
    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_mcp_timeout -v
"""

import subprocess
import time
import unittest

import mcp_bridge


def _make_bridge(code):
    """Create MCPBridge with a subprocess as _proc.

    Tests use this helper, NOT bridge.start() (which would launch the real
    MCP server via node). Process is killed via addCleanup.
    """
    proc = subprocess.Popen(
        ["python3", "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    bridge = mcp_bridge.MCPBridge()
    bridge._proc = proc
    return bridge


def _kill_proc(bridge):
    if bridge._proc and bridge._proc.poll() is None:
        try:
            bridge._proc.kill()
            bridge._proc.wait(timeout=2)
        except Exception:
            pass


class TestMcpReadResponse(unittest.TestCase):

    def test_silent_process_timeout(self):
        bridge = _make_bridge("import time; time.sleep(60)")
        self.addCleanup(_kill_proc, bridge)

        t0 = time.monotonic()
        result = bridge._read_response(expected_id=1, timeout=2)
        elapsed = time.monotonic() - t0

        self.assertIsNone(result, "silent process must yield None")
        self.assertGreaterEqual(elapsed, 1.8, f"timeout too early: {elapsed:.3f}s")
        self.assertLess(elapsed, 3.0, f"timeout too late: {elapsed:.3f}s")

    def test_normal_json_response(self):
        code = (
            "import time; "
            "print('{\"id\":1,\"ok\":true}', flush=True); "
            "time.sleep(60)"
        )
        bridge = _make_bridge(code)
        self.addCleanup(_kill_proc, bridge)

        result = bridge._read_response(expected_id=1, timeout=3)
        self.assertIsNotNone(result, "normal response should not be None")
        self.assertEqual(result.get("id"), 1)
        self.assertEqual(result.get("ok"), True)

    def test_partial_json_collected(self):
        code = (
            "import sys, time; "
            "sys.stdout.write('{\"id\":'); sys.stdout.flush(); "
            "time.sleep(0.3); "
            "sys.stdout.write('1}\\n'); sys.stdout.flush(); "
            "time.sleep(60)"
        )
        bridge = _make_bridge(code)
        self.addCleanup(_kill_proc, bridge)

        result = bridge._read_response(expected_id=1, timeout=3)
        self.assertIsNotNone(result, "partial response should be collected")
        self.assertEqual(result.get("id"), 1)

    def test_garbage_before_json(self):
        code = (
            "import time; "
            "print('NOT_JSON', flush=True); "
            "print('{\"id\":1}', flush=True); "
            "time.sleep(60)"
        )
        bridge = _make_bridge(code)
        self.addCleanup(_kill_proc, bridge)

        result = bridge._read_response(expected_id=1, timeout=3)
        self.assertIsNotNone(result, "should skip garbage and find JSON")
        self.assertEqual(result.get("id"), 1)

    def test_wrong_id_ignored(self):
        code = (
            "import time; "
            "print('{\"id\":999}', flush=True); "
            "print('{\"id\":1}', flush=True); "
            "time.sleep(60)"
        )
        bridge = _make_bridge(code)
        self.addCleanup(_kill_proc, bridge)

        result = bridge._read_response(expected_id=1, timeout=3)
        self.assertIsNotNone(result)
        self.assertEqual(result.get("id"), 1)

    def test_late_response_not_misattributed(self):
        code = (
            "import time; "
            "time.sleep(0.4); "
            "print('{\"id\":1}', flush=True); "
            "time.sleep(0.4); "
            "print('{\"id\":2}', flush=True); "
            "time.sleep(60)"
        )
        bridge = _make_bridge(code)
        self.addCleanup(_kill_proc, bridge)

        t0 = time.monotonic()
        first = bridge._read_response(expected_id=1, timeout=0.1)
        elapsed = time.monotonic() - t0
        self.assertIsNone(first, "should timeout before first write")
        self.assertLess(elapsed, 0.5, "first timeout too long")

        result = bridge._read_response(expected_id=2, timeout=3)
        self.assertIsNotNone(result, "should eventually get id=2")
        self.assertEqual(result.get("id"), 2, f"got wrong id: {result.get('id')}")

    def test_overflow_sets_restart_flag(self):
        code = (
            "import sys, time; "
            "sys.stdout.write('A' * 100000); sys.stdout.flush(); "
            "time.sleep(60)"
        )
        bridge = _make_bridge(code)
        self.addCleanup(_kill_proc, bridge)

        result = bridge._read_response(expected_id=1, timeout=3)
        self.assertIsNone(result, "overflow should yield None")
        self.assertTrue(bridge._needs_restart, "overflow must set _needs_restart")

    def test_multiple_messages_sequential_reads(self):
        """Multiple consecutive JSON-RPC messages over sequential reads.

        After reading id=2, next call must get id=3 — regardless of whether
        id=3 was buffered in the same os.read() chunk or arrived in a later one.
        """
        code = (
            "import time; "
            "print('{\"id\":1}', flush=True); "
            "print('{\"id\":2}', flush=True); "
            "print('{\"id\":3}', flush=True); "
            "time.sleep(60)"
        )
        bridge = _make_bridge(code)
        self.addCleanup(_kill_proc, bridge)

        result2 = bridge._read_response(expected_id=2, timeout=3)
        self.assertIsNotNone(result2)
        self.assertEqual(result2.get("id"), 2)

        result3 = bridge._read_response(expected_id=3, timeout=2)
        self.assertIsNotNone(result3, "next read must return id=3")
        self.assertEqual(result3.get("id"), 3)

    def test_finished_process_data_in_pipe(self):
        code = (
            "import sys, time; "
            "sys.stdout.write('{\"id\":1}\\n'); sys.stdout.flush(); "
            "time.sleep(0.1); "
            "sys.exit(0)"
        )
        bridge = _make_bridge(code)
        self.addCleanup(_kill_proc, bridge)

        time.sleep(0.4)
        self.assertFalse(bridge.is_alive(), "process should have exited")

        result = bridge._read_response(expected_id=1, timeout=2)
        self.assertIsNotNone(result, "must read data even from dead process")
        self.assertEqual(result.get("id"), 1)

    def test_non_dict_json_skipped(self):
        code = (
            "import time; "
            "print('[\"unexpected\"]', flush=True); "
            "print('{\"id\":1}', flush=True); "
            "time.sleep(60)"
        )
        bridge = _make_bridge(code)
        self.addCleanup(_kill_proc, bridge)

        result = bridge._read_response(expected_id=1, timeout=3)
        self.assertIsNotNone(result, "should skip list JSON and find dict")
        self.assertEqual(result.get("id"), 1)

    def test_many_full_messages_no_false_overflow(self):
        # v3 fix verification: 200 full messages × ~640 bytes ≈ 128 KB total.
        # Total volume > 64 KB, but each is a complete line. After parsing,
        # buffer is small. Overflow must NOT fire.
        code = (
            "import time; "
            "\nfor i in range(200):\n"
            "    print('{\"id\":' + str(i) + ',\"data\":\"' + ('x' * 600) + '\"}', flush=True)\n"
            "time.sleep(60)"
        )
        bridge = _make_bridge(code)
        self.addCleanup(_kill_proc, bridge)

        result = bridge._read_response(expected_id=50, timeout=8)
        self.assertIsNotNone(result, "should find id=50 among 200 messages")
        self.assertEqual(result.get("id"), 50)
        self.assertFalse(bridge._needs_restart, "false overflow: v3 fix failed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
