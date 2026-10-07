import json
import unittest
from unittest.mock import patch

from fabric.deploy import run_notebook
from fabric.rest import BASE, DeploymentError, FabricClient


class FakeTransport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.time = 0

    def __call__(self, method, url, body, skill):
        self.calls.append((method, url, body, skill))
        return next(self.responses)

    def sleep(self, seconds):
        self.time += seconds

    def client(self, timeout=60):
        return FabricClient("fixture-tenant", transport=self, sleep=self.sleep,
                            clock=lambda: self.time, timeout=timeout)


class RestTests(unittest.TestCase):
    def test_lro_poll_and_result_preserve_attribution_and_public_host(self):
        t = FakeTransport([
            (202, {"x-ms-operation-id": "fixture-operation", "Location": "https://redirect.analysis.windows.net/v1/operations/fixture-operation", "Retry-After": "2"}, {}),
            (200, {}, {"status": "Running"}),
            (200, {}, {"status": "Succeeded"}),
            (200, {}, {"definition": {"parts": []}})
        ])
        result = t.client().operation("POST", "/v1/fixture", {}, "fabriciq-ontology-cli", True)
        self.assertIn("definition", result)
        self.assertTrue(all(c[1].startswith(BASE) for c in t.calls))
        self.assertTrue(all(c[3] == "fabriciq-ontology-cli" for c in t.calls))
        self.assertTrue(t.calls[-1][1].endswith("/result"))
        self.assertEqual(sum(c[0] == "POST" for c in t.calls), 1)

    def test_failed_and_cancelled_lros_are_not_success(self):
        for state in ("Failed", "Cancelled", "Canceled"):
            t = FakeTransport([(202, {"x-ms-operation-id": "fixture"}, {}),
                               (200, {}, {"status": state, "error": {"errorCode": "FixtureDenied"}})])
            with self.subTest(state=state), self.assertRaisesRegex(DeploymentError, state):
                t.client().operation("POST", "/v1/fixture", {})
            self.assertEqual(len(t.calls), 2)

    def test_permission_failure_and_post_ambiguity_no_retry(self):
        t = FakeTransport([(403, {}, {"errorCode": "InsufficientPrivileges"})])
        with self.assertRaisesRegex(DeploymentError, "permission denied"):
            t.client().operation("POST", "/v1/fixture", {})
        self.assertEqual(len(t.calls), 1)
        t = FakeTransport([(202, {}, {})])
        with self.assertRaisesRegex(DeploymentError, "ambiguous"):
            t.client().operation("POST", "/v1/fixture", {})
        self.assertEqual(len(t.calls), 1)

    def test_lro_timeout_is_bounded(self):
        t = FakeTransport([(202, {"x-ms-operation-id": "fixture"}, {}),
                           (200, {}, {"status": "Running"}),
                           (200, {}, {"status": "Running"})])
        with self.assertRaisesRegex(DeploymentError, "deadline"):
            t.client(timeout=6).operation("POST", "/v1/fixture", {})
        self.assertEqual(sum(c[0] == "POST" for c in t.calls), 1)

    def test_429_retry_after_and_attribution(self):
        t = FakeTransport([(429, {"Retry-After": "3"}, {}), (200, {}, {"value": []})])
        self.assertEqual(t.client().list("/v1/items", "eventstream-cli"), [])
        self.assertEqual(t.time, 3)
        self.assertTrue(all(c[3] == "eventstream-cli" for c in t.calls))

    def test_http_transport_has_real_attribution_header(self):
        class Response:
            status = 200
            headers = {}
            def read(self):
                return b"{}"
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        with patch("fabric.rest.token", return_value="fixture-token"), patch("fabric.rest.urlopen", return_value=Response()) as http:
            FabricClient("fixture-tenant").request("GET", "/v1/workspaces", skill="eventhouse-cli")
            request = http.call_args.args[0]
            self.assertEqual(request.get_header("X-ms-fabric-skill"), "eventhouse-cli")

    def test_cross_host_token_leak_and_pagination_cycle_rejected(self):
        t = FakeTransport([])
        with self.assertRaisesRegex(DeploymentError, "host"):
            t.client().request("GET", "https://evil.example/v1/items")
        t = FakeTransport([(200, {}, {"value": [], "continuationUri": "/v1/items"})])
        with self.assertRaisesRegex(DeploymentError, "cycle"):
            t.client().list("/v1/items")

    def test_notebook_job_is_not_a_control_plane_lro(self):
        location = BASE + "/v1/workspaces/fixture/items/fixture/jobs/instances/fixture-job"
        t = FakeTransport([(200, {}, {"value": []}), (202, {"Location": location, "Retry-After": "2"}, {}),
                           (200, {}, {"status": "InProgress"}), (200, {}, {"status": "Completed"})])
        client = t.client()
        result = run_notebook(client, "fixture", {"id": "fixture"})
        self.assertEqual(result["job_id"], "fixture-job")
        self.assertTrue(t.calls[1][1].endswith("/jobs/RunNotebook/instances"))
        self.assertTrue(all("/operations/" not in c[1] for c in t.calls))
        self.assertEqual(sum(c[0] == "POST" for c in t.calls), 1)

    def test_recent_job_blocks_duplicate(self):
        from datetime import datetime, timezone
        t = FakeTransport([(200, {}, {"value": [{"id": "fixture-existing",
             "startTimeUtc": datetime.now(timezone.utc).isoformat(), "status": "InProgress"}]})])
        with self.assertRaisesRegex(DeploymentError, "No duplicate"):
            run_notebook(t.client(), "fixture", {"id": "fixture"})
        self.assertTrue(all(c[0] == "GET" for c in t.calls))


if __name__ == "__main__":
    unittest.main()
