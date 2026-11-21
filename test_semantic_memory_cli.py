"""Tests for the local-only guarded semantic memory preview command."""
import os
import unittest
from unittest import mock

os.environ.setdefault("OPENROUTER_API_KEY", "test-only-placeholder")

import brain


class SemanticMemoryCliTests(unittest.TestCase):
    def test_preview_uses_local_provider_and_fact_frame_guard(self):
        provider = object()
        frames = object()
        with (
            mock.patch("memory.fact_frame_extractor.extract_fact_frames", frames),
            mock.patch(
                "memory.local_embedding_provider.LocalEmbeddingProvider",
                return_value=provider,
            ) as provider_factory,
            mock.patch(
                "memory.memory_core.preview_guarded_semantic_memory_consolidation",
                return_value=[],
            ) as preview,
        ):
            result = brain.run_guarded_semantic_memory_preview()

        self.assertEqual(result, [])
        provider_factory.assert_called_once_with()
        preview.assert_called_once_with(provider, frames, min_similarity=0.82)

    def test_injected_embedder_is_used_without_starting_a_provider(self):
        provider = object()
        frames = object()
        with (
            mock.patch("memory.fact_frame_extractor.extract_fact_frames", frames),
            mock.patch("memory.local_embedding_provider.LocalEmbeddingProvider") as factory,
            mock.patch(
                "memory.memory_core.preview_guarded_semantic_memory_consolidation",
                return_value=[{"entry_ids": ["a", "b"]}],
            ) as preview,
        ):
            result = brain.run_guarded_semantic_memory_preview(provider)

        self.assertEqual(len(result), 1)
        factory.assert_not_called()
        preview.assert_called_once_with(provider, frames, min_similarity=0.82)

    def test_command_reports_candidates_and_never_calls_apply(self):
        candidates = [{
            "similarity": 0.91,
            "candidate_policy": "guarded_semantic_review_only",
            "entries": [
                {"id": "12345678-aaaa", "text": "first synthetic fact"},
                {"id": "87654321-bbbb", "text": "second synthetic fact"},
            ],
            "guard_decisions": [{
                "decision": "CANDIDATE_FOR_REVIEW",
                "relation": "SAME_FACT",
                "reason_codes": ["SUBJECT_MATCH", "PREDICATE_MATCH"],
            }],
        }]
        with (
            mock.patch.object(brain, "run_guarded_semantic_memory_preview", return_value=candidates),
            mock.patch("builtins.print") as output,
            mock.patch("memory.memory_core.apply_memory_consolidation") as apply,
        ):
            result = brain.handle_semantic_memory_preview_command()

        self.assertEqual(result, {"ok": True, "candidate_count": 1})
        rendered = " ".join(str(call.args) for call in output.call_args_list)
        self.assertIn("first synthetic fact", rendered)
        self.assertIn("CANDIDATE_FOR_REVIEW", rendered)
        apply.assert_not_called()

    def test_provider_failure_is_reported_without_mutation(self):
        with (
            mock.patch.object(
                brain,
                "run_guarded_semantic_memory_preview",
                side_effect=RuntimeError("synthetic provider failure"),
            ),
            mock.patch("builtins.print") as output,
            mock.patch("memory.memory_core.apply_memory_consolidation") as apply,
        ):
            result = brain.handle_semantic_memory_preview_command()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "RuntimeError")
        apply.assert_not_called()
        self.assertNotIn("synthetic provider failure", str(output.call_args_list))


if __name__ == "__main__":
    unittest.main(verbosity=2)
