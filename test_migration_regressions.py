#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for the 2026-11-03 migration fixes."""

import contextlib
import copy
import io
import json
import unittest
from unittest.mock import mock_open, patch

import brain


class MigrationRegressionTests(unittest.TestCase):
    def setUp(self):
        self.original_state = {
            key: copy.deepcopy(brain.state.get(key))
            for key in (
                "model_stats",
                "total_requests",
                "successful_requests",
                "failed_requests",
            )
        }

    def tearDown(self):
        for key, value in self.original_state.items():
            brain.state[key] = value

    def _load_stats_from(self, saved):
        data = json.dumps(saved)
        with patch("brain.os.path.exists", return_value=True), patch(
            "builtins.open", mock_open(read_data=data)
        ):
            brain.load_stats()

    def test_load_stats_migrates_every_model_entry(self):
        brain.state["model_stats"] = {}
        self._load_stats_from({
            "model_stats": {
                "model-a": {"success": 1},
                "model-b": {"success": 2, "error_types": {}},
            },
            "total_requests": 3,
            "successful_requests": 2,
            "failed_requests": 1,
        })

        self.assertEqual(
            brain.state["model_stats"]["model-a"]["last_status_code"], None
        )
        self.assertEqual(
            brain.state["model_stats"]["model-b"]["last_status_code"], None
        )
        self.assertEqual(
            brain.state["model_stats"]["model-a"]["error_types"], {}
        )

    def test_load_stats_handles_empty_model_stats(self):
        brain.state["model_stats"] = {"stale": {"success": 1}}
        self._load_stats_from({
            "model_stats": {},
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
        })
        self.assertEqual(brain.state["model_stats"], {})

    def test_delete_memory_stops_when_memory_cannot_be_loaded(self):
        output = io.StringIO()
        with patch.object(brain, "_load_raw", return_value=None), patch.object(
            brain, "delete_memory"
        ) as delete_mock, contextlib.redirect_stdout(output):
            brain.handle_delete_memory_command("удали из памяти важный факт")

        self.assertIn("MEMORY_READ_FAILED", output.getvalue())
        delete_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
