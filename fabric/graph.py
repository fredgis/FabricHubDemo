"""Physical graph projection of the same canonical Gold ontology contract."""
import base64
import json
import uuid
from urllib.parse import urlparse

from fabric.build import part, stable_id
from fabric.contracts import ENTITIES, GOLD_TABLES, LINKS

SCHEMA_BASE = "https://developer.microsoft.com/json-schemas/fabric/item/graphIndex/definition"


def gold_graph_definition(workspace_id, gold_id, dfs_endpoint, existing):
    uuid.UUID(workspace_id)
    uuid.UUID(gold_id)
    endpoint = urlparse(dfs_endpoint)
    if endpoint.scheme != "https" or not endpoint.hostname or not endpoint.hostname.endswith(".dfs.fabric.microsoft.com"):
        raise ValueError("Graph requires the discovered OneLake DFS endpoint")
    base = f"abfss://{workspace_id}@{endpoint.hostname}/{gold_id}/Tables/gold"
    types = {"string": "STRING", "long": "INT", "boolean": "BOOLEAN",
             "date": "DATETIME", "timestamp": "DATETIME"}
    nodes, edges, sources, node_tables, edge_tables = [], [], [], [], []
    for entity, spec in ENTITIES.items():
        alias = entity + "_node"
        name = "Gold_" + GOLD_TABLES[entity]
        nodes.append({"alias": alias, "labels": [entity], "primaryKeyProperties": [spec["key"]],
                      "properties": [{"name": column, "type": types[kind]} for column, kind in spec["fields"].items()]})
        sources.append({"name": name, "type": "DeltaTable",
                        "properties": {"path": base + "/" + GOLD_TABLES[entity]}})
        node_tables.append({"id": entity + "_" + stable_id("graph/node/" + entity), "nodeTypeAlias": alias,
                            "dataSourceName": name, "propertyMappings": [
                                {"propertyName": column, "sourceColumn": column} for column in spec["fields"]]})
    for relationship, (left, lkey, right, rkey, _) in LINKS.items():
        alias = relationship + "_edge"
        name = "Gold_link_" + relationship
        edges.append({"alias": alias, "labels": [relationship], "sourceNodeType": {"alias": left + "_node"},
                      "destinationNodeType": {"alias": right + "_node"}, "properties": []})
        sources.append({"name": name, "type": "DeltaTable",
                        "properties": {"path": base + "/link_" + relationship}})
        edge_tables.append({"id": relationship + "_" + stable_id("graph/edge/" + relationship), "edgeTypeAlias": alias,
                            "dataSourceName": name, "sourceNodeKeyColumns": [lkey],
                            "destinationNodeKeyColumns": [rkey], "propertyMappings": []})
    documents = {
        "graphType.json": {"$schema": SCHEMA_BASE + "/graphType/1.0.0/schema.json",
                           "nodeTypes": nodes, "edgeTypes": edges},
        "dataSources.json": {"$schema": SCHEMA_BASE + "/dataSources/1.0.0/schema.json", "dataSources": sources},
        "graphDefinition.json": {"$schema": SCHEMA_BASE + "/graphDefinition/1.0.0/schema.json",
                                 "nodeTables": node_tables, "edgeTables": edge_tables},
    }
    old = {p["path"]: p for p in existing["parts"]}
    old_type = json.loads(base64.b64decode(old["graphType.json"]["payload"]))
    for group in ("nodeTypes", "edgeTypes"):
        if {n["alias"] for n in old_type.get(group) or []} - {n["alias"] for n in documents["graphType.json"][group]}:
            raise ValueError("Refusing to replace an unrelated graph projection")
    return {"parts": [part(p["path"], json.dumps(documents[p["path"]]))
                      if p["path"] in documents else p for p in existing["parts"]]}
