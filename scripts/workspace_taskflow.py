"""Deploy/read back the native MSFlix Task Flow and organize workspace items.

Task Flow uses the exact observed portal contract and workspace DNS routing.
Folder writes use documented public APIs. Authentication stays in CLI caches.
"""

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import UUID, NAMESPACE_URL, uuid5

API = "https://api.fabric.microsoft.com"
ROOT = Path(__file__).resolve().parents[1]
TASKS = (
    ("oracle", "Oracle references", "Mirror data"),
    ("crm", "Salesforce BPS CRM", "Get data"),
    ("rti", "RTI transactions", "Track data"),
    ("raw", "Raw", "Store data"),
    ("silver", "Silver conformance", "Prepare data"),
    ("gold", "Warehouse Gold business domains", "Store data"),
    ("ontology", "Ontology v2", "General"),
    ("cockpit", "Cockpit Apps", "Develop data"),
    ("flixy", "Flixy", "General"),
)
EDGES = (
    ("oracle", "raw", "Mirrored reference shortcuts"),
    ("crm", "raw", "BPS CRM handoff; conformance qualification required"),
    ("rti", "raw", "KQL native OneLake availability to physical Raw"),
    ("raw", "silver", "Validated source and event conformance"),
    ("silver", "gold", "Publication-gated Warehouse load"),
    ("gold", "ontology", "Gold business facts and junctions; binding/instance qualification gate"),
    ("gold", "cockpit", "Actual Warehouse read surface"),
    ("ontology", "cockpit", "Business Graph; instances gate"),
    ("cockpit", "rti", "Committed operational outbox to Event Hubs"),
    ("gold", "flixy", "Consolidated Warehouse source for the native Data Agent"),
    ("ontology", "flixy", "Ontology via its actual native GraphModel source"),
    ("flixy", "cockpit", "Source-grounded read-only Flixy conversation"),
)
FOLDERS = {
    "oracle": "01 Oracle References",
    "crm": "02 Salesforce BPS",
    "rti": "03 RTI Transactions",
    "raw": "04 Raw",
    "silver": "05 Silver Conformance",
    "gold": "06 Gold Business Domains",
    "ontology": "07 Ontology v2",
    "cockpit": "08 Cockpit",
    "flixy": "09 Flixy",
}
MOVABLE = {
    ("MSFlix_OracleMirror", "MirroredDatabase"): "oracle",
    ("MSFlixEventhouse", "Eventhouse"): "rti",
    ("MSFlixIngress", "Eventstream"): "rti",
    ("MSFlixRaw", "Lakehouse"): "raw",
    ("MSFlixRawProcessing", "Notebook"): "raw",
    ("MSFlixSilver", "Lakehouse"): "silver",
    ("MSFlixSilverProcessing", "Notebook"): "silver",
    ("MSFlixGold", "Warehouse"): "gold",
    ("MSFlixBusiness", "Ontology"): "ontology",
    ("Flixy", "DataAgent"): "flixy",
}
EXACT_ROLES = {
    "MSFlix_OracleMirror": "oracle",
    "MSFlixSalesforceSQLdb": "crm",
    "MSFlixEventhouse": "rti",
    "MSFlixEvents": "rti",
    "MSFlixIngress": "rti",
    "MSFlixRaw": "raw",
    "MSFlixRawProcessing": "raw",
    "MSFlixSilver": "silver",
    "MSFlixSilverProcessing": "silver",
    "MSFlixGold": "gold",
    "MSFlixBusiness": "ontology",
    "MSFlix Business Control": "cockpit",
    "Flixy": "flixy",
}
PORTAL_TYPES = {
    "SQLEndpoint": "SqlAnalyticsEndpoint",
    "SQLDatabase": "SQLDbNative",
    "MirroredDatabase": "MountedRelationalDatabase",
    "Notebook": "SynapseNotebook",
    "DataPipeline": "Pipeline",
    "KQLDatabase": "KustoDatabase",
    "Eventhouse": "KustoEventHouse",
    "Eventstream": "EventStream",
    "UserDataFunction": "FunctionSet",
    "GraphModel": "GraphIndex",
    "Microsoft.WaaS.BusinessProcessSolutions": "Microsoft.WaaS",
}


class Gate(RuntimeError):
    pass


def guid(value):
    return str(UUID(value))


