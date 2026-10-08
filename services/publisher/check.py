"""Read-only IMDS preflight; fail if the publisher can alter business state."""
from __future__ import annotations

import argparse
import json
from contextlib import closing
from pathlib import Path

from fabric.rest import DeploymentError
from fabric.sql import execute
from services.publisher.access import check_access
from services.publisher.runtime import Runtime
from services.publisher.worker import validate_config


def check(cfg):
    runtime = Runtime(validate_config(cfg))
    access = check_access(runtime)
    workspace = runtime.client.request("GET", f"/v1/workspaces/{runtime.ws}",
                                      skill="e2e-medallion-architecture")[2]
    if workspace["capacityId"] != cfg["capacity_id"]:
        raise DeploymentError("Workspace moved to a different capacity")
    native = runtime.exact_ids("native", [])
    graph = runtime.graph_rows("MATCH (r:rental) RETURN r.order_id AS order_id LIMIT 1")
    with closing(runtime.analytics("gold")) as connection:
        gold = execute(connection, "SELECT COUNT_BIG(*) AS order_lines FROM gold.fact_order_line;")
    return {"auth": "managed-identity", **access,
            "workspace_id": runtime.ws, "capacity_id": workspace["capacityId"],
            "native_onelake_distinct_events": native["observed_distinct"],
            "graph_query_rows": len(graph), "gold": gold}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    result = check(json.loads(a.config.read_text(encoding="utf-8")))
    if a.output:
        a.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
