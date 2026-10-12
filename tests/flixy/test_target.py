import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from fabric.rest import DeploymentError
from scripts import configure_flixy, prepare_flixy


class FlixyTargetTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "target.json"
        target_path = patch.object(prepare_flixy, "TARGET_PATH", self.path)
        target_path.start()
        self.addCleanup(target_path.stop)
        self.target = {
            key: str(UUID(int=400 + index)) for index, key in enumerate((
                "tenant_id", "workspace_id", "capacity_id", "warehouse_id", "ontology_id", "graph_id",
            ))
        }

    def save(self, value):
        self.path.write_text(json.dumps(value), encoding="utf-8")

    def test_explicit_private_target_is_preserved(self):
        self.save(self.target)
        self.assertEqual(prepare_flixy.load_target(include_graph=True), self.target)
        self.assertEqual(configure_flixy.item_reference(self.target["graph_id"], self.target["workspace_id"]), {
            "type": "FabricItem", "itemReference": {
                "referenceType": "ById", "itemId": self.target["graph_id"],
                "workspaceId": self.target["workspace_id"],
            },
        })

    def test_missing_target_stops_both_tools_before_client_creation(self):
        for module in (prepare_flixy, configure_flixy):
            with self.subTest(module=module.__name__), patch.object(module, "FabricClient") as client:
                with self.assertRaisesRegex(DeploymentError, "private"):
                    module.main()
                client.assert_not_called()

    def test_empty_invalid_and_nil_ids_are_rejected(self):
        for key in self.target:
            for value in ("", "not-a-uuid", str(UUID(int=0)), None, 123):
                with self.subTest(key=key, value=value):
                    self.save({**self.target, key: value})
                    with self.assertRaisesRegex(DeploymentError, key):
                        prepare_flixy.load_target(include_graph=True)

    def test_invalid_json_and_non_objects_are_rejected(self):
        for value in ("{", "[]", "null"):
            with self.subTest(value=value):
                self.path.write_text(value, encoding="utf-8")
                with self.assertRaises(DeploymentError):
                    prepare_flixy.load_target()

    def test_independent_expected_capacity_is_still_enforced(self):
        self.save(self.target)
        for module in (prepare_flixy, configure_flixy):
            with self.subTest(module=module.__name__), patch.object(module, "FabricClient") as factory:
                factory.return_value.request.return_value = (200, {}, {
                    "displayName": "MSFlix", "capacityId": str(UUID(int=999)),
                })
                with self.assertRaisesRegex(DeploymentError, "capacity"):
                    module.main()
                factory.assert_called_once_with(self.target["tenant_id"])
                factory.return_value.request.assert_called_once()
                factory.return_value.operation.assert_not_called()


if __name__ == "__main__":
    unittest.main()
