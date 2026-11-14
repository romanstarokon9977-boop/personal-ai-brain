"""Safety and contract tests for the Self-Improvement foundation."""
import os
import tempfile
import unittest
from unittest.mock import patch

from self_improvement.core import analyze_quality_events, build_improvement_proposal, collect_diagnostics
from self_improvement.store import ImprovementEventStore, SolutionLibrary


class DiagnosticsTests(unittest.TestCase):
    def test_golden_drift_is_reported_as_warning_not_silent_healthy(self):
        inspection = {
            "ok": True,
            "result": {
                "files": {"brain.py": {"exists": True, "readable": True}},
                "golden": {"brain.py": {"status": "DIFFERS"}},
                "git": {"available": True, "staged": ["brain.py"], "unstaged": [], "untracked": []},
                "diagnostics": {"warnings": [], "inconclusive": []},
            },
        }
        with patch("self_inspection.collect", return_value=inspection):
            with patch("module_manager.state_health", return_value="ok"):
                result = collect_diagnostics()
        self.assertEqual(result["status"], "WARNING")
        self.assertEqual(result["checks"]["golden:brain.py"], "WARNING")
        self.assertEqual(result["metrics"]["git_staged"], 1)
        self.assertFalse(result["mutations_performed"])

    def test_unavailable_inspection_is_unknown_not_healthy(self):
        with patch("self_inspection.collect", return_value={"ok": False, "result": None}):
            with patch("module_manager.state_health", return_value="unknown"):
                result = collect_diagnostics()
        self.assertEqual(result["status"], "WARNING")
        self.assertEqual(result["findings"][0]["severity"], "UNKNOWN")
        self.assertFalse(result["mutations_performed"])


class QualityAnalysisTests(unittest.TestCase):
    def test_repeated_failures_are_grouped_without_root_cause_claim(self):
        result = analyze_quality_events([
            {"category": "tool_timeout", "outcome": "fail"},
            {"category": "tool_timeout", "outcome": "fail"},
            {"category": "answer", "outcome": "uncertain"},
            {"category": "style", "outcome": "user_preference"},
            {"category": "answer", "outcome": "pass"},
        ])
        self.assertEqual(result["recurring_failures"], [{"category": "TOOL_TIMEOUT", "count": 2}])
        self.assertFalse(result["automatic_root_cause_claims"])
        self.assertEqual(result["outcomes"]["uncertain"], 1)
        self.assertEqual(result["outcomes"]["user_preference"], 1)

    def test_invalid_threshold_rejected(self):
        with self.assertRaisesRegex(ValueError, "INVALID_REPEAT_THRESHOLD"):
            analyze_quality_events([], 1)

    def test_invalid_events_rejected(self):
        with self.assertRaisesRegex(ValueError, "INVALID_EVENTS"):
            analyze_quality_events(None)


class ProposalTests(unittest.TestCase):
    def test_proposal_is_inert_and_requires_approval(self):
        proposal = build_improvement_proposal(
            {"code": "REPEATED_FAILURE", "severity": "WARNING", "evidence": "3 failures"},
            "Improve retry diagnostics", "Repeated timeout failures are observed.",
            ["execution_engine.py"], ["test_execution_engine.py"], "LOW",
        )
        self.assertEqual(proposal["status"], "PROPOSED")
        self.assertTrue(proposal["approval_required"])
        self.assertFalse(proposal["implementation_applied"])
        self.assertFalse(proposal["activation_allowed"])

    def test_invalid_proposal_rejected(self):
        with self.assertRaises(ValueError):
            build_improvement_proposal({}, "", "reason", ["x"], ["test"])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_event_store_records_only_explicit_sanitized_metadata(self):
        path = os.path.join(self.tmp.name, "events.json")
        store = ImprovementEventStore(path)
        event = store.add("timeout", "fail", "verifier", "HTTP_504")
        self.assertEqual(event["category"], "TIMEOUT")
        self.assertEqual(store.list_events(), [event])
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertNotIn("conversation", event)

    def test_invalid_event_rejected(self):
        store = ImprovementEventStore(os.path.join(self.tmp.name, "events.json"))
        with self.assertRaisesRegex(ValueError, "INVALID_EVENT_OUTCOME"):
            store.add("timeout", "maybe", "verifier")

    def test_solution_candidate_requires_test_evidence_to_verify(self):
        library = SolutionLibrary(os.path.join(self.tmp.name, "solutions.json"))
        candidate = library.add_candidate(
            "bounded_retry", "Transient read-only timeout",
            "Retry one explicitly allowlisted read-only operation.",
            ["Tool is explicitly read-only"], ["Never retry side-effecting tools"],
        )
        with self.assertRaisesRegex(ValueError, "VERIFICATION_EVIDENCE_REQUIRED"):
            library.verify(candidate["id"], {})
        verified = library.verify(candidate["id"], {"test_run": "CI run 123", "passed": True})
        self.assertEqual(verified["status"], "VERIFIED")
        self.assertEqual(library.list_solutions("VERIFIED")[0]["id"], candidate["id"])

    def test_solution_cannot_be_verified_after_failed_evidence(self):
        library = SolutionLibrary(os.path.join(self.tmp.name, "solutions.json"))
        candidate = library.add_candidate("x", "p", "a", [], [])
        with self.assertRaisesRegex(ValueError, "VERIFICATION_EVIDENCE_INSUFFICIENT"):
            library.verify(candidate["id"], {"test_run": "CI run 123", "passed": False})

    def test_duplicate_solution_names_rejected(self):
        library = SolutionLibrary(os.path.join(self.tmp.name, "solutions.json"))
        library.add_candidate("x", "p", "a", [], [])
        with self.assertRaisesRegex(ValueError, "DUPLICATE_SOLUTION"):
            library.add_candidate("X", "p", "a", [], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
