"""
Изолированный тест для self_inspection.py.

Не импортирует brain.py или другие модули проекта.
Работает с временным каталогом.
"""

import hashlib
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import self_inspection


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


class SelfInspectionTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="si_test_")

    def tearDown(self):
        try:
            shutil.rmtree(self.tmp)
        except Exception:
            pass

    def _write(self, rel, content):
        p = os.path.join(self.tmp, rel)
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(p, "wb") as f:
            f.write(content)
        return p

    # T1
    def test_collect_returns_dict(self):
        r = self_inspection.collect(project_root=self.tmp)
        self.assertIsInstance(r, dict)
        for k in ("ok", "error", "result"):
            self.assertIn(k, r)
        self.assertTrue(r["ok"])

    # T2
    def test_result_structure(self):
        r = self_inspection.collect(project_root=self.tmp)
        res = r["result"]
        for k in ("project_root", "files", "golden", "git", "diagnostics"):
            self.assertIn(k, res)
        self.assertIsInstance(res["diagnostics"]["warnings"], list)
        self.assertIsInstance(res["diagnostics"]["inconclusive"], list)

    # T3
    def test_files_section_keys(self):
        r = self_inspection.collect(project_root=self.tmp)
        files = r["result"]["files"]
        for rel in self_inspection.INSPECTED_FILES:
            self.assertIn(rel, files)
            for k in ("exists", "size", "sha256", "readable", "is_secret", "error"):
                self.assertIn(k, files[rel])

    # T3b
    def test_critical_modules_are_in_inspection_scope(self):
        for rel in (
            "memory/fact_extractor.py",
            "auto_poster.py",
            "cpa_brain_bridge.py",
        ):
            self.assertIn(rel, self_inspection.INSPECTED_FILES)

    # T4
    def test_sha256_correct(self):
        content = b"hello world\n"
        p = self._write("test_file.txt", content)
        got = self_inspection.sha256_file(p)
        self.assertEqual(got, _sha256(content))

    # T5
    def test_missing_file_handled(self):
        r = self_inspection.collect(project_root=self.tmp)
        for rel in self_inspection.INSPECTED_FILES:
            fi = r["result"]["files"][rel]
            self.assertFalse(fi["exists"])
            self.assertIsNone(fi["sha256"])

    # T6
    def test_secret_file_skipped(self):
        self._write("config.py", b"SECRET_CONTENT")
        with mock.patch.object(self_inspection, "INSPECTED_FILES", ("config.py",)):
            r = self_inspection.collect(project_root=self.tmp)
        fi = r["result"]["files"]["config.py"]
        self.assertTrue(fi["is_secret"])
        self.assertIsNone(fi["sha256"])
        self.assertEqual(fi["error"], "SECRET_SKIPPED")

    # T7
    def test_no_secret_content_read(self):
        self._write("config.py", b"UNIQUE_MARKER_98765")
        opened = []
        real_open = open

        def fake_open(path, mode="r", *a, **kw):
            opened.append((str(path), mode))
            return real_open(path, mode, *a, **kw)

        with mock.patch("builtins.open", side_effect=fake_open):
            with mock.patch.object(
                self_inspection, "INSPECTED_FILES", ("config.py",)
            ):
                self_inspection.collect(project_root=self.tmp)

        for path, mode in opened:
            self.assertNotIn("config.py", os.path.basename(path))

    # T8
    def test_golden_no_reference(self):
        with mock.patch.object(self_inspection, "GOLDEN_REFERENCES", {}):
            r = self_inspection.collect(project_root=self.tmp)
        for rel in self_inspection.INSPECTED_FILES:
            gi = r["result"]["golden"][rel]
            self.assertEqual(gi["status"], "NO_REFERENCE")

    # T9
    def test_golden_match(self):
        content = b"current content\n"
        sha = _sha256(content)
        self._write("brain.py", content)
        self._write("backups_golden/brain_GOLDEN_test.py", content)
        refs = {
            "brain.py": {
                "reference_path": "backups_golden/brain_GOLDEN_test.py",
                "expected_sha256": sha,
                "verified": True,
                "verified_by": "test",
            }
        }
        with mock.patch.object(self_inspection, "INSPECTED_FILES", ("brain.py",)), \
             mock.patch.object(self_inspection, "GOLDEN_REFERENCES", refs):
            r = self_inspection.collect(project_root=self.tmp)
        gi = r["result"]["golden"]["brain.py"]
        self.assertEqual(gi["status"], "MATCH")
        self.assertEqual(gi["current_sha256"], sha)
        self.assertEqual(gi["reference_sha256"], sha)

    # T10
    def test_golden_differs(self):
        c1 = b"current\n"
        c2 = b"reference\n"
        s1 = _sha256(c1)
        s2 = _sha256(c2)
        self._write("brain.py", c1)
        self._write("backups_golden/brain_GOLDEN_test.py", c2)
        refs = {
            "brain.py": {
                "reference_path": "backups_golden/brain_GOLDEN_test.py",
                "expected_sha256": s2,
                "verified": True,
                "verified_by": "test",
            }
        }
        with mock.patch.object(self_inspection, "INSPECTED_FILES", ("brain.py",)), \
             mock.patch.object(self_inspection, "GOLDEN_REFERENCES", refs):
            r = self_inspection.collect(project_root=self.tmp)
        gi = r["result"]["golden"]["brain.py"]
        self.assertEqual(gi["status"], "DIFFERS")
        self.assertEqual(gi["current_sha256"], s1)
        self.assertEqual(gi["reference_sha256"], s2)

    # T11
    def test_git_readonly(self):
        calls = []

        def fake_run(args, **kw):
            calls.append(list(args))
            m = mock.MagicMock()
            m.returncode = 128
            m.stdout = ""
            m.stderr = ""
            return m

        with mock.patch("subprocess.run", side_effect=fake_run):
            self_inspection.collect(project_root=self.tmp)

        forbidden = {
            "add", "commit", "push", "reset", "restore",
            "clean", "checkout", "stash", "fetch", "pull",
        }
        for args in calls:
            if not args or args[0] != "git":
                continue
            for token in args[1:]:
                self.assertNotIn(token, forbidden)

    # T12
    def test_no_project_changes(self):
        src_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "self_inspection.py",
        )
        with open(src_path, "r", encoding="utf-8") as f:
            src = f.read()

        # T12a: нет open с режимами записи
        self.assertIsNone(
            re.search(r"""open\s*\([^)]*["'][wax+]""", src),
            "self_inspection.py contains open() with write mode",
        )
        # T12b: нет destructive os/shutil
        for bad in (
            "os.remove", "os.rename", "os.replace", "os.rmdir",
            "os.unlink", "shutil.move", "shutil.copy", "shutil.rmtree",
        ):
            self.assertNotIn(bad, src, "self_inspection.py contains " + bad)

        # T12c: runtime — open() только на чтение
        self._write("brain.py", b"fake content")
        opened = []
        real_open = open

        def fake_open(path, mode="r", *a, **kw):
            opened.append((str(path), mode))
            return real_open(path, mode, *a, **kw)

        with mock.patch("builtins.open", side_effect=fake_open):
            with mock.patch.object(
                self_inspection, "INSPECTED_FILES", ("brain.py",)
            ):
                self_inspection.collect(project_root=self.tmp)

        for path, mode in opened:
            for w in "wax+":
                self.assertNotIn(w, mode, "open(" + path + ", " + mode + ")")

    # T13
    def test_tmp_dir_isolation(self):
        r = self_inspection.collect(project_root=self.tmp)
        self.assertEqual(r["result"]["project_root"], os.path.realpath(self.tmp))
        for rel in self_inspection.INSPECTED_FILES:
            self.assertFalse(r["result"]["files"][rel]["exists"])

    # T14
    def test_no_brain_import(self):
        src_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "self_inspection.py",
        )
        with open(src_path, "r", encoding="utf-8") as f:
            src = f.read()
        for bad in (
            "import brain", "from brain",
            "import tool_registry", "from tool_registry",
            "import mcp_bridge", "from mcp_bridge",
            "import verifier", "from verifier",
            "import context_manager", "from context_manager",
        ):
            self.assertNotIn(bad, src, "self_inspection.py contains " + bad)



    # T15
    def test_golden_reference_corrupted(self):
        content = b"reference content\n"
        ref_sha = _sha256(content)
        self._write("brain.py", b"other content\n")
        self._write("backups_golden/brain_GOLDEN_test.py", content)
        wrong_expected = "f" * 64
        refs = {
            "brain.py": {
                "reference_path": "backups_golden/brain_GOLDEN_test.py",
                "expected_sha256": wrong_expected,
                "verified": True,
                "verified_by": "test",
            }
        }
        with mock.patch.object(self_inspection, "INSPECTED_FILES", ("brain.py",)), \
             mock.patch.object(self_inspection, "GOLDEN_REFERENCES", refs):
            r = self_inspection.collect(project_root=self.tmp)
        gi = r["result"]["golden"]["brain.py"]
        self.assertEqual(gi["status"], "REFERENCE_CORRUPTED")
        self.assertEqual(gi["reference_sha256"], ref_sha)
        self.assertEqual(gi["expected_reference_sha256"], wrong_expected)

    # T16
    def test_golden_reference_missing(self):
        self._write("brain.py", b"content\n")
        refs = {
            "brain.py": {
                "reference_path": "backups_golden/brain_GOLDEN_does_not_exist.py",
                "expected_sha256": "a" * 64,
                "verified": True,
                "verified_by": "test",
            }
        }
        with mock.patch.object(self_inspection, "INSPECTED_FILES", ("brain.py",)), \
             mock.patch.object(self_inspection, "GOLDEN_REFERENCES", refs):
            r = self_inspection.collect(project_root=self.tmp)
        gi = r["result"]["golden"]["brain.py"]
        self.assertEqual(gi["status"], "REFERENCE_MISSING")
        self.assertFalse(gi["reference_exists"])

    # T17
    def test_outside_project_root(self):
        outside = os.path.join(os.path.dirname(self.tmp), "si_outside_test.txt")
        try:
            with open(outside, "wb") as f:
                f.write(b"outside")
            with mock.patch.object(
                self_inspection, "INSPECTED_FILES", ("../si_outside_test.txt",)
            ):
                r = self_inspection.collect(project_root=self.tmp)
            fi = r["result"]["files"]["../si_outside_test.txt"]
            self.assertEqual(fi["error"], "OUTSIDE_PROJECT_ROOT")
            self.assertFalse(fi["exists"])
            self.assertIsNone(fi["sha256"])
        finally:
            try:
                os.remove(outside)
            except Exception:
                pass

    # T18
    def test_symlink_escapes_root(self):
        import tempfile as _tf
        outside_dir = _tf.mkdtemp(prefix="si_outside_")
        outside_file = os.path.join(outside_dir, "outside.txt")
        link_path = os.path.join(self.tmp, "link.txt")
        try:
            with open(outside_file, "wb") as f:
                f.write(b"outside content")
            try:
                os.symlink(outside_file, link_path)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks not supported")
            with mock.patch.object(
                self_inspection, "INSPECTED_FILES", ("link.txt",)
            ):
                r = self_inspection.collect(project_root=self.tmp)
            fi = r["result"]["files"]["link.txt"]
            self.assertEqual(fi["error"], "OUTSIDE_PROJECT_ROOT")
            self.assertFalse(fi["exists"])
        finally:
            shutil.rmtree(outside_dir, ignore_errors=True)

    # T19
    def test_golden_secret_skipped(self):
        refs = {
            "brain.py": {
                "reference_path": "config.py",
                "expected_sha256": "a" * 64,
                "verified": True,
                "verified_by": "test",
            }
        }
        with mock.patch.object(self_inspection, "INSPECTED_FILES", ("brain.py",)), \
             mock.patch.object(self_inspection, "GOLDEN_REFERENCES", refs):
            r = self_inspection.collect(project_root=self.tmp)
        gi = r["result"]["golden"]["brain.py"]
        self.assertEqual(gi["status"], "SECRET_SKIPPED")

    # T20
    def test_secret_basename_classification(self):
        cases = [
            ("config.py", True),
            ("update_config.py", False),
            ("my_config.py", False),
            ("legacy_config.py", False),
            ("subdir/config.py", True),
            (".env", True),
            (".env.local", True),
            ("credentials.json", True),
            ("secret_notes.txt", True),
            ("api_token.txt", True),
            ("cert.pem", True),
            ("private.key", True),
            ("brain.py", False),
            ("memory/memory_core.py", False),
        ]
        for name, expected in cases:
            self.assertEqual(
                self_inspection._is_secret_basename(name),
                expected,
                "mismatch for " + repr(name),
            )

    # T21
    def test_real_project_sha_unchanged(self):
        project_root = os.path.dirname(os.path.abspath(self_inspection.__file__))
        files = (
            "brain.py",
            "tool_registry.py",
            "mcp_bridge.py",
            "verifier.py",
            "context_manager.py",
            "memory/memory_core.py",
        )
        before = {}
        for rel in files:
            p = os.path.join(project_root, rel)
            if not os.path.isfile(p):
                self.skipTest("project file missing: " + rel)
            before[rel] = self_inspection.sha256_file(p)
        self_inspection.collect(project_root=project_root)
        after = {}
        for rel in files:
            p = os.path.join(project_root, rel)
            after[rel] = self_inspection.sha256_file(p)
        self.assertEqual(before, after)

    # T22
    def test_git_secret_masking(self):
        porcelain = "?? config.py\0?? update_config.py\0?? brain.py\0"

        def fake_run(args, **kw):
            m = mock.MagicMock()
            m.stderr = ""
            m.returncode = 0
            if args[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                m.stdout = "main\n"
            elif args[:3] == ["git", "rev-parse", "--short"]:
                m.stdout = "abc1234\n"
            elif args[:2] == ["git", "rev-list"]:
                m.stdout = "0\n"
            elif args[:2] == ["git", "status"]:
                m.stdout = porcelain
            else:
                m.returncode = 128
                m.stdout = ""
            return m

        with mock.patch("subprocess.run", side_effect=fake_run):
            r = self_inspection.collect(project_root=self.tmp)
        untracked = r["result"]["git"]["untracked"]
        self.assertIn("[REDACTED_SECRET]", untracked)
        self.assertIn("update_config.py", untracked)
        self.assertIn("brain.py", untracked)
        self.assertNotIn("config.py", untracked)

    # T23
    def test_golden_expected_sha_missing(self):
        content = b"content\n"
        self._write("brain.py", content)
        self._write("backups_golden/brain_GOLDEN_test.py", content)
        refs = {
            "brain.py": {
                "reference_path": "backups_golden/brain_GOLDEN_test.py",
                "expected_sha256": "",
                "verified": True,
                "verified_by": "test",
            }
        }
        with mock.patch.object(self_inspection, "INSPECTED_FILES", ("brain.py",)), \
             mock.patch.object(self_inspection, "GOLDEN_REFERENCES", refs):
            r = self_inspection.collect(project_root=self.tmp)
        gi = r["result"]["golden"]["brain.py"]
        self.assertEqual(gi["status"], "UNKNOWN")
        self.assertEqual(gi["detail"], "EXPECTED_SHA_MISSING")
        self.assertIn(
            "golden_expected_sha_missing:brain.py",
            r["result"]["diagnostics"]["inconclusive"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
