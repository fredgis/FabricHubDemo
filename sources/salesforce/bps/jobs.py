"""Run only discovered, native BPS pipelines; never substitute a custom loader."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from fabric.rest import DeploymentError, safe_error_message

SKILL = "spark-cli"
STAGES = {
    "extraction": "bps_sf_salesforce_data_pull_",
    "silver": "bps_sf_orchestration_pipeline_b2s_processing_",
    "dimensions": "bps_sf_orchestration_pipeline_s2g_dimension_processing_",
    "facts": "bps_sf_orchestration_pipeline_s2g_fact_processing_",
}
ACTIVE = {"NotStarted", "InProgress"}
FAILED = {"Failed", "Cancelled", "Canceled", "Deduped"}
KNOWN = ACTIVE | FAILED | {"Completed"}


def validate_suffix(suffix):
    if not isinstance(suffix, str) or not re.fullmatch(r"[a-f0-9]{8}", suffix):
        raise DeploymentError("Use the discovered eight-character native BPS suffix")


def resolve_pipelines(client, workspace_id, suffix):
    validate_suffix(suffix)
    items = client.list(f"/v1/workspaces/{workspace_id}/items", SKILL)
    pipelines = {}
    for stage, prefix in STAGES.items():
        matches = [
            item for item in items
            if item["type"] == "DataPipeline" and item["displayName"] == prefix + suffix
        ]
        if len(matches) != 1:
            raise DeploymentError("Expected exactly one native BPS pipeline: " + prefix + suffix)
        pipelines[stage] = matches[0]
    return pipelines


def _save(path, evidence):
    """Replace a local checkpoint atomically without writing tokens or payloads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _safe_failure(reason):
    if not reason:
        return None
    return {
        "errorCode": reason.get("errorCode", "Unknown"),
        "message": safe_error_message(reason.get("message", "")),
        "isRetriable": reason.get("isRetriable"),
    }


