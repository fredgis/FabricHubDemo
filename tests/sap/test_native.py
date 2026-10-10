import copy
import json
import re
import shutil
import unittest
import uuid
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal as D
from unittest.mock import patch

import jsonschema
import pyarrow as pa
import pyarrow.parquet as pq

from sources.sap import native
from sources.sap.config import DEFAULT_CONFIG, DEFAULT_REFERENCES, read_json
from sources.sap.datasphere import changes, digest, json_bytes
from sources.sap.scenario import build as build_pr1
from sources.sap.schema import Object, SCHEMAS


@contextmanager
def project_directory():
    folder = native.REPOSITORY / ".state" / "sap-native" / f"adapter-test-{uuid.uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        yield folder
    finally:
        shutil.rmtree(folder)


class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config, cls.references = read_json(DEFAULT_CONFIG), read_json(DEFAULT_REFERENCES)
        cls.original = build_pr1(cls.config, cls.references)
        cls.scenario = native.build(cls.config, cls.references)
        cls.contract = cls.scenario.native_contract
        cls.final = cls.scenario.snapshots[-1]

    def test_approved_totals_and_all_checkpoints_are_preserved(self):
        self.assertEqual(self.scenario.documents, self.original.documents)
        self.assertEqual(self.scenario.config, self.config)
        self.assertEqual(self.scenario.references, self.references)
        self.assertEqual(len(self.scenario.snapshots), 6)
        for expected, actual in zip(self.original.snapshots, self.scenario.snapshots, strict=True):
            self.assertEqual((expected.label, expected.timestamp, expected.summary),
                             (actual.label, actual.timestamp, actual.summary))
        expected = {
            "recognized_revenue": "28.00", "content_cost": "13.60", "content_contribution": "14.40",
            "receivables": "12.00", "payables": "8.16", "net_bank_movement": "13.44",
            "net_vat_liability": "2.88", "deferred_revenue": "0.00", "net_billings": "28.00",
        }
        for key, value in expected.items():
            self.assertEqual(self.final.summary[key], D(value))
        self.assertEqual(self.final.summary["accounting_documents"], 10)
        self.assertEqual(self.final.summary["journal_lines"], 25)

    def test_pr1_schemas_and_generator_are_immutable(self):
        before = copy.deepcopy(SCHEMAS)
        native.build(self.config, self.references)
        self.assertEqual(SCHEMAS, before)
        self.assertEqual(build_pr1(self.config, self.references), self.original)
        self.assertNotEqual(set(SCHEMAS), set(self.scenario.schemas))
        self.assertNotIn("FUNCTIONALCURRENCY", {f.name for f in SCHEMAS["I_OPERATIONALACCTGDOCITEM"].fields})

    def test_all_85_native_objects_plus_custom_and_dd03nd_are_delivered(self):
        self.assertEqual(len(self.contract.objects), 85)
        self.assertEqual(len(self.scenario.schemas), 93)
        for snapshot in self.scenario.snapshots:
            self.assertEqual(set(snapshot.tables), set(self.scenario.schemas))
            self.assertTrue(set(self.contract.objects) <= set(snapshot.tables))
            for name, obj in self.scenario.schemas.items():
                self.assertEqual(len(obj.index(snapshot.tables[name])), len(snapshot.tables[name]))
                if name in self.contract.objects:
                    self.assertEqual(obj.keys, tuple(self.contract.objects[name][1]))

    def test_empty_unused_objects_are_typed_not_fabricated_business_rows(self):
        self.assertEqual(len(native.EMPTY_OBJECTS), 12)
        for name in native.EMPTY_OBJECTS:
            self.assertEqual(self.final.tables[name], [])
            obj = self.scenario.schemas[name]
            self.assertTrue(obj.keys)
            table = native.as_table(obj, [], self.final.timestamp)
            self.assertEqual(table.num_rows, 0)
            self.assertEqual(set(table.column_names) - {"__operation_type", "__sequence_number", "__timestamp"},
                             {f.name for f in obj.fields})

    def test_all_scoped_joins_and_extra_projections_resolve_in_source_schema(self):
        self.assertEqual(len(self.contract.joins), 71)
        self.contract.validate_schema()
        for fact, dimension, conditions, extra, _sk in self.contract.joins:
            left = {f.name for f in self.scenario.schemas[fact].fields}
            right = {f.name for f in self.scenario.schemas[dimension].fields}
            for a, b, _op in conditions:
                self.assertIn(a, left)
                self.assertIn(b, right)
            self.assertTrue(set(extra) <= right)
        for snapshot in self.scenario.snapshots:
            stats = native.resolve_relationships(snapshot.tables, self.contract)
            self.assertEqual(len(stats), 71)
            for fact, _dim, _conditions, _extra, sk in self.contract.joins:
                self.assertEqual(sum(stats[f"{fact}:{sk}"].values()), len(snapshot.tables[fact]))

    def test_all_assigned_foreign_keys_match_nonempty_real_dimensions(self):
        stats = native.resolve_relationships(self.final.tables, self.contract)
        for fact, dimension, _conditions, _extra, sk in self.contract.joins:
            if dimension in native.EMPTY_OBJECTS:
                self.assertEqual(stats[f"{fact}:{sk}"]["matched"], 0)
            elif dimension not in {"I_CUSTOMER", "I_SUPPLIER", "I_GLOBALCOMPANY"}:
                self.assertEqual(stats[f"{fact}:{sk}"]["matched"], len(self.final.tables[fact]))
            else:
                self.assertTrue(self.final.tables[dimension])
        for dimension in ("I_COMPANYCODE", "I_GLACCOUNTINCHARTOFACCOUNTS", "I_LEDGER", "I_FISCALPERIODFORVARIANT",
                          "I_COSTCENTER", "I_PROFITCENTER", "I_POSTINGKEY", "I_PAYMENTTERMS",
                          "I_ACCOUNTINGDOCUMENTCATEGORY", "I_SPECIALGLCODE"):
            self.assertTrue(self.final.tables[dimension])

    def test_dd03nd_exactly_matches_every_column_including_custom_and_empty(self):
        expected = native.dd03nd_rows(self.scenario.schemas)
        self.assertEqual(self.final.tables["DD03ND"], expected)
        entries = {(r["STRUCOBJN"], r["FIELDNAME"]): r for r in expected}
        self.assertEqual(len(entries), sum(len(obj.fields) for obj in self.scenario.schemas.values()))
        descriptor = {f.name: f for f in self.scenario.schemas["DD03ND"].fields}
        self.assertGreaterEqual(descriptor["FIELDNAME"].length, max(len(field) for _name, field in entries))
        for name, obj in self.scenario.schemas.items():
            for f in obj.fields:
                self.assertEqual((entries[name, f.name]["DATATYPE"], int(entries[name, f.name]["LENG"]),
                                  int(entries[name, f.name]["DECIMALS"])), (f.ddic, f.length, f.scale))
        self.assertEqual(native.as_table(self.scenario.schemas["DD03ND"],
                         [("L", r) for r in expected], self.final.timestamp).num_rows, len(expected))

    def test_every_journal_projection_preserves_dates_signs_and_clearing(self):
        for old, snapshot in zip(self.original.snapshots, self.scenario.snapshots, strict=True):
            for name in ("I_OPERATIONALACCTGDOCITEM", "I_GLACCOUNTLINEITEMRAWDATA"):
                for original, actual in zip(old.tables[name], snapshot.tables[name], strict=True):
                    for key, expected in original.items():
                        if key in {"INVOICEREFERENCEFISCALYEAR", "INVOICEITEMREFERENCE"} and expected == "":
                            expected = None
                        self.assertEqual(actual[key], expected, (snapshot.label, name, key))
                    self.assertEqual(actual["DEBITCREDITCODE"],
                                     "S" if actual["AMOUNTINTRANSACTIONCURRENCY"] > 0 else "H")
                    for code, amount in native.CURRENCIES.values():
                        self.assertEqual(actual[code], "EUR")
                        self.assertEqual(actual[amount], actual["AMOUNTINTRANSACTIONCURRENCY"])
                sums = defaultdict(lambda: D("0"))
                for row in snapshot.tables[name]:
                    sums[row["COMPANYCODE"], row["FISCALYEAR"], row["ACCOUNTINGDOCUMENT"]] += row["AMOUNTINTRANSACTIONCURRENCY"]
                self.assertTrue(all(total == 0 for total in sums.values()))

    def test_native_aggregate_signed_debit_credit_math_for_all_four_currencies(self):
        rows = self.final.tables["I_OPERATIONALACCTGDOCITEM"]
        for account_type, debit, credit, net in (
            ("D", "38.40", "26.40", "12.00"), ("K", "8.16", "16.32", "-8.16"),
        ):
            projection = native.balance_projection(rows, account_type)
            self.assertEqual(set(projection), {"CC", "FC", "TC", "GC"})
            for currency in projection.values():
                self.assertEqual(currency, {"debit": D(debit), "credit": D(credit), "net": D(net)})
        for snapshot in self.scenario.snapshots:
            for kind, summary in (("D", "receivables"), ("K", "payables")):
                balance = native.balance_projection(snapshot.tables["I_OPERATIONALACCTGDOCITEM"], kind)
                sign = 1 if kind == "D" else -1
                self.assertEqual(balance["TC"]["net"], sign * snapshot.summary[summary])

    def test_billing_custom_contract_linkage_and_supplier_payment_stay_exact(self):
        for name in SCHEMAS:
            if name.startswith("ZMSF_"):
                self.assertEqual(self.final.tables[name], self.original.snapshots[-1].tables[name])
        bills = self.final.tables["C_BILLINGDOCITEMBASICDEX_1"]
        self.assertEqual(len(bills), 4)
        for old, new in zip(self.original.snapshots[-1].tables["C_BILLINGDOCITEMBASICDEX_1"], bills, strict=True):
            self.assertTrue(all(new[k] == v for k, v in old.items()))
            self.assertEqual({new[k] for k in ("PAYERPARTY", "SOLDTOPARTY", "BILLTOPARTY", "SHIPTOPARTY")}, {old["SOLDTOPARTY"]})
        credit = next(r for r in bills if r["BILLINGDOCUMENTCATEGORY"] == "O")
        self.assertEqual((credit["NETAMOUNT"], credit["TAXAMOUNT"], credit["GROSSAMOUNT"]),
                         (D("-2"), D("-.40"), D("-2.40")))
        supplier = [r for r in self.final.tables["I_OPERATIONALACCTGDOCITEM"] if r["FINANCIALACCOUNTTYPE"] == "K"]
        self.assertEqual({r["AMOUNTINTRANSACTIONCURRENCY"] for r in supplier}, {D("-16.32"), D("8.16")})
        self.assertTrue(all(r["CLEARINGDATE"] is None for r in supplier))

    def test_raw_texts_support_native_english_and_french_derivation_without_gold_columns(self):
        for name, (role, _keys, _delta, related) in self.contract.objects.items():
            fields = {f.name for f in self.scenario.schemas[name].fields}
            self.assertFalse(fields & native.NOT_SOURCE)
            self.assertFalse(any(f.startswith("_") for f in fields))
            if role != "TEXT" or not self.final.tables[name]:
                continue
            self.assertEqual({r["LANGUAGE"] for r in self.final.tables[name]}, {"E", "F"})
            keys = set(self.scenario.schemas[related].keys) & fields
            self.assertEqual({tuple(r[k] for k in sorted(keys)) for r in self.final.tables[name]},
                             {tuple(r[k] for k in sorted(keys)) for r in self.final.tables[related]})
        text_rows = self.final.tables["I_GLACCOUNTTEXT"]
        self.assertEqual(len(text_rows), 16)
        self.assertTrue(all(r["GLACCOUNTNAME"] and r["GLACCOUNTLONGNAME"] and r["HIERARCHYNODETEXT"] for r in text_rows))
        self.assertNotIn("LANGUAGENAME", {f.name for f in self.scenario.schemas["I_LANGUAGE"].fields})
        self.assertEqual({r["LANGUAGECODE"] for r in self.final.tables["I_LANGUAGETEXT"]}, {"E", "F"})

    def test_native_finance_hierarchies_cover_msflix_business_leaves(self):
        for kind, dimension in (
            ("GLACCOUNT", "I_GLACCOUNTINCHARTOFACCOUNTS"), ("COSTCENTER", "I_COSTCENTER"),
            ("PROFITCENTER", "I_PROFITCENTER"),
        ):
            rows = self.final.tables[f"I_{kind}HIERARCHYNODE"]
            leaves = {r[kind] for r in rows if r["NODETYPE"] == "L"}
            self.assertEqual(leaves, {r[kind] for r in self.final.tables[dimension]})
            self.assertEqual({r["NODETYPE"] for r in rows}, {"R", "N", "L"})
            self.assertTrue(all(r["HIERARCHYNODE"].startswith("MSF") for r in rows))
        business = json_bytes(self.final.tables).decode().lower()
        for unrelated in ("contoso", "industrial", "pump", "steel", "manufacturing"):
            self.assertNotIn(unrelated, business)
        for row in self.final.tables["ZMSF_RIGHTS_COVERAGE"]:
            self.assertEqual(row["SIMULATION_ONLY"], "X")
            self.assertIsNone(row["CATALOG_SAP_PARTNER_CODE"])
        self.assertEqual({r["CONTENT_KEY"] for r in self.final.tables["ZMSF_RIGHTS_COVERAGE"]}, set(self.config["content_keys"]))
        self.assertIn("fictional", self.final.tables["I_SUPPLIER"][0]["SUPPLIERNAME"])
        self.assertEqual({r["SALESFORCE_CONTACT_ID"] for r in self.final.tables["ZMSF_CUSTOMER_LINK"]},
                         {r["salesforce_contact_id"] for r in self.references["customers"]})

    def test_numc_is_source_string_then_consistent_native_integer_on_join_partners(self):
        fact = self.scenario.schemas["I_GLACCOUNTLINEITEMRAWDATA"]
        dimension = self.scenario.schemas["I_FISCALPERIODFORVARIANT"]
        for column in ("FISCALYEAR", "FISCALPERIOD"):
            left = next(f for f in fact.fields if f.name == column)
            right = next(f for f in dimension.fields if f.name == column)
            self.assertEqual((left.ddic, left.length), (right.ddic, right.length))
            self.assertEqual(native.arrow_type(left), pa.string())
            self.assertEqual(native._cast("011", left), 11)
        self.assertEqual(self.final.tables[fact.name][0]["FISCALPERIOD"], "011")
        self.assertTrue(all(len(r["CUSTOMER"]) == 10 for r in self.final.tables["I_CUSTOMER"]))
        self.assertTrue(all(len(r["ACCOUNTINGDOCUMENT"]) == 10 for r in self.final.tables[fact.name]))
        with self.assertRaisesRegex(ValueError, "overflow"):
            native.NativeField("OVERFLOW", "NUMC", 10).validate("9999999999")

    def test_invalid_inputs_are_not_defaulted_or_dropped(self):
        for key, value in (("monthly_net", 10.0), ("currency", "USD"), ("unknown", "value"),
                           ("content_keys", ["UNKNOWN"]), ("supplier_name", "Blender Foundation")):
            config = copy.deepcopy(self.config)
            config[key] = value
            with self.subTest(key=key), self.assertRaises((ValueError, jsonschema.ValidationError)):
                native.build(config, self.references)
        obj = self.scenario.schemas["I_CUSTOMER"]
        row = self.final.tables[obj.name][0]
        for rows in ([{**row, "UNKNOWN": "value"}], [row, row],
                     [{**row, "CUSTOMER": "X" * 11}], [{**row, "COUNTRY": 42}]):
            with self.assertRaises(ValueError):
                native.as_table(obj, [("L", r) for r in rows], self.final.timestamp)
        for bad in (1.0, D("NaN"), D("1.001")):
            with self.assertRaises(ValueError):
                native.NativeField("MONEY", "CURR", 23, 2).validate(bad)
        with self.assertRaisesRegex(ValueError, "UTC"):
            native.as_table(obj, [("L", row)], datetime(2026, 11, 1))

    def test_uncovered_native_keys_relationships_and_type_conflicts_fail(self):
        for mutation, pattern in (
            (lambda c: c.schemas.pop("I_COMPANYCODE"), "Uncovered"),
            (lambda c: c.objects["I_COMPANYCODE"][1].append("UNKNOWN"), "keys"),
            (lambda c: c.joins[0][2][0].__setitem__(0, "UNKNOWN"), "join columns"),
            (lambda c: c.joins[0][3].append("UNKNOWN"), "projections"),
        ):
            contract = copy.deepcopy(self.contract)
            mutation(contract)
            with self.assertRaisesRegex(ValueError, pattern):
                contract.validate_schema()
        contract = copy.deepcopy(self.contract)
        obj = contract.schemas["I_FISCALPERIODFORVARIANT"]
        contract.schemas[obj.name] = Object(obj.name, tuple(
            replace(f, ddic="CHAR") if f.name == "FISCALPERIOD" else f for f in obj.fields
        ))
        with self.assertRaisesRegex(ValueError, "type conflict"):
            contract.validate_schema()

    def test_corrupted_foreign_keys_clearing_types_and_lineage_fail(self):
        cases = (
            ("I_COMPANYCODE", "COMPANYCODE", "FAIL"),
            ("I_OPERATIONALACCTGDOCITEM", "CUSTOMER", "9999999999"),
            ("I_OPERATIONALACCTGDOCITEM", "FUNCTIONALCURRENCY", "USD"),
            ("I_OPERATIONALACCTGDOCITEM", "CLEARINGACCOUNTINGDOCUMENT", "0000000000"),
            ("ZMSF_CUSTOMER_LINK", "SALESFORCE_CONTACT_ID", "X" * 18),
            ("ZMSF_RIGHTS_CONTRACT", "SIMULATION_ONLY", ""),
            ("ZMSF_RIGHTS_COVERAGE", "CONTENT_KEY", "UNRESOLVED"),
            ("ZMSF_BILLING_LINK", "SUBSCRIPTION_ID", "UNRESOLVED"),
            ("I_GLACCOUNTHIERARCHYNODE", "PARENTNODE", "UNRESOLVED"),
            ("DD03ND", "DATATYPE", "FAIL"),
        )
        for name, column, value in cases:
            tables = copy.deepcopy(self.final.tables)
            tables[name][0][column] = value
            with self.subTest(table=name, column=column), self.assertRaises(ValueError):
                native.validate_snapshot(tables, self.contract, self.config, self.references)

    def test_scope_manifest_never_claims_cloud_or_native_pipeline_success(self):
        manifest = self.contract.manifest()
        self.assertFalse(manifest["native_bps_ready"])
        compatibility = manifest["compatibility"]
        self.assertEqual(compatibility["scope"], "LOCAL_ASSERTED_ONLY")
        self.assertFalse(compatibility["pipeline_qualified"])
        self.assertEqual(compatibility["native_objects_covered"], 85)
        self.assertEqual(compatibility["in_scope_relationships"], 71)
        self.assertEqual(compatibility["excluded_global_relationships"][0]["count"], 196)
        self.assertEqual(self.contract.provenance["native_metadata_rows"], 167)
        self.assertTrue(self.contract.provenance["input_sha256"]["column_contract.json"])

    def test_actual_captured_metadata_is_fully_compared_with_explicit_scope_inventory(self):
        actual = native.REPOSITORY / ".state" / "sap-native" / "native-contract.json"
        if not actual.is_file():
            self.skipTest("Captured local metadata absent; vendored source contract is tested separately")
        raw = read_json(actual)
        contract = native.load_contract(actual)
        self.assertEqual(len(contract.excluded_relationships), len(raw["joins"]) - 71)
        self.assertTrue(all(r["fact"] not in contract.objects for r in contract.excluded_relationships))
        self.assertEqual(contract.provenance["actual_metadata_sha256"], digest(actual.read_bytes()))
        self.assertEqual(contract.schemas, self.contract.schemas)
        for mutation in ("key", "relationship", "role", "field_metadata"):
            broken = copy.deepcopy(raw)
            if mutation == "key":
                broken["objects"][0]["KeyFields"] = '["UNKNOWN"]'
            elif mutation == "relationship":
                broken["joins"][0]["JoinCondition"] = '[("UNKNOWN","BILLINGDOCUMENTTYPE","==")]'
            elif mutation == "role":
                broken["objects"][0]["Type"] = "UNKNOWN"
            else:
                broken["columns"] = [{"fieldName": "UNKNOWN"}]
            with project_directory() as folder:
                path = folder / "contract.json"
                path.write_bytes(json_bytes(broken))
                with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, "native|Native"):
                    native.load_contract(path)

    def test_native_gold_sql_source_projections_are_covered_without_emitting_gold_fields(self):
        path = native.REPOSITORY / ".state" / "sap-native" / "gold-views-notebook-content.py"
        if not path.is_file():
            self.skipTest("Captured Gold SQL notebook absent")
        notebook = path.read_text(encoding="utf-8")
        for view, source in (
            ("vCOSTCENTER", "I_COSTCENTER"), ("vCOSTCENTERACTIVITYTYPE", "I_COSTCENTERACTIVITYTYPE"),
            ("vPROFITCENTER", "I_PROFITCENTER"), ("vGLACCOUNTLINEITEMRAWDATA_AGGR", "I_GLACCOUNTLINEITEMRAWDATA"),
        ):
            section = notebook.split(f"# #### {view}\n", 1)[1].split("# MARKDOWN", 1)[0]
            # Skip table-existence guards and find the actual CREATE VIEW SELECT.
            select = section[section.index("CREATE OR ALTER VIEW"):].split("FROM [", 1)[0]
            columns = set(re.findall(r"\[([A-Za-z_][A-Za-z0-9_]*)\]", select))
            columns -= {"dbo", view, "Key", "_UpdateTimeStamp", "_SystemName"}
            columns = {c for c in columns if not c.lower().startswith("_key_")}
            self.assertTrue(columns <= {f.name for f in self.scenario.schemas[source].fields},
                            (view, columns - {f.name for f in self.scenario.schemas[source].fields}))

    def test_parquet_and_metadata_support_native_custom_ddic_types_and_empty_keys(self):
        name = "C_BILLINGDOCITEMBASICDEX_1"
        obj = self.scenario.schemas[name]
        table = native.as_table(obj, [("L", r) for r in self.final.tables[name]], self.final.timestamp)
        self.assertEqual(table.schema.field("BILLINGQUANTITY").type, pa.decimal128(13, 3))
        self.assertEqual(table.schema.field("NETAMOUNT").type, pa.decimal128(23, 2))
        self.assertEqual(table.schema.field("BILLINGDOCUMENTDATE").type, pa.date32())
        fields = {r["name"]: r for r in json.loads(native.metadata(obj, "S4M"))["columns"]}
        self.assertEqual((fields["BILLINGQUANTITY"]["dataType"], fields["BILLINGQUANTITY"]["scale"]), ("DECIMAL", 3))
        technical = {"__operation_type", "__sequence_number", "__timestamp"}
        self.assertEqual(set(fields) - technical, {f.name for f in obj.fields})
        self.assertEqual(fields["BILLINGDOCUMENTITEM"]["dataType"], "NVARCHAR")
        initial = self.scenario.schemas["I_ACCOUNTINGDOCUMENTCATEGORY"]
        self.assertEqual(native.as_table(initial, [("L", self.final.tables[initial.name][0])], self.final.timestamp).num_rows, 1)
        with self.assertRaises(ValueError):
            native.NativeField("CUSTOMER", "CHAR", 10, key=True).validate("")
        for ddic, value, expected in (("INT4", 2, pa.int32()), ("INT8", 2147483648, pa.int64())):
            f = native.NativeField("VALUE", ddic, 10 if ddic == "INT4" else 19)
            f.validate(value)
            self.assertEqual(native.arrow_type(f), expected)
            with self.assertRaises(ValueError):
                f.validate(float(value))
        with self.assertRaisesRegex(ValueError, "Uncovered"):
            native.arrow_type(native.NativeField("VALUE", "UNKNOWN"))

    def test_native_financial_deletes_and_unknown_operations_are_prohibited(self):
        obj = self.scenario.schemas["I_OPERATIONALACCTGDOCITEM"]
        row = self.final.tables[obj.name][0]
        with self.assertRaisesRegex(ValueError, "financial deletes"):
            changes(obj, [row], [])
        with self.assertRaisesRegex(ValueError, "operation"):
            native.as_table(obj, [("X", {key: row[key] for key in obj.keys})], self.final.timestamp)
        with self.assertRaisesRegex(ValueError, "operation"):
            native.as_table(obj, [("UNKNOWN", row)], self.final.timestamp)

    def test_packages_replay_all_93_objects_idempotently_at_every_checkpoint(self):
        with project_directory() as root:
            manifest = native.write_package(root, self.scenario)
            batches = read_json(root / "manifest.json")["batch_count"]
            self.assertEqual(batches, 6)
            self.assertEqual((manifest["native_object_count"], manifest["object_count"]), (85, 93))
            self.assertFalse(manifest["native_bps_ready"])
            self.assertFalse(manifest["pipeline_qualified"])
            self.assertEqual(manifest["network_operations"], 0)
            state = {name: {} for name in self.scenario.schemas}
            for batch, snapshot in zip(json.loads((root / "batches.json").read_text()), self.scenario.snapshots, strict=True):
                for name, entry in batch["objects"].items():
                    obj = self.scenario.schemas[name]
                    payload = pq.read_table(root / entry["file"])
                    for _ in range(2):
                        for raw in payload.to_pylist():
                            operation = raw.pop("__operation_type")
                            self.assertIsNone(raw.pop("__sequence_number"))
                            raw.pop("__timestamp")
                            key = tuple(raw[column] for column in obj.keys)
                            if operation == "X":
                                state[name].pop(key, None)
                            else:
                                state[name][key] = raw
                for name, obj in self.scenario.schemas.items():
                    self.assertEqual(state[name], obj.index(snapshot.tables[name]), (snapshot.label, name))
            for path, checksum in manifest["files"].items():
                self.assertEqual(digest((root / path).read_bytes()), checksum)
            for name in self.scenario.schemas:
                folder = root / "datasphere" / "S4M" / name / "initial"
                self.assertTrue((folder / "_SUCCESS").is_file())
                self.assertTrue((folder / ".sap.partfile.metadata").is_file())
                self.assertEqual(len(list(folder.glob("*.parquet"))), 1)
            self.assertTrue((root / "local-validation.json").is_file())

    def test_clearing_deltas_update_old_rows_and_use_native_composite_keys(self):
        before, after = self.scenario.snapshots[:2]
        for name in ("I_OPERATIONALACCTGDOCITEM", "I_GLACCOUNTLINEITEMRAWDATA"):
            obj = self.scenario.schemas[name]
            operations = changes(obj, before.tables[name], after.tables[name])
            self.assertEqual(len(operations), 3)
            self.assertTrue(all(op == "U" for op, _r in operations))
            old = obj.index(before.tables[name])
            cleared = [r for _op, r in operations if tuple(r[k] for k in obj.keys) in old]
            self.assertEqual(len(cleared), 1)
            self.assertEqual(cleared[0]["CLEARINGDATE"], date(2026, 11, 2))

    def test_generation_is_local_reproducible_and_never_overwrites_changed_output(self):
        with project_directory() as parent:
            a, b = parent / "a", parent / "b"
            with patch("socket.socket", side_effect=AssertionError("Network access prohibited")):
                first = native.generate(a)
                self.assertEqual(first["status"], "created")
                self.assertEqual(native.generate(a)["status"], "unchanged")
                native.generate(b)
            self.assertEqual((a / "manifest.json").read_bytes(), (b / "manifest.json").read_bytes())
            (a / "summary.json").write_text("corrupted")
            with self.assertRaises(FileExistsError):
                native.generate(a)
            self.assertEqual((a / "summary.json").read_text(), "corrupted")
            self.assertFalse(list(parent.glob(".native-pending-*")))
        with self.assertRaisesRegex(ValueError, "child"):
            native.generate(native.REPOSITORY / "native-source-package")

    def test_long_observed_source_keys_are_preserved_without_sap_id_truncation(self):
        config, references = copy.deepcopy(self.config), copy.deepcopy(self.references)
        old = config["customers"][0]["customer_key"]
        key = "C" * 80
        config["customers"][0]["customer_key"] = key
        next(r for r in references["customers"] if r["customer_key"] == old)["customer_key"] = key
        original_content = config["content_keys"][0]
        content = "MSF-" + "C" * 76
        config["content_keys"][0] = content
        next(r for r in references["contents"] if r["content_key"] == original_content)["content_key"] = content
        scenario = native.build(config, references)
        self.assertIn(key, {r["CUSTOMER_KEY"] for r in scenario.snapshots[-1].tables["ZMSF_CUSTOMER_LINK"]})
        self.assertIn(content, {r["CONTENT_KEY"] for r in scenario.snapshots[-1].tables["ZMSF_RIGHTS_COVERAGE"]})
        self.assertEqual(scenario.snapshots[-1].summary["recognized_revenue"], D("28.00"))

    def test_february_calendar_and_credit_rounding_preserve_original_behavior(self):
        config = copy.deepcopy(self.config)
        config.update(period_start="2027-02-01", credit_net="0.01")
        scenario = native.build(config, self.references)
        self.assertEqual(scenario.snapshots[-1].summary["as_of"], date(2027, 2, 28))
        self.assertEqual(scenario.snapshots[-1].summary["recognized_revenue"], D("29.99"))
        self.assertEqual(scenario.snapshots[-1].tables["ZMSF_PLAN"][0]["VALID_TO_EXCLUSIVE"], date(2027, 3, 1))


if __name__ == "__main__":
    unittest.main()
