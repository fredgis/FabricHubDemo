"""Bounded native-BPS SQL snapshot for the parent's existing CRM conformer."""
from __future__ import annotations

import argparse
import json
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path

from fabric.deploy import preflight, validate_config
from fabric.rest import DeploymentError, FabricClient
from fabric.sql import connect, execute
from sources.salesforce.bps.inspect import MAPPINGS, quoted_identifier
from sources.salesforce.bps.jobs import validate_suffix

ROOT = Path(__file__).resolve().parents[3]
KEY_PREFIXES = {
    "customer": "MSF-C%",
    "campaign": "MSF-MKT-%",
    "consent": "MSF-CONSENT-%",
    "touch": "MSF-TOUCH-%",
}


def entity_query(entity, schema, table, columns):
    """Rank BEFORE filtering tombstones so an old append cannot resurrect a row."""
    if entity not in MAPPINGS:
        raise DeploymentError("Unsupported native CRM snapshot entity")
    actual = {column.casefold(): column for column in columns}
    required = list(dict.fromkeys(MAPPINGS[entity]["fields"].values())) + ["IsDeleted", "SystemModstamp"]
    missing = [column for column in required if column.casefold() not in actual]
    if missing:
        raise DeploymentError("Native " + MAPPINGS[entity]["object"] + " fields missing: " + ", ".join(missing))
    selected = required + [
        column for column in ("_SystemName", "_UpdatedTimeStamp") if column.casefold() in actual
    ]
    projection = ", ".join(
        quoted_identifier(actual[column.casefold()]) + " AS " + quoted_identifier(column)
        for column in selected
    )
    identifier = quoted_identifier(schema) + "." + quoted_identifier(table)
    identity = quoted_identifier(actual["id"])
    stamp = quoted_identifier(actual["systemmodstamp"])
    updated = (
        "," + quoted_identifier(actual["_updatedtimestamp"]) + " DESC"
        if "_updatedtimestamp" in actual else ""
    )
    system = quoted_identifier(actual["_systemname"]) if "_systemname" in actual else None
    scope = " WHERE " + system + "=?" if system else ""
    return f"""
        WITH native_latest AS (
            SELECT {projection},
                ROW_NUMBER() OVER (PARTITION BY {identity} ORDER BY {stamp} DESC{updated}) AS __latest
            FROM {identifier}{scope}
        )
        SELECT TOP 100001 {','.join(quoted_identifier(c) for c in selected)}
        FROM native_latest
        WHERE __latest=1 AND [MSFlix_Key__c] LIKE '{KEY_PREFIXES[entity]}' AND [IsDeleted]=0
        ORDER BY [MSFlix_Key__c]
    """, bool(system)


def customer_query(schema, table, columns):
    return entity_query("customer", schema, table, columns)


def json_native(value):
    """Salesforce datetime fields are UTC; preserve scalar types for the adapter."""
    if isinstance(value, datetime):
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return str(value)
    raise TypeError("Unsupported native snapshot value type: " + type(value).__name__)


def normalize_row(row):
    result = dict(row)
    if "MSFlix_BudgetMinor__c" in result:
        value = result["MSFlix_BudgetMinor__c"]
        if value is not None:
            if isinstance(value, bool):
                raise DeploymentError("Native campaign minor-unit budget cannot be boolean")
            number = Decimal(str(value))
            if not number.is_finite() or number != number.to_integral_value():
                raise DeploymentError("Native campaign minor-unit budget is not an exact integer")
            result["MSFlix_BudgetMinor__c"] = int(number)
    return result


