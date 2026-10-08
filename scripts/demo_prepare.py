"""Discover the existing Demo bindings and grant the VM identity runtime access."""
from __future__ import annotations

import argparse
import json
import re
import uuid
from contextlib import closing
from pathlib import Path

from fabric.rest import DeploymentError, FabricClient, az_json
from fabric.sql import execute
from scripts.demo_vm import Arm
from services.publisher.publish import make_credential, sql_connect
from services.publisher.worker import validate_config
from services.publisher.access import POLICY


def sql_permissions(connection, application_id, name="msflix_demo_worker"):
    """No db_owner grant. DENY also constrains Fabric-inherited SQL permissions."""
    # Fabric SQL service principals use application/client ID as SID, unlike
    # Entra users/groups (object ID). ARM/Fabric role assignments still use the
    # managed identity's service-principal object ID.
    uuid.UUID(application_id)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]+", name):
        raise ValueError("Invalid managed SQL username")
    user = "[" + name + "]"
    sid = "0x" + uuid.UUID(application_id).bytes_le.hex()
    existing = execute(connection,
        "SELECT name,CONVERT(varchar(256),sid,1) AS sid FROM sys.database_principals WHERE name=?;", (name,))
    if existing and existing[0]["sid"].lower() != sid.lower():
        raise DeploymentError("Existing SQL user has a different identity; refusing replacement")
    if not existing:
        execute(connection, f"CREATE USER {user} WITH SID={sid}, TYPE=E;")
    tables = execute(connection, """
        SELECT s.name AS schema_name,t.name AS table_name FROM sys.tables t
        JOIN sys.schemas s ON s.schema_id=t.schema_id WHERE t.is_ms_shipped=0;""")
    columns = execute(connection,
        "SELECT name FROM sys.columns WHERE object_id=OBJECT_ID('dbo.Outboxes');")
    if "published_at" not in {r["name"] for r in columns}:
        raise DeploymentError("Expected persisted Outboxes schema missing")
    execute(connection, f"GRANT SELECT ON OBJECT::dbo.Outboxes TO {user}; "
                        f"GRANT UPDATE ON OBJECT::dbo.Outboxes (published_at) TO {user};")
    # The runtime needs Contributor for the supported notebook APIs. Fabric's
    # SQL authorization documentation specifies that native DENY takes priority
    # over that inherited access. Prove effective rights from IMDS before start.
    execute(connection, f"DENY INSERT,DELETE,ALTER,TAKE OWNERSHIP ON OBJECT::dbo.Outboxes TO {user};")
    for row in columns:
        if row["name"] != "published_at":
            column = row["name"].replace("]", "]]")
            execute(connection, f"DENY UPDATE ON OBJECT::dbo.Outboxes ([{column}]) TO {user};")
    for row in tables:
        if (row["schema_name"], row["table_name"]) == ("dbo", "Outboxes"):
            continue
        table = ".".join("[" + row[k].replace("]", "]]") + "]" for k in ("schema_name", "table_name"))
        execute(connection, f"DENY SELECT,INSERT,UPDATE,DELETE,ALTER,TAKE OWNERSHIP ON OBJECT::{table} TO {user};")
    execute(connection, f"DENY CREATE TABLE,CREATE PROCEDURE,CREATE VIEW,CREATE FUNCTION,"
            f"ALTER ANY USER,ALTER ANY ROLE,ALTER ANY SCHEMA TO {user};")
    execute(connection, f"DENY IMPERSONATE ON USER::dbo TO {user};")
    return execute(connection, """
        SELECT p.name,d.permission_name,d.state_desc,
               OBJECT_SCHEMA_NAME(d.major_id) AS schema_name,OBJECT_NAME(d.major_id) AS object_name,
               COL_NAME(d.major_id,d.minor_id) AS column_name
        FROM sys.database_permissions d JOIN sys.database_principals p ON p.principal_id=d.grantee_principal_id
        WHERE p.name=? ORDER BY object_name,column_name,permission_name;""", (name,))


