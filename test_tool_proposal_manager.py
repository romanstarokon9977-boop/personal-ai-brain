"""Safety tests for persistent, inert tool proposal lifecycle management."""
import os
import tempfile
import unittest

import tool_proposals
import tool_proposal_commands
from tool_proposal_manager import ToolProposalManager
from tool_registry import create_default_registry


class ToolProposalManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "proposals.json")
        self.manager = ToolProposalManager(self.path, create_default_registry())

    def proposal(self, name="sample_tool", permissions=None, risk="LOW"):
        return tool_proposals.create_tool_proposal(
            name, "Count text statistics", "text.statistics", risk,
            ["filesystem.read"] if permissions is None else permissions,
            ["Read-only; no file mutation"],
            ["Empty input returns zeros", "UTF-8 text is counted correctly"],
            execution_scope=("arguments_only" if permissions == [] else "external_resources"),
        )

    def test_factory_accepts_empty_permissions_but_rejects_invalid_types(self):
        proposal = self.proposal("permissionless_factory", [])
        self.assertEqual(proposal["required_permissions"], [])
        with self.assertRaisesRegex(ValueError, "INVALID_REQUIRED_PERMISSIONS"):
            tool_proposals.create_tool_proposal(
                "invalid_permissions", "Purpose", "capability", "LOW",
                None, ["constraint"], ["test"],
            )
        with self.assertRaisesRegex(ValueError, "ARGUMENTS_ONLY_REQUIRES_EMPTY_PERMISSIONS"):
            tool_proposals.create_tool_proposal(
                "scope_conflict", "Purpose", "capability", "LOW",
                ["filesystem.read"], ["constraint"], ["test"],
                execution_scope="arguments_only",
            )

    def test_create_persists_proposed_record_and_is_private(self):
        record = self.manager.create(self.proposal())
        self.assertEqual(record["status"], "PROPOSED")
        self.assertTrue(os.path.exists(self.path))
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        reopened = ToolProposalManager(self.path, create_default_registry())
        self.assertEqual(reopened.get(record["id"])["proposal"]["name"], "sample_tool")

    def test_list_filter_and_get_return_copies(self):
        record = self.manager.create(self.proposal())
        listed = self.manager.list_proposals("PROPOSED")
        listed[0]["proposal"]["name"] = "tampered"
        self.assertEqual(self.manager.get(record["id"])["proposal"]["name"], "sample_tool")
        self.assertEqual(self.manager.list_proposals("APPROVED"), [])

    def test_approve_and_reject_are_separate_metadata_only_decisions(self):
        first = self.manager.create(self.proposal("sample_one"))
        approved = self.manager.review(first["id"], "APPROVED", "Reviewed")
        self.assertEqual(approved["status"], "APPROVED")
        self.assertFalse(approved["proposal"]["implementation_applied"])
        self.assertFalse(approved["proposal"]["activation_allowed"])
        second = self.manager.create(self.proposal("sample_two"))
        rejected = self.manager.review(second["id"], "REJECTED")
        self.assertEqual(rejected["status"], "REJECTED")
        self.assertFalse(rejected["proposal"]["implementation_applied"])
        self.assertFalse(rejected["proposal"]["activation_allowed"])

    def test_duplicate_and_existing_registry_names_rejected(self):
        self.manager.create(self.proposal())
        with self.assertRaisesRegex(ValueError, "DUPLICATE_PROPOSAL_NAME"):
            self.manager.create(self.proposal())
        with self.assertRaisesRegex(ValueError, "TOOL_NAME_CONFLICT_OR_INVALID"):
            self.manager.create(self.proposal("read_file"))

    def test_permissionless_proposal_is_valid_and_remains_inert(self):
        proposal = self.proposal("permissionless_tool", [])
        self.assertEqual(proposal["required_permissions"], [])
        record = self.manager.create(proposal)
        self.assertEqual(record["status"], "PROPOSED")
        self.assertEqual(record["proposal"]["required_permissions"], [])
        self.assertTrue(record["proposal"]["approval_required"])
        self.assertFalse(record["proposal"]["implementation_applied"])
        self.assertFalse(record["proposal"]["activation_allowed"])

    def test_invalid_permission_container_and_entries_are_rejected(self):
        proposal = self.proposal("invalid_permission_type")
        proposal["required_permissions"] = None
        with self.assertRaisesRegex(ValueError, "UNKNOWN_REQUIRED_PERMISSION"):
            self.manager.create(proposal)
        proposal = self.proposal("blank_permission")
        proposal["required_permissions"] = [""]
        with self.assertRaisesRegex(ValueError, "UNKNOWN_REQUIRED_PERMISSION"):
            self.manager.create(proposal)
        proposal = self.proposal("scope_permission_conflict")
        proposal["execution_scope"] = "arguments_only"
        with self.assertRaisesRegex(ValueError, "ARGUMENTS_ONLY_REQUIRES_EMPTY_PERMISSIONS"):
            self.manager.create(proposal)

    def test_unknown_permissions_and_risk_understatement_rejected(self):
        with self.assertRaisesRegex(ValueError, "UNKNOWN_REQUIRED_PERMISSION"):
            self.manager.create(self.proposal("unknown_permission", ["not.a.permission"]))
        with self.assertRaisesRegex(ValueError, "PROPOSAL_RISK_BELOW_PERMISSION_RISK"):
            self.manager.create(self.proposal("risk_understated", ["shell"], "LOW"))

    def test_forbidden_capability_and_non_inert_flags_rejected(self):
        forbidden = self.proposal("forbidden_capability")
        forbidden["capability"] = "security.bypass"
        with self.assertRaisesRegex(ValueError, "FORBIDDEN_CAPABILITY"):
            self.manager.create(forbidden)
        applied = self.proposal("applied")
        applied["implementation_applied"] = True
        with self.assertRaisesRegex(ValueError, "IMPLEMENTATION_MUST_REMAIN_INERT"):
            self.manager.create(applied)

    def test_invalid_review_transitions_rejected(self):
        record = self.manager.create(self.proposal())
        with self.assertRaisesRegex(ValueError, "INVALID_REVIEW_DECISION"):
            self.manager.review(record["id"], "IMPLEMENTED")
        self.manager.review(record["id"], "APPROVED")
        with self.assertRaisesRegex(ValueError, "PROPOSAL_ALREADY_REVIEWED"):
            self.manager.review(record["id"], "REJECTED")

    def test_implementation_request_is_a_separate_approved_only_transition(self):
        proposed = self.manager.create(self.proposal("request_before_approval"))
        with self.assertRaisesRegex(ValueError, "IMPLEMENTATION_REQUIRES_APPROVED_PROPOSAL"):
            self.manager.request_implementation(proposed["id"])

        approved = self.manager.review(proposed["id"], "APPROVED")
        self.assertEqual(approved["status"], "APPROVED")
        queued = self.manager.request_implementation(proposed["id"], "Explicit terminal request")
        self.assertEqual(queued["status"], "IMPLEMENTATION_REQUESTED")
        self.assertTrue(queued["implementation_requested_at"])
        self.assertEqual(queued["implementation_request_note"], "Explicit terminal request")
        self.assertFalse(queued["proposal"]["implementation_applied"])
        self.assertFalse(queued["proposal"]["activation_allowed"])
        self.assertEqual(
            self.manager.list_proposals("IMPLEMENTATION_REQUESTED")[0]["id"],
            proposed["id"],
        )
        with self.assertRaisesRegex(ValueError, "IMPLEMENTATION_REQUIRES_APPROVED_PROPOSAL"):
            self.manager.request_implementation(proposed["id"])

    def test_rejected_proposal_cannot_enter_implementation_request_state(self):
        record = self.manager.create(self.proposal("rejected_request"))
        self.manager.review(record["id"], "REJECTED")
        with self.assertRaisesRegex(ValueError, "IMPLEMENTATION_REQUIRES_APPROVED_PROPOSAL"):
            self.manager.request_implementation(record["id"])
        self.assertEqual(self.manager.get(record["id"])["status"], "REJECTED")

    def test_terminal_command_requires_exact_confirmation_to_queue_request(self):
        record = self.manager.create(self.proposal("terminal_request"))
        self.manager.review(record["id"], "APPROVED")
        output = []

        handled = tool_proposal_commands.handle_proposal_command(
            f"предложение подготовить {record['id']}",
            self.manager,
            input_fn=lambda prompt: "да",
            output_fn=output.append,
        )
        self.assertTrue(handled)
        self.assertEqual(self.manager.get(record["id"])["status"], "APPROVED")
        self.assertTrue(any("Изменений нет" in line for line in output))

        output.clear()
        expected = f"ПОДГОТОВИТЬ РЕАЛИЗАЦИЮ {record['id']}"
        handled = tool_proposal_commands.handle_proposal_command(
            f"предложение подготовить {record['id']}",
            self.manager,
            input_fn=lambda prompt: expected,
            output_fn=output.append,
        )
        self.assertTrue(handled)
        queued = self.manager.get(record["id"])
        self.assertEqual(queued["status"], "IMPLEMENTATION_REQUESTED")
        self.assertFalse(queued["proposal"]["implementation_applied"])
        self.assertFalse(queued["proposal"]["activation_allowed"])
        self.assertTrue(any("Код не создан и не изменён" in line for line in output))

    def test_terminal_command_does_not_queue_unapproved_proposal(self):
        record = self.manager.create(self.proposal("unapproved_terminal_request"))
        output = []
        asked = []
        handled = tool_proposal_commands.handle_proposal_command(
            f"предложение подготовить {record['id']}",
            self.manager,
            input_fn=lambda prompt: asked.append(prompt) or f"ПОДГОТОВИТЬ РЕАЛИЗАЦИЮ {record['id']}",
            output_fn=output.append,
        )
        self.assertTrue(handled)
        self.assertEqual(asked, [])
        self.assertEqual(self.manager.get(record["id"])["status"], "PROPOSED")
        self.assertTrue(any("требуется статус APPROVED" in line for line in output))

    def test_corrupt_store_fails_closed(self):
        with open(self.path, "w", encoding="utf-8") as stream:
            stream.write("{broken")
        with self.assertRaises(ValueError):
            self.manager.list_proposals()

    def test_no_parent_creation_or_implicit_store_path(self):
        missing = os.path.join(self.tmp.name, "missing", "proposals.json")
        manager = ToolProposalManager(missing, create_default_registry())
        with self.assertRaisesRegex(ValueError, "STORE_PARENT_MISSING"):
            manager.create(self.proposal())
        self.assertFalse(os.path.exists(os.path.dirname(missing)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
