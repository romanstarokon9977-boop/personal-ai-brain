import sys
import os
import unittest
from brain import tool_execute

class TestCPABridgeIntegration(unittest.TestCase):

    def test_successful_preview(self):
        params = {
            "title": "Умная колонка",
            "price": "4 990",
            "description": "Отличный звук",
            "product_url": "https://market.yandex.ru/product/123"
        }
        res = tool_execute("publish_cpa_gadget", params)
        self.assertTrue(res["ok"])
        self.assertIsNotNone(res["result"])
        self.assertIsNotNone(res["post_text"])
        self.assertIsNone(res["error"])

    def test_validation_error(self):
        params = {
            "title": "",
            "price": "100",
            "description": "Описание",
            "product_url": "ftp://invalid-url.com"
        }
        res = tool_execute("publish_cpa_gadget", params)
        self.assertFalse(res["ok"])
        self.assertIsNotNone(res["error"])

    def test_dry_run_override_impossible(self):
        # Передача dry_run=False в параметрах игнорируется диспетчером
        params = {
            "title": "Тестовый гаджет",
            "price": "100",
            "description": "Описание",
            "product_url": "https://market.yandex.ru/product/123",
            "dry_run": False
        }
        res = tool_execute("publish_cpa_gadget", params)
        # Так как диспетчер принудительно передает dry_run=True, валидация должна пройти успехом в режиме dry-run
        self.assertTrue(res["ok"])
        self.assertIn("[DRY_RUN SUCCESS]", str(res["result"]))

if __name__ == "__main__":
    unittest.main()
