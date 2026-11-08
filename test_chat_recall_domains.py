import unittest
from unittest.mock import patch

import chat_recall


class TestChatRecallDomainIsolation(unittest.TestCase):
    def setUp(self):
        self.chats = [
            {"id": "dev", "title": "Development", "context_domain": "development"},
            {"id": "income", "title": "Income", "context_domain": "income"},
            {"id": "legacy", "title": "Legacy"},
        ]
        self.data = {
            "dev": {"title": "Development", "messages": [
                {"role": "user", "content": "Python project deployment notes"}]},
            "income": {"title": "Income", "messages": [
                {"role": "user", "content": "Python project deployment notes"}]},
            "legacy": {"title": "Legacy", "messages": [
                {"role": "user", "content": "Python project deployment notes"}]},
        }
        self.list_patch = patch.object(chat_recall.chat_system, "list_chats", return_value=self.chats)
        self.load_patch = patch.object(
            chat_recall.chat_system, "load_chat",
            side_effect=lambda chat_id: self.data.get(chat_id),
        )
        self.list_patch.start()
        self.load_patch.start()
        self.addCleanup(self.list_patch.stop)
        self.addCleanup(self.load_patch.stop)

    def test_only_matching_domain_is_recalled(self):
        results = chat_recall.search_chat_history(
            "Python project deployment", context_domain="development"
        )
        self.assertEqual({item["chat_id"] for item in results}, {"dev"})

    def test_legacy_chat_is_neutral_general_domain(self):
        results = chat_recall.search_chat_history(
            "Python project deployment", context_domain="general"
        )
        self.assertEqual({item["chat_id"] for item in results}, {"legacy"})

    def test_unknown_domain_fails_closed(self):
        with patch.object(chat_recall.chat_system, "list_chats") as listing:
            self.assertEqual(
                chat_recall.search_chat_history("Python project", context_domain="unknown"), []
            )
            listing.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
