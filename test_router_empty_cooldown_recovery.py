import unittest
from unittest.mock import MagicMock, patch

import brain


class RouterEmptyCooldownRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.original_lock = {
            key: brain.state.get(key)
            for key in ("model_lock", "model_lock_type", "model_lock_layer")
        }
        self.original_model_stats = brain.state.get("model_stats", {}).copy()
        self.model_id = "test/router-empty-cooldown-recovery"
        brain.state["model_stats"] = self.original_model_stats.copy()
        brain.state["model_stats"][self.model_id] = {
            "success": 0,
            "fail": 2,
            "total_time": 0.0,
            "rate_429": 0,
            "cooldown_until": 0,
            "last_error": "EMPTY_STREAK_COOLDOWN",
            "error_types": {},
            "empty_streak": 2,
            "empty_cooldown_until": 9999999999,
            "last_status_code": 200,
        }

    def tearDown(self):
        brain.state["model_stats"] = self.original_model_stats
        for key, value in self.original_lock.items():
            brain.state[key] = value

    def test_successful_api_response_clears_empty_cooldown(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "choices": [{"message": {"content": "recovered"}}],
            "model": self.model_id,
            "provider": "mock",
        }

        with patch.object(brain.requests, "post", return_value=response):
            ok, result = brain.ask_model(
                self.model_id,
                [{"role": "user", "content": "test"}],
            )

        stats = brain.get_model_stats(self.model_id)
        self.assertTrue(ok)
        self.assertEqual(result["answer"], "recovered")
        self.assertEqual(stats["empty_streak"], 0)
        self.assertEqual(stats["empty_cooldown_until"], 0)

    def test_auto_lock_is_reselected_when_model_enters_cooldown(self):
        brain.state["model_lock"] = self.model_id
        brain.state["model_lock_type"] = "AUTO"
        brain.state["model_lock_layer"] = "API"

        replacement = {"id": "test/healthy-replacement"}
        with patch.object(brain, "controller_is_local_enabled", return_value=False), patch.object(
            brain, "rank_models", return_value=[replacement]
        ) as rank:
            route = brain.controller_route("general")

        rank.assert_called_once_with("general")
        self.assertEqual(route["model"], replacement["id"])
        self.assertEqual(brain.state["model_lock"], replacement["id"])
        self.assertEqual(brain.state["model_lock_type"], "AUTO")

    def test_manual_lock_is_not_overridden_by_auto_cooldown_recovery(self):
        brain.state["model_lock"] = self.model_id
        brain.state["model_lock_type"] = "MANUAL"
        brain.state["model_lock_layer"] = "API"

        with patch.object(brain, "rank_models") as rank:
            route = brain.controller_route("general")

        rank.assert_not_called()
        self.assertEqual(route["model"], self.model_id)
        self.assertEqual(route["lock_type"], "MANUAL")


    def test_empty_choices_increment_streak_and_activate_cooldown(self):
        stats = brain.get_model_stats(self.model_id)
        stats["empty_streak"] = 0
        stats["empty_cooldown_until"] = 0

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"choices": []}

        with patch.object(brain.requests, "post", return_value=response):
            ok, first = brain.ask_model(
                self.model_id,
                [{"role": "user", "content": "test"}],
            )
            ok2, second = brain.ask_model(
                self.model_id,
                [{"role": "user", "content": "test"}],
            )

        self.assertFalse(ok)
        self.assertFalse(ok2)
        self.assertEqual(first["error"], "Пустой ответ модели")
        self.assertEqual(second["error"], "Пустой ответ модели")
        self.assertEqual(stats["empty_streak"], 2)
        self.assertGreater(stats["empty_cooldown_until"], brain.time.time())
        self.assertEqual(stats["last_error"], "EMPTY_STREAK_COOLDOWN")

    def test_retry_tool_calls_without_text_is_success(self):
        first_response = MagicMock()
        first_response.status_code = 200
        first_response.json.return_value = {
            "choices": [{"message": {"content": ""}}],
        }

        expected_tool_calls = [{
            "id": "call_test",
            "type": "function",
            "function": {"name": "test_tool", "arguments": "{}"},
        }]
        retry_response = MagicMock()
        retry_response.status_code = 200
        retry_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": expected_tool_calls,
                }
            }],
            "model": self.model_id,
            "provider": "mock",
        }

        with patch.object(
            brain.requests, "post", side_effect=[first_response, retry_response]
        ), patch.object(brain.time, "sleep"):
            ok, result = brain.ask_model(
                self.model_id,
                [{"role": "user", "content": "test"}],
            )

        self.assertTrue(ok)
        self.assertEqual(result["tool_calls"], expected_tool_calls)
        stats = brain.get_model_stats(self.model_id)
        self.assertEqual(stats["empty_streak"], 0)
        self.assertEqual(stats["empty_cooldown_until"], 0)



if __name__ == "__main__":
    unittest.main()
