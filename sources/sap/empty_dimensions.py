"""Deploy/run an owned schema-only adapter; never edit managed BPS notebooks."""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import nbformat

from fabric.build import cell, part
from fabric.rest import DeploymentError
from sources.sap.datasphere import json_bytes
from sources.sap.empty_runtime import FIELDS, table_root
from sources.sap.fabric_client import ScopedClient, load_target
from sources.salesforce.bps.jobs import ACTIVE, FAILED, KNOWN, _save, _safe_failure

NAME = "MSFlixSAPEmptyDimensionSchemas"
OWNER = "MSFlix SAP schema-only adapter v1"
RECOVERY_VERSION = 2


def definition(target, mirror, silver, environment):
    config = {
        "workspace_id": target["workspace_id"], "source_system": target["source_system"],
        "mirror_id": mirror["id"], "mirror_path": mirror["properties"]["oneLakeTablesPath"],
        "mirror_schema": mirror["properties"]["defaultSchema"],
        "silver_id": silver["id"], "silver_path": silver["properties"]["oneLakeTablesPath"],
        "silver_schema": silver["properties"]["defaultSchema"], "fields": FIELDS,
    }
    for stage in ("mirror", "silver"):
        table_root(config[stage + "_path"], config["workspace_id"], config[stage + "_id"], config[stage + "_schema"])
    doc = {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Synapse PySpark", "language": "python", "name": "synapse_pyspark"},
            "language_info": {"name": "python"},
            "dependencies": {
                "lakehouse": {"default_lakehouse": silver["id"], "default_lakehouse_name": silver["displayName"],
                              "default_lakehouse_workspace_id": target["workspace_id"],
                              "known_lakehouses": [{"id": silver["id"]}]},
                "environment": {"environmentId": environment["id"], "workspaceId": target["workspace_id"]},
            },
        },
        "cells": [
            cell("# SAP empty-dimension schema adapter\n"
                 "Zero business rows. Only missing, typed Silver structures; native BPS still produces Gold.\n",
                 "intro", markdown=True),
            cell(Path(__file__).with_name("empty_runtime.py").read_text(encoding="utf-8"), "runtime"),
            cell("import json\nimport notebookutils\nconfig = " + repr(config) + "\n"
                 "result = materialize(spark, notebookutils, config)\n"
                 "print(json.dumps(result))\nnotebookutils.notebook.exit(json.dumps(result))\n", "execute"),
        ],
    }
    nbformat.validate(nbformat.from_dict(doc))
    return {"format": "ipynb", "parts": [part("notebook-content.ipynb", json.dumps(doc))]}


def run(target, evidence):
    client = ScopedClient(target)
    client.workspace()
    root = "/v1/workspaces/" + target["workspace_id"]
    for item in client.list(root + "/items"):
        if item["type"] == "DataPipeline" and item["displayName"].endswith("_" + target["system_suffix"]):
            if any(j["status"] in ACTIVE for j in client.list(root + "/items/" + item["id"] + "/jobs/instances")):
                raise DeploymentError("Native SAP processing is active; schema recovery refused")
    silver_item = client.item("bps_silver_" + target["system_suffix"], "Lakehouse")
    silver = client.request("GET", root + "/lakehouses/" + silver_item["id"])[2]
    mirror_item = client.item("bps_mirrored_sap_db_S4M_" + target["system_suffix"], "MirroredDatabase")
    if mirror_item["id"] != target["mirror_id"]:
        raise DeploymentError("Native SAP mirror identity changed")
    mirror = client.request("GET", root + "/mirroredDatabases/" + mirror_item["id"])[2]
    environment = client.item("bps_env_" + target["system_suffix"], "Environment")
    payload = definition(target, mirror, silver, environment)
    notebooks = [r for r in client.list(root + "/notebooks") if r["displayName"] == NAME]
    if len(notebooks) > 1:
        raise DeploymentError("Ambiguous empty-dimension recovery notebook")
    if notebooks:
        item = client.request("GET", root + "/notebooks/" + notebooks[0]["id"])[2]
        if item.get("description") != OWNER:
            raise DeploymentError("Refusing an unowned empty-dimension recovery notebook")
        client.operation("POST", root + "/items/" + item["id"] + "/updateDefinition",
                         {"definition": payload}, "spark-cli")
    else:
        item = client.ensure_item(target["workspace_id"], "notebooks", NAME, "spark-cli",
                                  {"description": OWNER, "definition": payload})
    if item.get("description") != OWNER:
        raise DeploymentError("Refusing an unowned empty-dimension recovery notebook")
    jobs_path = root + "/items/" + item["id"] + "/jobs/instances"
    checkpoint = evidence / "empty-dimensions-job.json"
    previous = json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
    if previous.get("state") == "Completed" and previous.get("recovery_version") != RECOVERY_VERSION:
        checkpoint = evidence / f"empty-dimensions-job-v{RECOVERY_VERSION}.json"
        previous = json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
    if previous.get("state") == "ambiguous_submission":
        raise DeploymentError("Schema recovery submission was ambiguous; inspect before resubmitting")
    history = client.list(jobs_path)
    job_id = previous.get("job_id")
    if job_id:
        if previous.get("notebook_id") != item["id"] or not any(j["id"] == job_id for j in history):
            raise DeploymentError("Existing schema recovery checkpoint differs from the native job history")
    else:
        now = datetime.now(timezone.utc)
        for job in history:
            start = datetime.fromisoformat(job["startTimeUtc"].replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if job["status"] in ACTIVE or (now - start).total_seconds() < 300:
                raise DeploymentError("An active/recent schema recovery exists; no duplicate run")
        _save(checkpoint, {"notebook_id": item["id"], "recovery_version": RECOVERY_VERSION,
                           "state": "ambiguous_submission"})
        status, headers, _ = client.request("POST", root + "/items/" + item["id"] + "/jobs/RunNotebook/instances", {})
        expected = "https://api.fabric.microsoft.com" + jobs_path + "/"
        location = headers.get("location", "")
        if status != 202 or not location.startswith(expected):
            raise DeploymentError("Schema recovery acceptance is ambiguous; do not resubmit")
        job_id = location.rsplit("/", 1)[-1]
        _save(checkpoint, {"notebook_id": item["id"], "recovery_version": RECOVERY_VERSION,
                           "job_id": job_id, "state": "accepted"})
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        actual = client.request("GET", jobs_path + "/" + job_id)[2]
        state = actual["status"]
        if state not in KNOWN:
            raise DeploymentError("Unknown schema-recovery job state; existing job preserved")
        row = {"notebook_id": item["id"], "recovery_version": RECOVERY_VERSION,
               "job_id": job_id, "state": state,
               "failure": _safe_failure(actual.get("failureReason"))}
        _save(checkpoint, row)
        if state == "Completed":
            return row
        if state in FAILED:
            raise DeploymentError("Schema-only recovery failed: " + str(row["failure"]))
        time.sleep(20)
    raise DeploymentError("Schema recovery timed out; resume the existing checkpoint")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        target = load_target(args.target)
        result = run(target, args.evidence) if args.apply else {
            "mode": "preview", "fields": FIELDS, "business_rows_written": 0, "gold_written": False}
    except (ValueError, OSError, DeploymentError) as exc:
        parser.exit(2, f"SAP schema-only recovery failed: {exc}\n")
    print(json_bytes(result).decode(), end="")


if __name__ == "__main__":
    main()
