"""Bounded entrypoint. Every stage is independently rerunnable, never a fake deploy."""
from __future__ import annotations

import argparse
import base64
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fabric.build import ROOT, bind_notebook, ontology_definition, preserve_ontology_identity
from fabric.connections import qualify_eventhub_connection
from fabric.contracts import ENTITIES, LINKS, utc_timestamp
from fabric.rest import DeploymentError, FabricClient, az_json
from fabric.rti import deploy_kql, eventstream_definition, kusto
from fabric.sql import connect, deploy_gold, execute, validate_gold, validate_silver

STAGES = ("validate", "check", "foundation", "notebooks", "bootstrap", "rti",
          "process", "gold", "ontology", "reconcile")
COLLECTIONS = {"raw": "lakehouses", "silver": "lakehouses", "gold": "warehouses",
               "eventhouse": "eventhouses", "kql": "kqlDatabases",
               "eventstream": "eventstreams", "ontology": "ontologies"}
OWNER = "MSFlix analytics managed"


def load_target_policy():
    try:
        return json.loads((ROOT / "target-policy.json").read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DeploymentError(
            "Missing private fabric/target-policy.json; copy target-policy.example.json "
            "and fill the independently approved target before running deployment tools"
        ) from exc


def validate_config(cfg, stage):
    if cfg.get("environment") not in ("dev", "test", "prod"):
        raise DeploymentError("environment must explicitly be dev, test or prod")
    policy = load_target_policy()
    for field in ("region", "capacity_sku", "workspace_name"):
        if cfg.get(field) != policy[field]:
            raise DeploymentError("Only one MSFlix workspace on the externally approved F16 region is authorized")
    for field in ("tenant_id", "subscription_id"):
        try:
            uuid.UUID(cfg[field])
        except (ValueError, KeyError, TypeError) as exc:
            raise DeploymentError(f"Missing/invalid required config: {field}") from exc
    for field in ("tenant_id", "subscription_id", "region", "capacity_sku", "workspace_name"):
        if cfg[field].lower() != policy[field].lower():
            raise DeploymentError(f"Unauthorized {field}; only the externally declared MSFlix target is approved")
    for key in COLLECTIONS:
        name = cfg.get("names", {}).get(key)
        if not name or not re.fullmatch("MSFlix[A-Za-z0-9]{1,90}", name):
            raise DeploymentError(f"names.{key} must be an explicit MSFlix alphanumeric name")
    if cfg.get("workspace_id"):
        uuid.UUID(cfg["workspace_id"])
    if cfg.get("rti_ingestion", "eventstream_fanout") not in ("eventstream_fanout", "eventhouse_onelake"):
        raise DeploymentError("Unsupported RTI ingestion route")
    if type(cfg.get("minimum_rti_events", 0)) is not int or cfg.get("minimum_rti_events", 0) < 0:
        raise DeploymentError("minimum_rti_events must be a nonnegative integer")
    if stage != "validate":
        resource = cfg.get("capacity_resource_id", "")
        expected = "/subscriptions/" + cfg["subscription_id"] + "/"
        if not resource.lower().startswith(expected.lower()) or "/providers/microsoft.fabric/capacities/" not in resource.lower():
            raise DeploymentError("capacity_resource_id required: approved F16 ARM resource only; capacity/workspace provisioning is an external gate")
        approved_resource = (
            f"/subscriptions/{policy['subscription_id']}/resourceGroups/{policy['resource_group']}"
            f"/providers/Microsoft.Fabric/capacities/{policy['capacity_name']}")
        if resource.lower() != approved_resource.lower():
            raise DeploymentError("Unauthorized capacity_resource_id; do not use other existing tenant capacities")
    if stage in ("rti", "reconcile"):
        for field in ("eventhub_connection_id",):
            try:
                uuid.UUID(cfg[field])
            except (ValueError, KeyError, TypeError) as exc:
                raise DeploymentError(f"Missing/invalid required RTI config: {field}") from exc
        if cfg.get("eventhub_name") != "msflix-events" or not cfg.get("eventhub_namespace") or not cfg.get("consumer_group"):
            raise DeploymentError("Real msflix-events namespace/consumer_group required")
        if stage == "rti" and cfg.get("producer_payload_json_mirror") is not True:
            raise DeploymentError("RTI blocked until producer emits verified payload_json mirror")
    if stage in ("rti", "process", "gold", "ontology", "reconcile"):
        if not cfg.get("run_id") or len(cfg["run_id"]) > 128:
            raise DeploymentError("An explicit bounded run_id is required")
        event_map = cfg.get("event_entity_map", {})
        if not event_map or any(v not in ENTITIES for v in event_map.values()):
            raise DeploymentError("event_entity_map required: parent must supply exact event_type -> entity map; no guessed names")
        if any(name not in event_map for name in cfg.get("delete_event_types", [])):
            raise DeploymentError("delete_event_types must exist in event_entity_map")
        for name, source in cfg.get("sources", {}).items():
            if name not in ENTITIES or not isinstance(source, dict) or not source.get("path"):
                raise DeploymentError(f"Invalid sources.{name}; stage real source files/mirror table paths")
            if source.get("snapshot_complete") and name in event_map.values() and name not in cfg.get("master_reference_entities", []):
                raise DeploymentError("Complete reference snapshots and sequenced CDC cannot both own an entity without an explicit source watermark")
        for entity in cfg.get("master_reference_entities", []):
            source = cfg.get("sources", {}).get(entity, {})
            if entity not in ENTITIES or not source.get("snapshot_complete") or source.get("source_kind") not in ("OracleMirror", "BPS"):
                raise DeploymentError("Master references require a complete native Oracle/BPS source snapshot")
        if cfg.get("max_input_events", 100000) <= 0 or cfg.get("max_quarantine_records", 0) < 0:
            raise DeploymentError("Input/quarantine bounds must be nonnegative")
        if not cfg.get("currency_exponents"):
            raise DeploymentError("currency_exponents must be supplied")
        if any(not re.fullmatch("[A-Z]{3}", code) or type(exponent) is not int or not 0 <= exponent <= 4
               for code, exponent in cfg["currency_exponents"].items()):
            raise DeploymentError("currency_exponents must map ISO codes to integer exponents 0..4")
    if stage == "process" and not all(x in cfg.get("sources", {}) for x in ("content", "customer")):
        raise DeploymentError("Real catalog and CRM ingress paths required for process")
    if stage == "gold" and not cfg.get("commercial_statuses"):
        raise DeploymentError("Parent must supply statuses that count booked commercial orders")
    # Credential material must never be put in definitions or checked-in config.
    def inspect(value):
        if isinstance(value, dict):
            for name, child in value.items():
                if re.search(r"(password|secret|access_token|sas_token|connection_string)", name, re.I):
                    raise DeploymentError("Secrets/connection strings are prohibited in config")
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)
        elif isinstance(value, str) and re.search(r"(?i)([?&]sig=|SharedAccessKey=|Bearer )", value):
            raise DeploymentError("Credential material prohibited in configuration")
    inspect(cfg)
    return cfg


