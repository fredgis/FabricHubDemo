"""Additive native BPS Gold -> MSFlixGold SAP publication.

Preview is offline. --inspect-source only reads Fabric/TDS and records a qualified
catalog; --apply requires that catalog, fresh job readback and SQL reconciliation.
No local scenario row is ever an INSERT payload. All ingress is INSERT ... SELECT
from the uniquely discovered, same-workspace native Gold SQL endpoint.
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import importlib
import json
import re
import struct
from contextlib import closing
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from fabric.rest import DeploymentError
from fabric.sql import execute, literal
from sources.sap.accounting import ACCOUNTS, CHART, ZERO, money
from sources.sap.config import DEFAULT_CONFIG, DEFAULT_REFERENCES, period, read_json
from sources.sap.fabric_client import ScopedClient, load_target
from sources.sap.native import load_contract
from sources.sap.process import PREFIX, silver_evidence_path
from sources.salesforce.bps.jobs import _save
from sources.sap.scenario import build

ROOT = Path(__file__).resolve().parents[2]
SQL_ROOT = ROOT / "fabric" / "gold"
DEFAULT_METADATA = ROOT / ".state" / "sap-native" / "native-contract-with-custom.json"
VERSION = 1
LABEL = "MSFlix_SAP_native_gold_publication"
STAMPS = {
    "source_system": "varchar(16)", "company_scope": "varchar(4)",
    "scenario_id": "varchar(128)", "run_id": "varchar(128)", "as_of": "date",
}
PUBLICATION_TYPES = {
    **STAMPS, "source_workspace_id": "varchar(36)", "source_item_id": "varchar(36)",
    "source_endpoint_id": "varchar(36)", "source_database": "varchar(128)",
    "b2s_job_id": "varchar(36)", "s2g_job_id": "varchar(36)",
    "input_sha256": "varchar(64)", "catalog_sha256": "varchar(64)", "data_sha256": "varchar(64)",
    "journal_lines": "bigint", "accounting_documents": "bigint", "completed_at": "datetime2(6)",
    **{k: "decimal(23,2)" for k in ("net_billings", "recognized_revenue", "content_cost",
                                   "receivables", "payables", "net_bank_movement", "net_vat_liability")},
}
# Native source business keys, not BPS Key/SK columns, define every table's grain.
# These are separate from every table replaced by fabric/gold/load.sql.
TABLES = {
    "I_COMPANYCODE": "sap_company",
    "I_GLACCOUNTINCHARTOFACCOUNTS": "sap_account",
    "I_FISCALPERIODFORVARIANT": "sap_period",
    "I_FISCALYEARFORCOMPANYCODE": "sap_fiscal_year",
    "I_FISCALYEARVARIANT": "sap_fiscal_variant",
    "I_SUPPLIER": "sap_supplier",
    "I_PRODUCT": "sap_product",
    "I_COSTCENTER": "sap_cost_center",
    "I_PROFITCENTER": "sap_profit_center",
    "I_GLACCOUNTHIERARCHYNODE": "sap_gl_hierarchy",
    "I_COSTCENTERHIERARCHYNODE": "sap_cost_hierarchy",
    "I_PROFITCENTERHIERARCHYNODE": "sap_profit_hierarchy",
    "ZMSF_CUSTOMER_LINK": "sap_customer_link",
    "ZMSF_PLAN": "sap_plan",
    "ZMSF_SUBSCRIPTION": "sap_subscription",
    "ZMSF_RIGHTS_CONTRACT": "sap_rights_contract",
    "ZMSF_RIGHTS_COVERAGE": "sap_rights_coverage",
    "ZMSF_BILLING_LINK": "sap_billing_link",
    "ZMSF_CONTRACT_CHARGE": "sap_contract_charge",
    "C_BILLINGDOCITEMBASICDEX_1": "sap_invoice_item",
    "I_GLACCOUNTLINEITEMRAWDATA": "sap_gl_line",
    "I_OPERATIONALACCTGDOCITEM": "sap_operational_item",
}
CUSTOM = tuple(n for n in TABLES if n.startswith("ZMSF_"))
CUSTOM_RELATIONSHIPS = {
    "ZMSF_BILLING_LINK": ("ZMSF_SUBSCRIPTION", ("SUBSCRIPTION_ID",), "_key_ZMSFSUBSCRIPTION"),
    "ZMSF_CONTRACT_CHARGE": ("ZMSF_RIGHTS_CONTRACT", ("CONTRACT_ID", "VERSION"), "_key_ZMSFRIGHTSCONTRACT"),
}
# Industrial master attributes are intentionally not a serving contact/address copy.
SUBSETS = {
    "I_COSTCENTER": "CONTROLLINGAREA COSTCENTER VALIDITYENDDATE VALIDITYSTARTDATE COMPANYCODE "
                    "BUSINESSAREA FUNCTIONALAREA PROFITCENTER COSTCENTERCURRENCY COSTCENTERCATEGORY "
                    "COSTCENTERSTANDARDHIERAREA",
    "I_PROFITCENTER": "CONTROLLINGAREA PROFITCENTER VALIDITYENDDATE VALIDITYSTARTDATE COMPANYCODE "
                      "SEGMENT PROFITCENTERSTANDARDHIERARCHY",
}


def require(condition, message):
    if not condition:
        raise DeploymentError("SAP serving gate closed: " + message)


def ident(value):
    # DB_NAME can be an opaque Fabric database name, not necessarily a display name.
    require(isinstance(value, str) and 0 < len(value) <= 128
            and not any(ord(c) < 32 for c in value), "invalid SQL coordinate")
    return "[" + value.replace("]", "]]") + "]"


def text(value):
    return literal(value)


def batch_literal(value):
    require(isinstance(value, str) and len(value) < 1000000 and "\0" not in value, "invalid SQL batch")
    return "'" + value.replace("'", "''") + "'"


def canonical(value):
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if isinstance(value, Decimal):
        require(value.is_finite(), "nonfinite SQL money")
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def signature(value):
    return hashlib.sha256(json.dumps(canonical(value), sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def fingerprint(rows):
    return signature(sorted((canonical(r) for r in rows),
                            key=lambda r: json.dumps(r, sort_keys=True)))


def selected_fields(contract, name):
    fields = contract.schemas[name].fields
    return tuple(f for f in fields if name not in SUBSETS or f.name in SUBSETS[name].split())


def sql_type(field):
    if field.ddic == "DATS":
        return "date"
    if field.ddic in {"CURR", "DEC", "QUAN"}:
        return f"decimal({field.length},{field.scale})"
    if field.ddic in {"INT4", "INT8"}:
        return "int" if field.ddic == "INT4" else "bigint"
    return f"varchar({field.length})"


def expression(field, alias="s"):
    column = alias + "." + ident(field.name)
    if field.ddic == "NUMC":
        # BPS casts NUMC to int. Reconstruct its source-domain text (including versions).
        return (f"CASE WHEN {column} IS NULL THEN NULL ELSE "
                f"RIGHT(REPLICATE('0',{field.length})+CAST({column} AS varchar({field.length})),"
                f"{field.length}) END")
    return f"CAST({column} AS {sql_type(field)})"


def expected(config, references):
    # This is EXPECTED totals only. Never returned/used as an ingestion row payload.
    summary = build(config, references).snapshots[-1].summary
    return {k: summary[k] for k in (
        "as_of", "currency", "accounting_documents", "journal_lines", "net_billings",
        "recognized_revenue", "deferred_revenue", "content_cost", "content_contribution",
        "receivables", "payables", "net_bank_movement", "net_vat_liability",
        "open_customer_items", "open_supplier_items",
    )}


def inputs(config, references, metadata):
    contract = load_contract(metadata)
    raw = read_json(metadata)
    custom = {r["CDSViewName"] for r in raw["objects"] if r["CDSViewName"].startswith("ZMSF_")}
    require(custom == set(CUSTOM), "all seven custom objects must be registered in native BPS")
    require(all(set(contract.schemas[n].keys) <= {f.name for f in selected_fields(contract, n)}
                for n in TABLES), "projection omits a native business PK")
    require(config["source_system"] == "S4M" and config["currency"] == "EUR",
            "only the approved S4M EUR simulation is supported")
    totals = expected(config, references)
    input_hash = signature({
        "config": config, "references": references, "metadata": raw,
        "fields": {n: [(f.name, f.ddic, f.length, f.scale, f.key)
                       for f in selected_fields(contract, n)] for n in TABLES},
        "account_roles": ACCOUNTS, "version": VERSION,
    })
    return contract, totals, input_hash


def local_jobs(target, evidence, stages=PREFIX):
    jobs = {}
    for stage in stages:
        row = read_json(evidence / (stage + "-job.json"))
        require(row.get("state") == "Completed", stage + " checkpoint is not Completed")
        require(row.get("workspace_id") == target["workspace_id"] and row.get("stage") == stage,
                stage + " checkpoint belongs to another target/stage")
        for key in ("pipeline_id", "job_id"):
            try:
                UUID(row[key])
            except (KeyError, ValueError, TypeError) as exc:
                raise DeploymentError(f"Invalid {stage} {key} evidence") from exc
        jobs[stage] = {"pipeline_id": row["pipeline_id"], "job_id": row["job_id"]}
    return jobs


def live_jobs(client, jobs):
    root = "/v1/workspaces/" + client.target["workspace_id"]
    times = {}
    for stage, checkpoint in jobs.items():
        item = client.item(PREFIX[stage] + client.target["system_suffix"], "DataPipeline")
        require(item["id"] == checkpoint["pipeline_id"], stage + " pipeline evidence mismatch")
        path = root + "/items/" + item["id"] + "/jobs/instances"
        actual = client.request("GET", path + "/" + checkpoint["job_id"])[2]
        require(actual.get("status") == "Completed" and actual.get("id") == checkpoint["job_id"],
                stage + " live job readback is not the checkpointed Completed run")
        history = client.list(path)
        require(history and all(j.get("status") in {"Completed", "Failed", "Cancelled", "Deduped"}
                                for j in history), "active/unknown native processing; retry only after qualification")
        latest = max(history, key=lambda j: j.get("startTimeUtc", ""))
        require(latest["id"] == checkpoint["job_id"] and latest["status"] == "Completed",
                stage + " checkpoint is not the latest native job")
        require(actual.get("endTimeUtc") and actual.get("startTimeUtc"), "job timestamps missing")
        times[stage] = actual
    if "s2g" in times:
        require(times["b2s"]["endTimeUtc"] <= times["s2g"]["startTimeUtc"],
                "Gold job predates the completed Bronze-to-Silver run")


def discover(client, source_stage="gold"):
    require(source_stage in {"silver", "gold"}, "invalid native source stage")
    client.workspace()
    root = "/v1/workspaces/" + client.target["workspace_id"]
    source_name = "bps_" + source_stage + "_" + client.target["system_suffix"]
    source = client.item(source_name, "Lakehouse")
    target = client.item("MSFlixGold", "Warehouse")
    source_id, target_id = source["id"], target["id"]
    source = client.request("GET", root + "/lakehouses/" + source["id"])[2]
    target = client.request("GET", root + "/warehouses/" + target["id"])[2]
    require(source.get("displayName") == source_name
            and target.get("displayName") == "MSFlixGold"
            and source.get("id") == source_id and target.get("id") == target_id,
            "item readback changed identity")
    endpoint = source.get("properties", {}).get("sqlEndpointProperties", {})
    require(endpoint.get("id") and endpoint.get("connectionString"), "native Gold SQL endpoint not ready")
    return source, target


def connect(client, item, lakehouse=False):
    properties = item.get("properties", {})
    props = properties.get("sqlEndpointProperties", {}) if lakehouse else properties
    server = props.get("connectionString", "").removeprefix("tcp:").split(",")[0]
    require(re.fullmatch(r"[A-Za-z0-9.-]+\.datawarehouse\.fabric\.microsoft\.com", server),
            "SQL FQDN not discovered/ready")
    catalog = props.get("id") if lakehouse else item["id"]
    UUID(catalog)
    token = client.token("https://database.windows.net").encode("utf-16-le")
    auth = struct.pack("<I", len(token)) + token
    base = f"Server={server},1433;Database={catalog};Encrypt=yes;TrustServerCertificate=no;"
    try:
        driver = importlib.import_module("pyodbc")
    except ImportError:
        driver = None
    if driver and "ODBC Driver 18 for SQL Server" in driver.drivers():
        connection = driver.connect("Driver={ODBC Driver 18 for SQL Server};" + base,
                                    attrs_before={1256: auth}, timeout=30, autocommit=True)
    else:
        try:
            driver = importlib.import_module("mssql_python")
        except ImportError as exc:
            raise DeploymentError("SAP TDS needs declared mssql-python or ODBC 18; ODBC 17 is not used") from exc
        connection = driver.connect(base, attrs_before={1256: auth}, timeout=30,
                                    autocommit=True, native_uuid=False)
    connection.timeout = 300
    return connection


def catalog(connection, contract, source_schema, *, source_stage="gold"):
    require(source_stage in {"silver", "gold"}, "invalid native source stage")
    ident(source_schema)
    tables = execute(connection, """
        SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES
        OPTION (LABEL = 'MSFlix_SAP_source_tables');""")
    columns = execute(connection, """
        SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION, DATA_TYPE,
               CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE, IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        OPTION (LABEL = 'MSFlix_SAP_source_columns');""")
    result = {}
    for name in TABLES:
        matches = [r for r in tables if r["TABLE_SCHEMA"] == source_schema
                   and r["TABLE_NAME"].casefold() == name.casefold() and r["TABLE_TYPE"] == "BASE TABLE"]
        require(len(matches) == 1, f"native Gold coordinate missing/ambiguous: {source_schema}.{name}")
        table_name = matches[0]["TABLE_NAME"]
        actual = sorted((r for r in columns if r["TABLE_SCHEMA"] == source_schema
                         and r["TABLE_NAME"] == table_name), key=lambda r: r["ORDINAL_POSITION"])
        by_name = {r["COLUMN_NAME"]: r for r in actual}
        needed = {f.name for f in selected_fields(contract, name)} | {"_SystemName", "_UpdateTimeStamp"}
        require(needed <= set(by_name), f"{source_schema}.{table_name}: native columns missing {sorted(needed-set(by_name))}")
        require(len(actual) == len(by_name), f"{name}: duplicate SQL columns")
        for field in selected_fields(contract, name):
            sql = by_name[field.name]
            kind = sql["DATA_TYPE"].lower()
            if field.ddic == "NUMC":
                require(kind in {"int", "bigint", "smallint"}, f"{name}.{field.name}: native NUMC must be integral")
            elif field.ddic in {"CHAR", "CUKY", "UNIT", "LANG"}:
                require(kind in {"varchar", "char", "nvarchar", "nchar"}
                        and (sql["CHARACTER_MAXIMUM_LENGTH"] == -1
                             or sql["CHARACTER_MAXIMUM_LENGTH"] >= field.length),
                        f"{name}.{field.name}: CHAR identifier would lose source characters")
            elif field.ddic in {"CURR", "DEC", "QUAN"}:
                require(kind in {"decimal", "numeric"} and sql["NUMERIC_SCALE"] == field.scale
                        and sql["NUMERIC_PRECISION"] == field.length,
                        f"{name}.{field.name}: exact decimal scale required")
            elif field.ddic == "DATS":
                require(kind == "date", f"{name}.{field.name}: native date required")
        require(by_name["_UpdateTimeStamp"]["DATA_TYPE"] in {"datetime2", "datetime"},
                f"{name}: native update watermark missing/invalid")
        if source_stage == "gold" and name in CUSTOM and not contract.schemas[name].financial:
            require("Key" in by_name, f"{name}: native custom dimension Key missing; BPS Gold is not qualified")
        if source_stage == "gold" and name in CUSTOM_RELATIONSHIPS:
            sk = CUSTOM_RELATIONSHIPS[name][2]
            require(sk in by_name and by_name[sk]["DATA_TYPE"] in {"int", "bigint", "smallint"},
                    f"{name}: native fact surrogate {sk} missing/invalid")
        if "Key" in by_name:
            require(by_name["Key"]["DATA_TYPE"] in {"int", "bigint", "smallint"},
                    f"{name}: native dimension Key must be integral")
        result[name] = {"schema": source_schema, "table": table_name, "columns": actual}
    return result


def source_coordinate(binding, database=None):
    return ((ident(database) + ".") if database else "") + ident(binding["schema"]) + "." + ident(binding["table"])


def projection(contract, name, binding):
    fields = selected_fields(contract, name)
    names = [f.name for f in fields] + ["NATIVE_DIMENSION_KEY", "NATIVE_UPDATE_TIMESTAMP"]
    has_key = any(c["COLUMN_NAME"] == "Key" for c in binding["columns"])
    values = [expression(f) for f in fields]
    values += ["CAST(s.[Key] AS bigint)" if has_key else "CAST(NULL AS bigint)",
               "CAST(s.[_UpdateTimeStamp] AS datetime2(6))"]
    return names, values


def source_filter(config, names):
    where = "s.[_SystemName]=" + text(config["source_system"])
    if "COMPANYCODE" in names:
        where += " AND s.[COMPANYCODE]=" + text(config["company_code"])
    return where


def source_domain_errors(contract, name):
    invalid = []
    for field in selected_fields(contract, name):
        col = "s." + ident(field.name)
        if field.ddic == "NUMC":
            invalid.append(f"({col}<0 OR {col}>={10**field.length})")
        elif field.ddic in {"CHAR", "CUKY", "UNIT", "LANG"}:
            # Do not silently truncate a CHAR ID even when its SQL type is varchar(max).
            invalid.append(f"LEN({col}+'#')-1>{field.length}")
    return " OR ".join(invalid)


def source_rows(connection, contract, bindings, config, database=None):
    rows = {}
    for name, binding in bindings.items():
        names, values = projection(contract, name, binding)
        selected = ",".join(v + " AS " + ident(n) for n, v in zip(names, values))
        where = source_filter(config, names)
        require(not execute(connection, f"SELECT TOP (1) 1 AS invalid FROM {source_coordinate(binding, database)} s "
                            f"WHERE {where} AND ({source_domain_errors(contract, name)}) "
                            f"OPTION (LABEL = '{LABEL}_source_types');"),
                name + ": source value exceeds declared CHAR/NUMC domain")
        rows[name] = execute(connection, f"SELECT {selected} FROM {source_coordinate(binding, database)} s "
                             f"WHERE {where} OPTION (LABEL = '{LABEL}_source');")
    return rows


def qualify_native_relationships(connection, bindings, config, rows, database=None):
    """Check actual Gold SKs against business keys, not just dimension existence."""
    result = {}
    for fact, (dimension, keys, sk) in CUSTOM_RELATIONSHIPS.items():
        join = " AND ".join(f"s.{ident(k)}=d.{ident(k)}" for k in (*keys, "_SystemName"))
        where = source_filter(config, [c["COLUMN_NAME"] for c in bindings[fact]["columns"]])
        actual = execute(connection, f"""
            SELECT COUNT_BIG(*) AS joined_rows,
                   SUM(CASE WHEN d.[Key] IS NULL OR d.[Key]=-1 OR s.{ident(sk)} IS NULL
                                 OR s.{ident(sk)}<>d.[Key]
                            THEN CAST(1 AS bigint) ELSE CAST(0 AS bigint) END) AS invalid_rows
            FROM {source_coordinate(bindings[fact], database)} s
            LEFT JOIN {source_coordinate(bindings[dimension], database)} d ON {join}
            WHERE {where} OPTION (LABEL = '{LABEL}_relationships');
        """)
        require(actual == [{"joined_rows": len(rows[fact]), "invalid_rows": 0}],
                f"{fact}: native surrogate relationship missing, sentinel, mismatched or multiplicative")
        result[fact] = {"dimension": dimension, "keys": list(keys), "surrogate_column": sk,
                        **actual[0]}
    return result


def index(rows, keys, label):
    result = {}
    for row in rows:
        key = tuple(row[k] for k in keys)
        # SAP initials are valid in hierarchy PARENTNODE and certain financial status PKs.
        require(all(v is not None for v in key), label + ": null native business PK")
        require(key not in result, label + ": duplicate native business PK " + repr(key))
        result[key] = row
    return result


def as_date(value):
    return value.date() if isinstance(value, datetime) else value


def qualify(rows, contract, config, references, totals, customers, contents, distributors, *, source_stage="gold"):
    """Independent SQL-read qualification; no expected/generated source rows."""
    require(source_stage in {"silver", "gold"}, "invalid native source stage")
    indexes = {n: index(rows[n], contract.schemas[n].keys, n) for n in TABLES}
    for n in TABLES:
        require(rows[n], n + ": native " + source_stage + " table empty")
        for r in rows[n]:
            require(r["NATIVE_UPDATE_TIMESTAMP"] is not None, n + ": missing native watermark")
            if source_stage == "gold" and n in CUSTOM and not contract.schemas[n].financial:
                require(type(r["NATIVE_DIMENSION_KEY"]) is int, n + ": missing actual native dimension Key")
            for f in selected_fields(contract, n):
                v = r[f.name]
                if f.ddic == "NUMC" and v is not None:
                    require(isinstance(v, str) and len(v) == f.length and v.isdigit(),
                            f"{n}.{f.name}: invalid NUMC conversion")
                if f.ddic in {"CURR", "DEC", "QUAN"}:
                    require(isinstance(v, Decimal) and v.is_finite(), f"{n}.{f.name}: exact source decimal required")
    customer_by_key = index(customers, ("customer_key",), "existing gold.dim_customer")
    content_by_key = index(contents, ("content_key",), "existing gold.dim_content")
    distributor_by_key = index(distributors, ("distributor_key",), "existing gold.dim_distributor")
    ref_customers = {r["customer_key"]: r for r in references["customers"]}
    links = rows["ZMSF_CUSTOMER_LINK"]
    require(len(links) == len(config["customers"]), "customer crosswalk count")
    link_by_customer = {r["CUSTOMER"]: r for r in links}
    for selection in config["customers"]:
        link = link_by_customer.get(selection["sap_customer"])
        ref = ref_customers[selection["customer_key"]]
        actual = customer_by_key.get((selection["customer_key"],))
        require(link and actual and link["CUSTOMER_KEY"] == actual["customer_key"]
                and link["SALESFORCE_CONTACT_ID"] == actual["source_customer_id"] == ref["salesforce_contact_id"],
                "customer_key + source_customer_id must match the observed existing CRM customer")
    company = rows["I_COMPANYCODE"]
    require(len(company) == 1 and company[0]["CHARTOFACCOUNTS"] == CHART
            and company[0]["CURRENCY"] == "EUR", "company/chart/currency mismatch")
    accounts = {(r["CHARTOFACCOUNTS"], r["GLACCOUNT"]) for r in rows["I_GLACCOUNTINCHARTOFACCOUNTS"]}
    require(accounts == {(CHART, a[0]) for a in ACCOUNTS.values()}, "unknown/missing MSFX account roles")
    suppliers = rows["I_SUPPLIER"]
    require(len(suppliers) == 1 and suppliers[0]["SUPPLIER"] == config["supplier_id"]
            and suppliers[0]["SUPPLIERNAME"] == config["supplier_name"]
            and "fictional" in suppliers[0]["SUPPLIERNAME"].lower(), "supplier is not the approved fictional partner")
    start, end = period(config)
    fiscal = rows["I_FISCALPERIODFORVARIANT"]
    require(len(fiscal) == 12, "full native fiscal calendar (12 periods) required")
    for month in range(1, 13):
        found = [r for r in fiscal if r["FISCALYEAR"] == str(start.year) and r["FISCALYEARVARIANT"] == "K4"
                 and r["FISCALPERIOD"] == f"{month:03d}"]
        require(len(found) == 1 and found[0]["FISCALPERIODSTARTDATE"] == date(start.year, month, 1)
                and found[0]["FISCALPERIODENDDATE"] == date(start.year, month, calendar.monthrange(start.year, month)[1]),
                "native fiscal calendar gap/overlap")
    plans = indexes["ZMSF_PLAN"]
    rights = indexes["ZMSF_RIGHTS_CONTRACT"]
    subs = indexes["ZMSF_SUBSCRIPTION"]
    require(len(plans) == len(rights) == 1 and len(subs) == len(links), "plan/contract/subscription counts")
    plan = next(iter(plans.values()))
    right = next(iter(rights.values()))
    require(plan["PLAN_ID"] == config["plan_id"] and plan["VERSION"] == "0001"
            and (plan["CONTRACT_ID"], plan["CONTRACT_VERSION"]) in rights
            and plan["MONTHLY_NET"] == Decimal(config["monthly_net"])
            and plan["VAT_RATE"] == Decimal(config["vat_rate"]) and plan["CURRENCY"] == "EUR",
            "approved subscription formula/version mismatch")
    require(right["CONTRACT_ID"] == config["contract_id"] and right["VERSION"] == "0001"
            and right["SUPPLIER"] == config["supplier_id"] and right["SIMULATION_ONLY"] == "X"
            and right["CURRENCY"] == "EUR" and right["FIXED_NET"] == Decimal(config["fixed_content_cost"])
            and right["REVENUE_SHARE"] == Decimal(config["content_revenue_share"])
            and right["REVENUE_BASIS"] == "NET_SUBSCRIPTION_BILLINGS_AFTER_CREDITS",
            "fictional content contract formula/version mismatch")
    stop = date(end.year + (end.month == 12), end.month % 12 + 1, 1)
    for r in [plan, right]:
        require(r["VALID_FROM"] == start and r["VALID_TO_EXCLUSIVE"] == stop, "contract/plan validity mismatch")
    require({r["CUSTOMER"] for r in subs.values()} == set(link_by_customer), "subscription customer grain")
    for r in subs.values():
        require((r["PLAN_ID"], r["PLAN_VERSION"]) in plans and r["STATUS"] == "ACTIVE"
                and r["SERVICE_FROM"] == start and r["SERVICE_TO_EXCLUSIVE"] == stop,
                "unresolved subscription plan/service interval")
    coverage = rows["ZMSF_RIGHTS_COVERAGE"]
    require(len(coverage) == len(config["content_keys"])
            and {r["CONTENT_KEY"] for r in coverage} == set(config["content_keys"]), "coverage grain mismatch")
    for r in coverage:
        content = content_by_key.get((r["CONTENT_KEY"],))
        require(content and content["distributor_key"] == r["CATALOG_DISTRIBUTOR_KEY"]
                and (r["CATALOG_DISTRIBUTOR_KEY"],) in distributor_by_key
                and (r["CONTRACT_ID"], r["VERSION"]) in rights and r["SIMULATION_ONLY"] == "X"
                and r["CATALOG_SAP_PARTNER_CODE"] is None and r["USAGE_TYPE"] == "SVOD"
                and r["TERRITORY"] == config["territory"] and r["VALID_FROM"] == start
                and r["VALID_TO_EXCLUSIVE"] == stop,
                "unresolved catalog reference or fictional coverage represented as a commercial license")
    gl = rows["I_GLACCOUNTLINEITEMRAWDATA"]
    operational = rows["I_OPERATIONALACCTGDOCITEM"]
    require(len(gl) == len(operational) == totals["journal_lines"], "GL/BSEG journal line counts")
    projected = [{k: r[k] for k in (f.name for f in selected_fields(contract, "I_OPERATIONALACCTGDOCITEM"))}
                 for r in gl]
    op_payload = [{f.name: r[f.name] for f in selected_fields(contract, "I_OPERATIONALACCTGDOCITEM")} for r in operational]
    require(fingerprint(projected) == fingerprint(op_payload), "BSEG must be the same journal projection, not additional revenue")
    balances = {role: ZERO for role in ACCOUNTS}
    role_by_account = {a[0]: role for role, a in ACCOUNTS.items()}
    docs = {}
    journal_by_item = index(operational, ("COMPANYCODE", "FISCALYEAR", "ACCOUNTINGDOCUMENT",
                                        "ACCOUNTINGDOCUMENTITEM"), "journal item")
    for r in gl:
        require(r["SOURCELEDGER"] == "0L" and r["CHARTOFACCOUNTS"] == CHART
                and r["TRANSACTIONCURRENCY"] == r["COMPANYCODECURRENCY"] == "EUR"
                and r["AMOUNTINTRANSACTIONCURRENCY"] == r["AMOUNTINCOMPANYCODECURRENCY"],
                "mixed currency/ledger or changed company money")
        require(all(r[c] == "EUR" and r[a] == r["AMOUNTINTRANSACTIONCURRENCY"] for c, a in (
            ("FUNCTIONALCURRENCY", "AMOUNTINFUNCTIONALCURRENCY"),
            ("ADDITIONALCURRENCY1", "AMOUNTINADDITIONALCURRENCY1"),
            ("GLOBALCURRENCY", "AMOUNTINGLOBALCURRENCY"))), "mixed native currency projections")
        require(r["LEDGERGLLINEITEM"] == r["ACCOUNTINGDOCUMENTITEM"].zfill(6)
                and r["LEDGERFISCALYEAR"] == r["FISCALYEAR"], "leading-ledger operational item mapping differs")
        amount = r["AMOUNTINTRANSACTIONCURRENCY"]
        require(amount != ZERO and ((amount > ZERO and r["DEBITCREDITCODE"] == "S")
                                    or (amount < ZERO and r["DEBITCREDITCODE"] == "H")), "native journal sign mismatch")
        require(start <= r["POSTINGDATE"] <= end and r["FISCALYEAR"] == str(start.year)
                and r["COMPANYCODE"] == config["company_code"] and r["FISCALYEARVARIANT"] == "K4"
                and r["FISCALYEARPERIOD"] == f"{start.year:04d}{start.month:03d}"
                and r["FISCALPERIOD"] == f"{start.month:03d}", "journal is not the qualified scenario period")
        role = role_by_account.get(r["GLACCOUNT"])
        require(role is not None, "unmapped native GL account")
        require((r["FINANCIALACCOUNTTYPE"] == "D") == (role == "receivables")
                and (r["FINANCIALACCOUNTTYPE"] == "K") == (role == "payables"), "AR/AP account role mismatch")
        require(not r["CUSTOMER"] or r["CUSTOMER"] in link_by_customer, "unresolved journal customer")
        require(not r["SUPPLIER"] or r["SUPPLIER"] == config["supplier_id"], "unresolved journal supplier")
        require((role != "receivables" or r["CUSTOMER"]) and (role != "payables" or r["SUPPLIER"]),
                "missing journal business partner")
        require((role == "receivables" or not r["CUSTOMER"]) and (role == "payables" or not r["SUPPLIER"])
                and r["FINANCIALACCOUNTTYPE"] == {"receivables": "D", "payables": "K"}.get(role, "S"),
                "journal partner present on another account role")
        balances[role] += amount
        key = (r["COMPANYCODE"], r["FISCALYEAR"], r["ACCOUNTINGDOCUMENT"])
        docs.setdefault(key, []).append(r)
    require(len(docs) == totals["accounting_documents"] and all(
        sum((r["AMOUNTINTRANSACTIONCURRENCY"] for r in items), ZERO) == ZERO
        and len({r["ACCOUNTINGDOCUMENTTYPE"] for r in items}) == 1
        and len({r["POSTINGDATE"] for r in items}) == 1 for items in docs.values()),
        "full ledger/document/item journal does not balance")
    as_of = max(r["POSTINGDATE"] for r in gl)
    require(as_of == totals["as_of"], "source as-of is not the complete month-end scenario")
    kinds = {kind: sum(items[0]["ACCOUNTINGDOCUMENTTYPE"] == kind for items in docs.values())
             for kind in ("DR", "DG", "DZ", "DA", "SA", "KR", "KZ")}
    require(kinds == {"DR": 3, "DG": 1, "DZ": 2, "DA": 1, "SA": 1, "KR": 1, "KZ": 1},
            "approved invoice/credit/payment/recognition FI document counts differ")
    recognition = next(items for items in docs.values() if items[0]["ACCOUNTINGDOCUMENTTYPE"] == "SA")
    require(len(recognition) == 2 and recognition[0]["POSTINGDATE"] == as_of
            and {r["GLACCOUNT"] for r in recognition} == {ACCOUNTS["deferred_revenue"][0], ACCOUNTS["revenue"][0]},
            "monthly recognition must be deferred-liability release, not cash or orders")
    cleared = {}
    for r in operational:
        if r["CLEARINGDATE"] is not None:
            require(r["FINANCIALACCOUNTTYPE"] in {"D", "K"} and r["CLEARINGACCOUNTINGDOCUMENT"]
                    and r["CLEARINGDOCFISCALYEAR"] == str(start.year)
                    and r["POSTINGDATE"] <= r["CLEARINGDATE"] <= as_of, "invalid actual clearing fields")
            key = (r["COMPANYCODE"], r["CLEARINGDOCFISCALYEAR"], r["CLEARINGACCOUNTINGDOCUMENT"])
            require(key in docs and any(x["CUSTOMER"] == r["CUSTOMER"] and x["SUPPLIER"] == r["SUPPLIER"]
                                       and x["POSTINGDATE"] == r["CLEARINGDATE"] for x in docs[key]),
                    "clearing document missing from same partner journal/date")
            cleared.setdefault((key, r["FINANCIALACCOUNTTYPE"], r["CUSTOMER"], r["SUPPLIER"]), []).append(r)
        else:
            require(not r["CLEARINGACCOUNTINGDOCUMENT"] and r["CLEARINGDOCFISCALYEAR"] is None,
                    "partial/uncleared item falsely carries a clearing document")
    require(all(sum((r["AMOUNTINTRANSACTIONCURRENCY"] for r in items), ZERO) == ZERO
                for items in cleared.values()), "cleared groups do not settle to zero")
    ar = [r for r in operational if r["FINANCIALACCOUNTTYPE"] == "D" and r["CLEARINGDATE"] is None]
    ap = [r for r in operational if r["FINANCIALACCOUNTTYPE"] == "K" and r["CLEARINGDATE"] is None]
    gross = Decimal(config["monthly_net"]) + money(Decimal(config["monthly_net"]) * Decimal(config["vat_rate"]))
    refund = Decimal(config["credit_net"]) + money(Decimal(config["credit_net"]) * Decimal(config["vat_rate"]))
    supplier_paid = money((totals["content_cost"] + money(totals["content_cost"] * Decimal(config["vat_rate"]))) / 2)
    roles = {r["role"]: r["sap_customer"] for r in config["customers"]}
    payment_docs = {kind: [items for items in docs.values() if items[0]["ACCOUNTINGDOCUMENTTYPE"] == kind]
                    for kind in ("DZ", "DA", "KZ")}
    require([len(payment_docs[k]) for k in ("DZ", "DA", "KZ")] == [2, 1, 1], "collection/refund/payment journal counts")
    for kind, expected_bank in (("DZ", gross), ("DA", -refund), ("KZ", -supplier_paid)):
        for items in payment_docs[kind]:
            bank = [r for r in items if r["GLACCOUNT"] == ACCOUNTS["bank"][0]]
            partner = [r for r in items if r["FINANCIALACCOUNTTYPE"] in {"D", "K"}]
            require(len(items) == 2 and len(bank) == len(partner) == 1
                    and bank[0]["AMOUNTINTRANSACTIONCURRENCY"] == expected_bank,
                    "collection/refund/supplier payment differs from the same signed journal")
            r = partner[0]
            referenced = journal_by_item.get((r["COMPANYCODE"], r["INVOICEREFERENCEFISCALYEAR"],
                                              r["INVOICEREFERENCE"], r["INVOICEITEMREFERENCE"]))
            require(referenced and referenced["CUSTOMER"] == r["CUSTOMER"] and referenced["SUPPLIER"] == r["SUPPLIER"],
                    "payment/refund invoice reference missing or another partner")
            require(referenced["ACCOUNTINGDOCUMENT"] != r["ACCOUNTINGDOCUMENT"]
                    and referenced["ACCOUNTINGDOCUMENTTYPE"] == {"DZ": "DR", "DA": "DG", "KZ": "KR"}[kind]
                    and referenced["FINANCIALACCOUNTTYPE"] == r["FINANCIALACCOUNTTYPE"]
                    and referenced["AMOUNTINTRANSACTIONCURRENCY"] * r["AMOUNTINTRANSACTIONCURRENCY"] < ZERO,
                    "payment/refund must reference an opposite-sign invoice/credit of the expected type, not itself")
            if kind == "DA":
                require(r["CUSTOMER"] == roles["paid_with_credit"], "credit refunded to the wrong customer")
            if kind == "KZ":
                require(r["SUPPLIER"] == config["supplier_id"] and r["CLEARINGDATE"] is None,
                        "partial supplier payment must remain genuinely open")
    require({r["CUSTOMER"] for items in payment_docs["DZ"] for r in items if r["CUSTOMER"]}
            == {roles["paid"], roles["paid_with_credit"]}, "wrong collected customers")
    for selection in config["customers"]:
        outstanding = sum((r["AMOUNTINTRANSACTIONCURRENCY"] for r in ar if r["CUSTOMER"] == selection["sap_customer"]), ZERO)
        require(outstanding == (gross if selection["role"] == "unpaid" else ZERO), "wrong customer AR current balance")
    bills = rows["C_BILLINGDOCITEMBASICDEX_1"]
    bill_links = indexes["ZMSF_BILLING_LINK"]
    require(len(bills) == len(bill_links) == 4 and set(indexes["C_BILLINGDOCITEMBASICDEX_1"]) == set(bill_links),
            "four billing items require one native billing link each")
    require({r["SOLDTOPARTY"] for r in bills if r["BILLINGDOCUMENTCATEGORY"] == "M"}
            == set(link_by_customer), "one initial subscription invoice per customer required")
    for r in bills:
        key = (r["BILLINGDOCUMENT"], r["BILLINGDOCUMENTITEM"])
        link = bill_links[key]
        sub = subs.get((link["SUBSCRIPTION_ID"],))
        doc = docs.get((r["COMPANYCODE"], r["FISCALYEAR"], r["ACCOUNTINGDOCUMENT"]))
        require(sub and doc and sub["CUSTOMER"] == r["SOLDTOPARTY"] and r["PRODUCT"] == plan["PRODUCT"]
                and r["TRANSACTIONCURRENCY"] == "EUR" and r["TAXAMOUNT"] == money(r["NETAMOUNT"] * plan["VAT_RATE"])
                and r["GROSSAMOUNT"] == r["NETAMOUNT"] + r["TAXAMOUNT"], "billing partner/product/signed tax mismatch")
        credit = r["BILLINGDOCUMENTCATEGORY"] == "O"
        require((credit and r["NETAMOUNT"] == -Decimal(config["credit_net"]))
                or (r["BILLINGDOCUMENTCATEGORY"] == "M" and r["NETAMOUNT"] == Decimal(config["monthly_net"])),
                "billing sign/category/approved formula mismatch")
        require(link["ORDER_ID"] is None and link["SERVICE_FROM"] == start and link["SERVICE_TO_EXCLUSIVE"] == stop,
                "subscription billing must not invent commercial order revenue")
        if credit:
            original = indexes["C_BILLINGDOCITEMBASICDEX_1"].get((link["ORIGINAL_BILLINGDOCUMENT"], r["BILLINGDOCUMENTITEM"]))
            require(original and original["SOLDTOPARTY"] == r["SOLDTOPARTY"]
                    and original["BILLINGDOCUMENTCATEGORY"] == "M"
                    and r["SOLDTOPARTY"] == roles["paid_with_credit"], "credit original invoice/customer link missing")
        else:
            require(link["ORIGINAL_BILLINGDOCUMENT"] is None, "invoice unexpectedly references a credit")
        bill_balances = {role: sum((x["AMOUNTINTRANSACTIONCURRENCY"] for x in doc
                                   if x["GLACCOUNT"] == a[0]), ZERO) for role, a in ACCOUNTS.items()}
        require(all(x["BILLINGDOCUMENT"] == r["BILLINGDOCUMENT"] for x in doc)
                and bill_balances["receivables"] == r["GROSSAMOUNT"]
                and bill_balances["deferred_revenue"] == -r["NETAMOUNT"]
                and bill_balances["output_vat"] == -r["TAXAMOUNT"],
                "billing amounts do not reconcile to same native FI document")
    charges = rows["ZMSF_CONTRACT_CHARGE"]
    require(len(charges) == 2 and {r["CHARGE_TYPE"] for r in charges} == {"FIXED", "VARIABLE"},
            "two native contract charge items required")
    for r in charges:
        require((r["CONTRACT_ID"], r["VERSION"]) in rights and r["PERIOD_START"] == start
                and (r["COMPANYCODE"], r["FISCALYEAR"], r["ACCOUNTINGDOCUMENT"]) in docs,
                "contract charge does not reference its FI document")
        fixed = r["CHARGE_TYPE"] == "FIXED"
        require(r["BASIS_NET"] == (right["FIXED_NET"] if fixed else totals["net_billings"])
                and r["RATE"] == (Decimal(1) if fixed else right["REVENUE_SHARE"])
                and r["CHARGE_NET"] == money(r["BASIS_NET"] * r["RATE"]),
                "contract charges/formula do not reconcile")
    require(len({r["ACCOUNTINGDOCUMENT"] for r in charges}) == 1
            and sum((r["CHARGE_NET"] for r in charges), ZERO) == balances["content_cost"],
            "contract charge FI grain/content expense mismatch")
    charge_doc = docs[(charges[0]["COMPANYCODE"], charges[0]["FISCALYEAR"], charges[0]["ACCOUNTINGDOCUMENT"])]
    require(sum((r["AMOUNTINTRANSACTIONCURRENCY"] for r in charge_doc
                 if r["GLACCOUNT"] == ACCOUNTS["content_cost"][0]), ZERO) == totals["content_cost"]
            and charge_doc[0]["ACCOUNTINGDOCUMENTTYPE"] == "KR", "contract charges point to another FI expense document")
    result = {
        "as_of": as_of, "currency": "EUR", "accounting_documents": len(docs), "journal_lines": len(gl),
        "net_billings": sum((r["NETAMOUNT"] for r in bills), ZERO),
        "recognized_revenue": -balances["revenue"], "deferred_revenue": -balances["deferred_revenue"],
        "content_cost": balances["content_cost"], "content_contribution": -balances["revenue"]-balances["content_cost"],
        "receivables": sum((r["AMOUNTINTRANSACTIONCURRENCY"] for r in ar), ZERO),
        "payables": -sum((r["AMOUNTINTRANSACTIONCURRENCY"] for r in ap), ZERO),
        "net_bank_movement": balances["bank"], "net_vat_liability": -balances["output_vat"]-balances["input_vat"],
        "open_customer_items": len(ar), "open_supplier_items": len(ap),
    }
    require(result == totals and result["receivables"] == balances["receivables"]
            and result["payables"] == -balances["payables"]
            and result["net_billings"] == -balances["deferred_revenue"]-balances["revenue"],
            "independent source SQL totals differ from approved scenario/GL/open items")
    return result


def reference_rows(connection):
    return (
        execute(connection, "SELECT customer_key, source_customer_id FROM gold.dim_customer;"),
        execute(connection, "SELECT content_key, distributor_key FROM gold.dim_content;"),
        execute(connection, "SELECT distributor_key FROM gold.dim_distributor;"),
    )


def domain_ddl(contract):
    batches = []
    for name, table in TABLES.items():
        columns = [f"{ident(k)} {v} NOT NULL" for k, v in STAMPS.items()]
        columns += [f"{ident(f.name)} {sql_type(f)} {'NOT NULL' if f.key else 'NULL'}"
                    for f in selected_fields(contract, name)]
        columns += ["[NATIVE_DIMENSION_KEY] bigint NULL", "[NATIVE_UPDATE_TIMESTAMP] datetime2(6) NOT NULL"]
        batches.append(f"IF OBJECT_ID('gold.{table}','U') IS NULL\n"
                       f"CREATE TABLE gold.{ident(table)} (\n    " + ",\n    ".join(columns) + "\n);")
    return "\n".join(batches)


def checked(connection, query):
    return execute(connection, "BEGIN TRY\n" + query + "\nEND TRY\n"
                   "BEGIN CATCH\n IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;\n THROW;\nEND CATCH;")


def scope(config):
    return (f"source_system={text(config['source_system'])} AND company_scope={text(config['company_code'])}"
            f" AND scenario_id={text(config['scenario_id'])}")


def target_schema(connection, contract):
    actual = execute(connection, "SELECT TABLE_NAME,COLUMN_NAME,DATA_TYPE,CHARACTER_MAXIMUM_LENGTH,"
                     "NUMERIC_PRECISION,NUMERIC_SCALE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='gold';")
    tables = {
        table: {**STAMPS, **{f.name: sql_type(f) for f in selected_fields(contract, name)},
                "NATIVE_DIMENSION_KEY": "bigint", "NATIVE_UPDATE_TIMESTAMP": "datetime2(6)"}
        for name, table in TABLES.items()
    }
    tables["sap_publication"] = PUBLICATION_TYPES
    tables["sap_writer_guard"] = {"resource_name": "varchar(128)", "generation": "bigint"}
    for table, expected_types in tables.items():
        columns = {r["COLUMN_NAME"]: r for r in actual if r["TABLE_NAME"] == table}
        require(set(columns) == set(expected_types), table + ": target COLUMNCOUNT/schema drift; no automatic migration")
        for col, sql in expected_types.items():
            row = columns[col]
            require(row["DATA_TYPE"] == sql.split("(")[0], table + "." + col + ": target type drift")
            if sql.startswith("varchar"):
                require(row["CHARACTER_MAXIMUM_LENGTH"] == int(sql[8:-1]), table + "." + col + ": target CHAR drift")
            if sql.startswith("decimal"):
                precision, scale = map(int, sql[8:-1].split(","))
                require((row["NUMERIC_PRECISION"], row["NUMERIC_SCALE"]) == (precision, scale),
                        table + "." + col + ": target decimal drift")


def view_batches():
    sql = (SQL_ROOT / "sap-views.sql").read_text(encoding="utf-8")
    for role, account in ACCOUNTS.items():
        sql = sql.replace("{{ACCOUNT_" + role.upper() + "}}", text(account[0]))
    sql = sql.replace("{{CHART}}", text(CHART))
    require("{{" not in sql, "unresolved SAP reporting account role")
    return [batch.strip() for batch in sql.split("-- @batch") if batch.strip()]


def publish(connection, contract, bindings, source_database, config, run_id, qualification, rows, proof):
    """One SAP writer resource; snapshot write conflicts abort, never retry silently."""
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", run_id), "invalid run_id")
    filter_sql = scope(config)
    stamp_values = [text(config["source_system"]), text(config["company_code"]), text(config["scenario_id"]),
                    text(run_id), "CAST(" + text(qualification["as_of"].isoformat()) + " AS date)"]
    try:
        # Fabric Warehouse has no XACT_ABORT; checked() rolls back SQL errors.
        checked(connection, "SET NOCOUNT ON; BEGIN TRANSACTION;\n"
                + (SQL_ROOT / "sap-ddl.sql").read_text(encoding="utf-8").replace("{{SAP_DOMAIN_DDL}}", domain_ddl(contract)))
        target_schema(connection, contract)
        for name, table in TABLES.items():
            names, values = projection(contract, name, bindings[name])
            source = source_coordinate(bindings[name], source_database)
            where = source_filter(config, names)
            all_names = ",".join(ident(n) for n in [*STAMPS, *names])
            selected = ",".join(stamp_values + values)
            keys = ",".join(ident(k) for k in contract.schemas[name].keys)
            checked(connection, f"""
                IF EXISTS (SELECT 1 FROM {source} s WHERE {where} AND ({source_domain_errors(contract, name)}))
                    THROW 51103, 'Native source CHAR/NUMC domain changed; no truncation allowed', 1;
                DELETE FROM gold.{ident(table)} WHERE {filter_sql};
                INSERT INTO gold.{ident(table)} ({all_names})
                SELECT {selected} FROM {source} s WHERE {where} OPTION (LABEL = '{LABEL}');
                IF (SELECT COUNT_BIG(*) FROM gold.{ident(table)} WHERE {filter_sql})<>{len(rows[name])}
                    THROW 51101, 'SAP target count differs from qualified native Gold', 1;
                IF EXISTS (SELECT {keys} FROM gold.{ident(table)} WHERE {filter_sql}
                           GROUP BY {keys} HAVING COUNT_BIG(*)<>1)
                    THROW 51102, 'SAP target business PK duplicate', 1;
            """)
            copied = execute(connection, f"SELECT {','.join(ident(n) for n in names)} FROM gold.{ident(table)} "
                             f"WHERE {filter_sql} OPTION (LABEL = '{LABEL}_reconcile');")
            require(fingerprint(copied) == fingerprint(rows[name]),
                    table + ": target values/counts/sums changed since qualified source read; rollback")
        # Reference masters are read only, including inside the target transaction.
        qualify(rows, contract, config, proof["references"], qualification, *reference_rows(connection))
        require(qualify_native_relationships(connection, bindings, config, rows, source_database)
                == proof["native_relationships"], "native surrogate relationships changed; rollback")
        for batch in view_batches():
            checked(connection, "EXEC(" + batch_literal(batch) + ");")
        columns = ["source_system", "company_scope", "scenario_id", "run_id", "as_of", "source_workspace_id",
                   "source_item_id", "source_endpoint_id", "source_database", "b2s_job_id", "s2g_job_id",
                   "input_sha256", "catalog_sha256", "data_sha256", "journal_lines", "accounting_documents",
                   "net_billings", "recognized_revenue", "content_cost", "receivables", "payables",
                   "net_bank_movement", "net_vat_liability"]
        values = stamp_values + [text(proof[k]) for k in ("workspace_id", "source_item_id", "source_endpoint_id", "database")]
        values += [text(proof["jobs"][s]["job_id"]) for s in ("b2s", "s2g")]
        values += [text(proof[k]) for k in ("input_sha256", "catalog_sha256", "data_sha256")]
        values += [str(qualification[k]) for k in columns[14:]]
        checked(connection, f"DELETE FROM gold.sap_publication WHERE {filter_sql};\n"
                f"INSERT INTO gold.sap_publication ({','.join(ident(c) for c in columns)},completed_at) "
                f"SELECT {','.join(values)},SYSUTCDATETIME();")
        marker = execute(connection, "SELECT run_id,data_sha256 FROM gold.sap_publication WHERE " + filter_sql + ";")
        require(marker == [{"run_id": run_id, "data_sha256": proof["data_sha256"]}], "target SAP publication marker mismatch")
        checked(connection, "COMMIT TRANSACTION;")
    except Exception:
        execute(connection, "IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;")
        raise
    return {"mode": "published", "native_bps_gold": True, "synthetic": True, "warehouse": "MSFlixGold",
            "run_id": run_id, "source_database": source_database, "tables": {TABLES[n]: len(r) for n, r in rows.items()},
            "reconciliation": qualification, "shared_masters_mutated": False}


def inspect_silver(target, config, references, metadata, evidence, catalog_path, run_id, source_schema="dbo"):
    contract, totals, input_hash = inputs(config, references, metadata)
    jobs = local_jobs(target, evidence, ("b2s",))
    require(catalog_path.resolve() == silver_evidence_path(evidence, jobs["b2s"]["job_id"]).resolve(),
            "Silver catalog must use the job-qualified evidence path")
    require(not catalog_path.exists(), "qualified Silver evidence already exists; do not overwrite it")
    client = ScopedClient(target)
    live_jobs(client, jobs)
    source, warehouse = discover(client, "silver")
    with closing(connect(client, source, lakehouse=True)) as source_connection, closing(connect(client, warehouse)) as target_connection:
        bindings = catalog(source_connection, contract, source_schema, source_stage="silver")
        actual = source_rows(source_connection, contract, bindings, config)
        reconciliation = qualify(actual, contract, config, references, totals, *reference_rows(target_connection),
                                 source_stage="silver")
        require(catalog(source_connection, contract, source_schema, source_stage="silver") == bindings,
                "Silver COLUMNCOUNT/schema drift during read")
        live_jobs(client, jobs)
        proof = {
            "version": VERSION, "source_stage": "silver", "run_id": run_id,
            "workspace_id": target["workspace_id"], "source_item_id": source["id"],
            "source_endpoint_id": source["properties"]["sqlEndpointProperties"]["id"],
            "jobs": jobs, "input_sha256": input_hash, "catalog_sha256": signature(bindings),
            "data_sha256": signature({n: fingerprint(r) for n, r in actual.items()}),
            "data_verified": True, "reconciliation": canonical(reconciliation),
        }
        _save(catalog_path, proof)
        return {"mode": "silver_qualified_only", "warehouse_written": False,
                "catalog": str(catalog_path), "reconciliation": reconciliation}


def run(target, config, references, metadata, evidence, catalog_path, run_id, source_schema="dbo", inspect=False):
    contract, totals, input_hash = inputs(config, references, metadata)
    jobs = local_jobs(target, evidence)
    pinned = None if inspect else read_json(catalog_path)
    if pinned is not None:
        require(pinned.get("version") == VERSION and pinned.get("run_id") == run_id
                and pinned.get("input_sha256") == input_hash and pinned.get("jobs") == jobs,
                "qualified catalog/run/config/native jobs changed; inspect source again explicitly")
    client = ScopedClient(target)
    live_jobs(client, jobs)
    source, warehouse = discover(client)
    with closing(connect(client, source, lakehouse=True)) as source_connection, closing(connect(client, warehouse)) as target_connection:
        db_row = execute(source_connection, "SELECT DB_NAME() AS database_name;")
        require(len(db_row) == 1, "source DB_NAME discovery failed")
        database = db_row[0]["database_name"]
        ident(database)
        bindings = catalog(source_connection, contract, source_schema)
        actual = source_rows(source_connection, contract, bindings, config)
        reconciliation = qualify(actual, contract, config, references, totals, *reference_rows(target_connection))
        relationships = qualify_native_relationships(source_connection, bindings, config, actual)
        proof = {
            "version": VERSION, "run_id": run_id, "workspace_id": target["workspace_id"],
            "source_item_id": source["id"], "source_endpoint_id": source["properties"]["sqlEndpointProperties"]["id"],
            "target_item_id": warehouse["id"], "database": database, "schema": source_schema,
            "jobs": jobs, "input_sha256": input_hash, "bindings": bindings,
            "catalog_sha256": signature(bindings), "data_sha256": signature({n: fingerprint(r) for n, r in actual.items()}),
            "reconciliation": canonical(reconciliation), "native_relationships": relationships,
        }
        # Detect a metadata change during bounded source qualification.
        require(catalog(source_connection, contract, source_schema) == bindings, "source COLUMNCOUNT/schema drift during read")
        if inspect:
            require(not catalog_path.exists(), "qualified catalog already exists; use a new explicit path")
            catalog_path.parent.mkdir(parents=True, exist_ok=True)
            with catalog_path.open("x", encoding="utf-8") as stream:
                json.dump(canonical(proof), stream, indent=2)
                stream.write("\n")
            return {"mode": "source_qualified_only", "warehouse_written": False, "catalog": str(catalog_path),
                    "source_database": database, "reconciliation": reconciliation}
        require(canonical(proof) == pinned, "native source coordinate/COLUMNCOUNT/data changed since explicit qualification")
        live_jobs(client, jobs)
        return publish(target_connection, contract, bindings, database, config, run_id,
                       reconciliation, actual, {**proof, "references": references})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--references", type=Path, default=DEFAULT_REFERENCES)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--processing-evidence", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-schema", default="dbo")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--inspect-source", action="store_true")
    mode.add_argument("--inspect-silver", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        target = load_target(args.target)
        config, references = read_json(args.config), read_json(args.references)
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", args.run_id), "invalid run_id")
        if args.inspect_silver:
            result = inspect_silver(target, config, references, args.metadata, args.processing_evidence,
                                    args.catalog, args.run_id, args.source_schema)
        elif not (args.inspect_source or args.apply):
            _, totals, _ = inputs(config, references, args.metadata)
            result = {"mode": "offline_preview", "warehouse_written": False, "expected": totals,
                      "source": "bps_gold_" + target["system_suffix"], "target": "MSFlixGold",
                      "tables": TABLES, "gates": ["Completed local + live b2s/s2g jobs", "exact native SQL catalog",
                          "independent source reconciliation", "existing CRM/catalog references",
                          "native custom surrogate relationships", "qualified catalog unchanged",
                          "transactional target reconciliation"]}
        else:
            result = run(target, config, references, args.metadata, args.processing_evidence,
                         args.catalog, args.run_id, args.source_schema, args.inspect_source)
    except (ValueError, OSError, DeploymentError) as exc:
        parser.exit(2, f"SAP Warehouse publication failed; no success claimed: {exc}\n")
    print(json.dumps(canonical(result), indent=2))


if __name__ == "__main__":
    main()
