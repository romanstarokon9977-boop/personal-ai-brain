import json
import os
import shutil
import tempfile
import unittest

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    AESGCM = None

from memory.encrypted_backup import (
    EncryptedBackupError,
    create_encrypted_backup,
    decrypt_backup_to_directory,
    inspect_encrypted_backup,
)


@unittest.skipIf(AESGCM is None, "cryptography optional dependency not installed")
class EncryptedBackupTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="brain_encrypted_backup_")
        self.memory = os.path.join(self.root, "brain_memory.json")
        self.tasks = os.path.join(self.root, "tasks.json")
        self.modules = os.path.join(self.root, "module_state.json")
        self.export = os.path.join(self.root, "portable.pabenc")
        with open(self.memory, "w", encoding="utf-8") as handle:
            json.dump({"version": 2, "entries": [{"id": "m1", "text": "PRIVATE_MEMORY_MARKER"}]}, handle)
        with open(self.tasks, "w", encoding="utf-8") as handle:
            json.dump({"schema_version": 1, "tasks": [{"id": "t1", "status": "pending"}]}, handle)
        with open(self.modules, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "updated_at": "now", "disabled": []}, handle)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_encrypted_export_round_trip_to_staging_only(self):
        result = create_encrypted_backup(
            self.memory, self.tasks, self.export, "correct horse battery staple",
            module_state_file=self.modules,
        )
        self.assertTrue(result["ok"])
        with open(self.export, "rb") as handle:
            encrypted = handle.read()
        self.assertNotIn(b"PRIVATE_MEMORY_MARKER", encrypted)
        metadata = inspect_encrypted_backup(self.export, "correct horse battery staple")
        self.assertTrue(metadata["authenticated"])
        staging = os.path.join(self.root, "staging")
        restored = decrypt_backup_to_directory(
            self.export, staging, "correct horse battery staple"
        )
        self.assertFalse(restored["live_stores_modified"])
        with open(os.path.join(staging, "memory.json"), encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(data["entries"][0]["text"], "PRIVATE_MEMORY_MARKER")
        self.assertTrue(os.path.isfile(os.path.join(staging, "tasks.json")))
        self.assertTrue(os.path.isfile(os.path.join(staging, "module_state.json")))

    def test_wrong_passphrase_is_rejected(self):
        create_encrypted_backup(self.memory, self.tasks, self.export, "correct horse battery staple")
        with self.assertRaisesRegex(EncryptedBackupError, "BACKUP_AUTHENTICATION_FAILED"):
            inspect_encrypted_backup(self.export, "incorrect horse battery staple")

    def test_ciphertext_tampering_is_rejected(self):
        create_encrypted_backup(self.memory, self.tasks, self.export, "correct horse battery staple")
        with open(self.export, "r+b") as handle:
            handle.seek(-1, os.SEEK_END)
            byte = handle.read(1)
            handle.seek(-1, os.SEEK_END)
            handle.write(bytes([byte[0] ^ 1]))
        with self.assertRaisesRegex(EncryptedBackupError, "BACKUP_AUTHENTICATION_FAILED"):
            inspect_encrypted_backup(self.export, "correct horse battery staple")

    def test_existing_export_is_never_overwritten(self):
        with open(self.export, "wb") as handle:
            handle.write(b"existing")
        with self.assertRaisesRegex(EncryptedBackupError, "DESTINATION_ALREADY_EXISTS"):
            create_encrypted_backup(self.memory, self.tasks, self.export, "correct horse battery staple")
        with open(self.export, "rb") as handle:
            self.assertEqual(handle.read(), b"existing")

    def test_invalid_memory_is_not_exported(self):
        with open(self.memory, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        with self.assertRaisesRegex(EncryptedBackupError, "MEMORY_SCHEMA_INVALID"):
            create_encrypted_backup(self.memory, self.tasks, self.export, "correct horse battery staple")
        self.assertFalse(os.path.exists(self.export))

    def test_short_passphrase_is_rejected(self):
        with self.assertRaisesRegex(EncryptedBackupError, "PASSPHRASE_TOO_SHORT"):
            create_encrypted_backup(self.memory, self.tasks, self.export, "short")

    def test_staging_directory_must_be_new(self):
        create_encrypted_backup(self.memory, self.tasks, self.export, "correct horse battery staple")
        staging = os.path.join(self.root, "staging")
        os.makedirs(staging)
        with self.assertRaisesRegex(EncryptedBackupError, "STAGING_DIRECTORY_ALREADY_EXISTS"):
            decrypt_backup_to_directory(self.export, staging, "correct horse battery staple")


if __name__ == "__main__":
    unittest.main(verbosity=2)