def preflight(cfg, client):
    account = az_json("account", "show", "--subscription", cfg["subscription_id"])
    if account["tenantId"].lower() != cfg["tenant_id"].lower() or account["id"].lower() != cfg["subscription_id"].lower():
        raise DeploymentError("Cached Azure account differs from explicit approved tenant/subscription")
    capacity = az_json("resource", "show", "--ids", cfg["capacity_resource_id"])
    if (capacity["location"].lower().replace(" ", "") != cfg["region"] or capacity.get("sku", {}).get("name") != "F16"
            or not any(str(v).lower() == "msflix" for v in capacity.get("tags", {}).values())):
        raise DeploymentError("Capacity must be the approved tagged MSFlix F16 in the configured authorized region")
    if cfg.get("workspace_id"):
        workspace = client.request("GET", "/v1/workspaces/" + cfg["workspace_id"])[2]
    else:
        matches = [r for r in client.list("/v1/workspaces") if r["displayName"] == "MSFlix"]
        if len(matches) != 1:
            raise DeploymentError("MSFlix workspace does not exist or is ambiguous; approved F16 provisioning remains unverified")
        workspace = client.request("GET", "/v1/workspaces/" + matches[0]["id"])[2]
    if workspace["displayName"] != "MSFlix":
        raise DeploymentError("Supplied workspace_id is not the authorized MSFlix workspace")
    capacities = client.list("/v1/capacities")
    capacity_name = cfg["capacity_resource_id"].split("/")[-1]
    allowed = [r for r in capacities if r["displayName"].lower() == capacity_name.lower()
               and r["sku"] == "F16" and r.get("state", "").lower() == "active"
               and r.get("region", "").lower().replace(" ", "") == cfg["region"]]
    if len(allowed) != 1 or workspace.get("capacityId") != allowed[0]["id"]:
        raise DeploymentError("Workspace not assigned to the approved active F16; no other tenant capacity is allowed")
    return workspace


