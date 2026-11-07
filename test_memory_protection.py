#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0.1.1 isolated tests. Real memory untouched, uses tempfile."""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.expanduser("~/personal_ai_brain"))
from memory import memory_core


class Base(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="mem_test_")
        self.memfile = os.path.join(self.tmpdir, "brain_memory.json")
        self.backupdir = os.path.join(self.tmpdir, "backups_memory")
        self._patches = [
            mock.patch.object(memory_core, "MEMORY_FILE", self.memfile),
            mock.patch.object(memory_core, "__file__",
                              os.path.join(self.tmpdir, "memory", "memory_core.py")),
            mock.patch.object(memory_core, "_BACKUP_KEEP", 3),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, data):
        with open(self.memfile, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def _sha(self):
        if not os.path.exists(self.memfile):
            return None
        with open(self.memfile, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def _valid_empty(self):
        return {"version": 2, "entries": []}

    def _valid_with(self, n):
        return {"version": 2, "entries": [
            {"id": f"id{i}", "timestamp": "2026-01-01 00:00:00",
             "text": f"уникальный_текст_{i}_zzz", "category": "facts",
             "importance": 0.5, "source": "user", "topics": []}
            for i in range(n)
        ]}


class TestMemoryProtection(Base):
    def test_01_load_raw_ok(self):
        self._write(self._valid_with(37))
        r = memory_core._load_raw()
        self.assertIsNotNone(r)
        self.assertEqual(r["version"], 2)
        self.assertEqual(len(r["entries"]), 37)

    def test_02_load_raw_empty(self):
        self._write(self._valid_empty())
        r = memory_core._load_raw()
        self.assertIsNotNone(r)
        self.assertEqual(r["version"], 2)
        self.assertEqual(r["entries"], [])

    def test_03_load_raw_corrupt_json(self):
        with open(self.memfile, "w", encoding="utf-8") as f:
            f.write("{ not valid")
        self.assertIsNone(memory_core._load_raw())

    def test_04_load_raw_permission_error(self):
        self._write(self._valid_empty())
        real_open = open
        def fake_open(path, *a, **kw):
            if path == self.memfile:
                raise PermissionError("mock read")
            return real_open(path, *a, **kw)
        with mock.patch("builtins.open", side_effect=fake_open):
            r = memory_core._load_raw()
        self.assertIsNone(r)

    def test_05_add_memory_refuses_on_corrupt(self):
        with open(self.memfile, "w", encoding="utf-8") as f:
            f.write("{ corrupted")
        sha_before = self._sha()
        result = memory_core.add_memory("новый_уникальный_факт_zzz1", category="facts")
        sha_after = self._sha()
        self.assertTrue(result.startswith("MEMORY_READ_FAILED"), f"got: {result}")
        self.assertEqual(sha_before, sha_after)

    def test_06_save_raw_tmp_error(self):
        self._write(self._valid_with(5))
        sha_before = self._sha()
        new_data = self._valid_with(6)
        real_open = open
        def fake_open(path, mode="r", *a, **kw):
            if path == self.memfile + ".tmp" and "w" in mode:
                raise PermissionError("mock write")
            return real_open(path, mode, *a, **kw)
        with mock.patch("builtins.open", side_effect=fake_open):
            with self.assertRaises(memory_core.MemoryWriteError):
                memory_core._save_raw(new_data)
        self.assertEqual(sha_before, self._sha())

    def test_07_save_raw_replace_error(self):
        self._write(self._valid_with(5))
        sha_before = self._sha()
        new_data = self._valid_with(6)
        with mock.patch("os.replace", side_effect=OSError("mock replace")):
            with self.assertRaises(memory_core.MemoryWriteError):
                memory_core._save_raw(new_data)
        self.assertEqual(sha_before, self._sha())

    def test_08_save_raw_success_backup_before(self):
        self._write(self._valid_with(5))
        new_data = self._valid_with(6)
        memory_core._save_raw(new_data)
        self.assertTrue(os.path.isdir(self.backupdir))
        backups = sorted(
            name for name in os.listdir(self.backupdir) if name.endswith(".json")
        )
        self.assertGreaterEqual(len(backups), 1)
        with open(os.path.join(self.backupdir, backups[-1]), "r", encoding="utf-8") as f:
            backup = json.load(f)
        self.assertTrue(os.path.isfile(os.path.join(self.backupdir, backups[-1] + ".sha256")))
        self.assertEqual(len(backup["entries"]), 5)
        with open(self.memfile, "r", encoding="utf-8") as f:
            current = json.load(f)
        self.assertEqual(len(current["entries"]), 6)

    def test_09_no_data_loss_on_read_error(self):
        self._write(self._valid_with(37))
        sha_before = self._sha()
        real_open = open
        def fake_open(path, *a, **kw):
            if path == self.memfile:
                raise PermissionError("mock read")
            return real_open(path, *a, **kw)
        with mock.patch("builtins.open", side_effect=fake_open):
            result = memory_core.add_memory("новый_уникальный_факт_zzz2", category="facts")
        self.assertTrue(result.startswith("MEMORY_READ_FAILED"), f"got: {result}")
        self.assertEqual(sha_before, self._sha())
        with open(self.memfile, "r", encoding="utf-8") as f:
            still_there = json.load(f)
        self.assertEqual(len(still_there["entries"]), 37)

    def test_10_load_memory_raises_on_corrupt(self):
        with open(self.memfile, "w", encoding="utf-8") as f:
            f.write("{ corrupted")
        with self.assertRaises(memory_core.MemoryReadError):
            memory_core.load_memory()

    def test_11_backup_failure_does_not_touch_target(self):
        """GAP-5: backup failure in _save_raw must not modify the target file."""
        self._write(self._valid_with(5))
        sha_before = self._sha()
        self.assertIsNotNone(sha_before)
        new_data = self._valid_with(6)
        with mock.patch.object(
            memory_core,
            "_backup_memory_snapshot",
            side_effect=memory_core.MemoryWriteError("mock backup failure"),
        ):
            with self.assertRaises(memory_core.MemoryWriteError):
                memory_core._save_raw(new_data)
        self.assertEqual(sha_before, self._sha())

if __name__ == "__main__":
    unittest.main(verbosity=2)
