"""Offline contracts for native Demo snapshots; no Fabric jobs or live reads."""
import base64
import copy
import hashlib
import json
import re
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError

from fabric.contracts import ENTITIES, GOLD_TABLES, canonical
from fabric.native_references import ORACLE_QUERIES, ORACLE_TABLES
from fabric.spark_runtime import reference_run_id
from services.publisher import source_reload as sr
from sources.salesforce.bps.jobs import STAGES


def guid(number):
    return str(UUID(int=number))


def native_item(number, name, kind="Lakehouse"):
    return {"id": guid(number), "displayName": name, "type": kind,
            "properties": {"sqlEndpointProperties": {
                "id": guid(number + 100), "connectionString": "example.datawarehouse.fabric.microsoft.com"}}}


def oracle_rows():
    return {
        "content": [{"content_key": "film-1", "title": "Source title", "release_date": "2025-01-03",
                     "duration_seconds": 120, "distributor_key": "rights-1", "genre": "Drama",
                     "image_url": "https://example.test/film.jpg", "source_url": "https://example.test/film",
                     "license": "CC0", "attribution": "Offline test fixture"}],
        "offer": [{"offer_key": "offer-1", "content_key": "film-1", "territory": "FR", "currency": "EUR",
                   "transaction_type": "TVOD", "price_minor": 399, "start_window_hours": 48,
                   "play_window_hours": 24}],
        "distributor": [{"distributor_key": "rights-1", "name": "Source distributor"}],
    }


def salesforce_rows():
    return {
        "customer": [{"MSFlix_Key__c": "MSF-C1", "FirstName": "Ada", "LastName": "Test",
                      "MSFlix_Territory__c": "FR", "Id": "contact-native-1"}],
        "campaign": [{"MSFlix_Key__c": "MSF-MKT-1", "Name": "Native campaign",
                      "MSFlix_BudgetMinor__c": Decimal("12345.0"), "MSFlix_Currency__c": "EUR",
                      "MSFlix_Channel__c": "email", "Id": "campaign-native-1"}],
        "consent": [{"MSFlix_Key__c": "MSF-CONSENT-1", "CustomerKey__c": "MSF-C1", "Purpose__c": "marketing",
                     "Channel__c": "email", "Granted__c": True,
                     "EffectiveAt__c": datetime(2025, 1, 3, 9, 30), "Id": "consent-native-1"}],
        "touch": [{"MSFlix_Key__c": "MSF-TOUCH-1", "CustomerKey__c": "MSF-C1", "CampaignKey__c": "MSF-MKT-1",
                   "Channel__c": "email", "TouchType__c": "opened", "OccurredAt__c": datetime(
                       2025, 1, 3, 11, 30, tzinfo=timezone(timedelta(hours=2))),
                   "TrackingToken__c": "trace-1", "Id": "touch-native-1"}],
    }


class Connection:
    def __init__(self, layer):
        self.layer, self.timeout, self.closed = layer, 0, False

    def close(self):
        self.closed = True