def resolve(cfg, client, ws, key, required=True):
    collection = COLLECTIONS[key]
    skill = "eventhouse-cli" if key in ("eventhouse", "kql") else (
        "eventstream-cli" if key == "eventstream" else (
            "fabriciq-ontology-cli" if key == "ontology" else "spark-cli"))
    rows = [r for r in client.list(f"/v1/workspaces/{ws}/{collection}", skill) if r["displayName"] == cfg["names"][key]]
    if len(rows) == 0 and not required:
        return None
    if len(rows) != 1:
        raise DeploymentError(f"Missing/ambiguous {key}; run its prerequisite stage")
    item = client.request("GET", f"/v1/workspaces/{ws}/{collection}/{rows[0]['id']}", skill=skill)[2]
    if not item.get("description", "").startswith(OWNER):
        raise DeploymentError(f"Refusing mutation/reuse of unmarked {key}; parent must qualify ownership")
    return item


def verify_eventhub_region(cfg):
    """Qualify the new regional namespace, never the temporary Germany ingress."""
    policy = load_target_policy()
    hostname = cfg["eventhub_namespace"].lower()
    if not re.fullmatch(r"[a-z0-9-]+\.servicebus\.windows\.net", hostname):
        raise DeploymentError("eventhub_namespace must be the actual fully qualified Azure namespace")
    namespace = az_json("eventhubs", "namespace", "show",
        "--subscription", cfg["subscription_id"],
        "--resource-group", policy["resource_group"], "--name", hostname.split(".")[0])
    if namespace.get("location", "").lower().replace(" ", "") != cfg["region"]:
        raise DeploymentError("Event Hubs namespace is not in approved Southeast Asia; temporary Germany ingress prohibited")
    return namespace


def ensure(cfg, client, ws, key, skill, extra=None):
    current = resolve(cfg, client, ws, key, required=False)
    if current:
        return current
    return client.ensure_item(ws, COLLECTIONS[key], cfg["names"][key], skill,
        {"description": OWNER + ": " + key, **(extra or {})})


def foundation(cfg, client, ws):
    items = {}
    for key in ("raw", "silver"):
        items[key] = ensure(cfg, client, ws, key, "spark-cli",
                            {"creationPayload": {"enableSchemas": True}})
    items["gold"] = ensure(cfg, client, ws, "gold", "sqldw-cli")
    items["eventhouse"] = ensure(cfg, client, ws, "eventhouse", "eventhouse-cli")
    items["kql"] = ensure(cfg, client, ws, "kql", "eventhouse-cli", {
        "creationPayload": {"databaseType": "ReadWrite", "parentEventhouseItemId": items["eventhouse"]["id"]}})
    if items["kql"].get("properties", {}).get("parentEventhouseItemId") != items["eventhouse"]["id"]:
        raise DeploymentError("KQL database parent is not the approved MSFlix Eventhouse")
    return {key: value["id"] for key, value in items.items()}


