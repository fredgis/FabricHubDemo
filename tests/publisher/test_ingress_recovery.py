import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from fabric.rest import DeploymentError
from services.publisher.runtime import Runtime
from services.publisher.worker import Store, Worker
from test_worker import config, event


INGRESS = {
    "eventstream_id": "55555555-5555-4555-8555-555555555555",
    "source_id": "66666666-6666-4666-8666-666666666666",
    "destination_id": "77777777-7777-4777-8777-777777777777",
}


def nodes(status):
    return [{"group": group, "id": INGRESS[key], "status": status}
            for group, key in (("destinations", "destination_id"), ("sources", "source_id"))]


class IngressRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))
        self.cfg = {**config(), "ingress": INGRESS}
        self.now = 1000.0
        self.runtime = Mock()
        self.runtime.published.return_value = [event()]
        self.runtime.publish.return_value = {}
        self.runtime.ingress_status.return_value = nodes("Running")
        self.runtime.resume_ingress.return_value = {}
        self.runtime.exact_ids.return_value = {"complete": False, "missing_count": 1}
        self.worker = Worker(self.cfg, self.runtime, self.store, lambda: self.now)
        self.worker.tick()
        self.cycle = copy.deepcopy(self.worker.state["cycle"])

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def restore(self):
        self.worker = Worker(self.cfg, self.runtime, self.store, lambda: self.now)

    def test_paused_ingress_is_resumed_before_raw_and_ids_are_preserved(self):
        self.runtime.ingress_status.return_value = nodes("Paused")
        self.worker.run_pass()
        self.runtime.resume_ingress.assert_called_once_with("destinations", INGRESS["destination_id"])
        self.runtime.exact_ids.assert_not_called()
        self.runtime.submit_job.assert_not_called()
        self.assertEqual(self.worker.state["phase"], "waiting_native_onelake")
        self.restore()
        self.runtime.ingress_status.return_value = [nodes("Running")[0], nodes("Paused")[1]]
        self.worker.run_pass()
        self.runtime.resume_ingress.assert_called_with("sources", INGRESS["source_id"])
        self.runtime.ingress_status.return_value = nodes("Running")
        self.runtime.exact_ids.return_value = {"complete": True}
        self.worker.run_pass()
        self.assertEqual(self.worker.state["phase"], "raw")
        self.assertEqual(self.worker.state["cycle"]["events"], self.cycle["events"])
        self.assertEqual(self.store.pending([event()]), [event()])

    def test_native_deadline_keeps_a_durable_read_only_retry(self):
        self.now += self.cfg["stage_timeout_seconds"] + 1
        self.worker.run_pass()
        self.assertEqual(self.worker.state["phase"], "waiting_native_onelake")
        self.assertTrue(self.worker.state["cycle"]["native_onelake"]["overdue"])
        self.assertEqual(self.runtime.exact_ids.call_count, 1)
        self.restore()
        self.now += 30
        self.worker.run_pass()
        self.assertEqual(self.runtime.exact_ids.call_count, 1)
        self.now = self.worker.state["cycle"]["native_probe_not_before"]
        self.runtime.exact_ids.return_value = {"complete": True}
        self.worker.run_pass()
        self.assertEqual(self.worker.state["phase"], "raw")
        self.assertEqual(self.worker.state["cycle"]["id"], self.cycle["id"])
        self.runtime.submit_job.assert_not_called()

    def test_old_native_deadline_block_recovers_without_operator_resume(self):
        self.worker.state.update(
            phase="blocked", blocked_phase="waiting_native_onelake", error_kind="nonretryable",
            error="waiting_native_onelake exceeded bounded stage deadline; no success claimed")
        self.worker.save()
        self.restore()
        self.now += 4000
        self.runtime.exact_ids.return_value = {"complete": True}
        self.worker.run_pass()
        self.assertEqual(self.worker.state["phase"], "raw")
        self.assertNotIn("blocked_phase", self.worker.state)
        self.assertEqual(self.worker.state["cycle"]["id"], self.cycle["id"])
        self.assertEqual(self.store.pending([event()]), [event()])

    def test_lost_resume_response_reconciles_topology_without_another_post(self):
        self.runtime.ingress_status.return_value = nodes("Paused")
        self.runtime.resume_ingress.side_effect = TimeoutError("Resume response lost")
        self.worker.run_pass()
        self.restore()
        self.now += 30
        self.worker.run_pass()
        self.runtime.resume_ingress.assert_called_once()
        self.assertEqual(self.worker.state["phase"], "waiting_native_onelake")
        self.runtime.ingress_status.return_value = nodes("Running")
        self.runtime.exact_ids.return_value = {"complete": True}
        self.worker.run_pass()
        self.assertEqual(self.worker.state["phase"], "raw")

    def test_unresolved_resume_stops_without_replaying_events_or_writes(self):
        self.runtime.ingress_status.return_value = nodes("Paused")
        self.runtime.resume_ingress.side_effect = TimeoutError("Resume response lost")
        self.worker.run_pass()
        self.now += 601
        self.worker.run_pass()
        self.assertEqual(self.worker.state["phase"], "blocked")
        self.assertIn("resume", self.worker.state["error"].lower())
        self.runtime.resume_ingress.assert_called_once()
        self.runtime.submit_job.assert_not_called()
        self.assertEqual(self.store.pending([event()]), [event()])

    def test_permission_block_is_not_automatically_reopened(self):
        self.runtime.ingress_status.return_value = nodes("Paused")
        self.runtime.resume_ingress.side_effect = DeploymentError("Fabric HTTP 403 [Forbidden]: permission denied")
        self.worker.run_pass()
        self.assertEqual(self.worker.state["phase"], "blocked")
        self.restore()
        self.worker.run_pass()
        self.runtime.resume_ingress.assert_called_once()
        self.runtime.submit_job.assert_not_called()

    def test_ingress_binding_change_is_rejected_after_restart(self):
        self.cfg = {**self.cfg, "ingress": {**INGRESS, "source_id": "different-source"}}
        with self.assertRaisesRegex(DeploymentError, "ingress bindings changed"):
            self.restore()

    def test_async_resume_is_polled_before_running_topology_is_accepted(self):
        self.runtime.ingress_status.return_value = nodes("Paused")
        self.runtime.resume_ingress.return_value = {"operation": "/v1/operations/operation-id", "retry_after": 30}
        self.worker.run_pass()
        self.restore()
        self.runtime.ingress_status.return_value = nodes("Running")
        self.worker.run_pass()
        self.runtime.ingress_operation.assert_not_called()
        self.runtime.exact_ids.assert_not_called()
        self.now += 30
        self.runtime.ingress_operation.return_value = {"status": "Succeeded"}
        self.runtime.exact_ids.return_value = {"complete": True}
        self.worker.run_pass()
        self.runtime.ingress_operation.assert_called_once_with("/v1/operations/operation-id")
        self.assertEqual(self.worker.state["phase"], "raw")
        self.runtime.resume_ingress.assert_called_once()


class IngressAdapterTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {**config(), "tenant_id": "tenant", "ingress": INGRESS}
        self.cfg["items"]["kql"] = {"id": "88888888-8888-4888-8888-888888888888"}
        self.runtime = Runtime(self.cfg, credential=Mock())
        self.runtime.client = Mock()

    def test_resume_uses_stopped_position_and_pinned_node_only(self):
        self.runtime.client.request.return_value = (200, {}, {})
        self.runtime.resume_ingress("sources", INGRESS["source_id"])
        self.runtime.client.request.assert_called_once_with(
            "POST", f"/v1/workspaces/{self.cfg['workspace_id']}/eventstreams/{INGRESS['eventstream_id']}"
            f"/sources/{INGRESS['source_id']}/resume", {"startType": "WhenLastStopped"}, "eventstream-cli")
        with self.assertRaises(DeploymentError):
            self.runtime.resume_ingress("sources", "different-node")
        self.assertEqual(self.runtime.client.request.call_count, 1)

    def test_resume_operation_and_poll_keep_fabric_skill_attribution(self):
        operation_id = "99999999-9999-4999-8999-999999999999"
        path = f"/v1/operations/{operation_id}"
        self.runtime.client.request.return_value = (202, {"x-ms-operation-id": operation_id, "retry-after": "45"}, {})
        self.assertEqual(self.runtime.resume_ingress("sources", INGRESS["source_id"]),
                         {"operation": path, "retry_after": 45})
        self.runtime.client.request.return_value = (200, {}, {"status": "Succeeded"})
        self.assertEqual(self.runtime.ingress_operation(path)["status"], "Succeeded")
        self.runtime.client.request.assert_called_with("GET", path, skill="eventstream-cli")

    def test_topology_must_still_match_the_configured_raw_events_route(self):
        topology = {
            "sources": [{"id": INGRESS["source_id"], "name": "OperationalEvents",
                         "type": "AzureEventHubExtended", "status": "Paused"}],
            "destinations": [{"id": INGRESS["destination_id"], "type": "Eventhouse", "status": "Paused",
                              "inputNodes": [{"name": "Ingress-stream"}], "properties": {
                                  "workspaceId": self.cfg["workspace_id"],
                                  "itemId": self.cfg["items"]["kql"]["id"], "tableName": "RawEvents"}}],
            "streams": [{"name": "Ingress-stream", "type": "DefaultStream", "status": "Running",
                         "inputNodes": [{"name": "OperationalEvents"}]}], "operators": [],
        }
        self.runtime.client.request.return_value = (200, {}, topology)
        self.assertEqual(self.runtime.ingress_status(), nodes("Paused"))
        topology["destinations"][0]["properties"]["itemId"] = "different-database"
        with self.assertRaises(DeploymentError):
            self.runtime.ingress_status()


if __name__ == "__main__":
    unittest.main()
