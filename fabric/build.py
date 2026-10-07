"""Build reviewable Jupyter and generation-2 TMDL artifacts, offline."""
from __future__ import annotations

import base64
import json
import re
import uuid
from pathlib import Path

from fabric.contracts import ENTITIES, GOLD_TABLES, LINKS

ROOT = Path(__file__).resolve().parent
ID_NAMESPACE = uuid.UUID("72fc5c51-4018-56e0-aa60-852cbec106bb")


def stable_id(name):
    return str(uuid.uuid5(ID_NAMESPACE, "msflix/" + name))


def persisted_ids():
    names = ["ontology", "expression"]
    for entity, spec in ENTITIES.items():
        names.extend([f"entity/{entity}", f"table/{entity}"])
        names.extend(f"property/{entity}/{column}" for column in spec["fields"])
        names.extend(f"column/{entity}/{column}" for column in spec["fields"])
    for name, (left, lkey, right, rkey, _) in LINKS.items():
        names.extend([f"link/{name}", f"relationship/{name}", f"join/{name}/left", f"join/{name}/right",
                      f"column/link_{name}/{lkey}", f"column/link_{name}/{rkey}"])
    desired = {name: stable_id(name) for name in sorted(set(names))}
    path = ROOT / "ontology" / "ids.json"
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
        if any(current.get(k, v) != v for k, v in desired.items()):
            raise ValueError("Persisted lineage IDs changed; deliberate migration required")
        desired = {**current, **desired}
    return desired


def cell(text, name, metadata=None, markdown=False):
    result = {"cell_type": "markdown" if markdown else "code", "id": name,
              "metadata": metadata or {}, "source": text.splitlines(keepends=True)}
    result["source"] = [line if line.endswith("\n") else line + "\n" for line in result["source"]]
    if not markdown:
        result.update(outputs=[], execution_count=None)
    return result


def notebook(layer):
    # Embedding these modules means remote notebooks don't need local import paths,
    # wheel installation or undeployed source files.
    common = (ROOT / "contracts.py").read_text(encoding="utf-8")
    runtime = (ROOT / "spark_runtime.py").read_text(encoding="utf-8")
    return {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Synapse PySpark", "language": "python", "name": "synapse_pyspark"},
            "language_info": {"name": "python"},
            "dependencies": {"lakehouse": {}},
            "msflix": {"layer": layer, "binding": "discovered_at_deploy", "schema_enabled_required": True}
        },
        "cells": [
            cell("# MSFlix " + layer + "\nParameterized managed Delta processing. No synthetic input or execution evidence.\n",
                 "intro", markdown=True),
            cell('%%configure\n{"conf":{"spark.native.enabled":"true","spark.sql.session.timeZone":"UTC"}}\n', "configure"),
            cell('config_json = ""\nmode = "ingest"\n', "parameters",
                 {"tags": ["parameters"]}),
            cell(common, "contracts"),
            cell(runtime, "runtime"),
            cell('import notebookutils\nif not config_json:\n    raise ValueError("config_json is required")\n'
                 'cfg = json.loads(config_json)\n'
                 'if cfg.get("environment") not in ("dev", "test", "prod"):\n'
                 '    raise ValueError("Explicit environment dev/test/prod required")\n'
                 'context = notebookutils.runtime.context\n'
                 'is_for_pipeline = context["isForPipeline"]\n'
                 'if not context.get("defaultLakehouseId"):\n'
                 '    raise ValueError("Default schema-enabled lakehouse is not bound")\n'
                 f'result = run_{layer.lower()}(spark, notebookutils, cfg'
                 + (", mode" if layer == "Raw" else "") + ')\n'
                 'notebookutils.notebook.exit(json.dumps(result))\n', "execute")
        ]
    }


def bind_notebook(layer, workspace_id, lakehouse, cfg):
    doc = notebook(layer)
    doc["metadata"]["dependencies"]["lakehouse"] = {
        "default_lakehouse": lakehouse["id"],
        "default_lakehouse_name": lakehouse["displayName"],
        "default_lakehouse_workspace_id": workspace_id,
        "known_lakehouses": [{"id": lakehouse["id"]}]
    }
    doc["cells"][2]["source"][0] = "config_json = " + repr(json.dumps(cfg)) + "\n"
    return {"format": "ipynb", "parts": [part("notebook-content.ipynb", json.dumps(doc))]}


def part(path, text):
    if "\\" in path:
        raise ValueError("Fabric part paths must use forward slashes")
    return {"path": path, "payload": base64.b64encode(text.encode("utf-8")).decode(),
            "payloadType": "InlineBase64"}


