"""Immutable native reference captures and non-vacuous Demo reload proofs.

Cycle keys raw_config, source_items and reference_snapshot are private worker state.
No source jobs, mirror controls, CLI credentials or notebook deployment run here.
"""
from __future__ import annotations

import ast
import base64
import binascii
import copy
import hashlib
import json
import re
from contextlib import closing
from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.parse import urlparse
from uuid import UUID, uuid4

from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError
from azure.storage.filedatalake import DataLakeServiceClient

from fabric.contracts import ENTITIES, GOLD_TABLES, LINKS, canonical, digest, validate_record
from fabric.native_references import ORACLE_QUERIES, ORACLE_TABLES
from fabric.rest import DeploymentError
from fabric.sql import execute
from fabric.staging import conform_salesforce
from services.publisher import publish
from sources.salesforce.bps.inspect import MAPPINGS, quoted_identifier
from sources.salesforce.bps.jobs import resolve_pipelines
from sources.salesforce.bps.snapshot import entity_query, json_native, normalize_row

BPS_SUFFIX = "8fbe0076"
BPS_SYSTEM = "MSFlixSF"
BPS_DATASET = "MSFlixCRM"
SOURCE_ENTITIES = {
    "oracle": ("content", "offer", "distributor"),
    "salesforce": ("customer", "campaign", "consent", "touch"),
}
SOURCE_KIND = {"oracle": "OracleMirror", "salesforce": "BPS"}
MAX_ROWS = 100000
MAX_BYTES = 128 * 1024 * 1024


def _guid(value, label):
    try:
        parsed = str(UUID(value))
        if parsed != value.lower():
            raise ValueError()
        return parsed
    except (ValueError, TypeError, AttributeError) as exc:
        raise DeploymentError(label + " must be a discovered UUID") from exc


