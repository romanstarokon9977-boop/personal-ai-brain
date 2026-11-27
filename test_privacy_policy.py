import unittest

from privacy_policy import (
    INTERNAL,
    PERSONAL,
    SECRET,
    USER_INPUT,
    classify_message,
    contains_secret_data,
    filter_external_messages,
    private_context_allowed,
    redact_secrets,
)


class PrivacyPolicyTests(unittest.TestCase):
    def test_only_exact_local_route_allows_private_context(self):
        self.assertTrue(private_context_allowed("LOCAL"))
        for layer in ("local", "API", "GEMINI", "REMOTE", "", None):
            self.assertFalse(private_context_allowed(layer))

    def test_message_classification(self):
        self.assertEqual(classify_message({"role": "system", "name": "memory", "content": "x"}), PERSONAL)
        self.assertEqual(classify_message({"role": "system", "content": "Воспоминания из прошлых обсуждений: x"}), PERSONAL)
        self.assertEqual(classify_message({"role": "user", "content": "ordinary question"}), USER_INPUT)
        self.assertEqual(classify_message({"role": "system", "content": "system policy"}), INTERNAL)

    def test_secret_patterns_detect_provider_and_bot_tokens(self):
        samples = (
            "OPENROUTER_API_KEY=sk-or-v1-123456789012345678901234",
            "ghp_123456789012345678901234567890",
            "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk",
            "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456",
            "-----BEGIN PRIVATE KEY-----",
        )
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertTrue(contains_secret_data(sample))

    def test_nested_tool_arguments_are_scanned(self):
        self.assertTrue(contains_secret_data({
            "role": "assistant",
            "tool_calls": [{"function": {"arguments": '{"api_key":"sk-123456789012345678901234"}'}}],
        }))

    def test_external_projection_removes_personal_and_secret_messages(self):
        source = [
            {"role": "system", "name": "memory", "content": "private fact"},
            {"role": "system", "name": "credentials", "content": "not for export"},
            {"role": "user", "content": "ordinary request"},
        ]
        result = filter_external_messages(source)
        self.assertEqual(len(result), 2)
        self.assertIn("ordinary request", str(result))
        self.assertNotIn("private fact", str(result))
        self.assertNotIn("not for export", str(result))
        self.assertIn("privacy_boundary", str(result))

    def test_secret_redaction(self):
        token = "sk-or-v1-123456789012345678901234"
        result = redact_secrets("provider token " + token)
        self.assertNotIn(token, result)
        self.assertIn("[REDACTED_SECRET]", result)

    def test_scan_budget_and_depth_fail_closed(self):
        self.assertTrue(contains_secret_data("x" * 300_000))
        nested = "ordinary"
        for _ in range(12):
            nested = [nested]
        self.assertTrue(contains_secret_data(nested))


if __name__ == "__main__":
    unittest.main(verbosity=2)
