"""Unit tests for Module Manager v0. Isolated temp dirs only."""

import builtins
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import module_manager as mm


def _write_valid(state_path, disabled_list, *, version=1, extra=None,
                 updated_at="2026-01-01T00:00:00Z"):
    payload = {"version": version, "updated_at": updated_at,
               "disabled": list(disabled_list)}
    if extra:
        payload.update(extra)
    with open(state_path, "wb") as f:
        f.write(json.dumps(payload).encode("utf-8"))


class Base(unittest.TestCase):
    def setUp(self):
        # Restore the module-level manager state after every isolated test.
        self._original_loaded_once = mm._loaded_once
        self._original_state_health = mm._state_health
        self._original_disabled = (
            None if mm._disabled is None else set(mm._disabled)
        )
        self.tmpdir = tempfile.mkdtemp(prefix="mm_test_")
        self.state_path = os.path.join(self.tmpdir, "module_state.json")
        self.tmp_path = os.path.join(self.tmpdir, "module_state.json.tmp")
        self._p1 = mock.patch.object(mm, "STATE_PATH", self.state_path)
        self._p2 = mock.patch.object(mm, "TMP_PATH", self.tmp_path)
        self._p1.start()
        self._p2.start()
        mm._loaded_once = False
        mm._state_health = "first_run"
        mm._disabled = None
        mm.load_state(force=True)

    def tearDown(self):
        self._p1.stop()
        self._p2.stop()
        mm._loaded_once = self._original_loaded_once
        mm._state_health = self._original_state_health
        mm._disabled = self._original_disabled
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _set_state_file(self, disabled_list):
        _write_valid(self.state_path, disabled_list)
        mm.load_state(force=True)


# ---------- State classification ----------

