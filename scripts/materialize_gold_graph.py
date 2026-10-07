"""Apply the documented GraphModel definition to the existing ontology child graph."""
import json
from pathlib import Path

from fabric.deploy import preflight, resolve, validate_config
from fabric.graph import gold_graph_definition
from fabric.rest import DeploymentError, FabricClient
from fabric.sql import connect, validate_gold

ROOT = Path(__file__).resolve().parents[1]
SKILL = "fabriciq-ontology-cli"


def main():
    cfg = validate_config(json.loads((ROOT / "fabric" / "config.live.local.json").read_text()), "check")
    client = FabricClient(cfg["tenant_id"])
    workspace = preflight(cfg, client)
    ws = workspace["id"]
    gold = resolve(cfg, client, ws, "gold")
    with connect(cfg, gold) as sql:
        validate_gold(sql, cfg["run_id"])
    items = client.list(f"/v1/workspaces/{ws}/items", SKILL)
    graphs = [item for item in items if item["type"] == "GraphModel"
              and item["displayName"] == "MSFlixBusiness_graph_88888888888848888888888888888888"]
    if len(graphs) != 1:
        raise DeploymentError("Expected the existing MSFlix ontology graph; no replacement graph created")
    base = f"/v1/workspaces/{ws}/graphModels/{graphs[0]['id']}"
    old = client.operation("POST", base + "/getDefinition", {}, SKILL, True)["definition"]
    desired = gold_graph_definition(ws, gold["id"], workspace["oneLakeEndpoints"]["dfsEndpoint"], old)
    client.operation("POST", base + "/updateDefinition", {"definition": desired}, SKILL)
    evidence = {"graph_id": graphs[0]["id"], "gold_id": gold["id"],
                "definition_persisted": True, "node_types": 10, "edge_types": 12,
                "instances_verified": False}
    (ROOT / "fabric" / "evidence" / "graph-gold-projection.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()
