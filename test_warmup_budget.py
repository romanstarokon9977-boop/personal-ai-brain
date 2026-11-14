"""Regression tests for safe, provider-aware startup warmup requests."""

import os
os.environ.setdefault("OPENROUTER_API_KEY", "ci-dummy-key-not-a-secret")

import unittest
from unittest.mock import MagicMock, patch

import brain


MESSAGES = [{"role": "user", "content": "Привет"}]


def make_success_response(model="test/model:free"):
    response = MagicMock()
    response.status_code = 200
    response.headers = {"Content-Type": "application/json"}
    response.text = ""
    response.json.return_value = {
        "choices": [{"message": {"content": "ok"}}],
        "model": model,
        "provider": "test",
    }
    return response


class WarmupBudgetTests(unittest.TestCase):
    def test_openrouter_request_accepts_explicit_output_limit(self):
        response = make_success_response()
        with patch.object(brain.requests, "post", return_value=response) as post:
            ok, _ = brain.ask_model(
                "test/model:free", MESSAGES, max_tokens=brain.WARMUP_MAX_TOKENS
            )

        self.assertTrue(ok)
        self.assertEqual(
            post.call_args.kwargs["json"]["max_tokens"],
            brain.WARMUP_MAX_TOKENS,
        )

    def test_openrouter_default_request_payload_remains_unchanged(self):
        response = make_success_response()
        with patch.object(brain.requests, "post", return_value=response) as post:
            ok, _ = brain.ask_model("test/model:free", MESSAGES)

        self.assertTrue(ok)
        self.assertNotIn("max_tokens", post.call_args.kwargs["json"])

    def test_gemini_request_accepts_explicit_output_limit(self):
        response = make_success_response("gemini-3.7-flash")
        with patch.object(brain, "GEMINI_API_KEY", "test-key"), patch.object(
            brain.requests, "post", return_value=response
        ) as post:
            ok, _ = brain.ask_gemini_model(
                "gemini-3.7-flash",
                MESSAGES,
                max_tokens=brain.WARMUP_MAX_TOKENS,
            )

        self.assertTrue(ok)
        self.assertEqual(
            post.call_args.kwargs["json"]["max_tokens"],
            brain.WARMUP_MAX_TOKENS,
        )

    def test_free_openrouter_warmup_uses_bounded_api_request(self):
        expected = (True, {"answer": "ok"})
        with patch.object(brain, "ask_model", return_value=expected) as ask:
            result = brain.ask_warmup_model(
                {"model": "vendor/model:free", "layer": "API"}, MESSAGES
            )

        self.assertEqual(result, expected)
        ask.assert_called_once_with(
            "vendor/model:free", MESSAGES, max_tokens=brain.WARMUP_MAX_TOKENS
        )

    def test_paid_or_unverified_openrouter_model_is_not_called(self):
        with patch.object(brain, "ask_model") as ask:
            ok, result = brain.ask_warmup_model(
                {"model": "vendor/paid-model", "layer": "API"}, MESSAGES
            )

        self.assertFalse(ok)
        self.assertEqual(result["error"], "WARMUP_SKIPPED_NON_FREE_MODEL")
        ask.assert_not_called()

    def test_gemini_warmup_uses_gemini_client(self):
        expected = (True, {"answer": "ok"})
        with patch.object(brain, "ask_gemini_model", return_value=expected) as ask_gemini, patch.object(
            brain, "ask_model"
        ) as ask_openrouter:
            result = brain.ask_warmup_model(
                {"model": "gemini-3.7-flash", "layer": "GEMINI"}, MESSAGES
            )

        self.assertEqual(result, expected)
        ask_gemini.assert_called_once_with(
            "gemini-3.7-flash", MESSAGES, max_tokens=brain.WARMUP_MAX_TOKENS
        )
        ask_openrouter.assert_not_called()

    def test_local_or_unknown_layer_is_not_sent_to_openrouter(self):
        with patch.object(brain, "ask_model") as ask_openrouter, patch.object(
            brain, "ask_gemini_model"
        ) as ask_gemini:
            ok, result = brain.ask_warmup_model(
                {"model": "qwen-local", "layer": "LOCAL"}, MESSAGES
            )

        self.assertFalse(ok)
        self.assertEqual(result["error"], "WARMUP_UNSUPPORTED_LAYER:LOCAL")
        ask_openrouter.assert_not_called()
        ask_gemini.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
