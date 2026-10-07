"""Supported Eventstream definition builder and discovered Kusto data plane."""
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fabric.build import ROOT, part
from fabric.rest import DeploymentError, safe_error_message, token


def eventstream_definition(cfg, workspace_id, raw, kql, existing=None):
    if not cfg.get("producer_payload_json_mirror"):
        raise DeploymentError(
            "RTI blocked: producer must include payload_json=json.dumps(payload) alongside "
            "the original object. Lakehouse nested-object string casting is not supported.")
    values = {
        "{{WORKSPACE_ID}}": workspace_id, "{{RAW_LAKEHOUSE_ID}}": raw["id"],
        "{{KQL_DATABASE_ID}}": kql["id"], "{{KQL_DATABASE_NAME}}": kql["displayName"],
        "{{EVENTHUB_CONNECTION_ID}}": cfg["eventhub_connection_id"],
        "{{CONSUMER_GROUP}}": cfg["consumer_group"]
    }
    topology = json.loads((ROOT / "rti" / "eventstream.template.json").read_text())

    def substitute(value):
        if isinstance(value, str):
            return values.get(value, value)
        if isinstance(value, list):
            return [substitute(v) for v in value]
        if isinstance(value, dict):
            return {k: substitute(v) for k, v in value.items()}
        return value

    topology = substitute(topology)
    use_onelake = cfg.get("rti_ingestion") == "eventhouse_onelake"
    stream = cfg["names"]["eventstream"] + "-stream"
    topology["streams"][0]["name"] = stream
    for group in ("operators", "destinations"):
        for node in topology[group]:
            for input_node in node["inputNodes"]:
                if input_node["name"] == "MSFlixIngress-stream":
                    input_node["name"] = stream
    topology["operators"][0]["properties"]["query"] = topology["operators"][0]["properties"]["query"].replace(
        "MSFlixIngress-stream", stream)
    if use_onelake:
        topology["operators"] = []
        topology["destinations"] = [node for node in topology["destinations"] if node["type"] == "Eventhouse"]
    if existing:
        # System-generated node IDs are required on update, never invented.
        for group in ("sources", "streams", "operators", "destinations"):
            old_nodes = {node["name"]: node for node in existing.get(group, [])}
            removed = set(old_nodes) - {node["name"] for node in topology[group]}
            allowed_removal = {"operators": {"PreserveRawEnvelope"},
                               "destinations": {"RawEnvelopeSink"}}.get(group, set()) if use_onelake else set()
            if removed - allowed_removal:
                raise DeploymentError("Unexpected Eventstream nodes; stop rather than remove unowned topology")
            if "RawEnvelopeSink" in removed:
                old_sink = old_nodes["RawEnvelopeSink"]
                properties = old_sink.get("properties", {})
                if old_sink["type"] != "Lakehouse" or properties.get("workspaceId") != workspace_id or properties.get("itemId") != raw["id"]:
                    raise DeploymentError("Refusing to retire a Raw destination with unverified ownership")
            for node in topology[group]:
                if node["name"] in old_nodes:
                    old_id = old_nodes[node["name"]].get("id")
                    if not old_id and group != "operators":
                        raise DeploymentError("Existing Eventstream node missing discovered ID")
                    if old_nodes[node["name"]]["type"] != node["type"]:
                        raise DeploymentError("Eventstream node type change requires explicit migration")
                    if old_id:
                        node["id"] = old_id
    return {"parts": [
        part("eventstream.json", json.dumps(topology)),
        part("eventstreamProperties.json", (ROOT / "rti" / "eventstreamProperties.json").read_text())
    ]}


