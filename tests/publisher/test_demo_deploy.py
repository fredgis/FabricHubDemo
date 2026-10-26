"""Offline archive packaging boundary; no ARM submission or worker execution."""
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from scripts import demo_deploy
from services.publisher.access import POLICY


SQL_FILES = ("ddl.sql", "load.sql", "kpis.sql")


def config():
    guid = str(UUID(int=1))
    cfg = {
        **{key: guid for key in ("tenant_id", "subscription_id", "workspace_id", "capacity_id", "graph_id",
                                "managed_identity_principal_id", "managed_identity_application_id")},
        "environment": "test", "auth": "managed-identity", "run_id": "offline-bundle-test",
        "rti_ingestion": "eventhouse_onelake", "max_input_events": 100,
        "vm_resource_id": "/subscriptions/" + guid + "/resourceGroups/test/providers/Microsoft.Compute/virtualMachines/test",
        "items": {name: {"id": guid} for name in ("raw", "silver", "gold", "kql")},
        "notebooks": {"raw": guid, "silver": guid},
    }
    cfg["orchestration_authorization"] = {
        "mode": POLICY, "workspace_role": "Contributor",
        **{key: cfg[key] for key in ("tenant_id", "workspace_id", "vm_resource_id",
                                    "managed_identity_principal_id", "managed_identity_application_id")},
    }
    return cfg


class DemoBundleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="demo-bundle-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.runtime_files = {}
        for directory in ("services/publisher", "fabric", "sources/salesforce/bps"):
            for source in (demo_deploy.ROOT / directory).glob("*.py"):
                self.runtime_files[source.relative_to(demo_deploy.ROOT).as_posix()] = source.read_bytes()
        for name in ("services/publisher/msflix-demo-worker.service", "sources/__init__.py", "sources/salesforce/__init__.py"):
            source = demo_deploy.ROOT / name
            if source.is_file():
                self.runtime_files[name] = source.read_bytes()
        for name, data in self.runtime_files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (self.root / "fabric/gold").mkdir()
        for name in SQL_FILES:
            shutil.copyfile(demo_deploy.ROOT / "fabric/gold" / name, self.root / "fabric/gold" / name)

    def test_bundle_includes_only_explicit_required_sql_without_changing_runtime(self):
        for name in ("sap-ddl.sql", "sap-views.sql", "sap-live-views.preview.sql", "future-migration.sql"):
            (self.root / "fabric/gold" / name).write_text("-- must not ship\n", encoding="utf-8")
        with patch.object(demo_deploy, "ROOT", self.root), patch.object(demo_deploy, "Arm") as arm:
            cfg = config()
            content, digest = demo_deploy.bundle(cfg)
            arm.assert_not_called()
        self.assertEqual(digest, hashlib.sha256(content).hexdigest())
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual(len(archive.namelist()), len(set(archive.namelist())))
            self.assertEqual({name for name in archive.namelist() if name.endswith(".sql")},
                             {"fabric/gold/" + name for name in SQL_FILES})
            for name in SQL_FILES:
                self.assertEqual(archive.read("fabric/gold/" + name), (self.root / "fabric/gold" / name).read_bytes())
            for name in ("services/publisher/runtime.py", "services/publisher/worker.py",
                         "services/publisher/source_reload.py", "services/publisher/msflix-demo-worker.service"):
                self.assertEqual(archive.read(name), self.runtime_files[name])
            self.assertEqual(json.loads(archive.read("worker-config.json")), cfg)
            self.assertFalse(any(name.startswith("sources/sap/") for name in archive.namelist()))
        for name in SQL_FILES:
            with self.subTest(missing=name), patch.object(demo_deploy, "ROOT", self.root):
                path = self.root / "fabric/gold" / name
                data = path.read_bytes()
                path.unlink()
                try:
                    with self.assertRaises(FileNotFoundError):
                        demo_deploy.bundle(cfg)
                finally:
                    path.write_bytes(data)


if __name__ == "__main__":
    unittest.main()
