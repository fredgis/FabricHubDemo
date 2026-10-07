import unittest

from fabric.rest import DeploymentError
from sources.salesforce.bps.runtime import libraries, verify_runtime_only


class RuntimeRecoveryTests(unittest.TestCase):
    def test_only_runtime_can_change(self):
        before = {"runtimeVersion": "2.0", "driverCores": 8, "sparkProperties": []}
        after = {**before, "runtimeVersion": "1.3"}
        wheel = [{"name": "native_bps.whl", "libraryType": "Custom"}]
        verify_runtime_only(before, after, wheel, wheel)

    def test_compute_change_rejected(self):
        with self.assertRaises(DeploymentError):
            verify_runtime_only(
                {"runtimeVersion": "2.0", "driverCores": 8},
                {"runtimeVersion": "1.3", "driverCores": 4}, [], [],
            )

    def test_library_change_rejected(self):
        with self.assertRaises(DeploymentError):
            verify_runtime_only(
                {"runtimeVersion": "2.0"}, {"runtimeVersion": "1.3"},
                [{"name": "native_bps.whl"}], [],
            )

    def test_every_library_pagination_call_is_attributed(self):
        class Client:
            def __init__(self):
                self.calls = []

            def request(self, method, path, skill=None):
                self.calls.append((method, path, skill))
                if len(self.calls) == 1:
                    return 200, {}, {"libraries": [{"name": "one"}], "continuationToken": "a+b"}
                return 200, {}, {"libraries": [{"name": "two"}], "continuationUri": "null"}

        client = Client()
        self.assertEqual(2, len(libraries(client, "/v1/workspaces/ws/environments/env", True)))
        self.assertIn("continuationToken=a%2Bb", client.calls[1][1])
        self.assertTrue(all(call[2] == "spark-cli" for call in client.calls))


if __name__ == "__main__":
    unittest.main()
