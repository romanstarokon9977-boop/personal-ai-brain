"""Runtime integration tests for Phase 4 skills, catalog, proposals and errors."""
import os
import tempfile
import unittest
from unittest import mock

# brain.py requires a non-empty key at import time; tests never make API calls.
os.environ.setdefault("OPENROUTER_API_KEY", "test-only-placeholder")

import brain
import autonomy_controller
import execution_engine
import skills_manager
import tool_catalog
import tool_proposals
import tool_registry
from tool_proposal_manager import ToolProposalManager


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



class Phase4NativeDispatchTests(unittest.TestCase):
    def test_phase4_tools_are_exposed_to_the_model(self):
        with mock.patch.object(brain.mcp_bridge, "mcp_is_alive", return_value=False), \
             mock.patch.object(brain.module_manager, "is_enabled", return_value=True):
            names = {
                item["function"]["name"]
                for item in brain.get_tool_definitions()
            }
        self.assertIn("tool_catalog", names)
        self.assertIn("propose_tool", names)

    def test_tool_catalog_dispatches_locally_not_through_mcp(self):
        with mock.patch.object(brain.module_manager, "get_status", return_value="enabled"), \
             mock.patch.object(
                 brain.mcp_bridge, "mcp_is_alive",
                 side_effect=AssertionError("Native tool was incorrectly routed to MCP"),
             ):
            result = brain.tool_execute("tool_catalog", {})
        self.assertTrue(result["ok"], result)
        self.assertIsInstance(result["result"], list)
        self.assertIn("tool_catalog", {item["name"] for item in result["result"]})

    def test_permissionless_proposal_dispatches_and_persists_inertly(self):
        params = {
            "name": "text_counter", "purpose": "Count supplied text",
            "capability": "text.statistics", "risk": "LOW",
            "execution_scope": "arguments_only",
            "required_permissions": [],
            "constraints": ["Analyze only the supplied string", "No external or system access"],
            "acceptance_tests": ["Empty input returns zero counts", "UTF-8 text is counted"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            manager = ToolProposalManager(
                os.path.join(tmp, "proposals.json"),
                tool_registry.create_default_registry(),
            )
            with mock.patch.object(brain, "TOOL_PROPOSAL_MANAGER", manager):
                with mock.patch.object(brain.module_manager, "get_status", return_value="enabled"):
                    with mock.patch.object(
                        brain.mcp_bridge, "mcp_is_alive",
                        side_effect=AssertionError("Native tool routed to MCP"),
                    ):
                        result = brain.tool_execute("propose_tool", params)
            # Read persisted metadata before TemporaryDirectory removes the store.
            persisted_records = manager.list_proposals()
        self.assertTrue(result["ok"], result)
        proposal = result["result"]["proposal"]
        self.assertEqual(proposal["execution_scope"], "arguments_only")
        self.assertEqual(proposal["required_permissions"], [])
        self.assertFalse(proposal["implementation_applied"])
        self.assertFalse(proposal["activation_allowed"])
        self.assertEqual(result["result"]["proposal_record"]["status"], "PROPOSED")
        self.assertEqual(persisted_records[0]["proposal"]["name"], "text_counter")

    def test_propose_tool_dispatches_locally_not_through_mcp(self):
        params = {
            "name": "sample_tool", "purpose": "Read sample data",
            "capability": "sample.read", "risk": "LOW",
            "execution_scope": "external_resources",
            "required_permissions": ["filesystem.read"],
            "constraints": ["read-only"],
            "acceptance_tests": ["returns expected result"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            manager = ToolProposalManager(
                os.path.join(tmp, "proposals.json"),
                tool_registry.create_default_registry(),
            )
            with mock.patch.object(brain, "TOOL_PROPOSAL_MANAGER", manager):
                with mock.patch.object(brain.module_manager, "get_status", return_value="enabled"):
                    with mock.patch.object(
                        brain.mcp_bridge, "mcp_is_alive",
                        side_effect=AssertionError("Native tool routed to MCP"),
                    ):
                        result = brain.tool_execute("propose_tool", params)
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["result"]["proposal"]["implementation_applied"])
        self.assertFalse(result["result"]["proposal"]["activation_allowed"])
        self.assertEqual(result["result"]["proposal_record"]["status"], "PROPOSED")
        self.assertIn("def sample_tool", result["result"]["inert_code_draft"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