class TestStateClassification(Base):
    def test_01_first_run_when_no_file(self):
        self.assertEqual(mm.state_health(), "first_run")
        self.assertEqual(mm.list_disabled(), [])
        self.assertTrue(mm.is_enabled("anything"))
        self.assertTrue(mm.is_enabled("never-seen"))

    def test_02_ok_when_valid(self):
        self._set_state_file(["a", "b"])
        self.assertEqual(mm.state_health(), "ok")
        self.assertEqual(mm.list_disabled(), ["a", "b"])

    def test_03_invalid_json_corrupt(self):
        with open(self.state_path, "wb") as f:
            f.write(b"not-json{")
        mm.load_state(force=True)
        self.assertEqual(mm.state_health(), "corrupt")
        self.assertIsNone(mm.list_disabled())
        self.assertEqual(mm.get_status("x"), "indeterminate")
        self.assertFalse(mm.is_enabled("x"))

    def test_04_non_dict_corrupt(self):
        with open(self.state_path, "wb") as f:
            f.write(b'["a","b"]')
        mm.load_state(force=True)
        self.assertEqual(mm.state_health(), "corrupt")

    def test_05_missing_version(self):
        with open(self.state_path, "wb") as f:
            f.write(json.dumps({"updated_at": "x", "disabled": []}).encode())
        mm.load_state(force=True)
        self.assertEqual(mm.state_health(), "corrupt")

    def test_06_version_wrong_type(self):
        _write_valid(self.state_path, [], version="1")
        mm.load_state(force=True)
        self.assertEqual(mm.state_health(), "corrupt")

    def test_07_version_wrong_value(self):
        _write_valid(self.state_path, [], version=2)
        mm.load_state(force=True)
        self.assertEqual(mm.state_health(), "corrupt")

    def test_08_missing_updated_at(self):
        with open(self.state_path, "wb") as f:
            f.write(json.dumps({"version": 1, "disabled": []}).encode())
        mm.load_state(force=True)
        self.assertEqual(mm.state_health(), "corrupt")

    def test_09_empty_updated_at(self):
        _write_valid(self.state_path, [], updated_at="")
        mm.load_state(force=True)
        self.assertEqual(mm.state_health(), "corrupt")

    def test_10_disabled_missing(self):
        with open(self.state_path, "wb") as f:
            f.write(json.dumps({"version": 1, "updated_at": "x"}).encode())
        mm.load_state(force=True)
        self.assertEqual(mm.state_health(), "corrupt")

    def test_11_disabled_not_list(self):
        with open(self.state_path, "wb") as f:
            f.write(json.dumps({"version": 1, "updated_at": "x",
                                "disabled": "a"}).encode())
        mm.load_state(force=True)
        self.assertEqual(mm.state_health(), "corrupt")

    def test_12_disabled_element_non_str(self):
        with open(self.state_path, "wb") as f:
            f.write(json.dumps({"version": 1, "updated_at": "x",
                                "disabled": [1, 2]}).encode())
        mm.load_state(force=True)
        self.assertEqual(mm.state_health(), "corrupt")

    def test_13_disabled_element_empty(self):
        with open(self.state_path, "wb") as f:
            f.write(json.dumps({"version": 1, "updated_at": "x",
                                "disabled": [""]}).encode())
        mm.load_state(force=True)
        self.assertEqual(mm.state_health(), "corrupt")

    def test_14_disabled_duplicates(self):
        with open(self.state_path, "wb") as f:
            f.write(json.dumps({"version": 1, "updated_at": "x",
                                "disabled": ["a", "a"]}).encode())
        mm.load_state(force=True)
        self.assertEqual(mm.state_health(), "corrupt")

    def test_15_extra_key_corrupt(self):
        _write_valid(self.state_path, [], extra={"junk": 1})
        mm.load_state(force=True)
        self.assertEqual(mm.state_health(), "corrupt")

    def test_16_tmp_present_makes_corrupt(self):
        self._set_state_file(["a"])
        with open(self.tmp_path, "wb") as f:
            f.write(b"leftover")
        mm.load_state(force=True)
        self.assertEqual(mm.state_health(), "corrupt")
        self.assertIsNone(mm.list_disabled())

    def test_17_unreadable_file(self):
        _write_valid(self.state_path, ["a"])
        real_open = builtins.open

        def failing_open(path, mode="r", *a, **kw):
            if path == self.state_path and "r" in mode:
                raise PermissionError("mock")
            return real_open(path, mode, *a, **kw)

        with mock.patch("builtins.open", side_effect=failing_open):
            mm.load_state(force=True)
        self.assertEqual(mm.state_health(), "unreadable")
        self.assertIsNone(mm.list_disabled())


# ---------- get_status ----------

class TestGetStatus(Base):
    def test_20_ok_disabled(self):
        self._set_state_file(["x"])
        self.assertEqual(mm.get_status("x"), "disabled")

    def test_21_ok_enabled(self):
        self._set_state_file(["x"])
        self.assertEqual(mm.get_status("y"), "enabled")

    def test_22_first_run_enabled(self):
        self.assertEqual(mm.get_status("anything"), "enabled")

    def test_23_corrupt_indeterminate(self):
        with open(self.state_path, "wb") as f:
            f.write(b"junk")
        mm.load_state(force=True)
        self.assertEqual(mm.get_status("x"), "indeterminate")

    def test_24_empty_name(self):
        self._set_state_file([])
        self.assertEqual(mm.get_status(""), "indeterminate")
        self.assertFalse(mm.is_enabled(""))

    def test_25_non_str_name(self):
        self._set_state_file([])
        self.assertEqual(mm.get_status(None), "indeterminate")


# ---------- enable/disable basic ----------