def deploy_notebook(cfg, client, ws, layer, mode="ingest"):
    raw, silver = resolve(cfg, client, ws, "raw"), resolve(cfg, client, ws, "silver")
    runtime_cfg = {**cfg, "raw_lakehouse_id": raw["id"]}
    if cfg.get("rti_ingestion") == "eventhouse_onelake":
        runtime_cfg["eventhouse_onelake_item_id"] = resolve(cfg, client, ws, "kql")["id"]
    definition = bind_notebook(layer, ws, raw if layer == "Raw" else silver, runtime_cfg)
    # Defaults are persisted in the notebook. No undocumented RunNotebook
    # parameter wire shape is needed for the empty-body job request.
    doc = json.loads(base64.b64decode(definition["parts"][0]["payload"]))
    doc["cells"][2]["source"][1] = "mode = " + repr(mode) + "\n"
    from fabric.build import part
    definition["parts"] = [part("notebook-content.ipynb", json.dumps(doc))]
    name = "MSFlix" + layer + "Processing"
    path = f"/v1/workspaces/{ws}/notebooks"
    existing = [n for n in client.list(path) if n["displayName"] == name]
    if len(existing) > 1:
        raise DeploymentError("Ambiguous processing notebook")
    if existing:
        item = client.request("GET", path + "/" + existing[0]["id"])[2]
        if not item.get("description", "").startswith(OWNER):
            raise DeploymentError("Refusing overwrite of unmarked processing notebook")
        jobs = client.list(f"/v1/workspaces/{ws}/items/{item['id']}/jobs/instances")
        if any(job.get("status") in ("NotStarted", "InProgress") for job in jobs):
            raise DeploymentError("Processing notebook has an active job; definition overwrite blocked")
        client.operation("POST", path + "/" + item["id"] + "/updateDefinition",
                         {"definition": definition})
    else:
        item = client.ensure_item(ws, "notebooks", name, "spark-cli",
            {"description": OWNER + ": " + layer, "definition": definition})
    return item


def run_notebook(client, ws, item):
    job_base = f"/v1/workspaces/{ws}/items/{item['id']}/jobs/instances"
    now = datetime.now(timezone.utc)
    recent = []
    for job in client.list(job_base):
        start = job.get("startTimeUtc")
        # Fabric's startTimeUtc can omit the suffix; this platform field is explicitly UTC.
        parsed_start = datetime.fromisoformat(start.replace("Z", "+00:00")) if start else None
        if parsed_start and parsed_start.tzinfo is None:
            parsed_start = parsed_start.replace(tzinfo=timezone.utc)
        if parsed_start and (now - parsed_start).total_seconds() < 300:
            recent.append(job)
    if recent:
        raise DeploymentError(
            f"Recent notebook job exists ({recent[0]['id']}); inspect it and wait five minutes. No duplicate run submitted.")
    status, headers, _ = client.request(
        "POST", f"/v1/workspaces/{ws}/items/{item['id']}/jobs/RunNotebook/instances", {})
    location = headers.get("location")
    if status != 202 or not location or urlparse(location).netloc != "api.fabric.microsoft.com":
        raise DeploymentError("Notebook submission outcome ambiguous; inspect job history, do not resubmit")
    # Capture the instance immediately, separately from control-plane LROs.
    job_id = location.rstrip("/").split("/")[-1]
    client.evidence.append({"notebook_id": item["id"], "job_id": job_id, "state": "submitted"})
    deadline = client.clock() + 1200
    delay = max(1, int(headers.get("retry-after", 20)))
    while client.clock() < deadline:
        client.sleep(delay)
        result = client.request("GET", location)[2]
        state = result.get("status")
        if state == "Completed":
            return {"notebook_id": item["id"], "job_id": job_id, "state": state}
        if state in ("Failed", "Cancelled", "Canceled", "Deduped"):
            raise DeploymentError(f"Notebook {state}, job {job_id}; inspect run error, no live processing success")
        if state not in ("NotStarted", "InProgress"):
            raise DeploymentError(f"Unknown notebook state {state!r}, job {job_id}")
        delay = 20
    raise DeploymentError(f"Notebook deadline exceeded, job {job_id}; no second run submitted")


def refresh_silver_metadata(client, ws, silver):
    endpoint = silver.get("properties", {}).get("sqlEndpointProperties", {})
    if not endpoint.get("id") or not endpoint.get("connectionString"):
        raise DeploymentError("Silver SQL endpoint not ready/discovered")
    result = client.operation("POST",
        f"/v1/workspaces/{ws}/sqlEndpoints/{endpoint['id']}/refreshMetadata",
        {"timeout": {"timeUnit": "Minutes", "value": 2}}, "sqldw-cli")
    if any(r.get("status") == "Failed" for r in result.get("value", [])):
        raise DeploymentError("Silver SQL metadata refresh reported failed tables")
    return endpoint


