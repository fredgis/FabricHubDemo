"""Offline, tiny synthetic append-package protocol tests (never real orders)."""
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import importlib
import json
import os
import tempfile

import pyarrow.parquet as pq
import unittest
from dataclasses import replace
from datetime import timedelta

from sources.sap import native
from sources.sap.datasphere import digest, json_bytes
from sources.sap.schema import Object

STAMP = datetime(2026, 11, 30, 23, 59, tzinfo=timezone.utc)
NEXT = datetime(2026, 12, 1, tzinfo=timezone.utc)
NAME = "I_TEST_FINANCE"
BRIDGE = "ZMSF_ORDER_LINK"


def baseline(scratch):
    fields = (
        native.NativeField("ID", "NUMC", 3, key=True),
        native.NativeField("VALUE", "DEC", 10, 2),
        native.NativeField("DAY", "DATS", 8),
    )
    schemas = {NAME: Object(NAME, fields, financial=True),
               "DD03ND": native.load_contract().schemas["DD03ND"]}
    rows = {NAME: [{"ID": "001", "VALUE": Decimal("2.50"), "DAY": date(2026, 11, 1)}],
            "DD03ND": native.dd03nd_rows(schemas)}
    root = scratch / "baseline"
    root.mkdir()
    entries = {}
    for name, obj in schemas.items():
        folder = root / "datasphere" / "S4M" / name
        for part in (folder, folder / "initial", folder / "delta"):
            part.mkdir(parents=True, exist_ok=True)
            (part / ".sap.partfile.metadata").write_bytes(native.metadata(obj, "S4M"))
        file = folder / "initial" / ("part-" + "a" * 33 + ".parquet")
        pq.write_table(native.as_table(obj, [("L", r) for r in rows[name]], STAMP), file, compression="snappy")
        (folder / "initial" / "_SUCCESS").write_bytes(b"")
        entries[name] = {"file": file.relative_to(root).as_posix(), "loads": len(rows[name]), "upserts": 0, "deletes": 0}
    from dataclasses import asdict
    payloads = {
        "contract.json": {"version": native.SCHEMA_VERSION, "objects": {
            n: {"fields": [asdict(f) for f in o.fields], "keys": list(o.keys),
                "financial_deletes_allowed": not o.financial} for n, o in schemas.items()}},
        "batches.json": [{"timestamp": STAMP, "objects": entries}],
        "final-snapshot.json": rows,
    }
    for file, value in payloads.items():
        (root / file).write_bytes(json_bytes(value))
    manifest = {"format_version": 1, "schema_version": native.SCHEMA_VERSION,
                "source_system": "S4M", "synthetic": True, "compatibility_scope": "LOCAL_ASSERTED_ONLY",
                "object_count": len(schemas), "batch_count": 1, "initial_as_of": STAMP, "final_as_of": STAMP,
                "files": {p.relative_to(root).as_posix(): digest(p.read_bytes()) for p in root.rglob("*") if p.is_file()}}
    (root / "manifest.json").write_bytes(json_bytes(manifest))
    return root, schemas, rows


def api():
    assert importlib.util.find_spec("sources.sap.native_delta") is not None, "append module is missing"
    return importlib.import_module("sources.sap.native_delta")


def added():
    return {"ID": "002", "VALUE": Decimal("3.75"), "DAY": date(2026, 11, 2)}


class NativeDeltaTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="native-delta-test-", dir=os.environ["TMPDIR"])
        self.addCleanup(temp.cleanup)
        self.scratch = Path(temp.name)
        self.root, self.schemas, self.rows = baseline(self.scratch)

    def rehash(self):
        manifest = json.loads((self.root / "manifest.json").read_bytes())
        manifest["files"] = {p.relative_to(self.root).as_posix(): digest(p.read_bytes())
                             for p in self.root.rglob("*") if p.is_file() and p.name != "manifest.json"}
        (self.root / "manifest.json").write_bytes(json_bytes(manifest))

    def test_replay_rejects_rehashed_inconsistent_evidence(self):
        path = self.root / "final-snapshot.json"
        snapshot = json.loads(path.read_bytes())
        snapshot[NAME][0]["VALUE"] = "999.00"
        path.write_bytes(json_bytes(snapshot))
        self.rehash()
        with self.assertRaisesRegex(ValueError, "snapshot"):
            api().load_baseline(self.root)

    def test_baseline_rejects_invalid_protocol(self):
        original = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        for case in ("operation", "sequence", "timestamp", "counts", "keys", "metadata", "missing_marker", "unlisted", "unsafe_path"):
            with self.subTest(case=case):
                for p in self.root.rglob("*"):
                    if p.is_file():
                        p.unlink()
                for p, data in original.items():
                    (self.root / p).write_bytes(data)
                batches = json.loads((self.root / "batches.json").read_bytes())
                entry = batches[0]["objects"][NAME]
                if case in {"operation", "sequence", "timestamp"}:
                    import pyarrow as pa
                    file = self.root / entry["file"]
                    table = pq.read_table(file)
                    rows = table.to_pylist()
                    column, value = {"operation": ("__operation_type", "BAD"),
                                     "sequence": ("__sequence_number", Decimal(1)),
                                     "timestamp": ("__timestamp", NEXT)}[case]
                    rows[0][column] = value
                    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), file)
                elif case == "counts":
                    entry["loads"] = 999
                    (self.root / "batches.json").write_bytes(json_bytes(batches))
                elif case == "keys":
                    path = self.root / "contract.json"
                    contract = json.loads(path.read_bytes())
                    contract["objects"][NAME]["keys"] = ["VALUE"]
                    path.write_bytes(json_bytes(contract))
                elif case == "metadata":
                    (self.root / f"datasphere/S4M/{NAME}/.sap.partfile.metadata").write_bytes(b"{}")
                elif case == "missing_marker":
                    (self.root / f"datasphere/S4M/{NAME}/initial/_SUCCESS").unlink()
                elif case == "unlisted":
                    (self.root / "extra").write_bytes(b"unlisted")
                if case != "unlisted":
                    self.rehash()
                if case == "unsafe_path":
                    path = self.root / "manifest.json"
                    manifest = json.loads(path.read_bytes())
                    manifest["files"]["../outside"] = digest(b"outside")
                    (self.scratch / "outside").write_bytes(b"outside")
                    path.write_bytes(json_bytes(manifest))
                with self.assertRaises(ValueError):
                    api().load_baseline(self.root)

    def test_existing_append_is_delta_only_deterministic_and_replayable(self):
        module = api()
        self.assertTrue(hasattr(module, "write_package"), "append writer is missing")
        additions = {NAME: [self.rows[NAME][0], added()]}
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        output = self.scratch / "append"
        manifest = module.write_package(self.root, self.schemas, additions, NEXT, "tiny-fixture", output)
        self.assertEqual(manifest["format_version"], "sap-native-append-v1")
        self.assertEqual(manifest["source_system"], "S4M")
        self.assertEqual(manifest["predecessor_manifest_sha256"], digest((self.root / "manifest.json").read_bytes()))
        self.assertEqual(len(manifest["ordered_files"]), 1)
        path = manifest["ordered_files"][0]
        self.assertTrue(path.startswith(f"datasphere/S4M/{NAME}/delta/part-"))
        actual = pq.read_table(output / path).to_pylist()
        self.assertEqual([r["__operation_type"] for r in actual], ["U"])
        self.assertEqual(actual[0]["ID"], "002")
        self.assertEqual(actual[0]["__timestamp"], NEXT)
        self.assertIsNone(actual[0]["__sequence_number"])
        self.assertEqual(actual[0]["VALUE"], added()["VALUE"])
        final = json.loads((output / "final-snapshot.json").read_bytes())
        self.assertEqual([r["ID"] for r in final[NAME]], ["001", "002"])
        self.assertEqual(module.write_package(self.root, self.schemas, additions, NEXT, "tiny-fixture", output), manifest)
        self.assertEqual(module.write_package(self.root, self.schemas, {NAME: list(reversed(additions[NAME]))}, NEXT, "tiny-fixture", self.scratch / "another"), manifest)
        self.assertEqual({p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}, before)
        self.assertFalse(list(self.scratch.glob(".append-pending-*")))

    def test_append_rejects_mutations_schema_changes_and_watermarks_before_output(self):
        cases = [
            (self.schemas, {NAME: [{**self.rows[NAME][0], "VALUE": Decimal("9.00")}]}, NEXT),
            ({**self.schemas, NAME: replace(self.schemas[NAME], financial=False)}, {}, NEXT),
            ({"DD03ND": self.schemas["DD03ND"]}, {}, NEXT),
            (self.schemas, {NAME: [{"ID": "001", "__operation_type": "X"}]}, NEXT),
            (self.schemas, {NAME: [added(), added()]}, NEXT),
            (self.schemas, {"UNKNOWN": []}, NEXT),
            (self.schemas, {}, STAMP), (self.schemas, {}, STAMP - timedelta(days=1)),
            (self.schemas, {}, NEXT.replace(tzinfo=None)),
        ]
        for schemas, rows, stamp in cases:
            with self.subTest(rows=rows, stamp=stamp):
                output = self.scratch / "must-not-exist" / "append"
                with self.assertRaises(ValueError):
                    api().write_package(self.root, schemas, rows, stamp, "guard", output)
                self.assertFalse(output.parent.exists())

    def test_noop_collision_and_atomic_failure(self):
        from unittest.mock import patch
        output = self.scratch / "noop"
        manifest = api().write_package(self.root, self.schemas, {NAME: self.rows[NAME]}, NEXT, "noop", output)
        self.assertEqual(manifest["ordered_files"], [])
        with self.assertRaises(FileExistsError):
            api().write_package(self.root, self.schemas, {NAME: [added()]}, NEXT, "changed", output)
        with patch.object(api().pq, "write_table", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                api().write_package(self.root, self.schemas, {NAME: [added()]}, NEXT, "fail", self.scratch / "fail")
        self.assertFalse((self.scratch / "fail").exists())
        self.assertFalse(list(self.scratch.glob(".append-pending-*")))

    def test_output_cannot_overlap_baseline(self):
        for output in (self.root, self.root / "nested", self.scratch):
            with self.subTest(output=output), self.assertRaises(ValueError):
                api().write_package(self.root, self.schemas, {}, NEXT, "overlap", output)

    def test_snapshot_decimal_representation_is_compared_as_typed_value(self):
        path = self.root / "final-snapshot.json"
        snapshot = json.loads(path.read_bytes())
        snapshot[NAME][0]["VALUE"] = "2.5"
        path.write_bytes(json_bytes(snapshot))
        self.rehash()
        self.assertEqual(api().load_baseline(self.root).tables[NAME], self.rows[NAME])

    def test_allowlisted_bridge_bootstrap_and_dd03nd_delta(self):
        bridge = Object(BRIDGE, (native.NativeField("ORDER_ID", "CHAR", 128, key=True),
                                 native.NativeField("LINE_NUMBER", "INT4", 10, key=True),
                                 native.NativeField("BILLINGDOCUMENT", "CHAR", 10)), financial=True)
        row = {"ORDER_ID": "literal-order-01", "LINE_NUMBER": 1, "BILLINGDOCUMENT": "900001"}
        schemas = {**self.schemas, BRIDGE: bridge}
        output = self.scratch / "bridge"
        manifest = api().write_package(self.root, schemas, {BRIDGE: [row]}, NEXT, "bridge", output)
        self.assertEqual(api().verify_package(output, self.root).tables[BRIDGE], [row])
        files = manifest["ordered_files"]
        bridge_files = [p for p in files if f"/{BRIDGE}/" in p]
        self.assertEqual(len(bridge_files), 5)
        initial = next(p for p in bridge_files if p.endswith(".parquet"))
        self.assertEqual(pq.read_table(output / initial).to_pylist()[0]["__operation_type"], "L")
        marker = f"datasphere/S4M/{BRIDGE}/initial/_SUCCESS"
        self.assertGreater(files.index(marker), files.index(initial))
        dd = next(p for p in files if "/DD03ND/delta/" in p)
        rows = pq.read_table(output / dd).to_pylist()
        self.assertEqual({r["STRUCOBJN"] for r in rows}, {BRIDGE})
        self.assertEqual({r["__operation_type"] for r in rows}, {"U"})
        self.assertEqual(len(rows), len(bridge.fields))
        self.assertIn(BRIDGE, manifest["requires_bps_ui_registration"])
        contract = json.loads((output / "contract.json").read_bytes())
        self.assertEqual(contract["objects"][BRIDGE]["keys"], list(bridge.keys))
        for file in bridge_files:
            if file.endswith(".metadata"):
                self.assertEqual((output / file).read_bytes(), native.metadata(bridge, "S4M"))
        for bad_name in ("ZMSF_OTHER", "../ZMSF_ORDER_LINK"):
            with self.assertRaises(ValueError):
                api().write_package(self.root, {**self.schemas, bad_name: replace(bridge, name=bad_name)}, {}, NEXT, "bad", self.scratch / "bad")

    def test_package_verification_binds_manifest_order_and_predecessor(self):
        output = self.scratch / "verified"
        manifest = api().write_package(self.root, self.schemas, {NAME: [added()]}, NEXT, "verify", output)
        self.assertTrue(hasattr(api(), "verify_package"), "offline append verifier missing")
        verified = api().verify_package(output, self.root)
        self.assertEqual(verified.tables[NAME], [self.rows[NAME][0], added()])
        self.assertEqual(verified.manifest_sha256, digest((output / "manifest.json").read_bytes()))
        manifest["ordered_files"] = []
        (output / "manifest.json").write_bytes(json_bytes(manifest))
        with self.assertRaises(ValueError):
            api().verify_package(output, self.root)

    def test_dd03nd_only_describes_declared_fields(self):
        forged = {"STRUCOBJN": NAME, "FIELDNAME": "FORGED", "DATATYPE": "CHAR", "LENG": "000010", "DECIMALS": "000000"}
        with self.assertRaises(ValueError):
            api().write_package(self.root, self.schemas, {"DD03ND": [forged]}, NEXT, "forged", self.scratch / "forged")

    def test_decimal_scale_is_canonical_for_verifiable_paths(self):
        output = self.scratch / "scale"
        row = {**added(), "VALUE": Decimal("3.750")}
        manifest = api().write_package(self.root, self.schemas, {NAME: [row]}, NEXT, "scale", output)
        self.assertEqual(api().verify_package(output, self.root).manifest, manifest)
        other = api().write_package(self.root, self.schemas, {NAME: [added()]}, NEXT, "scale", self.scratch / "scale2")
        self.assertEqual(manifest, other)

    def test_schema_key_mutation_and_invalid_batch_id(self):
        obj = self.schemas[NAME]
        changed = replace(obj, fields=tuple(replace(f, key=(f.name == "VALUE")) for f in obj.fields))
        with self.assertRaises(ValueError):
            api().write_package(self.root, {**self.schemas, NAME: changed}, {}, NEXT, "key", self.scratch / "key")
        with self.assertRaises(ValueError):
            api().write_package(self.root, self.schemas, {}, NEXT, "../escape", self.scratch / "key")

    def test_output_dotdot_alias_cannot_enter_baseline(self):
        (self.scratch / "alias").mkdir()
        alias = self.scratch / "alias" / ".." / "baseline" / "nested"
        with self.assertRaises(ValueError):
            api().write_package(self.root, self.schemas, {}, NEXT, "alias", alias)

    def test_baseline_hash_and_typed_replay(self):
        result = api().load_baseline(self.root, expected_manifest_sha256=digest((self.root / "manifest.json").read_bytes()))
        self.assertEqual({n: self.schemas[n].index(r) for n, r in result.tables.items()},
                         {n: self.schemas[n].index(r) for n, r in self.rows.items()})
        self.assertEqual(result.schemas, self.schemas)
        self.assertEqual(result.watermark, STAMP)
        with self.assertRaisesRegex(ValueError, "manifest.*hash"):
            api().load_baseline(self.root, expected_manifest_sha256="0" * 64)
        (self.root / "final-snapshot.json").write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "hash"):
            api().load_baseline(self.root)