class TestEnableDisable(Base):
    def test_30_first_run_disable_creates_file(self):
        result = mm.disable("x")
        self.assertTrue(result)
        self.assertEqual(mm.state_health(), "ok")
        self.assertEqual(mm.list_disabled(), ["x"])
        self.assertTrue(os.path.exists(self.state_path))

    def test_31_first_run_enable_idempotent_no_file(self):
        # Q7: enable at first_run without change -> True, no file
        result = mm.enable("x")
        self.assertTrue(result)
        self.assertFalse(os.path.exists(self.state_path))
        self.assertEqual(mm.state_health(), "first_run")

    def test_32_ok_disable_adds(self):
        self._set_state_file(["a"])
        self.assertTrue(mm.disable("b"))
        self.assertEqual(mm.list_disabled(), ["a", "b"])

    def test_33_ok_enable_removes(self):
        self._set_state_file(["a", "b"])
        self.assertTrue(mm.enable("a"))
        self.assertEqual(mm.list_disabled(), ["b"])

    def test_34_idempotent_disable_no_write(self):
        self._set_state_file(["x"])
        with mock.patch.object(mm, "_write_state_atomic") as m:
            self.assertTrue(mm.disable("x"))
        m.assert_not_called()

    def test_35_idempotent_enable_no_write(self):
        self._set_state_file([])
        with mock.patch.object(mm, "_write_state_atomic") as m:
            self.assertTrue(mm.enable("x"))
        m.assert_not_called()

    def test_36_corrupt_blocks_writes(self):
        with open(self.state_path, "wb") as f:
            f.write(b"junk")
        mm.load_state(force=True)
        before = open(self.state_path, "rb").read()
        self.assertFalse(mm.disable("x"))
        self.assertFalse(mm.enable("x"))
        after = open(self.state_path, "rb").read()
        self.assertEqual(before, after)

    def test_37_unreadable_blocks_writes(self):
        _write_valid(self.state_path, ["a"])
        real_open = builtins.open

        def failing_open(path, mode="r", *a, **kw):
            if path == self.state_path and "r" in mode:
                raise PermissionError("mock")
            return real_open(path, mode, *a, **kw)

        with mock.patch("builtins.open", side_effect=failing_open):
            mm.load_state(force=True)
            self.assertEqual(mm.state_health(), "unreadable")
            self.assertFalse(mm.disable("y"))

    def test_38_empty_name_false(self):
        self._set_state_file([])
        self.assertFalse(mm.disable(""))
        self.assertFalse(mm.enable(""))

    def test_39_tmp_present_blocks_write(self):
        self._set_state_file(["a"])
        with open(self.tmp_path, "wb") as f:
            f.write(b"leftover")
        # state_health is now corrupt (on reload), but call directly too:
        mm._state_health = "ok"  # force past the corrupt guard for this test
        self.assertFalse(mm.disable("b"))


# ---------- serialization / schema ----------

class TestSchema(Base):
    def test_40_serialize_normalizes(self):
        data = mm._serialize_state({"b", "a", "b", ""})
        parsed = json.loads(data.decode("utf-8"))
        self.assertEqual(parsed["disabled"], ["a", "b"])
        self.assertEqual(parsed["version"], 1)

    def test_41_validate_rejects_duplicates(self):
        raw = json.dumps({"version": 1, "updated_at": "x",
                          "disabled": ["a", "a"]}).encode()
        self.assertFalse(mm._validate_state_bytes(raw))

    def test_42_validate_rejects_extra_key(self):
        raw = json.dumps({"version": 1, "updated_at": "x",
                          "disabled": [], "junk": 1}).encode()
        self.assertFalse(mm._validate_state_bytes(raw))

    def test_43_validate_accepts_good(self):
        raw = mm._serialize_state({"a"})
        self.assertTrue(mm._validate_state_bytes(raw))

    def test_44_load_state_uses_same_validator(self):
        with open(self.state_path, "wb") as f:
            f.write(json.dumps({"version": 2, "updated_at": "x",
                                "disabled": []}).encode())
        mm.load_state(force=True)
        self.assertEqual(mm.state_health(), "corrupt")


# ---------- atomic write ----------

