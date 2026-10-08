import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from sources.sap.config import DEFAULT_CONFIG, DEFAULT_REFERENCES, read_json
from sources.sap.datasphere import as_table, changes, digest, json_bytes, metadata, write_package
from sources.sap.scenario import build
from sources.sap.schema import SCHEMAS, dd03nd_rows


class DatasphereTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenario = build(read_json(DEFAULT_CONFIG), read_json(DEFAULT_REFERENCES))

    def test_dd03nd_exactly_covers_every_exported_business_field(self):
        entries = {(r["STRUCOBJN"], r["FIELDNAME"]): r for r in dd03nd_rows()}
        self.assertEqual(len(entries), sum(len(obj.fields) for obj in SCHEMAS.values()))
        for name, obj in SCHEMAS.items():
            for f in obj.fields:
                row = entries[name, f.name]
                self.assertEqual((row["DATATYPE"], int(row["LENG"]), int(row["DECIMALS"])), (f.ddic, f.length, f.scale))

    def test_metadata_keys_dates_decimals_and_deterministic_task_id(self):
        obj = SCHEMAS["I_OPERATIONALACCTGDOCITEM"]
        data = json.loads(metadata(obj, "S4M"))
        fields = {r["name"]: r for r in data["columns"]}
        self.assertEqual({k for k, r in fields.items() if r.get("primaryKey")}, set(obj.keys))
        self.assertEqual(fields["POSTINGDATE"]["dataType"], "DATE")
        self.assertEqual(fields["AMOUNTINTRANSACTIONCURRENCY"]["precision"], 23)
        self.assertEqual(fields["AMOUNTINTRANSACTIONCURRENCY"]["scale"], 2)
        props = {r["name"]: r["value"] for r in data["properties"]}
        self.assertEqual(props["loadType"], "REPLICATE")
        self.assertEqual(props["groupDeltaFilesBy"], "NONE")
        self.assertEqual(metadata(obj, "S4M"), metadata(obj, "S4M"))
        self.assertNotEqual(metadata(obj, "S4M"), metadata(obj, "S4X"))

    def test_parquet_types_are_lossless(self):
        snapshot = self.scenario.snapshots[0]
        obj = SCHEMAS["I_OPERATIONALACCTGDOCITEM"]
        rows = snapshot.tables[obj.name]
        table = as_table(obj, [("L", r) for r in rows], snapshot.timestamp)
        self.assertEqual(table.schema.field("AMOUNTINTRANSACTIONCURRENCY").type, pa.decimal128(23, 2))
        self.assertEqual(table.schema.field("POSTINGDATE").type, pa.date32())
        self.assertEqual(table.schema.field("__timestamp").type, pa.timestamp("us", tz="UTC"))
        self.assertTrue(all(r["__sequence_number"] is None for r in table.to_pylist()))
        self.assertEqual(table.to_pylist()[0]["CUSTOMER"], "0010000001")
        self.assertEqual(table.to_pylist()[0]["AMOUNTINTRANSACTIONCURRENCY"], Decimal("12.00"))

    def test_financial_deletes_fail_and_nonfinancial_delete_is_key_only(self):
        obj = SCHEMAS["I_OPERATIONALACCTGDOCITEM"]
        row = self.scenario.snapshots[0].tables[obj.name][0]
        with self.assertRaisesRegex(ValueError, "financial deletes"):
            changes(obj, [row], [])
        with self.assertRaises(ValueError):
            as_table(obj, [("X", {key: row[key] for key in obj.keys})], self.scenario.snapshots[0].timestamp)
        product = SCHEMAS["I_PRODUCT"]
        before = [{"PRODUCT": "DISPOSABLE", "PRODUCTTYPE": "SERV"}]
        ops = changes(product, before, [])
        self.assertEqual(ops, [("X", {"PRODUCT": "DISPOSABLE"})])
        table = as_table(product, ops, self.scenario.snapshots[0].timestamp)
        self.assertEqual(table.to_pylist()[0]["__operation_type"], "X")
        self.assertIsNone(table.to_pylist()[0]["PRODUCTTYPE"])

    def test_unknown_columns_duplicate_keys_and_timezone_fail(self):
        obj = SCHEMAS["I_PRODUCT"]
        row = {"PRODUCT": "DEMO", "PRODUCTTYPE": "SERV"}
        stamp = datetime(2026, 11, 1, tzinfo=timezone.utc)
        for rows in ([{**row, "UNKNOWN": "x"}], [row, row], [{**row, "PRODUCT": "X" * 41}]):
            with self.assertRaises(ValueError):
                as_table(obj, [("L", r) for r in rows], stamp)
        with self.assertRaisesRegex(ValueError, "UTC"):
            as_table(obj, [("L", row)], stamp.replace(tzinfo=None))

    def test_every_batch_replays_to_its_snapshot_and_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = write_package(root, self.scenario)
            batches = json.loads((root / "batches.json").read_text())
            state = {name: {} for name in SCHEMAS}
            for batch, expected in zip(batches, self.scenario.snapshots, strict=True):
                for name, entry in batch["objects"].items():
                    table = pq.read_table(root / entry["file"])
                    for _ in range(2):
                        for row in table.to_pylist():
                            op = row.pop("__operation_type")
                            self.assertIsNone(row.pop("__sequence_number"))
                            row.pop("__timestamp")
                            key = tuple(row[f] for f in SCHEMAS[name].keys)
                            if op == "X":
                                state[name].pop(key, None)
                            else:
                                state[name][key] = row
                for name in SCHEMAS:
                    self.assertEqual(state[name], SCHEMAS[name].index(expected.tables[name]), (batch["label"], name))
            self.assertEqual(len(batches), 6)
            self.assertFalse(manifest["native_bps_ready"])
            for filename, checksum in manifest["files"].items():
                self.assertEqual(digest((root / filename).read_bytes()), checksum)
            for name in SCHEMAS:
                initial = root / "datasphere" / "S4M" / name / "initial"
                self.assertEqual((initial / "_SUCCESS").read_bytes(), b"")
                self.assertTrue((initial / ".sap.partfile.metadata").is_file())

    def test_collection_updates_old_clearing_rows_not_only_new_payments(self):
        before, after = self.scenario.snapshots[:2]
        obj = SCHEMAS["I_OPERATIONALACCTGDOCITEM"]
        ops = changes(obj, before.tables[obj.name], after.tables[obj.name])
        self.assertEqual(len(ops), 3)
        self.assertTrue(all(op == "U" for op, _ in ops))
        old_keys = obj.index(before.tables[obj.name])
        updates = [r for _, r in ops if tuple(r[k] for k in obj.keys) in old_keys]
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["CLEARINGDATE"], date(2026, 11, 2))

    def test_complete_packages_are_byte_reproducible(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            manifest_a = write_package(Path(a), self.scenario)
            manifest_b = write_package(Path(b), build(read_json(DEFAULT_CONFIG), read_json(DEFAULT_REFERENCES)))
            self.assertEqual(manifest_a, manifest_b)
            self.assertEqual((Path(a) / "manifest.json").read_bytes(), (Path(b) / "manifest.json").read_bytes())

    def test_json_keeps_decimal_values_as_strings(self):
        data = json.loads(json_bytes({"money": Decimal("13.60")}))
        self.assertEqual(data["money"], "13.60")


if __name__ == "__main__":
    unittest.main()
