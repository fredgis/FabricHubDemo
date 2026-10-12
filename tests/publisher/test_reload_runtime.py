import json
import unittest
from unittest.mock import Mock, patch

from fabric.rest import DeploymentError
from services.publisher.runtime import Runtime


class SourceReloadRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime.__new__(Runtime)
        self.runtime.operational = Mock(return_value=Mock())
        self.cycle = {"source": "oracle", "command_id": "00000000-0000-4000-8000-000000000602"}
        self.row = {"id": self.cycle["command_id"], "type": "reload_oracle", "status": "requested",
                    "parameters": json.dumps({"limit": 1})}

    @patch("services.publisher.runtime.execute")
    def test_reads_only_one_requested_reload(self, execute):
        execute.return_value = [self.row]
        self.assertEqual(self.runtime.next_reload(), {"id": self.row["id"], "type": "reload_oracle"})
        execute.return_value = []
        self.assertIsNone(self.runtime.next_reload())

    @patch("services.publisher.runtime.execute")
    def test_does_not_replay_orphaned_running_or_multiple_commands(self, execute):
        for rows in ([{**self.row, "status": "running"}], [{**self.row, "status": "blocked"}], [self.row, self.row]):
            execute.return_value = rows
            with self.subTest(rows=rows), self.assertRaises(DeploymentError):
                self.runtime.next_reload()

    @patch("services.publisher.runtime.execute")
    def test_rejects_invalid_reload_payload(self, execute):
        for value in (True, 2, "1", None):
            execute.return_value = [{**self.row, "parameters": json.dumps({"limit": value})}]
            with self.subTest(value=value), self.assertRaises(DeploymentError):
                self.runtime.next_reload()

    @patch("services.publisher.runtime.execute")
    def test_completion_is_idempotent_and_changes_only_status_columns(self, execute):
        execute.return_value = [{"status": "completed"}]
        self.assertEqual(self.runtime.set_reload_status(self.cycle, "completed"), "completed")
        query = execute.call_args.args[1]
        self.assertIn("COALESCE(completed_at,SYSUTCDATETIME())", query)
        self.assertIn("'running','blocked','completed'", query)
        self.assertNotIn("parameters=", query)
        self.assertIsNone(execute.call_args.args[2][2])

    @patch("services.publisher.runtime.execute")
    def test_lost_completion_response_never_downgrades_completed_command(self, execute):
        execute.side_effect = [[], [{"status": "completed"}]]
        self.assertEqual(self.runtime.set_reload_status(self.cycle, "blocked", "response lost"), "completed")
        self.assertNotIn("'completed'", execute.call_args_list[0].args[1].split("AND status IN", 1)[1])

    def test_raw_job_passes_typed_notebook_parameter(self):
        self.runtime.ws = "workspace"
        self.runtime.client = Mock()
        self.runtime.client.request.return_value = (202, {
            "location": "https://api.fabric.microsoft.com/v1/workspaces/workspace/items/raw/jobs/instances/run-1"
        }, {})
        self.runtime.submit_job("raw", parameters={"config_json": "{}"})
        self.assertEqual(self.runtime.client.request.call_args.args[2], {
            "executionData": {"parameters": {"config_json": {"value": "{}", "type": "string"}}}})
        self.runtime.submit_job("bps", pipeline=True)
        self.assertIn("jobType=Pipeline", self.runtime.client.request.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