def azure(*args):
    command = shutil.which("az")
    if not command:
        raise Gate("Azure CLI is not installed.")
    result = subprocess.run(
        [command, *args, "--output", "json", "--only-show-errors"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        # Authentication diagnostics can contain sensitive identifiers or URLs.
        raise Gate("Cached Azure CLI operation failed; no login was attempted.")
    return json.loads(result.stdout)


class Client:
    def __init__(self, tenant, subscription):
        account = azure("account", "show", "--subscription", subscription)
        if account.get("tenantId") != tenant:
            raise Gate("The cached account is outside the supplied tenant.")
        token = azure(
            "account", "get-access-token", "--subscription", subscription,
            "--resource", API,
        )["accessToken"]
        segment = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
        if claims.get("tid") != tenant:
            raise Gate("The Fabric token is outside the supplied tenant.")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "x-ms-fabric-skill": "spark-cli",
            "Content-Type": "application/json",
        }

    def request(self, method, path, body=None):
        url = API + path if path.startswith("/") else path
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "api.fabric.microsoft.com":
            raise Gate("Refusing a request outside the public Fabric API host.")
        data = None if body is None else json.dumps(body).encode("utf-8")
        try:
            with urlopen(Request(url, data=data, headers=self.headers, method=method),
                         timeout=60) as response:
                payload = response.read()
                return json.loads(payload) if payload else {}
        except HTTPError as error:
            try:
                code = json.loads(error.read()).get("errorCode", "Unspecified")
            except (ValueError, AttributeError):
                code = "Unspecified"
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(code)):
                code = "Unspecified"
            raise Gate(f"Fabric HTTP {error.code}: {code}; no ambiguous write retried.") from None
        except (URLError, TimeoutError):
            raise Gate("Fabric request failed; no ambiguous write retried.") from None

    def list(self, path):
        items = []
        while path:
            page = self.request("GET", path)
            items.extend(page["value"])
            path = page.get("continuationUri")
            if page.get("continuationToken") and not path:
                raise Gate("Pagination token without a documented continuation URI.")
        return items


def role(item):
    name = item["displayName"]
    if name.startswith("bps_") and name.endswith("_8fbe0076"):
        return "crm"
    if name == "MSFlix" and item["type"] == "Microsoft.WaaS.BusinessProcessSolutions":
        return "crm"
    if name.startswith("MSFlixBusiness_"):
        return "ontology"
    return EXACT_ROLES.get(name)


def in_scope(item):
    name = item["displayName"]
    return (name.startswith("MSFlix")
            or (name.startswith("bps_") and name.endswith("_8fbe0076"))
            or (name == "Flixy" and item["type"] == "DataAgent"))


def mapping(items):
    result = []
    for item in items:
        if not in_scope(item):
            continue
        key = role(item)
        if not key:
            raise Gate(f"An in-scope {item['type']} item has no qualified logical task mapping.")
        result.append({
            "item_id": item["id"], "name": item["displayName"], "type": item["type"],
            "logical_task": key, "folder_id": item.get("folderId"),
        })
    return sorted(result, key=lambda row: (row["logical_task"], row["name"], row["type"]))


def task_graph(items):
    has_flixy = any(item["logical_task"] == "flixy" for item in items)
    tasks = tuple(task for task in TASKS if task[0] != "flixy" or has_flixy)
    keys = {task[0] for task in tasks}
    edges = tuple(edge for edge in EDGES if edge[0] in keys and edge[1] in keys)
    return tasks, edges


