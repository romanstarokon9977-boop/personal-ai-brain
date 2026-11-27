import unittest
import contextlib
import io
import warnings
from unittest.mock import patch

import brain


class HiddenPassphrasePromptTests(unittest.TestCase):
    def test_missing_controlling_tty_fails_before_prompt(self):
        with patch("os.open", side_effect=OSError("no tty")):
            with patch("getpass.getpass") as prompt:
                with self.assertRaises(OSError):
                    brain._read_hidden_passphrase("secret: ")
                prompt.assert_not_called()

    def test_verify_command_authenticates_without_writing(self):
        with patch("builtins.input", return_value="/tmp/backup.pabenc"):
            with patch("brain._read_hidden_passphrase", return_value="long secure passphrase"):
                with patch(
                    "memory.encrypted_backup.inspect_encrypted_backup",
                    return_value={"ok": True, "authenticated": True, "files": ["memory.json", "tasks.json"], "created_at": "now"},
                ) as inspect:
                    with contextlib.redirect_stdout(io.StringIO()):
                        result = brain.handle_encrypted_backup_verify_command()
        self.assertTrue(result["ok"])
        inspect.assert_called_once_with("/tmp/backup.pabenc", "long secure passphrase")

    def test_decrypt_command_only_creates_staging_copy(self):
        with patch("builtins.input", side_effect=["/tmp/backup.pabenc", "/tmp/staging"]):
            with patch("brain._read_hidden_passphrase", side_effect=["long secure passphrase", "long secure passphrase"]):
                with patch(
                    "memory.encrypted_backup.decrypt_backup_to_directory",
                    return_value={
                        "ok": True, "staging_directory": "/tmp/staging",
                        "restored_files": ["memory.json", "tasks.json"],
                        "live_stores_modified": False,
                    },
                ) as decrypt:
                    with contextlib.redirect_stdout(io.StringIO()):
                        result = brain.handle_encrypted_backup_decrypt_command()
        self.assertTrue(result["ok"])
        self.assertFalse(result["live_stores_modified"])
        decrypt.assert_called_once_with(
            "/tmp/backup.pabenc", "/tmp/staging", "long secure passphrase"
        )

    def test_decrypt_command_rejects_mismatched_passphrases(self):
        with patch("builtins.input", side_effect=["/tmp/backup.pabenc", "/tmp/staging"]):
            with patch("brain._read_hidden_passphrase", side_effect=["first long passphrase", "second long passphrase"]):
                with patch("memory.encrypted_backup.decrypt_backup_to_directory") as decrypt:
                    with contextlib.redirect_stdout(io.StringIO()):
                        result = brain.handle_encrypted_backup_decrypt_command()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "PASSPHRASE_MISMATCH")
        decrypt.assert_not_called()

    def test_echo_fallback_warning_is_fatal(self):
        import getpass
        with patch("os.open", return_value=123):
            with patch("termios.tcgetattr", return_value=[]):
                with patch("os.close"):
                    with patch(
                        "getpass.getpass",
                        side_effect=lambda prompt: warnings.warn(
                            "echo fallback", getpass.GetPassWarning
                        ),
                    ):
                        with self.assertRaises(getpass.GetPassWarning):
                            brain._read_hidden_passphrase("secret: ")


if __name__ == "__main__":
    unittest.main(verbosity=2)
