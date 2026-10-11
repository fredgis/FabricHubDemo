import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from services.publisher import publish
from services.publisher.runtime import latest_targets, targets_present
from services.publisher.worker import Store, Worker


def config():
    return {
        "workspace_id": "11111111-1111-4111-8111-111111111111",
        "items": {"raw": {"id": "raw"}, "silver": {"id": "silver"}},
        "notebooks": {"raw": "raw-job", "silver": "silver-job"},
        "graph_id": "graph", "run_id": "native-complete",
        "event_entity_map": {"rental.created": "rental", "rental.updated": "rental", "content.upserted": "content"},
        "master_reference_entities": ["content"], "stage_timeout_seconds": 1800,
    }


def event(event_id="new-event", sequence=1):
    return {"event_id": event_id, "entity_key": "order-1", "event_type": "rental.created",
            "source_sequence": sequence}


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))
        self.runtime = Mock()
        self.runtime.published.return_value = [event()]
        self.now = 1000
        self.worker = Worker(config(), self.runtime, self.store, lambda: self.now)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_idle_without_new_events_never_reads_onelake_or_runs_spark(self):
        self.runtime.published.return_value = []
        self.worker.tick()
        self.runtime.exact_ids.assert_not_called()
        self.runtime.jobs.assert_not_called()
        self.runtime.submit_job.assert_not_called()

    def test_same_count_but_missing_exact_id_does_not_start_raw(self):
        self.worker.tick()
        self.runtime.exact_ids.return_value = {"complete": False, "missing_count": 1, "observed_distinct": 1}
        self.worker.tick()
        self.assertEqual(self.worker.state["phase"], "waiting_native_onelake")
        self.runtime.submit_job.assert_not_called()
        self.assertEqual(len(self.store.pending([event()])), 1)

    def test_raw_is_not_started_until_exact_native_ids_exist(self):
        self.worker.tick()
        self.runtime.exact_ids.return_value = {"complete": True}
        self.worker.tick()
        self.assertEqual(self.worker.state["phase"], "raw")
        self.runtime.jobs.return_value = []
        self.runtime.submit_job.return_value = {"id": "actual-job"}
        self.worker.tick()
        self.runtime.submit_job.assert_called_once_with("raw-job", False)
        self.assertEqual(self.store.load()["cycle"]["raw_job"]["id"], "actual-job")
        self.assertEqual(len(self.store.pending([event()])), 1)

    def test_restart_polls_saved_job_never_submits_duplicate(self):
        self.worker.tick()
        self.worker.state["cycle"]["raw_job"] = {"id": "actual-job"}
        self.worker.advance("raw")
        restored = Worker(config(), self.runtime, self.store, lambda: self.now)
        self.runtime.get_job.return_value = {"status": "InProgress"}
        restored.tick()
        self.runtime.get_job.assert_called_once_with("raw-job", "actual-job", "spark-cli")
        self.runtime.submit_job.assert_not_called()

    def test_vm_stop_start_preserves_job_and_remaining_stage_deadline(self):
        self.worker.tick()
        self.worker.state["cycle"]["raw_job"] = {"id": "existing-job"}
        self.worker.advance("raw")
        cycle = copy.deepcopy(self.worker.state["cycle"])
        self.now += 100
        with patch("services.publisher.worker.time.time", return_value=self.now):
            self.worker.save()
        self.now += 8 * 3600
        restored = Worker(config(), self.runtime, self.store, lambda: self.now)
        self.runtime.get_job.return_value = {"status": "InProgress"}
        restored.tick()
        self.assertEqual(restored.state["phase"], "raw")
        self.assertEqual(self.now - restored.state["stage_started_at"], 100)
        self.assertEqual(restored.state["cycle"]["id"], cycle["id"])
        self.assertEqual(restored.state["cycle"]["events"], cycle["events"])
        self.runtime.get_job.assert_called_once_with("raw-job", "existing-job", "spark-cli")
        self.runtime.submit_job.assert_not_called()
        self.now += 1701
        with self.assertRaisesRegex(RuntimeError, "bounded stage deadline"):
            restored.tick()

    def test_job_completed_while_vm_off_is_verified_without_resubmission(self):
        self.worker.tick()
        self.worker.state["cycle"]["raw_job"] = {"id": "completed-during-outage"}
        self.worker.advance("raw")
        with patch("services.publisher.worker.time.time", return_value=self.now):
            self.worker.save()
        self.now += 24 * 3600
        restored = Worker(config(), self.runtime, self.store, lambda: self.now)
        self.runtime.get_job.return_value = {"status": "Completed", "endTimeUtc": "1970-01-01T00:30:00Z"}
        restored.tick()
        self.assertEqual(restored.state["phase"], "verify_raw")
        self.assertEqual(len(self.store.pending([event()])), 1)
        self.runtime.get_job.assert_called_once_with("raw-job", "completed-during-outage", "spark-cli")
        self.runtime.submit_job.assert_not_called()

    def test_lost_post_response_adopts_single_matching_job(self):
        self.worker.tick()
        self.worker.state["cycle"]["raw_intent"] = 900
        self.worker.advance("raw")
        self.runtime.jobs.return_value = [{"id": "accepted", "status": "InProgress",
                                          "startTimeUtc": "1970-01-01T00:15:00Z"}]
        self.worker.tick()
        self.assertEqual(self.worker.state["cycle"]["raw_job"]["id"], "accepted")
        self.runtime.submit_job.assert_not_called()

    def test_active_external_graph_blocks_raw(self):
        self.worker.tick()
        self.worker.advance("raw")
        self.runtime.jobs.side_effect = [[], [], [{"id": "active", "status": "InProgress"}]]
        self.worker.tick()
        self.runtime.submit_job.assert_not_called()

    def test_checkpoint_advances_only_after_real_graph_proof(self):
        self.worker.tick()
        self.worker.advance("verify_graph")
        self.runtime.verify_graph.return_value = None
        self.worker.tick()
        self.assertEqual(len(self.store.pending([event()])), 1)
        self.runtime.verify_graph.return_value = {"verified_orders": 1}
        self.worker.tick()
        self.assertEqual(self.worker.state["phase"], "idle")
        self.assertEqual(self.store.pending([event()]), [])

    def test_gold_link_availability_is_required_before_graph(self):
        self.worker.tick()
        self.worker.advance("waiting_gold_onelake")
        self.runtime.gold_onelake.return_value = False
        self.worker.tick()
        self.assertEqual(self.worker.state["phase"], "waiting_gold_onelake")
        self.runtime.submit_job.assert_not_called()
        self.runtime.gold_onelake.return_value = True
        self.worker.tick()
        self.assertEqual(self.worker.state["phase"], "graph")

    def test_terminal_notebook_failure_does_not_run_silver(self):
        self.worker.tick()
        self.worker.state["cycle"]["raw_job"] = {"id": "failed"}
        self.worker.advance("raw")
        self.runtime.get_job.return_value = {"status": "Failed"}
        with self.assertRaisesRegex(RuntimeError, "no automatic resubmission"):
            self.worker.tick()
        self.runtime.submit_job.assert_not_called()

    def test_source_bindings_cannot_change_under_pending_cycle(self):
        self.worker.tick()
        different = copy.deepcopy(config())
        different["run_id"] = "different-reference-snapshot"
        with self.assertRaisesRegex(RuntimeError, "bindings changed"):
            Worker(different, self.runtime, self.store)

    def test_ack_receipts_do_not_advance_propagation_checkpoint(self):
        self.store.receipt({"event_ids": ["new-event"], "broker_acknowledged": 1, "sql_committed": True})
        self.assertEqual(len(self.store.pending([event()])), 1)


