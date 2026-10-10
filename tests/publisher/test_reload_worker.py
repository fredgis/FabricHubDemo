import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from services.publisher.worker import Store, Worker
from tests.publisher.test_worker import config, event


class SourceReloadWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))
        self.cfg = {**config(), "source_reload_enabled": True}
        self.runtime = Mock()
        self.runtime.next_reload.return_value = {"id": "command-1", "type": "reload_oracle"}
        self.runtime.jobs.return_value = []
        self.worker = Worker(self.cfg, self.runtime, self.store, lambda: 1000)
        self.worker.tick()

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_requested_reload_runs_without_events_and_before_event_cycle(self):
        self.assertEqual(self.store.load()["phase"], "source_claim")
        self.runtime.published.assert_not_called()
        self.worker.tick()
        self.assertEqual(self.worker.state["phase"], "source_prepare")
        self.runtime.set_reload_status.assert_called_once_with(self.worker.state["cycle"], "running")

    def test_reload_uses_parameterized_raw_and_preserves_default_run(self):
        self.worker.state["cycle"]["raw_config"] = {"run_id": "native-complete", "sources": []}
        self.worker.advance("raw")
        self.runtime.submit_job.return_value = {"id": "notebook-run"}
        self.worker.tick()
        self.runtime.submit_job.assert_called_once_with(
            "raw-job", parameters={"config_json": json.dumps(self.worker.state["cycle"]["raw_config"])})
        self.assertEqual(self.cfg["run_id"], "native-complete")
        self.assertEqual(self.store.load()["cycle"]["raw_job"]["id"], "notebook-run")

    def test_restart_polls_native_job_without_restarting_extraction(self):
        self.worker.state["cycle"].update(source="salesforce", source_pipelines={"extraction": "pipeline-1"},
                                          bps_extraction_job={"id": "native-job"})
        self.worker.advance("bps_extraction")
        restored = Worker(self.cfg, self.runtime, self.store, lambda: 1000)
        self.runtime.get_job.return_value = {"status": "InProgress"}
        restored.tick()
        self.runtime.get_job.assert_called_once_with("pipeline-1", "native-job", "e2e-medallion-architecture")
        self.runtime.submit_job.assert_not_called()

    def test_reload_waits_for_real_snapshot_proof(self):
        self.worker.advance("verify_raw")
        self.runtime.verify_source_reload.return_value = False
        self.worker.tick()
        self.assertEqual(self.worker.state["phase"], "verify_raw")
        self.runtime.exact_ids.assert_not_called()
        self.runtime.verify_source_reload.return_value = True
        self.worker.tick()
        self.assertEqual(self.worker.state["phase"], "silver")

    def test_completed_status_is_after_graph_and_does_not_checkpoint_pending_events(self):
        self.worker.state["cycle"].update(raw_config={"private": "config"}, reference_snapshot={"private": "rows"})
        self.worker.advance("verify_graph")
        self.runtime.verify_graph.return_value = {"verified_orders": 0}
        self.worker.tick()
        self.runtime.set_reload_status.assert_not_called()
        self.assertEqual(self.worker.state["phase"], "source_complete")
        self.worker.tick()
        self.assertEqual(self.worker.state["phase"], "idle")
        self.assertEqual(self.runtime.set_reload_status.call_args.args[1], "completed")
        self.assertEqual(self.store.pending([event()]), [event()])
        status = json.loads((Path(self.temp.name) / "status.json").read_text())
        self.assertNotIn("raw_config", status["last_cycle"])
        self.assertNotIn("reference_snapshot", status["last_cycle"])

    def test_block_reports_failure_once_and_never_resubmits_job(self):
        self.worker.block("native snapshot is empty")
        self.runtime.set_reload_status.assert_called_once_with(
            self.worker.state["cycle"], "blocked", "native snapshot is empty")
        self.worker.run_pass()
        self.assertEqual(self.runtime.set_reload_status.call_count, 1)
        self.runtime.submit_job.assert_not_called()


if __name__ == "__main__":
    unittest.main()
