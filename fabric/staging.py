"""Conform actual licensed/CRM exports and upload through discovered OneLake DFS."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from fabric.contracts import validate_record
from fabric.rest import DeploymentError, token


def records(path):
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    rows = value.get("records") if isinstance(value, dict) else value
    if not isinstance(rows, list):
        raise DeploymentError("Source export must be a JSON array or Salesforce records envelope")
    return rows


def source_utc(value):
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise DeploymentError("CRM source timestamp has no offset; cannot infer UTC")
    return timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def conform_salesforce(name, rows):
    mapped = []
    for row in rows:
        if name == "customer":
            state = {"customer_key": row["MSFlix_Key__c"], "name":
                     " ".join(p for p in (row.get("FirstName"), row.get("LastName")) if p),
                     "territory": row["MSFlix_Territory__c"], "source_customer_id": row["Id"]}
        elif name == "campaign":
            state = {"campaign_key": row["MSFlix_Key__c"], "name": row["Name"],
                     "budget_minor": row["MSFlix_BudgetMinor__c"], "currency": row["MSFlix_Currency__c"],
                     "channel": row["MSFlix_Channel__c"], "source_campaign_id": row["Id"]}
        elif name == "consent":
            state = {"consent_key": row["MSFlix_Key__c"], "customer_key": row["CustomerKey__c"],
                     "purpose": row["Purpose__c"], "channel": row["Channel__c"], "granted": row["Granted__c"],
                     "effective_at": source_utc(row["EffectiveAt__c"]), "source_consent_id": row["Id"]}
        elif name == "touch":
            state = {"touch_key": row["MSFlix_Key__c"], "customer_key": row["CustomerKey__c"],
                     "campaign_key": row["CampaignKey__c"], "channel": row["Channel__c"],
                     "touch_type": row["TouchType__c"], "occurred_at": source_utc(row["OccurredAt__c"]),
                     "tracking_token": row.get("TrackingToken__c"), "source_touch_id": row["Id"]}
        else:
            raise DeploymentError("Unsupported CRM export mapping")
        mapped.append(validate_record(name, state))
    return mapped


class OneLake:
    def __init__(self, cfg, workspace, lakehouse):
        self.cfg = cfg
        endpoint = workspace.get("oneLakeEndpoints", {}).get("dfsEndpoint", "")
        host = urlparse(endpoint).netloc
        if not host.endswith(".dfs.fabric.microsoft.com") or urlparse(endpoint).scheme != "https":
            raise DeploymentError("Regional OneLake DFS endpoint was not discovered")
        self.base = endpoint.rstrip("/") + "/" + workspace["id"] + "/" + lakehouse["id"]
        self.evidence = []

    def request(self, method, path, query, data=b""):
        if ".." in Path(path).parts or path.startswith("/") or "\\" in path:
            raise DeploymentError("Unsafe OneLake relative path")
        headers = {"Authorization": "Bearer " + token(self.cfg["tenant_id"], "https://storage.azure.com"),
                   "x-ms-version": "2021-06-08", "Content-Type": "application/octet-stream"}
        req = Request(self.base + "/" + quote(path, safe="/") + "?" + query,
                      data=data, method=method, headers=headers)
        try:
            with urlopen(req, timeout=90) as response:
                status = response.status
        except HTTPError as exc:
            if method == "PUT" and "resource=directory" in query and exc.code == 409:
                status = exc.code
            else:
                raise DeploymentError(f"OneLake HTTP {exc.code}: upload stage failed") from exc
        self.evidence.append({"method": method, "path": path, "status": status, "bytes": len(data)})

    def put(self, path, data):
        for parent in reversed(Path(path).parents):
            text = parent.as_posix()
            if text != ".":
                self.request("PUT", text, "resource=directory")
        self.request("PUT", path, "resource=file")
        self.request("PATCH", path, "action=append&position=0", data)
        self.request("PATCH", path, "action=flush&position=" + str(len(data)))


def stage_exports(cfg, workspace, raw, repository):
    repository = Path(repository)
    lake = OneLake(cfg, workspace, raw)
    counts, paths, provenance = {}, {}, {}
    catalog_path = repository / "data" / "catalog.json"
    catalog = records(catalog_path)
    conformed = {"content": [validate_record("content", row) for row in catalog]}
    # The reference distributor identity is explicitly in the parent's catalog,
    # and its label is supported by the licensed attribution—not a rights grant.
    distributor_keys = {r.get("distributor_key") for r in catalog if r.get("distributor_key")}
    if distributor_keys:
        claimed_rows = [r for r in catalog if r.get("distributor_key")]
        if distributor_keys != {"BLENDER-FOUNDATION"} or not all("Blender Foundation" in r["attribution"] for r in claimed_rows):
            raise DeploymentError("Catalog distributor requires an authoritative source label")
        conformed["distributor"] = [{"distributor_key": "BLENDER-FOUNDATION", "name": "Blender Foundation"}]
    lake.put("Files/ingress/original/catalog.json", catalog_path.read_bytes())
    provenance["catalog"] = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    for file_name, entity in (("customers", "customer"), ("campaigns", "campaign"),
                              ("consents", "consent"), ("touches", "touch")):
        path = repository / ".state" / "salesforce" / (file_name + ".json")
        source = records(path)
        conformed[entity] = conform_salesforce(entity, source)
        lake.put(f"Files/ingress/original/{file_name}.json", path.read_bytes())
        provenance[file_name] = hashlib.sha256(path.read_bytes()).hexdigest()
    for entity, rows in conformed.items():
        payload = (json.dumps(rows, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        path = f"Files/ingress/{entity}.json"
        lake.put(path, payload)
        counts[entity] = len(rows)
        paths[entity] = {"path": path, "format": "json", "multiline": True, "snapshot_complete": False}
    return {"state": "actual_exports_staged", "counts": counts, "sources": paths,
            "source_sha256": provenance, "dfs_calls": lake.evidence}
