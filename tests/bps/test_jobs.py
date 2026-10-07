"""Native-only orchestration guardrails; no Azure login or Fabric writes in tests."""
import json
import tempfile
import unittest
from pathlib import Path

from fabric.rest import DeploymentError
from sources.salesforce.bps.jobs import SKILL, STAGES, run_stage

WS = "11111111-1111-4111-8111-111111111111"
SUFFIX = "1234abcd"
JOB = "22222222-2222-4222-8222-222222222222"


class Client:
    def __init__(self):
        self.items = [
            {"id": name, "type": "DataPipeline", "displayName": prefix + SUFFIX}
            for name, prefix in STAGES.items()
        ]
        self.jobs = {name: [] for name in STAGES}
        self.jobs["extraction"] = [{"id": JOB, "status": "Completed"}]
        self.requests = []
        self.statuses = ["Completed"]
        self.location = f"https://api.fabric.microsoft.com/v1/workspaces/{WS}/items/silver/jobs/instances/{JOB}"

    def list(self, path, skill):
        assert skill == SKILL
        if path.endswith("/items"):
            return self.items
        return self.jobs[path.split("/items/")[1].split("/")[0]]

    def request(self, method, path, body=None, skill=None):
        assert skill == SKILL
        self.requests.append((method, path))
        if method == "POST":
            return 202, {"location": self.location}, {}
        state = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return 200, {}, {"status": state, "id": JOB}


class NativeJobsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.client = Client()

    def run_stage(self, **options):
        return run_stage(self.client, WS, SUFFIX, "silver", self.directory, **options)

    def test_submission_is_checkpointed_before_first_get(self):
        original = self.client.request

        def request(method, path, body=None, skill=None):
            if method == "GET":
                evidence = json.loads((self.directory / "silver-job.json").read_text())
                self.assertEqual(JOB, evidence["job_id"])
                self.assertFalse(evidence["data_verified"])
            return original(method, path, body, skill)

        self.client.request = request
        result = self.run_stage()
        self.assertEqual("Completed", result["state"])
        self.assertEqual(1, sum(m == "POST" for m, _ in self.client.requests))
        self.assertTrue(self.client.requests[0][1].endswith("?jobType=Pipeline"))

    def test_existing_active_run_is_not_submitted_again(self):
        self.client.jobs["silver"] = [{"id": JOB, "status": "InProgress"}]
        self.run_stage()
        self.assertFalse(any(m == "POST" for m, _ in self.client.requests))

    def test_completed_run_is_read_back_without_resubmission(self):
        self.client.jobs["silver"] = [{"id": JOB, "status": "Completed"}]
        self.run_stage()
        self.assertFalse(any(m == "POST" for m, _ in self.client.requests))

    def test_other_stage_active_blocks_submission(self):
        self.client.jobs["dimensions"] = [{"id": JOB, "status": "InProgress"}]
        with self.assertRaises(DeploymentError):
            self.run_stage()
        self.assertEqual([], self.client.requests)

    def test_missing_completed_prerequisite_blocks_submission(self):
        self.client.jobs["extraction"] = []
        with self.assertRaises(DeploymentError):
            self.run_stage()
        self.assertEqual([], self.client.requests)

    def test_exact_name_not_prefix_substitute(self):
        self.client.items[1]["displayName"] += "_copy"
        with self.assertRaises(DeploymentError):
            self.run_stage()
        self.assertEqual([], self.client.requests)

    def test_ambiguous_location_prevents_subsequent_post(self):
        self.client.location = "https://another.example/jobs/" + JOB
        with self.assertRaises(DeploymentError):
            self.run_stage()
        with self.assertRaises(DeploymentError):
            self.run_stage()
        self.assertEqual(1, sum(m == "POST" for m, _ in self.client.requests))

    def test_unknown_job_state_blocks_submission(self):
        self.client.jobs["silver"] = [{"id": JOB, "status": "NewUnknownState"}]
        with self.assertRaises(DeploymentError):
            self.run_stage()
        self.assertEqual([], self.client.requests)

    def test_stale_completed_acknowledgement_is_rejected(self):
        self.client.jobs["silver"] = [{"id": JOB, "status": "Completed"}]
        with self.assertRaises(DeploymentError):
            self.run_stage(after_completed_job="33333333-3333-4333-8333-333333333333")
        self.assertEqual([], self.client.requests)

    def test_timeout_keeps_submitted_id(self):
        self.client.statuses = ["InProgress"]
        now = [0]

        def sleep(seconds):
            now[0] += seconds

        with self.assertRaises(DeploymentError):
            self.run_stage(timeout=60, clock=lambda: now[0], sleep=sleep)
        evidence = json.loads((self.directory / "silver-job.json").read_text())
        self.assertEqual(JOB, evidence["job_id"])
        self.assertEqual(1, sum(m == "POST" for m, _ in self.client.requests))


if __name__ == "__main__":
    unittest.main()
