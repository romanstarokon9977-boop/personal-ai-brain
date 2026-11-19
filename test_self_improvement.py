"""Safety and contract tests for the Self-Improvement foundation."""
import base64
import os
import tempfile
import unittest
from unittest.mock import patch

from self_improvement.core import analyze_quality_events, build_improvement_proposal, collect_diagnostics
from self_improvement.store import ImprovementEventStore, SolutionLibrary, ImprovementProposalStore
from self_improvement.commands import record_answer_feedback, build_quality_report, manage_solution_library, manage_module_improvements
from self_improvement.evidence import validate_github_actions_evidence


class ExternalEvidenceTests(unittest.TestCase):
    def _api(self, overrides=None):
        sha = "d" * 40
        workflow_text = "test_self_improvement.py\\npython -m unittest -v \"${test_module}\""
        content = {"type": "file", "path": ".github/workflows/python-ci.yml", "sha": "blob-trusted",
                   "encoding": "base64", "content": base64.b64encode(workflow_text.encode()).decode()}
        test_text = "class ExternalEvidenceTests:\n    def test_external_evidence(self):\n        pass"
        test_content = {"type": "file", "path": "test_self_improvement.py", "sha": "test-blob",
                        "encoding": "base64", "content": base64.b64encode(test_text.encode()).decode()}
        responses = {
            "/repos/romanstarokon9977-boop/personal-ai-brain": {
                "id": 1381206490, "full_name": "romanstarokon9977-boop/personal-ai-brain"},
            "/repos/romanstarokon9977-boop/personal-ai-brain/actions/workflows/python-ci.yml": {
                "id": 77, "path": ".github/workflows/python-ci.yml"},
            "/repos/romanstarokon9977-boop/personal-ai-brain/contents/.github/workflows/python-ci.yml?ref=main": content,
            f"/repos/romanstarokon9977-boop/personal-ai-brain/contents/.github/workflows/python-ci.yml?ref={sha}": content,
            f"/repos/romanstarokon9977-boop/personal-ai-brain/contents/test_self_improvement.py?ref={sha}": test_content,
            f"/repos/romanstarokon9977-boop/personal-ai-brain/actions/workflows/77/runs?head_sha={sha}&per_page=100": {
                "workflow_runs": [{
                    "id": 901, "workflow_id": 77, "head_sha": sha, "event": "push",
                    "head_branch": "feat/p6-6-test", "status": "completed", "conclusion": "success",
                    "run_attempt": 1, "html_url": "https://github.com/example/run/901",
                    "updated_at": "2026-11-19T12:00:00Z"}]},
            "/repos/romanstarokon9977-boop/personal-ai-brain/actions/runs/901/jobs?per_page=100": {
                "jobs": [{"id": 902, "name": "Python 3.11 checks",
                          "status": "completed", "conclusion": "success",
                          "steps": [
                              {"name": "Compile project modules and test modules", "status": "completed", "conclusion": "success"},
                              {"name": "Run isolated unittest modules", "status": "completed", "conclusion": "success"}]}]},
        }
        if overrides:
            responses.update(overrides)
        return sha, lambda path: responses.get(path, {"_error": "unexpected API path: " + path})

    def test_exact_commit_and_required_job_are_verified(self):
        sha, api = self._api()
        result = validate_github_actions_evidence(
            "romanstarokon9977-boop/personal-ai-brain", sha,
            "test_self_improvement.py::test_external_evidence", api_reader=api)
        self.assertEqual(result["decision"], "VERIFIED")
        self.assertEqual(result["run_id"], 901)
        self.assertEqual(result["job_conclusion"], "success")

    def test_workflow_definition_mismatch_is_rejected(self):
        sha, api = self._api()
        original = api
        def changed(path):
            value = original(path)
            if "ref=" + sha in path and isinstance(value, dict) and "sha" in value:
                return {**value, "sha": "different-blob"}
            return value
        result = validate_github_actions_evidence(
            "romanstarokon9977-boop/personal-ai-brain", sha,
            "test_self_improvement.py::test_external_evidence", api_reader=changed)
        self.assertEqual(result["decision"], "REJECTED")
        self.assertEqual(result["reason"], "WORKFLOW_DEFINITION_DIFFERS_FROM_TRUSTED_MAIN")

    def test_caller_cannot_select_untrusted_repository(self):
        result = validate_github_actions_evidence(
            "attacker/example", "d" * 40, "test_self_improvement.py::test_case",
            api_reader=lambda path: {})
        self.assertEqual(result["decision"], "REJECTED")
        self.assertEqual(result["reason"], "UNTRUSTED_REPOSITORY")


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


class RuntimeCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.memory_file = os.path.join(self.tmp.name, "brain_memory.json")

    def test_explicit_feedback_is_persisted_without_conversation_text(self):
        event = record_answer_feedback(self.memory_file, "ACCURACY", "fail", "FACT_MISMATCH")
        self.assertEqual(event["source"], "user_feedback")
        self.assertEqual(event["category"], "ACCURACY")
        self.assertNotIn("text", event)
        report = build_quality_report(self.memory_file)
        self.assertEqual(report["recurring_failures"], [])
        self.assertEqual(report["outcomes"]["fail"], 1)
        self.assertEqual(report["storage"], {"status": "READ_OK", "event_count": 1})
        self.assertEqual(report["events"][0]["evidence_code"], "FACT_MISMATCH")
        self.assertTrue(os.path.isfile(os.path.join(self.tmp.name, "self_improvement_events.json")))

    def test_feedback_rejects_unknown_category(self):
        with self.assertRaisesRegex(ValueError, "INVALID_FEEDBACK_CATEGORY"):
            record_answer_feedback(self.memory_file, "RAW_TEXT", "fail")

    def test_solution_library_runtime_requires_external_evidence(self):
        reference = "test_self_improvement.py::test_solution_library_runtime_requires_external_evidence"
        candidate = manage_solution_library(self.memory_file, "add_candidate", {
            "name": "safe_read_retry", "problem": "Transient read-only network failure",
            "algorithm": "Retry only an explicitly allowlisted read operation once.",
            "conditions": ["Operation is read-only"], "limitations": ["No side effects"],
            "compatibility": ["Android/Termux"], "test_references": [reference], "source_sha": "a" * 40})
        fake = {"decision": "VERIFIED", "test_reference": reference, "commit_sha": "a" * 40,
            "repository_id": 1381206490, "workflow_id": 7, "workflow_path": ".github/workflows/python-ci.yml",
            "run_id": 99, "run_attempt": 1, "job_id": 3, "job_name": "Python 3.11 checks",
            "job_conclusion": "success", "run_url": "https://github.com/example/run/99", "assurance": "API metadata validated"}
        with patch("self_improvement.evidence.validate_github_actions_evidence", return_value=fake):
            result = manage_solution_library(self.memory_file, "verify", {
                "solution_id": candidate["id"], "test_reference": reference, "commit_sha": "a" * 40})
        self.assertEqual(result["decision"], "VERIFIED")
        self.assertTrue(result["candidate_changed"])
        self.assertEqual(result["candidate"]["verification"]["evidence"]["run_id"], 99)

    def test_solution_library_runtime_keeps_candidate_when_external_evidence_is_inconclusive(self):
        reference = "test_self_improvement.py::test_case"
        candidate = manage_solution_library(self.memory_file, "add_candidate", {
            "name": "no_ci", "problem": "p", "algorithm": "a", "conditions": [], "limitations": [],
            "test_references": [reference], "source_sha": "b" * 40})
        with patch("self_improvement.evidence.validate_github_actions_evidence",
                   return_value={"decision": "INCONCLUSIVE", "reason": "NO_EXACT_COMMIT_RUN"}):
            result = manage_solution_library(self.memory_file, "verify", {
                "solution_id": candidate["id"], "test_reference": reference, "commit_sha": "b" * 40})
        self.assertEqual(result["decision"], "INCONCLUSIVE")
        self.assertFalse(result["candidate_changed"])
        self.assertEqual(result["candidate_status"], "CANDIDATE")

    def test_solution_library_rejects_unknown_operation(self):
        with self.assertRaisesRegex(ValueError, "INVALID_SOLUTION_LIBRARY_OPERATION"):
            manage_solution_library(self.memory_file, "execute", {})

    def test_module_improvement_proposal_requires_review_and_stays_inert(self):
        proposal = manage_module_improvements(self.memory_file, "create", {
            "finding": {"code": "REPEATED_FAILURE", "severity": "WARNING", "evidence": "3 similar failures"},
            "title": "Improve timeout diagnostics",
            "rationale": "Repeated timeouts need clearer evidence.",
            "affected_modules": ["execution_engine.py"],
            "tests": ["test_execution_engine.py"],
            "risk": "LOW",
        })
        self.assertEqual(proposal["id"], "M-001")
        self.assertEqual(proposal["review_status"], "PENDING")
        approved = manage_module_improvements(self.memory_file, "approve", {"reference": "M-001"})
        self.assertEqual(approved["review_status"], "APPROVED")
        self.assertFalse(approved["implementation_applied"])
        self.assertFalse(approved["activation_allowed"])
        with self.assertRaisesRegex(ValueError, "IMPROVEMENT_PROPOSAL_ALREADY_REVIEWED"):
            manage_module_improvements(self.memory_file, "reject", {"reference": "M-001"})


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
        # A fresh store instance must independently read the persisted event.
        reopened = ImprovementEventStore(path)
        self.assertEqual(reopened.list_events(), [event])
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertNotIn("conversation", event)

    def test_invalid_event_rejected(self):
        store = ImprovementEventStore(os.path.join(self.tmp.name, "events.json"))
        with self.assertRaisesRegex(ValueError, "INVALID_EVENT_OUTCOME"):
            store.add("timeout", "maybe", "verifier")

    def test_write_is_not_reported_successful_without_disk_readback(self):
        store = ImprovementEventStore(os.path.join(self.tmp.name, "events.json"))
        with patch("self_improvement.store._write_private_json", return_value=None):
            with self.assertRaisesRegex(ValueError, "EVENT_WRITE_VERIFICATION_FAILED"):
                store.add("ACCURACY", "pass", "user_feedback", "READBACK_TEST")

    def test_self_reported_evidence_is_rejected(self):
        library = SolutionLibrary(os.path.join(self.tmp.name, "solutions.json"))
        candidate = library.add_candidate("self_claim", "p", "a", [], [],
            test_references=["test_self_improvement.py::test_case"], source_sha="a" * 40)
        with self.assertRaisesRegex(ValueError, "EXTERNAL_VERIFICATION_REQUIRED"):
            library.verify(candidate["id"], {"test_run": "invented", "passed": True})

    def test_external_verification_persists_api_evidence(self):
        library = SolutionLibrary(os.path.join(self.tmp.name, "solutions.json"))
        reference = "test_self_improvement.py::test_case"
        candidate = library.add_candidate("external", "p", "a", [], [],
            test_references=[reference], source_sha="a" * 40)
        evidence = {"decision": "VERIFIED", "test_reference": reference, "commit_sha": "a" * 40,
            "repository_id": 1381206490, "workflow_id": 7, "workflow_path": ".github/workflows/python-ci.yml",
            "run_id": 123, "run_attempt": 1, "job_id": 456, "job_name": "Python 3.11 checks",
            "job_conclusion": "success", "run_url": "https://github.com/example/run/123", "assurance": "API metadata validated"}
        verified = library.verify_external(candidate["id"], evidence)
        self.assertEqual(verified["status"], "VERIFIED")
        self.assertEqual(verified["verification"]["evidence"]["run_id"], 123)
        self.assertEqual(SolutionLibrary(library.path).list_solutions("VERIFIED"), [verified])

    def test_external_verification_rejects_sha_mismatch(self):
        library = SolutionLibrary(os.path.join(self.tmp.name, "solutions.json"))
        reference = "test_self_improvement.py::test_case"
        candidate = library.add_candidate("sha_mismatch", "p", "a", [], [],
            test_references=[reference], source_sha="a" * 40)
        evidence = {"decision": "VERIFIED", "test_reference": reference, "commit_sha": "b" * 40,
            "repository_id": 1381206490, "workflow_id": 7, "workflow_path": ".github/workflows/python-ci.yml",
            "run_id": 1, "run_attempt": 1, "job_id": 2, "job_name": "Python 3.11 checks",
            "job_conclusion": "success", "run_url": "https://github.com/example/run/1", "assurance": "API metadata validated"}
        with self.assertRaisesRegex(ValueError, "CANDIDATE_SOURCE_SHA_MISMATCH"):
            library.verify_external(candidate["id"], evidence)

    def test_legacy_candidate_cannot_be_verified_from_claims(self):
        library = SolutionLibrary(os.path.join(self.tmp.name, "solutions.json"))
        candidate = library.add_candidate("legacy", "p", "a", [], [])
        with self.assertRaisesRegex(ValueError, "EXTERNAL_VERIFICATION_REQUIRED"):
            library.verify(candidate["id"], {"test_run": "CI:run", "passed": True})

    def test_solution_metadata_is_validated_and_persisted(self):
        library = SolutionLibrary(os.path.join(self.tmp.name, "solutions.json"))
        with self.assertRaisesRegex(ValueError, "INVALID_COMPATIBILITY"):
            library.add_candidate("bad", "p", "a", [], [], compatibility=[""])
        with self.assertRaisesRegex(ValueError, "INVALID_TEST_REFERENCES"):
            library.add_candidate("bad_refs", "p", "a", [], [], test_references=[" "])

        candidate = library.add_candidate(
            "metadata", "problem", "algorithm", [], [],
            compatibility=["Android/Termux"],
            test_references=["CI:run-42", "test_solution.py::test_metadata"],
        )
        reopened = SolutionLibrary(library.path)
        saved = reopened.list_solutions()[0]
        self.assertEqual(saved, candidate)
        self.assertEqual(saved["compatibility"], ["Android/Termux"])
        self.assertEqual(saved["test_references"], ["CI:run-42", "test_solution.py::test_metadata"])

    def test_failed_or_successful_caller_claims_are_not_evidence(self):
        library = SolutionLibrary(os.path.join(self.tmp.name, "solutions.json"))
        candidate = library.add_candidate("x", "p", "a", [], [])
        with self.assertRaisesRegex(ValueError, "EXTERNAL_VERIFICATION_REQUIRED"):
            library.verify(candidate["id"], {"test_run": "CI run 123", "passed": False})

    def test_duplicate_solution_names_rejected(self):
        library = SolutionLibrary(os.path.join(self.tmp.name, "solutions.json"))
        library.add_candidate("x", "p", "a", [], [])
        with self.assertRaisesRegex(ValueError, "DUPLICATE_SOLUTION"):
            library.add_candidate("X", "p", "a", [], [])

    def test_solution_write_is_verified_by_readback(self):
        library = SolutionLibrary(os.path.join(self.tmp.name, "solutions.json"))
        with patch("self_improvement.store._write_private_json", return_value=None):
            with self.assertRaisesRegex(ValueError, "SOLUTION_WRITE_VERIFICATION_FAILED"):
                library.add_candidate("readback", "problem", "algorithm", [], [])

    def test_solution_concurrent_candidates_receive_unique_ids_without_lost_records(self):
        from concurrent.futures import ThreadPoolExecutor

        library = SolutionLibrary(os.path.join(self.tmp.name, "solutions.json"))

        def add_one(index):
            return library.add_candidate(
                "concurrent_" + str(index), "problem", "algorithm", [], []
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            created = list(pool.map(add_one, range(24)))

        ids = [item["id"] for item in created]
        persisted = SolutionLibrary(library.path).list_solutions()
        self.assertEqual(len(set(ids)), 24)
        self.assertEqual(len(persisted), 24)
        self.assertEqual({item["id"] for item in persisted}, set(ids))

    def test_external_verification_and_status_changes_survive_reopen(self):
        library = SolutionLibrary(os.path.join(self.tmp.name, "solutions.json"))
        reference = "test_self_improvement.py::test_external_verification_and_status_changes_survive_reopen"
        candidate = library.add_candidate("lifecycle", "p", "a", [], [],
            test_references=[reference], source_sha="c" * 40)
        evidence = {"decision": "VERIFIED", "test_reference": reference, "commit_sha": "c" * 40,
            "repository_id": 1381206490, "workflow_id": 7, "workflow_path": ".github/workflows/python-ci.yml",
            "run_id": 321, "run_attempt": 1, "job_id": 654, "job_name": "Python 3.11 checks",
            "job_conclusion": "success", "run_url": "https://github.com/example/run/321", "assurance": "API metadata validated"}
        verified = library.verify_external(candidate["id"], evidence)
        reopened = SolutionLibrary(library.path)
        self.assertEqual(reopened.list_solutions("VERIFIED"), [verified])
        deprecated = reopened.set_status(candidate["id"], "DEPRECATED")
        self.assertEqual(SolutionLibrary(library.path).list_solutions("DEPRECATED"), [deprecated])

class ImprovementProposalStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "proposals.json")
        self.proposal = build_improvement_proposal(
            {"code": "TEST_FINDING", "severity": "LOW", "evidence": "unit test"},
            "Test proposal", "Validate durable inert proposal storage.",
            ["sample_module.py"], ["test_sample_module.py"], "LOW",
        )

    def test_lock_file_is_stored_in_private_home_not_shared_data_directory(self):
        shared_path = os.path.join(self.tmp.name, "shared", "proposals.json")
        private_home = os.path.join(self.tmp.name, "termux-home")
        os.makedirs(private_home)
        with patch.dict(os.environ, {"HOME": private_home}):
            from self_improvement.store import _private_lock_path
            lock_path = _private_lock_path(shared_path)
            self.assertTrue(lock_path.startswith(os.path.join(private_home, ".cache", "personal_ai_brain", "locks") + os.sep))
            self.assertFalse(lock_path.startswith(os.path.dirname(shared_path) + os.sep))
            self.assertEqual(lock_path, _private_lock_path(shared_path))
            self.assertNotEqual(lock_path, _private_lock_path(shared_path + ".other"))
            lock_dir = os.path.dirname(lock_path)
            self.assertEqual(os.stat(lock_dir).st_mode & 0o777, 0o700)
            from self_improvement.store import _locked_store
            with _locked_store(shared_path):
                pass
            self.assertEqual(os.stat(lock_path).st_mode & 0o777, 0o600)

    def test_create_is_read_back_and_survives_fresh_store_instance(self):
        store = ImprovementProposalStore(self.path)
        created = store.create(self.proposal)
        reopened = ImprovementProposalStore(self.path)
        self.assertEqual(reopened.list_proposals(), [created])
        self.assertFalse(created["implementation_applied"])
        self.assertFalse(created["activation_allowed"])
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_create_fails_if_persisted_record_cannot_be_read_back(self):
        store = ImprovementProposalStore(self.path)
        with patch("self_improvement.store._write_private_json", return_value=None):
            with self.assertRaisesRegex(ValueError, "IMPROVEMENT_PROPOSAL_WRITE_VERIFICATION_FAILED"):
                store.create(self.proposal)

    def test_review_is_persisted_and_remains_inert(self):
        store = ImprovementProposalStore(self.path)
        created = store.create(self.proposal)
        reviewed = store.review(created["id"], "APPROVED")
        reopened = ImprovementProposalStore(self.path)
        saved = reopened.list_proposals("APPROVED")[0]
        self.assertEqual(saved, reviewed)
        self.assertFalse(saved["implementation_applied"])
        self.assertFalse(saved["activation_allowed"])

    def test_rejected_proposal_is_persisted(self):
        store = ImprovementProposalStore(self.path)
        created = store.create(self.proposal)
        rejected = store.review(created["id"], "REJECTED")
        self.assertEqual(ImprovementProposalStore(self.path).list_proposals("REJECTED"), [rejected])

    def test_concurrent_creates_receive_unique_ids_without_lost_records(self):
        from concurrent.futures import ThreadPoolExecutor

        store = ImprovementProposalStore(self.path)
        def create_one(index):
            proposal = dict(self.proposal)
            proposal["title"] = "Concurrent proposal " + str(index)
            return store.create(proposal)

        with ThreadPoolExecutor(max_workers=8) as pool:
            created = list(pool.map(create_one, range(24)))

        ids = [item["id"] for item in created]
        self.assertEqual(len(set(ids)), 24)
        persisted = ImprovementProposalStore(self.path).list_proposals()
        self.assertEqual(len(persisted), 24)
        self.assertEqual({item["id"] for item in persisted}, set(ids))
        self.assertTrue(all(item["review_status"] == "PENDING" for item in persisted))
        self.assertTrue(all(item["implementation_applied"] is False for item in persisted))
        self.assertTrue(all(item["activation_allowed"] is False for item in persisted))


if __name__ == "__main__":
    unittest.main(verbosity=2)
