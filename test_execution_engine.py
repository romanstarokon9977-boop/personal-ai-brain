import unittest

import planner
import execution_engine


def make_plan():
    return planner.validate_plan("Собрать отчёт", [
        {
            "id": "step_read",
            "title": "Сбор данных",
            "description": "Прочитать исходные данные",
            "depends_on": [],
            "acceptance_criteria": ["Данные прочитаны"],
        },
        {
            "id": "step_report",
            "title": "Подготовить отчёт",
            "description": "Сформировать отчёт на основе данных",
            "depends_on": ["step_read"],
            "acceptance_criteria": ["Отчёт сформирован"],
        },
    ])


def passing_verifier(step, outcome):
    criterion_id = step["acceptance_criteria"][0]["id"]
    return {
        "status": "PASS",
        "evidence": {
            criterion_id: {
                "passed": True,
                "evidence": "Независимое подтверждение: PASS",
            }
        },
    }


class RetryPolicyTests(unittest.TestCase):
    def test_only_allowlisted_read_only_transient_failure_can_retry(self):
        self.assertEqual(
            execution_engine.classify_retry("read_file", "TIMEOUT")["decision"],
            "RETRY_SAFE",
        )

    def test_write_timeout_requires_human(self):
        self.assertEqual(
            execution_engine.classify_retry("write_file", "TIMEOUT")["decision"],
            "HUMAN_REQUIRED",
        )

    def test_unknown_tool_is_not_retried(self):
        self.assertEqual(
            execution_engine.classify_retry("unknown_tool", "HTTP_503")["decision"],
            "HUMAN_REQUIRED",
        )

    def test_read_only_non_transient_failure_stops(self):
        self.assertEqual(
            execution_engine.classify_retry("read_file", "PATH_NOT_FOUND")["decision"],
            "STOP",
        )


class MultiStepExecutionTests(unittest.TestCase):
    def test_executes_in_dependency_order_and_persists_each_step(self):
        plan = make_plan()
        calls, persisted = [], []

        def execute(step):
            calls.append(step["id"])
            return {
                "ok": True,
                "tool_results": [{
                    "tool_name": "read_file",
                    "result": {"ok": True, "result": "data"},
                }],
            }

        report = execution_engine.run_multistep(
            "Собрать отчёт", plan, execute, passing_verifier,
            persist=lambda event, current_plan, step, detail: persisted.append(event),
        )
        self.assertEqual(report["status"], "completed")
        self.assertEqual(calls, ["step_read", "step_report"])
        self.assertEqual(report["completed_steps"], ["step_read", "step_report"])
        self.assertIn("step_verified", persisted)
        self.assertEqual(plan["status"], "completed")

    def test_safe_read_only_timeout_retries_once(self):
        plan, calls = make_plan(), []

        def execute(step):
            calls.append(step["id"])
            if len(calls) == 1:
                return {
                    "ok": False,
                    "error": "TOOL_FAILED",
                    "tool_results": [{
                        "tool_name": "read_file",
                        "result": {"ok": False, "error": "TIMEOUT"},
                    }],
                }
            return {
                "ok": True,
                "tool_results": [{
                    "tool_name": "read_file",
                    "result": {"ok": True, "result": "data"},
                }],
            }

        report = execution_engine.run_multistep(
            "Собрать отчёт", plan, execute, passing_verifier
        )
        self.assertEqual(report["status"], "completed")
        self.assertEqual(calls, ["step_read", "step_read", "step_report"])
        self.assertEqual(report["retries_used"], 1)

    def test_write_timeout_is_not_retried_and_pauses(self):
        plan, calls = make_plan(), []

        def execute(step):
            calls.append(step["id"])
            return {
                "ok": False,
                "tool_results": [{
                    "tool_name": "write_file",
                    "result": {"ok": False, "error": "TIMEOUT"},
                }],
            }

        report = execution_engine.run_multistep(
            "Собрать отчёт", plan, execute, passing_verifier
        )
        self.assertEqual(report["status"], "paused")
        self.assertEqual(calls, ["step_read"])
        self.assertEqual(report["reason"], "HUMAN_REQUIRED_AFTER_AMBIGUOUS_SIDE_EFFECT")

    def test_uncertain_verification_pauses_without_marking_step_complete(self):
        plan = make_plan()
        report = execution_engine.run_multistep(
            "Собрать отчёт", plan,
            lambda step: {"ok": True, "tool_results": []},
            lambda step, outcome: {"status": "UNCERTAIN", "reason": "NEED_HUMAN"},
        )
        self.assertEqual(report["status"], "paused")
        self.assertEqual(plan["steps"][0]["status"], "in_progress")
        self.assertEqual(report["reason"], "NEED_HUMAN")

    def test_interrupted_in_progress_step_is_not_replayed(self):
        plan = make_plan()
        plan["steps"][0]["status"] = "in_progress"
        calls = []
        report = execution_engine.run_multistep(
            "Собрать отчёт", plan,
            lambda step: calls.append(step["id"]) or {"ok": True, "tool_results": []},
            passing_verifier,
        )
        self.assertEqual(report["status"], "paused")
        self.assertEqual(calls, [])
        self.assertEqual(report["reason"], "STEP_ALREADY_IN_PROGRESS_REQUIRES_RECONCILIATION")

    def test_checkpoint_failure_stops_before_execution(self):
        plan, calls = make_plan(), []
        report = execution_engine.run_multistep(
            "Собрать отчёт", plan,
            lambda step: calls.append(step["id"]) or {"ok": True, "tool_results": []},
            passing_verifier,
            persist=lambda *args: (_ for _ in ()).throw(OSError("disk full")),
        )
        self.assertEqual(report["status"], "paused")
        self.assertEqual(calls, [])
        self.assertEqual(report["reason"], "CHECKPOINT_WRITE_FAILED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
