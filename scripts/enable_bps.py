"""Assign the Microsoft BPS workload only to the approved MSFlix workspace."""
import argparse
import json
from pathlib import Path

from fabric.deploy import preflight, validate_config
from fabric.rest import DeploymentError, FabricClient

ROOT = Path(__file__).resolve().parents[1]
SKILL = "e2e-medallion-architecture"


def enable(cfg, client):
    workspace = preflight(cfg, client)
    matches = [row for row in client.list("/v1/admin/workloads", SKILL)
               if row["name"] == "Business Process Solutions" and row["publisher"] == "Microsoft"]
    if len(matches) != 1 or not matches[0].get("isAssignable"):
        raise DeploymentError("Microsoft Business Process Solutions is missing or not assignable")
    workload_id = matches[0]["id"]
    path = "/v1/admin/workloads/assignments?workloadId=" + workload_id
    before = client.list(path, SKILL)
    own = [row for row in before
           if row["type"] == "Workspace" and row["workspaceId"] == workspace["id"]]
    if len(own) > 1:
        raise DeploymentError("Ambiguous existing MSFlix BPS assignment")
    if not own:
        client.operation("POST", "/v1/admin/workloads/assignments",
                         {"type": "Workspace", "workloadId": workload_id,
                          "workspaceId": workspace["id"]}, SKILL)
    after = client.list(path, SKILL)
    if not {row["id"] for row in before}.issubset({row["id"] for row in after}):
        raise DeploymentError("An existing workload assignment changed unexpectedly")
    own = [row for row in after
           if row["type"] == "Workspace" and row["workspaceId"] == workspace["id"]]
    if len(own) != 1:
        raise DeploymentError("MSFlix BPS workspace assignment readback failed")
    return {"workload_id": workload_id, "assignment": own[0],
            "existing_assignments_preserved": True, "salesforce_ingestion_verified": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "fabric" / "config.live.local.json")
    args = parser.parse_args()
    cfg = validate_config(json.loads(args.config.read_text(encoding="utf-8-sig")), "check")
    evidence = enable(cfg, FabricClient(cfg["tenant_id"]))
    path = ROOT / ".state" / "bps" / "workload-assignment.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
