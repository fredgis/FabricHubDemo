"""Qualified Event Hub cloud connections; credentials remain outside configuration."""
import json

from fabric.rest import DeploymentError, az_json


def qualify_eventhub_connection(cfg, connection):
    details = connection.get("connectionDetails", {})
    if details.get("type") != "EventHub":
        raise DeploymentError("Fabric cloud connection is not the tenant's supported EventHub type")
    path = details.get("path", "")
    try:
        parsed = json.loads(path)
    except (json.JSONDecodeError, TypeError):
        parts = path.split(";") if isinstance(path, str) else []
        parsed = {"endpoint": parts[0], "entityPath": parts[1]} if len(parts) == 2 else {}
    if not isinstance(parsed, dict):
        parsed = {}
    namespace = cfg["eventhub_namespace"].lower()
    endpoint = parsed.get("endpoint")
    allowed = {namespace, namespace.split(".")[0],
               "sb://" + namespace, "sb://" + namespace + "/"}
    if (not isinstance(endpoint, str) or endpoint.lower() not in allowed or
            parsed.get("entityPath") != cfg["eventhub_name"]):
        raise DeploymentError("Event Hub connection path does not qualify the real MSFlix namespace/topic")
    return connection


def ensure_workspace_eventhub_connection(cfg, client):
    """Use the workspace identity and a hub-scoped Receiver grant, never SAS secrets."""
    workspace_id = cfg["workspace_id"]
    workspace = client.request("GET", "/v1/workspaces/" + workspace_id)[2]
    identity = workspace.get("workspaceIdentity")
    if not identity:
        identity = client.operation("POST", "/v1/workspaces/" + workspace_id + "/provisionIdentity")
    if not identity or not identity.get("servicePrincipalId"):
        raise DeploymentError("Workspace identity provisioning did not return its actual service principal")
    scope = (cfg["capacity_resource_id"].split("/providers/")[0] +
             "/providers/Microsoft.EventHub/namespaces/" + cfg["eventhub_namespace"].split(".")[0] +
             "/eventhubs/" + cfg["eventhub_name"])
    az_json("role", "assignment", "create", "--subscription", cfg["subscription_id"],
            "--assignee-object-id", identity["servicePrincipalId"],
            "--assignee-principal-type", "ServicePrincipal",
            "--role", "Azure Event Hubs Data Receiver", "--scope", scope)
    name = "MSFlixSeaEventsIdentityName"
    existing = [c for c in client.list("/v1/connections") if c["displayName"] == name]
    if len(existing) > 1:
        raise DeploymentError("Ambiguous workspace-identity Event Hubs connection")
    if existing:
        return qualify_eventhub_connection(
            cfg, client.request("GET", "/v1/connections/" + existing[0]["id"], skill="eventstream-cli")[2])
    body = {
        "connectivityType": "ShareableCloud",
        "displayName": name,
        "connectionDetails": {
            "type": "EventHub",
            "creationMethod": "EventHub.Contents",
            "parameters": [
                {"dataType": "Text", "name": "endpoint",
                 "value": cfg["eventhub_namespace"].split(".")[0]},
                {"dataType": "Text", "name": "entityPath", "value": cfg["eventhub_name"]},
            ],
        },
        "privacyLevel": "Organizational",
        "credentialDetails": {
            "singleSignOnType": "None",
            "connectionEncryption": "NotEncrypted",
            "skipTestConnection": False,
            "credentials": {"credentialType": "WorkspaceIdentity", "workspaceId": workspace_id},
        },
    }
    result = client.operation("POST", "/v1/connections", body, "eventstream-cli")
    return qualify_eventhub_connection(
        cfg, client.request("GET", "/v1/connections/" + result["id"], skill="eventstream-cli")[2])


def ensure_eventhub_connection(cfg, client):
    supported = client.request("GET", "/v1/connections/supportedConnectionTypes?showAllCreationMethods=true",
                               skill="eventstream-cli")[2]["value"]
    contract = next((item for item in supported if item["type"] == "EventHub"), None)
    if not contract or "Basic" not in contract.get("supportedCredentialTypes", []):
        raise DeploymentError("Tenant does not expose the supported EventHub Basic connection contract")
    methods = [m for m in contract["creationMethods"]
               if {p["name"] for p in m["parameters"]} == {"endpoint", "entityPath"}]
    if len(methods) != 1:
        raise DeploymentError("EventHub connection creation contract is ambiguous")
    name = "MSFlixSeaEventsListen"
    matches = [r for r in client.list("/v1/connections", "eventstream-cli") if r["displayName"] == name]
    if len(matches) > 1:
        raise DeploymentError("Ambiguous MSFlix cloud connection")
    if matches:
        item = client.request("GET", "/v1/connections/" + matches[0]["id"], skill="eventstream-cli")[2]
        return qualify_eventhub_connection(cfg, item)
    namespace = cfg["eventhub_namespace"].split(".")[0]
    resource_group = cfg["capacity_resource_id"].split("/")[4]
    base = ["--subscription", cfg["subscription_id"], "--resource-group", resource_group,
            "--namespace-name", namespace, "--eventhub-name", cfg["eventhub_name"]]
    rules = az_json("eventhubs", "eventhub", "authorization-rule", "list", *base)
    rule = next((r for r in rules if r["name"] == "fabric-listen"), None)
    if not rule:
        rule = az_json("eventhubs", "eventhub", "authorization-rule", "create",
                       *base, "--name", "fabric-listen", "--rights", "Listen")
    if set(rule.get("rights", [])) != {"Listen"}:
        raise DeploymentError("fabric-listen must be Event-Hub-scoped Listen-only; refusing broader credentials")
    keys = az_json("eventhubs", "eventhub", "authorization-rule", "keys", "list",
                   *base, "--name", "fabric-listen")
    try:
        payload = {
            "connectivityType": "ShareableCloud", "displayName": name,
            "connectionDetails": {
                "type": contract["type"], "creationMethod": methods[0]["name"],
                "parameters": [
                    {"dataType": "Text", "name": "endpoint", "value": cfg["eventhub_namespace"].split(".")[0]},
                    {"dataType": "Text", "name": "entityPath", "value": cfg["eventhub_name"]}]},
            "privacyLevel": "Organizational", "allowUsageInUserControlledCode": False,
            "credentialDetails": {
                "singleSignOnType": "None", "connectionEncryption": "NotEncrypted",
                "skipTestConnection": False,
                "credentials": {"credentialType": "Basic", "username": "fabric-listen",
                                "password": keys["primaryKey"]}}
        }
        result = client.operation("POST", "/v1/connections", payload, "eventstream-cli")
        # Never return, print, log, or persist credential-bearing request material.
        return client.request("GET", "/v1/connections/" + result["id"], skill="eventstream-cli")[2]
    finally:
        keys.clear()
        if "payload" in locals():
            payload["credentialDetails"]["credentials"]["password"] = ""