class TestAtomicWrite(Base):
    def test_50_success_writes_file(self):
        self._set_state_file([])
        self.assertTrue(mm.disable("x"))
        with open(self.state_path, "rb") as f:
            raw = f.read()
        self.assertTrue(mm._validate_state_bytes(raw))
        self.assertFalse(os.path.exists(self.tmp_path))

    def test_51_replace_fails_target_unchanged_tmp_removed(self):
        self._set_state_file(["a"])
        with mock.patch("os.replace", side_effect=OSError("mock")):
            self.assertFalse(mm.disable("b"))
        self.assertFalse(os.path.exists(self.tmp_path))
        self.assertEqual(mm.state_health(), "ok")
        self.assertEqual(mm.list_disabled(), ["a"])

    def test_52_replace_post_error_target_new_tmp_present(self):
        self._set_state_file(["a"])
        real = os.replace

        def m(src, dst):
            with open(src, "rb") as f:
                data = f.read()
            real(src, dst)
            with open(src, "wb") as f:
                f.write(data)
            raise OSError("post")

        with mock.patch("os.replace", side_effect=m):
            self.assertFalse(mm.disable("b"))
        self.assertEqual(mm.state_health(), "corrupt")

    def test_53_replace_post_error_target_new_tmp_absent(self):
        self._set_state_file(["a"])
        real = os.replace

        def m(src, dst):
            real(src, dst)
            raise OSError("post")

        with mock.patch("os.replace", side_effect=m):
            self.assertTrue(mm.disable("b"))
        self.assertEqual(mm.state_health(), "ok")
        self.assertEqual(mm.list_disabled(), ["a", "b"])

    def test_54_replace_post_error_third_state(self):
        self._set_state_file(["a"])
        real = os.replace

        def m(src, dst):
            real(src, dst)
            with open(dst, "wb") as f:
                f.write(json.dumps({"version": 1, "updated_at": "zzz",
                                    "disabled": ["third"]}).encode())
            raise OSError("post")

        with mock.patch("os.replace", side_effect=m):
            self.assertFalse(mm.disable("b"))

    def test_55_tmp_write_fails_target_unchanged(self):
        self._set_state_file(["a"])
        real_open = builtins.open

        def failing_open(path, mode="r", *a, **kw):
            if path == self.tmp_path and "w" in mode:
                raise OSError("mock write fail")
            return real_open(path, mode, *a, **kw)

        before = open(self.state_path, "rb").read()
        with mock.patch("builtins.open", side_effect=failing_open):
            self.assertFalse(mm.disable("b"))
        after = open(self.state_path, "rb").read()
        self.assertEqual(before, after)
        self.assertEqual(mm.state_health(), "ok")

    def test_56_target_not_written_directly(self):
        # Ensure target is never opened in write modes
        self._set_state_file([])
        real_open = builtins.open
        seen_writes = []

        def spy_open(path, mode="r", *a, **kw):
            if path == self.state_path and any(c in mode for c in "wax"):
                seen_writes.append((path, mode))
            return real_open(path, mode, *a, **kw)

        with mock.patch("builtins.open", side_effect=spy_open):
            mm.disable("x")
        self.assertEqual(seen_writes, [])


# ---------- recovery ----------

