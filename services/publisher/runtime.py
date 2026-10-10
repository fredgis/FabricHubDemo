"""Managed-identity data/control-plane adapters for the existing Demo path."""
from __future__ import annotations

import argparse
import json
import re
from contextlib import closing
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from fabric.contracts import ENTITIES, GOLD_TABLES, LINKS
from fabric.rest import DeploymentError, FabricClient
from fabric.sql import execute, render_load, validate_silver
from services.publisher import publish

SKILL = "e2e-medallion-architecture"


class GoldDeadlockError(DeploymentError):
    """Gold reconciliation was aborted by a confirmed SQL Server deadlock."""


def timestamp(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DeploymentError("Unexpected authenticated HTTP redirect; token not forwarded")


def latest_targets(rows, cfg):
    """Reference authorities stay native; only event-owned facts are compared."""
    result = {}
    for row in rows:
        entity = cfg["event_entity_map"].get(row["event_type"])
        if entity in cfg.get("master_reference_entities", []) or entity not in ENTITIES:
            continue
        key = (entity, row["entity_key"])
        if key not in result or row["source_sequence"] > result[key]["source_sequence"]:
            result[key] = {"entity": entity, "key": row["entity_key"],
                           "source_sequence": row["source_sequence"], "event_id": str(row["event_id"])}
    return list(result.values())


def targets_present(targets, rows, key):
    actual = {}
    for row in rows:
        if row[key] in actual:
            raise DeploymentError("Duplicate serving natural key; publication blocked")
        actual[row[key]] = row
    # A later valid state may already supersede a cycle's target; earlier
    # event IDs still have to be present individually in append-only Raw.
    return all(t["key"] in actual and int(actual[t["key"]]["source_sequence"]) >= t["source_sequence"]
               for t in targets)


class Runtime:
    def __init__(self, cfg, credential=None):
        self.cfg = cfg
        self.credential = credential or publish.make_credential(argparse.Namespace(
            auth=cfg["auth"], tenant=cfg["tenant_id"],
            managed_identity_client_id=cfg.get("managed_identity_client_id")))
        self.client = FabricClient(cfg["tenant_id"], transport=self.fabric_http)
        self.ws = cfg["workspace_id"]
        self.lock_connection = None

    def fabric_http(self, method, url, body, skill):
        if urlparse(url).hostname != "api.fabric.microsoft.com":
            raise DeploymentError("Invalid Fabric host")
        path = urlparse(url).path
        if path.startswith("/v1/workspaces/") and path.split("/")[3] != self.ws:
            raise DeploymentError("Runtime cannot call a different Fabric workspace")
        request = Request(url, method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + self.credential.get_token(
                "https://api.fabric.microsoft.com/.default").token,
                "Content-Type": "application/json", "x-ms-fabric-skill": skill})
        try:
            with build_opener(NoRedirect()).open(request, timeout=60) as response:
                data = response.read()
                return response.status, dict(response.headers), json.loads(data) if data else {}
        except HTTPError as exc:
            data = exc.read()
            try:
                result = json.loads(data)
            except ValueError:
                result = {"errorCode": "NonJsonError"}
            return exc.code, dict(exc.headers), result

    def operational(self):
        c = self.cfg["operational"]
        return publish.sql_connect(c["server"], c["database"], self.credential, autocommit=True)

    def acquire_lock(self):
        self.lock_connection = self.operational()
        rows = execute(self.lock_connection,
            "DECLARE @r int; EXEC @r=sys.sp_getapplock "
            "@Resource=N'MSFlix-DemoPropagation',@LockMode=N'Exclusive',"
            "@LockOwner=N'Session',@LockTimeout=0; SELECT @r AS result;")
        if rows[0]["result"] < 0:
            self.lock_connection.close()
            raise DeploymentError("Another deployed Demo orchestrator holds the SQL session lock")

    def heartbeat_lock(self):
        # A lost SQL session is a lost lease: terminate, never continue writing.
        rows = execute(self.lock_connection,
            "SELECT APPLOCK_MODE(N'public',N'MSFlix-DemoPropagation',N'Session') AS mode;")
        if rows[0]["mode"] != "Exclusive":
            raise DeploymentError("Demo propagation lease lost")

    def close(self):
        if self.lock_connection:
            self.lock_connection.close()

    def publish(self, receipt):
        p = self.cfg["publisher"]
        return publish.run(argparse.Namespace(
            tenant=self.cfg["tenant_id"], auth=self.cfg["auth"],
            server=self.cfg["operational"]["server"], database=self.cfg["operational"]["database"],
            namespace=p["namespace"], topic=p["topic"], duration=p.get("duration", 30),
            max_messages=p.get("max_messages", 2000), batch_size=p.get("batch_size", 128),
            exit_when_empty=True), credential=self.credential, receipt=receipt)

    def published(self):
        with closing(self.operational()) as connection:
            rows = execute(connection,
                "SELECT TOP (?) event_id,event_type,entity_key,source_sequence,published_at,occurred_at "
                "FROM dbo.Outboxes WHERE published_at IS NOT NULL ORDER BY published_at,event_id;",
                (self.cfg["max_input_events"] + 1,))
        if len(rows) > self.cfg["max_input_events"]:
            raise DeploymentError("Outbox exceeds approved input bound")
        return [{**r, "event_id": str(r["event_id"]), "published_at": str(r["published_at"]),
                 "occurred_at": str(r["occurred_at"])} for r in rows]

    def next_reload(self):
        with closing(self.operational()) as connection:
            rows = execute(connection,
                "SELECT TOP (2) CONVERT(varchar(36),id) AS id,type,status,parameters "
                "FROM dbo.ControlCommands WHERE type IN ('reload_oracle','reload_salesforce') "
                "AND status IN ('requested','running','blocked') ORDER BY id;")
        if not rows:
            return None
        if len(rows) != 1:
            raise DeploymentError("Multiple active source reloads; reconcile the command queue before resuming")
        row = rows[0]
        if row["status"] != "requested":
            raise DeploymentError("Active source reload has no local checkpoint; reconcile before resuming")
        try:
            command_id = str(UUID(row["id"]))
            parameters = json.loads(row["parameters"])
        except (ValueError, TypeError, AttributeError) as exc:
            raise DeploymentError("Invalid source reload command identity or parameters") from exc
        if not isinstance(parameters, dict) or type(parameters.get("limit")) is not int or parameters["limit"] != 1:
            raise DeploymentError("Source reload command must request exactly one load")
        return {"id": command_id, "type": row["type"]}

    def set_reload_status(self, cycle, status, error=None):
        transitions = {
            "running": "'requested','running','blocked'",
            "blocked": "'requested','running','blocked'",
            "completed": "'running','blocked','completed'",
        }
        if status not in transitions or cycle.get("source") not in ("oracle", "salesforce"):
            raise DeploymentError("Invalid source reload status transition")
        command_id = str(UUID(cycle["command_id"]))
        command_type = "reload_" + cycle["source"]
        message = str(error or "Source reload needs operator attention")[:1000] if status == "blocked" else None
        with closing(self.operational()) as connection:
            rows = execute(connection,
                "UPDATE dbo.ControlCommands SET status=?, "
                "completed_at=CASE WHEN ?='completed' THEN COALESCE(completed_at,SYSUTCDATETIME()) ELSE NULL END, "
                "error=? OUTPUT INSERTED.status AS status WHERE id=CONVERT(uniqueidentifier,?) AND type=? "
                f"AND status IN ({transitions[status]});",
                (status, status, message, command_id, command_type))
            if len(rows) == 1:
                return rows[0]["status"]
            current = execute(connection,
                "SELECT status FROM dbo.ControlCommands WHERE id=CONVERT(uniqueidentifier,?) AND type=?;",
                (command_id, command_type))
        # A lost completion response must never turn a completed command into a failure.
        if status == "blocked" and current == [{"status": "completed"}]:
            return "completed"
        raise DeploymentError("Source reload command is missing or no longer in the expected state")

    def delta_rows(self, item, path, columns, filters=None):
        from deltalake import DeltaTable
        import pyarrow as pa

        # Delta-rs resolves _delta_log/checkpoints before reading active files.
        # Never scan all Parquet files (that would include superseded snapshots).
        access_token = self.credential.get_token("https://storage.azure.com/.default").token
        uri = f"abfss://{self.ws}@onelake.dfs.fabric.microsoft.com/{item}/Tables/{path}"
        table = DeltaTable(uri, storage_options={
            "account_name": "onelake", "bearer_token": access_token,
            "use_fabric_endpoint": "true",
        })
        # scan() is the Rust-native reader in pinned delta-rs 1.6.6. The older
        # to_pyarrow_dataset() path cannot read Fabric deletionVectors or Gold
        # columnMapping and must not be used as a Parquet-only fallback.
        rows, count = [], 0
        allowed = set(filters[1]) if filters else None
        with pa.RecordBatchReader.from_stream(table.scan(columns=columns)) as reader:
            for batch in reader:
                count += batch.num_rows
                if count > self.cfg["max_input_events"]:
                    raise DeploymentError("OneLake read exceeds approved input bound")
                values = batch.to_pylist()
                rows.extend(r for r in values if not filters or r[filters[0]] in allowed)
        return rows

    def exact_ids(self, kind, expected):
        item, path = ((self.cfg["items"]["kql"]["id"], "RawEvents") if kind == "native" else
                      (self.cfg["items"]["raw"]["id"], "raw/events_ingress"))
        rows = self.delta_rows(item, path, ["event_id"])
        observed = {str(row["event_id"]) for row in rows}
        missing = set(expected) - observed
        if kind == "raw" and len(observed) != len(rows):
            raise DeploymentError("Raw contains physical duplicate event IDs")
        return {"complete": not missing, "expected": len(expected), "observed_distinct": len(observed),
                "missing_count": len(missing), "missing_ids": sorted(missing)[:20]}

    def jobs(self, item_id, skill="spark-cli"):
        return self.client.list(f"/v1/workspaces/{self.ws}/items/{item_id}/jobs/instances", skill)

    def get_job(self, item_id, job_id, skill="spark-cli"):
        return self.client.request("GET",
            f"/v1/workspaces/{self.ws}/items/{item_id}/jobs/instances/{job_id}", skill=skill)[2]

    def submit_job(self, item_id, graph=False, *, pipeline=False, parameters=None):
        if graph and (pipeline or parameters) or pipeline and parameters:
            raise DeploymentError("Invalid job execution options")
        skill = ("fabriciq-ontology-cli" if graph else
                 "e2e-medallion-architecture" if pipeline else "spark-cli")
        kind = "Pipeline" if pipeline else "RunNotebook"
        path = (f"/v1/workspaces/{self.ws}/graphModels/{item_id}/jobs/refreshGraph/instances" if graph else
                f"/v1/workspaces/{self.ws}/items/{item_id}/jobs/instances?jobType={kind}")
        body = None if graph else {}
        if parameters:
            if set(parameters) != {"config_json"} or not isinstance(parameters["config_json"], str):
                raise DeploymentError("Only the Raw config_json notebook parameter is supported")
            body = {"executionData": {"parameters": {
                "config_json": {"value": parameters["config_json"], "type": "string"}}}}
        status, headers, result = self.client.request("POST", path, body, skill)
        location = headers.get("location", "")
        if status != 202 or urlparse(location).hostname != "api.fabric.microsoft.com":
            raise DeploymentError("Job submission ambiguous; reconcile saved intent with job history")
        return {"id": location.rstrip("/").split("/")[-1],
                "not_before": __import__("time").time() + max(1, int(headers.get("retry-after", 30)))}

    def prepare_source_reload(self, cycle):
        from services.publisher.source_reload import SourceReload
        return SourceReload(self).prepare(cycle)

    def stage_source_reload(self, cycle):
        from services.publisher.source_reload import SourceReload
        return SourceReload(self).stage(cycle)

    def verify_source_reload(self, cycle, layer):
        from services.publisher.source_reload import SourceReload
        return SourceReload(self).verify(cycle, layer)

    def analytics(self, layer):
        item = self.cfg["items"][layer]
        props = item["properties"]
        if layer in ("raw", "silver"):
            props = props["sqlEndpointProperties"]
            database = props["id"]
        else:
            database = item["id"]
        return publish.sql_connect(props["connectionString"], database, self.credential, autocommit=True)

    def refresh_metadata(self):
        item = self.cfg["items"]["silver"]
        endpoint = item["properties"]["sqlEndpointProperties"]["id"]
        result = self.client.operation("POST",
            f"/v1/workspaces/{self.ws}/sqlEndpoints/{endpoint}/refreshMetadata",
            {"timeout": {"timeUnit": "Minutes", "value": 2}}, "sqldw-cli")
        if any(r.get("status") == "Failed" for r in result.get("value", [])):
            raise DeploymentError("Silver metadata refresh failed")

    def verify_targets(self, layer, targets, *, onelake=False):
        for entity in sorted({t["entity"] for t in targets}):
            expected = [t for t in targets if t["entity"] == entity]
            key = ENTITIES[entity]["key"]
            table = GOLD_TABLES[entity] if layer == "gold" else entity
            # Reference tables and campaign conversions have no event_id in
            # their Gold contract; event-owned rental/playback are primary.
            if onelake:
                rows = self.delta_rows(self.cfg["items"][layer]["id"], f"{layer}/{table}",
                                       [key, "source_sequence"])
            else:
                with closing(self.analytics(layer)) as connection:
                    rows = execute(connection,
                        f"SELECT TOP ({self.cfg['max_input_events'] + 1}) [{key}],source_sequence "
                        f"FROM [{layer}].[{table}];")
            if not targets_present(expected, rows, key):
                return False
        return True

    def gold(self, cycle):
        from pyodbc import Error

        try:
            return self._gold(cycle)
        except DeploymentError as exc:
            cause = exc.__cause__
            if (isinstance(cause, Error) and cause.args[:1] == ("40001",) and
                    any(isinstance(part, str) and re.search(
                        r"\(1205\)(?:\s+\(SQL\w+\))?(?:;|$)", part) for part in cause.args[1:])):
                # SQL Server rolls back the victim. Retry the whole reconciliation,
                # never an individual statement or an ambiguous commit failure.
                raise GoldDeadlockError("Gold reconciliation deadlock (40001/1205); transaction rolled back") from exc
            raise

    def _gold(self, cycle):
        with closing(self.analytics("silver")) as source:
            validate_silver(source, self.cfg["run_id"])
            marker = execute(source, "SELECT run_id,completed_at FROM silver.publication;")
        if len(marker) != 1 or timestamp(marker[0]["completed_at"]) < cycle["silver_started_at"]:
            return None
        if not self.verify_targets("silver", cycle["targets"]):
            return None
        with closing(self.analytics("gold")) as connection:
            existing = execute(connection, "SELECT run_id,completed_at,order_lines FROM gold.publication;")
            if (len(existing) != 1 or existing[0]["run_id"] != self.cfg["run_id"] or
                    timestamp(existing[0]["completed_at"]) < timestamp(marker[0]["completed_at"])):
                # Existing proven atomic reconciliation, no schema or notebook
                # rewrite. Safe to re-execute if crash preceded the SQL commit.
                execute(connection, render_load(self.cfg, self.cfg["items"]["silver"]))
            result = execute(connection, "SELECT run_id,completed_at,order_lines FROM gold.publication;")
        if not self.verify_targets("gold", cycle["targets"]):
            return None
        return {k: str(v) if isinstance(v, datetime) else v for k, v in result[0].items()}

    def gold_onelake(self, cycle):
        if not self.verify_targets("gold", cycle["targets"], onelake=True):
            return False
        # Graph relationships are separate Delta sources. A visible fact alone
        # does not prove the link tables have reached OneLake.
        with closing(self.analytics("gold")) as connection:
            for name, (_, left, _, right, _) in LINKS.items():
                expected = execute(connection,
                    f"SELECT [{left}],[{right}] FROM gold.[link_{name}];")
                native = self.delta_rows(self.cfg["items"]["gold"]["id"],
                                        "gold/link_" + name, [left, right])
                if {(r[left], r[right]) for r in expected} != {(r[left], r[right]) for r in native}:
                    return False
        return True

    def graph_rows(self, query):
        result = self.client.request("POST",
            f"/v1/workspaces/{self.ws}/graphModels/{self.cfg['graph_id']}/executeQuery?beta=true",
            {"query": query}, "fabriciq-ontology-cli")[2]
        if result.get("status", {}).get("code") != "00000":
            raise DeploymentError("Graph query did not complete successfully")
        return result["result"]["data"]

    def verify_graph(self, targets):
        orders = sorted({t["key"] for t in targets if t["entity"] == "rental"})
        observed = []
        for start in range(0, len(orders), 100):
            keys = orders[start:start + 100]
            if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) for value in keys):
                raise DeploymentError("Invalid graph key")
            values = ", ".join("'" + value + "'" for value in keys)
            query = ("MATCH (c:customer)-[:customer_order]->(r:rental)"
                     "-[:order_offer]->(o:offer)-[:offer_content]->(f:content) "
                     f"WHERE r.order_id IN [{values}] "
                     "RETURN r.order_id AS order_id, c.customer_key AS customer_key, "
                     "f.content_key AS content_key LIMIT 101")
            rows = self.graph_rows(query)
            if {r["order_id"] for r in rows} != set(keys) or len(rows) != len(keys):
                return None
            observed.extend(rows)
        # Also execute a real graph read for a playback-only or reference-only
        # cycle, rather than treating refresh completion as a query proof.
        if not orders:
            observed = self.graph_rows("MATCH (r:rental) RETURN r.order_id AS order_id LIMIT 1")
        # Source sequence is lineage, not an ontology property. Compare actual
        # business state against the just-published Gold snapshot instead.
        properties = {"rental": ["order_id", "status", "amount_minor", "currency"],
                      "playback": ["session_id", "order_id", "position_seconds", "status"]}
        counts = {}
        for entity, columns in properties.items():
            keys = sorted({t["key"] for t in targets if t["entity"] == entity})
            if not keys:
                continue
            key = columns[0]
            with closing(self.analytics("gold")) as connection:
                expected_rows = execute(connection, "SELECT " + ",".join(f"[{c}]" for c in columns) +
                                        f" FROM gold.[{GOLD_TABLES[entity]}];")
            expected = {row[key]: row for row in expected_rows}
            for start in range(0, len(keys), 100):
                batch = keys[start:start + 100]
                if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) for value in batch):
                    raise DeploymentError("Invalid graph key")
                values = ",".join("'" + value + "'" for value in batch)
                rows = self.graph_rows(
                    f"MATCH (n:{entity}) WHERE n.{key} IN [{values}] RETURN " +
                    ",".join(f"n.{c} AS {c}" for c in columns) + " LIMIT 101")
                if {r[key] for r in rows} != set(batch) or len(rows) != len(batch):
                    return None
                if any(row != expected.get(row[key]) for row in rows):
                    return None
            counts[entity] = len(keys)
        return {"verified_orders": len(orders), "verified_entities": counts, "sample": observed[:5]}
