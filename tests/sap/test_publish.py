import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fabric.rest import DeploymentError
from sources.sap.config import DEFAULT_CONFIG, DEFAULT_REFERENCES, read_json
from sources.sap.datasphere import json_bytes
from sources.sap.fabric_client import OneLakeFiles, ScopedClient
from sources.sap.native import build, write_package
from sources.sap.publish import publication_files


class PublisherTests(unittest.TestCase):
    def test_interrupted_atomic_write_does_not_leave_a_blocking_final_file(self):
        store = object.__new__(OneLakeFiles)
        store.base = "https://onelake.dfs.fabric.microsoft.com/workspace/lakehouse/Files"
        store.directories = set()
        files = {}
        failed = [False]

        def request(method, path, query="", data=None, headers=None, *, blob=False):
            if method == "GET":
                return (200, {}, files[path]) if path in files else (404, {}, b"")
            if method == "HEAD":
                return 200, {"x-ms-resource-type": "directory"}, b""
            if method == "DELETE":
                files.pop(path, None)
                return 200, {}, b""
            if method == "PUT":
                self.assertTrue(blob)
                self.assertEqual(headers["If-None-Match"], "*")
                self.assertEqual(headers["x-ms-blob-type"], "BlockBlob")
                if not failed[0]:
                    failed[0] = True
                    raise DeploymentError("Interrupted atomic write")
                files[path] = data
                return 201, {}, b""
            return 200, {}, b""

        with patch.object(store, "request", side_effect=request):
            with self.assertRaisesRegex(DeploymentError, "Interrupted"):
                store.put("datasphere/S4M/object/initial/part-file.parquet", b"source")
            self.assertFalse(files)
            self.assertEqual(store.put("datasphere/S4M/object/initial/part-file.parquet", b"source"), "created")
            self.assertEqual(list(files.values()), [b"source"])

    def test_complete_package_orders_markers_after_initial_and_deltas_last(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_package(root, build(read_json(DEFAULT_CONFIG), read_json(DEFAULT_REFERENCES)))
            files = publication_files(root, "S4M")
            self.assertEqual(len(files), len(set(files)))
            first_marker = min(i for i, f in enumerate(files) if f.endswith("/_SUCCESS"))
            last_initial = max(i for i, f in enumerate(files) if "/initial/part-" in f)
            first_delta = min(i for i, f in enumerate(files) if "/delta/part-" in f)
            last_marker = max(i for i, f in enumerate(files) if f.endswith("/_SUCCESS"))
            self.assertGreater(first_marker, last_initial)
            self.assertGreater(first_delta, last_marker)
            path = root / files[0]
            path.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "modified"):
                publication_files(root, "S4M")

    def test_manifest_path_cannot_escape_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = {
                "synthetic": True, "source_system": "S4M", "compatibility_scope": "LOCAL_ASSERTED_ONLY",
                "files": {"../credentials": "fake"},
            }
            (root / "manifest.json").write_bytes(json_bytes(manifest))
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                publication_files(root, "S4M")

    def test_identical_source_file_is_not_overwritten(self):
        store = object.__new__(OneLakeFiles)
        with patch.object(store, "request", return_value=(200, {}, b"same")) as request:
            self.assertEqual(store.put("datasphere/S4M/object/file", b"same"), "unchanged")
            self.assertEqual(request.call_count, 1)
        with patch.object(store, "request", return_value=(200, {}, b"user edits")):
            with self.assertRaisesRegex(DeploymentError, "replacement is prohibited"):
                store.put("datasphere/S4M/object/file", b"same")

    def test_only_directory_existence_is_reused(self):
        store = object.__new__(OneLakeFiles)
        store.directories = set()
        with patch.object(store, "request", return_value=(200, {"x-ms-resource-type": "file"}, b"")):
            with self.assertRaisesRegex(DeploymentError, "directory"):
                store.directory("datasphere/S4M")

    def test_auth_checks_principal_tenant_and_audience(self):
        def token(claims):
            import base64
            encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
            return "header." + encoded + ".signature"

        target = {"tenant_id": "tenant", "subscription_id": "subscription", "operator_id": "operator"}
        for claims in (
            {"tid": "wrong", "oid": "operator", "aud": "https://storage.azure.com/", "exp": 9999999999},
            {"tid": "tenant", "oid": "wrong", "aud": "https://storage.azure.com/", "exp": 9999999999},
            {"tid": "tenant", "oid": "operator", "aud": "https://other.invalid", "exp": 9999999999},
        ):
            with patch("sources.sap.fabric_client.az_json", return_value={"accessToken": token(claims)}):
                with self.assertRaises(DeploymentError):
                    ScopedClient(target).token("https://storage.azure.com/")


if __name__ == "__main__":
    unittest.main()
