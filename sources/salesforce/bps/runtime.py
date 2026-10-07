"""Recover the native BPS environment through documented Environment REST APIs."""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fabric.deploy import preflight, validate_config
from fabric.rest import DeploymentError, FabricClient
from sources.salesforce.bps.jobs import ACTIVE, _save, resolve_pipelines, validate_suffix

ROOT = Path(__file__).resolve().parents[3]
SKILL = "spark-cli"


def libraries(client, base, staging=False):
    original = base + ("/staging" if staging else "") + "/libraries?beta=false"
    path, rows, seen = original, [], set()
    while path:
        if path in seen or len(seen) >= 50:
            raise DeploymentError("Environment library pagination exceeded its bound")
        seen.add(path)
        response = client.request("GET", path, skill=SKILL)[2]
        rows.extend(response.get("libraries", []))
        path = response.get("continuationUri")
        if path == "null":
            path = None
        continuation = response.get("continuationToken")
        if not path and continuation not in (None, "", "null"):
            path = original + "&continuationToken=" + quote(continuation, safe="")
    return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))


def verify_runtime_only(before, after, libraries_before, libraries_after):
    if after.get("runtimeVersion") != "1.3":
        raise DeploymentError("Published native BPS runtime readback is not 1.3")
    unchanged = lambda value: {k: v for k, v in value.items() if k != "runtimeVersion"}
    if unchanged(before) != unchanged(after):
        raise DeploymentError("Non-runtime BPS compute settings changed unexpectedly")
    if libraries_before != libraries_after:
        raise DeploymentError("Native BPS library dependencies changed unexpectedly")


def recover(client, workspace_id, suffix, checkpoint, *, apply=False, timeout=720):
    validate_suffix(suffix)
    if not 60 <= timeout <= 900:
        raise DeploymentError("Environment publication deadline must be 60-900 seconds")
    matches = [
        item for item in client.list(f"/v1/workspaces/{workspace_id}/items", SKILL)
        if item["type"] == "Environment" and item["displayName"] == "bps_env_" + suffix
    ]
    if len(matches) != 1:
        raise DeploymentError("Native BPS environment missing or ambiguous")
    environment = matches[0]
    base = f"/v1/workspaces/{workspace_id}/environments/{environment['id']}"

    def compute(staging=False):
        return client.request(
            "GET", base + ("/staging" if staging else "") + "/sparkcompute?beta=false",
            skill=SKILL,
        )[2]

    published, staging = compute(), compute(True)
    published_libraries, staging_libraries = libraries(client, base), libraries(client, base, True)
    details = client.request("GET", base, skill=SKILL)[2]["properties"]["publishDetails"]
    evidence = {
        "workspace_id": workspace_id, "environment_id": environment["id"],
        "environment_name": environment["displayName"], "before": published,
        "libraries_before": published_libraries, "requested_runtime": "1.3",
        "observed_at": datetime.now(timezone.utc).isoformat(), "status": "inspected",
        "publish_details": details, "staging": staging, "staging_libraries": staging_libraries,
    }
    checkpoint = Path(checkpoint)
    if not apply:
        return evidence
    if published != staging or published_libraries != staging_libraries:
        raise DeploymentError("Unpublished BPS changes exist; do not publish unrelated edits")
    if details["state"] != "Success":
        raise DeploymentError("Existing environment publication is incomplete; no duplicate publish")
    if published.get("runtimeVersion") not in ("2.0", "1.3"):
        raise DeploymentError("Unexpected native runtime; only the approved 2.0→1.3 recovery is supported")
    for item in resolve_pipelines(client, workspace_id, suffix).values():
        jobs = client.list(f"/v1/workspaces/{workspace_id}/items/{item['id']}/jobs/instances", SKILL)
        if any(job["status"] in ACTIVE for job in jobs):
            raise DeploymentError("Native BPS stage is active; do not change its environment")
    if published["runtimeVersion"] == "1.3":
        evidence.update(status="verified", after=published, libraries_after=published_libraries)
        # Retain the original recovery baseline rather than overwrite audit evidence
        # with an already-recovered state on an idempotent invocation.
        if not checkpoint.exists():
            _save(checkpoint, evidence)
        return evidence
    _save(checkpoint, evidence)
    staged = client.request(
        "PATCH", base + "/staging/sparkcompute?beta=false", {"runtimeVersion": "1.3"}, SKILL,
    )[2]
    verify_runtime_only(published, staged, published_libraries, libraries(client, base, True))
    evidence.update(status="staged", staging=staged)
    _save(checkpoint, evidence)
    # Save intent so an interrupted POST is never automatically repeated.
    evidence["status"] = "ambiguous_publication"
    _save(checkpoint, evidence)
    status, headers, _ = client.request("POST", base + "/staging/publish?beta=false", {}, SKILL)
    if status not in (200, 202):
        raise DeploymentError("Publication acceptance is ambiguous; do not resubmit")
    evidence.update(
        status="publishing", publish_http_status=status,
        publish_operation_id=headers.get("x-ms-operation-id"),
        publish_location=headers.get("location"),
    )
    _save(checkpoint, evidence)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(min(30, max(0, deadline - time.monotonic())))
        details = client.request("GET", base, skill=SKILL)[2]["properties"]["publishDetails"]
        evidence["publish_details"] = details
        _save(checkpoint, evidence)
        if details["state"] == "Success":
            break
        if details["state"] in ("Failed", "Cancelled", "Canceled"):
            raise DeploymentError("Environment publication failed; no automatic retry")
    else:
        raise DeploymentError("Environment deadline exceeded; inspect existing publication, do not resubmit")
    after, after_libraries = compute(), libraries(client, base)
    verify_runtime_only(published, after, published_libraries, after_libraries)
    evidence.update(
        status="verified", after=after, libraries_after=after_libraries,
        verified_at=datetime.now(timezone.utc).isoformat(),
    )
    _save(checkpoint, evidence)
    return evidence


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--system-suffix", required=True)
    parser.add_argument("--apply", action="store_true", help="Explicit runtime-only patch and publication")
    parser.add_argument("--timeout-seconds", type=int, default=720)
    args = parser.parse_args()
    cfg = validate_config(json.loads(args.config.read_text(encoding="utf-8-sig")), "check")
    client = FabricClient(cfg["tenant_id"])
    workspace = preflight(cfg, client)
    result = recover(
        client, workspace["id"], args.system_suffix, ROOT / ".state" / "bps" / "runtime-recovery.json",
        apply=args.apply, timeout=args.timeout_seconds,
    )
    print(json.dumps({
        "status": result["status"], "environment_id": result["environment_id"],
        "published_runtime": result.get("after", result["before"])["runtimeVersion"],
        "publish_details": result.get("publish_details"),
    }))


if __name__ == "__main__":
    main()
