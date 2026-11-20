import json
import os
import tempfile
import unittest
from unittest.mock import patch

import brain


class LoadStatsMigrationTests(unittest.TestCase):
    def setUp(self):
        self.original_state = {
            key: brain.state.get(key)
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

    def _load_from_payload(self, payload):
        with tempfile.TemporaryDirectory() as temp_dir:
            stats_path = os.path.join(temp_dir, "router_stats.json")
            with open(stats_path, "w", encoding="utf-8") as file:
                json.dump(payload, file)

            fake_brain_path = os.path.join(temp_dir, "brain.py")
            with patch.object(brain, "__file__", fake_brain_path):
                brain.load_stats()

    def test_empty_model_stats_does_not_raise_unbound_mdata(self):
        self._load_from_payload({"model_stats": {}})
        self.assertEqual(brain.state["model_stats"], {})

    def test_migration_updates_every_model_record(self):
        self._load_from_payload({
            "model_stats": {
                "model-a": {"success": 1},
                "model-b": {"error_types": {"timeout": 2}},
                "invalid-record": None,
            }
        })

        stats = brain.state["model_stats"]
        self.assertEqual(stats["model-a"]["error_types"], {})
        self.assertIsNone(stats["model-a"]["last_status_code"])
        self.assertEqual(
            stats["model-b"]["error_types"],
            {"timeout": 2},
        )
        self.assertIsNone(stats["model-b"]["last_status_code"])
        self.assertIsNone(stats["invalid-record"])


if __name__ == "__main__":
    unittest.main()
