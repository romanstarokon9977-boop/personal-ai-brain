import sys
import unittest
from types import SimpleNamespace
from unittest import mock

import cpa_brain_bridge


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b'{"ok": true, "result": {"message_id": 1}}'


class CpaPublishSafetyTests(unittest.TestCase):
    def test_default_call_is_dry_run(self):
        with mock.patch.object(cpa_brain_bridge.urllib.request, "urlopen") as send:
            result = cpa_brain_bridge.publish_cpa_gadget("https://example.test", "title", "desc", "10")
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        send.assert_not_called()

    def test_real_publish_requires_confirmation(self):
        with mock.patch.object(cpa_brain_bridge.urllib.request, "urlopen") as send:
            result = cpa_brain_bridge.publish_cpa_gadget(
                "https://example.test", "title", "desc", "10", dry_run=False
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "PUBLISH_CONFIRMATION_REQUIRED")
        send.assert_not_called()

    def test_explicit_confirmation_allows_publish(self):
        fake_config = SimpleNamespace(
            TELEGRAM_BOT_TOKEN="test-token",
            TELEGRAM_CHANNEL_ID="@test-channel",
        )
        with mock.patch.dict(sys.modules, {"config": fake_config}), \\
             mock.patch.object(cpa_brain_bridge.urllib.request, "urlopen", return_value=FakeResponse()) as send:
            result = cpa_brain_bridge.publish_cpa_gadget(
                "https://example.test", "title", "desc", "10",
                dry_run=False, confirm_publish=True,
            )
        self.assertTrue(result["ok"])
        send.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