class TargetTests(unittest.TestCase):
    def test_latest_sequence_wins_and_native_master_is_not_overridden(self):
        rows = [event("old", 1), event("new", 2),
                {**event(), "event_type": "content.upserted", "entity_key": "film"}]
        self.assertEqual(latest_targets(rows, config()), [
            {"entity": "rental", "key": "order-1", "source_sequence": 2, "event_id": "new"}])

    def test_equal_total_count_cannot_substitute_other_order(self):
        targets = latest_targets([event()], config())
        self.assertFalse(targets_present(targets, [{"order_id": "other", "source_sequence": 10}], "order_id"))
        self.assertFalse(targets_present(targets, [{"order_id": "order-1", "source_sequence": 0}], "order_id"))
        self.assertTrue(targets_present(targets, [{"order_id": "order-1", "source_sequence": 1}], "order_id"))

    def test_managed_identity_never_falls_back_to_cli(self):
        args = Mock(auth="managed-identity", managed_identity_client_id=None)
        with patch("azure.identity.ManagedIdentityCredential") as managed, patch("azure.identity.AzureCliCredential") as cli:
            self.assertIs(publish.make_credential(args), managed.return_value)
            managed.assert_called_once_with()
            cli.assert_not_called()


if __name__ == "__main__":
    unittest.main()