def kusto(cfg, database, command, query=False, parameters=None):
    uri = database.get("properties", {}).get("queryServiceUri", "")
    host = urlparse(uri).netloc
    if urlparse(uri).scheme != "https" or not host.endswith(".kusto.fabric.microsoft.com"):
        raise DeploymentError("Kusto query URI not discovered or not a Fabric host")
    body = {"db": database["displayName"], "csl": command}
    if parameters:
        body["properties"] = json.dumps({"Parameters": parameters})
    request = Request(uri.rstrip("/") + ("/v1/rest/query" if query else "/v1/rest/mgmt"),
                      data=json.dumps(body).encode(), method="POST",
                      headers={"Authorization": "Bearer " + token(cfg["tenant_id"], "https://kusto.kusto.windows.net"),
                               "Accept": "application/json",
                               "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=90) as response:
            result = json.loads(response.read())
    except HTTPError as exc:
        detail = safe_error_message(exc.read().decode("utf-8", errors="replace"))
        raise DeploymentError(f"Kusto HTTP {exc.code}: {detail}; no success claimed") from exc
    except (URLError, TimeoutError) as exc:
        raise DeploymentError("Kusto endpoint request failed: " + safe_error_message(exc)) from exc
    if result.get("error"):
        raise DeploymentError("Kusto returned error; no success claimed")
    for table in result.get("Tables", []):
        names = [c["ColumnName"] for c in table.get("Columns", [])]
        if table.get("TableName") == "QueryStatus" or {"Severity", "StatusCode"}.issubset(names):
            # Completion rows can expose partial failures despite HTTP 200.
            if "Severity" in names and any(row[names.index("Severity")] <= 2 for row in table["Rows"]):
                raise DeploymentError("Kusto query/management partial failure")
    return result


def deploy_kql(cfg, database):
    for command in (ROOT / "rti" / "schema.kql").read_text().split("// @command"):
        command = "\n".join(line for line in command.strip().splitlines() if not line.startswith("//"))
        if command.strip():
            if not command.lstrip().startswith("."):
                raise DeploymentError("Invalid KQL command block; no request submitted")
            kusto(cfg, database, command)
    # Only explicitly supplied operational event names enter current business
    # state. ControlCommand and transaction Outbox records remain diagnostics,
    # never commercial facts.
    if not cfg.get("event_entity_map"):
        raise DeploymentError("Exact parent event_entity_map required before KQL current-state authoring")
    entity_map = json.dumps(cfg["event_entity_map"], separators=(",", ":"))
    deleted = json.dumps(cfg.get("delete_event_types", []), separators=(",", ":"))
    command = """.create-or-alter function with (folder='MSFlix', docstring='Latest entity state by source sequence, retaining deletes; not a sales sum') CurrentBusinessEntities() {
        let entity_map=dynamic(MAPPING);
        let delete_types=dynamic(DELETES);
        let valid=DeduplicatedEvents()
            | extend entity=tostring(entity_map[event_type])
            | where isnotempty(entity) and schema_version==1 and source_sequence>0
            | extend is_deleted=set_has_element(delete_types,event_type) or coalesce(tobool(payload.is_deleted),false);
        let conflicts=valid | summarize ids=make_set(event_id,2) by entity,entity_key,source_sequence
            | where array_length(ids)>1 | project entity,entity_key;
        valid
        | join kind=leftanti (EventIdConflicts() | project event_id) on event_id
        | join kind=leftanti (conflicts) on entity,entity_key
        | summarize arg_max(source_sequence, *) by entity,entity_key
    }""".replace("MAPPING", entity_map).replace("DELETES", deleted)
    kusto(cfg, database, command)
    kusto(cfg, database, """.create-or-alter function with (folder='MSFlix') CurrentOrders() {
        CurrentBusinessEntities()
        | where entity=='rental' and not(is_deleted)
        | project order_id=entity_key, customer_key=tostring(payload.customer_key),
            offer_key=tostring(payload.offer_key), status=tostring(payload.status),
            amount_minor=tolong(payload.amount_minor), currency=tostring(payload.currency),
            source_sequence,event_id,run_id
    }""")
    # API 200 on schema commands is not an end-to-end ingest success.
    return kusto(cfg, database, ".show table RawEvents schema as json")
