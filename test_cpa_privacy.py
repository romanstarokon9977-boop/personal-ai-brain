import sys
import types
import unittest
from unittest import mock

from cpa_brain_bridge import publish_cpa_gadget


class CpaPrivacyTests(unittest.TestCase):
    def test_secret_like_content_is_blocked_even_in_dry_run(self):
        result = publish_cpa_gadget(
            product_url="https://example.com/product",
            title="Product",
            description="Use token sk-or-v1-123456789012345678901234",
            price="10",
            dry_run=True,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "SENSITIVE_CONTENT_BLOCKED")

    def test_publish_failure_never_returns_bot_token_or_url(self):
        token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk"
        config = types.SimpleNamespace(
            TELEGRAM_BOT_TOKEN=token,
            TELEGRAM_CHANNEL_ID="@test",
        )
        with mock.patch.dict(sys.modules, {"config": config}):
            with mock.patch(
                "urllib.request.urlopen",
                side_effect=RuntimeError("failed https://api.telegram.org/bot" + token + "/sendMessage"),
            ):
                result = publish_cpa_gadget(
                    product_url="https://example.com/product",
                    title="Product",
                    description="Description",
                    price="10",
                    dry_run=False,
                    confirm_publish=True,
                )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "TELEGRAM_PUBLISH_FAILED")
        self.assertNotIn(token, str(result))


if __name__ == "__main__":
    unittest.main(verbosity=2)
