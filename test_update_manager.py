import unittest

import update_manager


class TestParsePorcelainStatus(unittest.TestCase):
    def test_parses_modified_and_untracked_paths(self):
        result = update_manager.parse_porcelain_status(
            " M brain.py\n?? personal notes.txt\n"
        )
        self.assertEqual(
            result,
            [(" M", "brain.py"), ("??", "personal notes.txt")],
        )

    def test_empty_status_is_clean(self):
        self.assertEqual(update_manager.parse_porcelain_status(""), [])


class TestParseLsRemote(unittest.TestCase):
    def test_extracts_main_sha(self):
        sha = "a" * 40
        self.assertEqual(
            update_manager.parse_ls_remote(f"{sha}\trefs/heads/main"),
            sha,
        )

    def test_rejects_missing_main_ref(self):
        with self.assertRaises(update_manager.UpdateManagerError):
            update_manager.parse_ls_remote(f"{'b' * 40}\trefs/heads/development/test")


class TestFormatReport(unittest.TestCase):
    def test_report_discloses_read_only_boundary_and_local_changes(self):
        report = {
            "repository": "owner/repo",
            "root": "/tmp/repo",
            "branch": "main",
            "local_sha": "a" * 40,
            "remote_sha": "a" * 40,
            "dirty_entries": [(" M", "brain.py")],
            "comparison": {"status": "identical", "commits": [], "files": []},
            "ci": {"state": "not_verified", "reason": "No exact run"},
        }
        rendered = update_manager.format_report(report)
        self.assertIn("Working tree: DIRTY (1 entries)", rendered)
        self.assertIn("LOCAL  M brain.py", rendered)
        self.assertIn("CI for exact origin/main commit: not_verified", rendered)
        self.assertIn("no fetch, checkout, merge", rendered)
        self.assertNotIn("OPENROUTER_API_KEY", rendered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
