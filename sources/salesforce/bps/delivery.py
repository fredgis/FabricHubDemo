"""Bounded continuation of UI-configured native BPS marketing ingestion."""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from fabric.deploy import preflight, validate_config
from fabric.rest import DeploymentError, FabricClient
from fabric.staging import conform_salesforce
from sources.salesforce.bps.jobs import FAILED, _save, run_stage
from sources.salesforce.bps.snapshot import snapshot

ROOT = Path(__file__).resolve().parents[3]
EXPECTED = {"campaign": 6, "consent": 700, "touch": 600}


def validate_snapshots(directory, provenance):
    """Validate real snapshots with the unchanged parent adapter and actual keys."""
    canonical, summary = {}, {}
    for entity, evidence in provenance.items():
        path = Path(evidence["snapshot_file"])
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = conform_salesforce(entity, raw)
        key = entity + "_key"
        keys = {row[key] for row in rows}
        if len(raw) != EXPECTED[entity] or len(rows) != len(raw) or len(keys) != len(rows):
            raise DeploymentError("Actual native " + entity + " count/key acceptance failed")
        canonical[entity] = rows
        summary[entity] = {
            "snapshot_file": str(path), "provenance_file": str(path.with_name(
                path.name.replace(".native.json", ".provenance.json"))),
            "row_count": len(rows), "distinct_business_keys": len(keys),
            "actual_source_layer": evidence["layer"], "processed_silver": evidence["processed_silver"],
            "delta_path": evidence["delta_path"], "sql_endpoint_id": evidence["sql_endpoint_id"],
            "schema": evidence["schema"], "table": evidence["table"],
            "adapter": "fabric.staging.conform_salesforce",
        }
    customer_file = Path(directory) / "contact.silver.native.json"
    customers = {
        row["MSFlix_Key__c"]
        for row in json.loads(customer_file.read_text(encoding="utf-8"))
    }
    campaign_keys = {row["campaign_key"] for row in canonical["campaign"]}
    for entity in ("consent", "touch"):
        if any(row["customer_key"] not in customers for row in canonical[entity]):
            raise DeploymentError("Actual native " + entity + " has an unknown parent customer key")
    if any(row["campaign_key"] not in campaign_keys for row in canonical["touch"]):
        raise DeploymentError("Actual native touches have an unknown native campaign key")
    return summary


def export_marketing(cfg, client, workspace, suffix, source_system, directory, layer):
    """Retry only bounded SQL metadata visibility; never rerun extraction here."""
    evidence = {}
    for entity in EXPECTED:
        for attempt in range(4):
            try:
                evidence[entity] = snapshot(
                    cfg, client, workspace, suffix, layer, source_system, directory,
                    entity=entity, output_label="silver",
                )
                break
            except DeploymentError as exc:
                if attempt == 3 or ("missing" not in str(exc) and "empty" not in str(exc)):
                    raise
                time.sleep(20)
    return validate_snapshots(directory, evidence)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--system-suffix", required=True)
    parser.add_argument("--source-system", required=True)
    parser.add_argument("--after-extraction-job", required=True)
    parser.add_argument("--after-silver-job", required=True)
    parser.add_argument("--after-dimensions-job", required=True)
    parser.add_argument("--after-facts-job", required=True)
    args = parser.parse_args()
    cfg = validate_config(json.loads(args.config.read_text(encoding="utf-8-sig")), "check")
    client = FabricClient(cfg["tenant_id"])
    workspace = preflight(cfg, client)["id"]
    directory = ROOT / ".state" / "bps"
    state_file = directory / "marketing-delivery.json"
    state = {
        "environment": cfg["environment"], "workspace_id": workspace,
        "source_system": args.source_system, "system_suffix": args.system_suffix,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "state": "awaiting_existing_incremental_extraction", "jobs": {},
    }
    _save(state_file, state)

    def milestone(name, **details):
        state.update(state=name, updated_at=datetime.now(timezone.utc).isoformat(), **details)
        _save(state_file, state)
        print(json.dumps({"milestone": name, **details}), flush=True)

    # The caller already submitted the deliberate extraction rerun. Watch that
    # accepted checkpoint instead of posting or racing another extraction runner.
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        checkpoint = directory / "extraction-job.json"
        job = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else {}
        if job.get("job_id") and job["job_id"] != args.after_extraction_job:
            if job.get("state") in FAILED:
                raise DeploymentError("Native incremental extraction failed: " + str(job.get("failure")))
            if job.get("state") == "Completed":
                state["jobs"]["extraction"] = {
                    "job_id": job["job_id"], "pipeline_id": job["pipeline_id"], "state": job["state"],
                }
                milestone("extraction_complete", job=state["jobs"]["extraction"])
                break
        time.sleep(20)
    else:
        raise DeploymentError("Existing incremental extraction wait exceeded; no duplicate submitted")

    bronze = export_marketing(
        cfg, client, workspace, args.system_suffix, args.source_system, directory, "bronze",
    )
    milestone("marketing_snapshots_ready", snapshots=bronze)

    acknowledgements = {
        "silver": args.after_silver_job,
        "dimensions": args.after_dimensions_job,
        "facts": args.after_facts_job,
    }
    for stage in ("silver", "dimensions", "facts"):
        job = run_stage(
            client, workspace, args.system_suffix, stage, directory,
            timeout=900, after_completed_job=acknowledgements[stage],
            notify=lambda item: print(json.dumps({
                "native_stage": item["stage"], "job_id": item["job_id"], "state": item["state"],
            }), flush=True),
        )
        state["jobs"][stage] = {
            "job_id": job["job_id"], "pipeline_id": job["pipeline_id"], "state": job["state"],
        }
        if stage == "silver":
            silver = export_marketing(
                cfg, client, workspace, args.system_suffix, args.source_system, directory, "silver",
            )
            milestone("processed_silver_snapshots_ready", snapshots=silver, jobs=state["jobs"])
        else:
            milestone(stage + "_complete", jobs=state["jobs"])
    milestone("native_marketing_delivery_complete", jobs=state["jobs"])


if __name__ == "__main__":
    main()