def organize(client, base, items, folders, include_native_groups=False):
    operations = []
    for item in items:
        key = MOVABLE.get((item["displayName"], item["type"]))
        native_key = role(item)
        if include_native_groups and native_key in ("crm", "cockpit"):
            if item["type"] == "SQLEndpoint":
                continue  # Native endpoints follow their parent.
            key = native_key
        if not key:
            continue
        if include_native_groups and item["type"] == "Microsoft.WaaS.BusinessProcessSolutions":
            # This exact native parent already returned EntityNotFound on the
            # documented move API. Do not repeat the failed operation.
            operations.append({
                "unmoved_item_id": item["id"],
                "gate": "Native BPS solution move returned HTTP 404 EntityNotFound",
            })
            continue
        description = item.get("description") or ""
        owned = description.startswith("MSFlix analytics managed:") or (
            key == "oracle" and description.startswith("MSFlix Oracle reference mirror:")
        ) or (include_native_groups and key in ("crm", "cockpit"))
        # Existing user placement wins. Only root-level, positively owned parents move.
        if not owned or item.get("folderId"):
            continue
        name = FOLDERS[key]
        matches = [f for f in folders if f["displayName"] == name and not f.get("parentFolderId")]
        if len(matches) > 1:
            raise Gate("Ambiguous existing root folder; refusing organization.")
        if matches:
            folder = matches[0]
        else:
            folder = client.request("POST", base + "/folders", {"displayName": name})
            folders.append(folder)
            operations.append({"created_folder": name, "folder_id": folder["id"]})
        moved = client.request(
            "POST", base + f"/items/{item['id']}/move", {"targetFolderId": folder["id"]},
        )["value"]
        if not any(row["id"] == item["id"] for row in moved):
            raise Gate("Move response did not include its parent item.")
        if any(role(row) != key or row.get("folderId") != folder["id"] for row in moved):
            raise Gate("Native move response exceeded the qualified item family.")
        operations.append({
            "moved_parent_id": item["id"], "folder_id": folder["id"],
            "moved_item_ids": [row["id"] for row in moved],
        })
        # A native app/solution may move several parents and children together.
        # Update the inventory so none of those children is moved independently.
        by_id = {row["id"]: row for row in moved}
        for existing in items:
            if existing["id"] in by_id:
                existing.update(by_id[existing["id"]])
    return operations


