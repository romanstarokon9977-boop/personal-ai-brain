import json
import os
import tempfile
import unittest

from memory.backup_restore import (
    MemoryBackupError,
    create_snapshot,
    restore_snapshot,
    verify_snapshot,
)


class MemoryBackupRestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="memory_backup_restore_")
        self.memory_file = os.path.join(self.tmp, "brain_memory.json")
        self.backup_dir = os.path.join(self.tmp, "backups_memory")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_memory(self, entries):
        with open(self.memory_file, "w", encoding="utf-8") as handle:
            json.dump({"version": 2, "entries": entries}, handle, ensure_ascii=False)

    def _read_memory(self):
        with open(self.memory_file, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_snapshot_has_sha256_manifest_and_verifies(self):
        self._write_memory([{"id": "one", "text": "first"}])
        snapshot = create_snapshot(self.memory_file, self.backup_dir)
        result = verify_snapshot(snapshot, self.backup_dir)
        self.assertTrue(result["ok"])
        self.assertEqual(result["entries"], 1)
        self.assertTrue(os.path.isfile(snapshot + ".sha256"))

    def test_tampered_snapshot_is_rejected_before_restore(self):
        self._write_memory([{"id": "one", "text": "first"}])
        snapshot = create_snapshot(self.memory_file, self.backup_dir)
        with open(snapshot, "ab") as handle:
            handle.write(b" ")
        with self.assertRaisesRegex(MemoryBackupError, "BACKUP_CHECKSUM_MISMATCH"):
            verify_snapshot(snapshot, self.backup_dir)

    def test_restore_is_atomic_verified_and_snapshots_current_memory(self):
        self._write_memory([{"id": "old", "text": "restore target"}])
        snapshot = create_snapshot(self.memory_file, self.backup_dir)
        self._write_memory([{"id": "new", "text": "current value"}])
        result = restore_snapshot(self.memory_file, snapshot, self.backup_dir)
        self.assertTrue(result["ok"])
        self.assertEqual(self._read_memory()["entries"][0]["id"], "old")
        snapshots = [name for name in os.listdir(self.backup_dir) if name.endswith(".json")]
        self.assertGreaterEqual(len(snapshots), 2)
        for name in snapshots:
            self.assertTrue(os.path.isfile(os.path.join(self.backup_dir, name + ".sha256")))

    def test_restore_can_repair_corrupt_current_file(self):
        self._write_memory([{"id": "valid", "text": "known good"}])
        snapshot = create_snapshot(self.memory_file, self.backup_dir)
        with open(self.memory_file, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        result = restore_snapshot(self.memory_file, snapshot, self.backup_dir)
        self.assertTrue(result["ok"])
        self.assertEqual(self._read_memory()["entries"][0]["id"], "valid")

    def test_path_traversal_is_rejected(self):
        with self.assertRaises(MemoryBackupError):
            verify_snapshot(os.path.join(self.tmp, "outside.json"), self.backup_dir)

    def test_invalid_source_is_not_backed_up(self):
        with open(self.memory_file, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        with self.assertRaisesRegex(MemoryBackupError, "MEMORY_SOURCE_READ_FAILED|BACKUP_JSON_INVALID"):
            create_snapshot(self.memory_file, self.backup_dir)
        self.assertFalse(os.path.exists(self.backup_dir))


if __name__ == "__main__":
    unittest.main(verbosity=2)
