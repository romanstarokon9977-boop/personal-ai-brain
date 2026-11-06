"""Regression tests for model HTTP diagnostics and controller fallback reporting."""

import os
os.environ.setdefault("OPENROUTER_API_KEY", "ci-dummy-key-not-a-secret")

import unittest
from unittest.mock import MagicMock, patch

import brain


def make_http_response(status_code, payload, headers=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    response.headers = headers or {}
    response.text = ""
    return response


class ModelHttpDiagnosticsTests(unittest.TestCase):
    def test_openrouter_429_preserves_upstream_provider_and_quota_reason(self):
        model_id = "test/diagnostics-openrouter"
        brain.state["model_stats"].pop(model_id, None)
        response = make_http_response(429, {
            "error": {
                "message": "Provider rate limit exceeded",
                "code": 429,
                "metadata": {
                    "provider_name": "ExampleProvider",
                    "limit_source": "provider",
                    "retry_after_seconds": 17,
                },
            }
        })

        with patch.object(brain.requests, "post", return_value=response):
            ok, result = brain.ask_model(
                model_id, [{"role": "user", "content": "test"}]
            )

        self.assertFalse(ok)
        self.assertEqual(result["error"], "429")
        self.assertEqual(result["provider"], "OpenRouter")
        self.assertEqual(result["upstream_provider"], "ExampleProvider")
        self.assertEqual(result["limit_source"], "provider")
        self.assertEqual(result["retry_after_seconds"], "17")
        self.assertEqual(result["detail"], "Provider rate limit exceeded")

    def test_gemini_429_preserves_provider_status_and_reason(self):
        model_id = "gemini-diagnostics-test"
        brain.state["model_stats"].pop(model_id, None)
        response = make_http_response(429, {
            "error": {
                "message": "Resource exhausted",
                "status": "RESOURCE_EXHAUSTED",
            }
        })

        with patch.object(brain, "GEMINI_API_KEY", "test-key"), \
             patch.object(brain.requests, "post", return_value=response):
            ok, result = brain.ask_gemini_model(
                model_id, [{"role": "user", "content": "test"}]
            )

        self.assertFalse(ok)
        self.assertEqual(result["error"], "HTTP_429")
        self.assertEqual(result["provider"], "Google Gemini")
        self.assertEqual(result["provider_status"], "RESOURCE_EXHAUSTED")
        self.assertEqual(result["detail"], "Resource exhausted")

    def test_controller_returns_diagnostics_for_every_failed_fallback(self):
        messages = [{"role": "user", "content": "test"}]
        failures = {
            "primary-model": {
                "error": "429", "model": "primary-model",
                "provider": "OpenRouter", "upstream_provider": "PrimaryHost",
                "detail": "primary quota exceeded",
            },
            "fallback-one": {
                "error": "429", "model": "fallback-one",
                "provider": "OpenRouter", "upstream_provider": "FallbackHost",
                "detail": "fallback quota exceeded",
            },
            "fallback-two": {
                "error": "HTTP_503", "model": "fallback-two",
                "provider": "OpenRouter", "detail": "temporarily unavailable",
            },
        }

        def fake_ask_model(model_id, _messages, tools=None):
            return False, dict(failures[model_id])

        context_diag = {
            "input_size": 10, "budget": 100, "output_size": 10,
            "used_pct": 10, "messages_in": 1, "messages_out": 1,
            "trimmed": False,
        }
        with patch.object(
            brain.context_manager, "prepare_context",
            return_value=(messages, context_diag),
        ), patch.object(
            brain, "BRAIN_LOG_FILE", "/dev/null"
        ), patch.object(
            brain, "rank_models",
            return_value=[{"id": "fallback-one"}, {"id": "fallback-two"}],
        ), patch.object(
            brain, "ask_model", side_effect=fake_ask_model
        ):
            ok, result = brain.controller_execute(
                {"model": "primary-model", "layer": "API"},
                messages,
                tools=None,
            )

        self.assertFalse(ok)
        self.assertEqual(result["error"], "429")
        self.assertEqual(
            [item["model"] for item in result["attempts"]],
            ["primary-model", "fallback-one", "fallback-two"],
        )
        self.assertEqual(
            result["attempts"][1]["upstream_provider"], "FallbackHost"
        )
        self.assertEqual(
            result["attempts"][2]["detail"], "temporarily unavailable"
        )

    def test_execution_error_formatter_shows_provider_and_fallback_attempts(self):
        formatted = brain._format_execution_model_error({
            "error": "HTTP_429",
            "model": "primary-model",
            "provider": "OpenRouter",
            "upstream_provider": "ProviderA",
            "detail": "quota exceeded",
            "attempts": [{
                "model": "fallback-model",
                "provider": "Google Gemini",
                "error": "HTTP_429",
                "detail": "resource exhausted",
            }],
        })

        self.assertIn("ProviderA", formatted)
        self.assertIn("quota exceeded", formatted)
        self.assertIn("fallback-model", formatted)
        self.assertIn("resource exhausted", formatted)


if __name__ == "__main__":
    unittest.main(verbosity=2)
