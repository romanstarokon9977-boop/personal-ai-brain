"""Изолированные тесты безопасности и согласованности chat_system.py."""

import importlib.util
import os
import tempfile
import unittest
import uuid
from unittest import mock


ROOT = os.path.dirname(os.path.abspath(__file__))
SPEC = importlib.util.spec_from_file_location(
    "chat_system_under_test",
    os.path.join(ROOT, "chat_system.py"),
)
cs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cs)


class ChatSystemSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_chats_dir = cs.CHATS_DIR
        self.old_index_file = cs.INDEX_FILE
        cs.CHATS_DIR = os.path.join(self.temp.name, "chats")
        cs.INDEX_FILE = os.path.join(cs.CHATS_DIR, "index.json")
        os.makedirs(cs.CHATS_DIR, exist_ok=True)

    def tearDown(self):
        cs.CHATS_DIR = self.old_chats_dir
        cs.INDEX_FILE = self.old_index_file
        self.temp.cleanup()

    def make_chat(self, title="Test"):
        chat = cs.create_new_chat(title=title)
        self.assertIsInstance(chat, dict)
        return chat

    def test_rejects_path_traversal_for_all_public_operations(self):
        outside = os.path.join(self.temp.name, "outside.json")
        with open(outside, "w", encoding="utf-8") as f:
            f.write("do-not-touch")

        bad_id = "../../outside"
        self.assertIsNone(cs.load_chat(bad_id))
        self.assertFalse(cs.save_chat({"id": bad_id, "messages": []}))
        self.assertFalse(cs.rename_chat(bad_id, "changed"))
        self.assertFalse(cs.delete_chat(bad_id))
        self.assertFalse(cs.set_active_chat(bad_id))

        with open(outside, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "do-not-touch")

    def test_rejects_chat_symlink_that_resolves_outside_directory(self):
        chat_id = str(uuid.uuid4())
        outside = os.path.join(self.temp.name, "outside.json")
        with open(outside, "w", encoding="utf-8") as f:
            f.write('{"id": "%s", "messages": []}' % chat_id)

        link_path = os.path.join(cs.CHATS_DIR, chat_id + ".json")
        try:
            os.symlink(outside, link_path)
        except (OSError, NotImplementedError) as exc:
            self.skipTest("Symlinks unavailable in this environment: %s" % exc)

        self.assertIsNone(cs.load_chat(chat_id))
        self.assertFalse(cs.set_active_chat(chat_id))
        self.assertFalse(cs.delete_chat(chat_id))
        self.assertTrue(os.path.islink(link_path))
        self.assertTrue(os.path.exists(outside))

    def test_create_removes_chat_file_if_index_save_fails(self):
        with mock.patch.object(cs, "save_index", return_value=False):
            self.assertIsNone(cs.create_new_chat("No index"))

        remaining = [
            name for name in os.listdir(cs.CHATS_DIR)
            if name.endswith(".json")
        ]
        self.assertEqual(remaining, [])

    def test_rename_rolls_back_chat_file_if_index_save_fails(self):
        chat = self.make_chat("Original")

        with mock.patch.object(cs, "save_index", return_value=False):
            self.assertFalse(cs.rename_chat(chat["id"], "Changed"))

        loaded = cs.load_chat(chat["id"])
        self.assertEqual(loaded["title"], "Original")

    def test_delete_keeps_chat_if_index_save_fails(self):
        chat = self.make_chat("Keep me")
        path = os.path.join(cs.CHATS_DIR, chat["id"] + ".json")

        with mock.patch.object(cs, "save_index", return_value=False):
            self.assertFalse(cs.delete_chat(chat["id"]))

        self.assertTrue(os.path.isfile(path))
        self.assertEqual(cs.load_chat(chat["id"])["title"], "Keep me")

    def test_invalid_identifier_is_rejected_without_side_effects(self):
        for invalid in ("", None, "../x", "not-a-uuid", "/tmp/other"):
            with self.subTest(invalid=invalid):
                self.assertIsNone(cs._chat_path(invalid))
                self.assertIsNone(cs.load_chat(invalid))
                self.assertFalse(cs.delete_chat(invalid))

    def test_corrupt_index_is_preserved_and_mutations_fail_closed(self):
        chat = self.make_chat("Protected")
        chat_path = os.path.join(cs.CHATS_DIR, chat["id"] + ".json")
        with open(chat_path, "rb") as f:
            original_chat = f.read()

        corrupt_bytes = b'{"version": 1, "chats": ['
        with open(cs.INDEX_FILE, "wb") as f:
            f.write(corrupt_bytes)

        self.assertIsNone(cs.create_new_chat("Must not be created"))
        self.assertFalse(cs.rename_chat(chat["id"], "Must not rename"))
        self.assertFalse(cs.delete_chat(chat["id"]))
        self.assertFalse(cs.set_active_chat(chat["id"]))
        self.assertIsNone(cs.load_or_create_active_chat())

        with open(cs.INDEX_FILE, "rb") as f:
            self.assertEqual(f.read(), corrupt_bytes)
        with open(chat_path, "rb") as f:
            self.assertEqual(f.read(), original_chat)

        chat_files = [
            name for name in os.listdir(cs.CHATS_DIR)
            if name.endswith(".json") and name != "index.json"
        ]
        self.assertEqual(chat_files, [chat["id"] + ".json"])

    def test_invalid_index_structure_is_rejected_for_updates(self):
        chat = self.make_chat("Existing")
        invalid_indexes = (
            b'{"version": 1, "chats": {}}',
            b'{"version": 1, "chats": [], "active_chat_id": "../bad"}',
            b'{"version": 1, "chats": [], "active_chat_id": "00000000-0000-0000-0000-000000000001"}',
            b'{"version": 1, "chats": [{"id": "not-a-uuid"}]}',
            b'{"version": 1, "chats": [{"id": "00000000-0000-0000-0000-000000000001"}, '
            b'{"id": "00000000-0000-0000-0000-000000000001"}]}',
        )
        for raw in invalid_indexes:
            with self.subTest(raw=raw):
                with open(cs.INDEX_FILE, "wb") as f:
                    f.write(raw)
                self.assertFalse(cs.set_active_chat(chat["id"]))
                self.assertIsNone(cs.create_new_chat("Must not be created"))
                with open(cs.INDEX_FILE, "rb") as f:
                    self.assertEqual(f.read(), raw)

    def test_normal_create_rename_delete_flow(self):
        chat = self.make_chat("Before")
        self.assertTrue(cs.rename_chat(chat["id"], "After"))
        self.assertEqual(cs.load_chat(chat["id"])["title"], "After")
        self.assertTrue(cs.delete_chat(chat["id"]))
        self.assertIsNone(cs.load_chat(chat["id"]))


if __name__ == "__main__":
    unittest.main()
