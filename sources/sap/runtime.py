"""Bounded, runtime-only recovery for the dedicated native SAP BPS environment."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from fabric.rest import DeploymentError
from sources.salesforce.bps.jobs import ACTIVE, _save
from sources.salesforce.bps.runtime import libraries, verify_runtime_only
from sources.sap.fabric_client import ScopedClient, load_target
from sources.sap.datasphere import json_bytes


def recover(target: dict, checkpoint: Path, apply=False) -> dict:
    client = ScopedClient(target)
    client.workspace()
    root = "/v1/workspaces/" + target["workspace_id"]
    environment = client.item("bps_env_" + target["system_suffix"], "Environment")
    base = root + "/environments/" + environment["id"]

    def compute(staging=False):
        return client.request("GET", base + ("/staging" if staging else "") + "/sparkcompute?beta=false")[2]

    published, staged = compute(), compute(True)
    before_lib, staged_lib = libraries(client, base), libraries(client, base, True)
    details = client.request("GET", base)[2]["properties"]["publishDetails"]
    result = {"environment_id": environment["id"], "before": published, "libraries_before": before_lib,
              "status": "inspected", "target_runtime": "1.3"}
    if not apply:
        return result
    if published != staged or before_lib != staged_lib or details["state"] != "Success":
        raise DeploymentError("Unpublished or active native environment changes; runtime recovery refused")
    if published["runtimeVersion"] not in ("1.3", "2.0"):
        raise DeploymentError("Unexpected native SAP runtime")
    for item in client.list(root + "/items"):
        if item["type"] == "DataPipeline" and item["displayName"].endswith("_" + target["system_suffix"]):
            jobs = client.list(root + "/items/" + item["id"] + "/jobs/instances")
            if any(j["status"] in ACTIVE for j in jobs):
                raise DeploymentError("SAP processing must stop before runtime publication")
    if published["runtimeVersion"] == "1.3":
        return {**result, "status": "unchanged"}
    _save(checkpoint, result)
    after = client.request("PATCH", base + "/staging/sparkcompute?beta=false", {"runtimeVersion": "1.3"})[2]
    verify_runtime_only(published, after, before_lib, libraries(client, base, True))
    _save(checkpoint, {**result, "status": "ambiguous_publication"})
    code, _, _ = client.request("POST", base + "/staging/publish?beta=false", {})
    if code not in (200, 202):
        raise DeploymentError("Publication acceptance is ambiguous; inspect before retrying")
    _save(checkpoint, {**result, "status": "publishing"})
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        state = client.request("GET", base)[2]["properties"]["publishDetails"]["state"]
        if state == "Success":
            actual, actual_lib = compute(), libraries(client, base)
            verify_runtime_only(published, actual, before_lib, actual_lib)
            result.update(status="verified", after=actual, libraries_after=actual_lib)
            _save(checkpoint, result)
            return result
        if state in ("Failed", "Cancelled", "Canceled"):
            raise DeploymentError("Native SAP environment publication failed")
        time.sleep(30)
    raise DeploymentError("SAP environment publication exceeded its deadline; inspect existing operation")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = recover(load_target(args.target), args.evidence, args.apply)
    except (ValueError, OSError, DeploymentError) as exc:
        parser.exit(2, f"SAP runtime recovery failed: {exc}\n")
    print(json_bytes(result).decode(), end="")


if __name__ == "__main__":
    main()
