import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from fabric.rest import DeploymentError
from sources.sap import process


class ProcessTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="sap-process-test-", dir=".")
        self.addCleanup(directory.cleanup)
        self.output = Path(directory.name)
        self.target = {
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "subscription_id": "00000000-0000-0000-0000-000000000002",
            "workspace_id": "00000000-0000-0000-0000-000000000003",
            "operator_id": "00000000-0000-0000-0000-000000000004",
            "landing_lakehouse_id": "00000000-0000-0000-0000-000000000005",
            "mirror_id": "00000000-0000-0000-0000-000000000006",
            "source_system": "S4M",
            "system_suffix": "fea347cc",
        }
        self.pipelines = {
            "b2s": {
                "id": "00000000-0000-0000-0000-000000000010",
                "displayName": "bps_datasphere_b2s_orchestration_pipeline_fea347cc",
                "type": "DataPipeline",
            },
            "s2g": {
                "id": "00000000-0000-0000-0000-000000000011",
                "displayName": "bps_s2g_full_processing_pipeline_fea347cc",
                "type": "DataPipeline",
            },
        }
        self.new_job = "00000000-0000-0000-0000-000000000020"
        self.old_job = "00000000-0000-0000-0000-000000000021"
        self.other_job = "00000000-0000-0000-0000-000000000022"
        self.root = "/v1/workspaces/" + self.target["workspace_id"]
        self.client = Mock(spec=process.ScopedClient)
        self.client.item.side_effect = self.lookup_item
        self.client.list.side_effect = self.list_items
        self.client.request.side_effect = self.request
        self.constructor = self.start_patch(
            "sources.sap.process.ScopedClient", return_value=self.client,
        )
        self.time = self.start_patch("sources.sap.process.time")
        self.time.monotonic.side_effect = lambda: self.now
        self.time.sleep.side_effect = self.advance_clock
        self.start_patch("sources.sap.process.print", create=True)
        self.start_patch(
            "socket.socket.connect", side_effect=AssertionError("Network is prohibited"),
        )
        self.case_number = 0
        self.reset_case()

    def start_patch(self, *args, **kwargs):
        patcher = patch(*args, **kwargs)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def reset_case(self):
        self.case_number += 1
        self.evidence = self.output / str(self.case_number)
        self.evidence.mkdir()
        self.histories = {"b2s": [], "s2g": []}
        self.responses = {}
        self.stage = "b2s"
        self.now = 1000
        self.before_post = None
        self.before_get = None
        self.post_result = (
            202, {"location": self.location("b2s", self.new_job)}, {},
        )
        self.client.reset_mock()
        self.constructor.reset_mock()
        self.time.reset_mock()

    def advance_clock(self, seconds):
        self.assertGreater(seconds, 0)
        self.now += seconds

    def jobs_path(self, stage):
        return self.root + "/items/" + self.pipelines[stage]["id"] + "/jobs/instances"

    def location(self, stage, job_id):
        return "https://api.fabric.microsoft.com" + self.jobs_path(stage) + "/" + job_id

    def lookup_item(self, name, item_type):
        self.assertEqual(item_type, "DataPipeline")
        matches = [p for p in self.pipelines.values() if p["displayName"] == name]
        self.assertEqual(len(matches), 1, "Only the dedicated native pipelines may be resolved")
        return copy.deepcopy(matches[0])

    def list_items(self, path):
        if path == self.root + "/items":
            return copy.deepcopy(list(self.pipelines.values())) + [
                {
                    "id": "unrelated-pipeline",
                    "displayName": "bps_datasphere_b2s_orchestration_pipeline_deadbeef",
                    "type": "DataPipeline",
                },
                {
                    "id": "unrelated-notebook",
                    "displayName": "notebook_fea347cc",
                    "type": "Notebook",
                },
            ]
        for stage in self.pipelines:
            if path == self.jobs_path(stage):
                return copy.deepcopy(self.histories[stage])
        self.fail("Unexpected native history read: " + path)

    def request(self, method, path, *args, **kwargs):
        if method == "POST":
            self.assertEqual(path, self.jobs_path(self.stage) + "?jobType=Pipeline")
            self.assertEqual(args, ({},))
            self.assertEqual(kwargs, {})
            if self.before_post:
                self.before_post()
            if isinstance(self.post_result, Exception):
                raise self.post_result
            return copy.deepcopy(self.post_result)
        self.assertEqual(method, "GET", "No write other than native submission is allowed")
        self.assertEqual(args, ())
        self.assertEqual(kwargs, {})
        self.assertIn(path, self.responses, "Unexpected native job readback")
        self.assertTrue(self.responses[path], "More polls than expected")
        if self.before_get:
            self.before_get(path)
        result = self.responses[path].pop(0)
        if isinstance(result, Exception):
            raise result
        return 200, {}, copy.deepcopy(result)

    def queue_results(self, stage, job_id, *results):
        self.responses[self.jobs_path(stage) + "/" + job_id] = [
            {"id": job_id, "status": result} if isinstance(result, str) else result
            for result in results
        ]

    def checkpoint_path(self, stage="b2s"):
        return self.evidence / (stage + "-job.json")

    def write_checkpoint(self, state, job_id=None, stage="b2s", **overrides):
        row = {
            "workspace_id": self.target["workspace_id"],
            "pipeline_id": self.pipelines[stage]["id"],
            "stage": stage,
            "state": state,
            "data_verified": False,
        }
        if job_id is not None:
            row["job_id"] = job_id
        row.update(overrides)
        self.checkpoint_path(stage).write_text(json.dumps(row), encoding="utf-8")
        return row

    def read_checkpoint(self, stage="b2s"):
        return json.loads(self.checkpoint_path(stage).read_text(encoding="utf-8"))

    def write_silver_proof(self, **overrides):
        proof = {"version": 1, "source_stage": "silver", "data_verified": True,
                 "workspace_id": self.target["workspace_id"],
                 "jobs": {"b2s": {"pipeline_id": self.pipelines["b2s"]["id"], "job_id": self.old_job}}}
        proof.update(overrides)
        process.silver_evidence_path(self.evidence, self.old_job).write_text(json.dumps(proof), encoding="utf-8")

    def assert_checkpoint(self, state, job_id, stage="b2s"):
        row = self.read_checkpoint(stage)
        self.assertEqual(row["workspace_id"], self.target["workspace_id"])
        self.assertEqual(row["pipeline_id"], self.pipelines[stage]["id"])
        self.assertEqual(row["stage"], stage)
        self.assertEqual(row["state"], state)
        self.assertEqual(row.get("job_id"), job_id)
        self.assertIs(row["data_verified"], False)
        self.assertFalse(list(self.evidence.glob("*.tmp")))
        return row

    def assert_no_submission(self):
        self.assertFalse(
            [c for c in self.client.request.call_args_list if c.args[0] == "POST"],
            "A safety refusal or resume must not submit another job",
        )

    def run_stage(self, stage="b2s", **kwargs):
        self.stage = stage
        return process.run(self.target, stage, self.evidence, **kwargs)

    def test_native_submission_persists_intent_then_accepted_id_before_polling(self):
        self.before_post = lambda: self.assert_checkpoint("ambiguous_submission", None)
        observed = []

        def before_poll(_path):
            observed.append(self.read_checkpoint()["state"])
            expected = ["accepted", "NotStarted", "InProgress"][len(observed) - 1]
            self.assert_checkpoint(expected, self.new_job)

        self.before_get = before_poll
        self.queue_results("b2s", self.new_job, "NotStarted", "InProgress", "Completed")
        result = self.run_stage(timeout=120)

        self.assertEqual(observed, ["accepted", "NotStarted", "InProgress"])
        self.assertEqual(result, self.assert_checkpoint("Completed", self.new_job))
        self.assertIsNone(result["failure"])
        self.constructor.assert_called_once_with(self.target)
        self.client.workspace.assert_called_once_with()
        self.client.item.assert_called_once_with(
            "bps_datasphere_b2s_orchestration_pipeline_fea347cc", "DataPipeline",
        )
        self.assertEqual(
            self.client.list.call_args_list,
            [
                call(self.root + "/items"),
                call(self.jobs_path("b2s")),
                call(self.jobs_path("s2g")),
            ],
        )
        self.assertEqual(
            self.client.request.call_args_list,
            [call("POST", self.jobs_path("b2s") + "?jobType=Pipeline", {})]
            + [call("GET", self.jobs_path("b2s") + "/" + self.new_job)] * 3,
        )
        self.assertEqual(self.time.sleep.call_args_list, [call(30), call(30)])

    def test_poll_transport_failure_preserves_accepted_id_and_retry_only_resumes(self):
        self.queue_results("b2s", self.new_job, OSError("Polling connection lost"))
        with self.assertRaisesRegex(OSError, "Polling connection lost"):
            self.run_stage()
        self.assert_checkpoint("accepted", self.new_job)

        self.histories["b2s"] = [{"id": self.new_job, "status": "InProgress"}]
        self.queue_results("b2s", self.new_job, "Completed")
        result = self.run_stage()
        self.assertEqual(result, self.assert_checkpoint("Completed", self.new_job))
        posts = [c for c in self.client.request.call_args_list if c.args[0] == "POST"]
        self.assertEqual(posts, [call("POST", self.jobs_path("b2s") + "?jobType=Pipeline", {})])
        self.time.sleep.assert_not_called()

    def test_ambiguous_post_is_durable_and_cannot_be_submitted_twice(self):
        valid_location = self.location("b2s", self.new_job)
        cases = (
            (200, {"location": valid_location}, {}),
            (500, {"location": valid_location}, {}),
            (202, {}, {}),
            (202, {"location": valid_location.replace("api.fabric.microsoft.com", "other.invalid")}, {}),
            (202, {"location": valid_location.replace(self.target["workspace_id"], "other-workspace")}, {}),
            (202, {"location": self.location("s2g", self.new_job)}, {}),
            DeploymentError("Submission response lost"),
            OSError("Submission connection lost"),
        )
        for response in cases:
            with self.subTest(response=response):
                self.reset_case()
                self.post_result = response
                self.before_post = lambda: self.assert_checkpoint("ambiguous_submission", None)
                with self.assertRaises((DeploymentError, OSError)):
                    self.run_stage()
                self.assert_checkpoint("ambiguous_submission", None)
                original = self.checkpoint_path().read_bytes()

                for kwargs in (
                    {}, {"after_completed_job": self.old_job}, {"retry_failed_job": self.old_job},
                ):
                    with self.assertRaisesRegex(DeploymentError, "ambiguous"):
                        self.run_stage(**kwargs)
                    self.assertEqual(self.checkpoint_path().read_bytes(), original)
                self.client.request.assert_called_once_with(
                    "POST", self.jobs_path("b2s") + "?jobType=Pipeline", {},
                )
                self.time.sleep.assert_not_called()

    def test_checkpointed_active_job_resumes_without_submission(self):
        for checkpoint_state in ("accepted", "NotStarted", "InProgress"):
            with self.subTest(checkpoint_state=checkpoint_state):
                self.reset_case()
                self.write_checkpoint(checkpoint_state, self.old_job)
                self.histories["b2s"] = [{"id": self.old_job, "status": "InProgress"}]
                self.queue_results("b2s", self.old_job, "InProgress", "Completed")
                result = self.run_stage(timeout=60)
                self.assertEqual(result, self.assert_checkpoint("Completed", self.old_job))
                self.assert_no_submission()
                self.assertEqual(
                    self.client.request.call_args_list,
                    [call("GET", self.jobs_path("b2s") + "/" + self.old_job)] * 2,
                )
                self.time.sleep.assert_called_once_with(30)

    def test_timeout_preserves_active_checkpoint_and_next_run_resumes_same_job(self):
        self.queue_results("b2s", self.new_job, "InProgress", "InProgress")
        with self.assertRaisesRegex(DeploymentError, "deadline exceeded"):
            self.run_stage(timeout=60)
        self.assert_checkpoint("InProgress", self.new_job)
        self.assertEqual(self.time.sleep.call_args_list, [call(30), call(30)])

        self.histories["b2s"] = [{"id": self.new_job, "status": "InProgress"}]
        self.queue_results("b2s", self.new_job, "Completed")
        result = self.run_stage(timeout=60)
        self.assertEqual(result, self.assert_checkpoint("Completed", self.new_job))
        posts = [c for c in self.client.request.call_args_list if c.args[0] == "POST"]
        self.assertEqual(len(posts), 1)

    def test_terminal_failure_statuses_raise_and_record_failure_not_success(self):
        reason = {
            "errorCode": "NativeExecutionFailed",
            "message": "Native pipeline execution failed",
            "isRetriable": True,
            "details": "Must not be copied into the checkpoint",
        }
        for status in ("Failed", "Cancelled", "Canceled", "Deduped"):
            with self.subTest(status=status):
                self.reset_case()
                self.queue_results(
                    "b2s", self.new_job,
                    {"id": self.new_job, "status": status, "failureReason": reason},
                )
                with self.assertRaisesRegex(DeploymentError, "failed"):
                    self.run_stage()
                row = self.assert_checkpoint(status, self.new_job)
                self.assertEqual(
                    row["failure"],
                    {key: reason[key] for key in ("errorCode", "message", "isRetriable")},
                )
                self.assertNotEqual(row["state"], "Completed")
                self.time.sleep.assert_not_called()
                self.client.request.assert_has_calls([
                    call("POST", self.jobs_path("b2s") + "?jobType=Pipeline", {}),
                    call("GET", self.jobs_path("b2s") + "/" + self.new_job),
                ])
                self.assertEqual(self.client.request.call_count, 2)

    def test_existing_failed_checkpoint_is_read_back_without_automatic_retry(self):
        self.write_checkpoint("Failed", self.old_job)
        self.histories["b2s"] = [{"id": self.old_job, "status": "Failed"}]
        self.queue_results("b2s", self.old_job, "Failed")
        with self.assertRaisesRegex(DeploymentError, "failed"):
            self.run_stage()
        self.assert_checkpoint("Failed", self.old_job)
        self.assert_no_submission()
        self.client.request.assert_called_once_with(
            "GET", self.jobs_path("b2s") + "/" + self.old_job,
        )
        self.time.sleep.assert_not_called()

    def failed_history(self, status="Failed"):
        return [
            {
                "id": self.old_job, "status": status,
                "startTimeUtc": "2026-10-09T08:30:00Z",
            },
            {
                "id": self.other_job, "status": "Failed",
                "startTimeUtc": "2026-10-09T08:00:00Z",
            },
        ]

    def test_exact_latest_failed_or_cancelled_job_can_be_retried_once(self):
        for status in ("Failed", "Cancelled", "Canceled", "Deduped"):
            with self.subTest(status=status):
                self.reset_case()
                self.write_checkpoint(status, self.old_job)
                self.histories["b2s"] = self.failed_history(status)
                self.before_post = lambda: self.assert_checkpoint("ambiguous_submission", None)
                self.before_get = lambda _path: self.assert_checkpoint("accepted", self.new_job)
                self.queue_results("b2s", self.new_job, "Completed")
                result = self.run_stage(retry_failed_job=self.old_job)
                self.assertEqual(result, self.assert_checkpoint("Completed", self.new_job))
                self.assertEqual(self.client.request.call_args_list, [
                    call("POST", self.jobs_path("b2s") + "?jobType=Pipeline", {}),
                    call("GET", self.jobs_path("b2s") + "/" + self.new_job),
                ])

                self.histories["b2s"].append({
                    "id": self.new_job, "status": "Completed",
                    "startTimeUtc": "2026-10-09T08:31:00Z",
                })
                original = self.checkpoint_path().read_bytes()
                with self.assertRaisesRegex(DeploymentError, "exact latest failed native job"):
                    self.run_stage(retry_failed_job=self.old_job)
                self.assertEqual(self.checkpoint_path().read_bytes(), original)
                self.assertEqual(
                    len([c for c in self.client.request.call_args_list if c.args[0] == "POST"]), 1,
                )
                self.time.sleep.assert_not_called()

    def test_wrong_or_nonlatest_failed_retry_is_refused_without_overwriting_checkpoint(self):
        cases = [
            (self.failed_history(), self.other_job),
            (self.failed_history(), self.new_job),
            ([], self.old_job),
            (self.failed_history() + [self.failed_history()[0]], self.old_job),
        ]
        for status in ("Completed", "NotStarted", "InProgress"):
            cases.append(([{
                "id": self.old_job, "status": status,
                "startTimeUtc": "2026-10-09T08:30:00Z",
            }], self.old_job))
        for status in ("Failed", "Cancelled", "Completed", "InProgress"):
            cases.append((self.failed_history() + [{
                "id": self.new_job, "status": status,
                "startTimeUtc": "2026-10-09T08:31:00Z",
            }], self.old_job))
        for history, acknowledged in cases:
            with self.subTest(history=history, acknowledged=acknowledged):
                self.reset_case()
                self.write_checkpoint("Failed", self.old_job)
                self.histories["b2s"] = history
                original = self.checkpoint_path().read_bytes()
                with self.assertRaisesRegex(DeploymentError, "exact latest failed native job"):
                    self.run_stage(retry_failed_job=acknowledged)
                self.assertEqual(self.checkpoint_path().read_bytes(), original)
                self.client.request.assert_not_called()
                self.time.sleep.assert_not_called()

    def test_exact_failed_retry_is_blocked_if_another_sap_stage_is_active(self):
        for status in ("NotStarted", "InProgress"):
            with self.subTest(status=status):
                self.reset_case()
                self.write_checkpoint("Failed", self.old_job)
                self.histories["b2s"] = self.failed_history()
                self.histories["s2g"] = [{"id": self.other_job, "status": status}]
                original = self.checkpoint_path().read_bytes()
                with self.assertRaisesRegex(DeploymentError, "Another SAP stage is active"):
                    self.run_stage(retry_failed_job=self.old_job)
                self.assertEqual(self.checkpoint_path().read_bytes(), original)
                self.client.request.assert_not_called()

    def test_exact_failed_retry_is_blocked_by_any_active_job_in_the_same_stage(self):
        for status in ("NotStarted", "InProgress"):
            with self.subTest(status=status):
                self.reset_case()
                self.write_checkpoint("Failed", self.old_job)
                self.histories["b2s"] = self.failed_history()
                self.histories["b2s"][1]["status"] = status
                original = self.checkpoint_path().read_bytes()
                with self.assertRaisesRegex(DeploymentError, "uncheckpointed SAP job"):
                    self.run_stage(retry_failed_job=self.old_job)
                self.assertEqual(self.checkpoint_path().read_bytes(), original)
                self.client.request.assert_not_called()

    def test_latest_failed_retry_is_allowed_despite_older_completed_history(self):
        for checkpointed in (False, True):
            with self.subTest(checkpointed=checkpointed):
                self.reset_case()
                self.histories["b2s"] = self.failed_history("Cancelled")
                self.histories["b2s"][1].update(
                    status="Completed", endTimeUtc="2026-10-09T08:10:00Z",
                )
                if checkpointed:
                    self.write_checkpoint("Completed", self.other_job)
                self.before_post = lambda: self.assert_checkpoint("ambiguous_submission", None)
                self.queue_results("b2s", self.new_job, "Completed")
                result = self.run_stage(retry_failed_job=self.old_job)
                self.assertEqual(result, self.assert_checkpoint("Completed", self.new_job))
                self.assertEqual(self.client.request.call_args_list, [
                    call("POST", self.jobs_path("b2s") + "?jobType=Pipeline", {}),
                    call("GET", self.jobs_path("b2s") + "/" + self.new_job),
                ])

    def test_completed_rerun_and_failed_retry_cannot_be_requested_together(self):
        self.write_checkpoint("Failed", self.old_job)
        self.histories["b2s"] = self.failed_history()
        original = self.checkpoint_path().read_bytes()
        with self.assertRaisesRegex(DeploymentError, "Choose either"):
            self.run_stage(after_completed_job=self.other_job, retry_failed_job=self.old_job)
        self.assertEqual(self.checkpoint_path().read_bytes(), original)
        self.client.list.assert_not_called()
        self.client.request.assert_not_called()

    def test_failed_retry_poll_failure_resumes_the_new_accepted_job_without_another_submission(self):
        self.write_checkpoint("Failed", self.old_job)
        self.histories["b2s"] = self.failed_history()
        self.queue_results("b2s", self.new_job, OSError("Polling response lost"))
        with self.assertRaisesRegex(OSError, "Polling response lost"):
            self.run_stage(retry_failed_job=self.old_job)
        self.assert_checkpoint("accepted", self.new_job)

        self.histories["b2s"].append({
            "id": self.new_job, "status": "InProgress",
            "startTimeUtc": "2026-10-09T08:31:00Z",
        })
        self.queue_results("b2s", self.new_job, "Completed")
        result = self.run_stage()
        self.assertEqual(result, self.assert_checkpoint("Completed", self.new_job))
        self.assertEqual(
            len([c for c in self.client.request.call_args_list if c.args[0] == "POST"]), 1,
        )

    def test_retry_cannot_resubmit_when_history_has_not_caught_up_to_accepted_checkpoint(self):
        self.write_checkpoint("Failed", self.old_job)
        self.histories["b2s"] = self.failed_history()
        self.queue_results("b2s", self.new_job, OSError("Polling response lost"))
        with self.assertRaisesRegex(OSError, "Polling response lost"):
            self.run_stage(retry_failed_job=self.old_job)
        self.assert_checkpoint("accepted", self.new_job)
        original = self.checkpoint_path().read_bytes()

        self.queue_results("b2s", self.new_job, "Completed")
        with self.assertRaises(DeploymentError):
            self.run_stage(retry_failed_job=self.old_job)
        self.assertEqual(self.checkpoint_path().read_bytes(), original)
        self.assertEqual(
            len([c for c in self.client.request.call_args_list if c.args[0] == "POST"]), 1,
        )

    def test_unknown_poll_status_does_not_destroy_accepted_checkpoint(self):
        self.queue_results("b2s", self.new_job, "UnexpectedServiceState")
        with self.assertRaisesRegex(DeploymentError, "Unknown SAP job status"):
            self.run_stage()
        self.assert_checkpoint("accepted", self.new_job)
        self.time.sleep.assert_not_called()

        self.histories["b2s"] = [{"id": self.new_job, "status": "InProgress"}]
        self.queue_results("b2s", self.new_job, "Completed")
        self.run_stage()
        self.assert_checkpoint("Completed", self.new_job)
        self.assertEqual(
            len([c for c in self.client.request.call_args_list if c.args[0] == "POST"]), 1,
        )

    def test_retry_preserves_newer_checkpoint_even_when_history_lags_completion(self):
        for status in ("accepted", "InProgress", "Completed", "Failed"):
            with self.subTest(status=status):
                self.reset_case()
                self.write_checkpoint(status, self.new_job)
                self.histories["b2s"] = self.failed_history()
                original = self.checkpoint_path().read_bytes()
                with self.assertRaisesRegex(DeploymentError, "newer accepted SAP job"):
                    self.run_stage(retry_failed_job=self.old_job)
                self.assertEqual(self.checkpoint_path().read_bytes(), original)
                self.client.request.assert_not_called()

    def test_retry_requires_chronology_before_replacing_a_different_checkpoint(self):
        for missing in (self.old_job, self.other_job):
            with self.subTest(missing=missing):
                self.reset_case()
                self.write_checkpoint("Completed", self.other_job)
                self.histories["b2s"] = self.failed_history()
                next(j for j in self.histories["b2s"] if j["id"] == missing).pop("startTimeUtc")
                original = self.checkpoint_path().read_bytes()
                with self.assertRaises(DeploymentError):
                    self.run_stage(retry_failed_job=self.old_job)
                self.assertEqual(self.checkpoint_path().read_bytes(), original)
                self.client.request.assert_not_called()

    def test_unknown_history_state_in_either_native_stage_blocks_submission(self):
        for stage in ("b2s", "s2g"):
            for status in ("UnexpectedServiceState", "completed", None):
                with self.subTest(stage=stage, status=status):
                    self.reset_case()
                    self.histories[stage] = [{"id": self.old_job, "status": status}]
                    with self.assertRaisesRegex(DeploymentError, "Unknown native SAP job state"):
                        self.run_stage()
                    self.client.request.assert_not_called()
                    self.assertFalse(self.checkpoint_path().exists())

    def test_wrong_checkpoint_workspace_or_pipeline_is_not_overwritten_or_submitted(self):
        for overrides in (
            {"workspace_id": "other-workspace"},
            {"pipeline_id": self.pipelines["s2g"]["id"]},
            {"workspace_id": "other-workspace", "pipeline_id": "other-pipeline"},
        ):
            with self.subTest(overrides=overrides):
                self.reset_case()
                self.write_checkpoint("accepted", self.old_job, **overrides)
                original = self.checkpoint_path().read_bytes()
                with self.assertRaisesRegex(DeploymentError, "another native target"):
                    self.run_stage()
                self.assertEqual(self.checkpoint_path().read_bytes(), original)
                self.client.list.assert_not_called()
                self.client.request.assert_not_called()

    def test_missing_checkpointed_job_is_not_replaced_with_a_new_job(self):
        self.write_checkpoint("accepted", self.old_job)
        self.histories["b2s"] = [{"id": self.other_job, "status": "Completed"}]
        original = self.checkpoint_path().read_bytes()
        with self.assertRaisesRegex(DeploymentError, "Checkpointed SAP job is missing"):
            self.run_stage()
        self.assertEqual(self.checkpoint_path().read_bytes(), original)
        self.client.request.assert_not_called()

    def test_uncheckpointed_active_job_is_not_adopted_or_resubmitted(self):
        for status in ("NotStarted", "InProgress"):
            with self.subTest(status=status):
                self.reset_case()
                self.histories["b2s"] = [{"id": self.old_job, "status": status}]
                with self.assertRaisesRegex(DeploymentError, "uncheckpointed SAP job"):
                    self.run_stage()
                self.client.request.assert_not_called()
                self.assertFalse(self.checkpoint_path().exists())

    def test_other_active_native_stage_blocks_new_submission(self):
        self.histories["s2g"] = [{"id": self.old_job, "status": "InProgress"}]
        with self.assertRaisesRegex(DeploymentError, "Another SAP stage is active"):
            self.run_stage()
        self.client.request.assert_not_called()
        self.assertFalse(self.checkpoint_path().exists())

    def test_multiple_active_jobs_block_even_a_matching_checkpoint(self):
        self.write_checkpoint("InProgress", self.old_job)
        self.histories["b2s"] = [
            {"id": self.old_job, "status": "InProgress"},
            {"id": self.other_job, "status": "NotStarted"},
        ]
        original = self.checkpoint_path().read_bytes()
        with self.assertRaisesRegex(DeploymentError, "Multiple active SAP runs"):
            self.run_stage()
        self.client.request.assert_not_called()
        self.assertEqual(self.checkpoint_path().read_bytes(), original)

    def completed_history(self):
        return [
            {"id": self.old_job, "status": "Completed", "endTimeUtc": "2026-01-02T00:00:00Z"},
            {"id": self.other_job, "status": "Completed", "endTimeUtc": "2026-01-01T00:00:00Z"},
        ]

    def test_completed_history_requires_exact_latest_id_before_rerun(self):
        for acknowledged in (None, self.other_job, self.new_job):
            with self.subTest(acknowledged=acknowledged):
                self.reset_case()
                self.histories["b2s"] = self.completed_history()
                with self.assertRaisesRegex(DeploymentError, "exact latest job ID"):
                    self.run_stage(after_completed_job=acknowledged)
                self.client.request.assert_not_called()
                self.assertFalse(self.checkpoint_path().exists())

    def test_exact_latest_completed_acknowledgement_allows_one_native_rerun(self):
        self.write_checkpoint("Completed", self.old_job)
        self.histories["b2s"] = self.completed_history()
        self.before_post = lambda: self.assert_checkpoint("ambiguous_submission", None)
        self.queue_results("b2s", self.new_job, "Completed")
        result = self.run_stage(after_completed_job=self.old_job)
        self.assertEqual(result, self.assert_checkpoint("Completed", self.new_job))
        self.assertEqual(
            self.client.request.call_args_list,
            [
                call("POST", self.jobs_path("b2s") + "?jobType=Pipeline", {}),
                call("GET", self.jobs_path("b2s") + "/" + self.new_job),
            ],
        )

    def test_completed_checkpoint_is_confirmed_without_starting_another_run(self):
        self.write_checkpoint("Completed", self.old_job)
        self.histories["b2s"] = self.completed_history()
        self.queue_results("b2s", self.old_job, "Completed")
        result = self.run_stage()
        self.assertEqual(result, self.assert_checkpoint("Completed", self.old_job))
        self.assert_no_submission()
        self.client.request.assert_called_once_with(
            "GET", self.jobs_path("b2s") + "/" + self.old_job,
        )

    def test_s2g_without_b2s_checkpoint_never_submits(self):
        with self.assertRaises((DeploymentError, FileNotFoundError)):
            self.run_stage("s2g")
        self.client.request.assert_not_called()
        self.assertFalse(self.checkpoint_path("s2g").exists())

    def test_s2g_requires_locally_completed_b2s_before_any_job_request(self):
        for state in ("accepted", "NotStarted", "InProgress", "Failed", "Cancelled"):
            with self.subTest(state=state):
                self.reset_case()
                self.write_checkpoint(state, self.old_job)
                original = self.checkpoint_path().read_bytes()
                with self.assertRaisesRegex(DeploymentError, "Bronze-to-Silver must complete"):
                    self.run_stage("s2g")
                self.client.request.assert_not_called()
                self.assertFalse(self.checkpoint_path("s2g").exists())
                self.assertEqual(self.checkpoint_path().read_bytes(), original)

    def test_s2g_requires_live_b2s_completion_not_just_a_completed_local_file(self):
        for status in ("NotStarted", "InProgress", "Failed", "Cancelled", "Canceled", "Deduped", "Unknown"):
            with self.subTest(status=status):
                self.reset_case()
                self.write_checkpoint("Completed", self.old_job)
                self.histories["b2s"] = [{"id": self.old_job, "status": "Completed"}]
                self.queue_results("b2s", self.old_job, status)
                original = self.checkpoint_path().read_bytes()
                with self.assertRaisesRegex(DeploymentError, "prerequisite readback is not Completed"):
                    self.run_stage("s2g")
                self.client.request.assert_called_once_with(
                    "GET", self.jobs_path("b2s") + "/" + self.old_job,
                )
                self.assert_no_submission()
                self.assertFalse(self.checkpoint_path("s2g").exists())
                self.assertEqual(self.checkpoint_path().read_bytes(), original)

    def test_s2g_reads_native_b2s_completion_before_submitting_gold_pipeline(self):
        self.write_checkpoint("Completed", self.old_job)
        self.write_silver_proof()
        self.histories["b2s"] = [{"id": self.old_job, "status": "Completed"}]
        self.queue_results("b2s", self.old_job, "Completed")
        self.queue_results("s2g", self.new_job, "InProgress", "Completed")
        self.post_result = (202, {"location": self.location("s2g", self.new_job)}, {})
        original = self.checkpoint_path().read_bytes()
        self.before_post = lambda: self.assert_checkpoint(
            "ambiguous_submission", None, "s2g",
        )
        result = self.run_stage("s2g", timeout=60)

        self.assertEqual(result, self.assert_checkpoint("Completed", self.new_job, "s2g"))
        self.assertEqual(self.checkpoint_path().read_bytes(), original)
        self.assertEqual(
            self.client.item.call_args_list,
            [
                call("bps_s2g_full_processing_pipeline_fea347cc", "DataPipeline"),
                call("bps_datasphere_b2s_orchestration_pipeline_fea347cc", "DataPipeline"),
            ],
        )
        self.assertEqual(
            self.client.request.call_args_list,
            [
                call("GET", self.jobs_path("b2s") + "/" + self.old_job),
                call("POST", self.jobs_path("s2g") + "?jobType=Pipeline", {}),
                call("GET", self.jobs_path("s2g") + "/" + self.new_job),
                call("GET", self.jobs_path("s2g") + "/" + self.new_job),
            ],
        )
        self.time.sleep.assert_called_once_with(30)

    def test_s2g_resume_still_checks_b2s_and_never_submits_another_gold_job(self):
        self.write_checkpoint("Completed", self.old_job)
        self.write_silver_proof()
        self.write_checkpoint("InProgress", self.new_job, stage="s2g")
        self.histories["b2s"] = [{"id": self.old_job, "status": "Completed"}]
        self.histories["s2g"] = [{"id": self.new_job, "status": "InProgress"}]
        self.queue_results("b2s", self.old_job, "Completed")
        self.queue_results("s2g", self.new_job, "Completed")
        result = self.run_stage("s2g")
        self.assertEqual(result, self.assert_checkpoint("Completed", self.new_job, "s2g"))
        self.assert_no_submission()
        self.assertEqual(
            self.client.request.call_args_list,
            [
                call("GET", self.jobs_path("b2s") + "/" + self.old_job),
                call("GET", self.jobs_path("s2g") + "/" + self.new_job),
            ],
        )

    def test_s2g_refuses_missing_or_mismatched_silver_proof(self):
        for wrong in (None, {"data_verified": False}, {"source_stage": "gold"}, {"workspace_id": "another"},
                      {"jobs": {"b2s": {"pipeline_id": self.pipelines["b2s"]["id"], "job_id": self.new_job}}}):
            with self.subTest(wrong=wrong):
                self.reset_case()
                self.write_checkpoint("Completed", self.old_job)
                self.histories["b2s"] = [{"id": self.old_job, "status": "Completed"}]
                self.queue_results("b2s", self.old_job, "Completed")
                if wrong is not None:
                    self.write_silver_proof(**wrong)
                with self.assertRaises((DeploymentError, FileNotFoundError)):
                    self.run_stage("s2g")
                self.assert_no_submission()
                self.assertFalse(self.checkpoint_path("s2g").exists())

    def test_s2g_refuses_silver_proof_after_a_newer_native_b2s_run(self):
        self.write_checkpoint("Completed", self.old_job)
        self.write_silver_proof()
        self.histories["b2s"] = [
            {"id": self.old_job, "status": "Completed", "startTimeUtc": "2026-10-09T08:00:00Z"},
            {"id": self.new_job, "status": "Completed", "startTimeUtc": "2026-10-09T09:00:00Z"},
        ]
        self.queue_results("b2s", self.old_job, "Completed")
        with self.assertRaisesRegex(DeploymentError, "latest completed native B2S"):
            self.run_stage("s2g")
        self.assert_no_submission()

    def test_adopt_latest_scheduled_run_preserves_existing_job_and_never_posts(self):
        self.write_checkpoint("Completed", self.old_job)
        self.histories["b2s"] = [{"id": self.new_job, "status": "InProgress"}]
        self.queue_results("b2s", self.new_job,
                           {"id": self.new_job, "itemId": self.pipelines["b2s"]["id"], "jobType": "Pipeline",
                            "invokeType": "Scheduled", "status": "InProgress"}, "Completed")
        result = self.run_stage(adopt_scheduled_job=self.new_job)
        self.assertEqual(result, self.assert_checkpoint("Completed", self.new_job))
        self.assertEqual(result["adopted_scheduled_job"], self.new_job)
        self.assert_no_submission()

    def test_adoption_rejects_non_scheduled_or_mismatched_native_jobs(self):
        for changed in ({"invokeType": "Manual"}, {"itemId": "another"}, {"id": self.other_job},
                        {"jobType": "Refresh"}, {"status": "Failed"}):
            with self.subTest(changed=changed):
                self.reset_case()
                self.write_checkpoint("Completed", self.old_job)
                original = self.checkpoint_path().read_bytes()
                self.histories["b2s"] = [{"id": self.new_job, "status": "InProgress"}]
                actual = {"id": self.new_job, "itemId": self.pipelines["b2s"]["id"],
                          "jobType": "Pipeline", "invokeType": "Scheduled", "status": "InProgress", **changed}
                self.queue_results("b2s", self.new_job, actual)
                with self.assertRaisesRegex(DeploymentError, "scheduled SAP job"):
                    self.run_stage(adopt_scheduled_job=self.new_job)
                self.assertEqual(self.checkpoint_path().read_bytes(), original)
                self.assert_no_submission()

    def test_adoption_cannot_discard_an_accepted_job_or_select_an_older_one(self):
        self.write_checkpoint("accepted", self.old_job)
        self.histories["b2s"] = [{"id": self.new_job, "status": "InProgress"}]
        original = self.checkpoint_path().read_bytes()
        for job in (self.old_job, self.new_job):
            with self.subTest(job=job), self.assertRaises(DeploymentError):
                self.run_stage(adopt_scheduled_job=job)
        self.assertEqual(self.checkpoint_path().read_bytes(), original)
        self.client.request.assert_not_called()

    def test_workspace_validation_failure_has_no_submission_or_checkpoint(self):
        self.client.workspace.side_effect = DeploymentError("Workspace not approved")
        with self.assertRaisesRegex(DeploymentError, "Workspace not approved"):
            self.run_stage()
        self.client.item.assert_not_called()
        self.client.list.assert_not_called()
        self.client.request.assert_not_called()
        self.assertFalse(self.checkpoint_path().exists())

    def test_history_transport_failure_has_no_submission_or_checkpoint(self):
        self.client.list.side_effect = OSError("History read failed")
        with self.assertRaisesRegex(OSError, "History read failed"):
            self.run_stage()
        self.client.request.assert_not_called()
        self.assertFalse(self.checkpoint_path().exists())


if __name__ == "__main__":
    unittest.main()