def native_taskflow(args, items):
    """Use the captured taskflow202602/202512 DTO and shared-BE host adapter."""
    tasks, edges = task_graph(items)
    key = UUID(args.workspace).hex
    base = f"https://{key}.z{key[:2]}.w.api.fabric.microsoft.com/metadata/workspaces/{args.workspace}"
    token = azure("account", "get-access-token", "--subscription", args.subscription,
                  "--resource", "https://analysis.windows.net/powerbi/api")["accessToken"]
    segment = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
    if claims.get("tid") != args.tenant:
        raise Gate("The cached Power BI token is outside the approved tenant.")
    headers = {
        "Authorization": f"Bearer {token}", "x-ms-fabric-skill": "spark-cli",
        "Content-Type": "application/json",
    }

    def request(method, path, body=None, etag=None):
        current = dict(headers)
        if etag:
            current["If-Match"] = etag
        data = None if body is None else json.dumps(body).encode("utf-8")
        try:
            with urlopen(Request(base + path, headers=current, data=data, method=method),
                         timeout=60) as response:
                raw = response.read()
                return (response.status, dict(response.headers),
                        json.loads(raw) if raw else None)
        except HTTPError as error:
            raise Gate(f"Native Task Flow HTTP {error.code}; no ambiguous write retried.") from None
        except (URLError, TimeoutError):
            raise Gate("Native Task Flow network failure; no ambiguous write retried.") from None

    _, _, before = request("GET", "/taskflow202602")
    flow_id = str(uuid5(NAMESPACE_URL, f"MSFlix:{args.workspace}:business-architecture"))
    existing = next((row for row in before if row["taskFlow"]["id"] == flow_id), None)
    if not args.deploy_taskflow:
        if not existing:
            raise Gate("The native MSFlix Task Flow has not been persisted.")
        flow = existing["taskFlow"]
        count = sum(len(task["items"]) for task in flow["tasks"])
        identities = {item["artifactUniqueId"] for task in flow["tasks"] for item in task["items"]}
        portal_ids = [item["artifactUniqueId"].split(":", 1)[1]
                      for task in flow["tasks"] for item in task["items"]
                      if item["artifactType"] == "Microsoft.WaaS"]
        portal_bps_id = args.bps_portal_item_id or (portal_ids[0] if len(set(portal_ids)) == 1 else None)
        expected = set()
        for item in items:
            kind = PORTAL_TYPES.get(item["type"], item["type"])
            native_id = portal_bps_id if kind == "Microsoft.WaaS" else item["item_id"]
            task_id = str(uuid5(UUID(flow_id), item["logical_task"]))
            expected.add((task_id, kind, f"{kind}:{native_id}"))
        actual = {(task["id"], item["artifactType"], item["artifactUniqueId"])
                  for task in flow["tasks"] for item in task["items"]}
        complete = (len(flow["tasks"]) == len(tasks) and len(flow["edges"]) == len(edges)
                    and count == len(items) == len(identities) and actual == expected)
        return {
            "persisted": complete, "flow_id": flow_id, "resource_id": existing["resourceId"],
            "etag": existing["etag"], "task_count": len(flow["tasks"]),
            "connector_count": len(flow["edges"]), "assignment_count": count,
            "tasks": flow["tasks"], "route": base,
        }

    # Keep a complete pre-write snapshot. Do not replace another user's canvas.
    directory = ROOT / ".state" / "taskflow"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    (directory / f"native-backup-{stamp}.json").write_text(
        json.dumps(before, indent=2) + "\n", encoding="utf-8")
    portal_bps_id = args.bps_portal_item_id
    if not portal_bps_id and existing:
        aliases = [item["artifactUniqueId"].split(":", 1)[1]
                   for task in existing["taskFlow"]["tasks"] for item in task["items"]
                   if item["artifactType"] == "Microsoft.WaaS"]
        if len(set(aliases)) == 1:
            portal_bps_id = guid(aliases[0])
    if any(item["type"] == "Microsoft.WaaS.BusinessProcessSolutions" for item in items) and not portal_bps_id:
        raise Gate("Supply the observed --bps-portal-item-id; do not guess its public/native alias.")
    locations = {
        "oracle": "0 0", "crm": "0 220", "rti": "0 440", "raw": "360 220",
        "silver": "700 220", "gold": "1040 220", "ontology": "1380 100", "cockpit": "1700 340",
        "flixy": "1700 100",
    }
    node_ids = {key: str(uuid5(UUID(flow_id), key)) for key, _, _ in tasks}
    previous_tasks = {task["id"]: task for task in existing["taskFlow"]["tasks"]} if existing else {}
    previous_edges = {edge["id"]: edge for edge in existing["taskFlow"]["edges"]} if existing else {}
    edge_ids = {str(uuid5(UUID(flow_id), source + "->" + target)) for source, target, _ in edges}
    if set(previous_tasks) - set(node_ids.values()) or set(previous_edges) - edge_ids:
        raise Gate("Existing canvas contains unrecognized tasks or connectors; no overwrite.")
    flow = {
        "id": flow_id, "name": "MSFlix Business Architecture",
        "description": "Oracle and native BPS CRM plus committed RTI transactions → Raw → Silver → Gold business domains → Ontology and Business Control. SAP and Planning are not deployed.",
        "tasks": [{
            "id": node_ids[key], "name": name, "type": kind.lower(), "description": name,
            "loc": locations[key], **previous_tasks.get(node_ids[key], {}), "items": [],
        } for key, name, kind in tasks],
        "edges": [{
            "id": str(uuid5(UUID(flow_id), source + "->" + target)),
            "source": node_ids[source], "target": node_ids[target],
            **previous_edges.get(str(uuid5(UUID(flow_id), source + "->" + target)), {}),
        } for source, target, _ in edges],
    }
    task_by_key = {key: flow["tasks"][index] for index, (key, _, _) in enumerate(tasks)}
    bindings = []
    for item in items:
        kind = PORTAL_TYPES.get(item["type"], item["type"])
        native_id = portal_bps_id if kind == "Microsoft.WaaS" else item["item_id"]
        dto = {"artifactType": kind, "artifactUniqueId": f"{kind}:{native_id}"}
        task = task_by_key[item["logical_task"]]
        task["items"].append(dto)
        bindings.append({"public_item_id": item["item_id"], "task_id": task["id"], **dto})
    if existing:
        previous_assignments = {(task["id"], item["artifactType"], item["artifactUniqueId"])
                                for task in previous_tasks.values() for item in task["items"]}
        next_assignments = {(row["task_id"], row["artifactType"], row["artifactUniqueId"])
                            for row in bindings}
        if not previous_assignments.issubset(next_assignments):
            raise Gate("An existing item assignment would change or disappear; no overwrite.")
    (directory / f"native-bindings-{stamp}.json").write_text(
        json.dumps(bindings, indent=2) + "\n", encoding="utf-8")
    if existing:
        request("PUT", "/taskflow202512/" + existing["resourceId"], flow, existing["etag"])
    else:
        request("POST", "/taskflow202512", flow)
    _, _, after = request("GET", "/taskflow202602")
    current = next(row for row in after if row["taskFlow"]["id"] == flow_id)
    actual = current["taskFlow"]
    assigned = [(task["id"], item["artifactType"], item["artifactUniqueId"])
                for task in actual["tasks"] for item in task["items"]]
    expected = [(row["task_id"], row["artifactType"], row["artifactUniqueId"]) for row in bindings]
    if (set(assigned) != set(expected) or len(assigned) != len(items)
            or len(actual["tasks"]) != len(tasks) or len(actual["edges"]) != len(edges)):
        raise Gate("Native Task Flow failed exact persisted assignment/graph readback.")
    (directory / f"native-readback-{stamp}.json").write_text(
        json.dumps(current, indent=2) + "\n", encoding="utf-8")
    return {
        "persisted": True, "flow_id": flow_id, "resource_id": current["resourceId"],
        "etag": current["etag"], "task_count": len(tasks), "connector_count": len(edges),
        "assignment_count": len(assigned), "tasks": actual["tasks"], "route": base,
    }


