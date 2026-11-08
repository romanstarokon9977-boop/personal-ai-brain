import os
import subprocess
import tempfile
import unittest
from unittest import mock

import git_readonly


class GitReadonlyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="git_readonly_")
        self.addCleanup(self.temp_dir.cleanup)
        self.repo = self.temp_dir.name
        os.mkdir(os.path.join(self.repo, ".git"))
        self.repo_patch = mock.patch.object(git_readonly, "REPO_ROOT", self.repo)
        self.repo_patch.start()
        self.addCleanup(self.repo_patch.stop)

    def test_all_supported_operations_use_fixed_argv_without_shell(self):
        cases = {
            "status": ["status", "--short", "--branch", "--no-color", "--untracked-files=no", "--ignore-submodules=all"],
            "diff": ["diff", "--no-ext-diff", "--no-textconv", "--no-color", "--"],
            "log": ["log", "--oneline", "--no-decorate", "--no-color", "-n", "10"],
            "show": ["show", "--no-ext-diff", "--no-textconv", "--no-color",
                     "--stat", "--oneline", "HEAD"],
        }
        for operation, expected in cases.items():
            with self.subTest(operation=operation):
                completed = subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="safe output\n", stderr=""
                )
                with mock.patch.object(
                    git_readonly.subprocess, "run", return_value=completed
                ) as run_mock:
                    result = git_readonly.inspect_repo({"operation": operation})

                self.assertTrue(result["ok"])
                self.assertEqual(result["result"], "safe output")
                args, kwargs = run_mock.call_args
                self.assertEqual(args[0][0:7], [
                    "git", "--no-pager", "--no-optional-locks", "-c",
                    "core.fsmonitor=false", "-C", self.repo
                ])
                self.assertEqual(args[0][7:], expected)
                self.assertIs(kwargs["shell"], False)
                self.assertEqual(kwargs["cwd"], self.repo)
                self.assertEqual(kwargs["timeout"], 10)
                self.assertEqual(kwargs["env"]["GIT_OPTIONAL_LOCKS"], "0")
                self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")

    def test_unknown_operation_is_rejected_without_process(self):
        with mock.patch.object(git_readonly.subprocess, "run") as run_mock:
            result = git_readonly.inspect_repo({"operation": "push"})
        self.assertFalse(result["ok"])
        self.assertIn("INVALID_OPERATION", result["error"])
        run_mock.assert_not_called()

    def test_extra_arguments_are_rejected_without_process(self):
        with mock.patch.object(git_readonly.subprocess, "run") as run_mock:
            result = git_readonly.inspect_repo({
                "operation": "show", "revision": "HEAD~1"
            })
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "UNSUPPORTED_PARAMETERS")
        run_mock.assert_not_called()

    def test_non_mapping_parameters_are_rejected(self):
        result = git_readonly.inspect_repo(["status"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "INVALID_PARAMETERS")

    def test_missing_git_metadata_is_rejected(self):
        os.rmdir(os.path.join(self.repo, ".git"))
        with mock.patch.object(git_readonly.subprocess, "run") as run_mock:
            result = git_readonly.inspect_repo({"operation": "status"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "GIT_METADATA_NOT_FOUND")
        run_mock.assert_not_called()

    def test_timeout_is_reported(self):
        with mock.patch.object(
            git_readonly.subprocess, "run",
            side_effect=subprocess.TimeoutExpired("git", 10),
        ):
            result = git_readonly.inspect_repo({"operation": "status"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "GIT_INSPECTION_TIMEOUT")

    def test_nonzero_exit_is_reported(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=128, stdout="", stderr="not a repository"
        )
        with mock.patch.object(
            git_readonly.subprocess, "run", return_value=completed
        ):
            result = git_readonly.inspect_repo({"operation": "status"})
        self.assertFalse(result["ok"])
        self.assertIn("GIT_EXIT_128", result["error"])

    def test_output_is_bounded(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="x" * (git_readonly.MAX_OUTPUT_CHARS + 5),
            stderr=""
        )
        with mock.patch.object(
            git_readonly.subprocess, "run", return_value=completed
        ):
            result = git_readonly.inspect_repo({"operation": "diff"})
        self.assertTrue(result["ok"])
        self.assertLessEqual(len(result["result"]), git_readonly.MAX_OUTPUT_CHARS + 32)
        self.assertIn("OUTPUT_TRUNCATED", result["result"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
