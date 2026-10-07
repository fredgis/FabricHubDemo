"""Read native BPS outputs and emit a real, environment-parameterized handoff."""
from __future__ import annotations

import argparse
import json
import re
import struct
import time
from datetime import datetime, timezone
from pathlib import Path

from fabric.deploy import preflight, validate_config
from fabric.rest import DeploymentError, FabricClient, token
from fabric.sql import connect, execute
from sources.salesforce.bps.jobs import STAGES, resolve_pipelines, validate_suffix

ROOT = Path(__file__).resolve().parents[3]
MAPPINGS = {
    "customer": {
        "object": "Contact",
        "fields": {
            "customer_key": "MSFlix_Key__c", "territory": "MSFlix_Territory__c",
            "first_name": "FirstName", "last_name": "LastName", "source_id": "Id",
        },
        "scope": "MSFlix_Key__c LIKE 'MSF-C%'",
    },
    "campaign": {
        "object": "Campaign",
        "fields": {
            "campaign_key": "MSFlix_Key__c", "name": "Name",
            "budget_minor": "MSFlix_BudgetMinor__c", "currency": "MSFlix_Currency__c",
            "channel": "MSFlix_Channel__c", "source_id": "Id",
        },
    },
    "consent": {
        "object": "MSFlix_Consent__c",
        "fields": {
            "consent_key": "MSFlix_Key__c", "customer_key": "CustomerKey__c",
            "purpose": "Purpose__c", "channel": "Channel__c", "granted": "Granted__c",
            "effective_at": "EffectiveAt__c", "source_id": "Id",
        },
    },
    "touch": {
        "object": "MSFlix_Touch__c",
        "fields": {
            "touch_key": "MSFlix_Key__c", "customer_key": "CustomerKey__c",
            "campaign_key": "CampaignKey__c", "channel": "Channel__c",
            "touch_type": "TouchType__c", "occurred_at": "OccurredAt__c",
            "tracking_token": "TrackingToken__c", "source_id": "Id",
        },
    },
}


def quoted_identifier(value):
    if not isinstance(value, str) or not value or len(value) > 128 or any(ord(c) < 32 for c in value):
        raise DeploymentError("Invalid discovered SQL identifier")
    return "[" + value.replace("]", "]]") + "]"


def connect_metadata(cfg, item):
    """Use SQLDb databaseName, not item ID or the REST connection-string flags."""
    import pyodbc

    properties = item.get("properties", {})
    server = properties.get("serverFqdn", "").removeprefix("tcp:").split(",")[0]
    catalog = properties.get("databaseName", "")
    if (
        not server.endswith(".database.fabric.microsoft.com")
        or any(c in server for c in ";{}\"/") or not catalog
        or any(c in catalog for c in ";{}\"")
    ):
        raise DeploymentError("Native metadata SQLDb endpoint not discovered/ready")
    encoded = token(cfg["tenant_id"], "https://database.windows.net").encode("utf-16-le")
    auth = struct.pack("<I", len(encoded)) + encoded
    connection = pyodbc.connect(
        f"Driver={{ODBC Driver 18 for SQL Server}};Server={server},1433;"
        f"Database={catalog};Encrypt=yes;TrustServerCertificate=no;",
        attrs_before={1256: auth}, timeout=30, autocommit=True,
    )
    connection.timeout = 90
    return connection


def mapping_evidence(mapping, tables):
    matches = [
        table for table in tables
        if table["table"].casefold() == mapping["object"].casefold()
    ]
    if len(matches) != 1:
        return {**mapping, "available": False, "reason": "Native output table missing or ambiguous"}
    table = matches[0]
    actual = {name.casefold(): name for name in table["columns"]}
    missing = [name for name in mapping["fields"].values() if name.casefold() not in actual]
    return {
        **mapping, "available": not missing, "missing_columns": missing,
        "actual_fields": {
            canonical: actual[field.casefold()]
            for canonical, field in mapping["fields"].items() if field.casefold() in actual
        },
        "schema": table["schema"], "table": table["table"],
        "delta_path": table["delta_path"], "row_count": table["row_count"],
        "deleted_rows": table.get("deleted_rows"), "customer_quality": table.get("customer_quality"),
    }


