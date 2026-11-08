"""Runtime integration tests for Phase 4 skills, catalog, proposals and errors."""
import unittest

import autonomy_controller
import execution_engine
import skills_manager
import tool_catalog
import tool_proposals
import tool_registry


class SkillRuntimeIntegrationTests(unittest.TestCase):
    def test_task_selects_bounded_skill_context_as_untrusted_data(self):
        selected = skills_manager.select_skills("Нужно отладить Python код")
        self.assertEqual(selected[0]["id"], "programming")
        context = skills_manager.render_skill_context(selected)
        self.assertIn("недоверенные данные", context.lower())
        self.assertIn('"reference_instructions"', context)
        self.assertNotIn("The following skill text is task guidance", context)

    def test_oversized_skill_instructions_are_rejected(self):
        item = {
            "id": "programming", "name": "Code", "category": "programming",
            "description": "x", "triggers": ["python"],
            "instructions": "x" * (skills_manager.MAX_INSTRUCTIONS_CHARS + 1),
        }
        with self.assertRaises(ValueError):
            skills_manager._validate_skill(item)


class LiveToolCatalogTests(unittest.TestCase):
    def test_catalog_is_exposed_and_auto_authorized_read_only(self):
        registry = tool_registry.create_default_registry()
        item = tool_catalog.get_tool_entry(registry, "tool_catalog")
        self.assertIsNotNone(item)
        self.assertEqual(item["authorization"], "AUTO")
        self.assertFalse(item["requires_user_confirmation"])

    def test_tool_proposal_remains_confirmation_gated(self):
        registry = tool_registry.create_default_registry()
        decision = autonomy_controller.decide("propose_tool", {
            "name": "sample_tool",
        }, registry)
        self.assertEqual(decision.decision, autonomy_controller.AutonomyDecision.CONFIRM)
        proposal = tool_proposals.create_tool_proposal(
            "sample_tool", "Read sample data", "sample.read", "LOW",
            ["filesystem.read"], ["read-only"], ["returns expected result"],
        )
        self.assertFalse(proposal["implementation_applied"])
        self.assertFalse(proposal["activation_allowed"])


class SharedErrorTaxonomyTests(unittest.TestCase):
    def test_transient_read_only_errors_use_shared_classifier(self):
        self.assertEqual(
            execution_engine.classify_retry("read_file", "HTTP_503")["decision"],
            "RETRY_SAFE",
        )
        self.assertEqual(
            execution_engine.classify_retry("read_file", "CONNECTION_ERROR")["decision"],
            "STOP",
        )

    def test_side_effecting_and_unknown_tools_do_not_retry(self):
        self.assertEqual(
            execution_engine.classify_retry("write_file", "TIMEOUT")["decision"],
            "HUMAN_REQUIRED",
        )
        self.assertEqual(
            execution_engine.classify_retry("unknown", "HTTP_503")["decision"],
            "HUMAN_REQUIRED",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
