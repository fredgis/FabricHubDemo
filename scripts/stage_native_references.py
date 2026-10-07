"""Stage canonical references from the live Oracle mirror and native BPS tables."""
import json
from datetime import datetime, timezone
from pathlib import Path

from fabric.contracts import validate_record
from fabric.deploy import preflight, resolve, validate_config
from fabric.rest import DeploymentError, FabricClient
from fabric.sql import connect, execute
from fabric.staging import OneLake, conform_salesforce

ROOT = Path(__file__).resolve().parents[1]
ORACLE_QUERIES = {
    "content": """
        IF EXISTS (SELECT CONTENT_ID FROM DEMO_DW.REF_PRICE_RULE
                   GROUP BY CONTENT_ID HAVING COUNT(DISTINCT DISTRIBUTOR_ID)>1)
            THROW 51020, 'Multiple source distributors require an explicit rights model', 1;
        SELECT c.CONTENT_KEY AS content_key,c.TITLE AS title,
            CONVERT(varchar(10),c.RELEASE_DATE,23) AS release_date,
            c.DURATION_SECONDS AS duration_seconds,c.GENRE AS genre,c.IMAGE_URL AS image_url,
            c.SOURCE_URL AS source_url,c.LICENSE AS license,c.ATTRIBUTION AS attribution,
            d.DISTRIBUTOR_KEY AS distributor_key
        FROM DEMO_DW.REF_CONTENT c
        LEFT JOIN (SELECT CONTENT_ID,MAX(DISTRIBUTOR_ID) AS DISTRIBUTOR_ID
                   FROM DEMO_DW.REF_PRICE_RULE GROUP BY CONTENT_ID) p ON p.CONTENT_ID=c.CONTENT_ID
        LEFT JOIN DEMO_DW.REF_DISTRIBUTOR d ON d.DISTRIBUTOR_ID=p.DISTRIBUTOR_ID""",
    "offer": """
        SELECT p.PRICE_RULE_KEY AS offer_key,c.CONTENT_KEY AS content_key,
            t.TERRITORY_CODE AS territory,p.CURRENCY_CODE AS currency,
            CASE o.OFFER_TYPE WHEN 'RENTAL' THEN 'TVOD' WHEN 'PURCHASE' THEN 'EST' END AS transaction_type,
            p.AMOUNT_MINOR AS price_minor,o.START_WINDOW_HOURS AS start_window_hours,
            o.PLAY_WINDOW_HOURS AS play_window_hours
        FROM DEMO_DW.REF_PRICE_RULE p
        JOIN DEMO_DW.REF_CONTENT c ON c.CONTENT_ID=p.CONTENT_ID
        JOIN DEMO_DW.REF_OFFER o ON o.OFFER_ID=p.OFFER_ID
        JOIN DEMO_DW.REF_TERRITORY t ON t.TERRITORY_ID=p.TERRITORY_ID""",
    "distributor": """
        SELECT DISTRIBUTOR_KEY AS distributor_key,DISTRIBUTOR_NAME AS name
        FROM DEMO_DW.REF_DISTRIBUTOR""",
}


def main():
    config_path = ROOT / "fabric" / "config.live.local.json"
    cfg = validate_config(json.loads(config_path.read_text()), "check")
    client = FabricClient(cfg["tenant_id"])
    workspace = preflight(cfg, client)
    ws = workspace["id"]
    raw = resolve(cfg, client, ws, "raw")
    mirrors = [item for item in client.list(f"/v1/workspaces/{ws}/mirroredDatabases", "sqldw-cli")
               if item["displayName"] == "MSFlix_OracleMirror"]
    if len(mirrors) != 1:
        raise DeploymentError("The dedicated live Oracle mirror is missing or ambiguous")
    mirror = client.request("GET", f"/v1/workspaces/{ws}/mirroredDatabases/{mirrors[0]['id']}",
                            skill="sqldw-cli")[2]
    bps_items = [item for item in client.list(f"/v1/workspaces/{ws}/lakehouses", "sqldw-cli")
                 if item["displayName"] == "bps_bronze_8fbe0076"]
    if len(bps_items) != 1:
        raise DeploymentError("The native BPS Salesforce Bronze Lakehouse is missing or ambiguous")
    bps = client.request("GET", f"/v1/workspaces/{ws}/lakehouses/{bps_items[0]['id']}",
                         skill="sqldw-cli")[2]
    rows = {}
    with connect(cfg, mirror, lakehouse=True) as database:
        for entity, query in ORACLE_QUERIES.items():
            rows[entity] = [validate_record(entity, row) for row in execute(database, query)]
    with connect(cfg, bps, lakehouse=True) as database:
        customers = execute(database, """
            SELECT Id,FirstName,LastName,MSFlix_Key__c,MSFlix_Territory__c
            FROM [MSFlixSF].[Contact] WHERE MSFlix_Key__c LIKE 'MSF-C%' AND IsDeleted=0""")
        rows["customer"] = conform_salesforce("customer", customers)
    actual = {entity: len(values) for entity, values in rows.items()}
    if any(count == 0 for count in actual.values()):
        raise DeploymentError(f"An expected native reference source is empty; refusing mass replacement: {actual}")
    lake = OneLake(cfg, workspace, raw)
    lineage = {}
    for entity, values in rows.items():
        source_kind = "BPS" if entity == "customer" else "OracleMirror"
        source_id = bps["id"] if entity == "customer" else mirror["id"]
        path = f"Files/ingress/native/{source_kind}/{entity}.json"
        lake.put(path, (json.dumps(values, ensure_ascii=False, indent=2) + "\n").encode())
        cfg["sources"][entity] = {
            "path": path, "format": "json", "multiline": True, "snapshot_complete": True,
            "source_kind": source_kind, "source_item_id": source_id,
        }
        lineage[entity] = {"source_kind": source_kind, "source_item_id": source_id, "rows": len(values)}
    cfg["master_reference_entities"] = sorted(rows)
    cfg["run_id"] = "msflix-native-masters-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    validate_config(cfg, "process")
    config_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    evidence = {"run_id": cfg["run_id"], "lineage": lineage,
                "remaining_bootstrap_entities": sorted(set(cfg["sources"]) - set(rows))}
    (ROOT / ".state" / "native-reference-staging.json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
