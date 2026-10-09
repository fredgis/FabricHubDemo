"""Run only the dedicated native SAP BPS pipelines, with resumable accepted job IDs."""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from uuid import UUID

from fabric.rest import DeploymentError
from sources.salesforce.bps.jobs import ACTIVE, FAILED, KNOWN, _safe_failure, _save
from sources.sap.config import read_json
from sources.sap.datasphere import json_bytes
from sources.sap.fabric_client import ScopedClient, load_target

PREFIX = {"b2s": "bps_datasphere_b2s_orchestration_pipeline_",
          "s2g": "bps_s2g_full_processing_pipeline_"}


def silver_evidence_path(evidence: Path, job_id: str) -> Path:
    return evidence / ("silver-qualified-" + str(UUID(job_id)) + ".json")


def run(target: dict, stage: str, evidence: Path, timeout=7200, after_completed_job=None, retry_failed_job=None,
        adopt_scheduled_job=None) -> dict:
    client = ScopedClient(target)
    client.workspace()
    suffix = target["system_suffix"]
    root = "/v1/workspaces/" + target["workspace_id"]
    item = client.item(PREFIX[stage] + suffix, "DataPipeline")
    checkpoint = evidence / (stage + "-job.json")
    previous = read_json(checkpoint) if checkpoint.exists() else {}
    if previous.get("workspace_id") not in (None, target["workspace_id"]) or previous.get("pipeline_id") not in (None, item["id"]):
        raise DeploymentError("Existing SAP checkpoint belongs to another native target")
    if previous.get("state") == "ambiguous_submission":
        raise DeploymentError("SAP submission was ambiguous; reconcile job history before resubmitting")
    if sum(bool(v) for v in (after_completed_job, retry_failed_job, adopt_scheduled_job)) > 1:
        raise DeploymentError("Choose either a completed rerun, exact failed-job retry, or scheduled-job adoption")
    family = [r for r in client.list(root + "/items") if r["type"] == "DataPipeline"
              and r["displayName"].endswith("_" + suffix)]
    histories = {}
    for pipeline in family:
        jobs = client.list(root + "/items/" + pipeline["id"] + "/jobs/instances")
        if any(j["status"] not in KNOWN for j in jobs):
            raise DeploymentError("Unknown native SAP job state")
        histories[pipeline["id"]] = jobs
        if any(j["status"] in ACTIVE for j in jobs) and pipeline["id"] != item["id"]:
            if previous.get("job_id") is None or after_completed_job or retry_failed_job:
                raise DeploymentError("Another SAP stage is active; no new processing submitted")
    if stage == "s2g":
        prereq = read_json(evidence / "b2s-job.json")
        if prereq.get("state") != "Completed":
            raise DeploymentError("Native SAP Bronze-to-Silver must complete before Gold processing")
        source = client.item(PREFIX["b2s"] + suffix, "DataPipeline")
        actual = client.request("GET", root + "/items/" + source["id"] + "/jobs/instances/" + prereq["job_id"])[2]
        if actual["status"] != "Completed":
            raise DeploymentError("Native prerequisite readback is not Completed")
        latest_source = max(histories[source["id"]], key=lambda j: j.get("startTimeUtc", ""), default=None)
        if not latest_source or latest_source["id"] != prereq["job_id"] or latest_source["status"] != "Completed":
            raise DeploymentError("Gold processing requires the latest completed native B2S job")
        proof = read_json(silver_evidence_path(evidence, prereq["job_id"]))
        if (proof.get("version") != 1 or proof.get("source_stage") != "silver"
                or proof.get("data_verified") is not True or proof.get("workspace_id") != target["workspace_id"]
                or proof.get("jobs", {}).get("b2s") != {"pipeline_id": source["id"], "job_id": prereq["job_id"]}):
            raise DeploymentError("Native Silver qualification must match the completed B2S job before Gold processing")
    jobs = histories[item["id"]]
    active = [j for j in jobs if j["status"] in ACTIVE]
    if len(active) > 1:
        raise DeploymentError("Multiple active SAP runs; do not submit")
    job_id = previous.get("job_id")
    adopted = previous.get("adopted_scheduled_job")
    if retry_failed_job or after_completed_job:
        adopted = None
    if adopt_scheduled_job:
        latest = max(jobs, key=lambda j: j.get("startTimeUtc", ""), default=None)
        if not latest or latest["id"] != adopt_scheduled_job:
            raise DeploymentError("Adoption must acknowledge the exact latest scheduled native job")
        if job_id not in (None, adopt_scheduled_job) and previous.get("state") not in FAILED | {"Completed"}:
            raise DeploymentError("An accepted SAP checkpoint must be resumed before adopting another job")
        actual = client.request("GET", root + "/items/" + item["id"] + "/jobs/instances/" + adopt_scheduled_job)[2]
        if (actual.get("id") != adopt_scheduled_job or actual.get("itemId") != item["id"]
                or actual.get("jobType") != "Pipeline" or actual.get("invokeType") != "Scheduled"
                or actual.get("status") not in ACTIVE | {"Completed"}):
            raise DeploymentError("Only an exact active/completed scheduled SAP job may be adopted")
        job_id = adopted = adopt_scheduled_job
        _save(checkpoint, {"workspace_id": target["workspace_id"], "pipeline_id": item["id"],
                          "job_id": job_id, "stage": stage, "state": "accepted", "data_verified": False,
                          "adopted_scheduled_job": adopted})
    if retry_failed_job:
        failed = [j for j in jobs if j["id"] == retry_failed_job and j["status"] in FAILED]
        latest = max(jobs, key=lambda j: j.get("startTimeUtc", ""), default=None)
        if len(failed) != 1 or not latest or latest["id"] != retry_failed_job:
            raise DeploymentError("Retry must acknowledge the exact latest failed native job")
        if previous.get("job_id") not in (None, retry_failed_job):
            checkpointed = [j for j in jobs if j["id"] == previous["job_id"]]
            if (len(checkpointed) != 1 or not checkpointed[0].get("startTimeUtc")
                    or not failed[0].get("startTimeUtc")
                    or checkpointed[0]["startTimeUtc"] >= failed[0]["startTimeUtc"]):
                raise DeploymentError("A newer accepted SAP job is checkpointed; resume it instead of retrying an older failure")
        job_id = None
    if job_id and not after_completed_job:
        if not any(j["id"] == job_id for j in jobs):
            raise DeploymentError("Checkpointed SAP job is missing")
    elif active:
        raise DeploymentError("An uncheckpointed SAP job is active; reconcile it explicitly")
    else:
        completed = sorted((j for j in jobs if j["status"] == "Completed"),
                           key=lambda j: j.get("endTimeUtc", ""), reverse=True)
        if completed and not retry_failed_job and (not after_completed_job or completed[0]["id"] != after_completed_job):
            raise DeploymentError("A completed SAP stage requires its exact latest job ID before rerun")
        state = {"workspace_id": target["workspace_id"], "pipeline_id": item["id"], "stage": stage,
                 "state": "ambiguous_submission", "data_verified": False}
        _save(checkpoint, state)
        code, headers, _ = client.request("POST", root + "/items/" + item["id"] + "/jobs/instances?jobType=Pipeline", {})
        location = headers.get("location", "")
        expected = "https://api.fabric.microsoft.com" + root + "/items/" + item["id"] + "/jobs/instances/"
        if code != 202 or not location.startswith(expected):
            raise DeploymentError("SAP submission acceptance is ambiguous; inspect before retrying")
        job_id = location.rsplit("/", 1)[-1]
        _save(checkpoint, {**state, "state": "accepted", "job_id": job_id})
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        result = client.request("GET", root + "/items/" + item["id"] + "/jobs/instances/" + job_id)[2]
        state = result["status"]
        if state not in KNOWN:
            raise DeploymentError("Unknown SAP job status; keep the existing job checkpoint")
        evidence_row = {
            "workspace_id": target["workspace_id"], "pipeline_id": item["id"], "job_id": job_id, "stage": stage,
            "state": state, "data_verified": False, "failure": _safe_failure(result.get("failureReason")),
        }
        if adopted:
            evidence_row["adopted_scheduled_job"] = adopted
        _save(checkpoint, evidence_row)
        if state != last:
            print(f"SAP {stage}: {state}; job {job_id}", flush=True)
            last = state
        if state == "Completed":
            return evidence_row
        if state in FAILED:
            raise DeploymentError(f"Native SAP {stage} failed: {evidence_row['failure']}")
        time.sleep(30)
    raise DeploymentError("Native SAP deadline exceeded; resume the checkpointed job, never resubmit it blindly")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--stage", choices=PREFIX, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    parser.add_argument("--after-completed-job")
    parser.add_argument("--retry-failed-job")
    parser.add_argument("--adopt-scheduled-job")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not 60 <= args.timeout_seconds <= 10800:
        parser.error("SAP processing timeout must be 60-10800 seconds")
    target = load_target(args.target)
    if not args.apply:
        print(json_bytes({"mode": "preview", "pipeline": PREFIX[args.stage] + target["system_suffix"]}).decode(), end="")
        return
    try:
        result = run(target, args.stage, args.evidence, args.timeout_seconds, args.after_completed_job,
                     args.retry_failed_job, args.adopt_scheduled_job)
    except (ValueError, OSError, DeploymentError) as exc:
        parser.exit(2, f"SAP processing failed: {exc}\n")
    print(json_bytes(result).decode(), end="")


if __name__ == "__main__":
    main()
