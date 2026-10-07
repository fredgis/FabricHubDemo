import unittest
from fabric.spark_runtime import eventhouse_delta_path, onelake_host


class OneLakePathTests(unittest.TestCase):
    def test_https_endpoint_is_not_embedded_in_abfs_authority(self):
        self.assertEqual(
            onelake_host("https://southeastasia-onelake.dfs.fabric.microsoft.com"),
            "southeastasia-onelake.dfs.fabric.microsoft.com",
        )

    def test_host_only_endpoint_is_supported(self):
        self.assertEqual(onelake_host("onelake.dfs.fabric.microsoft.com"), "onelake.dfs.fabric.microsoft.com")

    def test_untrusted_endpoint_is_not_silently_used(self):
        with self.assertRaises(ValueError):
            onelake_host("http://unexpected.example.invalid")

    def test_eventhouse_delta_uses_actual_item_and_workspace_order(self):
        workspace = "00000000-0000-0000-0000-000000000004"
        item = "00000000-0000-0000-0000-000000000005"
        self.assertEqual(
            eventhouse_delta_path(workspace, item, "https://onelake.dfs.fabric.microsoft.com"),
            f"abfss://{workspace}@onelake.dfs.fabric.microsoft.com/{item}/Tables/RawEvents")

    def test_eventhouse_delta_rejects_unresolved_names_and_external_hosts(self):
        with self.assertRaises(ValueError):
            eventhouse_delta_path("MSFlix", "MSFlixEvents", "onelake.dfs.fabric.microsoft.com")
        with self.assertRaises(ValueError):
            eventhouse_delta_path("00000000-0000-0000-0000-000000000004",
                "00000000-0000-0000-0000-000000000005", "https://unexpected.example.invalid")


if __name__ == "__main__":
    unittest.main()
