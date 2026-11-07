import unittest

import autonomy_controller
import tool_registry


class AutonomyPolicyTests(unittest.TestCase):
    def setUp(self):
        self.registry = tool_registry.create_default_registry()

    def test_allowlisted_low_risk_read_only_tool_is_automatic(self):
        result = autonomy_controller.decide(
            "read_file", {"path": "~/personal_ai_brain/README.md"}, self.registry
        )
        self.assertEqual(result.decision, autonomy_controller.AutonomyDecision.AUTO)
        self.assertEqual(result.reason, "ALLOWLISTED_READ_ONLY_LOW_RISK")

    def test_low_risk_mutating_or_stateful_tools_still_require_confirmation(self):
        for name, params in (
            ("briefing_set", {"action": "off"}),
            ("notify_user", {"title": "x", "message": "y"}),
            ("run_tests", {"scope": "targeted", "test": "test_brain.py"}),
            ("publish_cpa_gadget", {"title": "x", "product_url": "https://example.com"}),
        ):
            with self.subTest(name=name):
                result = autonomy_controller.decide(name, params, self.registry)
                self.assertEqual(
                    result.decision, autonomy_controller.AutonomyDecision.CONFIRM
                )

    def test_medium_high_and_critical_risks_require_confirmation(self):
        cases = (
            ("write_file", {"path": "~/personal_ai_brain/x", "content": "x"}),
            ("web_fetch", {"url": "https://example.com"}),
            ("shell", {"command": "pwd"}),
        )
        for name, params in cases:
            with self.subTest(name=name):
                result = autonomy_controller.decide(name, params, self.registry)
                self.assertEqual(
                    result.decision, autonomy_controller.AutonomyDecision.CONFIRM
                )

    def test_mcp_mutations_require_confirmation(self):
        for name, params in (
            ("move_file", {"source": "~/personal_ai_brain/a", "destination": "~/personal_ai_brain/b"}),
            ("create_directory", {"path": "~/personal_ai_brain/new"}),
            ("edit_file", {"path": "~/personal_ai_brain/a", "edits": []}),
        ):
            with self.subTest(name=name):
                result = autonomy_controller.decide(name, params, self.registry)
                self.assertEqual(
                    result.decision, autonomy_controller.AutonomyDecision.CONFIRM
                )

    def test_unknown_tool_is_blocked(self):
        result = autonomy_controller.decide("unregistered_tool", {}, self.registry)
        self.assertEqual(result.decision, autonomy_controller.AutonomyDecision.BLOCK)
        self.assertEqual(result.reason, "UNKNOWN_TOOL")

    def test_invalid_requests_and_registry_metadata_fail_closed(self):
        self.assertEqual(
            autonomy_controller.decide("", {}, self.registry).decision,
            autonomy_controller.AutonomyDecision.BLOCK,
        )
        self.assertEqual(
            autonomy_controller.decide("read_file", [], self.registry).decision,
            autonomy_controller.AutonomyDecision.BLOCK,
        )

        class InvalidRegistry:
            def get(self, name):
                return type("Definition", (), {
                    "capability": "filesystem.read",
                    "risk": "LOW",
                    "source": tool_registry.ToolSource.NATIVE,
                })()

        self.assertEqual(
            autonomy_controller.decide("read_file", {}, InvalidRegistry()).decision,
            autonomy_controller.AutonomyDecision.BLOCK,
        )

    def test_forbidden_capability_is_blocked(self):
        class ForbiddenRegistry:
            def get(self, name):
                return type("Definition", (), {
                    "capability": "security.bypass",
                    "risk": tool_registry.RiskLevel.LOW,
                    "source": tool_registry.ToolSource.NATIVE,
                })()

        result = autonomy_controller.decide("dangerous_tool", {}, ForbiddenRegistry())
        self.assertEqual(result.decision, autonomy_controller.AutonomyDecision.BLOCK)
        self.assertEqual(result.reason, "FORBIDDEN_CAPABILITY")


if __name__ == "__main__":
    unittest.main()