def inspect_outputs(cfg, client, workspace_id, suffix, system_name, dataset_name, timeout=600):
    validate_suffix(suffix)
    if not 60 <= timeout <= 900:
        raise DeploymentError("Native output inspection deadline must be 60-900 seconds")
    deadline = time.monotonic() + timeout

    def remaining():
        seconds = int(deadline - time.monotonic())
        if seconds < 1:
            raise DeploymentError("Native BPS output inspection deadline exceeded; no fabricated manifest")
        return min(60, seconds)

    items = client.list(f"/v1/workspaces/{workspace_id}/items", "spark-cli")

    def resolve(name, item_type):
        matches = [i for i in items if i["displayName"] == name and i["type"] == item_type]
        if len(matches) != 1:
            raise DeploymentError("Native BPS item missing or ambiguous: " + name)
        return matches[0]

    metadata = resolve("bps_metadata_db_" + suffix, "SQLDatabase")
    metadata = client.request(
        "GET", f"/v1/workspaces/{workspace_id}/sqlDatabases/{metadata['id']}",
        skill="sqldb-cli",
    )[2]
    with connect_metadata(cfg, metadata) as connection:
        connection.timeout = remaining()
        extraction = execute(connection, """
            SELECT TOP 1000 SystemName,sourceType,CDSViewName,Type,Delta,KeyFields,
                IsTableEnabled,IsDatasetEnabled,inScope
            FROM dbo.extractionMetadata WHERE SystemName=? ORDER BY CDSViewName
        """, (system_name,))
        scope = execute(connection, """
            SELECT TOP 1000 SystemName,DatasetName,TableName,IsEnabled
            FROM dbo.extractionScope WHERE SystemName=? AND DatasetName=? ORDER BY TableName
        """, (system_name, dataset_name))
        checkpoints = execute(connection, """
            SELECT TOP 1000 SystemName,ObjectName,MaxSystemModStamp
            FROM dbo.SalesforceTableCheckpoint WHERE SystemName=? ORDER BY ObjectName
        """, (system_name,))
    if len(extraction) >= 1000 or len(scope) >= 1000:
        raise DeploymentError("Native metadata exceeds the bounded discovery limit")
    if not scope:
        raise DeploymentError("Requested native BPS dataset/source is not configured")

    layers = {}
    for layer in ("bronze", "silver", "gold"):
        remaining()
        item = resolve("bps_" + layer + "_" + suffix, "Lakehouse")
        item = client.request(
            "GET", f"/v1/workspaces/{workspace_id}/lakehouses/{item['id']}",
            skill="sqldw-cli",
        )[2]
        properties = item["properties"]
        tables_path = properties["oneLakeTablesPath"].rstrip("/")
        with connect(cfg, item, lakehouse=True) as connection:
            connection.timeout = remaining()
            objects = execute(connection, """
                SELECT TOP 1000 TABLE_SCHEMA,TABLE_NAME
                FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE'
                ORDER BY TABLE_SCHEMA,TABLE_NAME
            """)
            columns = execute(connection, """
                SELECT TOP 10000 TABLE_SCHEMA,TABLE_NAME,COLUMN_NAME,DATA_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS ORDER BY TABLE_SCHEMA,TABLE_NAME,ORDINAL_POSITION
            """)
            if len(objects) >= 1000 or len(columns) >= 10000:
                raise DeploymentError("Native output discovery was truncated")
            tables = []
            for obj in objects:
                connection.timeout = remaining()
                schema, name = obj["TABLE_SCHEMA"], obj["TABLE_NAME"]
                actual_columns = {
                    row["COLUMN_NAME"]: row["DATA_TYPE"] for row in columns
                    if row["TABLE_SCHEMA"] == schema and row["TABLE_NAME"] == name
                }
                identifier = quoted_identifier(schema) + "." + quoted_identifier(name)
                entry = {
                    "schema": schema, "table": name, "columns": actual_columns,
                    "delta_path": tables_path + "/" + schema + "/" + name,
                    "row_count": execute(connection, "SELECT COUNT_BIG(*) AS n FROM " + identifier)[0]["n"],
                }
                by_lower = {column.casefold(): column for column in actual_columns}
                deletion = by_lower.get("isdeleted")
                if deletion:
                    entry["deleted_rows"] = execute(
                        connection, "SELECT COUNT_BIG(*) AS n FROM " + identifier
                        + " WHERE " + quoted_identifier(deletion) + "=1",
                    )[0]["n"]
                if name.casefold() == "contact" and "msflix_key__c" in by_lower:
                    key = quoted_identifier(by_lower["msflix_key__c"])
                    where = key + " LIKE 'MSF-C%'"
                    if deletion:
                        where += " AND (" + quoted_identifier(deletion) + "=0 OR " + quoted_identifier(deletion) + " IS NULL)"
                    quality = execute(connection, f"""
                        SELECT COUNT_BIG(*) AS customer_rows,
                            COUNT(DISTINCT {key}) AS distinct_customer_keys,
                            MIN({key}) AS first_customer_key,MAX({key}) AS last_customer_key
                        FROM {identifier} WHERE {where}
                    """)[0]
                    quality["duplicate_customer_keys"] = quality["customer_rows"] - quality["distinct_customer_keys"]
                    entry["customer_quality"] = quality
                tables.append(entry)
        layers[layer] = {
            "lakehouse_id": item["id"], "display_name": item["displayName"],
            "sql_endpoint_id": properties["sqlEndpointProperties"]["id"],
            "one_lake_tables_path": tables_path, "tables": tables,
            "entities": {name: mapping_evidence(mapping, tables) for name, mapping in MAPPINGS.items()},
        }

    env = resolve("bps_env_" + suffix, "Environment")
    compute = client.request(
        "GET", f"/v1/workspaces/{workspace_id}/environments/{env['id']}/sparkcompute?beta=false",
        skill="spark-cli",
    )[2]
    pipelines = resolve_pipelines(client, workspace_id, suffix)
    jobs = {}
    for stage, pipeline in pipelines.items():
        history = client.list(
            f"/v1/workspaces/{workspace_id}/items/{pipeline['id']}/jobs/instances", "spark-cli",
        )
        latest = max(history, key=lambda j: j.get("startTimeUtc") or "", default={})
        jobs[stage] = {
            "pipeline_id": pipeline["id"], "pipeline_name": pipeline["displayName"],
            "job_id": latest.get("id"), "status": latest.get("status"),
            "start_time_utc": latest.get("startTimeUtc"), "end_time_utc": latest.get("endTimeUtc"),
        }
    active = [
        row["CDSViewName"] for row in extraction
        if row["IsTableEnabled"] and row["IsDatasetEnabled"] and row["inScope"]
    ]
    missing = [m["object"] for m in MAPPINGS.values() if m["object"] not in active]
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "environment": cfg["environment"], "workspace_id": workspace_id,
        "system_suffix": suffix, "source_system": system_name, "dataset": dataset_name,
        "native_environment_id": env["id"], "published_runtime": compute["runtimeVersion"],
        "metadata_database_name": metadata["properties"]["databaseName"],
        "extraction_metadata": extraction, "dataset_scope": scope,
        "source_checkpoints": checkpoints, "jobs": jobs, "layers": layers,
        "missing_native_dataset_objects": missing,
        "deletion_acceptance": {
            "delete_round_trip_executed": False,
            "warning": "Zero deleted rows is an observation, not proof of insert/update/delete propagation.",
        },
        "external_gate": (
            "BPS > Datasets > MSFlixSF > MSFlixCRM > Import tables > New Table; "
            "add " + ", ".join(missing) + " using native BPS configuration, then Save/activate."
        ) if missing else None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--system-suffix", required=True)
    parser.add_argument("--source-system", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--output", type=Path, default=ROOT / ".state" / "bps" / "handoff.json")
    args = parser.parse_args()
    cfg = validate_config(json.loads(args.config.read_text(encoding="utf-8-sig")), "check")
    client = FabricClient(cfg["tenant_id"])
    workspace = preflight(cfg, client)
    manifest = inspect_outputs(
        cfg, client, workspace["id"], args.system_suffix, args.source_system, args.dataset,
        timeout=args.timeout_seconds,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, default=str, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "manifest": str(args.output), "jobs": manifest["jobs"],
        "published_runtime": manifest["published_runtime"],
        "missing_native_dataset_objects": manifest["missing_native_dataset_objects"],
        "customers": {
            layer: data["entities"]["customer"] for layer, data in manifest["layers"].items()
        },
    }, default=str))


if __name__ == "__main__":
    main()