class Fabric:
    def __init__(self, runtime):
        self.runtime = runtime
        self.items = list(copy.deepcopy(runtime.cfg["items"]).values())
        self.items += [{"id": guid(4), "displayName": "MSFlixRaw", "type": "Notebook"}]
        self.native = {
            "oracle": native_item(6, "MSFlix_OracleMirror", "MirroredDatabase"),
            "salesforce": native_item(7, "bps_silver_8fbe0076"),
        }
        self.items += list(self.native.values())
        self.items += [native_item(8, "bps_silver_fea347cc")]
        self.items += [{"id": guid(20 + i), "displayName": prefix + sr.BPS_SUFFIX, "type": "DataPipeline"}
                       for i, prefix in enumerate(STAGES.values())]
        self.config = {
            "environment": "test", "workspace_id": guid(10), "raw_lakehouse_id": guid(1),
            "silver_lakehouse_id": guid(2), "run_id": "base-run", "max_input_events": 100,
            "master_reference_entities": [e for entities in sr.SOURCE_ENTITIES.values() for e in entities],
            "event_entity_map": {"OrderChanged": "rental"}, "opaque_live_setting": {"nested": ["keep", "all"]},
            "sources": {
                entity: {"path": f"Files/ingress/native/{entity}.json", "format": "json", "multiline": True,
                         "snapshot_complete": True, "source_kind": sr.SOURCE_KIND[source],
                         "source_item_id": self.native[source]["id"]}
                for source, entities in sr.SOURCE_ENTITIES.items() for entity in entities
            },
        }
        self.calls, self.parameter_source = [], None
        self.binding = {"default_lakehouse": guid(1), "default_lakehouse_workspace_id": guid(10)}

    def list(self, path, skill):
        self.calls.append(("list", path))
        if path != f"/v1/workspaces/{guid(10)}/items":
            raise AssertionError(path)
        return copy.deepcopy(self.items)

    def request(self, method, path, body=None, skill=None):
        self.calls.append((method, path))
        if method != "GET":
            raise AssertionError("prepare must not change control-plane state")
        if path == f"/v1/workspaces/{guid(10)}":
            return 200, {}, {"id": guid(10), "oneLakeEndpoints": {
                "dfsEndpoint": "https://onelake.dfs.fabric.microsoft.com"}}
        for item in self.native.values():
            if path.endswith("/" + item["id"]):
                return 200, {}, copy.deepcopy(item)
        raise AssertionError(path)

    def operation(self, method, path, body=None, skill=None, result_required=False):
        self.calls.append((method, path))
        if path.endswith("/refreshMetadata"):
            return {"value": [{"status": "Success"}]}
        if not path.endswith(f"/notebooks/{guid(4)}/getDefinition?format=ipynb"):
            raise AssertionError("Unexpected operation: " + path)
        assert result_required
        document = {"metadata": {"dependencies": {"lakehouse": self.binding}}, "cells": [{
            "cell_type": "code", "metadata": {"tags": ["parameters"]},
            "source": self.parameter_source or ["config_json = " + repr(json.dumps(self.config)) + "\n",
                                                 'mode = "ingest"\n'],
        }]}
        return {"definition": {"parts": [{"path": "notebook-content.ipynb", "payloadType": "InlineBase64",
                                          "payload": base64.b64encode(json.dumps(document).encode()).decode()}]}}


class Runtime:
    def __init__(self):
        self.cfg = {"environment": "test", "workspace_id": guid(10), "run_id": "base-run", "max_input_events": 100,
                    "items": {"raw": native_item(1, "MSFlixRaw"), "silver": native_item(2, "MSFlixSilver"),
                              "gold": native_item(3, "MSFlixGold", "Warehouse")},
                    "notebooks": {"raw": guid(4), "silver": guid(5)}}
        self.credential = object()
        self.client = Fabric(self)
        self.delta, self.sql = {}, {}

    def analytics(self, layer):
        return Connection(layer)

    def delta_rows(self, item, path, columns, filters=None):
        rows = copy.deepcopy(self.delta.get(path, []))
        if filters:
            rows = [row for row in rows if row[filters[0]] in filters[1]]
        return rows

    def execute(self, connection, query, params=()):
        match = re.search(r"FROM \[([^]]+)\]\.\[([^]]+)\]", query)
        if not match or match[1] != connection.layer:
            raise AssertionError(query)
        return copy.deepcopy(self.sql.get((match[1], match[2]), []))


class MemoryStore:
    def __init__(self):
        self.files = {}
        self.fail_once = None

    def close(self):
        pass

    def read(self, path):
        return self.files.get(path)

    def seal(self, path, data):
        return self.files.setdefault(path, data)

    def put(self, path, data):
        if self.fail_once and path.endswith(self.fail_once):
            self.fail_once = None
            raise OSError("Simulated crash after the capture was sealed")
        if self.seal(path, data) != data:
            raise sr.DeploymentError("Immutable native snapshot conflicts with existing content")


class SourceReloadTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()
        self.reload = sr.SourceReload(self.runtime)
        self.store = MemoryStore()
        self.store_patch = patch.object(sr.SourceReload, "_store", return_value=self.store)
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)

    def prepared(self, source="oracle"):
        cycle = {"kind": "source_reload", "id": guid(49), "command_id": guid(50),
                 "source": source, "events": [], "targets": []}
        cycle.update(self.reload.prepare(cycle))
        return cycle

    def staged(self):
        cycle = self.prepared()
        with patch.object(sr.SourceReload, "_native_rows", return_value=(oracle_rows(), {
                e: {"tables": ORACLE_TABLES[e]} for e in sr.SOURCE_ENTITIES["oracle"]})):
            cycle.update(self.reload.stage(cycle))
        return cycle

    def install_proof(self, cycle):
        manifest = cycle["reference_snapshot"]
        stamp = datetime.fromisoformat(manifest["captured_at"]) + timedelta(seconds=1)
        self.runtime.delta["raw/snapshot_batches"] = []
        self.runtime.delta["raw/reference_snapshots"] = []
        for entity, evidence in manifest["entities"].items():
            self.runtime.delta["raw/snapshot_batches"].append({
                "entity": entity, "run_id": cycle["command_id"], "snapshot_complete": True,
                "row_count": evidence["row_count"], "ingested_at": stamp,
            })
            for value in evidence["rows"]:
                self.runtime.delta["raw/reference_snapshots"].append({
                    "entity": entity, "entity_key": value[ENTITIES[entity]["key"]],
                    "record_id": hashlib.sha256((entity + cycle["command_id"] + canonical(value)).encode()).hexdigest(),
                    "row_json": canonical(value), "run_id": cycle["command_id"],
                    "ingested_at": stamp, "snapshot_complete": True,
                })
            for layer in ("silver", "gold"):
                table = entity if layer == "silver" else GOLD_TABLES[entity]
                self.runtime.sql[layer, table] = [
                    {**value, "run_id": cycle["command_id"], "source_sequence": 0} for value in evidence["rows"]]
                if layer == "gold":
                    self.runtime.delta["gold/" + table] = copy.deepcopy(self.runtime.sql[layer, table])
        for i, layer in enumerate(("silver", "gold"), 1):
            self.runtime.sql[layer, "publication"] = [{"run_id": "base-run", "completed_at": stamp + timedelta(seconds=i)}]
        self.runtime.delta["gold/publication"] = copy.deepcopy(self.runtime.sql["gold", "publication"])

    def test_prepare_allows_source_only_and_is_read_only(self):
        with patch.object(sr.publish, "sql_connect", side_effect=AssertionError("No SQL during prepare")):
            for source in sr.SOURCE_ENTITIES:
                result = self.reload.prepare({"source": source})
                self.assertEqual(result["raw_config"], self.runtime.client.config)
                self.assertIn(source, result["source_items"])
        self.assertFalse(any("refreshMetadata" in path or "/jobs/" in path for _, path in self.runtime.client.calls))
        self.reload._store.assert_not_called()

    def test_prepare_selects_exact_bps_suffix_and_four_pipeline_ids(self):
        result = self.reload.prepare({"source": "salesforce"})
        self.assertEqual(result["source_items"]["salesforce"]["id"], guid(7))
        self.assertEqual(result["source_pipelines"], {stage: guid(20 + i) for i, stage in enumerate(STAGES)})
        self.assertNotIn("source_pipelines", self.reload.prepare({"source": "oracle"}))

    def test_prepare_rejects_duplicate_native_name(self):
        self.runtime.client.items.append(native_item(88, "bps_silver_8fbe0076"))
        with self.assertRaisesRegex(sr.DeploymentError, "Expected one exact"):
            self.reload.prepare({"source": "salesforce"})

    def test_prepare_rejects_foreign_native_workspace(self):
        self.runtime.client.native["oracle"]["workspaceId"] = guid(999)
        with self.assertRaisesRegex(sr.DeploymentError, "cross workspaces"):
            self.prepared()

    def test_prepare_rejects_wrong_deployed_bindings(self):
        for key in ("workspace_id", "raw_lakehouse_id", "silver_lakehouse_id", "run_id", "environment"):
            with self.subTest(key=key):
                original = self.runtime.client.config[key]
                self.runtime.client.config[key] = guid(999)
                with self.assertRaises(sr.DeploymentError):
                    self.prepared()
                self.runtime.client.config[key] = original
        self.runtime.client.binding["default_lakehouse"] = guid(999)
        with self.assertRaises(sr.DeploymentError):
            self.prepared()

    def test_prepare_rejects_executable_or_mutated_parameters(self):
        for value in (
                ["config_json = __import__('os').getcwd()\n", "mode = 'ingest'\n"],
                ["config_json = '{}'\n", "config_json += '{}'\n", "mode = 'ingest'\n"],
                ["config_json = '{}'\n", "mode = 'bootstrap'\n"]):
            with self.subTest(value=value):
                self.runtime.client.parameter_source = value
                with self.assertRaisesRegex(sr.DeploymentError, "safe literal"):
                    self.prepared()

    def test_stage_changes_only_selected_sources_and_keeps_global_run(self):
        cycle = self.staged()
        original = self.runtime.client.config
        actual = cycle["raw_config"]
        self.assertEqual(actual["run_id"], "base-run")
        self.assertEqual({k: v for k, v in actual.items() if k != "sources"},
                         {k: v for k, v in original.items() if k != "sources"})
        for entity in sr.SOURCE_ENTITIES["salesforce"]:
            self.assertEqual(actual["sources"][entity], original["sources"][entity])
        for entity in sr.SOURCE_ENTITIES["oracle"]:
            spec = actual["sources"][entity]
            self.assertEqual(spec["snapshot_run_id"], cycle["command_id"])
            self.assertTrue(spec["snapshot_complete"])
            self.assertEqual(spec["path"], f"Files/ingress/reloads/{guid(50)}/{entity}.json")
            self.assertEqual(json.loads(self.store.files[spec["path"]]), cycle["reference_snapshot"]["entities"][entity]["rows"])

    def test_retry_reuses_sealed_capture_after_partial_entity_publication(self):
        cycle = self.prepared()
        self.store.fail_once = "/offer.json"
        with patch.object(sr.SourceReload, "_native_rows", return_value=(oracle_rows(), {
                e: {"tables": ORACLE_TABLES[e]} for e in sr.SOURCE_ENTITIES["oracle"]})):
            with self.assertRaises(OSError):
                self.reload.stage(cycle)
        self.assertIn(f"Files/ingress/reloads/{guid(50)}/manifest.json", self.store.files)
        with patch.object(sr.SourceReload, "_native_rows", side_effect=AssertionError("Must not reread changed sources")):
            restarted = sr.SourceReload(self.runtime)
            result = restarted.stage(json.loads(json.dumps(cycle)))
            cycle.update(result)
            self.assertEqual(restarted.stage(cycle), result)
        self.assertEqual(result["reference_snapshot"]["entities"]["content"]["rows"][0]["title"], "Source title")

    def test_stage_never_overwrites_conflicting_entity_file(self):
        cycle = self.staged()
        path = cycle["raw_config"]["sources"]["content"]["path"]
        self.store.files[path] = b"different contents"
        with self.assertRaisesRegex(sr.DeploymentError, "Immutable"):
            self.reload.stage(cycle)
        self.assertEqual(self.store.files[path], b"different contents")

    def test_stage_rejects_empty_duplicate_or_oversized_snapshots_before_sealing(self):
        cases = [oracle_rows(), oracle_rows(), oracle_rows()]
        cases[0]["content"] = []
        cases[1]["content"] *= 2
        cases[2]["content"] = [{**cases[2]["content"][0], "content_key": "film-" + str(i)} for i in range(101)]
        for rows in cases:
            with self.subTest(rows=len(rows["content"])):
                with patch.object(sr.SourceReload, "_native_rows", return_value=(rows, {
                        e: {"tables": ORACLE_TABLES[e]} for e in sr.SOURCE_ENTITIES["oracle"]})):
                    with self.assertRaises(sr.DeploymentError):
                        self.reload.stage(self.prepared())
                self.assertEqual(self.store.files, {})

    def test_manifest_rejects_foreign_binding_tampered_digest_and_orphan(self):
        cycle = self.staged()
        for key, bad_value in (("workspace_id", guid(999)), ("source", "salesforce"), ("command_id", "other")):
            with self.subTest(key=key):
                manifest = copy.deepcopy(cycle["reference_snapshot"])
                manifest[key] = bad_value
                with self.assertRaises(sr.DeploymentError):
                    self.reload._check_manifest(cycle, manifest)
        manifest = copy.deepcopy(cycle["reference_snapshot"])
        manifest["entities"]["content"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(sr.DeploymentError, "corrupt"):
            self.reload._check_manifest(cycle, manifest)
        rows = oracle_rows()
        rows["offer"][0]["content_key"] = "missing"
        manifest = self.reload._manifest(cycle, rows, {e: {} for e in rows})
        with self.assertRaisesRegex(sr.DeploymentError, "orphan"):
            self.reload._check_manifest(cycle, manifest)

    def test_oracle_queries_are_shared_and_keep_multi_distributor_guard(self):
        from scripts.stage_native_references import ORACLE_QUERIES as script_queries
        self.assertIs(script_queries, ORACLE_QUERIES)
        self.assertIn("COUNT(DISTINCT DISTRIBUTOR_ID)>1", ORACLE_QUERIES["content"])
        self.assertIn("THROW 51020", ORACLE_QUERIES["content"])
        connection = Connection("native")
        def query(conn, sql, params=()):
            self.assertIs(conn, connection)
            entity = next(e for e, text in ORACLE_QUERIES.items() if text == sql)
            return oracle_rows()[entity]
        with patch.object(sr.publish, "sql_connect", return_value=connection) as connect, patch.object(sr, "execute", side_effect=query):
            rows, trace = self.reload._native_rows("oracle", self.runtime.client.native["oracle"])
        self.assertTrue(connection.closed)
        self.assertIs(connect.call_args.args[2], self.runtime.credential)
        self.assertEqual(rows["offer"][0]["price_minor"], 399)
        self.assertEqual(trace["content"]["tables"], ORACLE_TABLES["content"])
        self.assertFalse(any("refreshMetadata" in path for _, path in self.runtime.client.calls))

    def test_bps_reads_ranked_scoped_silver_and_normalizes_datetime_decimal(self):
        native = salesforce_rows()
        queries = []
        connection = Connection("native")
        def query(conn, sql, params=()):
            if "INFORMATION_SCHEMA.TABLES" in sql:
                entity = next(e for e, spec in sr.MAPPINGS.items() if spec["object"].lower() == params[0])
                return [{"TABLE_SCHEMA": "dbo", "TABLE_NAME": sr.MAPPINGS[entity]["object"]}]
            if "INFORMATION_SCHEMA.COLUMNS" in sql:
                entity = next(e for e, spec in sr.MAPPINGS.items() if spec["object"] == params[1])
                names = list(dict.fromkeys(sr.MAPPINGS[entity]["fields"].values()))
                return [{"COLUMN_NAME": name} for name in names + ["IsDeleted", "SystemModstamp", "_SystemName", "_UpdatedTimeStamp"]]
            entity = next(e for e, spec in sr.MAPPINGS.items() if f"FROM [dbo].[{spec['object']}]" in sql)
            queries.append(sql)
            self.assertEqual(params, ("MSFlixSF",))
            self.assertLess(sql.index("ROW_NUMBER()"), sql.index("WHERE __latest=1"))
            self.assertIn("ORDER BY [SystemModstamp] DESC,[_UpdatedTimeStamp] DESC", sql)
            self.assertIn("WHERE [_SystemName]=?", sql)
            self.assertIn("AND [IsDeleted]=0", sql)
            return native[entity]
        with patch.object(sr.publish, "sql_connect", return_value=connection), patch.object(sr, "execute", side_effect=query):
            rows, traces = self.reload._native_rows("salesforce", self.runtime.client.native["salesforce"])
        self.assertEqual(len(queries), 4)
        self.assertEqual(rows["campaign"][0]["budget_minor"], 12345)
        self.assertIs(type(rows["campaign"][0]["budget_minor"]), int)
        self.assertEqual(rows["consent"][0]["effective_at"], "2025-01-03T09:30:00.000000Z")
        self.assertEqual(rows["touch"][0]["occurred_at"], "2025-01-03T09:30:00.000000Z")
        self.assertEqual(rows["customer"][0]["source_customer_id"], "contact-native-1")
        self.assertTrue(all(t["processed_silver"] and t["system_scoped"] for t in traces.values()))
        self.assertEqual(sum("refreshMetadata" in path for _, path in self.runtime.client.calls), 1)
        with self.assertRaisesRegex(sr.DeploymentError, "exact integer"):
            sr.normalize_row({"MSFlix_BudgetMinor__c": Decimal("12.5")})

    def test_empty_event_targets_do_not_prove_a_native_reload(self):
        cycle = self.staged()
        for layer in ("raw", "silver", "gold", "gold_onelake"):
            with self.subTest(layer=layer):
                self.assertFalse(self.reload.verify(cycle, layer))

    def test_all_layers_require_actual_exact_snapshot_values(self):
        cycle = self.staged()
        self.install_proof(cycle)
        with patch.object(sr, "execute", side_effect=self.runtime.execute):
            for layer in ("raw", "silver", "gold", "gold_onelake"):
                with self.subTest(layer=layer):
                    self.assertTrue(sr.SourceReload(self.runtime).verify(cycle, layer))

    def test_salesforce_serving_proof_requires_new_consent_and_touch_run_ids(self):
        cycle = self.prepared("salesforce")
        native = salesforce_rows()
        rows = {entity: sr.conform_salesforce(entity, json.loads(json.dumps(
            [sr.normalize_row(row) for row in values], default=sr.json_native)))
            for entity, values in native.items()}
        with patch.object(sr.SourceReload, "_native_rows", return_value=(rows, {e: {"processed_silver": True} for e in rows})):
            cycle.update(self.reload.stage(cycle))
        self.install_proof(cycle)
        with patch.object(sr, "execute", side_effect=self.runtime.execute):
            for layer in ("raw", "silver", "gold", "gold_onelake"):
                self.assertTrue(self.reload.verify(cycle, layer))
            self.runtime.sql["gold", "fact_customer_consent"][0]["run_id"] = "prior-snapshot"
            self.assertFalse(self.reload.verify(cycle, "gold"))
            self.install_proof(cycle)
            self.runtime.delta["gold/fact_campaign_touch"][0]["run_id"] = "prior-snapshot"
            self.assertFalse(self.reload.verify(cycle, "gold_onelake"))

    def test_raw_duplicate_batch_or_changed_digest_is_unsafe(self):
        cycle = self.staged()
        self.install_proof(cycle)
        self.runtime.delta["raw/snapshot_batches"].append(copy.deepcopy(self.runtime.delta["raw/snapshot_batches"][0]))
        with self.assertRaisesRegex(sr.DeploymentError, "duplicate"):
            self.reload.verify(cycle, "raw")
        self.install_proof(cycle)
        row = next(r for r in self.runtime.delta["raw/reference_snapshots"] if r["entity"] == "content")
        value = json.loads(row["row_json"])
        row["row_json"] = canonical({**value, "title": "Wrong value, same key and count"})
        with self.assertRaisesRegex(sr.DeploymentError, "digest"):
            self.reload.verify(cycle, "raw")

    def test_raw_partial_visibility_returns_false(self):
        cycle = self.staged()
        self.install_proof(cycle)
        self.runtime.delta["raw/reference_snapshots"].pop()
        self.assertFalse(self.reload.verify(cycle, "raw"))
        self.install_proof(cycle)
        self.runtime.delta["raw/snapshot_batches"][0]["snapshot_complete"] = False
        self.assertFalse(self.reload.verify(cycle, "raw"))

    def test_silver_stale_run_and_gold_same_count_wrong_values_return_false(self):
        cycle = self.staged()
        self.install_proof(cycle)
        with patch.object(sr, "execute", side_effect=self.runtime.execute):
            self.runtime.sql["silver", "content"][0]["run_id"] = "base-run"
            self.assertFalse(self.reload.verify(cycle, "silver"))
            self.install_proof(cycle)
            self.runtime.sql["gold", "dim_content"][0]["title"] = "Prior source title"
            self.assertFalse(self.reload.verify(cycle, "gold"))
            self.install_proof(cycle)
            self.runtime.sql["silver", "content"].append({**self.runtime.sql["silver", "content"][0], "content_key": "deleted-native-key"})
            self.assertFalse(self.reload.verify(cycle, "silver"))

    def test_publication_and_gold_onelake_lag_are_not_success(self):
        cycle = self.staged()
        self.install_proof(cycle)
        with patch.object(sr, "execute", side_effect=self.runtime.execute):
            self.runtime.sql["gold", "publication"][0]["completed_at"] = datetime(2000, 1, 1)
            self.assertFalse(self.reload.verify(cycle, "gold"))
            self.install_proof(cycle)
            self.runtime.delta["gold/dim_offer"][0]["price_minor"] = 299
            self.assertFalse(self.reload.verify(cycle, "gold_onelake"))
            self.install_proof(cycle)
            self.runtime.delta["gold/publication"][0]["completed_at"] -= timedelta(seconds=1)
            self.assertFalse(self.reload.verify(cycle, "gold_onelake"))

    def test_serving_decimal_date_values_compare_canonically(self):
        cycle = self.staged()
        self.install_proof(cycle)
        self.runtime.sql["gold", "dim_offer"][0]["price_minor"] = Decimal("399")
        self.runtime.sql["gold", "dim_content"][0]["release_date"] = datetime(2025, 1, 3).date()
        with patch.object(sr, "execute", side_effect=self.runtime.execute):
            self.assertTrue(self.reload.verify(cycle, "gold"))

    def test_duplicate_serving_keys_and_auth_errors_are_not_hidden_as_lag(self):
        cycle = self.staged()
        self.install_proof(cycle)
        self.runtime.sql["silver", "content"] *= 2
        with patch.object(sr, "execute", side_effect=self.runtime.execute):
            with self.assertRaisesRegex(sr.DeploymentError, "duplicate natural keys"):
                self.reload.verify(cycle, "silver")
        with patch.object(sr, "execute", side_effect=sr.DeploymentError("SQL access denied")):
            with self.assertRaisesRegex(sr.DeploymentError, "access denied"):
                self.reload.verify(cycle, "silver")

    def test_unsafe_source_paths_hosts_and_command_ids_are_rejected(self):
        for host in ("https://onelake.dfs.fabric.microsoft.com.evil.test", "http://onelake.dfs.fabric.microsoft.com",
                     "https://u@onelake.dfs.fabric.microsoft.com", "https://onelake.dfs.fabric.microsoft.com:443",
                     "https://onelake.dfs.fabric.microsoft.com/foreign", "https://onelake.dfs.fabric.microsoft.com?secret=x"):
            with self.subTest(host=host), self.assertRaises(sr.DeploymentError):
                sr._dfs_endpoint(host)
        for command in (None, "../escape", "a/b", "a\\b", "x" * 129, ""):
            with self.subTest(command=command), self.assertRaises(sr.DeploymentError):
                self.reload.stage({**self.prepared(), "command_id": command})
        item = copy.deepcopy(self.runtime.client.native["oracle"])
        item["properties"]["sqlEndpointProperties"]["connectionString"] = "evil.test"
        with self.assertRaisesRegex(sr.DeploymentError, "approved Fabric SQL"):
            self.reload._sql_binding(item)

    def test_reference_run_id_override_does_not_change_event_run_id(self):
        cfg = {"run_id": "base-run"}
        self.assertEqual(reference_run_id(cfg, {}), "base-run")
        self.assertEqual(reference_run_id(cfg, {"snapshot_run_id": guid(50)}), guid(50))
        self.assertEqual(cfg, {"run_id": "base-run"})
        for value in (None, False, "", "bad/slash", "x" * 129):
            with self.subTest(value=value), self.assertRaises(ValueError):
                reference_run_id(cfg, {"snapshot_run_id": value})


class FakeFile:
    def __init__(self, service, path):
        self.service, self.path = service, path

    def get_file_properties(self):
        if self.path not in self.service.files:
            raise ResourceNotFoundError("Missing")
        return SimpleNamespace(size=len(self.service.files[self.path]), etag="etag")

    def download_file(self, **kwargs):
        assert kwargs["etag"] == "etag" and kwargs["match_condition"] == MatchConditions.IfNotModified
        return SimpleNamespace(readall=lambda: self.service.files[self.path])

    def upload_data(self, data, **kwargs):
        assert kwargs["overwrite"] is False
        self.service.files[self.path] = data[:-1] if self.service.truncate else data

    def rename_file(self, target, **kwargs):
        assert kwargs["etag"] == "*" and kwargs["match_condition"] == MatchConditions.IfMissing
        assert target.startswith(guid(10) + "/")
        path = target.split("/", 1)[1]
        if path in self.service.files:
            raise ResourceExistsError("Already sealed")
        self.service.files[path] = self.service.files.pop(self.path)


class FakeStorage:
    def __init__(self):
        self.files, self.truncate, self.directories = {}, False, []

    def get_file_system_client(self, workspace):
        assert workspace == guid(10)
        return self

    def get_file_client(self, path):
        assert path.startswith(guid(1) + "/Files/ingress/reloads/")
        return FakeFile(self, path)

    def get_directory_client(self, path):
        def create_directory(**kwargs):
            assert kwargs["match_condition"] == MatchConditions.IfMissing
            self.directories.append(path)
        return SimpleNamespace(create_directory=create_directory)

    def close(self):
        pass


class ImmutableOneLakeTests(unittest.TestCase):
    def setUp(self):
        self.service = FakeStorage()
        self.constructor = patch.object(sr, "DataLakeServiceClient", return_value=self.service)
        self.mock_constructor = self.constructor.start()
        self.addCleanup(self.constructor.stop)
        self.credential = object()
        self.store = sr._ImmutableOneLake(self.credential, "https://onelake.dfs.fabric.microsoft.com",
                                         guid(10), guid(1), guid(50))
        self.path = f"Files/ingress/reloads/{guid(50)}/content.json"

    def test_atomic_no_replace_rename_and_injected_credential(self):
        self.store.put(self.path, b"complete snapshot")
        self.assertEqual(self.store.read(self.path), b"complete snapshot")
        self.store.put(self.path, b"complete snapshot")
        with self.assertRaisesRegex(sr.DeploymentError, "conflicts"):
            self.store.put(self.path, b"changed on retry")
        self.assertEqual(len(self.service.files), 1)
        kwargs = self.mock_constructor.call_args.kwargs
        self.assertIs(kwargs["credential"], self.credential)
        self.assertFalse(kwargs["permit_redirects"])
        self.assertEqual(kwargs["account_url"], "https://onelake.dfs.fabric.microsoft.com")

    def test_real_sdk_disables_both_dfs_and_blob_redirects_without_io(self):
        from azure.storage.filedatalake import DataLakeServiceClient
        credential = SimpleNamespace(get_token=lambda *args, **kwargs: self.fail("No credential acquisition"))
        with patch.object(sr, "DataLakeServiceClient", DataLakeServiceClient):
            store = sr._ImmutableOneLake(credential, "https://onelake.dfs.fabric.microsoft.com", guid(10), guid(1), guid(50))
        try:
            file = store.fs.get_file_client(guid(1) + "/" + self.path)
            for client in (file, file._blob_client):
                policies = [getattr(p, "_policy", p) for p in client._pipeline._impl_policies]
                redirects = [p for p in policies if type(p).__name__ == "RedirectPolicy"]
                self.assertEqual(len(redirects), 1)
                self.assertFalse(redirects[0].allow)
        finally:
            store.close()

    def test_partial_upload_cannot_publish_a_final_file(self):
        self.service.truncate = True
        with self.assertRaisesRegex(sr.DeploymentError, "preserve its bytes"):
            self.store.put(self.path, b"full payload")
        self.assertIsNone(self.store.read(self.path))
        self.assertTrue(all(path.endswith(".pending") for path in self.service.files))

    def test_storage_rejects_escape_and_oversized_download(self):
        for path in ("../escape.json", "Files/elsewhere/content.json", self.path + "/../escape.json"):
            with self.subTest(path=path), self.assertRaises(sr.DeploymentError):
                self.store.read(path)
        with patch.object(FakeFile, "get_file_properties", return_value=SimpleNamespace(size=sr.MAX_BYTES + 1, etag="x")):
            with self.assertRaisesRegex(sr.DeploymentError, "size bound"):
                self.store.read(self.path)


if __name__ == "__main__":
    unittest.main()
