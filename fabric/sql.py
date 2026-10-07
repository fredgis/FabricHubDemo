"""Standalone TDS runner; credentials stay in the approved Azure CLI cache."""
import re
import struct
from urllib.parse import urlparse

from fabric.build import ROOT
from fabric.contracts import ENTITIES, GOLD_TABLES, LINKS
from fabric.rest import DeploymentError, token


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", value):
        raise DeploymentError("SQL database identifier must be a validated display name")
    return "[" + value + "]"


def literal(value):
    if not isinstance(value, str) or len(value) > 128 or any(ord(c) < 32 for c in value):
        raise DeploymentError("Invalid SQL literal input")
    return "'" + value.replace("'", "''") + "'"


def render_load(cfg, silver):
    currency_rows = []
    for currency, exponent in cfg["currency_exponents"].items():
        if not re.fullmatch("[A-Z]{3}", currency) or type(exponent) is not int or not 0 <= exponent <= 4:
            raise DeploymentError("Invalid configured currency exponent")
        currency_rows.append(f"({literal(currency)},{exponent})")
    if not currency_rows or not cfg.get("commercial_statuses"):
        raise DeploymentError("Explicit currency exponents/commercial_statuses required")
    substitutions = {
        "{{SILVER_DATABASE}}": identifier(silver["displayName"]),
        "{{RUN_ID}}": literal(cfg["run_id"]),
        "{{CURRENCY_ROWS}}": ",".join(currency_rows),
        "{{STATUS_ROWS}}": ",".join("(" + literal(s) + ")" for s in cfg["commercial_statuses"]),
        "{{LINK_LOADS}}": "\n".join(
            f"DELETE FROM gold.[link_{name}]; INSERT INTO gold.[link_{name}] "
            f"SELECT [{left}], [{right}] FROM {identifier(silver['displayName'])}.silver.[link_{name}];"
            for name, (_, left, _, right, _) in LINKS.items())
    }
    query = (ROOT / "gold" / "load.sql").read_text()
    for key, value in substitutions.items():
        query = query.replace(key, value)
    return query


def connect(cfg, item, lakehouse=False):
    try:
        import pyodbc
    except ImportError as exc:
        pyodbc = None
    properties = item.get("properties", {})
    server = (properties.get("sqlEndpointProperties", {}) if lakehouse else properties).get("connectionString", "")
    server = server.removeprefix("tcp:").split(",")[0]
    if not server.endswith(".datawarehouse.fabric.microsoft.com") or any(c in server for c in ";{}\"/"):
        raise DeploymentError("SQL connection endpoint not discovered/ready")
    encoded = token(cfg["tenant_id"], "https://database.windows.net").encode("utf-16-le")
    auth = struct.pack("<I", len(encoded)) + encoded
    catalog = properties.get("sqlEndpointProperties", {}).get("id") if lakehouse else item["id"]
    base = f"Server={server},1433;Database={catalog};Encrypt=yes;TrustServerCertificate=no;"
    if pyodbc and "ODBC Driver 18 for SQL Server" in pyodbc.drivers():
        connection = pyodbc.connect("Driver={ODBC Driver 18 for SQL Server};" + base,
                                   attrs_before={1256: auth}, timeout=30, autocommit=True)
    else:
        try:
            import mssql_python
        except ImportError as exc:
            raise DeploymentError("Standalone TDS requires ODBC 18 or the official bundled mssql-python client") from exc
        connection = mssql_python.connect(base, attrs_before={1256: auth}, timeout=30, autocommit=True,
                                         native_uuid=False)
    connection.timeout = 300
    return connection


def execute(connection, query, params=()):
    cursor = connection.cursor()
    try:
        cursor.execute(query, *params)
        results = []
        while True:
            if cursor.description:
                columns = [d[0] for d in cursor.description]
                rows = cursor.fetchmany(100001)
                if len(rows) > 100000:
                    raise DeploymentError("Bounded SQL read limit exceeded")
                results = [dict(zip(columns, row)) for row in rows]
            if not cursor.nextset():
                break
        return results
    except Exception as exc:
        # The original ODBC exception can contain connection/payload details.
        detail = str(exc)
        detail = re.sub(r"(?i)(Bearer\s+|access_token[=:]\s*)[^\s;]+", r"\1[REDACTED]", detail)
        detail = re.sub(r"(?i)(password|sharedaccesskey)\s*=\s*[^;]+", r"\1=[REDACTED]", detail)
        raise DeploymentError("SQL execution failed; no publication success claimed: " + detail[:1500]) from exc
    finally:
        cursor.close()


def validate_silver(connection, run_id):
    from fabric.contracts import ENTITIES, LINKS
    actual = execute(connection, """
        SELECT TABLE_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA='silver'""")
    columns = {}
    for row in actual:
        columns.setdefault(row["TABLE_NAME"], set()).add(row["COLUMN_NAME"])
    for entity, spec in ENTITIES.items():
        if not set(spec["fields"]).issubset(columns.get(entity, set())):
            raise DeploymentError(f"Silver binding table/columns missing: {entity}")
    for name, (_, left, _, right, _) in LINKS.items():
        if not {left, right}.issubset(columns.get("link_" + name, set())):
            raise DeploymentError(f"Silver managed relationship table missing: link_{name}")
    marker = execute(connection, "SELECT run_id FROM silver.publication WHERE run_id=?", (run_id,))
    if len(marker) != 1:
        raise DeploymentError("Silver successful publication required for this run_id")
    return columns


def deploy_gold(cfg, gold, silver):
    with connect(cfg, silver, lakehouse=True) as source:
        validate_silver(source, cfg["run_id"])
    with connect(cfg, gold) as connection:
        execute(connection, (ROOT / "gold" / "ddl.sql").read_text())
        for name, (_, left, _, right, _) in LINKS.items():
            execute(connection, f"IF OBJECT_ID('gold.link_{name}','U') IS NULL "
                f"CREATE TABLE gold.[link_{name}] ([{left}] varchar(128) NOT NULL, [{right}] varchar(128) NOT NULL);")
        execute(connection, render_load(cfg, silver))
        for batch in (ROOT / "gold" / "kpis.sql").read_text().split("-- @batch"):
            if batch.strip():
                execute(connection, batch)
        return execute(connection,
            "SELECT run_id, order_lines FROM gold.publication WHERE run_id=?", (cfg["run_id"],))


def validate_gold(connection, run_id):
    actual = execute(connection, """
        SELECT TABLE_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='gold'""")
    columns = {}
    for row in actual:
        columns.setdefault(row["TABLE_NAME"], set()).add(row["COLUMN_NAME"])
    for entity, spec in ENTITIES.items():
        if not set(spec["fields"]).issubset(columns.get(GOLD_TABLES[entity], set())):
            raise DeploymentError(f"Gold ontology table/columns missing: {entity}")
    for name, (_, left, _, right, _) in LINKS.items():
        if not {left, right}.issubset(columns.get("link_" + name, set())):
            raise DeploymentError(f"Gold relationship table missing: link_{name}")
    if len(execute(connection, "SELECT run_id FROM gold.publication WHERE run_id=?", (run_id,))) != 1:
        raise DeploymentError("Successful Gold publication required before ontology binding")
    return columns