def snapshot(
    cfg, client, workspace_id, suffix, layer, source_system, directory, *,
    entity="customer", output_label=None,
):
    validate_suffix(suffix)
    if entity not in MAPPINGS:
        raise DeploymentError("Unsupported native CRM snapshot entity")
    if layer not in ("bronze", "silver"):
        raise DeploymentError("Use verified native Bronze or Silver for the raw-field CRM adapter")
    if output_label not in (None, "bronze", "silver"):
        raise DeploymentError("Invalid output label")
    source_object = MAPPINGS[entity]["object"]
    items = client.list(f"/v1/workspaces/{workspace_id}/lakehouses", "sqldw-cli")
    matches = [item for item in items if item["displayName"] == "bps_" + layer + "_" + suffix]
    if len(matches) != 1:
        raise DeploymentError("Native BPS Lakehouse not uniquely discovered")
    item = client.request(
        "GET", f"/v1/workspaces/{workspace_id}/lakehouses/{matches[0]['id']}",
        skill="sqldw-cli",
    )[2]
    with connect(cfg, item, lakehouse=True) as connection:
        connection.timeout = 60
        tables = execute(connection, """
            SELECT TOP 100 TABLE_SCHEMA,TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES WHERE LOWER(TABLE_NAME)=?
        """, (source_object.lower(),))
        if len(tables) != 1:
            raise DeploymentError("Native " + source_object + " is missing or ambiguous; no snapshot claimed")
        schema, table = tables[0]["TABLE_SCHEMA"], tables[0]["TABLE_NAME"]
        columns = execute(connection, """
            SELECT TOP 1000 COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA=? AND TABLE_NAME=? ORDER BY ORDINAL_POSITION
        """, (schema, table))
        query, scoped = entity_query(entity, schema, table, [r["COLUMN_NAME"] for r in columns])
        rows = [
            normalize_row(row)
            for row in execute(connection, query, (source_system,) if scoped else ())
        ]
    keys = [row["MSFlix_Key__c"] for row in rows]
    if not rows or len(rows) > 100000 or len(keys) != len(set(keys)):
        raise DeploymentError("Native " + entity + " snapshot is empty, truncated or has duplicate business keys")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    name = "contact" if entity == "customer" else entity
    label = output_label or layer
    output = directory / (name + "." + label + ".native.json")
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(rows, default=json_native, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    provenance = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "environment": cfg["environment"], "workspace_id": workspace_id,
        "source": "Microsoft Business Process Solutions native Salesforce output",
        "layer": layer, "output_label": label, "processed_silver": layer == "silver",
        "entity": entity, "source_object": source_object, "source_system": source_system,
        "lakehouse_id": item["id"], "sql_endpoint_id": item["properties"]["sqlEndpointProperties"]["id"],
        "schema": schema, "table": table,
        "delta_path": item["properties"]["oneLakeTablesPath"].rstrip("/") + "/" + schema + "/" + table,
        "snapshot_file": str(output), "json_shape": "array of Salesforce raw-field records",
        "row_count": len(rows), "distinct_business_keys": len(set(keys)),
        "business_key_field": "MSFlix_Key__c", "deleted_rows_in_snapshot": 0,
        "method": "latest Id/SystemModstamp, native source-system filter, then MSFlix key/live-row filter",
        "native_delete_round_trip_tested": False,
    }
    if entity == "customer":
        provenance.update(distinct_customer_keys=len(set(keys)), customer_key_field="MSFlix_Key__c")
    (directory / (name + "." + label + ".provenance.json")).write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8",
    )
    return provenance


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--system-suffix", required=True)
    parser.add_argument("--source-system", required=True)
    parser.add_argument("--layer", choices=("bronze", "silver"), required=True)
    parser.add_argument("--entity", choices=tuple(MAPPINGS), default="customer")
    parser.add_argument(
        "--output-label", choices=("bronze", "silver"),
        help="Stable handoff filename label; provenance always records the actual source layer",
    )
    args = parser.parse_args()
    cfg = validate_config(json.loads(args.config.read_text(encoding="utf-8-sig")), "check")
    client = FabricClient(cfg["tenant_id"])
    workspace = preflight(cfg, client)
    print(json.dumps(snapshot(
        cfg, client, workspace["id"], args.system_suffix, args.layer,
        args.source_system, ROOT / ".state" / "bps",
        entity=args.entity, output_label=args.output_label,
    )))


if __name__ == "__main__":
    main()
