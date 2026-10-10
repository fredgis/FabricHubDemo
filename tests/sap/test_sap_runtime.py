import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from fabric.rest import DeploymentError
from sources.sap import runtime


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="sap-runtime-test-", dir=".")
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
        self.environment = {
            "id": "00000000-0000-0000-0000-000000000010",
            "displayName": "bps_env_fea347cc",
            "type": "Environment",
        }
        self.pipelines = [
            {
                "id": "00000000-0000-0000-0000-000000000011",
                "displayName": "bps_datasphere_b2s_orchestration_pipeline_fea347cc",
                "type": "DataPipeline",
            },
            {
                "id": "00000000-0000-0000-0000-000000000012",
                "displayName": "bps_s2g_full_processing_pipeline_fea347cc",
                "type": "DataPipeline",
            },
        ]
        self.root = "/v1/workspaces/" + self.target["workspace_id"]
        self.base = self.root + "/environments/" + self.environment["id"]
        self.client = Mock(spec=runtime.ScopedClient)
        self.client.item.side_effect = self.lookup_item
        self.client.list.side_effect = self.list_items
        self.client.request.side_effect = self.request
        self.constructor = self.start_patch(
            "sources.sap.runtime.ScopedClient", return_value=self.client,
        )
        self.libraries = self.start_patch(
            "sources.sap.runtime.libraries", side_effect=self.list_libraries,
        )
        self.verifier = self.start_patch(
            "sources.sap.runtime.verify_runtime_only", wraps=runtime.verify_runtime_only,
        )
        self.time = self.start_patch("sources.sap.runtime.time")
        self.time.monotonic.side_effect = lambda: self.now
        self.time.sleep.side_effect = self.advance_clock
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
        self.checkpoint = self.output / str(self.case_number) / "runtime.json"
        self.before = {
            "runtimeVersion": "2.0",
            "driverCores": 4,
            "driverMemory": "28g",
            "executorCores": 4,
            "executorMemory": "28g",
            "dynamicExecutorAllocation": {
                "enabled": True, "minExecutors": 1, "maxExecutors": 3,
            },
            "sparkProperties": {
                "spark.sql.shuffle.partitions": "8",
                "spark.sql.session.timeZone": "UTC",
            },
            "instancePool": {"id": "dedicated-sap-pool", "name": "SAP pool"},
        }
        self.before_libraries = [
            {"name": "semantic-link", "version": "0.12.0", "type": "PyPI"},
            {"name": "native-bps.whl", "type": "Custom"},
        ]
        self.published = copy.deepcopy(self.before)
        self.staged = copy.deepcopy(self.before)
        self.published_libraries = copy.deepcopy(self.before_libraries)
        self.staged_libraries = copy.deepcopy(self.before_libraries)
        self.patch_compute = {**copy.deepcopy(self.before), "runtimeVersion": "1.3"}
        self.patch_libraries = copy.deepcopy(self.before_libraries)
        self.publish_compute = copy.deepcopy(self.patch_compute)
        self.publish_libraries = copy.deepcopy(self.before_libraries)
        self.initial_publish_state = "Success"
        self.publish_states = ["Success"]
        self.publish_started = False
        self.post_result = (202, {}, {})
        self.histories = {pipeline["id"]: [] for pipeline in self.pipelines}
        self.before_patch = None
        self.before_post = None
        self.before_poll = None
        self.now = 1000
        for mocked in (self.client, self.constructor, self.libraries, self.verifier, self.time):
            mocked.reset_mock()

    def advance_clock(self, seconds):
        self.assertGreater(seconds, 0)
        self.now += seconds

    def lookup_item(self, name, item_type):
        self.assertEqual((name, item_type), ("bps_env_fea347cc", "Environment"))
        return copy.deepcopy(self.environment)

    def jobs_path(self, pipeline_id):
        return self.root + "/items/" + pipeline_id + "/jobs/instances"

    def list_items(self, path):
        if path == self.root + "/items":
            return copy.deepcopy(self.pipelines) + [
                {
                    "id": "unrelated-pipeline",
                    "displayName": "bps_s2g_full_processing_pipeline_deadbeef",
                    "type": "DataPipeline",
                },
                {
                    "id": "unrelated-notebook",
                    "displayName": "notebook_fea347cc",
                    "type": "Notebook",
                },
            ]
        for pipeline_id, history in self.histories.items():
            if path == self.jobs_path(pipeline_id):
                return copy.deepcopy(history)
        self.fail("Unexpected native SAP history read: " + path)

    def list_libraries(self, client, base, staging=False):
        self.assertIs(client, self.client)
        self.assertEqual(base, self.base)
        return copy.deepcopy(self.staged_libraries if staging else self.published_libraries)

    def request(self, method, path, *args, **kwargs):
        self.assertEqual(kwargs, {})
        if method == "PATCH":
            self.assertEqual(path, self.base + "/staging/sparkcompute?beta=false")
            self.assertEqual(args, ({"runtimeVersion": "1.3"},))
            if self.before_patch:
                self.before_patch()
            self.staged = copy.deepcopy(self.patch_compute)
            self.staged_libraries = copy.deepcopy(self.patch_libraries)
            return 200, {}, copy.deepcopy(self.staged)
        if method == "POST":
            self.assertEqual(path, self.base + "/staging/publish?beta=false")
            self.assertEqual(args, ({},))
            if self.before_post:
                self.before_post()
            if isinstance(self.post_result, Exception):
                raise self.post_result
            self.publish_started = self.post_result[0] in (200, 202)
            return copy.deepcopy(self.post_result)
        self.assertEqual(method, "GET", "Only a runtime PATCH and environment publish are allowed")
        self.assertEqual(args, ())
        if path == self.base + "/sparkcompute?beta=false":
            return 200, {}, copy.deepcopy(self.published)
        if path == self.base + "/staging/sparkcompute?beta=false":
            return 200, {}, copy.deepcopy(self.staged)
        self.assertEqual(path, self.base, "Unexpected environment readback")
        state = self.initial_publish_state
        if self.publish_started:
            if self.before_poll:
                self.before_poll()
            self.assertTrue(self.publish_states, "No publication response configured")
            state = self.publish_states[0]
            if len(self.publish_states) > 1:
                self.publish_states.pop(0)
            if state == "Success":
                self.published = copy.deepcopy(self.publish_compute)
                self.published_libraries = copy.deepcopy(self.publish_libraries)
        return 200, {}, {"properties": {"publishDetails": {"state": state}}}

    def read_checkpoint(self):
        return json.loads(self.checkpoint.read_text(encoding="utf-8"))

    def assert_checkpoint(self, status):
        row = self.read_checkpoint()
        self.assertEqual(row["environment_id"], self.environment["id"])
        self.assertEqual(row["status"], status)
        self.assertEqual(row["before"], self.before)
        self.assertEqual(row["libraries_before"], self.before_libraries)
        self.assertEqual(row["target_runtime"], "1.3")
        self.assertFalse(list(self.checkpoint.parent.glob("*.tmp")))
        return row

    def assert_no_writes(self):
        self.assertFalse([
            c for c in self.client.request.call_args_list if c.args[0] != "GET"
        ])
        self.verifier.assert_not_called()
        self.time.sleep.assert_not_called()

    def recover(self, apply=True):
        return runtime.recover(self.target, self.checkpoint, apply=apply)

    def test_preview_inspects_only_the_dedicated_environment_without_writing(self):
        self.staged["runtimeVersion"] = "1.3"
        self.staged_libraries.append({"name": "unpublished.whl"})
        self.initial_publish_state = "Running"
        result = self.recover(apply=False)
        self.assertEqual(result["status"], "inspected")
        self.assertEqual(result["before"], self.before)
        self.assertEqual(result["libraries_before"], self.before_libraries)
        self.assertNotIn("after", result)
        self.constructor.assert_called_once_with(self.target)
        self.client.workspace.assert_called_once_with()
        self.client.item.assert_called_once_with("bps_env_fea347cc", "Environment")
        self.client.list.assert_not_called()
        self.assert_no_writes()
        self.assertFalse(self.checkpoint.exists())
        self.assertEqual(self.libraries.call_args_list, [
            call(self.client, self.base), call(self.client, self.base, True),
        ])

    def test_runtime_only_patch_preserves_settings_libraries_and_verifies_success_readback(self):
        self.publish_states = ["Running", "Success"]
        self.before_patch = lambda: self.assert_checkpoint("inspected")
        self.before_post = lambda: self.assert_checkpoint("ambiguous_publication")
        self.before_poll = lambda: self.assert_checkpoint("publishing")
        result = self.recover()
        self.assertEqual(result, self.assert_checkpoint("verified"))
        self.assertEqual(result["after"], {**self.before, "runtimeVersion": "1.3"})
        self.assertEqual(result["libraries_after"], self.before_libraries)
        self.assertEqual(self.before["runtimeVersion"], "2.0")
        self.assertEqual(self.client.list.call_args_list, [
            call(self.root + "/items"),
            *[call(self.jobs_path(p["id"])) for p in self.pipelines],
        ])
        self.assertEqual(self.client.request.call_args_list, [
            call("GET", self.base + "/sparkcompute?beta=false"),
            call("GET", self.base + "/staging/sparkcompute?beta=false"),
            call("GET", self.base),
            call("PATCH", self.base + "/staging/sparkcompute?beta=false", {"runtimeVersion": "1.3"}),
            call("POST", self.base + "/staging/publish?beta=false", {}),
            call("GET", self.base),
            call("GET", self.base),
            call("GET", self.base + "/sparkcompute?beta=false"),
        ])
        self.assertEqual(self.libraries.call_args_list, [
            call(self.client, self.base), call(self.client, self.base, True),
            call(self.client, self.base, True), call(self.client, self.base),
        ])
        self.assertEqual(self.verifier.call_args_list, [
            call(self.before, self.patch_compute, self.before_libraries, self.before_libraries),
            call(self.before, self.publish_compute, self.before_libraries, self.before_libraries),
        ])
        self.time.sleep.assert_called_once_with(30)

    def test_already_13_is_unchanged_and_preserves_existing_recovery_evidence(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                self.reset_case()
                self.published["runtimeVersion"] = self.staged["runtimeVersion"] = "1.3"
                original = b'{"status":"verified","before":{"runtimeVersion":"2.0"}}\n'
                if existing:
                    self.checkpoint.parent.mkdir()
                    self.checkpoint.write_bytes(original)
                result = self.recover()
                self.assertEqual(result["status"], "unchanged")
                self.assertEqual(result["before"]["runtimeVersion"], "1.3")
                self.assert_no_writes()
                if existing:
                    self.assertEqual(self.checkpoint.read_bytes(), original)
                else:
                    self.assertFalse(self.checkpoint.exists())

    def test_any_active_native_sap_pipeline_blocks_patch_and_publication(self):
        for pipeline in self.pipelines:
            for status in ("NotStarted", "InProgress"):
                with self.subTest(pipeline=pipeline["id"], status=status):
                    self.reset_case()
                    self.histories[pipeline["id"]] = [{"id": "active-job", "status": status}]
                    with self.assertRaisesRegex(DeploymentError, "processing must stop"):
                        self.recover()
                    self.assert_no_writes()
                    self.assertFalse(self.checkpoint.exists())

    def test_inactive_failed_cancelled_and_completed_histories_allow_runtime_recovery(self):
        for status in ("Failed", "Cancelled", "Canceled", "Deduped", "Completed"):
            with self.subTest(status=status):
                self.reset_case()
                for pipeline in self.pipelines:
                    self.histories[pipeline["id"]] = [{"id": "inactive-job", "status": status}]
                self.assertEqual(self.recover()["status"], "verified")

    def test_unpublished_compute_settings_or_libraries_block_all_writes(self):
        for change in ("runtime", "settings", "libraries"):
            with self.subTest(change=change):
                self.reset_case()
                if change == "runtime":
                    self.staged["runtimeVersion"] = "1.3"
                elif change == "settings":
                    self.staged["sparkProperties"]["spark.sql.shuffle.partitions"] = "16"
                else:
                    self.staged_libraries[0]["version"] = "0.13.0"
                with self.assertRaisesRegex(DeploymentError, "Unpublished or active"):
                    self.recover()
                self.assert_no_writes()
                self.assertFalse(self.checkpoint.exists())

    def test_outstanding_or_failed_publication_blocks_all_writes(self):
        for state in ("Running", "NotStarted", "InProgress", "Failed", "Cancelled", "Canceled"):
            with self.subTest(state=state):
                self.reset_case()
                self.initial_publish_state = state
                with self.assertRaisesRegex(DeploymentError, "Unpublished or active"):
                    self.recover()
                self.client.list.assert_not_called()
                self.assert_no_writes()
                self.assertFalse(self.checkpoint.exists())

    def test_unexpected_runtime_is_not_silently_downgraded(self):
        for version in ("1.2", "1.4", "3.0", None):
            with self.subTest(version=version):
                self.reset_case()
                self.published["runtimeVersion"] = self.staged["runtimeVersion"] = version
                with self.assertRaisesRegex(DeploymentError, "Unexpected native SAP runtime"):
                    self.recover()
                self.client.list.assert_not_called()
                self.assert_no_writes()
                self.assertFalse(self.checkpoint.exists())

    def test_staging_readback_must_be_runtime_only_before_any_publish(self):
        for change, message in (
            ("runtime", "runtime readback is not 1.3"),
            ("settings", "Non-runtime BPS compute settings"),
            ("libraries", "library dependencies"),
        ):
            with self.subTest(change=change):
                self.reset_case()
                if change == "runtime":
                    self.patch_compute["runtimeVersion"] = "2.0"
                elif change == "settings":
                    self.patch_compute["dynamicExecutorAllocation"]["maxExecutors"] = 9
                else:
                    self.patch_libraries[0]["version"] = "0.13.0"
                with self.assertRaisesRegex(DeploymentError, message):
                    self.recover()
                self.assert_checkpoint("inspected")
                self.assertFalse([c for c in self.client.request.call_args_list if c.args[0] == "POST"])
                self.time.sleep.assert_not_called()

    def test_publish_intent_survives_ambiguous_acceptance_and_transport_errors(self):
        for response in ((400, {}, {}), (500, {}, {}), OSError("Publish response lost")):
            with self.subTest(response=response):
                self.reset_case()
                self.post_result = response
                self.before_post = lambda: self.assert_checkpoint("ambiguous_publication")
                with self.assertRaises((DeploymentError, OSError)):
                    self.recover()
                self.assert_checkpoint("ambiguous_publication")
                original = self.checkpoint.read_bytes()
                with self.assertRaisesRegex(DeploymentError, "Unpublished or active"):
                    self.recover()
                self.assertEqual(self.checkpoint.read_bytes(), original)
                self.assertEqual(
                    len([c for c in self.client.request.call_args_list if c.args[0] == "POST"]), 1,
                )
                self.time.sleep.assert_not_called()

    def test_http_200_and_202_require_verified_publication_readback(self):
        for code in (200, 202):
            with self.subTest(code=code):
                self.reset_case()
                self.post_result = (code, {}, {})
                self.assertEqual(self.recover()["status"], "verified")
                self.assert_checkpoint("verified")
                self.time.sleep.assert_not_called()

    def test_success_state_with_wrong_runtime_changed_settings_or_libraries_is_not_verified(self):
        for change, message in (
            ("runtime", "runtime readback is not 1.3"),
            ("settings", "Non-runtime BPS compute settings"),
            ("libraries", "library dependencies"),
        ):
            with self.subTest(change=change):
                self.reset_case()
                if change == "runtime":
                    self.publish_compute["runtimeVersion"] = "2.0"
                elif change == "settings":
                    self.publish_compute["sparkProperties"]["spark.sql.session.timeZone"] = "Europe/Paris"
                else:
                    self.publish_libraries[0]["version"] = "0.13.0"
                with self.assertRaisesRegex(DeploymentError, message):
                    self.recover()
                row = self.assert_checkpoint("publishing")
                self.assertNotIn("after", row)
                self.assertNotIn("libraries_after", row)
                self.assertEqual(self.verifier.call_count, 2)

    def test_failed_or_cancelled_publication_never_records_verified_runtime(self):
        for status in ("Failed", "Cancelled", "Canceled"):
            with self.subTest(status=status):
                self.reset_case()
                self.publish_states = ["Running", status]
                with self.assertRaisesRegex(DeploymentError, "publication failed"):
                    self.recover()
                row = self.assert_checkpoint("publishing")
                self.assertNotIn("after", row)
                self.assertNotIn("libraries_after", row)
                self.assertEqual(self.published, self.before)
                self.assertEqual(self.verifier.call_count, 1)
                self.time.sleep.assert_called_once_with(30)
                self.assertEqual(
                    len([c for c in self.client.request.call_args_list if c.args[0] == "POST"]), 1,
                )

    def test_deadline_retains_publication_checkpoint_and_does_not_claim_success_or_republish(self):
        self.publish_states = ["Running"]
        with self.assertRaisesRegex(DeploymentError, "exceeded its deadline"):
            self.recover()
        row = self.assert_checkpoint("publishing")
        self.assertNotIn("after", row)
        self.assertNotIn("libraries_after", row)
        self.assertEqual(self.now, 1900)
        self.assertEqual(self.time.sleep.call_args_list, [call(30)] * 30)
        self.assertEqual(self.verifier.call_count, 1)
        original = self.checkpoint.read_bytes()
        with self.assertRaisesRegex(DeploymentError, "Unpublished or active"):
            self.recover()
        self.assertEqual(self.checkpoint.read_bytes(), original)
        self.assertEqual(
            len([c for c in self.client.request.call_args_list if c.args[0] == "POST"]), 1,
        )

    def test_workspace_validation_failure_never_reads_or_changes_environment(self):
        self.client.workspace.side_effect = DeploymentError("Workspace not approved")
        with self.assertRaisesRegex(DeploymentError, "Workspace not approved"):
            self.recover()
        self.client.item.assert_not_called()
        self.client.list.assert_not_called()
        self.client.request.assert_not_called()
        self.libraries.assert_not_called()
        self.assertFalse(self.checkpoint.exists())


if __name__ == "__main__":
    unittest.main()
