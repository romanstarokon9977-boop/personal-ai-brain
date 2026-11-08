"""Runtime command tests for persistent, inert tool proposals."""
import os
import tempfile
import unittest

from tool_proposal_commands import handle_proposal_command
from tool_proposal_manager import ToolProposalManager
from tool_proposals import create_tool_proposal
from tool_registry import create_default_registry


class ProposalCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.manager = ToolProposalManager(os.path.join(self.tmp.name, "proposals.json"), create_default_registry())
        self.record = self.manager.create(create_tool_proposal(
            "sample_tool", "Count text statistics", "text.statistics", "LOW",
            ["filesystem.read"], ["read-only; no side effects"],
            ["empty input returns zero", "UTF-8 is handled"],
        ))
        self.output = []

    def run_command(self, command, answer=None):
        handled = handle_proposal_command(
            command, self.manager, input_fn=lambda _prompt: answer,
            output_fn=self.output.append,
        )
        self.assertTrue(handled)

    def test_list_and_details_are_read_only(self):
        self.run_command("предложения")
        self.assertTrue(any(self.record["short_id"] in line for line in self.output))
        self.output.clear()
        self.run_command("предложение " + self.record["short_id"])
        self.assertTrue(any("Реализация применена: НЕТ" in line for line in self.output))
        self.assertEqual(self.manager.get(self.record["id"])["status"], "PROPOSED")

    def test_approval_requires_exact_direct_confirmation(self):
        self.run_command("предложение одобрить " + self.record["id"], "да")
        self.assertEqual(self.manager.get(self.record["id"])["status"], "PROPOSED")
        self.assertTrue(any("Изменений нет" in line for line in self.output))
        self.output.clear()
        self.run_command("предложение одобрить " + self.record["id"], "ОДОБРИТЬ " + self.record["short_id"])
        approved = self.manager.get(self.record["id"])
        self.assertEqual(approved["status"], "APPROVED")
        self.assertFalse(approved["proposal"]["implementation_applied"])
        self.assertFalse(approved["proposal"]["activation_allowed"])

    def test_rejection_requires_exact_direct_confirmation(self):
        self.run_command("предложение отклонить " + self.record["id"], "ОТКЛОНИТЬ " + self.record["short_id"])
        rejected = self.manager.get(self.record["id"])
        self.assertEqual(rejected["status"], "REJECTED")
        self.assertFalse(rejected["proposal"]["implementation_applied"])
        self.assertFalse(rejected["proposal"]["activation_allowed"])

    def test_name_reference_and_ambiguous_fragment(self):
        self.run_command("предложение sample_tool")
        self.assertTrue(any("Инструмент: sample_tool" in line for line in self.output))
        second = self.manager.create(create_tool_proposal(
            "sample_task", "Another task", "task.sample", "LOW",
            ["filesystem.read"], ["read-only"], ["returns expected result"],
        ))
        self.output.clear()
        asked = []
        handle_proposal_command(
            "предложение sample", self.manager,
            input_fn=lambda prompt: asked.append(prompt) or "ОДОБРИТЬ T-001",
            output_fn=self.output.append,
        )
        self.assertEqual(asked, [])
        self.assertTrue(any("несколько предложений" in line.lower() for line in self.output))
        self.assertTrue(any("T-001" in line for line in self.output))
        self.assertTrue(any(second["short_id"] in line for line in self.output))
        self.assertEqual(self.manager.get(self.record["id"])["status"], "PROPOSED")

    def test_uuid_alias_uses_short_id_for_confirmation(self):
        self.run_command(
            "предложение одобрить " + self.record["id"],
            "ОДОБРИТЬ " + self.record["short_id"],
        )
        self.assertEqual(self.manager.get(self.record["id"])["status"], "APPROVED")

    def test_unknown_id_does_not_change_store(self):
        self.run_command("предложение одобрить unknown")
        self.assertTrue(any("не найдено" in line for line in self.output))
        self.assertEqual(self.manager.get(self.record["id"])["status"], "PROPOSED")

    def test_review_commands_are_not_model_tools(self):
        import brain
        names = {item["function"]["name"] for item in brain.get_tool_definitions()}
        self.assertNotIn("review_tool_proposal", names)
        self.assertNotIn("approve_tool_proposal", names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
