"""Privacy routing tests for user-derived context blocks."""
import unittest

import context_manager


class PrivateContextPolicyTests(unittest.TestCase):
    def test_only_explicit_local_route_may_receive_private_context(self):
        self.assertTrue(context_manager.private_context_allowed("LOCAL"))

    def test_external_and_unknown_routes_fail_closed(self):
        for layer in ("API", "GEMINI", "REMOTE", "UNKNOWN", "", None, "local"):
            with self.subTest(layer=layer):
                self.assertFalse(context_manager.private_context_allowed(layer))


if __name__ == "__main__":
    unittest.main(verbosity=2)
