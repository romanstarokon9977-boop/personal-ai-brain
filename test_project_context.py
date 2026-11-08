import unittest

import project_context


class TestProjectContextDomains(unittest.TestCase):
    def test_all_required_domains_are_available(self):
        self.assertEqual(set(project_context.DOMAINS),
                         {"general", "brain", "development", "learning", "income", "personal"})

    def test_russian_and_english_aliases_resolve(self):
        cases = {"Brain": "brain", "разработка": "development",
                 "учёба": "learning", "заработок": "income",
                 "личные задачи": "personal", "общий": "general"}
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(project_context.normalize_domain(value), expected)

    def test_unknown_or_non_string_domain_is_rejected(self):
        self.assertIsNone(project_context.normalize_domain("unknown"))
        self.assertIsNone(project_context.normalize_domain("../development"))
        self.assertIsNone(project_context.normalize_domain(None))

    def test_domain_listing_is_stable_and_descriptive(self):
        domains = project_context.list_domains()
        self.assertEqual([item["id"] for item in domains],
                         ["general", "brain", "development", "learning", "income", "personal"])
        self.assertTrue(all(item["label"] for item in domains))


if __name__ == "__main__":
    unittest.main(verbosity=2)
