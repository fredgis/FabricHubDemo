"""Stage actual approved catalog/CRM snapshots through the discovered Raw item."""
import json
from pathlib import Path

from fabric.deploy import preflight, resolve, validate_config
from fabric.rest import FabricClient
from fabric.staging import stage_exports


def main():
    root = Path(__file__).resolve().parents[1]
    config_path = root / "fabric" / "config.live.local.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    validate_config(config, "check")
    client = FabricClient(config["tenant_id"])
    workspace = preflight(config, client)
    raw = resolve(config, client, workspace["id"], "raw")
    result = stage_exports(config, workspace, raw, root)
    evidence = root / ".state" / "source-staging.json"
    evidence.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"state": result["state"], "counts": result["counts"]}, indent=2))


if __name__ == "__main__":
    main()
