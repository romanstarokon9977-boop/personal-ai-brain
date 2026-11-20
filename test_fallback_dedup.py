#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Isolated runtime tests for fallback tool-call deduplication and denial handling.

Does NOT call real models, MCP, tools, or file I/O.
Does NOT modify brain.py or any project file.
"""


import copy
import os

os.environ.setdefault("OPENROUTER_API_KEY", "dummy_for_test")

import unittest
from unittest import mock

import brain  # noqa: E402


class TestFallbackDedup(unittest.TestCase):
    def test_dedup_across_fallback(self):
        route_a = {"model": "model-a", "layer": "API"}
        route_b = {"model": "model-b", "layer": "API"}
        route_history = []

        def fake_route(task):
            route = route_b
            route_history.append(route.get("model"))
            return route

        responses = [
            (True, {"tool_calls": [{"id": "call_a_1", "function": {
                "name": "shell", "arguments": '{"command": "ls"}'}}]}),
            (False, {"error": "TIMEOUT", "model": "model-a"}),
            (True, {"tool_calls": [{"id": "call_b_1", "function": {
                "name": "shell", "arguments": '{"command": "ls"}'}}]}),
            (True, {"answer": "done"}),
        ]
        response_iter = iter(responses)
        controller_execute_routes = []
        messages_log = []

        def fake_controller_execute(route, messages, tools=None):
            controller_execute_routes.append(route.get("model"))
            messages_log.append(copy.deepcopy(messages))
            try:
                return next(response_iter)
            except StopIteration:
                return (True, {"answer": "unexpected_extra_call"})

        tool_iter = iter([{"ok": True, "result": "file1.txt\nfile2.txt", "error": None}])
        tool_calls_log = []

        def fake_tool_bridge_execute_call(tool_call, last_user=""):
            tool_calls_log.append(copy.deepcopy(tool_call))
            try:
                return next(tool_iter)
            except StopIteration:
                return {"ok": False, "result": None,
                        "error": "UNEXPECTED_TOOL_CALL (Model B should not execute)"}

        with mock.patch.object(brain, "controller_route", side_effect=fake_route), \
             mock.patch.object(brain, "controller_execute", side_effect=fake_controller_execute), \
             mock.patch.object(brain, "tool_bridge_execute_call", side_effect=fake_tool_bridge_execute_call), \
             mock.patch.object(brain, "get_tool_definitions", return_value=[]), \
             mock.patch.object(brain, "tool_bridge_has_calls", side_effect=lambda r: bool(r.get("tool_calls"))), \
             mock.patch.object(brain, "tool_bridge_log", side_effect=lambda *a, **k: None), \
             mock.patch("builtins.input", return_value="да"):
            ok, result = brain.execute_with_fallback(
                "test_task", route_a, [{"role": "user", "content": "list files"}]
            )

        self.assertEqual(len(tool_calls_log), 1,
                         f"Tool executed {len(tool_calls_log)} times, expected 1")
        self.assertEqual(tool_calls_log[0]["function"]["name"], "shell")
        self.assertEqual(len(route_history), 1,
                         f"controller_route called {len(route_history)} times, expected 1")
        self.assertEqual(controller_execute_routes,
                         ["model-a", "model-a", "model-b", "model-b"],
                         f"Unexpected route sequence: {controller_execute_routes}")
        final_messages = messages_log[-1]
        replay_found = any(
            m.get("role") == "tool" and "file1.txt" in (m.get("content") or "")
            for m in final_messages
        )
        self.assertTrue(replay_found,
                        f"Model B did not receive cached tool result. Roles: {[m.get('role') for m in final_messages]}")


class TestFallbackDenied(unittest.TestCase):
    def test_denied_across_fallback(self):
        route_a = {"model": "model-a", "layer": "API"}
        route_b = {"model": "model-b", "layer": "API"}
        route_history = []

        def fake_route(task):
            route = route_b
            route_history.append(route.get("model"))
            return route

        responses = [
            (True, {"tool_calls": [{"id": "call_a_1", "function": {
                "name": "shell", "arguments": '{"command": "ls"}'}}]}),
            (False, {"error": "TIMEOUT", "model": "model-a"}),
            (True, {"tool_calls": [{"id": "call_b_1", "function": {
                "name": "shell", "arguments": '{"command": "pwd"}'}}]}),
            (True, {"answer": "cannot run shell"}),
        ]
        response_iter = iter(responses)
        controller_execute_routes = []
        messages_log = []

        def fake_controller_execute(route, messages, tools=None):
            controller_execute_routes.append(route.get("model"))
            messages_log.append(copy.deepcopy(messages))
            try:
                return next(response_iter)
            except StopIteration:
                return (True, {"answer": "unexpected_extra_call"})

        tool_iter = iter([{"ok": False, "result": None, "error": "USER_DENIED: user rejected"}])
        tool_calls_log = []

        def fake_tool_bridge_execute_call(tool_call, last_user=""):
            tool_calls_log.append(copy.deepcopy(tool_call))
            try:
                return next(tool_iter)
            except StopIteration:
                return {"ok": False, "result": None,
                        "error": "UNEXPECTED_TOOL_CALL (should have been banned)"}

        with mock.patch.object(brain, "controller_route", side_effect=fake_route), \
             mock.patch.object(brain, "controller_execute", side_effect=fake_controller_execute), \
             mock.patch.object(brain, "tool_bridge_execute_call", side_effect=fake_tool_bridge_execute_call), \
             mock.patch.object(brain, "get_tool_definitions", return_value=[]), \
             mock.patch.object(brain, "tool_bridge_has_calls", side_effect=lambda r: bool(r.get("tool_calls"))), \
             mock.patch.object(brain, "tool_bridge_log", side_effect=lambda *a, **k: None), \
             mock.patch("builtins.input", return_value="да"):
            ok, result = brain.execute_with_fallback(
                "test_task", route_a, [{"role": "user", "content": "list files"}]
            )

        self.assertEqual(len(tool_calls_log), 1,
                         f"Tool executed {len(tool_calls_log)} times, expected 1")
        first_args = tool_calls_log[0]["function"]["arguments"]
        self.assertIn("ls", first_args)
        self.assertNotIn("pwd", first_args)
        self.assertEqual(len(route_history), 1,
                         f"controller_route called {len(route_history)} times, expected 1")
        self.assertEqual(controller_execute_routes,
                         ["model-a", "model-a", "model-b", "model-b"],
                         f"Unexpected route sequence: {controller_execute_routes}")
        final_messages = messages_log[-1]
        ban_found = any(
            m.get("role") == "tool" and "[DENIED-BAN:" in (m.get("content") or "")
            for m in final_messages
        )
        self.assertTrue(ban_found,
                        f"Model B missing [DENIED-BAN] message. Roles: {[m.get('role') for m in final_messages]}")


class TestFinalXmlRecovery(unittest.TestCase):
    def _run_final_xml_case(self, tool_result, expected_marker):
        route = {"model": "model-a", "layer": "API"}
        xml_answer = (
            "<tool_call><function=shell>"
            "<parameter=command>ls</parameter>"
            "</function></tool_call>"
        )
        responses = iter([
            (True, {"tool_calls": [{"id": "call_1", "function": {
                "name": "shell", "arguments": '{"command": "ls"}'}}]}),
            (True, {"answer": xml_answer}),
            (True, {"answer": "final answer"}),
        ])
        messages_log = []
        calls_log = []

        def fake_controller_execute(route_arg, messages, tools=None):
            messages_log.append(copy.deepcopy(messages))
            return next(responses)

        def fake_tool_execute(tool_call, last_user=""):
            calls_log.append(copy.deepcopy(tool_call))
            return tool_result

        with mock.patch.object(brain, "TOOL_BRIDGE_MAX_ITERATIONS", 1), \
             mock.patch.object(brain, "controller_execute", side_effect=fake_controller_execute), \
             mock.patch.object(brain, "tool_bridge_execute_call", side_effect=fake_tool_execute), \
             mock.patch.object(brain, "get_tool_definitions", return_value=[]), \
             mock.patch.object(brain, "tool_bridge_has_calls", side_effect=lambda r: bool(r.get("tool_calls"))), \
             mock.patch.object(brain, "tool_bridge_log", side_effect=lambda *a, **k: None), \
             mock.patch("builtins.input", return_value="да"):
            ok, result = brain.run_with_tools(route, [{"role": "user", "content": "list files"}])

        self.assertTrue(ok)
        self.assertEqual(result.get("answer"), "final answer")
        self.assertEqual(len(calls_log), 1, "Final XML recovery executed a tool more than once")
        final_context = messages_log[-1]
        marker_found = any(
            m.get("role") == "user" and expected_marker in (m.get("content") or "")
            for m in final_context
        )
        self.assertTrue(marker_found, f"Final XML recovery context missing {expected_marker!r}")

    def test_final_xml_recovery_reuses_cached_result(self):
        self._run_final_xml_case(
            {"ok": True, "result": "file1.txt", "error": None},
            "file1.txt",
        )

    def test_final_xml_recovery_respects_user_denial(self):
        self._run_final_xml_case(
            {"ok": False, "result": None, "error": "USER_DENIED: rejected"},
            "[DENIED-BAN:",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