def run(args):
    client = Client(args.tenant, args.subscription)
    base = f"/v1/workspaces/{args.workspace}"
    workspace = client.request("GET", base)
    if workspace.get("displayName") != "MSFlix":
        raise Gate("The supplied workspace is not MSFlix.")
    capacities = client.list("/v1/capacities")
    capacity = next((c for c in capacities if c["id"] == workspace.get("capacityId")), None)
    if not capacity or (
        capacity["displayName"] != args.capacity_name
        or capacity.get("sku") != "F16" or capacity.get("state") != "Active"
        or re.sub(r"[^a-z]", "", capacity.get("region", "").lower()) != "southeastasia"
    ):
        raise Gate("MSFlix is not on the supplied active Southeast Asia F16.")
    items = client.list(base + "/items")
    mapping(items)  # Qualify the complete scope before any write.
    folders = client.list(base + "/folders")
    before = {item["id"]: dict(item) for item in items}
    operations = organize(client, base, items, folders, args.include_native_groups) if args.organize_folders else []
    if operations:
        after = {i["id"]: i for i in client.list(base + "/items")}
        for item in before.values():
            current = after.get(item["id"])
            if not current or (current["displayName"], current["type"]) != (
                item["displayName"], item["type"]
            ):
                raise Gate("An existing item disappeared or changed identity during readback.")
            if not args.include_native_groups and role(item) in ("crm", "cockpit") and (
                current.get("folderId") != item.get("folderId")
            ):
                raise Gate("A protected native BPS or app placement changed.")
        for operation in operations:
            for item_id in operation.get("moved_item_ids", []):
                if after[item_id].get("folderId") != operation["folder_id"]:
                    raise Gate("Folder placement failed its live readback.")
        items = list(after.values())
        folders = client.list(base + "/folders")
    mapped = mapping(items)
    tasks, edges = task_graph(mapped)
    report = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "workspace": {k: workspace.get(k) for k in ("id", "displayName", "description", "capacityId")},
        "capacity": {k: capacity.get(k) for k in ("id", "displayName", "sku", "region", "state")},
        "task_flow": {"persisted": None, "state": "Not queried in inventory-only mode"},
        "tasks": [{"key": k, "name": n, "recommended_type": t} for k, n, t in tasks],
        "logical_connectors": [{"from": a, "to": b, "meaning": c} for a, b, c in edges],
        "items": mapped, "folders": folders, "folder_operations": operations,
    }
    if args.require_taskflow or args.deploy_taskflow:
        report["task_flow"] = native_taskflow(args, report["items"])
    if args.evidence:
        path = args.evidence.resolve()
        if not path.is_relative_to(ROOT / ".state") or path.suffix != ".json":
            raise Gate("Evidence must be an ignored JSON file under this repository's .state.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 2 if args.require_taskflow and not report["task_flow"]["persisted"] else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True, type=guid)
    parser.add_argument("--subscription", required=True, type=guid)
    parser.add_argument("--workspace", required=True, type=guid)
    parser.add_argument("--capacity-name", required=True)
    parser.add_argument("--organize-folders", action="store_true")
    parser.add_argument("--include-native-groups", action="store_true",
                        help="Explicit approval to organize native BPS/cockpit parents too.")
    parser.add_argument("--require-taskflow", action="store_true",
                        help="Read back the native graph; exit 2 unless graph and all assignments exist.")
    parser.add_argument("--deploy-taskflow", action="store_true",
                        help="Idempotently save the native graph/assignments with backup and ETag.")
    parser.add_argument("--bps-portal-item-id", type=guid,
                        help="Observed native Microsoft.WaaS object ID when creating the first graph.")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    try:
        return run(args)
    except Gate as error:
        print(json.dumps({"completed": False, "gate": str(error)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
