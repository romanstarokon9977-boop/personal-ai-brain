"""Chat persistence tests for context-domain metadata."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import chat_system


class TestChatSystemDomains(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.dir_patch = patch.object(chat_system, "CHATS_DIR", str(root / "chats"))
        self.index_patch = patch.object(chat_system, "INDEX_FILE", str(root / "chats" / "index.json"))
        self.dir_patch.start()
        self.index_patch.start()
        self.addCleanup(self.dir_patch.stop)
        self.addCleanup(self.index_patch.stop)
        self.addCleanup(self.temp.cleanup)

    def test_domain_persists_in_chat_and_index(self):
        chat = chat_system.create_new_chat("Development", context_domain="разработка")
        self.assertEqual(chat["context_domain"], "development")
        self.assertEqual(chat_system.load_chat(chat["id"])["context_domain"], "development")
        self.assertEqual(chat_system.list_chats()[0]["context_domain"], "development")

    def test_domain_can_be_changed_and_persists(self):
        chat = chat_system.create_new_chat("General")
        self.assertTrue(chat_system.set_chat_context_domain(chat["id"], "заработок"))
        self.assertEqual(chat_system.load_chat(chat["id"])["context_domain"], "income")
        self.assertEqual(chat_system.list_chats()[0]["context_domain"], "income")

    def test_invalid_domain_is_rejected(self):
        self.assertIsNone(chat_system.create_new_chat("Invalid", context_domain="../income"))
        chat = chat_system.create_new_chat("Valid")
        self.assertFalse(chat_system.set_chat_context_domain(chat["id"], "unknown"))
        self.assertEqual(chat_system.load_chat(chat["id"])["context_domain"], "general")

    def test_legacy_chat_defaults_to_general(self):
        chat = chat_system.create_new_chat("Legacy")
        path = Path(chat_system._chat_path(chat["id"]))
        data = chat_system.load_chat(chat["id"])
        data.pop("context_domain")
        path.write_text(__import__("json").dumps(data), encoding="utf-8")
        self.assertEqual(chat_system.load_chat(chat["id"])["context_domain"], "general")


if __name__ == "__main__":
    unittest.main(verbosity=2)