def prepare(args):
    source = json.loads(args.fabric_config.read_text(encoding="utf-8"))
    client = FabricClient(source["tenant_id"])
    workspace = client.request("GET", f"/v1/workspaces/{source['workspace_id']}",
                               skill="e2e-medallion-architecture")[2]
    if workspace["displayName"] != source["workspace_name"] or not workspace.get("capacityId"):
        raise DeploymentError("Workspace/capacity binding mismatch")
    arm = Arm(source["tenant_id"])
    vm = arm.request("GET", f"https://management.azure.com{args.vm_id}?api-version=2024-07-01")[2]
    if (vm["identity"]["tenantId"] != source["tenant_id"] or
            not args.vm_id.lower().startswith("/subscriptions/" + source["subscription_id"].lower() + "/") or
            vm["location"].replace(" ", "").lower() != source["region"]):
        raise DeploymentError("VM differs from approved tenant/subscription/region")
    principal = vm["identity"]["principalId"]
    service_principal = az_json("ad", "sp", "show", "--id", principal)
    application_id = service_principal["appId"]
    ws = workspace["id"]
    collections = {"raw": "lakehouses", "silver": "lakehouses", "gold": "warehouses", "kql": "kqlDatabases"}
    items = {}
    for key, collection in collections.items():
        matches = [r for r in client.list(f"/v1/workspaces/{ws}/{collection}", "e2e-medallion-architecture")
                   if r["displayName"] == source["names"][key]]
        if len(matches) != 1:
            raise DeploymentError(f"Expected one existing {key} item")
        items[key] = client.request("GET", f"/v1/workspaces/{ws}/{collection}/{matches[0]['id']}",
                                     skill="e2e-medallion-architecture")[2]
    notebooks = client.list(f"/v1/workspaces/{ws}/notebooks", "spark-cli")
    notebook_ids = {}
    for layer in ("raw", "silver"):
        matches = [r for r in notebooks if r["displayName"] == f"MSFlix{layer.title()}Processing"]
        if len(matches) != 1:
            raise DeploymentError(f"Expected existing {layer} notebook")
        notebook_ids[layer] = matches[0]["id"]
    graph = client.request("GET", f"/v1/workspaces/{ws}/items/{args.graph_id}",
                            skill="fabriciq-ontology-cli")[2]
    if graph["type"] != "GraphModel" or not graph["displayName"].startswith("MSFlixBusiness_graph_"):
        raise DeploymentError("Not the existing MSFlix graph")
    operational = client.request("GET", f"/v1/workspaces/{ws}/sqlDatabases/{args.operational_item}",
                                 skill="sqldb-cli")[2]
    if not operational["displayName"].startswith("MSFlix Business Control"):
        raise DeploymentError("Not the app-linked MSFlix operational database")
    cfg = {k: source[k] for k in (
        "environment", "tenant_id", "subscription_id", "region", "workspace_id", "run_id",
        "rti_ingestion", "minimum_rti_events", "max_input_events", "event_entity_map",
        "master_reference_entities", "currency_exponents", "commercial_statuses")}
    cfg.update(auth="managed-identity", capacity_id=workspace["capacityId"],
               vm_resource_id=args.vm_id, managed_identity_principal_id=principal,
               managed_identity_application_id=application_id,
               graph_id=graph["id"], items=items, notebooks=notebook_ids,
               poll_seconds=30, stage_timeout_seconds=1800,
               operational={"item_id": args.operational_item, "server": args.server, "database": args.database},
               publisher={"namespace": source["eventhub_namespace"].split(".")[0],
                          "topic": source["eventhub_name"], "duration": 30, "max_messages": 2000, "batch_size": 128})
    cfg["orchestration_authorization"] = {
        "mode": POLICY, "workspace_role": "Contributor",
        **{k: cfg[k] for k in ("tenant_id", "workspace_id", "vm_resource_id",
                              "managed_identity_principal_id", "managed_identity_application_id")}}
    validate_config(cfg)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    evidence = {"vm_id": args.vm_id, "principal_id": principal, "workspace_id": ws,
                "notebooks": notebook_ids, "graph_id": graph["id"], "config": str(args.output)}
    if args.grant:
        roles = client.list(f"/v1/workspaces/{ws}/roleAssignments", "e2e-medallion-architecture")
        found = [r for r in roles if r["principal"]["id"] == principal]
        if not found:
            client.request("POST", f"/v1/workspaces/{ws}/roleAssignments",
                {"principal": {"id": principal, "type": "ServicePrincipal"}, "role": "Contributor"},
                "e2e-medallion-architecture")
        elif found[0]["role"] not in ("Contributor",):
            raise DeploymentError("Existing MI workspace role differs; review rather than silently widening")
        credential = make_credential(argparse.Namespace(auth="azure-cli", tenant=source["tenant_id"]))
        with closing(sql_connect(args.server, args.database, credential, autocommit=True)) as connection:
            evidence["sql_permissions"] = sql_permissions(connection, application_id)
        evidence["workspace_role"] = "Contributor"
    (args.output.parent / "permissions.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in evidence.items() if k != "sql_permissions"}), flush=True)
    return cfg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fabric-config", type=Path, required=True)
    parser.add_argument("--vm-id", required=True)
    parser.add_argument("--operational-item", required=True)
    parser.add_argument("--server", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--graph-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--grant", action="store_true")
    prepare(parser.parse_args())


if __name__ == "__main__":
    main()
