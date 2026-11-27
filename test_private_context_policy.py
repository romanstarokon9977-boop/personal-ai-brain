"""Privacy routing tests for user-derived context blocks."""
import os
import unittest
from unittest import mock

os.environ.setdefault("OPENROUTER_API_KEY", "test-only-placeholder")

import brain
import context_manager
from memory import memory_core


class PrivateContextPolicyTests(unittest.TestCase):
    def test_only_explicit_local_route_may_receive_private_context(self):
        self.assertTrue(context_manager.private_context_allowed("LOCAL"))

    def test_external_and_unknown_routes_fail_closed(self):
        for layer in ("API", "GEMINI", "REMOTE", "UNKNOWN", "", None, "local"):
            with self.subTest(layer=layer):
                self.assertFalse(context_manager.private_context_allowed(layer))

    def test_natural_language_saved_memory_question_is_handled_locally(self):
        question = "Какая метка runtime-проверки была сохранена?"
        with (
            mock.patch.object(brain, "find_memory", return_value="Метка runtime-проверки: ORBIT-41") as lookup,
            mock.patch("builtins.print"),
        ):
            handled = brain.handle_explicit_memory_recall_request(question)

        self.assertTrue(handled)
        lookup.assert_called_once_with(question, limit=1)

    def test_explicit_memory_id_request_is_resolved_locally(self):
        question = "Найди в сохранённой памяти запись с ID f2e1b9f8."
        with (
            mock.patch.object(brain, "find_memory", return_value="Метка runtime-проверки: ORBIT-41") as lookup,
            mock.patch("builtins.print"),
        ):
            handled = brain.handle_explicit_memory_recall_request(question)

        self.assertTrue(handled)
        lookup.assert_called_once_with("f2e1b9f8", limit=1)

    def test_memory_core_returns_only_matching_record_for_short_id(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp_dir:
            memory_path = str(Path(temp_dir) / "brain_memory.json")
            with mock.patch.object(memory_core, "MEMORY_FILE", memory_path):
                memory_core._save_raw({
                    "version": 2,
                    "entries": [{
                        "id": "f2e1b9f8-0000-4000-8000-000000000001",
                        "timestamp": "2026-11-26 15:00:00",
                        "text": "Метка runtime-проверки: ORBIT-41",
                        "category": "facts",
                        "importance": 5,
                        "source": "user",
                        "status": "active",
                        "memory_type": "permanent",
                    }],
                })
                result = memory_core.find_memory("f2e1b9f8")

        self.assertIn("ORBIT-41", result)
        self.assertIn("f2e1b9f8", result)
        self.assertNotIn("Запись с ID", result)

    def test_non_memory_question_is_not_intercepted(self):
        self.assertIsNone(brain._explicit_memory_recall_query("Объясни, как работает маршрутизатор."))

    def test_remote_dispatch_blocks_credential_like_user_input(self):
        messages = [{
            "role": "user",
            "content": "Please debug this config: OPENROUTER_API_KEY=sk-or-v1-123456789012345678901234",
        }]
        with mock.patch.object(brain, "ask_model") as ask:
            ok, result = brain.controller_execute(
                {"model": "remote-test", "layer": "API"}, messages
            )
        self.assertFalse(ok)
        self.assertEqual(result["error"], "SENSITIVE_DATA_BLOCKED")
        ask.assert_not_called()

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

    def test_local_route_failure_cannot_fallback_to_external_provider(self):
        for fallback_layer in ("API", "GEMINI", "UNKNOWN"):
            with self.subTest(fallback_layer=fallback_layer):
                with mock.patch.dict(
                    brain.state,
                    {"model_lock": "cloud-model", "model_lock_type": "AUTO", "model_lock_layer": fallback_layer},
                    clear=False,
                ):
                    with (
                        mock.patch.object(
                            brain,
                            "run_with_tools",
                            return_value=(False, {"error": "LOCAL_SERVICE_UNAVAILABLE", "model": "local-model"}),
                        ) as run,
                        mock.patch.object(
                            brain,
                            "controller_route",
                            return_value={"model": "cloud-model", "layer": fallback_layer},
                        ) as route,
                        mock.patch.object(brain, "get_model_stats", return_value={}),
                        mock.patch("builtins.print"),
                    ):
                        ok, result = brain.execute_with_fallback(
                            "general",
                            {"model": "local-model", "layer": "LOCAL"},
                            [{"role": "user", "content": "private request"}],
                        )
                    self.assertIsNone(brain.state.get("model_lock"))
                    self.assertIsNone(brain.state.get("model_lock_type"))
                    self.assertIsNone(brain.state.get("model_lock_layer"))

                self.assertFalse(ok)
                self.assertEqual(result["error"], "LOCAL_TO_REMOTE_FALLBACK_BLOCKED")
                self.assertEqual(result["fallback_layer"], fallback_layer)
                run.assert_called_once()
                route.assert_called_once_with("general")

    def test_local_route_may_retry_another_local_model(self):
        with (
            mock.patch.object(
                brain,
                "run_with_tools",
                side_effect=[
                    (False, {"error": "LOCAL_SERVICE_UNAVAILABLE", "model": "local-a"}),
                    (True, {"answer": "local retry", "model": "local-b"}),
                ],
            ) as run,
            mock.patch.object(
                brain,
                "controller_route",
                return_value={"model": "local-b", "layer": "LOCAL"},
            ),
            mock.patch.object(brain, "get_model_stats", return_value={}),
        ):
            ok, result = brain.execute_with_fallback(
                "general",
                {"model": "local-a", "layer": "LOCAL"},
                [{"role": "user", "content": "private request"}],
            )

        self.assertTrue(ok)
        self.assertEqual(result["answer"], "local retry")
        self.assertEqual(run.call_count, 2)

    def test_dispatch_boundary_preserves_private_blocks_for_local_route(self):
        source = [
            {"role": "system", "name": "memory", "content": "memory secret"},
            {"role": "user", "content": "question"},
        ]
        result = context_manager.enforce_private_context_boundary(source, "LOCAL")
        self.assertEqual(result, source)

    def test_dispatch_boundary_strips_legacy_unnamed_private_context(self):
        source = [
            {"role": "system", "content": "Контекст профиля и среды: private secret"},
            {"role": "system", "content": "Воспоминания из прошлых обсуждений:\nprivate chat"},
            {"role": "system", "content": "Ниже приведены справочные материалы выбранных навыков"},
            {"role": "user", "content": "question"},
        ]
        result = context_manager.enforce_private_context_boundary(source, "GEMINI")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["role"], "user")
        self.assertEqual(result[1]["name"], "privacy_boundary")
        self.assertNotIn("private secret", str(result))
        self.assertNotIn("private chat", str(result))

    def test_controller_dispatch_strips_private_context_before_remote_api_call(self):
        source = [
            {"role": "system", "name": "memory", "content": "memory secret"},
            {"role": "system", "name": "chat_recall", "content": "chat secret"},
            {"role": "system", "name": "skill_guidance", "content": "skill secret"},
            {"role": "user", "content": "ordinary request"},
        ]
        captured = {}

        def fake_prepare(messages, layer):
            captured["messages"] = list(messages)
            return messages, {
                "input_size": 1,
                "output_size": 1,
                "budget": 24000,
                "used_pct": 0,
                "messages_in": len(messages),
                "messages_out": len(messages),
                "trimmed": False,
            }

        with (
            mock.patch.object(brain.context_manager, "prepare_context", side_effect=fake_prepare),
            mock.patch.object(brain, "ask_model", return_value=(True, {"answer": "ok"})),
            mock.patch("builtins.open", side_effect=OSError("test: no log write")),
        ):
            ok, result = brain.controller_execute(
                {"model": "remote-test", "layer": "API"}, source
            )

        self.assertTrue(ok, result)
        names = {item.get("name") for item in captured["messages"]}
        self.assertTrue({"memory", "chat_recall", "skill_guidance"}.isdisjoint(names))
        self.assertIn("privacy_boundary", names)
        self.assertIn("ordinary request", str(captured["messages"]))
        self.assertNotIn("memory secret", str(captured["messages"]))
        self.assertNotIn("chat secret", str(captured["messages"]))
        self.assertNotIn("skill secret", str(captured["messages"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
