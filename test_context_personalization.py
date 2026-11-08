import unittest
from unittest.mock import Mock

import context_personalization


class ChatHistoryContextTests(unittest.TestCase):
    def test_recall_is_scoped_to_active_domain_and_excludes_current_chat(self):
        recall = Mock(return_value="Воспоминания из прошлых обсуждений:\n- заметка")
        result = context_personalization.build_chat_history_context(
            "продолжить проект",
            context_domain="разработка",
            active_chat_id="active-chat",
            recall_func=recall,
        )
        self.assertIn("заметка", result)
        recall.assert_called_once_with(
            "продолжить проект",
            exclude_chat_id="active-chat",
            max_results=3,
            context_domain="development",
        )

    def test_unknown_domain_fails_closed_without_recall(self):
        recall = Mock(return_value="must not be used")
        result = context_personalization.build_chat_history_context(
            "query", "unknown", recall_func=recall
        )
        self.assertIsNone(result)
        recall.assert_not_called()

    def test_empty_query_fails_closed(self):
        recall = Mock(return_value="must not be used")
        self.assertIsNone(
            context_personalization.build_chat_history_context(
                "  ", "general", recall_func=recall
            )
        )
        recall.assert_not_called()

    def test_recall_failure_does_not_break_request_context(self):
        def fail(*args, **kwargs):
            raise OSError("history unavailable")
        self.assertIsNone(
            context_personalization.build_chat_history_context(
                "query", "general", recall_func=fail
            )
        )

    def test_history_context_is_bounded(self):
        recall = Mock(return_value="x" * 5000)
        result = context_personalization.build_chat_history_context(
            "query", "general", recall_func=recall, max_results=99
        )
        self.assertLessEqual(len(result), context_personalization.MAX_CHAT_CONTEXT_CHARS + 40)
        self.assertTrue(result.endswith("[контекст истории сокращён]"))

    def test_none_or_non_text_recall_is_ignored(self):
        for value in (None, {}, 123, "  "):
            with self.subTest(value=value):
                self.assertIsNone(
                    context_personalization.build_chat_history_context(
                        "query", "general", recall_func=Mock(return_value=value)
                    )
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
