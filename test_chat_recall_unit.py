"""Isolated unit tests for Chat Recall ranking; no chat files are accessed."""

import unittest
from unittest.mock import patch

import chat_recall


class TestChatRecallRanking(unittest.TestCase):
    def setUp(self):
        self.chats = [
            {"id": "phrase", "title": "Exact phrase", "updated_at": "2026-11-06T10:00:00"},
            {"id": "scattered", "title": "Scattered terms", "updated_at": "2026-11-06T11:00:00"},
            {"id": "partial", "title": "Partial match", "updated_at": "2026-11-06T12:00:00"},
        ]
        self.data = {
            "phrase": {
                "title": "Exact phrase",
                "updated_at": "2026-11-06T10:00:00",
                "messages": [{"role": "user", "content": "локальная модель Qwen3 доступна"}],
            },
            "scattered": {
                "title": "Scattered terms",
                "updated_at": "2026-11-06T11:00:00",
                "messages": [{"role": "assistant", "content": "Qwen3 обсуждали отдельно; затем проверили локальную модель"}],
            },
            "partial": {
                "title": "Partial match",
                "updated_at": "2026-11-06T12:00:00",
                "messages": [{"role": "user", "content": "локальная модель работает"}],
            },
        }
        self.list_patcher = patch.object(chat_recall.chat_system, "list_chats", return_value=self.chats)
        self.load_patcher = patch.object(
            chat_recall.chat_system, "load_chat",
            side_effect=lambda chat_id: self.data.get(chat_id),
        )
        self.list_mock = self.list_patcher.start()
        self.load_mock = self.load_patcher.start()
        self.addCleanup(self.list_patcher.stop)
        self.addCleanup(self.load_patcher.stop)

    def test_exact_phrase_ranks_above_scattered_matches(self):
        results = chat_recall.search_chat_history("локальная модель Qwen3")
        self.assertEqual(results[0]["chat_id"], "phrase")
        self.assertGreater(results[0]["score"], results[1]["score"])

    def test_complete_query_match_ranks_above_partial_match(self):
        results = chat_recall.search_chat_history("локальная модель Qwen3")
        ids = [item["chat_id"] for item in results]
        self.assertLess(ids.index("phrase"), ids.index("partial"))

    def test_excludes_active_chat(self):
        results = chat_recall.search_chat_history(
            "локальная модель Qwen3", exclude_chat_id="phrase"
        )
        self.assertNotIn("phrase", [item["chat_id"] for item in results])

    def test_internal_and_system_messages_are_excluded(self):
        self.data["phrase"]["messages"] = [
            {"role": "system", "content": "локальная модель Qwen3"},
            {"role": "assistant", "name": "memory", "content": "локальная модель Qwen3"},
            {"role": "assistant", "name": "chat_recall", "content": "локальная модель Qwen3"},
        ]
        results = chat_recall.search_chat_history("локальная модель Qwen3")
        self.assertNotIn("phrase", [item["chat_id"] for item in results])

    def test_result_content_is_bounded(self):
        self.data["phrase"]["messages"] = [
            {"role": "user", "content": "локальная модель Qwen3 " + ("x" * 500)}
        ]
        results = chat_recall.search_chat_history("локальная модель Qwen3")
        item = next(row for row in results if row["chat_id"] == "phrase")
        self.assertLessEqual(len(item["content"]), 301)

    def test_empty_query_does_not_read_chats(self):
        self.assertEqual(chat_recall.search_chat_history("   "), [])
        self.list_mock.assert_not_called()

    def test_chat_loading_errors_are_skipped(self):
        self.load_mock.side_effect = RuntimeError("unavailable")
        self.assertEqual(chat_recall.search_chat_history("локальная модель"), [])

    def test_recall_context_uses_ranked_results(self):
        context = chat_recall.recall_as_context("локальная модель Qwen3")
        self.assertTrue(context.startswith("Воспоминания из прошлых обсуждений:"))
        self.assertIn('Exact phrase', context)


if __name__ == "__main__":
    unittest.main(verbosity=2)
