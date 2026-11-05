import unittest
from unittest.mock import patch
import brain_auto_update as updater


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

    def test_ci_requires_exact_named_check_completed_success(self):
        self.assertTrue(updater.ci_is_successful({"check_runs": [{
            "name": updater.CI_CHECK_NAME,
            "status": "completed",
            "conclusion": "success",
        }]}))

    def test_ci_rejects_missing_pending_or_failed_check(self):
        self.assertFalse(updater.ci_is_successful({"check_runs": []}))
        self.assertFalse(updater.ci_is_successful({"check_runs": [{
            "name": updater.CI_CHECK_NAME,
            "status": "in_progress",
            "conclusion": None,
        }]}))
        self.assertFalse(updater.ci_is_successful({"check_runs": [{
            "name": updater.CI_CHECK_NAME,
            "status": "completed",
            "conclusion": "failure",
        }]}))

    def test_ci_rejects_unrelated_successful_checks(self):
        self.assertFalse(updater.ci_is_successful({"check_runs": [{
            "name": "Other workflow",
            "status": "completed",
            "conclusion": "success",
        }]}))

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