def ontology(cfg, client, ws, approve):
    if not approve:
        raise DeploymentError("Ontology write requires --approve-ontology after previewing fabric/ontology/definition")
    gold = resolve(cfg, client, ws, "gold")
    with connect(cfg, gold) as sql:
        validate_gold(sql, cfg["run_id"])
    definition = ontology_definition(gold["properties"]["connectionString"], gold["id"], cfg["names"]["ontology"])
    skill = "fabriciq-ontology-cli"
    existing = resolve(cfg, client, ws, "ontology", required=False)
    print(f"Ontology v2 preview: {len(ENTITIES)} business entities; {len(LINKS)} junction-backed relationships; consolidated Gold DirectLake; stable IDs, no part removal.")
    if existing:
        if existing.get("properties", {}).get("generation") != 2:
            raise DeploymentError("Existing ontology is not generation 2; v1 substitution/migration is prohibited")
        old = client.operation("POST", f"/v1/workspaces/{ws}/ontologies/{existing['id']}/getDefinition",
                               {}, skill, result_required=True)["definition"]
        definition = preserve_ontology_identity(definition, old)
        client.operation("POST", f"/v1/workspaces/{ws}/ontologies/{existing['id']}/updateDefinition?updateMetadata=true",
                         {"definition": definition}, skill)
        item = resolve(cfg, client, ws, "ontology")
    else:
        item = ensure(cfg, client, ws, "ontology", skill, {"definition": definition})
    if item.get("properties", {}).get("generation") != 2:
        raise DeploymentError("Ontology generation 2 not confirmed; no success claimed")
    readback = client.operation("POST", f"/v1/workspaces/{ws}/ontologies/{item['id']}/getDefinition", {}, skill, True)
    parts = {p["path"]: base64.b64decode(p["payload"]).decode() for p in readback["definition"]["parts"]}
    for entity in ENTITIES:
        text = parts.get(f"entities/{entity}.tmdl", "")
        if f"backingTable: {entity}" not in text or f"keyProperty: {ENTITIES[entity]['key']}" not in text:
            raise DeploymentError(f"Ontology business binding readback failed: {entity}")
    return {"item_id": item["id"], "generation": 2, "definition_verified": True,
            "instances_verified": False, "instance_refresh": "Portal qualification still required; no invented v2 refresh API"}


