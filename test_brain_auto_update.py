import unittest
from unittest.mock import patch
import brain_auto_update as updater


EXPECTED_SHA = "d2817b9fc40f903daeff2cf4db2a0b68d85a7cf0"


def workflow_run(*, sha=EXPECTED_SHA, status="completed", conclusion="success",
                 run_number=1, run_attempt=1, run_id=100,
                 name=updater.CI_WORKFLOW_NAME):
    return {
        "name": name,
        "head_sha": sha,
        "status": status,
        "conclusion": conclusion,
        "run_number": run_number,
        "run_attempt": run_attempt,
        "id": run_id,
    }


class AutoUpdatePolicyTests(unittest.TestCase):
    def test_accepts_expected_https_and_ssh_remotes(self):
        self.assertTrue(updater.is_expected_remote(
            "https://github.com/romanstarokon9977-boop/personal-ai-brain.git"
        ))
        self.assertTrue(updater.is_expected_remote(
            "git@github.com:romanstarokon9977-boop/personal-ai-brain.git"
        ))

    def test_rejects_other_remote(self):
        self.assertFalse(updater.is_expected_remote(
            "https://github.com/someone/other.git"
        ))

    def test_actions_ci_accepts_completed_success_for_exact_sha(self):
        payload = {"workflow_runs": [workflow_run()]}
        self.assertTrue(updater.ci_is_successful(payload, EXPECTED_SHA))

    def test_actions_ci_rejects_different_sha(self):
        payload = {"workflow_runs": [workflow_run(
            sha="0321d2185cee284f3cd59c76691d63d2be4b2d38"
        )]}
        self.assertFalse(updater.ci_is_successful(payload, EXPECTED_SHA))

    def test_actions_ci_rejects_missing_or_malformed_runs(self):
        self.assertFalse(updater.ci_is_successful({}, EXPECTED_SHA))
        self.assertFalse(updater.ci_is_successful(
            {"workflow_runs": "not-a-list"}, EXPECTED_SHA
        ))
        self.assertFalse(updater.ci_is_successful(
            {"workflow_runs": []}, EXPECTED_SHA
        ))

    def test_actions_ci_rejects_pending_failed_or_cancelled_runs(self):
        for status, conclusion in (
            ("in_progress", None),
            ("completed", "failure"),
            ("completed", "cancelled"),
        ):
            with self.subTest(status=status, conclusion=conclusion):
                payload = {"workflow_runs": [workflow_run(
                    status=status, conclusion=conclusion
                )]}
                self.assertFalse(updater.ci_is_successful(payload, EXPECTED_SHA))

    def test_actions_ci_rejects_unrelated_workflow(self):
        payload = {"workflow_runs": [workflow_run(name="Other workflow")]}
        self.assertFalse(updater.ci_is_successful(payload, EXPECTED_SHA))

    def test_latest_rerun_controls_result(self):
        payload = {"workflow_runs": [
            workflow_run(run_number=10, run_attempt=1, conclusion="success"),
            workflow_run(run_number=10, run_attempt=2, conclusion="failure",
                         run_id=101),
        ]}
        self.assertFalse(updater.ci_is_successful(payload, EXPECTED_SHA))

    def test_latest_successful_rerun_is_accepted(self):
        payload = {"workflow_runs": [
            workflow_run(run_number=10, run_attempt=1, conclusion="failure"),
            workflow_run(run_number=10, run_attempt=2, conclusion="success",
                         run_id=101),
        ]}
        self.assertTrue(updater.ci_is_successful(payload, EXPECTED_SHA))

    def test_dirty_worktree_stops_before_fetch(self):
        outputs = iter([
            "/tmp/brain",
            "main",
            "https://github.com/romanstarokon9977-boop/personal-ai-brain.git",
            " M brain.py",
        ])

        def fake_git(args, *, cwd, timeout=30):
            return next(outputs)

        with patch.object(updater, "_git", side_effect=fake_git) as mocked:
            result = updater.apply_update_if_safe("/tmp/brain")

        self.assertEqual(result["reason"], "working_tree_not_clean")
        self.assertEqual(mocked.call_count, 4)

    def test_non_main_branch_stops_before_remote_or_fetch(self):
        outputs = iter(["/tmp/brain", "development/test"])

        with patch.object(updater, "_git", side_effect=lambda *a, **k: next(outputs)) as mocked:
            result = updater.apply_update_if_safe("/tmp/brain")

        self.assertEqual(result["reason"], "not_on_main")
        self.assertEqual(mocked.call_count, 2)


if __name__ == "__main__":
    unittest.main()
