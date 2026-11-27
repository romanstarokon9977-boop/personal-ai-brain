import unittest
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
