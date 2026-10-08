"""Configure and publish native Flixy through the official Data Agent public API."""

import json
from urllib.parse import quote

from fabric.rest import DeploymentError, FabricClient
from scripts.prepare_flixy import CAPACITY, ROOT, SKILL, TENANT, WAREHOUSE, WORKSPACE

ONTOLOGY = "3534d696-e727-45b3-9387-bbd155a82a52"
GRAPH = "1f368a35-95da-42a2-924d-ef4bb6bc9413"
QUESTIONS = (
    ("Combien de films, clients et commandes sont publies dans Gold ?",
     "SELECT (SELECT COUNT_BIG(*) FROM gold.dim_content) AS films, "
     "(SELECT COUNT_BIG(*) FROM gold.dim_customer) AS customers, "
     "(SELECT COUNT_BIG(DISTINCT order_id) FROM gold.fact_order_line) AS orders, "
     "(SELECT MAX(completed_at) FROM gold.publication) AS published_at;"),
    ("Quelle est l'activite commerciale par devise et type d'offre ?",
     "SELECT o.currency, o.transaction_type, COUNT_BIG(DISTINCT o.order_id) AS orders, "
     "SUM(o.amount_decimal) AS booked_amount FROM gold.fact_order_line AS o "
     "WHERE o.transaction_type IN ('TVOD','EST') AND EXISTS "
     "(SELECT 1 FROM gold.commercial_status AS s WHERE s.status=o.status) "
     "GROUP BY o.currency, o.transaction_type ORDER BY o.currency, o.transaction_type;"),
    ("Quelles campagnes ont des conversions explicitement enregistrees ?",
     "SELECT c.campaign_key, c.name, COUNT_BIG(x.conversion_key) AS recorded_conversions "
     "FROM gold.dim_campaign AS c LEFT JOIN gold.fact_campaign_conversion AS x "
     "ON x.campaign_key=c.campaign_key GROUP BY c.campaign_key,c.name ORDER BY c.campaign_key;"),
    ("Combien de commandes distinctes sont presentes dans la derniere publication ?",
     "SELECT COUNT_BIG(DISTINCT order_id) AS orders, "
     "(SELECT MAX(completed_at) FROM gold.publication) AS published_at "
     "FROM gold.fact_order_line;"),
)
TABLE_DESCRIPTIONS = {
    "fact_order_line": "Complete current published order-line snapshot. Count DISTINCT order_id for orders. "
    "run_id is original EVENT producer provenance, NOT the refresh run ID. Never join/filter it "
    "against gold.publication.run_id; that incorrectly returns zero. Use created_at for business periods.",
    "fact_playback_session": "Complete current published playback snapshot. run_id is original EVENT producer "
    "provenance, NOT gold.publication.run_id. Do not join/filter on publication.run_id.",
    "publication": "Refresh marker only, not a dimension or source of batch filters. Its run_id is the analytics "
    "refresh run, unlike fact run_id which identifies the original event producer. Read MAX(completed_at) "
    "separately for freshness; current facts already contain the entire published snapshot.",
}


def item_reference(item_id):
    return {"type": "FabricItem", "itemReference": {
        "referenceType": "ById", "itemId": item_id, "workspaceId": WORKSPACE,
    }}