def _selection(cycle, *, require_command=True):
    source, command = cycle.get("source"), cycle.get("command_id")
    if source not in SOURCE_ENTITIES:
        raise DeploymentError("Only Oracle and Salesforce native reloads are supported")
    if require_command and (not isinstance(command, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", command)):
        raise DeploymentError("Unsafe native reload command identifier")
    return source, command


def _dfs_endpoint(value):
    parsed = urlparse(value)
    if (parsed.scheme != "https" or not re.fullmatch(
            r"[a-z0-9-]+\.dfs\.fabric\.microsoft\.com", parsed.netloc)
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise DeploymentError("An approved Microsoft OneLake DFS endpoint is required")
    return value.rstrip("/")


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON property")
        result[key] = value
    return result


def _invalid_number(value):
    raise ValueError("Non-finite JSON number")


def _decode(data):
    try:
        return json.loads(data, object_pairs_hook=_json_object, parse_constant=_invalid_number)
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise DeploymentError("Invalid native reload JSON document") from exc


def _payload(value):
    result = (canonical(value) + "\n").encode("utf-8")
    if len(result) > MAX_BYTES:
        raise DeploymentError("Native snapshot exceeds the bounded manifest/file size")
    return result


def _stamp(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise DeploymentError("Missing publication or snapshot timestamp")
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).timestamp()


def _state(entity, row):
    if not isinstance(row, dict):
        raise DeploymentError("Native/serving reference record must be an object")
    values = {}
    for field, kind in ENTITIES[entity]["fields"].items():
        value = row.get(field)
        if isinstance(value, Decimal) and kind == "long":
            if not value.is_finite() or value != value.to_integral_value():
                raise DeploymentError("Non-integral native/serving minor-unit value")
            value = int(value)
        if isinstance(value, datetime):
            if kind == "date":
                if value.time().isoformat() != "00:00:00":
                    raise DeploymentError("Non-midnight value in a serving date")
                value = value.date().isoformat()
            else:
                value = json_native(value)
        elif isinstance(value, date):
            value = value.isoformat()
        if kind == "boolean" and type(value) is int and value in (0, 1):
            value = bool(value)
        # Optional SQL NULLs are absent inputs to the contract validator.
        if value is not None:
            values[field] = value
    try:
        return validate_record(entity, values)
    except (ValueError, TypeError, KeyError) as exc:
        raise DeploymentError("Invalid " + entity + " reference/serving record") from exc


def _rows(entity, rows, limit, *, allow_empty=False):
    if not isinstance(rows, list) or len(rows) > limit or not rows and not allow_empty:
        raise DeploymentError(entity + " snapshot is empty or exceeds the approved input bound")
    normalized = [_state(entity, row) for row in rows]
    key = ENTITIES[entity]["key"]
    keys = [row[key] for row in normalized]
    if len(keys) != len(set(keys)):
        raise DeploymentError(entity + " snapshot/serving table has duplicate natural keys")
    return sorted(normalized, key=lambda row: row[key])


class _ImmutableOneLake:
    def __init__(self, credential, endpoint, workspace, raw_item, command):
        self.workspace = _guid(workspace, "Workspace")
        self.raw_item = _guid(raw_item, "Raw lakehouse")
        _selection({"source": "oracle", "command_id": command})
        self.prefix = f"Files/ingress/reloads/{command}/"
        self.service = DataLakeServiceClient(
            account_url=_dfs_endpoint(endpoint), credential=credential, api_version="2021-06-08",
            permit_redirects=False, retry_total=0,
            connection_timeout=30, read_timeout=90,
        )
        self.fs = self.service.get_file_system_client(self.workspace)

    def close(self):
        self.service.close()

    def _file(self, path):
        if not path.startswith(self.prefix) or not re.fullmatch(
                r"[a-z][a-z0-9_-]*\.json(?:\.[a-f0-9]{32}\.pending)?", path[len(self.prefix):]):
            raise DeploymentError("Snapshot path escaped the approved command directory")
        return self.fs.get_file_client(self.raw_item + "/" + path)

    def read(self, path):
        client = self._file(path)
        try:
            props = client.get_file_properties()
        except ResourceNotFoundError:
            return None
        if not 0 <= props.size <= MAX_BYTES:
            raise DeploymentError("Existing native snapshot file exceeds its size bound")
        data = client.download_file(
            length=props.size, etag=props.etag, match_condition=MatchConditions.IfNotModified,
        ).readall() if props.size else b""
        if len(data) != props.size:
            raise DeploymentError("Truncated native snapshot file")
        return data

    def seal(self, path, data):
        """Atomic first writer wins; an unflushed file is never a committed snapshot."""
        if len(data) > MAX_BYTES:
            raise DeploymentError("Native snapshot exceeds its file size bound")
        existing = self.read(path)
        if existing is not None:
            return existing
        directory = self.raw_item
        for segment in self.prefix.rstrip("/").split("/"):
            directory += "/" + segment
            try:
                self.fs.get_directory_client(directory).create_directory(
                    etag="*", match_condition=MatchConditions.IfMissing,
                )
            except (ResourceExistsError, ResourceModifiedError):
                pass
        temporary = path + "." + uuid4().hex + ".pending"
        client = self._file(temporary)
        client.upload_data(data, length=len(data), overwrite=False, max_concurrency=1)
        if self.read(temporary) != data:
            raise DeploymentError("Native snapshot upload did not preserve its bytes")
        try:
            client.rename_file(
                self.workspace + "/" + self.raw_item + "/" + path,
                etag="*", match_condition=MatchConditions.IfMissing,
            )
        except (ResourceExistsError, ResourceModifiedError):
            # Another retry may have sealed its capture first. Never replace it.
            pass
        sealed = self.read(path)
        if sealed is None:
            raise DeploymentError("Native snapshot atomic publication was not confirmed")
        return sealed

    def put(self, path, data):
        if self.seal(path, data) != data:
            raise DeploymentError("Immutable native snapshot conflicts with existing content")


class SourceReload:
    def __init__(self, runtime):
        self.runtime, self.cfg, self.client = runtime, runtime.cfg, runtime.client
        self.ws = _guid(self.cfg["workspace_id"], "Workspace")
        self.raw = _guid(self.cfg["items"]["raw"]["id"], "Raw lakehouse")
        self.silver = _guid(self.cfg["items"]["silver"]["id"], "Silver lakehouse")
        self.gold = _guid(self.cfg["items"]["gold"]["id"], "Gold warehouse")
        limit = self.cfg.get("max_input_events")
        if type(limit) is not int or limit < 1:
            raise DeploymentError("An explicit positive max_input_events is required")
        self.limit = min(limit, MAX_ROWS)
        if self.cfg.get("environment") not in ("dev", "test", "prod"):
            raise DeploymentError("Explicit dev/test/prod environment is required")

    def _item(self, item, *, expected_id=None, expected_name=None):
        item_id = _guid(item.get("id"), "Fabric item")
        if expected_id is not None and item_id != expected_id:
            raise DeploymentError("Discovered Fabric item differs from the approved binding")
        if expected_name is not None and item.get("displayName") != expected_name:
            raise DeploymentError("Native item name changed during discovery")
        for name in ("workspaceId", "workspace_id"):
            if name in item and _guid(item[name], "Item workspace") != self.ws:
                raise DeploymentError("Native reload cannot cross workspaces")
        return copy.deepcopy(item)

    def _config(self, raw_config, source):
        if not isinstance(raw_config, dict):
            raise DeploymentError("Deployed Raw config_json must contain an object")
        for key in ("environment", "run_id"):
            if raw_config.get(key) != self.cfg.get(key):
                raise DeploymentError("Deployed Raw " + key + " differs from worker configuration")
        if (_guid(raw_config.get("workspace_id"), "Raw config workspace") != self.ws
                or _guid(raw_config.get("raw_lakehouse_id"), "Raw config lakehouse") != self.raw):
            raise DeploymentError("Deployed Raw configuration has foreign lakehouse bindings")
        if "silver_lakehouse_id" in raw_config and _guid(
                raw_config["silver_lakehouse_id"], "Silver config lakehouse") != self.silver:
            raise DeploymentError("Deployed Raw configuration has a foreign Silver binding")
        sources = raw_config.get("sources", {})
        entities = SOURCE_ENTITIES[source]
        if not isinstance(sources, dict) or any(not isinstance(sources.get(e), dict) for e in entities):
            raise DeploymentError("The deployed native reference sources are incomplete")
        if not set(entities).issubset(raw_config.get("master_reference_entities", [])):
            raise DeploymentError("Reloaded entities must remain native reference authorities")
        stable_config = {**raw_config, "sources": {k: v for k, v in sources.items() if k not in entities}}
        return digest(stable_config)

    def _deployed_config(self, notebook_id):
        result = self.client.operation(
            "POST", f"/v1/workspaces/{self.ws}/notebooks/{notebook_id}/getDefinition?format=ipynb",
            {}, "spark-cli", result_required=True,
        )
        parts = result.get("definition", result).get("parts", [])
        matches = [p for p in parts if p.get("path", "").endswith(".ipynb")]
        if len(matches) != 1 or matches[0].get("payloadType") != "InlineBase64":
            raise DeploymentError("A unique deployed Raw ipynb definition is required")
        payload = matches[0].get("payload", "")
        if not isinstance(payload, str) or len(payload) > 24 * 1024 * 1024:
            raise DeploymentError("Deployed Raw notebook definition exceeds its bound")
        try:
            document = _decode(base64.b64decode(payload, validate=True))
        except (binascii.Error, ValueError) as exc:
            raise DeploymentError("Invalid deployed Raw notebook base64 payload") from exc
        lakehouse = document.get("metadata", {}).get("dependencies", {}).get("lakehouse", {})
        if (_guid(lakehouse.get("default_lakehouse"), "Notebook default lakehouse") != self.raw
                or _guid(lakehouse.get("default_lakehouse_workspace_id"), "Notebook workspace") != self.ws):
            raise DeploymentError("Deployed Raw notebook is bound to another lakehouse/workspace")
        cells = [c for c in document.get("cells", []) if c.get("cell_type") == "code"
                 and "parameters" in c.get("metadata", {}).get("tags", [])]
        if len(cells) != 1:
            raise DeploymentError("Deployed Raw notebook has no unique parameter cell")
        try:
            tree = ast.parse("".join(cells[0].get("source", [])))
            parameters = {}
            for node in tree.body:
                if (not isinstance(node, ast.Assign) or len(node.targets) != 1
                        or not isinstance(node.targets[0], ast.Name)
                        or node.targets[0].id not in ("config_json", "mode")
                        or node.targets[0].id in parameters):
                    raise ValueError("Only unique literal notebook parameter assignments are supported")
                parameters[node.targets[0].id] = ast.literal_eval(node.value)
            value = parameters.get("config_json")
            if not isinstance(value, str) or parameters.get("mode") != "ingest":
                raise ValueError("Raw must have a literal config_json and mode=ingest")
        except (SyntaxError, ValueError, TypeError, RecursionError) as exc:
            raise DeploymentError("Deployed Raw config_json is not a safe literal assignment") from exc
        return _decode(value)

    def prepare(self, cycle):
        source, _ = _selection(cycle, require_command=False)
        items = self.client.list(f"/v1/workspaces/{self.ws}/items", "spark-cli")

        def exact(kind, *, item_id=None, name=None):
            matches = [item for item in items if item.get("type") == kind
                       and (item_id is None or item.get("id", "").lower() == item_id)
                       and (name is None or item.get("displayName") == name)]
            if len(matches) != 1:
                raise DeploymentError("Expected one exact " + kind + " in the approved workspace")
            return self._item(matches[0], expected_id=item_id, expected_name=name)

        notebook_id = _guid(self.cfg["notebooks"]["raw"], "Raw notebook")
        exact("Notebook", item_id=notebook_id)
        raw = exact("Lakehouse", item_id=self.raw)
        silver = exact("Lakehouse", item_id=self.silver)
        exact("Warehouse", item_id=self.gold)
        workspace = self.client.request("GET", f"/v1/workspaces/{self.ws}", skill="spark-cli")[2]
        if _guid(workspace.get("id"), "Discovered workspace") != self.ws:
            raise DeploymentError("Wrong workspace returned by Fabric")
        endpoint = _dfs_endpoint(workspace.get("oneLakeEndpoints", {}).get("dfsEndpoint", ""))
        kind, name, collection = (
            ("MirroredDatabase", "MSFlix_OracleMirror", "mirroredDatabases") if source == "oracle" else
            ("Lakehouse", "bps_silver_" + BPS_SUFFIX, "lakehouses")
        )
        native = exact(kind, name=name)
        native = self._item(self.client.request(
            "GET", f"/v1/workspaces/{self.ws}/{collection}/{native['id']}", skill="sqldw-cli",
        )[2], expected_id=_guid(native["id"], "Native item"), expected_name=name)
        self._sql_binding(native)
        config = self._deployed_config(notebook_id)
        fingerprint = self._config(config, source)
        for entity in SOURCE_ENTITIES[source]:
            spec = config["sources"][entity]
            if (spec.get("source_kind") != SOURCE_KIND[source]
                    or _guid(spec.get("source_item_id"), "Configured native source") != native["id"]):
                raise DeploymentError("Deployed Raw native-source ownership differs from discovery")
        result = {"raw_config": config, "source_items": {
            "workspace": {"id": self.ws, "dfs_endpoint": endpoint},
            "raw": raw, "silver": silver, source: native, "config_sha256": fingerprint,
        }}
        if source == "salesforce":
            result["source_pipelines"] = {
                stage: _guid(self._item(item)["id"], "Native pipeline")
                for stage, item in resolve_pipelines(self.client, self.ws, BPS_SUFFIX).items()
            }
        return result

    def _sql_binding(self, item):
        endpoint = item.get("properties", {}).get("sqlEndpointProperties", {})
        database = _guid(endpoint.get("id"), "Native SQL endpoint")
        server = endpoint.get("connectionString", "")
        match = re.fullmatch(
            r"(?:tcp:)?([a-z0-9-]+(?:\.[a-z0-9-]+)*\.datawarehouse\.fabric\.microsoft\.com)(?:,1433)?",
            server, flags=re.IGNORECASE,
        ) if isinstance(server, str) else None
        if not match:
            raise DeploymentError("Native SQL server is not an approved Fabric SQL endpoint")
        return match[1], database

    def _plan(self, cycle):
        source, command = _selection(cycle)
        items = cycle.get("source_items", {})
        if self._config(cycle.get("raw_config"), source) != items.get("config_sha256"):
            raise DeploymentError("Prepared Raw configuration changed outside the selected sources")
        workspace = items.get("workspace", {})
        if _guid(workspace.get("id"), "Prepared workspace") != self.ws:
            raise DeploymentError("Prepared workspace differs from the approved binding")
        _dfs_endpoint(workspace.get("dfs_endpoint", ""))
        self._item(items.get("raw", {}), expected_id=self.raw)
        self._item(items.get("silver", {}), expected_id=self.silver)
        self._item(items.get(source, {}), expected_name=(
            "MSFlix_OracleMirror" if source == "oracle" else "bps_silver_" + BPS_SUFFIX))
        for entity in SOURCE_ENTITIES[source]:
            spec = cycle["raw_config"]["sources"][entity]
            if (spec.get("source_kind") != SOURCE_KIND[source]
                    or _guid(spec.get("source_item_id"), "Prepared native source") != items[source]["id"]):
                raise DeploymentError("Prepared native source ownership changed")
        self._sql_binding(items[source])
        return source, command, items

    def _store(self, cycle):
        _, command, items = self._plan(cycle)
        return _ImmutableOneLake(
            self.runtime.credential, items["workspace"]["dfs_endpoint"], self.ws, self.raw, command,
        )

    def _native_rows(self, source, item):
        server, database = self._sql_binding(item)
        if source == "salesforce":
            result = self.client.operation(
                "POST", f"/v1/workspaces/{self.ws}/sqlEndpoints/{database}/refreshMetadata",
                {"timeout": {"timeUnit": "Minutes", "value": 2}}, "sqldw-cli", result_required=True,
            )
            if any(row.get("status") == "Failed" for row in result.get("value", [])):
                raise DeploymentError("Native BPS Silver SQL metadata refresh failed")
        rows, traces = {}, {}
        with closing(publish.sql_connect(server, database, self.runtime.credential, autocommit=True)) as connection:
            connection.timeout = 60
            for entity in SOURCE_ENTITIES[source]:
                if source == "oracle":
                    query = ORACLE_QUERIES[entity]
                    rows[entity] = _rows(entity, execute(connection, query), self.limit)
                    traces[entity] = {"tables": ORACLE_TABLES[entity], "query_sha256": digest(query)}
                else:
                    source_object = MAPPINGS[entity]["object"]
                    tables = execute(connection, "SELECT TOP 101 TABLE_SCHEMA,TABLE_NAME "
                                     "FROM INFORMATION_SCHEMA.TABLES WHERE LOWER(TABLE_NAME)=?",
                                     (source_object.lower(),))
                    if len(tables) != 1:
                        raise DeploymentError("Native " + source_object + " table is missing or ambiguous")
                    schema, table = tables[0]["TABLE_SCHEMA"], tables[0]["TABLE_NAME"]
                    columns = execute(connection, "SELECT TOP 1001 COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                                      "WHERE TABLE_SCHEMA=? AND TABLE_NAME=? ORDER BY ORDINAL_POSITION", (schema, table))
                    names = [row["COLUMN_NAME"] for row in columns]
                    if len(names) >= 1001 or len({name.casefold() for name in names}) != len(names):
                        raise DeploymentError("Native BPS column discovery is truncated or ambiguous")
                    query, scoped = entity_query(entity, schema, table, names)
                    native = [normalize_row(row) for row in execute(
                        connection, query, (BPS_SYSTEM,) if scoped else ())]
                    if not native or len(native) > self.limit:
                        raise DeploymentError("Native BPS snapshot is empty or exceeds the approved input bound")
                    native = _decode(json.dumps(native, default=json_native, allow_nan=False))
                    rows[entity] = _rows(entity, conform_salesforce(entity, native), self.limit)
                    traces[entity] = {
                        "tables": [quoted_identifier(schema) + "." + quoted_identifier(table)],
                        "object": source_object, "source_system": BPS_SYSTEM, "dataset": BPS_DATASET,
                        "system_scoped": scoped, "query_sha256": digest(query), "processed_silver": True,
                        "method": "latest Id/SystemModstamp/_UpdatedTimeStamp, then live MSFlix keys",
                    }
        return rows, traces

    def _manifest(self, cycle, rows, traces):
        source, command, items = self._plan(cycle)
        entities = {}
        for entity in SOURCE_ENTITIES[source]:
            values = _rows(entity, rows[entity], self.limit)
            data = _payload(values)
            entities[entity] = {
                "path": f"Files/ingress/reloads/{command}/{entity}.json", "rows": values,
                "row_count": len(values), "sha256": digest(values),
                "file_sha256": hashlib.sha256(data).hexdigest(), "snapshot_run_id": command,
                "snapshot_complete": True, "source_kind": SOURCE_KIND[source],
                "source_item_id": items[source]["id"], "source_trace": traces[entity],
            }
        return {
            "version": 1, "environment": self.cfg["environment"], "workspace_id": self.ws,
            "raw_item_id": self.raw, "silver_item_id": self.silver, "base_run_id": self.cfg["run_id"],
            "source": source, "command_id": command, "config_sha256": items["config_sha256"],
            "captured_at": datetime.now(timezone.utc).isoformat(), "entities": entities,
        }

    def _check_manifest(self, cycle, manifest):
        source, command, items = self._plan(cycle)
        expected = {"version": 1, "environment": self.cfg["environment"], "workspace_id": self.ws,
                    "raw_item_id": self.raw, "silver_item_id": self.silver, "base_run_id": self.cfg["run_id"],
                    "source": source, "command_id": command, "config_sha256": items["config_sha256"]}
        if not isinstance(manifest, dict) or any(manifest.get(k) != v for k, v in expected.items()):
            raise DeploymentError("Immutable native snapshot does not belong to this prepared command")
        if (not isinstance(manifest.get("entities"), dict)
                or set(manifest["entities"]) != set(SOURCE_ENTITIES[source])):
            raise DeploymentError("Native snapshot entity set is incomplete or unexpected")
        _stamp(manifest.get("captured_at"))
        total = 0
        for entity, evidence in manifest["entities"].items():
            rows = _rows(entity, evidence.get("rows"), self.limit)
            total += len(rows)
            if (evidence.get("path") != f"Files/ingress/reloads/{command}/{entity}.json"
                    or evidence.get("source_kind") != SOURCE_KIND[source]
                    or evidence.get("source_item_id") != items[source]["id"]
                    or evidence.get("snapshot_run_id") != command or evidence.get("snapshot_complete") is not True
                    or evidence.get("row_count") != len(rows) or evidence.get("rows") != rows
                    or evidence.get("sha256") != digest(rows)
                    or evidence.get("file_sha256") != hashlib.sha256(_payload(rows)).hexdigest()
                    or not isinstance(evidence.get("source_trace"), dict)):
                raise DeploymentError("Native snapshot has conflicting or corrupt entity evidence")
        if total > self.limit:
            raise DeploymentError("Native command snapshot exceeds the approved total row bound")
        for left, _, right, right_key, origin in LINKS.values():
            if origin == left and left in manifest["entities"] and right in manifest["entities"]:
                targets = {r[right_key] for r in manifest["entities"][right]["rows"]}
                if any(r.get(right_key) is not None and r[right_key] not in targets
                       for r in manifest["entities"][left]["rows"]):
                    raise DeploymentError("Native snapshot has an orphan " + left + " -> " + right + " relationship")
        return manifest

    def stage(self, cycle):
        source, command, items = self._plan(cycle)
        manifest_path = f"Files/ingress/reloads/{command}/manifest.json"
        with closing(self._store(cycle)) as store:
            data = store.read(manifest_path)
            if data is None:
                rows, traces = self._native_rows(source, items[source])
                manifest = self._check_manifest(cycle, self._manifest(cycle, rows, traces))
                # Seal the complete capture before any entity file. A restarted
                # worker must not combine observations made at different times.
                data = store.seal(manifest_path, _payload(manifest))
            manifest = self._check_manifest(cycle, _decode(data))
            for evidence in manifest["entities"].values():
                store.put(evidence["path"], _payload(evidence["rows"]))
        config = copy.deepcopy(cycle["raw_config"])
        for entity, evidence in manifest["entities"].items():
            config["sources"][entity] = {
                **config["sources"][entity], "path": evidence["path"], "format": "json", "multiline": True,
                "column_mapping": {}, "snapshot_complete": True, "snapshot_run_id": command,
                "source_kind": evidence["source_kind"], "source_item_id": evidence["source_item_id"],
                "source_trace": evidence["source_trace"], "snapshot_manifest": manifest_path,
            }
        return {"raw_config": config, "reference_snapshot": manifest}

    def _delta(self, item, path, columns, filters=None):
        from deltalake.exceptions import TableNotFoundError
        try:
            rows = self.runtime.delta_rows(item, path, columns, filters=filters)
        except TableNotFoundError:
            return None
        if len(rows) > self.limit:
            raise DeploymentError("Reference proof exceeds its approved row bound")
        return rows

    def _raw_proof(self, manifest):
        command, entities = manifest["command_id"], manifest["entities"]
        batches = self._delta(self.raw, "raw/snapshot_batches",
                              ["entity", "run_id", "snapshot_complete", "row_count", "ingested_at"],
                              filters=("run_id", [command]))
        if batches is None:
            return None
        indexed = {}
        for row in batches:
            entity = row["entity"]
            if row["run_id"] != command or entity not in entities or entity in indexed:
                raise DeploymentError("Raw contains unexpected or duplicate command snapshot batches")
            indexed[entity] = row
        if set(indexed) != set(entities) or any(not r["snapshot_complete"] for r in indexed.values()):
            return None
        if any(indexed[e]["row_count"] != proof["row_count"] for e, proof in entities.items()):
            raise DeploymentError("Raw complete batch count conflicts with the immutable native snapshot")
        rows = self._delta(self.raw, "raw/reference_snapshots",
                           ["record_id", "entity", "entity_key", "row_json", "run_id", "ingested_at", "snapshot_complete"],
                           filters=("run_id", [command]))
        if rows is None:
            return None
        groups = {entity: [] for entity in entities}
        record_ids = set()
        for row in rows:
            entity = row["entity"]
            if (row["run_id"] != command or entity not in entities or row["record_id"] in record_ids
                    or not isinstance(row["record_id"], str) or not re.fullmatch(r"[a-f0-9]{64}", row["record_id"])):
                raise DeploymentError("Raw contains unexpected or duplicate native snapshot records")
            record_ids.add(row["record_id"])
            original = _decode(row["row_json"])
            value = _state(entity, original)
            if (canonical(original) != canonical(value)
                    or value[ENTITIES[entity]["key"]] != row["entity_key"] or not row["snapshot_complete"]
                    or _stamp(row["ingested_at"]) != _stamp(indexed[entity]["ingested_at"])):
                raise DeploymentError("Raw record identity/completion differs from its sealed batch")
            groups[entity].append(value)
        for entity, proof in entities.items():
            normalized = _rows(entity, groups[entity], self.limit, allow_empty=True)
            if len(normalized) < proof["row_count"]:
                return None
            if len(normalized) != proof["row_count"] or digest(normalized) != proof["sha256"]:
                raise DeploymentError("Raw payload digest conflicts with the immutable native snapshot")
        return max(_stamp(row["ingested_at"]) for row in indexed.values())

    def _sql_rows(self, connection, table, columns, limit=None):
        limit = self.limit if limit is None else limit
        query = f"SELECT TOP ({limit + 1}) " + ",".join("[" + c + "]" for c in columns) + " FROM " + table
        try:
            rows = execute(connection, query)
        except DeploymentError as exc:
            if "(208)" in str(exc) and "Invalid object name" in str(exc):
                return None
            raise
        if len(rows) > limit:
            raise DeploymentError("Reference SQL proof exceeds its approved row bound")
        return rows

    def _serving_rows_match(self, entity, rows, evidence, *, run_id=None):
        if rows is None:
            return False
        normalized = _rows(entity, rows, self.limit, allow_empty=True)
        if run_id is not None and any(row.get("run_id") != run_id or row.get("source_sequence") != 0 for row in rows):
            return False
        return len(normalized) == evidence["row_count"] and digest(normalized) == evidence["sha256"]

    def _publication(self, rows, after):
        if rows is None or not rows:
            return None
        if len(rows) != 1:
            raise DeploymentError("Duplicate serving publication markers")
        if rows[0]["run_id"] != self.cfg["run_id"] or _stamp(rows[0]["completed_at"]) < after:
            return None
        return _stamp(rows[0]["completed_at"])

    def _serving_proof(self, layer, manifest, after, *, onelake=False):
        def read(connection, table, columns, *, marker=False):
            if onelake:
                return self._delta(self.gold, "gold/" + table, columns)
            return self._sql_rows(connection, f"[{layer}].[{table}]", columns, limit=2 if marker else None)

        def check(connection):
            for entity, evidence in manifest["entities"].items():
                columns = list(ENTITIES[entity]["fields"])
                has_run_id = layer == "silver" or entity in ("consent", "touch")
                if has_run_id:
                    columns += ["run_id", "source_sequence"]
                table = entity if layer == "silver" else GOLD_TABLES[entity]
                if not self._serving_rows_match(
                        entity, read(connection, table, columns), evidence,
                        run_id=manifest["command_id"] if has_run_id else None):
                    return None
            return self._publication(read(connection, "publication", ["run_id", "completed_at"], marker=True), after)

        if onelake:
            return check(None)
        with closing(self.runtime.analytics(layer)) as connection:
            return check(connection)

    def verify(self, cycle, layer):
        if layer not in ("raw", "silver", "gold", "gold_onelake"):
            raise DeploymentError("Unknown native reload verification layer")
        manifest = self._check_manifest(cycle, cycle.get("reference_snapshot"))
        raw_stamp = self._raw_proof(manifest)
        if raw_stamp is None:
            return False
        if layer == "raw":
            return True
        after = max(raw_stamp, _stamp(cycle["silver_started_at"]) if cycle.get("silver_started_at") else raw_stamp)
        silver_stamp = self._serving_proof("silver", manifest, after)
        if silver_stamp is None:
            return False
        if layer == "silver":
            return True
        gold_stamp = self._serving_proof("gold", manifest, silver_stamp)
        if gold_stamp is None:
            return False
        if layer == "gold":
            return True
        return self._serving_proof("gold", manifest, gold_stamp, onelake=True) is not None
