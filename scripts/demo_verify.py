"""Read-only exact-ID acceptance proof for an existing persisted Demo journey."""
from __future__ import annotations

import argparse
import json
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from azure.identity import AzureCliCredential

from fabric.rest import DeploymentError
from fabric.sql import execute
from services.publisher.runtime import Runtime, latest_targets


def verify(cfg, target, vm):
    events = target["events"]
    ids = sorted(row["event_id"] for row in events)
    runtime = Runtime(cfg, AzureCliCredential(tenant_id=cfg["tenant_id"]))
    placeholders = ",".join("?" for _ in ids)
    with closing(runtime.operational()) as connection:
        outbox = execute(connection,
            "SELECT event_id,event_type,entity_key,source_sequence,published_at FROM dbo.Outboxes "
            f"WHERE event_id IN ({placeholders}) ORDER BY source_sequence;", ids)
        pending = execute(connection, "SELECT COUNT(*) AS pending FROM dbo.Outboxes WHERE published_at IS NULL;")
    acknowledged = {}
    for receipt in vm["broker_receipts"]:
        if receipt["sql_committed"]:
            acknowledged.update(receipt.get("broker_receipts", {}))
    if (len(outbox) != len(ids) or any(row["published_at"] is None for row in outbox)
            or not set(ids).issubset(acknowledged)):
        raise DeploymentError("Exact Kafka ACK/SQL commit evidence incomplete")
    native = runtime.exact_ids("native", ids)
    raw = runtime.delta_rows(cfg["items"]["raw"]["id"], "raw/events_ingress",
                             ["event_id", "event_type", "entity_key", "source_sequence", "payload"],
                             ("event_id", ids))
    if not native["complete"] or sorted(row["event_id"] for row in raw) != ids:
        raise DeploymentError("Exact native OneLake/Raw event evidence incomplete")
    orders = sorted({row["order_id"] for row in events if row.get("order_id")})
    sessions = sorted({row["session_id"] for row in events if row.get("session_id")})
    if len(orders) != 1 or len(sessions) != 1:
        raise DeploymentError("Acceptance is bounded to one existing order and playback")
    with closing(runtime.analytics("gold")) as connection:
        order = execute(connection,
            "SELECT order_id,customer_key,offer_key,content_key,status,amount_minor,currency,"
            "first_play_at,expires_at,source_sequence,event_id FROM gold.fact_order_line WHERE order_id=?;",
            orders)
        playback = execute(connection,
            "SELECT session_id,order_id,position_seconds,status,source_sequence,event_id "
            "FROM gold.fact_playback_session WHERE session_id=?;", sessions)
        publication = execute(connection, "SELECT run_id,completed_at,order_lines FROM gold.publication;")
    if len(order) != 1 or len(playback) != 1:
        raise DeploymentError("Actual Gold order/playback missing or duplicated")
    targets = latest_targets(events, cfg)
    latest = {row["entity_key"]: row for row in sorted(events, key=lambda row: row["source_sequence"])}
    for row, key in ((order[0], orders[0]), (playback[0], sessions[0])):
        if row["event_id"] != latest[key]["event_id"] or row["source_sequence"] != latest[key]["source_sequence"]:
            raise DeploymentError("Gold does not contain the exact latest accepted event state")
    graph = runtime.verify_graph(targets)
    if graph is None:
        raise DeploymentError("Refreshed graph does not match the accepted Gold state")
    graph_playback = runtime.graph_rows(
        f"MATCH (p:playback) WHERE p.session_id='{sessions[0]}' "
        "RETURN p.session_id AS session_id,p.order_id AS order_id,"
        "p.position_seconds AS position_seconds,p.status AS status LIMIT 2")
    cycle = vm["status"].get("last_cycle")
    if not cycle or vm["status"]["phase"] != "idle" or vm["paused_file"]:
        raise DeploymentError("Deployed worker has not committed its successful propagation checkpoint")
    if vm["status"].get("idle_checked_at", 0) <= cycle["completed_at"]:
        raise DeploymentError("A real subsequent idle cycle has not yet been observed")
    if vm["service"]["ActiveState"] != "active" or vm["service"]["UnitFileState"] != "enabled":
        raise DeploymentError("Persistent service is not active and enabled")
    return {
        "state": "accepted", "verified_at": datetime.now(timezone.utc).isoformat(),
        "new_orders_created_by_verification": 0, "event_ids": ids,
        "broker_acknowledgements": {key: acknowledged[key] for key in ids},
        "operational_outbox": outbox, "remaining_unpublished": pending[0]["pending"],
        "native_onelake": native, "raw_events": raw,
        "gold_order": order[0], "gold_playback": playback[0], "gold_publication": publication[0],
        "graph": graph, "graph_playback": graph_playback,
        "worker_cycle": cycle, "subsequent_idle_checked_at": vm["status"]["idle_checked_at"],
        "propagated_checkpoint_count": vm["propagated_count"], "service": vm["service"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--vm-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(
        json.loads(args.config.read_text(encoding="utf-8")),
        json.loads(args.target.read_text(encoding="utf-8")),
        json.loads(args.vm_evidence.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, default=str))


if __name__ == "__main__":
    main()