def run_stage(
    client, workspace_id, suffix, stage, evidence_dir, *, timeout=1800,
    poll_seconds=20, after_completed_job=None, sleep=time.sleep,
    clock=time.monotonic, notify=None,
):
    """Resume active/completed jobs. A completed rerun requires its exact job ID."""
    if stage not in STAGES or not 60 <= timeout <= 1800 or not 10 <= poll_seconds <= 60:
        raise DeploymentError("Invalid stage or bounded polling settings")
    if after_completed_job:
        try:
            UUID(after_completed_job)
        except (ValueError, TypeError) as exc:
            raise DeploymentError("Completed-job acknowledgement must be a job UUID") from exc
    pipelines = resolve_pipelines(client, workspace_id, suffix)
    histories = {}
    for name, item in pipelines.items():
        path = f"/v1/workspaces/{workspace_id}/items/{item['id']}/jobs/instances"
        jobs = client.list(path, SKILL)
        if any(job.get("status") not in KNOWN for job in jobs):
            raise DeploymentError("Unknown native BPS job state; inspect before submitting")
        active = [job for job in jobs if job["status"] in ACTIVE]
        if len(active) > 1:
            raise DeploymentError("Multiple active native BPS runs; no new job submitted")
        if active and name != stage:
            raise DeploymentError("Another BPS stage is active: " + name)
        histories[name] = jobs

    for prerequisite in list(STAGES)[:list(STAGES).index(stage)]:
        history = histories[prerequisite]
        latest = max(
            history, key=lambda job: job.get("startTimeUtc") or job.get("endTimeUtc") or "",
            default=None,
        )
        if not latest or latest["status"] != "Completed":
            raise DeploymentError("Native BPS prerequisite is not completed: " + prerequisite)

    item, jobs = pipelines[stage], histories[stage]
    jobs_path = f"/v1/workspaces/{workspace_id}/items/{item['id']}/jobs/instances"
    checkpoint = Path(evidence_dir) / (stage + "-job.json")
    previous = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else {}
    if previous.get("workspace_id") not in (None, workspace_id):
        raise DeploymentError("Checkpoint belongs to a different workspace")
    if previous.get("pipeline_id") not in (None, item["id"]):
        raise DeploymentError("Checkpoint belongs to a different native BPS pipeline")
    if previous.get("state") == "ambiguous_submission":
        raise DeploymentError("Previous submission is ambiguous; reconcile its history before rerun")

    active = [job for job in jobs if job["status"] in ACTIVE]
    completed = sorted(
        (job for job in jobs if job["status"] == "Completed"),
        key=lambda job: job.get("endTimeUtc") or job.get("startTimeUtc") or "",
        reverse=True,
    )
    submitted = False
    if active:
        job_id = active[0]["id"]
    elif completed and not after_completed_job:
        job_id = completed[0]["id"]
    else:
        if after_completed_job and (
            not completed or completed[0]["id"] != after_completed_job
        ):
            raise DeploymentError("Acknowledgement does not match the latest completed native run")
        # Persist intent BEFORE POST. An interrupted/ambiguous submission is never
        # blindly retried, even if history has not yet become eventually consistent.
        intent = {
            "workspace_id": workspace_id, "pipeline": item["displayName"],
            "pipeline_id": item["id"], "stage": stage, "system_suffix": suffix,
            "state": "ambiguous_submission", "data_verified": False,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        _save(checkpoint, intent)
        status, headers, _ = client.request(
            "POST", jobs_path + "?jobType=Pipeline", {}, SKILL,
        )
        location = headers.get("location", "")
        parsed = urlparse(location)
        expected_path = jobs_path + "/"
        if (
            status != 202 or parsed.scheme != "https"
            or parsed.netloc != "api.fabric.microsoft.com"
            or not parsed.path.startswith(expected_path)
        ):
            raise DeploymentError("BPS submission ambiguous; inspect history, do not resubmit")
        job_id = parsed.path.rstrip("/").split("/")[-1]
        try:
            UUID(job_id)
        except ValueError as exc:
            raise DeploymentError("BPS submission returned no valid job ID; do not resubmit") from exc
        submitted = True

    history = previous.get("previous_runs", [])
    if previous.get("job_id") and previous["job_id"] != job_id:
        history = history + [{
            key: previous.get(key)
            for key in ("job_id", "state", "started_at", "failure")
        }]
    evidence = {
        "workspace_id": workspace_id, "pipeline": item["displayName"],
        "pipeline_id": item["id"], "job_id": job_id, "stage": stage,
        "system_suffix": suffix, "state": "submitted" if submitted else "resumed",
        "started_at": (
            previous.get("started_at") if previous.get("job_id") == job_id
            else datetime.now(timezone.utc).isoformat()
        ),
        "data_verified": (
            bool(previous.get("data_verified")) if previous.get("job_id") == job_id else False
        ),
        "previous_runs": history,
    }
    _save(checkpoint, evidence)  # Capture the accepted job before any polling call.
    if notify:
        notify(evidence)
    location = jobs_path + "/" + job_id
    deadline = clock() + timeout
    while clock() < deadline:
        job = client.request("GET", location, skill=SKILL)[2]
        state = job.get("status")
        evidence.update(
            state=state, failure=_safe_failure(job.get("failureReason")),
            job_start_time_utc=job.get("startTimeUtc"),
            job_end_time_utc=job.get("endTimeUtc"),
        )
        _save(checkpoint, evidence)
        if state == "Completed":
            if notify:
                notify(evidence)
            return evidence
        if state in FAILED:
            raise DeploymentError(
                f"Native BPS pipeline {state}, job {job_id}: {evidence['failure']}"
            )
        if state not in ACTIVE:
            raise DeploymentError("Unknown native BPS status; no resubmission: " + str(state))
        sleep(min(poll_seconds, max(0, deadline - clock())))
    raise DeploymentError("BPS deadline exceeded; job " + job_id + " was not resubmitted")
