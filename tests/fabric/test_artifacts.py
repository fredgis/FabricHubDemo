import ast
import base64
import json
import re
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import nbformat

from fabric.build import ROOT, bind_notebook, notebook, ontology_definition, ontology_texts, persisted_ids
from fabric.contracts import ENTITIES, GOLD_TABLES, LINKS
from fabric.deploy import validate_config, verify_eventhub_region
from fabric.rest import DeploymentError
from fabric.rti import eventstream_definition
from fabric.sql import render_load


def fixture_config():
    cfg = json.loads((ROOT / "config.example.json").read_text())
    # UUIDs below are expressly local test fixtures, never deployment defaults.
    policy = json.loads((ROOT / "target-policy.json").read_text())
    cfg.update(tenant_id=policy["tenant_id"], subscription_id=policy["subscription_id"],
               capacity_resource_id="/subscriptions/" + policy["subscription_id"] + "/resourceGroups/" + policy["resource_group"] + "/providers/Microsoft.Fabric/capacities/" + policy["capacity_name"],
               eventhub_connection_id=str(uuid.UUID(int=3)), eventhub_namespace="fixture.servicebus.windows.net",
               producer_payload_json_mirror=True, run_id="fixture-run",
               event_entity_map={"order.state": "rental", "order.deleted": "rental"},
               delete_event_types=["order.deleted"], commercial_statuses=["created", "expired"],
               sources={"content": {"path": "Files/fixture/catalog.json"},
                        "customer": {"path": "Files/fixture/customers.json"}})
    return cfg