def dispatch(cfg, client, stage, approve=False):
    validate_config(cfg, stage)
    if stage == "validate":
        return {"state": "local_config_validated", "live_deployed": False}
    workspace = preflight(cfg, client)
    ws = workspace["id"]
    if stage == "check":
        return {"state": "approved_workspace_verified", "workspace_id": ws, "live_deployed": False}
    if stage == "foundation":
        return {"state": "foundation_created", "item_ids": foundation(cfg, client, ws)}
    if stage == "notebooks":
        return {"state": "notebook_definitions_persisted", "item_ids": {
            layer: deploy_notebook(cfg, client, ws, layer)["id"] for layer in ("Raw", "Silver")}}
    if stage == "bootstrap":
        raw = deploy_notebook(cfg, client, ws, "Raw", "bootstrap")
        return run_notebook(client, ws, raw)
    if stage == "process":
        runs = {}
        for layer in ("Raw", "Silver"):
            runs[layer] = run_notebook(client, ws, deploy_notebook(cfg, client, ws, layer))
        return {"state": "notebook_jobs_completed", "jobs": runs}
    if stage == "rti":
        verify_eventhub_region(cfg)
        raw, db = resolve(cfg, client, ws, "raw"), resolve(cfg, client, ws, "kql")
        connection = client.request("GET", "/v1/connections/" + cfg["eventhub_connection_id"], skill="eventstream-cli")[2]
        qualify_eventhub_connection(cfg, connection)
        with connect(cfg, raw, lakehouse=True) as sql:
            if not execute(sql, "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA='raw' AND TABLE_NAME='events_ingress'"):
                raise DeploymentError("Raw schema/bootstrap not ready; run bootstrap first")
        deploy_kql(cfg, db)
        existing = resolve(cfg, client, ws, "eventstream", required=False)
        old_topology = None
        if existing:
            old = client.operation("POST", f"/v1/workspaces/{ws}/eventstreams/{existing['id']}/getDefinition",
                                   {}, "eventstream-cli", True)
            old_topology = json.loads(base64.b64decode(next(p for p in old["definition"]["parts"] if p["path"] == "eventstream.json")["payload"]))
        definition = eventstream_definition(cfg, ws, raw, db, old_topology)
        if existing:
            client.operation("POST", f"/v1/workspaces/{ws}/eventstreams/{existing['id']}/updateDefinition",
                             {"definition": definition}, "eventstream-cli")
            item = existing
        else:
            item = ensure(cfg, client, ws, "eventstream", "eventstream-cli", {"definition": definition})
        topology = client.request("GET", f"/v1/workspaces/{ws}/eventstreams/{item['id']}/topology", skill="eventstream-cli")[2]
        return {"state": "topology_persisted", "item_id": item["id"],
                "ingestion_verified": False, "runtime_topology": topology}
    if stage == "gold":
        silver = resolve(cfg, client, ws, "silver")
        refresh_silver_metadata(client, ws, silver)
        return {"state": "gold_loaded", "publication": deploy_gold(cfg, resolve(cfg, client, ws, "gold"), silver)}
    if stage == "ontology":
        return ontology(cfg, client, ws, approve)
    if stage == "reconcile":
        db = resolve(cfg, client, ws, "kql")
        kql_result = kusto(cfg, db,
            "declare query_parameters(requested_run:string); RunEventIds(requested_run)", True,
            {"requested_run": cfg["run_id"]})
        table = next((t for t in kql_result["Tables"] if t.get("TableKind") == "PrimaryResult" or t.get("TableName") == "Table_0"), kql_result["Tables"][0])
        names = [c["ColumnName"] for c in table["Columns"]]
        kql_ids = {row[names.index("event_id")] for row in table["Rows"]}
        with connect(cfg, resolve(cfg, client, ws, "raw"), lakehouse=True) as sql:
            raw_ids = {r["event_id"] for r in execute(sql, "SELECT DISTINCT event_id FROM raw.events_ingress WHERE run_id=?", (cfg["run_id"],))}
        if not raw_ids or raw_ids != kql_ids:
            raise DeploymentError(f"Branch reconciliation incomplete: Raw={len(raw_ids)}, KQL={len(kql_ids)}, Raw-only={len(raw_ids-kql_ids)}, KQL-only={len(kql_ids-raw_ids)}")
        return {"state": "branches_reconciled", "run_id": cfg["run_id"], "distinct_events": len(raw_ids)}
    raise DeploymentError("Unknown stage")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--stage", required=True, choices=STAGES)
    parser.add_argument("--approve-ontology", action="store_true")
    parser.add_argument("--evidence", type=Path, default=ROOT / "evidence" / "last-run.json")
    args = parser.parse_args()
    if not args.evidence.resolve().is_relative_to(ROOT):
        parser.error("--evidence must stay within fabric/ (scope boundary)")
    client, code = None, 0
    evidence = {"stage": args.stage, "started_at": datetime.now(timezone.utc).isoformat(),
                "state": "blocked", "live_success": False}
    try:
        cfg = json.loads(args.config.read_text(encoding="utf-8"))
        validate_config(cfg, args.stage)
        client = FabricClient(cfg["tenant_id"])
        evidence["result"] = dispatch(cfg, client, args.stage, args.approve_ontology)
        evidence["state"] = "stage_completed"
        # Only this stage's actual evidence, never an overall deployment claim.
        evidence["live_success"] = args.stage not in ("validate", "check")
    except (DeploymentError, ValueError, OSError, KeyError) as exc:
        evidence["error"] = str(exc)
        code = 2
    finally:
        evidence["api_calls"] = client.evidence if client else []
        evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(evidence, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
