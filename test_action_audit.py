import json
import os
import tempfile
import unittest

from action_audit import record_tool_event


class ActionAuditTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="brain_action_audit_")
        self.path = os.path.join(self.root, "audit", "actions.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def test_records_authorization_and_outcome_without_payloads(self):
        result = record_tool_event(
            "read_file", "AUTO", "policy_auto", "READ_ONLY_ALLOWLIST", "SUCCESS",
            elapsed_ms=12, path=self.path,
        )
        self.assertTrue(result["ok"])
        with open(self.path, encoding="utf-8") as handle:
            event = json.loads(handle.readline())
        self.assertEqual(event["tool"], "READ_FILE")
        self.assertEqual(event["decision"], "AUTO")
        self.assertEqual(event["permission_source"], "POLICY_AUTO")
        self.assertEqual(event["authorization_reason"], "READ_ONLY_ALLOWLIST")
        self.assertEqual(event["outcome"], "SUCCESS")
        self.assertEqual(event["elapsed_ms"], 12)
        self.assertNotIn("arguments", event)
        self.assertNotIn("result", event)
        self.assertNotIn("prompt", event)

    def test_secret_values_and_tool_payload_are_never_written(self):
        record_tool_event(
            "write_file", "CONFIRM", "user_confirmed", "USER_APPROVED", "FAILED",
            error_code="API_KEY=super-secret-value", path=self.path,
        )
        with open(self.path, encoding="utf-8") as handle:
            raw = handle.read()
        self.assertNotIn("super-secret-value", raw)
        self.assertNotIn("arguments", raw)
        self.assertNotIn("content", raw)

    def test_appends_multiple_events_as_independent_json_lines(self):
        for index in range(3):
            self.assertTrue(record_tool_event(
                "directory_list", "AUTO", "policy_auto", "READ_ONLY_ALLOWLIST", "SUCCESS",
                elapsed_ms=index, path=self.path,
            )["ok"])
        with open(self.path, encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle]
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({row["event_id"] for row in rows}), 3)

    def test_invalid_tool_name_fails_without_creating_log(self):
        result = record_tool_event("", "AUTO", "policy_auto", "NONE", "SUCCESS", path=self.path)
        self.assertFalse(result["ok"])
        self.assertFalse(os.path.exists(self.path))


if __name__ == "__main__":
    unittest.main(verbosity=2)