class ArtifactsTests(unittest.TestCase):
    def test_checked_in_notebooks_match_generator_and_jupyter_schema(self):
        for layer in ("Raw", "Silver"):
            actual = json.loads((ROOT / "notebooks" / f"MSFlix{layer}.ipynb").read_text())
            self.assertEqual(actual, notebook(layer))
            nbformat.validate(nbformat.from_dict(actual))
            for cell in actual["cells"]:
                self.assertTrue(all(line.endswith("\n") for line in cell["source"]))
                text = "".join(cell["source"])
                if cell["cell_type"] == "code" and not text.startswith("%%"):
                    ast.parse(text)
            self.assertIn("parameters", actual["cells"][2]["metadata"]["tags"])

    def test_default_lakehouse_binding_is_resolved_not_fabricated(self):
        ws, lh = str(uuid.UUID(int=4)), str(uuid.UUID(int=5))
        definition = bind_notebook("Silver", ws, {"id": lh, "displayName": "MSFlixSilver"}, fixture_config())
        nb = json.loads(base64.b64decode(definition["parts"][0]["payload"]))
        binding = nb["metadata"]["dependencies"]["lakehouse"]
        self.assertEqual(binding["default_lakehouse"], lh)
        self.assertEqual(binding["default_lakehouse_workspace_id"], ws)
        self.assertEqual(definition["format"], "ipynb")

    def test_ontology_is_generation_two_tmdl_not_v1_json(self):
        files = ontology_texts()
        self.assertEqual(json.loads(files[".platform"])["config"]["version"], "2.0")
        self.assertIn("compatibilityLevel: 1000000", files["database.tmdl"])
        self.assertIn("ref namespace default", files["model.tmdl"])
        self.assertNotIn("definition.json", files)
        self.assertFalse(any(path.startswith("EntityTypes/") for path in files))
        for path, text in files.items():
            self.assertEqual((ROOT / "ontology" / "definition" / path).read_text(), text)

    def test_persisted_lineages_unique_and_business_bindings_complete(self):
        ids = persisted_ids()
        self.assertEqual(ids, json.loads((ROOT / "ontology" / "ids.json").read_text()))
        self.assertEqual(len(ids), len(set(ids.values())))
        files = ontology_texts()
        for entity, spec in ENTITIES.items():
            text = files[f"entities/{entity}.tmdl"]
            self.assertIn(f"keyProperty: {spec['key']}", text)
            self.assertIn(f"backingTable: {entity}", text)
            for column in spec["fields"]:
                self.assertIn(f"valueColumn: {entity}.{column}", text)
            backing = files[f"tables/{entity}.tmdl"]
            self.assertIn(f"entityName: {GOLD_TABLES[entity]}", backing)
            self.assertIn("schemaName: gold", backing)
        for name, (left, _, right, _, _) in LINKS.items():
            self.assertIn(f"tables/link_{name}.tmdl", files)
            self.assertIn(f"entityRelationship {name}", files["entityRelationships.tmdl"])
            self.assertIn(f"fromEntity: {left}", files["entityRelationships.tmdl"])
            self.assertIn(f"toEntity: {right}", files["entityRelationships.tmdl"])
            self.assertIn(f"fromRelationship: join_{name}_left", files["entityRelationships.tmdl"])

    def test_ontology_binding_only_discovered_valid_endpoint(self):
        definition = ontology_definition("fixture.datawarehouse.fabric.microsoft.com", str(uuid.UUID(int=6)), "MSFlixBusiness")
        decoded = {p["path"]: base64.b64decode(p["payload"]).decode() for p in definition["parts"]}
        self.assertNotIn("{{", decoded["expressions.tmdl"])
        self.assertIn(str(uuid.UUID(int=6)), decoded["expressions.tmdl"])
        with self.assertRaises(ValueError):
            ontology_definition("evil.example", str(uuid.UUID(int=6)), "MSFlixBusiness")

    def test_supported_eventstream_fanout_and_payload_preservation(self):
        cfg = fixture_config()
        definition = eventstream_definition(cfg, str(uuid.UUID(int=4)),
            {"id": str(uuid.UUID(int=5))}, {"id": str(uuid.UUID(int=6)), "displayName": "MSFlixEvents"})
        doc = json.loads(base64.b64decode(definition["parts"][0]["payload"]))
        self.assertEqual(doc["sources"][0]["type"], "AzureEventHubExtended")
        self.assertEqual(doc["sources"][0]["properties"]["startPosition"], "Earliest")
        self.assertEqual(sum(n["type"] == "DefaultStream" for n in doc["streams"]), 1)
        self.assertEqual(len(doc["destinations"]), 2)
        self.assertIn("payload_json AS payload", doc["operators"][0]["properties"]["query"])
        self.assertEqual(doc["destinations"][0]["properties"]["itemId"], str(uuid.UUID(int=6)))
        self.assertEqual(doc["destinations"][1]["properties"]["schema"], "raw")
        self.assertEqual(doc["destinations"][1]["properties"]["maximumDurationInSeconds"], 60)
        self.assertEqual(doc["destinations"][1]["properties"]["minimumRows"], 1000)
        self.assertFalse(any(n["type"] == "SampleData" for n in doc["sources"]))
        for group in ("sources", "operators", "destinations"):
            for node in doc[group]:
                self.assertRegex(node["name"], r"^[A-Za-z0-9]{3,63}$")
        cfg["producer_payload_json_mirror"] = False
        with self.assertRaisesRegex(DeploymentError, "blocked"):
            eventstream_definition(cfg, "unused", {}, {})

    def test_eventstream_update_preserves_discovered_node_ids(self):
        cfg = fixture_config()
        d = eventstream_definition(cfg, "fixture-ws", {"id": "fixture-raw"}, {"id": "fixture-kql", "displayName": "MSFlixEvents"})
        old = json.loads(base64.b64decode(d["parts"][0]["payload"]))
        for group in ("sources", "operators", "streams", "destinations"):
            for node in old[group]:
                node["id"] = str(uuid.uuid5(uuid.NAMESPACE_OID, node["name"]))
        new = eventstream_definition(cfg, "fixture-ws", {"id": "fixture-raw"}, {"id": "fixture-kql", "displayName": "MSFlixEvents"}, old)
        actual = json.loads(base64.b64decode(new["parts"][0]["payload"]))
        self.assertEqual(old, actual)
        old["sources"].append({"name": "UnownedSource", "type": "CustomEndpoint", "id": "fixture-unowned"})
        with self.assertRaisesRegex(DeploymentError, "unowned"):
            eventstream_definition(cfg, "fixture-ws", {"id": "fixture-raw"}, {"id": "fixture-kql", "displayName": "MSFlixEvents"}, old)

    def test_eventstream_update_accepts_actual_sql_operator_without_id(self):
        cfg = fixture_config()
        definition = eventstream_definition(cfg, "fixture-ws", {"id": "fixture-raw"},
            {"id": "fixture-kql", "displayName": "MSFlixEvents"})
        old = json.loads(base64.b64decode(definition["parts"][0]["payload"]))
        for group in ("sources", "streams", "destinations"):
            for node in old[group]:
                node["id"] = str(uuid.uuid5(uuid.NAMESPACE_OID, node["name"]))
        updated = eventstream_definition(cfg, "fixture-ws", {"id": "fixture-raw"},
            {"id": "fixture-kql", "displayName": "MSFlixEvents"}, old)
        self.assertEqual(old, json.loads(base64.b64decode(updated["parts"][0]["payload"])))
        del old["sources"][0]["id"]
        with self.assertRaisesRegex(DeploymentError, "missing discovered ID"):
            eventstream_definition(cfg, "fixture-ws", {"id": "fixture-raw"},
                {"id": "fixture-kql", "displayName": "MSFlixEvents"}, old)

    def test_onelake_route_retires_only_owned_failed_raw_branch(self):
        cfg = fixture_config()
        definition = eventstream_definition(cfg, "fixture-ws", {"id": "fixture-raw"},
            {"id": "fixture-kql", "displayName": "MSFlixEvents"})
        old = json.loads(base64.b64decode(definition["parts"][0]["payload"]))
        for group in ("sources", "streams", "destinations"):
            for node in old[group]:
                node["id"] = str(uuid.uuid5(uuid.NAMESPACE_OID, node["name"]))
        cfg["rti_ingestion"] = "eventhouse_onelake"
        updated = eventstream_definition(cfg, "fixture-ws", {"id": "fixture-raw"},
            {"id": "fixture-kql", "displayName": "MSFlixEvents"}, old)
        topology = json.loads(base64.b64decode(updated["parts"][0]["payload"]))
        self.assertEqual(topology["operators"], [])
        self.assertEqual([node["name"] for node in topology["destinations"]], ["KqlEnvelopeSink"])
        old["destinations"][1]["properties"]["itemId"] = "unrelated-lakehouse"
        with self.assertRaisesRegex(DeploymentError, "unverified ownership"):
            eventstream_definition(cfg, "fixture-ws", {"id": "fixture-raw"},
                {"id": "fixture-kql", "displayName": "MSFlixEvents"}, old)

    def test_gold_exact_amount_current_grains_and_safe_sql(self):
        cfg = fixture_config()
        query = render_load(cfg, {"displayName": "MSFlixSilver"})
        # Strip comments before checking unrendered markers.
        code = "\n".join(x for x in query.splitlines() if not x.strip().startswith("--"))
        self.assertNotIn("{{", code)
        self.assertNotIn("POWER(", code)
        self.assertIn("r.order_id, 1", code)
        self.assertIn("decimal(23,4)", code)
        self.assertIn("ROLLBACK TRANSACTION", code)
        ddl = (ROOT / "gold" / "ddl.sql").read_text()
        self.assertNotRegex(ddl.lower(), r"\b(nvarchar|money|datetime)\b")
        for dim in ("customer", "content", "offer", "distributor", "territory", "campaign", "date"):
            self.assertIn("gold.dim_" + dim, ddl)
        for fact in ("order_line", "playback_session", "campaign_conversion"):
            self.assertIn("gold.fact_" + fact, ddl)
        self.assertNotIn("SUM(source_sequence)", query)
        self.assertNotIn("ControlCommand", query)

    def test_missing_config_is_explicit_and_no_region_fallback(self):
        cfg = fixture_config()
        validate_config(cfg, "process")
        for field in ("tenant_id", "subscription_id", "capacity_resource_id"):
            missing = {**cfg, field: ""}
            with self.subTest(field=field), self.assertRaisesRegex(DeploymentError, field):
                validate_config(missing, "check")
        with self.assertRaisesRegex(DeploymentError, "authorized"):
            validate_config({**cfg, "region": "westeurope"}, "check")
        with self.assertRaisesRegex(DeploymentError, "Unauthorized tenant_id"):
            validate_config({**cfg, "tenant_id": str(uuid.UUID(int=1))}, "validate")
        with self.assertRaisesRegex(DeploymentError, "other existing tenant capacities"):
            validate_config({**cfg, "capacity_resource_id": cfg["capacity_resource_id"].replace("msflixf16sea", "anothercapacity")}, "check")
        with self.assertRaisesRegex(DeploymentError, "required"):
            validate_config({**cfg, "event_entity_map": {}}, "process")

    def test_no_secrets_and_no_inferred_complete_snapshot_cdc(self):
        cfg = fixture_config()
        cfg["password"] = "fixture-not-a-real-password"
        with self.assertRaisesRegex(DeploymentError, "Secrets"):
            validate_config(cfg, "validate")
        cfg = fixture_config()
        cfg["sources"]["rental"] = {"path": "Files/fixture/orders.json", "snapshot_complete": True}
        with self.assertRaisesRegex(DeploymentError, "watermark"):
            validate_config(cfg, "process")

    def test_sea_namespace_region_and_exact_capacity_are_pinned(self):
        cfg = fixture_config()
        with patch("fabric.deploy.az_json", return_value={"location": "southeastasia"}) as azure:
            self.assertEqual(verify_eventhub_region(cfg)["location"], "southeastasia")
            args = azure.call_args.args
            self.assertIn("rg-msflix-demo-sea", args)
            self.assertIn(cfg["subscription_id"], args)
        with patch("fabric.deploy.az_json", return_value={"location": "germanywestcentral"}):
            with self.assertRaisesRegex(DeploymentError, "temporary Germany"):
                verify_eventhub_region(cfg)

    def test_publication_withdrawn_before_writes(self):
        text = (ROOT / "spark_runtime.py").read_text()
        self.assertLess(text.index("DELETE FROM silver.publication"), text.index("saveAsTable(f\"silver.state_"))
        self.assertIn("left_anti", text)
        self.assertIn("max_input_events", text)
        self.assertIn("Conflicting event_id", text)


if __name__ == "__main__":
    unittest.main()
