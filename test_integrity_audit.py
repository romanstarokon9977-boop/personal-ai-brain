import hashlib
import json
import os
import shutil
import tempfile
import unittest

from integrity_audit import (
    collect_integrity_report,
    inspect_backup_directory,
    inspect_file,
    validate_memory_payload,
    validate_module_state,
    validate_task_payload,
)


class IntegrityAuditTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="brain_integrity_")
        self.memory = os.path.join(self.root, "brain_memory.json")
        self.tasks = os.path.join(self.root, "tasks.json")
        self.modules = os.path.join(self.root, "module_state.json")
        self.backups = os.path.join(self.root, "backups")
        self.project = os.path.join(self.root, "project")
        os.makedirs(self.project)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write_json(self, path, payload):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def _valid_stores(self):
        self._write_json(self.memory, {"version": 2, "entries": [{"id": "m1"}]})
        self._write_json(self.tasks, {"schema_version": 1, "tasks": [{"id": "t1", "status": "pending"}]})
        self._write_json(self.modules, {"version": 1, "updated_at": "2026-11-27T00:00:00Z", "disabled": []})

    def test_valid_store_schemas(self):
        self.assertTrue(validate_memory_payload(b'{"version":2,"entries":[]}'))
        self.assertTrue(validate_task_payload(b'{"schema_version":1,"tasks":[]}'))
        self.assertTrue(validate_module_state(b'{"version":1,"updated_at":"now","disabled":[]}'))

    def test_invalid_json_and_duplicate_ids_rejected(self):
        self.assertFalse(validate_memory_payload(b"{broken"))
        self.assertFalse(validate_memory_payload(b'{"version":2,"entries":[{"id":"x"},{"id":"x"}]}'))
        self.assertFalse(validate_task_payload(b'{"schema_version":1,"tasks":[{"id":"x","status":"other"}]}'))

    def test_expected_hash_detects_unexpected_change(self):
        path = os.path.join(self.project, "brain.py")
        with open(path, "wb") as handle:
            handle.write(b"trusted")
        expected = hashlib.sha256(b"trusted").hexdigest()
        self.assertEqual(inspect_file("brain", path, expected_sha256=expected)["status"], "OK")
        with open(path, "wb") as handle:
            handle.write(b"changed")
        result = inspect_file("brain", path, expected_sha256=expected)
        self.assertEqual(result["status"], "CHANGED")
        self.assertEqual(result["baseline"], "MISMATCH")

    def test_symlink_is_rejected_without_following(self):
        target = os.path.join(self.root, "target")
        with open(target, "wb") as handle:
            handle.write(b"secret")
        link = os.path.join(self.root, "link")
        os.symlink(target, link)
        self.assertEqual(inspect_file("linked", link)["status"], "UNSAFE_SYMLINK")

    def test_backup_snapshot_and_manifest_verified(self):
        from memory.backup_restore import create_snapshot
        self._write_json(self.memory, {"version": 2, "entries": [{"id": "m1"}]})
        create_snapshot(self.memory, self.backups)
        result = inspect_backup_directory(self.backups)
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["verified_count"], 1)

    def test_corrupt_backup_is_reported(self):
        from memory.backup_restore import create_snapshot
        self._write_json(self.memory, {"version": 2, "entries": [{"id": "m1"}]})
        snapshot = create_snapshot(self.memory, self.backups)
        with open(snapshot, "ab") as handle:
            handle.write(b"tamper")
        self.assertEqual(inspect_backup_directory(self.backups)["status"], "INVALID_BACKUPS")

    def test_report_is_read_only_and_does_not_expose_paths(self):
        self._valid_stores()
        for name in ("brain.py", "tool_registry.py", "verifier.py", "task_manager.py", "module_manager.py", "self_inspection.py"):
            with open(os.path.join(self.project, name), "w", encoding="utf-8") as handle:
                handle.write("# test")
        os.makedirs(os.path.join(self.project, "memory"))
        with open(os.path.join(self.project, "memory", "memory_core.py"), "w", encoding="utf-8") as handle:
            handle.write("# test")
        before = set(os.listdir(self.root))
        report = collect_integrity_report(
            project_root=self.project, memory_file=self.memory, task_file=self.tasks,
            module_state_file=self.modules, backup_dir=self.backups,
        )
        self.assertTrue(report["read_only"])
        self.assertNotIn(self.root, json.dumps(report))
        self.assertEqual(set(os.listdir(self.root)), before)
        self.assertEqual(report["status"], "WARNING")  # no trusted code baseline yet

    def test_missing_backup_directory_is_warning_not_mutation(self):
        result = inspect_backup_directory(self.backups)
        self.assertEqual(result["status"], "NO_BACKUP_DIRECTORY")
        self.assertFalse(os.path.exists(self.backups))


if __name__ == "__main__":
    unittest.main(verbosity=2)
