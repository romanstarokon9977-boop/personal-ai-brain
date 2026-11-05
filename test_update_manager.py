import unittest
from unittest.mock import patch

import update_manager as um


class TestParsePorcelainStatus(unittest.TestCase):
    def test_parses_modified_and_untracked_paths(self):
        self.assertEqual(
            um.parse_porcelain_status(" M brain.py\n?? personal notes.txt\n"),
            [(" M", "brain.py"), ("??", "personal notes.txt")],
        )

    def test_empty_status_is_clean(self):
        self.assertEqual(um.parse_porcelain_status(""), [])


class TestRemoteParsing(unittest.TestCase):
    def test_extracts_main_sha(self):
        sha = "a" * 40
        self.assertEqual(um.parse_ls_remote(f"{sha}\trefs/heads/main"), sha)

    def test_rejects_missing_main_ref_and_invalid_sha(self):
        with self.assertRaises(um.UpdateManagerError):
            um.parse_ls_remote(f"{'b' * 40}\trefs/heads/development/test")
        with self.assertRaises(um.UpdateManagerError):
            um.parse_ls_remote(f"{'z' * 40}\trefs/heads/main")

    def test_normalizes_supported_https_and_ssh_urls(self):
        self.assertEqual(um.normalize_github_remote("https://github.com/Owner/Repo.git"), "owner/repo")
        self.assertEqual(um.normalize_github_remote("git@github.com:Owner/Repo.git"), "owner/repo")

    def test_rejects_unexpected_remote_hosts(self):
        with self.assertRaises(um.UpdateManagerError):
            um.normalize_github_remote("https://evil.example/owner/repo.git")


class TestCIClassification(unittest.TestCase):
    def test_completed_run_uses_conclusion(self):
        self.assertEqual(um.classify_ci_run({"status": "completed", "conclusion": "success"}), "success")
        self.assertEqual(um.classify_ci_run({"status": "completed", "conclusion": "failure"}), "failure")

    def test_in_progress_run_is_not_success(self):
        self.assertEqual(um.classify_ci_run({"status": "in_progress", "conclusion": None}), "in_progress")


class TestCollectReport(unittest.TestCase):
    def test_rejects_origin_repository_mismatch_before_network_api(self):
        calls = []
        def git(args, cwd=None):
            if args[0] == "rev-parse":
                return "/tmp/repo" if args[1] == "--show-toplevel" else "a" * 40
            if args[0] == "branch":
                return "main"
            if args[0] == "status":
                return ""
            if args[:3] == ["remote", "get-url", "origin"]:
                return "https://github.com/someone/else.git"
            raise AssertionError(args)
        with self.assertRaisesRegex(um.UpdateManagerError, "identity mismatch"):
            um.collect_report(git_runner=git, api_reader=lambda path: calls.append(path))
        self.assertEqual(calls, [])

    def test_ci_requires_exact_sha_and_reports_pending(self):
        sha = "a" * 40
        git_calls = []
        def git(args, cwd=None):
            if args == ["rev-parse", "--show-toplevel"]:
                return "/tmp/repo"
            if args == ["rev-parse", "HEAD"]:
                return sha
            if args == ["branch", "--show-current"]:
                return "main"
            if args[0] == "status":
                return ""
            if args[:3] == ["remote", "get-url", "origin"]:
                return "git@github.com:romanstarokon9977-boop/personal-ai-brain.git"
            if args[0] == "ls-remote":
                return f"{sha}\trefs/heads/main"
            raise AssertionError(args)
        def api(path):
            return {"workflow_runs": [
                {"head_sha": "b" * 40, "status": "completed", "conclusion": "success"},
                {"head_sha": sha, "status": "in_progress", "conclusion": None, "id": 42},
            ]}
        report = um.collect_report(git_runner=git, api_reader=api)
        self.assertEqual(report["ci"]["state"], "in_progress")
        self.assertEqual(report["ci"]["head_sha"], sha)

    def test_api_error_is_unknown_not_failure(self):
        sha = "a" * 40
        def git(args, cwd=None):
            if args == ["rev-parse", "--show-toplevel"]:
                return "/tmp/repo"
            if args == ["rev-parse", "HEAD"]:
                return sha
            if args == ["branch", "--show-current"]:
                return "main"
            if args[0] == "status":
                return ""
            if args[:3] == ["remote", "get-url", "origin"]:
                return "https://github.com/romanstarokon9977-boop/personal-ai-brain"
            if args[0] == "ls-remote":
                return f"{sha}\trefs/heads/main"
            raise AssertionError(args)
        report = um.collect_report(git_runner=git, api_reader=lambda path: {"_error": "HTTP 403"})
        self.assertEqual(report["ci"]["state"], "unknown")
        self.assertIn("403", report["ci"]["reason"])


class TestFormatReport(unittest.TestCase):
    def test_report_discloses_read_only_boundary_and_local_changes(self):
        report = {
            "repository": "owner/repo", "root": "/tmp/repo", "branch": "main",
            "local_sha": "a" * 40, "remote_sha": "a" * 40,
            "dirty_entries": [(" M", "brain.py")],
            "comparison": {"status": "identical", "commits": [], "files": []},
            "ci": {"state": "not_verified", "reason": "No exact run"},
        }
        rendered = um.format_report(report)
        self.assertIn("Working tree: DIRTY (1 entries)", rendered)
        self.assertIn("LOCAL  M brain.py", rendered)
        self.assertIn("CI for exact origin/main commit: not_verified", rendered)
        self.assertIn("no fetch, checkout, merge", rendered)
        self.assertNotIn("OPENROUTER_API_KEY", rendered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
