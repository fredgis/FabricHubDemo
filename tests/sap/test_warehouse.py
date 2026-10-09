"""Offline only: native/TDS fixtures and mocked scoped client; never cloud calls."""
import copy
import io
import json
import shutil
import sys
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fabric.rest import DeploymentError
from sources.sap import warehouse as w
from sources.sap.config import DEFAULT_CONFIG, DEFAULT_REFERENCES, read_json
from sources.sap.native import INPUT_CONTRACT, build as build_native, load_contract


TARGET = {
    "workspace_id": "33333333-3333-4333-8333-333333333333", "system_suffix": "fea347cc",
    "source_system": "S4M", "tenant_id": "11111111-1111-1111-1111-111111111111",
    "subscription_id": "22222222-2222-2222-2222-222222222222",
    "operator_id": "33333333-3333-3333-3333-333333333333",
}
RUN = "sap-november-2026-qualified-v1"


class WarehouseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = read_json(DEFAULT_CONFIG)
        cls.references = read_json(DEFAULT_REFERENCES)
        # A test-only metadata fixture makes this suite independent of ignored .state captures.
        directory = w.ROOT / ".state" / ("warehouse-test-metadata-" + str(uuid4()))
        directory.mkdir(parents=True)
        cls.addClassCleanup(shutil.rmtree, directory)
        cls.metadata = directory / "native-contract.json"
        bundled = read_json(INPUT_CONTRACT)
        schemas = load_contract().schemas
        registrations = {
            **bundled["objects"],
            **{n: ["FACT" if schemas[n].financial else "DIMENSION", list(schemas[n].keys),
                    schemas[n].financial, ""] for n in w.CUSTOM},
        }
        cls.metadata.write_text(json.dumps({
            "objects": [{"SystemName": "S4M", "CDSViewName": n, "Type": spec[0], "KeyFields": spec[1],
                         "Delta": spec[2], "relatedCDSViewName": spec[3]} for n, spec in registrations.items()],
            "joins": [{"FactTable": f, "DimensionTable": d, "JoinCondition": c, "DimColumns": extra,
                       "SKColumn": sk, "RelationshipName": sk} for f, d, c, extra, sk in bundled["joins"]],
            "columns": [],
        }), encoding="utf-8")
        cls.contract, cls.totals, cls.input_hash = w.inputs(cls.config, cls.references, cls.metadata)
        # Generated fixture rows simulate SQL reads in tests only, never production ingress.
        snapshot = build_native(cls.config, cls.references, metadata_path=cls.metadata).snapshots[-1]
        cls.fixture = {}
        cls.bindings = {}
        for name in w.TABLES:
            cls.fixture[name] = []
            for row in snapshot.tables[name]:
                projected = {f.name: row[f.name] for f in w.selected_fields(cls.contract, name)}
                projected.update(NATIVE_DIMENSION_KEY=len(cls.fixture[name])+1
                                 if name in w.CUSTOM and not cls.contract.schemas[name].financial else None,
                                 NATIVE_UPDATE_TIMESTAMP=datetime(2026, 11, 30, 23, 59, 59))
                cls.fixture[name].append(projected)
            columns = []
            for i, field in enumerate(w.selected_fields(cls.contract, name), 1):
                kind = w.sql_type(field).split("(")[0]
                if field.ddic == "NUMC":
                    kind = "int"
                columns.append({
                    "TABLE_SCHEMA": "dbo", "TABLE_NAME": name, "COLUMN_NAME": field.name,
                    "ORDINAL_POSITION": i, "DATA_TYPE": kind,
                    "CHARACTER_MAXIMUM_LENGTH": field.length if kind == "varchar" else None,
                    "NUMERIC_PRECISION": field.length if kind == "decimal" else None,
                    "NUMERIC_SCALE": field.scale if kind == "decimal" else None, "IS_NULLABLE": "YES",
                })
            for col, kind in (("_SystemName", "varchar"), ("_UpdateTimeStamp", "datetime2")):
                columns.append({
                    "TABLE_SCHEMA": "dbo", "TABLE_NAME": name, "COLUMN_NAME": col,
                    "ORDINAL_POSITION": len(columns)+1, "DATA_TYPE": kind,
                    "CHARACTER_MAXIMUM_LENGTH": 16 if kind == "varchar" else None,
                    "NUMERIC_PRECISION": None, "NUMERIC_SCALE": None, "IS_NULLABLE": "NO",
                })
            if name in w.CUSTOM and not cls.contract.schemas[name].financial:
                columns.append({
                    "TABLE_SCHEMA": "dbo", "TABLE_NAME": name, "COLUMN_NAME": "Key",
                    "ORDINAL_POSITION": len(columns)+1, "DATA_TYPE": "bigint",
                    "CHARACTER_MAXIMUM_LENGTH": None, "NUMERIC_PRECISION": 19,
                    "NUMERIC_SCALE": 0, "IS_NULLABLE": "NO",
                })
            if name in w.CUSTOM_RELATIONSHIPS:
                columns.append({
                    "TABLE_SCHEMA": "dbo", "TABLE_NAME": name,
                    "COLUMN_NAME": w.CUSTOM_RELATIONSHIPS[name][2],
                    "ORDINAL_POSITION": len(columns)+1, "DATA_TYPE": "bigint",
                    "CHARACTER_MAXIMUM_LENGTH": None, "NUMERIC_PRECISION": 19,
                    "NUMERIC_SCALE": 0, "IS_NULLABLE": "YES",
                })
            cls.bindings[name] = {"schema": "dbo", "table": name, "columns": columns}
        cls.customers = [{"customer_key": r["customer_key"], "source_customer_id": r["salesforce_contact_id"]}
                         for r in cls.references["customers"]]
        cls.contents = [{"content_key": r["content_key"], "distributor_key": r["distributor_key"]}
                        for r in cls.references["contents"]]
        cls.distributors = [{"distributor_key": r["distributor_key"]} for r in cls.references["distributors"]]
        cls.jobs = {
            "b2s": {"pipeline_id": "44444444-4444-4444-4444-444444444444", "job_id": "55555555-5555-5555-5555-555555555555"},
            "s2g": {"pipeline_id": "66666666-6666-6666-6666-666666666666", "job_id": "77777777-7777-7777-7777-777777777777"},
        }

    def setUp(self):
        self.rows = copy.deepcopy(self.fixture)
        self.directory = w.ROOT / ".state" / ("warehouse-offline-tests-" + str(uuid4()))
        self.directory.mkdir()
        self.addCleanup(shutil.rmtree, self.directory)

    def qualify(self, **kwargs):
        return w.qualify(self.rows, self.contract, self.config, self.references, self.totals,
                         kwargs.get("customers", self.customers), kwargs.get("contents", self.contents),
                         kwargs.get("distributors", self.distributors))

    def write_evidence(self, state="Completed"):
        for stage, job in self.jobs.items():
            (self.directory / (stage+"-job.json")).write_text(json.dumps({
                **job, "workspace_id": TARGET["workspace_id"], "stage": stage, "state": state,
                "data_verified": False,
            }), encoding="utf-8")

    def test_approved_native_reconciliation(self):
        result = self.qualify()
        self.assertEqual(result["journal_lines"], 25)
        self.assertEqual(result["accounting_documents"], 10)
        for name, value in {
            "net_billings": "28.00", "recognized_revenue": "28.00", "content_cost": "13.60",
            "receivables": "12.00", "payables": "8.16", "net_bank_movement": "13.44",
            "net_vat_liability": "2.88", "content_contribution": "14.40",
        }.items():
            self.assertEqual(result[name], Decimal(value))
        self.assertEqual(len(self.rows["ZMSF_SUBSCRIPTION"]), 3)
        self.assertEqual(len(self.rows["ZMSF_CONTRACT_CHARGE"]), 2)

    def test_dynamic_expected_totals_not_ingress(self):
        config = copy.deepcopy(self.config)
        config["monthly_net"] = "15.00"
        result = w.expected(config, self.references)
        self.assertEqual(result["net_billings"], Decimal("43.00"))
        self.assertEqual(result["content_cost"], Decimal("16.60"))
        with self.assertRaisesRegex(DeploymentError, "formula"):
            w.qualify(self.rows, self.contract, config, self.references, result,
                      self.customers, self.contents, self.distributors)

    def test_duplicates_fail_at_every_custom_grain(self):
        for name in w.CUSTOM:
            with self.subTest(name=name):
                rows = copy.deepcopy(self.fixture)
                rows[name].append(copy.deepcopy(rows[name][0]))
                with self.assertRaisesRegex(DeploymentError, "duplicate native business PK"):
                    w.qualify(rows, self.contract, self.config, self.references, self.totals,
                              self.customers, self.contents, self.distributors)

    def test_gl_full_ledger_key_and_bseg_not_additional_revenue(self):
        self.rows["I_GLACCOUNTLINEITEMRAWDATA"][0]["SOURCELEDGER"] = "1L"
        with self.assertRaisesRegex(DeploymentError, "ledger"):
            self.qualify()
        self.rows = copy.deepcopy(self.fixture)
        self.rows["I_OPERATIONALACCTGDOCITEM"][0]["AMOUNTINTRANSACTIONCURRENCY"] += Decimal("1")
        with self.assertRaisesRegex(DeploymentError, "same journal projection"):
            self.qualify()

    def test_balanced_aggregate_does_not_hide_unbalanced_documents(self):
        # Change two different bank documents without changing the overall balance.
        gl = self.rows["I_GLACCOUNTLINEITEMRAWDATA"]
        bank = [r for r in gl if r["GLACCOUNT"] == "0011000000"][:2]
        bank[0]["AMOUNTINTRANSACTIONCURRENCY"] += Decimal("1")
        bank[1]["AMOUNTINTRANSACTIONCURRENCY"] -= Decimal("1")
        for row in bank:
            for field in ("AMOUNTINCOMPANYCODECURRENCY", "AMOUNTINFUNCTIONALCURRENCY",
                          "AMOUNTINADDITIONALCURRENCY1", "AMOUNTINGLOBALCURRENCY"):
                row[field] = row["AMOUNTINTRANSACTIONCURRENCY"]
            op = next(r for r in self.rows["I_OPERATIONALACCTGDOCITEM"]
                      if r["ACCOUNTINGDOCUMENT"] == row["ACCOUNTINGDOCUMENT"] and r["ACCOUNTINGDOCUMENTITEM"] == row["ACCOUNTINGDOCUMENTITEM"])
            op.update({k: row[k] for k in op if k not in {"NATIVE_DIMENSION_KEY", "NATIVE_UPDATE_TIMESTAMP"}})
        with self.assertRaisesRegex(DeploymentError, "does not balance"):
            self.qualify()

    def test_payment_reference_cannot_point_to_itself(self):
        for kind in ("DZ", "DA", "KZ"):
            self.rows = copy.deepcopy(self.fixture)
            for table in ("I_OPERATIONALACCTGDOCITEM", "I_GLACCOUNTLINEITEMRAWDATA"):
                row = next(r for r in self.rows[table]
                           if r["ACCOUNTINGDOCUMENTTYPE"] == kind and r["FINANCIALACCOUNTTYPE"] in ("D", "K"))
                row.update(INVOICEREFERENCE=row["ACCOUNTINGDOCUMENT"],
                           INVOICEREFERENCEFISCALYEAR=row["FISCALYEAR"],
                           INVOICEITEMREFERENCE=row["ACCOUNTINGDOCUMENTITEM"])
            with self.subTest(kind=kind), self.assertRaisesRegex(DeploymentError, "not itself"):
                self.qualify()

    def test_collection_and_refund_require_the_correct_reference_document_type(self):
        customer = next(r["sap_customer"] for r in self.config["customers"] if r["role"] == "paid_with_credit")
        for kind, wrong_reference_type in (("DZ", "DG"), ("DA", "DR")):
            self.rows = copy.deepcopy(self.fixture)
            for table in ("I_OPERATIONALACCTGDOCITEM", "I_GLACCOUNTLINEITEMRAWDATA"):
                reference = next(r for r in self.rows[table]
                                 if r["ACCOUNTINGDOCUMENTTYPE"] == wrong_reference_type
                                 and r["CUSTOMER"] == customer)
                payment = next(r for r in self.rows[table]
                               if r["ACCOUNTINGDOCUMENTTYPE"] == kind
                               and r["CUSTOMER"] == reference["CUSTOMER"])
                payment.update(INVOICEREFERENCE=reference["ACCOUNTINGDOCUMENT"],
                               INVOICEREFERENCEFISCALYEAR=reference["FISCALYEAR"],
                               INVOICEITEMREFERENCE=reference["ACCOUNTINGDOCUMENTITEM"])
            with self.subTest(kind=kind), self.assertRaisesRegex(DeploymentError, "expected type"):
                self.qualify()
    def test_crm_identity_and_catalog_links_are_exact(self):
        customers = copy.deepcopy(self.customers)
        customers[0]["source_customer_id"] = "another-contact"
        with self.assertRaisesRegex(DeploymentError, "source_customer_id"):
            self.qualify(customers=customers)
        contents = copy.deepcopy(self.contents)
        contents[0]["distributor_key"] = "ANOTHER-DISTRIBUTOR"
        with self.assertRaisesRegex(DeploymentError, "catalog reference"):
            self.qualify(contents=contents)

    def test_missing_table_or_native_watermark_fails(self):
        self.rows["I_FISCALPERIODFORVARIANT"] = []
        with self.assertRaisesRegex(DeploymentError, "empty"):
            self.qualify()
        self.rows = copy.deepcopy(self.fixture)
        self.rows["ZMSF_PLAN"][0]["NATIVE_UPDATE_TIMESTAMP"] = None
        with self.assertRaisesRegex(DeploymentError, "watermark"):
            self.qualify()

    def test_contract_versions_are_source_numc_text_not_surrogates(self):
        ddl = w.domain_ddl(self.contract)
        self.assertIn("[VERSION] varchar(4) NOT NULL", ddl)
        self.assertIn("[NATIVE_DIMENSION_KEY] bigint NULL", ddl)
        f = next(f for f in self.contract.schemas["ZMSF_PLAN"].fields if f.name == "VERSION")
        self.assertIn("CAST(s.[VERSION] AS varchar(4))", w.expression(f))
        self.assertIn("REPLICATE('0',4)", w.expression(f))
        self.rows["ZMSF_PLAN"][0]["VERSION"] = 1
        with self.assertRaisesRegex(DeploymentError, "NUMC conversion"):
            self.qualify()

    def test_custom_native_dimension_key_is_required_and_separate_from_business_pk(self):
        self.rows["ZMSF_PLAN"][0]["NATIVE_DIMENSION_KEY"] = None
        with self.assertRaisesRegex(DeploymentError, "actual native dimension Key"):
            self.qualify()
        altered = copy.deepcopy(self.bindings)
        altered["ZMSF_PLAN"]["columns"] = [c for c in altered["ZMSF_PLAN"]["columns"] if c["COLUMN_NAME"] != "Key"]
        with patch.object(w, "execute", side_effect=lambda conn, sql, params=():
                          [c for b in altered.values() for c in b["columns"]] if "COLUMNS" in sql else self.catalog_execute(conn, sql)):
            with self.assertRaisesRegex(DeploymentError, "native custom dimension Key missing"):
                w.catalog(object(), self.contract, "dbo")
        keys = self.contract.schemas["ZMSF_PLAN"].keys
        self.assertEqual(keys, ("PLAN_ID", "VERSION"))
        self.assertNotIn("Key", keys)

    def test_silver_qualification_does_not_invent_gold_surrogate_keys(self):
        for rows in self.rows.values():
            for row in rows:
                row["NATIVE_DIMENSION_KEY"] = None
        result = w.qualify(self.rows, self.contract, self.config, self.references, self.totals,
                           self.customers, self.contents, self.distributors, source_stage="silver")
        self.assertEqual(result["recognized_revenue"], Decimal("28.00"))
        with self.assertRaisesRegex(DeploymentError, "actual native dimension Key"):
            self.qualify()
        self.rows["I_GLACCOUNTLINEITEMRAWDATA"][0]["AMOUNTINTRANSACTIONCURRENCY"] += Decimal("1")
        with self.assertRaises(DeploymentError):
            w.qualify(self.rows, self.contract, self.config, self.references, self.totals,
                      self.customers, self.contents, self.distributors, source_stage="silver")

    def relationship_proof(self):
        return {fact: {"dimension": dimension, "keys": list(keys), "surrogate_column": sk,
                       "joined_rows": len(self.rows[fact]), "invalid_rows": 0}
                for fact, (dimension, keys, sk) in w.CUSTOM_RELATIONSHIPS.items()}

    def test_native_fact_surrogate_columns_are_gold_only_requirements(self):
        for kind in (None, "varchar"):
            altered = copy.deepcopy(self.bindings)
            sk = w.CUSTOM_RELATIONSHIPS["ZMSF_BILLING_LINK"][2]
            columns = altered["ZMSF_BILLING_LINK"]["columns"]
            if kind is None:
                columns[:] = [c for c in columns if c["COLUMN_NAME"] != sk]
            else:
                next(c for c in columns if c["COLUMN_NAME"] == sk)["DATA_TYPE"] = kind
            with self.subTest(kind=kind), patch.object(
                    w, "execute", side_effect=lambda conn, sql, params=():
                    [c for b in altered.values() for c in b["columns"]] if "COLUMNS" in sql
                    else self.catalog_execute(conn, sql)):
                with self.assertRaisesRegex(DeploymentError, "native fact surrogate"):
                    w.catalog(object(), self.contract, "dbo")
                w.catalog(object(), self.contract, "dbo", source_stage="silver")

    def test_native_surrogates_match_source_business_keys_and_contract_version(self):
        statements = []
        def execute(connection, query, params=()):
            statements.append(query)
            fact = next(n for n in w.CUSTOM_RELATIONSHIPS if "["+n+"] s" in query)
            return [{"joined_rows": len(self.rows[fact]), "invalid_rows": 0}]
        with patch.object(w, "execute", side_effect=execute):
            actual = w.qualify_native_relationships(object(), self.bindings, self.config,
                                                    self.rows, "native-database")
        self.assertEqual(actual, self.relationship_proof())
        sql = "\n".join(statements)
        self.assertIn("s.[VERSION]=d.[VERSION]", sql)
        self.assertIn("s.[_SystemName]=d.[_SystemName]", sql)
        self.assertIn("s.[_SystemName]='S4M'", sql)
        self.assertIn("d.[Key] IS NULL OR d.[Key]=-1", sql)
        self.assertIn("s.[_key_ZMSFSUBSCRIPTION] IS NULL", sql)
        self.assertIn("s.[_key_ZMSFRIGHTSCONTRACT]<>d.[Key]", sql)
        self.assertIn("[native-database].[dbo].[ZMSF_RIGHTS_CONTRACT]", sql)

    def test_native_surrogate_gate_refuses_missing_mismatched_and_multiple_members(self):
        for result in ([{"joined_rows": 4, "invalid_rows": 1}],
                       [{"joined_rows": 5, "invalid_rows": 0}],
                       [{"joined_rows": 0, "invalid_rows": None}], []):
            with self.subTest(result=result), patch.object(w, "execute", return_value=result):
                with self.assertRaisesRegex(DeploymentError, "native surrogate relationship"):
                    w.qualify_native_relationships(object(), self.bindings, self.config, self.rows)

    def test_unknown_native_qualification_stage_is_refused(self):
        with self.assertRaisesRegex(DeploymentError, "invalid native source stage"):
            w.qualify(self.rows, self.contract, self.config, self.references, self.totals,
                      self.customers, self.contents, self.distributors, source_stage="mirror")

    def test_initial_financial_status_and_unassigned_surrogate_are_not_rejected(self):
        for name in ("I_GLACCOUNTLINEITEMRAWDATA", "I_OPERATIONALACCTGDOCITEM"):
            self.rows[name][0]["ACCOUNTINGDOCUMENTCATEGORY"] = ""
            self.rows[name][0]["NATIVE_DIMENSION_KEY"] = -1
        self.assertEqual(self.qualify(), self.totals)

    def test_fiscal_full_calendar_and_hierarchy_business_keys(self):
        self.rows["I_FISCALPERIODFORVARIANT"][0]["FISCALPERIODENDDATE"] = self.totals["as_of"]
        with self.assertRaisesRegex(DeploymentError, "gap/overlap"):
            self.qualify()
        ddl = w.domain_ddl(self.contract)
        for name in ("I_GLACCOUNTHIERARCHYNODE", "I_COSTCENTERHIERARCHYNODE", "I_PROFITCENTERHIERARCHYNODE"):
            for key in self.contract.schemas[name].keys:
                self.assertIn("["+key+"]", ddl)

    def test_invoice_link_tax_credit_and_order_fail(self):
        for field, value, message in (
            ("TAXAMOUNT", Decimal("99.00"), "signed tax"),
            ("SOLDTOPARTY", "NO-CUSTOMER", "customer"),
        ):
            with self.subTest(field=field):
                self.rows = copy.deepcopy(self.fixture)
                self.rows["C_BILLINGDOCITEMBASICDEX_1"][0][field] = value
                with self.assertRaisesRegex(DeploymentError, message):
                    self.qualify()
        self.rows = copy.deepcopy(self.fixture)
        self.rows["ZMSF_BILLING_LINK"][0]["ORDER_ID"] = "A-TVOD-ORDER"
        with self.assertRaisesRegex(DeploymentError, "commercial order"):
            self.qualify()

    def test_clearing_fields_cannot_be_invented_for_partial_payment(self):
        for name in ("I_GLACCOUNTLINEITEMRAWDATA", "I_OPERATIONALACCTGDOCITEM"):
            row = next(r for r in self.rows[name] if r["ACCOUNTINGDOCUMENTTYPE"] == "KZ" and r["SUPPLIER"])
            row["CLEARINGACCOUNTINGDOCUMENT"] = row["ACCOUNTINGDOCUMENT"]
        with self.assertRaisesRegex(DeploymentError, "falsely carries"):
            self.qualify()

    def catalog_execute(self, connection, query, params=()):
        if "INFORMATION_SCHEMA.TABLES" in query:
            return [{"TABLE_SCHEMA": b["schema"], "TABLE_NAME": b["table"], "TABLE_TYPE": "BASE TABLE"}
                    for b in self.bindings.values()]
        if "INFORMATION_SCHEMA.COLUMNS" in query:
            return [c for b in self.bindings.values() for c in b["columns"]]
        return []

    def test_catalog_exact_coordinates_and_missing_columns(self):
        with patch.object(w, "execute", side_effect=self.catalog_execute):
            self.assertEqual(w.catalog(object(), self.contract, "dbo"), self.bindings)
            with self.assertRaisesRegex(DeploymentError, "coordinate missing"):
                w.catalog(object(), self.contract, "silver")
        altered = copy.deepcopy(self.bindings)
        altered["ZMSF_PLAN"]["columns"] = [c for c in altered["ZMSF_PLAN"]["columns"] if c["COLUMN_NAME"] != "VERSION"]
        with patch.object(w, "execute", side_effect=lambda conn, sql, params=():
                          [c for b in altered.values() for c in b["columns"]] if "COLUMNS" in sql else self.catalog_execute(conn, sql)):
            with self.assertRaisesRegex(DeploymentError, "columns missing"):
                w.catalog(object(), self.contract, "dbo")

    def test_source_projection_is_cross_database_explicit_and_scoped(self):
        statements = []
        with patch.object(w, "execute", side_effect=lambda c, q, params=(): statements.append(q) or []):
            w.source_rows(object(), self.contract, self.bindings, self.config, database="actual-db-name")
        sql = "\n".join(statements)
        self.assertIn("[actual-db-name].[dbo].[I_GLACCOUNTLINEITEMRAWDATA]", sql)
        self.assertIn("s.[_SystemName]='S4M'", sql)
        self.assertIn("s.[COMPANYCODE]='1710'", sql)
        self.assertNotIn("SELECT *", sql)
        self.assertIn("source_types", sql)
        self.assertIn("LEN(s.[CUSTOMER]+'#')-1>10", sql)
        self.assertIn("s.[VERSION]>=10000", sql)

    def test_local_job_gate_before_cloud(self):
        self.write_evidence("Failed")
        with patch.object(w, "ScopedClient") as client:
            with self.assertRaisesRegex(DeploymentError, "checkpoint is not Completed"):
                w.run(TARGET, self.config, self.references, self.metadata, self.directory,
                      self.directory/"catalog.json", RUN, inspect=True)
            client.assert_not_called()

    def mock_client(self, source_stage="gold"):
        client = MagicMock()
        client.target = TARGET
        def item(name, kind):
            stage = next((s for s, prefix in w.PREFIX.items() if name == prefix+TARGET["system_suffix"]), None)
            if stage:
                return {"id": self.jobs[stage]["pipeline_id"]}
            return {"id": "88888888-8888-8888-8888-888888888888" if kind == "Lakehouse"
                    else "99999999-9999-9999-9999-999999999999"}
        client.item.side_effect = item
        def get(method, path):
            self.assertEqual(method, "GET")
            if "/jobs/instances/" in path:
                stage = next(s for s, j in self.jobs.items() if path.endswith(j["job_id"]))
                return 200, {}, {"id": self.jobs[stage]["job_id"], "status": "Completed",
                                 "startTimeUtc": "2026-10-09T08:00:00Z" if stage == "b2s" else "2026-10-09T08:10:00Z",
                                 "endTimeUtc": "2026-10-09T08:09:00Z" if stage == "b2s" else "2026-10-09T08:20:00Z"}
            source = "/lakehouses/" in path
            return 200, {}, {"id": item("", "Lakehouse" if source else "Warehouse")["id"],
                             "displayName": "bps_" + source_stage + "_fea347cc" if source else "MSFlixGold",
                             "properties": {"sqlEndpointProperties": {"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                                                                       "connectionString": "discovered.datawarehouse.fabric.microsoft.com"}}}
        client.request.side_effect = get
        def history(path):
            stage = next(s for s, j in self.jobs.items() if j["pipeline_id"] in path)
            return [{"id": self.jobs[stage]["job_id"], "status": "Completed", "startTimeUtc": "2026-10-09T08:00:00Z"}]
        client.list.side_effect = history
        return client

    def test_live_completed_job_alone_does_not_publish_data(self):
        client = self.mock_client()
        w.live_jobs(client, self.jobs)
        self.rows["I_GLACCOUNTLINEITEMRAWDATA"] = []
        with self.assertRaisesRegex(DeploymentError, "empty"):
            self.qualify()
        client.request.assert_called()

    def test_live_running_or_newer_job_blocks(self):
        client = self.mock_client()
        client.list.return_value = []
        client.list.side_effect = lambda path: [
            {"id": self.jobs["b2s"]["job_id"], "status": "Running", "startTimeUtc": "2026-10-09T08:00:00Z"}]
        with self.assertRaisesRegex(DeploymentError, "active/unknown"):
            w.live_jobs(client, self.jobs)
        client = self.mock_client()
        client.list.side_effect = lambda path: [{"id": "different", "status": "Completed", "startTimeUtc": "2026-10-09T09:00:00Z"}]
        with self.assertRaisesRegex(DeploymentError, "latest"):
            w.live_jobs(client, self.jobs)

    def inspect_patches(self, client):
        return [
            patch.object(w, "ScopedClient", return_value=client),
            patch.object(w, "connect", side_effect=[MagicMock(), MagicMock()]),
            patch.object(w, "execute", return_value=[{"database_name": "actual-native-database"}]),
            patch.object(w, "catalog", return_value=self.bindings),
            patch.object(w, "source_rows", return_value=self.rows),
            patch.object(w, "reference_rows", return_value=(self.customers, self.contents, self.distributors)),
            patch.object(w, "qualify_native_relationships", return_value=self.relationship_proof()),
        ]

    def inspect(self, path):
        patches = self.inspect_patches(self.mock_client())
        for p in patches:
            p.start()
        try:
            return w.run(TARGET, self.config, self.references, self.metadata, self.directory, path, RUN, inspect=True)
        finally:
            for p in reversed(patches):
                p.stop()

    def test_inspect_persists_qualified_catalog_without_writes(self):
        self.write_evidence()
        path = self.directory/"catalog.json"
        with patch.object(w, "publish") as publish:
            result = self.inspect(path)
            publish.assert_not_called()
        self.assertEqual(result["mode"], "source_qualified_only")
        actual = read_json(path)
        self.assertEqual(actual["database"], "actual-native-database")
        self.assertEqual(actual["jobs"], self.jobs)
        self.assertEqual(actual["native_relationships"], self.relationship_proof())
        self.assertEqual(actual["reconciliation"]["receivables"], "12.00")
        with self.assertRaisesRegex(DeploymentError, "already exists"):
            self.inspect(path)

    def test_inspect_silver_records_exact_b2s_lineage_without_warehouse_writes(self):
        self.write_evidence()
        (self.directory / "s2g-job.json").unlink()
        for rows in self.rows.values():
            for row in rows:
                row["NATIVE_DIMENSION_KEY"] = None
        client = self.mock_client("silver")
        patches = self.inspect_patches(client)
        for p in patches:
            p.start()
        path = w.silver_evidence_path(self.directory, self.jobs["b2s"]["job_id"])
        try:
            with patch.object(w, "publish") as publish:
                result = w.inspect_silver(TARGET, self.config, self.references, self.metadata,
                                          self.directory, path, RUN)
                publish.assert_not_called()
            actual = read_json(path)
            self.assertEqual(result["mode"], "silver_qualified_only")
            self.assertFalse(result["warehouse_written"])
            self.assertEqual(actual["source_stage"], "silver")
            self.assertIs(actual["data_verified"], True)
            self.assertEqual(actual["jobs"], {"b2s": self.jobs["b2s"]})
            self.assertEqual(actual["reconciliation"]["net_billings"], "28.00")
            client.item.assert_any_call("bps_silver_fea347cc", "Lakehouse")
            with self.assertRaisesRegex(DeploymentError, "already exists"):
                w.inspect_silver(TARGET, self.config, self.references, self.metadata, self.directory, path, RUN)
        finally:
            for p in reversed(patches):
                p.stop()

    def test_silver_catalog_requires_source_fields_without_gold_dimension_keys(self):
        bindings = copy.deepcopy(self.bindings)
        for binding in bindings.values():
            binding["columns"] = [c for c in binding["columns"] if c["COLUMN_NAME"] != "Key"]
        with patch.object(w, "execute", side_effect=lambda conn, sql, params=():
                          [c for b in bindings.values() for c in b["columns"]] if "COLUMNS" in sql
                          else self.catalog_execute(conn, sql)):
            actual = w.catalog(object(), self.contract, "dbo", source_stage="silver")
            self.assertEqual(set(actual), set(w.TABLES))
            with self.assertRaisesRegex(DeploymentError, "native custom dimension Key missing"):
                w.catalog(object(), self.contract, "dbo")

    def test_apply_rejects_columncount_or_data_drift_and_pins_run(self):
        self.write_evidence()
        path = self.directory/"catalog.json"
        self.inspect(path)
        pinned = read_json(path)
        pinned["catalog_sha256"] = "different"
        path.write_text(json.dumps(pinned), encoding="utf-8")
        patches = self.inspect_patches(self.mock_client())
        for p in patches:
            p.start()
        try:
            with patch.object(w, "publish") as publish:
                with self.assertRaisesRegex(DeploymentError, "COLUMNCOUNT/data changed"):
                    w.run(TARGET, self.config, self.references, self.metadata, self.directory, path, RUN)
                publish.assert_not_called()
        finally:
            for p in reversed(patches):
                p.stop()

    def test_offline_preview_no_clients_and_no_jobs_required(self):
        argv = ["warehouse", "--target", "target.json", "--metadata", str(self.metadata), "--processing-evidence", str(self.directory),
                "--catalog", str(self.directory/"catalog.json"), "--run-id", RUN]
        with patch.object(sys, "argv", argv), patch.object(w, "load_target", return_value=TARGET), \
                patch.object(w, "ScopedClient") as client, patch("sys.stdout", new_callable=io.StringIO) as out:
            w.main()
            client.assert_not_called()
        self.assertEqual(json.loads(out.getvalue())["mode"], "offline_preview")
        self.assertFalse((self.directory/"catalog.json").exists())

    def proof(self):
        return {
            "workspace_id": TARGET["workspace_id"],
            "source_item_id": "88888888-8888-8888-8888-888888888888",
            "source_endpoint_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "database": "actual-native-database", "jobs": self.jobs,
            "input_sha256": self.input_hash, "catalog_sha256": w.signature(self.bindings),
            "data_sha256": w.signature({n: w.fingerprint(r) for n, r in self.rows.items()}),
            "references": self.references,
            "native_relationships": self.relationship_proof(),
        }

    def test_atomic_publish_only_writes_owned_tables_and_reconciles_before_commit(self):
        statements = []
        proof = self.proof()
        def execute(connection, query, params=()):
            statements.append(query)
            if "_relationships'" in query:
                fact = next(n for n in w.CUSTOM_RELATIONSHIPS if "["+n+"] s" in query)
                return [{"joined_rows": len(self.rows[fact]), "invalid_rows": 0}]
            if query.startswith("SELECT run_id,data_sha256"):
                return [{"run_id": RUN, "data_sha256": proof["data_sha256"]}]
            for name, table in w.TABLES.items():
                if query.startswith("SELECT ") and "FROM gold.["+table+"]" in query:
                    return self.rows[name]
            return []
        with patch.object(w, "execute", side_effect=execute), patch.object(w, "target_schema"), \
                patch.object(w, "reference_rows", return_value=(self.customers, self.contents, self.distributors)):
            result = w.publish(object(), self.contract, self.bindings, proof["database"], self.config,
                               RUN, self.totals, self.rows, proof)
        self.assertEqual(result["mode"], "published")
        sql = "\n".join(statements)
        for table in ("dim_customer", "dim_content", "fact_order_line", "publication"):
            self.assertNotIn("DELETE FROM gold."+table, sql)
            self.assertNotIn("INSERT INTO gold."+table, sql)
        self.assertNotIn("XACT_ABORT", sql)
        self.assertIn("BEGIN TRANSACTION", statements[0])
        self.assertIn("BEGIN CATCH", statements[0])
        self.assertIn("THROW;", statements[0])
        self.assertIn("UPDATE gold.sap_writer_guard", sql)
        self.assertIn("ROLLBACK TRANSACTION", sql)
        self.assertIn("source_system='S4M' AND company_scope='1710' AND scenario_id=", sql)
        self.assertIn("FROM [actual-native-database].[dbo].[I_GLACCOUNTLINEITEMRAWDATA]", sql)
        self.assertNotIn("VALUES ", sql)
        self.assertIn("COMMIT TRANSACTION", statements[-1])
        self.assertTrue(any("sap-views" not in q and "CREATE OR ALTER VIEW gold.sap_" in q for q in statements))

    def test_native_surrogate_failure_inside_publication_rolls_back(self):
        statements = []
        def execute(connection, query, params=()):
            statements.append(query)
            if "_relationships'" in query:
                return [{"joined_rows": 4, "invalid_rows": 1}]
            for name, table in w.TABLES.items():
                if query.startswith("SELECT ") and "FROM gold.["+table+"]" in query:
                    return self.rows[name]
            return []
        with patch.object(w, "execute", side_effect=execute), patch.object(w, "target_schema"), \
                patch.object(w, "reference_rows", return_value=(self.customers, self.contents, self.distributors)):
            with self.assertRaisesRegex(DeploymentError, "native surrogate relationship"):
                w.publish(object(), self.contract, self.bindings, "native-database", self.config,
                          RUN, self.totals, self.rows, self.proof())
        self.assertIn("ROLLBACK TRANSACTION", statements[-1])
        self.assertFalse(any("COMMIT TRANSACTION" in q for q in statements))

    def test_failed_target_reconciliation_rolls_back_no_success(self):
        statements = []
        def execute(connection, query, params=()):
            statements.append(query)
            return []
        with patch.object(w, "execute", side_effect=execute), patch.object(w, "target_schema"):
            with self.assertRaisesRegex(DeploymentError, "target values/counts/sums"):
                w.publish(object(), self.contract, self.bindings, "native-database", self.config,
                          RUN, self.totals, self.rows, self.proof())
        self.assertIn("ROLLBACK TRANSACTION", statements[-1])
        self.assertFalse(any("COMMIT TRANSACTION" in q for q in statements))

    def test_snapshot_conflict_fails_without_retry(self):
        with patch.object(w, "execute", side_effect=[DeploymentError("snapshot write conflict 24556"), []]) as exe:
            with self.assertRaisesRegex(DeploymentError, "snapshot write conflict"):
                w.publish(object(), self.contract, self.bindings, "native-database", self.config,
                          RUN, self.totals, self.rows, self.proof())
            self.assertEqual(exe.call_count, 2)
            self.assertIn("ROLLBACK", exe.call_args.args[1])

    def test_odbc17_falls_back_to_declared_official_client_with_scoped_token(self):
        client = self.mock_client()
        client.token.return_value = "scoped-token"
        official = MagicMock()
        odbc = SimpleNamespace(drivers=lambda: ["ODBC Driver 17 for SQL Server"])
        with patch.object(w.importlib, "import_module", side_effect=lambda name: odbc if name == "pyodbc" else official):
            w.connect(client, {"id": "99999999-9999-9999-9999-999999999999",
                               "properties": {"connectionString": "discovered.datawarehouse.fabric.microsoft.com"}})
        client.token.assert_called_once_with("https://database.windows.net")
        args, kwargs = official.connect.call_args
        self.assertIn("Encrypt=yes;TrustServerCertificate=no", args[0])
        self.assertEqual(kwargs["attrs_before"][1256][4:], "scoped-token".encode("utf-16-le"))
        self.assertTrue(kwargs["autocommit"])

    def test_views_keep_cash_vat_and_arap_separate_from_revenue(self):
        sql = (w.SQL_ROOT/"sap-views.sql").read_text(encoding="utf-8")
        self.assertIn("contribution_after_content_cost_only", sql)
        self.assertIn("WHERE g.SOURCELEDGER='0L'", sql)
        self.assertIn("o.CLEARINGDATE IS NULL OR o.CLEARINGDATE>p.as_of", sql)
        monthly = sql.split("-- @batch")[1]
        self.assertNotIn("sap_operational_item", monthly)
        self.assertNotIn("fact_order_line", sql)
        rendered = "\n".join(w.view_batches())
        self.assertNotIn("{{", rendered)
        self.assertIn("g.GLACCOUNT='0040000000'", rendered)
        self.assertIn("g.CHARTOFACCOUNTS='MSFX'", rendered)

    def test_target_schema_refuses_columncount_and_money_type_drift(self):
        types = {
            table: {**w.STAMPS, **{f.name: w.sql_type(f) for f in w.selected_fields(self.contract, name)},
                    "NATIVE_DIMENSION_KEY": "bigint", "NATIVE_UPDATE_TIMESTAMP": "datetime2(6)"}
            for name, table in w.TABLES.items()
        }
        types["sap_publication"] = w.PUBLICATION_TYPES
        types["sap_writer_guard"] = {"resource_name": "varchar(128)", "generation": "bigint"}
        actual = []
        for table, columns in types.items():
            for col, sql in columns.items():
                precision, scale = (map(int, sql[8:-1].split(",")) if sql.startswith("decimal") else (None, None))
                actual.append({"TABLE_NAME": table, "COLUMN_NAME": col, "DATA_TYPE": sql.split("(")[0],
                               "CHARACTER_MAXIMUM_LENGTH": int(sql[8:-1]) if sql.startswith("varchar") else None,
                               "NUMERIC_PRECISION": precision, "NUMERIC_SCALE": scale})
        with patch.object(w, "execute", return_value=actual):
            w.target_schema(object(), self.contract)
        with patch.object(w, "execute", return_value=actual[:-1]):
            with self.assertRaisesRegex(DeploymentError, "COLUMNCOUNT/schema drift"):
                w.target_schema(object(), self.contract)
        altered = copy.deepcopy(actual)
        row = next(r for r in altered if r["TABLE_NAME"] == "sap_publication" and r["COLUMN_NAME"] == "payables")
        row["NUMERIC_SCALE"] = 0
        with patch.object(w, "execute", return_value=altered):
            with self.assertRaisesRegex(DeploymentError, "decimal drift"):
                w.target_schema(object(), self.contract)


if __name__ == "__main__":
    unittest.main()
