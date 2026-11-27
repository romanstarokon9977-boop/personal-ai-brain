import unittest

from dashboard import build_dashboard_snapshot, render_dashboard


class DashboardTests(unittest.TestCase):
    def test_snapshot_counts_tasks_tools_memory_and_processes(self):
        snapshot = build_dashboard_snapshot(
            router_state={
                "active_model": "provider/model-x:free",
                "active_provider": "API",
                "total_requests": 12,
                "successful_requests": 10,
                "failed_requests": 2,
                "models": ["a", "b"],
            },
            memory_status={"total": 7, "categories": {"facts": 5, "preferences": 2}},
            tasks=[
                {"status": "active", "priority": "critical"},
                {"status": "pending", "priority": "high"},
                {"status": "completed"},
            ],
            tools=["read_file", "write_file", "directory_list"],
            enabled_tool_names={"read_file", "directory_list"},
            local_processes=["llama-8085"],
            mcp_alive=True,
            candidate_count=2,
        )
        self.assertEqual(snapshot["model"], "model-x:free")
        self.assertEqual(snapshot["memory_total"], 7)
        self.assertEqual(snapshot["task_statuses"]["active"], 1)
        self.assertEqual(snapshot["task_priorities"]["critical"], 1)
        self.assertEqual(snapshot["tools_enabled"], 2)
        self.assertEqual(snapshot["local_processes"], ["llama-8085"])
        self.assertEqual(snapshot["candidate_count"], 2)

    def test_render_is_compact_and_contains_required_panels(self):
        snapshot = build_dashboard_snapshot(
            router_state={}, memory_status={"total": 0, "categories": {}},
            tasks=[], tools=[], enabled_tool_names=set(),
            local_processes=[], mcp_alive=False, candidate_count=0,
        )
        rendered = render_dashboard(snapshot)
        for label in ("Система:", "Модель:", "Память:", "Задачи:", "Инструменты:", "MCP filesystem:"):
            self.assertIn(label, rendered)
        self.assertNotIn("None", rendered)

    def test_dashboard_does_not_render_task_or_memory_content(self):
        snapshot = build_dashboard_snapshot(
            router_state={}, memory_status={"total": 1, "categories": {"facts": 1}},
            tasks=[{"status": "pending", "priority": "normal", "title": "PRIVATE_TASK_TITLE"}],
            tools=["read_file"], enabled_tool_names={"read_file"},
            local_processes=[], mcp_alive=False,
        )
        rendered = render_dashboard(snapshot)
        self.assertNotIn("PRIVATE_TASK_TITLE", rendered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
