"""Privacy routing tests for user-derived context blocks."""
import os
import unittest
from unittest import mock

os.environ.setdefault("OPENROUTER_API_KEY", "test-only-placeholder")

import brain
import context_manager


class PrivateContextPolicyTests(unittest.TestCase):
    def test_only_explicit_local_route_may_receive_private_context(self):
        self.assertTrue(context_manager.private_context_allowed("LOCAL"))

    def test_external_and_unknown_routes_fail_closed(self):
        for layer in ("API", "GEMINI", "REMOTE", "UNKNOWN", "", None, "local"):
            with self.subTest(layer=layer):
                self.assertFalse(context_manager.private_context_allowed(layer))

    def test_external_route_never_loads_or_attaches_private_context(self):
        with (
            mock.patch.object(brain, "get_relevant_memory") as memory,
            mock.patch.object(brain.context_personalization, "build_chat_history_context") as history,
            mock.patch.object(brain.skills_manager, "select_skills") as select_skills,
        ):
            messages = brain._build_private_context_messages(
                "API", "private query", "personal", "active-chat"
            )

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["name"], "privacy_boundary")
        self.assertNotIn("private query", messages[0]["content"])
        memory.assert_not_called()
        history.assert_not_called()
        select_skills.assert_not_called()

    def test_local_route_loads_all_private_context_blocks(self):
        with (
            mock.patch.object(brain, "get_relevant_memory", return_value="memory secret") as memory,
            mock.patch.object(
                brain.context_personalization,
                "build_chat_history_context",
                return_value="chat secret",
            ) as history,
            mock.patch.object(brain.skills_manager, "select_skills", return_value=[{"id": "private"}]) as select_skills,
            mock.patch.object(brain.skills_manager, "render_skill_context", return_value="skill secret"),
        ):
            messages = brain._build_private_context_messages(
                "LOCAL", "private query", "personal", "active-chat"
            )

        self.assertEqual(
            {item["name"] for item in messages},
            {"memory", "chat_recall", "skill_guidance"},
        )
        memory.assert_called_once_with("private query")
        history.assert_called_once_with(
            "private query",
            context_domain="personal",
            active_chat_id="active-chat",
        )
        select_skills.assert_called_once_with("private query")

    def test_dispatch_boundary_strips_private_blocks_on_remote_fallback(self):
        source = [
            {"role": "system", "name": "memory", "content": "memory secret"},
            {"role": "system", "name": "chat_recall", "content": "chat secret"},
            {"role": "system", "name": "skill_guidance", "content": "skill secret"},
            {"role": "user", "content": "question"},
        ]
        result = context_manager.enforce_private_context_boundary(source, "API")
        names = {item.get("name") for item in result}
        self.assertTrue({"memory", "chat_recall", "skill_guidance"}.isdisjoint(names))
        self.assertIn("privacy_boundary", names)
        self.assertEqual(result[-2], source[-1])
        self.assertEqual(len(source), 4)

    def test_dispatch_boundary_preserves_private_blocks_for_local_route(self):
        source = [
            {"role": "system", "name": "memory", "content": "memory secret"},
            {"role": "user", "content": "question"},
        ]
        result = context_manager.enforce_private_context_boundary(source, "LOCAL")
        self.assertEqual(result, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