def main():
    client = FabricClient(TENANT)
    workspace_path = f"/v1/workspaces/{WORKSPACE}"
    workspace = client.request("GET", workspace_path, skill=SKILL)[2]
    if workspace.get("displayName") != "MSFlix" or workspace.get("capacityId") != CAPACITY:
        raise DeploymentError("Unapproved Flixy workspace/capacity")
    switches = client.request("GET", "/v1/admin/tenantsettings", skill=SKILL)[2]["tenantSettings"]
    required = {"EnableAOAI", "AllowSendAOAIDataToOtherRegions", "AllowStoreAOAIDataInOtherRegions"}
    if {s["settingName"] for s in switches if s.get("enabled") and s["settingName"] in required} != required:
        raise DeploymentError("Required AI policy is not enabled; this script never changes tenant settings")
    agents = [x for x in client.list(workspace_path + "/dataAgents", SKILL) if x["displayName"] == "Flixy"]
    if len(agents) != 1:
        raise DeploymentError("Create the single native Flixy draft first")
    agent = agents[0]
    base = workspace_path + "/dataAgents/" + agent["id"]
    sources_path = base + "/staging/datasources"
    sources = client.list(sources_path, SKILL)
    allowed = {WAREHOUSE, GRAPH}
    if any(s.get("itemReference", {}).get("itemId") not in allowed
           or s.get("itemReference", {}).get("workspaceId") != WORKSPACE for s in sources):
        raise DeploymentError("Unexpected source attached to Flixy; no source was removed")
    for source_id in (WAREHOUSE, GRAPH):
        if not any(s.get("itemReference", {}).get("itemId") == source_id for s in sources):
            client.operation("POST", sources_path, item_reference(source_id), SKILL)
    elements_path = sources_path + "/" + WAREHOUSE + "/elements"
    roots = client.list(elements_path, SKILL)
    # Replace only the initial unpublished draft's unavailable, hand-authored root.
    if any(r["id"] == "Z29sZA==" and r.get("state") == "NotAvailable" for r in roots):
        definition = client.operation("POST", base + "/getDefinition", {}, SKILL, result_required=True)
        if any("/published/" in p["path"].lower() for p in definition["definition"]["parts"]):
            raise DeploymentError("Refusing source replacement in an already-published agent")
        client.request("DELETE", sources_path + "/" + WAREHOUSE, skill=SKILL)
        client.operation("POST", sources_path, item_reference(WAREHOUSE), SKILL)
        roots = client.list(elements_path, SKILL)
    containers = [r for r in roots if r["displayName"] == "Schemas" and r["state"] == "Available"]
    if len(containers) != 1:
        raise DeploymentError("The native Warehouse schema container is not available")
    schemas = client.list(elements_path + "?rootId=" + quote(containers[0]["id"], safe=""), SKILL)
    gold = [s for s in schemas if s["displayName"] == "gold" and s["state"] == "Available"]
    if len(gold) != 1:
        raise DeploymentError("The actual gold schema is not available to Flixy")
    groups = client.list(elements_path + "?rootId=" + quote(gold[0]["id"], safe=""), SKILL)
    selected_tables = []
    for group in groups:
        if group.get("type") not in ("Tables", "Views") or group.get("state") != "Available":
            continue
        tables = client.list(elements_path + "?rootId=" + quote(group["id"], safe=""), SKILL)
        for table in tables:
            if table.get("type") not in ("Table", "View") or table.get("state") != "Available":
                raise DeploymentError("A Gold table/view is unavailable; no partial selection published")
            overrides = {}
            if not table.get("isSelected"):
                overrides["isSelected"] = True
            description = TABLE_DESCRIPTIONS.get(table["displayName"])
            if description and table.get("description") != description:
                overrides["description"] = description
            if overrides:
                client.request("PATCH", elements_path + "?id=" + quote(table["id"], safe=""),
                               overrides, SKILL)
            selected_tables.append(table["displayName"])
    if not {"fact_order_line", "dim_content", "dim_customer", "publication"}.issubset(selected_tables):
        raise DeploymentError("Required native Gold tables were not selected")
    settings = client.request("GET", base + "/staging/settings", skill=SKILL)[2]
    experimental = {**(settings.get("experimental") or {}), "enableExperimentalFeatures": True}
    client.request("PATCH", base + "/staging/settings", {
        "aiInstructions": (ROOT / "agents" / "flixy" / "instructions.md").read_text(encoding="utf-8"),
        "experimental": experimental,
    }, SKILL)
    client.request("PATCH", sources_path + "/" + WAREHOUSE, {
        "description": "MSFlix consolidated Gold: catalogue, CRM, commercial activity, playback and marketing.",
        "instructions": "Use only the selected gold schema. Preserve fact grain and stable keys. "
        "Use gold.commercial_status for booked sales, separate currencies and exact stored amounts. "
        "Use gold.publication only for freshness. All facts already are the complete current snapshot. "
        "Fact run_id is ORIGINAL EVENT provenance, never the analytics publication run ID: do not join or "
        "filter fact.run_id by gold.publication.run_id. Count current published orders without a run_id filter. "
        "Conversions require recorded facts, not inferred causality.",
    }, SKILL)
    client.request("PATCH", sources_path + "/" + GRAPH, {
        "description": "The real native GraphModel generated by MSFlixBusiness Ontology v2, backed by Gold.",
        "instructions": "This is Ontology via its native graph, not a direct ontology-context connection. "
        "Use GQL for actual relationships. The order entity is rental (TVOD and EST). "
        "Paths include customer - customer_order -> rental - order_offer -> offer - offer_content -> content. "
        "Never invent graph instances, counts or transaction actions. Prefer Gold for financial aggregates.",
    }, SKILL)
    examples_path = sources_path + "/" + WAREHOUSE + "/fewshots"
    examples = client.list(examples_path, SKILL)
    for question, query in QUESTIONS:
        matches = [row for row in examples if row["question"] == question]
        if len(matches) > 1:
            raise DeploymentError("Duplicate managed Flixy example question")
        body = {"question": question, "query": query}
        if matches:
            client.request("PATCH", examples_path + "/" + matches[0]["id"], body, SKILL)
        else:
            client.request("POST", examples_path, body, SKILL)
    description = "Flixy: read-only MSFlix business assistant using Gold and the ontology's native graph."
    client.request("POST", base + "/staging/publish", {"publishedDescription": description}, SKILL)
    published = client.list(base + "/datasources", SKILL)
    if ({s.get("itemReference", {}).get("itemId") for s in published} != allowed
            or len(published) != 2
            or any(s.get("itemReference", {}).get("workspaceId") != WORKSPACE
                   or s.get("selectionState") == "None" for s in published)):
        raise DeploymentError("Published Flixy source identities do not match Gold and the native graph")
    client.request("PATCH", base, {"description": description}, SKILL)
    evidence = {
        "item_id": agent["id"], "workspace_id": WORKSPACE, "folder_id": agent.get("folderId"),
        "published": True, "warehouse_id": WAREHOUSE, "ontology_id": ONTOLOGY, "graph_id": GRAPH,
        "ontology_mode": "native_graph", "direct_ontology_attachment": "OntologyAddAsDataSourceBlocked",
        "runtime_verified": False, "tenant_policy_changed": False, "sources": published,
        "selected_gold_tables": selected_tables,
    }
    path = ROOT / ".state" / "flixy" / "published.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