def ontology_texts(endpoint="{{GOLD_SQL_ENDPOINT}}", database_id="{{GOLD_SQL_DATABASE_ID}}", name="MSFlixBusiness"):
    ids = persisted_ids()
    files = {
        ".platform": json.dumps({
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
            "metadata": {"type": "Ontology", "displayName": name},
            "config": {"version": "2.0", "logicalId": ids["ontology"]}}, indent=2),
        "database.tmdl": "database\n\tcompatibilityLevel: 1000000\n",
        "namespaces/default.tmdl": "namespace default\n\tlineageTag: default\n",
        "expressions.tmdl": f'expression DatabaseQuery =\n\t\tlet\n\t\t    database = Sql.Database("{endpoint}", "{database_id}")\n\t\tin\n\t\t    database\n\tlineageTag: {ids["expression"]}\n',
    }
    model = ["model Model", "", "ref namespace default"]
    type_map = {"string": "string", "long": "int64", "date": "dateTime", "timestamp": "dateTime", "boolean": "boolean"}

    def backing_table(table, fields, lineage):
        text = f"table {table}\n\tlineageTag: {lineage}\n"
        for column, kind in fields.items():
            cid = ids.get(f"column/{table}/{column}")
            text += f"\n\tcolumn {column}\n\t\tdataType: {type_map[kind]}\n\t\tlineageTag: {cid}\n\t\tsourceColumn: {column}\n"
        source_table = GOLD_TABLES.get(table, table)
        text += f"\n\tpartition {table} = entity\n\t\tmode: directLake\n\t\tsource\n\t\t\tentityName: {source_table}\n\t\t\tschemaName: gold\n\t\t\texpressionSource: DatabaseQuery\n"
        files[f"tables/{table}.tmdl"] = text
        model.append(f"ref table {table}")

    for entity, spec in ENTITIES.items():
        backing_table(entity, spec["fields"], ids[f"table/{entity}"])
        text = f"entity {entity}\n\tlineageTag: {ids[f'entity/{entity}']}\n\tbackingTable: {entity}\n\tkeyProperty: {spec['key']}\n"
        for column, kind in spec["fields"].items():
            text += f"\n\tproperty {column}\n\t\tdataType: {type_map[kind]}\n\t\tlineageTag: {ids[f'property/{entity}/{column}']}\n\t\tbackingConfiguration\n\t\t\tvalueColumn: {entity}.{column}\n"
        files[f"entities/{entity}.tmdl"] = text
        model.append(f"ref entity {entity}")
    relationships, entity_relationships = [], []
    for name, (left, lkey, right, rkey, _) in LINKS.items():
        table = f"link_{name}"
        backing_table(table, {lkey: "string", rkey: "string"}, ids[f"link/{name}"])
        left_join, right_join = f"join_{name}_left", f"join_{name}_right"
        # Shared endpoints produce inactive physical joins to avoid ambiguous
        # tabular filter paths; graph contextualization still names them explicitly.
        for join, column, target, target_key in (
            (left_join, lkey, left, lkey), (right_join, rkey, right, rkey)
        ):
            side = "left" if join == left_join else "right"
            relationships.append(f"relationship {join}\n\tisActive: false\n\tfromCardinality: many\n\ttoCardinality: one\n\tfromColumn: {table}.{column}\n\ttoColumn: {target}.{target_key}\n\tannotation MSFlixStableId = {ids[f'join/{name}/{side}']}\n")
        entity_relationships.append(
            f"entityRelationship {name}\n\tlineageTag: {ids[f'relationship/{name}']}\n"
            f"\tfromEntity: {left}\n\ttoEntity: {right}\n\tbackingConfiguration\n"
            f"\t\ttype: table\n\t\ttable: {table}\n\t\tfromRelationship: {left_join}\n\t\ttoRelationship: {right_join}\n")
    files["relationships.tmdl"] = "\n".join(relationships)
    files["entityRelationships.tmdl"] = "\n".join(entity_relationships)
    files["model.tmdl"] = "\n".join(model) + "\n"
    return files


def ontology_definition(endpoint, database_id, name):
    from urllib.parse import urlparse
    uuid.UUID(database_id)
    host = endpoint.removeprefix("tcp:").split(",")[0]
    if not host.endswith(".datawarehouse.fabric.microsoft.com") or '"' in host or "/" in host:
        raise ValueError("Gold SQL endpoint must be the discovered Fabric SQL FQDN")
    return {"parts": [part(path, text) for path, text in ontology_texts(host, database_id, name).items()]}


def preserve_ontology_identity(definition, existing):
    desired = {p["path"]: p for p in definition["parts"]}
    old = {p["path"]: p for p in existing["parts"]}
    if set(old) - set(desired):
        raise ValueError("Unexpected ontology parts; refusing to remove existing content")
    for path, value in desired.items():
        if path.startswith(("entities/", "tables/")) or path == "entityRelationships.tmdl":
            if path not in old:
                raise ValueError("Existing ontology lineage is missing: " + path)
            expected_tags = re.findall(r"(?m)^\s*lineageTag:\s*(\S+)", base64.b64decode(value["payload"]).decode())
            actual_tags = re.findall(r"(?m)^\s*lineageTag:\s*(\S+)", base64.b64decode(old[path]["payload"]).decode())
            if expected_tags != actual_tags:
                raise ValueError("Existing ontology semantic lineage differs: " + path)
    platform = json.loads(base64.b64decode(old[".platform"]["payload"]))
    actual_id = uuid.UUID(platform["config"]["logicalId"])
    expected = json.loads(base64.b64decode(desired[".platform"]["payload"]))
    if actual_id.int and actual_id != uuid.UUID(expected["config"]["logicalId"]):
        raise ValueError("Existing ontology Git lineage differs from persisted ID map")
    # Fabric returns an unassigned all-zero Git logicalId before Git integration.
    # Preserve service metadata while validating the actual semantic lineages above.
    return {"parts": [old[".platform"] if p["path"] == ".platform" else p for p in definition["parts"]]}


def build():
    for layer in ("Raw", "Silver"):
        path = ROOT / "notebooks" / f"MSFlix{layer}.ipynb"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(notebook(layer), indent=2) + "\n", encoding="utf-8")
    for path, text in ontology_texts().items():
        output = ROOT / "ontology" / "definition" / path
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    ids_path = ROOT / "ontology" / "ids.json"
    ids_path.write_text(json.dumps(persisted_ids(), indent=2) + "\n", encoding="utf-8")
    print("Built Raw/Silver notebooks and generation-2 TMDL templates; not deployed.")


if __name__ == "__main__":
    build()