class TestRecovery(Base):
    def test_60_no_confirm_false(self):
        with open(self.state_path, "wb") as f:
            f.write(b"junk")
        mm.load_state(force=True)
        with mock.patch.object(mm, "load_state", wraps=mm.load_state) as spy:
            spy.reset_mock()
            self.assertFalse(mm.recover_to_fresh())
            self.assertEqual(spy.call_count, 0)

    def test_61_at_ok_false(self):
        self._set_state_file(["a"])
        self.assertFalse(mm.recover_to_fresh(confirm=True))

    def test_62_at_first_run_false(self):
        self.assertFalse(mm.recover_to_fresh(confirm=True))
        self.assertEqual(mm.state_health(), "first_run")

    def test_63_corrupt_valid_target_keeps_it(self):
        self._set_state_file(["a", "b"])
        with open(self.tmp_path, "wb") as f:
            f.write(b"leftover")
        mm.load_state(force=True)
        self.assertEqual(mm.state_health(), "corrupt")
        self.assertTrue(mm.recover_to_fresh(confirm=True))
        self.assertEqual(mm.state_health(), "ok")
        self.assertEqual(mm.list_disabled(), ["a", "b"])
        self.assertFalse(os.path.exists(self.tmp_path))
        stale = [f for f in os.listdir(self.tmpdir) if ".tmp.stale_" in f]
        self.assertEqual(len(stale), 1)

    def test_64_corrupt_invalid_target_full_recovery(self):
        with open(self.state_path, "wb") as f:
            f.write(b"junk")
        mm.load_state(force=True)
        self.assertTrue(mm.recover_to_fresh(confirm=True))
        self.assertEqual(mm.state_health(), "ok")
        self.assertEqual(mm.list_disabled(), [])
        backups = [f for f in os.listdir(self.tmpdir) if ".corrupt_" in f]
        self.assertEqual(len(backups), 1)

    def test_65_missing_target_with_tmp(self):
        with open(self.tmp_path, "wb") as f:
            f.write(b"leftover")
        mm.load_state(force=True)
        self.assertEqual(mm.state_health(), "corrupt")
        self.assertTrue(mm.recover_to_fresh(confirm=True))
        self.assertEqual(mm.state_health(), "ok")
        self.assertEqual(mm.list_disabled(), [])

    def test_66_backup_name_collision(self):
        with open(self.state_path, "wb") as f:
            f.write(b"junk")
        # pre-create a decoy backup with same timestamp prefix
        existing = [f for f in os.listdir(self.tmpdir)]
        decoy = self.state_path + ".corrupt_20200101T000000Z"
        with open(decoy, "wb") as f:
            f.write(b"decoy")
        mm.load_state(force=True)
        self.assertTrue(mm.recover_to_fresh(confirm=True))
        # decoy untouched, new backup created
        with open(decoy, "rb") as f:
            self.assertEqual(f.read(), b"decoy")

    def test_67_no_sync_on_early_return(self):
        self._set_state_file(["a"])  # ok
        with mock.patch.object(mm, "load_state", wraps=mm.load_state) as spy:
            spy.reset_mock()
            mm.recover_to_fresh(confirm=True)
            self.assertEqual(spy.call_count, 0)


# ---------- invariants ----------

class TestInvariants(Base):
    def test_70_I4_memory_matches_disk_after_ops(self):
        self._set_state_file([])
        mm.disable("a")
        s1 = (mm.state_health(), mm.list_disabled(),
              mm.get_status("a"), mm.get_status("b"))
        mm.load_state(force=True)
        s2 = (mm.state_health(), mm.list_disabled(),
              mm.get_status("a"), mm.get_status("b"))
        self.assertEqual(s1, s2)

    def test_71_I10_sync_after_fs_touch(self):
        self._set_state_file([])
        with mock.patch.object(mm, "load_state", wraps=mm.load_state) as spy:
            spy.reset_mock()
            mm.disable("x")
            self.assertGreaterEqual(spy.call_count, 1)

    def test_72_I7_tmp_left_when_target_not_old(self):
        self._set_state_file(["a"])

        def m(src, dst):
            # Do NOT invoke real os.replace. Simulate an external writer
            # that changed the target to a third state, plus a failing
            # replace syscall. Source (tmp) is intentionally left untouched.
            with open(dst, "wb") as f:
                f.write(json.dumps({"version": 1, "updated_at": "zzz",
                                    "disabled": ["third"]}).encode())
            raise OSError("post")

        with mock.patch("os.replace", side_effect=m):
            result = mm.disable("b")

        self.assertFalse(result)
        # I7: code must NOT remove .tmp when target is neither old nor new.
        self.assertTrue(os.path.exists(self.tmp_path))
        # .tmp still holds the intended new state (validated by schema v0).
        with open(self.tmp_path, "rb") as f:
            tmp_raw = f.read()
        self.assertTrue(mm._validate_state_bytes(tmp_raw))


    def test_73_unknown_name_is_enabled_status_but_not_permission(self):
        self._set_state_file([])
        # is_enabled returns True for unknown name; that is NOT a permission.
        self.assertTrue(mm.is_enabled("nonexistent"))
        self.assertEqual(mm.get_status("nonexistent"), "enabled")


if __name__ == "__main__":
    unittest.main(verbosity=2)
