"""Deterministic unit tests for verifier.verify_text_response."""

import unittest

from verifier import verify_text_response


def category(value):
    return verify_text_response(value)["category"]


class VerifyTextResponseTests(unittest.TestCase):
    def test_empty(self):
        for value in ("", "   \n\t  ", None):
            with self.subTest(value=value):
                self.assertEqual(category(value), "empty")
        self.assertIs(verify_text_response("")["ok"], False)

    def test_malformed(self):
        values = (
            "Traceback (most recent call last): ...",
            "HTTP_500", "HTTP_429", "HTTP_504", "HTTP_500.",
            "LOCAL_HTTP_503", "LOCAL_HTTP_503.",
            "LOCAL_SERVICE_UNAVAILABLE",
            "<error> something bad</error>",
            "ALL_MODELS_IN_COOLDOWN", "NO_MODEL_SELECTED",
        )
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(category(value), "malformed")
        self.assertIs(verify_text_response("HTTP_500")["ok"], False)

    def test_incomplete(self):
        values = (
            "&#96;&#96;&#96;python\nprint(1)",
            "Начало ответа… <truncated>",
            "Текст [cut]",
        )
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(category(value), "incomplete")
        self.assertIs(verify_text_response("&#96;&#96;&#96;python\nx=1")["ok"], False)

    def test_normal_text_with_ellipsis_or_open_ending_is_valid(self):
        values = (
            "Хорошо, подумаю…",
            "Я пошёл в магазин и",
            "Это ответ без точки",
            "&#96;&#96;&#96;python\nprint(1)\n&#96;&#96;&#96;",
            '{"key": "value"',
        )
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(category(value), "valid")

    def test_suspicious(self):
        values = (
            "🔧 TOOL BRIDGE | итерация 1/5",
            "📐 Context Manager [API]: 100→50",
            "lock_type = MANUAL",
            "model_lock = qwen3",
            "cooldown_until = 1234567890",
            "empty_streak = 2",
            "rate_429 = 5",
            "EMPTY_STREAK_COOLDOWN",
        )
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(category(value), "suspicious")
        self.assertIs(verify_text_response("lock_type = MANUAL")["ok"], False)

    def test_valid_responses(self):
        values = (
            "Привет! Как я могу помочь?",
            "Хорошо, я понял задачу.",
            "Это ответ без точки",
            "Хорошо, подумаю…",
            "&#96;&#96;&#96;python\nx=1\n&#96;&#96;&#96;\nГотово.",
        )
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(category(value), "valid")
        self.assertIs(verify_text_response("Привет!")["ok"], True)

    def test_technical_terms_inside_explanations_are_valid(self):
        values = (
            "В прошлый раз ошибка была HTTP_500, но я её исправил.",
            "HTTP_504 означает, что сервер не ответил вовремя.",
            "При прошлом сбое появился LOCAL_HTTP_503, это значит сервер вернул 503.",
            "NO_MODEL_SELECTED означает, что модель не выбрана.",
            "При запуске возник Traceback, но я его починил.",
            "LOCAL_SERVICE_UNAVAILABLE — это код ошибки, который возвращает Brain.",
            "Поле lock_type принимает значения AUTO или MANUAL.",
            "Внутри Brain используется model_lock для фиксации модели.",
            "Поле cooldown_until хранит время окончания кулдауна.",
            "empty_streak считает пустые ответы подряд.",
        )
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(category(value), "valid")


if __name__ == "__main__":
    unittest.main(verbosity=2)
