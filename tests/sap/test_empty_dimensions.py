import base64
import copy
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import nbformat

from sources.sap import empty_runtime as runtime
from sources.sap.empty_dimensions import definition


WS = "11111111-1111-1111-1111-111111111111"
MIRROR = "22222222-2222-2222-2222-222222222222"
SILVER = "33333333-3333-3333-3333-333333333333"


def uri(item):
    return f"https://onelake.dfs.fabric.microsoft.com/{WS}/{item}/Tables"


class EmptyDimensionTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {"workspace_id": WS, "source_system": "S4M", "mirror_id": MIRROR,
                    "mirror_path": uri(MIRROR), "mirror_schema": "dbo", "silver_id": SILVER,
                    "silver_path": uri(SILVER), "silver_schema": "dbo", "fields": runtime.FIELDS}
        self.spark = MagicMock()
        self.utils = MagicMock()
        self.utils.runtime.context = {"defaultLakehouseId": SILVER}
        self.utils.fs.exists.return_value = False
        self.delta = MagicMock()
        self.f = MagicMock()
        self.modules = {"delta": SimpleNamespace(DeltaTable=self.delta),
                        "pyspark": SimpleNamespace(), "pyspark.sql": SimpleNamespace(functions=self.f)}
        self.frames = {}
        for item in (MIRROR, SILVER):
            for name, spec in runtime.FIELDS.items():
                fields = runtime.field_names(spec)
                path = runtime.table_root(uri(item), WS, item, "dbo") + "/" + name
                frame = MagicMock()
                frame.columns = list(fields)
                frame.limit.return_value.count.return_value = 0
                frame.count.return_value = 0
                frame.dtypes = list(runtime.expected_dtypes(spec).items())
                frame.select.return_value = frame
                frame.withColumn.return_value = frame
                self.frames[path] = frame
        self.spark.read.format.return_value.load.side_effect = self.frames.__getitem__

    def materialize(self):
        with patch.dict(sys.modules, self.modules):
            return runtime.materialize(self.spark, self.utils, self.cfg)

    def target(self, name="I_PLANT"):
        return runtime.table_root(uri(SILVER), WS, SILVER, "dbo") + "/" + name

    def source(self, name="I_PLANT"):
        return runtime.table_root(uri(MIRROR), WS, MIRROR, "dbo") + "/" + name

    def test_exact_coordinate_required(self):
        self.assertTrue(runtime.table_root(uri(SILVER), WS, SILVER, "dbo").endswith("/Tables/dbo"))
        for value in (uri(SILVER).replace("https:", "http:"), uri(SILVER)+"?x=1",
                      uri(SILVER).replace("onelake", "evil"), uri(MIRROR)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                runtime.table_root(value, WS, SILVER, "dbo")
        with self.assertRaises(ValueError):
            runtime.table_root(uri(SILVER), WS, SILVER, "gold")

    def test_existing_empty_schema_is_unchanged(self):
        self.delta.isDeltaTable.return_value = True
        result = self.materialize()
        self.assertEqual(result["business_rows_written"], 0)
        self.assertFalse(result["gold_written"])
        self.assertEqual(set(result["tables"].values()), {"unchanged_empty"})
        for frame in self.frames.values():
            frame.write.format.assert_not_called()

    def test_source_rows_are_never_discarded_or_replaced(self):
        self.delta.isDeltaTable.return_value = True
        self.frames[self.source()].limit.return_value.count.return_value = 1
        with self.assertRaisesRegex(ValueError, "source is not empty"):
            self.materialize()
        self.frames[self.source()].write.format.assert_not_called()

    def test_existing_silver_rows_are_never_overwritten(self):
        self.delta.isDeltaTable.return_value = True
        self.frames[self.target()].limit.return_value.count.return_value = 1
        with self.assertRaisesRegex(ValueError, "existing Silver contains rows"):
            self.materialize()
        self.frames[self.target()].write.format.assert_not_called()

    def test_existing_wrong_schema_is_refused(self):
        self.delta.isDeltaTable.return_value = True
        self.frames[self.target()].dtypes.append(("foreign_column", "string"))
        with self.assertRaisesRegex(ValueError, "schema differs"):
            self.materialize()

    def test_missing_schema_created_without_business_rows_or_overwrite_mode(self):
        created = set()
        for name in runtime.FIELDS:
            self.frames[self.source(name)].write.format.return_value.mode.return_value.save.side_effect = created.add
        self.delta.isDeltaTable.side_effect = lambda spark, path: path in created or path.startswith(
            runtime.table_root(uri(MIRROR), WS, MIRROR, "dbo")+"/")
        result = self.materialize()
        self.assertEqual(set(result["tables"].values()), {"created_empty"})
        self.assertEqual(len(created), len(runtime.FIELDS))
        for name in runtime.FIELDS:
            frame = self.frames[self.source(name)]
            frame.write.format.return_value.mode.assert_called_once_with("errorifexists")
            frame.write.format.return_value.mode.return_value.save.assert_called_once_with(self.target(name))

    def test_non_delta_target_path_is_not_replaced(self):
        source_paths = {self.source(name) for name in runtime.FIELDS}
        self.delta.isDeltaTable.side_effect = lambda spark, path: path in source_paths
        self.utils.fs.exists.return_value = True
        with self.assertRaisesRegex(ValueError, "non-Delta target exists"):
            self.materialize()

    def test_wrong_binding_and_additional_dimensions_are_refused(self):
        self.utils.runtime.context = {"defaultLakehouseId": MIRROR}
        with self.assertRaisesRegex(ValueError, "dedicated native SAP Silver"):
            self.materialize()
        self.cfg = copy.deepcopy(self.cfg)
        self.cfg["fields"]["UNRELATED"] = ["ID"]
        with self.assertRaisesRegex(ValueError, "twelve admitted"):
            self.materialize()

    def test_definition_valid_and_bound_to_discovered_silver_and_sap_environment(self):
        target = {"workspace_id": WS, "source_system": "S4M"}
        def item(id, name):
            return {"id": id, "displayName": name, "properties": {"oneLakeTablesPath": uri(id), "defaultSchema": "dbo"}}
        body = definition(target, item(MIRROR, "mirror"), item(SILVER, "silver"), {"id": MIRROR})
        doc = json.loads(base64.b64decode(body["parts"][0]["payload"]))
        nbformat.validate(nbformat.from_dict(doc))
        self.assertEqual(doc["metadata"]["dependencies"]["lakehouse"]["default_lakehouse"], SILVER)
        self.assertEqual(doc["metadata"]["dependencies"]["environment"]["workspaceId"], WS)
        for cell in doc["cells"]:
            self.assertTrue(all(line.endswith("\n") for line in cell["source"]))


if __name__ == "__main__":
    unittest.main()
