"""Tests for Phase 4 infrastructure modules; no external services or writes."""
import json
import os
import tempfile
import unittest

import skills_manager
import tool_catalog
import tool_proposals
import mcp_server_catalog
import tool_error_handler
from tool_registry import create_default_registry


class SkillsManagerTests(unittest.TestCase):
    def test_default_skills_load_and_match(self):
        skills = skills_manager.list_skills()
        self.assertEqual({item["id"] for item in skills}, {"programming", "data_analysis", "research", "documents"})
        selected = skills_manager.select_skills("Помоги отладить Python код")
        self.assertEqual(selected[0]["id"], "programming")
        self.assertIn("not authorization", skills_manager.render_skill_context(selected).lower())

    def test_empty_task_and_invalid_limit(self):
        self.assertEqual(skills_manager.select_skills(" "), [])
        self.assertEqual(skills_manager.select_skills("python", limit=0), [])

    def test_invalid_schema_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "bad.json"), "w", encoding="utf-8") as stream:
                json.dump({"id": "bad"}, stream)
            self.assertEqual(skills_manager.list_skills(tmp), [])


class ToolCatalogTests(unittest.TestCase):
    def test_catalog_reflects_existing_authorization_policy(self):
        by_name = {item["name"]: item for item in tool_catalog.build_tool_catalog(create_default_registry())}
        self.assertEqual(by_name["git_inspect"]["authorization"], "AUTO")
        self.assertEqual(by_name["shell"]["authorization"], "CONFIRM")
        self.assertTrue(by_name["shell"]["requires_user_confirmation"])

    def test_unknown_registry_fails_closed(self):
        self.assertEqual(tool_catalog.build_tool_catalog(None), [])


class ToolProposalTests(unittest.TestCase):
    def _proposal(self):
        return tool_proposals.create_tool_proposal(
            "sample_tool", "Read a sample", "sample.read", "LOW",
            ["filesystem.read"], ["Read-only; no network"], ["Returns expected schema"],
        )

    def test_proposal_never_activates_or_applies(self):
        proposal = self._proposal()
        self.assertEqual(proposal["status"], "PROPOSED")
        self.assertTrue(proposal["approval_required"])
        self.assertFalse(proposal["implementation_applied"])
        self.assertFalse(proposal["activation_allowed"])

    def test_stub_is_inert(self):
        stub = tool_proposals.render_python_stub(self._proposal())
        self.assertIn("NOT_IMPLEMENTED", stub)
        self.assertNotIn("subprocess", stub)

    def test_invalid_name_and_risk_rejected(self):
        with self.assertRaises(ValueError):
            tool_proposals.create_tool_proposal("../bad", "x", "x", "LOW", ["p"], ["c"], ["t"])
        with self.assertRaises(ValueError):
            tool_proposals.create_tool_proposal("sample_tool", "x", "x", "UNKNOWN", ["p"], ["c"], ["t"])


class MCPServerCatalogTests(unittest.TestCase):
    def test_registration_is_inert_and_disabled(self):
        catalog = mcp_server_catalog.MCPServerCatalog()
        catalog.register(mcp_server_catalog.MCPServerSpec(
            "local_fs", "Local filesystem", "stdio", "node",
            ("server.js", "/safe/root"), ("filesystem.read",), False,
        ))
        item = catalog.list_servers()[0]
        self.assertFalse(item["enabled"])
        self.assertFalse(item["started"])
        self.assertTrue(item["activation_requires_confirmation"])

    def test_enabled_server_registration_is_rejected(self):\n        catalog = mcp_server_catalog.MCPServerCatalog()\n        with self.assertRaises(ValueError):\n            catalog.register(mcp_server_catalog.MCPServerSpec("active_fs", "FS", "stdio", "node", (), (), True))\n\n    def test_duplicate_and_unsupported_transport_rejected(self):
        catalog = mcp_server_catalog.MCPServerCatalog()
        spec = mcp_server_catalog.MCPServerSpec("local_fs", "FS", "stdio", "node", (), (), False)
        catalog.register(spec)
        with self.assertRaises(ValueError):
            catalog.register(spec)
        with self.assertRaises(ValueError):
            catalog.register(mcp_server_catalog.MCPServerSpec("remote", "Remote", "http", "node", (), (), False))


class ToolErrorHandlerTests(unittest.TestCase):
    def test_transient_read_only_can_retry(self):
        result = tool_error_handler.classify_tool_error("MCP CALL TIMEOUT", "read_file")
        self.assertEqual(result["category"], "TIMEOUT")
        self.assertTrue(result["retryable"])

    def test_side_effecting_and_unknown_tools_never_retry(self):
        self.assertFalse(tool_error_handler.classify_tool_error("HTTP_503", "write_file", True)["retryable"])
        self.assertFalse(tool_error_handler.classify_tool_error("HTTP_503", "unknown_tool")["retryable"])

    def test_rate_limit_on_side_effect_is_not_advised_to_retry(self):\n        result = tool_error_handler.classify_tool_error("429 RATE_LIMIT", "write_file", True)\n        self.assertFalse(result["retryable"])\n        self.assertEqual(result["recovery"], "STOP_AND_REPORT")\n\n    def test_auth_and_protocol_errors_stop(self):
        self.assertEqual(tool_error_handler.classify_tool_error("403 Forbidden")["category"], "AUTHORIZATION")
        self.assertFalse(tool_error_handler.classify_tool_error("MCP_PROTOCOL_ERROR")["retryable"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
