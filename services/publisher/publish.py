"""Publish persisted MSFlix outbox rows with broker-ACK-controlled delivery state."""

from __future__ import annotations

import argparse
import json
import re
import struct
import time
from datetime import datetime, timezone
from typing import Any


def canonical_payload(value: str | dict[str, Any]) -> tuple[dict[str, Any], str]:
    payload = json.loads(value) if isinstance(value, str) else value
    if not isinstance(payload, dict):
        raise ValueError("Outbox payload must be a JSON object.")
    return payload, json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def utc_text(value: datetime | str) -> str:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def envelope(row: dict[str, Any]) -> dict[str, Any]:
    payload, payload_json = canonical_payload(row["payload"])
    if row.get("payload_json") is not None and json.loads(row["payload_json"]) != payload:
        raise ValueError("Persisted payload_json differs from the actual outbox payload.")
    if row.get("schema_version", 1) != 1:
        raise ValueError("Unsupported outbox schema_version.")
    sequence = row["source_sequence"]
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        raise ValueError("Persisted source_sequence must be a positive integer.")
    for field in ("event_id", "event_type", "entity_key", "run_id"):
        if not row.get(field):
            raise ValueError(f"Outbox row is missing {field}.")
    return {
        "event_id": str(row["event_id"]),
        "event_type": row["event_type"],
        "schema_version": row.get("schema_version", 1),
        "entity_key": row["entity_key"],
        "source_sequence": sequence,
        "occurred_at": utc_text(row["occurred_at"]),
        "produced_at": utc_text(row["produced_at"]) if row.get("produced_at") else datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "run_id": str(row["run_id"]),
        "correlation_id": str(row.get("correlation_id") or row["event_id"]),
        "payload": payload,
        "payload_json": payload_json,
    }


def publish_batch(rows, producer, topic, cursor, database, clock=time.monotonic):
    bodies = [envelope(row) for row in rows]
    if len({body["event_id"] for body in bodies}) != len(bodies):
        raise ValueError("Duplicate event_id in the persisted outbox batch.")
    delivered: dict[str, str | None] = {}
    for body in bodies:
        def on_delivery(error: Any, _message: Any, event_id=body["event_id"]) -> None:
            delivered[event_id] = str(error) if error is not None else None

        producer.produce(
            topic, key=body["entity_key"],
            value=json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
            on_delivery=on_delivery,
        )
    acknowledgement_deadline = clock() + 65
    while len(delivered) < len(bodies) and clock() < acknowledgement_deadline:
        producer.poll(0.2)
    if len(delivered) != len(bodies) or any(error is not None for error in delivered.values()):
        database.rollback()
        raise RuntimeError("Kafka batch acknowledgement failed; SQL delivery state unchanged, acknowledged events may replay.")
    placeholders = ",".join("?" for _ in rows)
    cursor.execute(
        "UPDATE dbo.Outboxes SET published_at=SYSUTCDATETIME() "
        f"WHERE published_at IS NULL AND event_id IN ({placeholders});",
        *(row["event_id"] for row in rows),
    )
    if cursor.rowcount != len(rows):
        database.rollback()
        raise RuntimeError("Outbox batch changed after broker ACK; events may replay, not silently discarded.")
    database.commit()
    return len(rows)


def run(args: argparse.Namespace) -> dict[str, Any]:
    import pyodbc
    from azure.identity import AzureCliCredential
    from confluent_kafka import Producer

    if not re.fullmatch(r"[A-Za-z0-9.-]+", args.server):
        raise ValueError("Invalid SQL server hostname.")
    if not re.fullmatch(r"[A-Za-z0-9 _.-]+", args.database):
        raise ValueError("Invalid operational database name.")
    if not re.fullmatch(r"[A-Za-z0-9-]+", args.namespace):
        raise ValueError("Invalid Event Hubs namespace.")
    if args.duration < 1 or args.duration > 600 or args.max_messages < 1 or args.max_messages > 20000:
        raise ValueError("Publisher duration/messages must be explicitly bounded.")
    if args.batch_size < 1 or args.batch_size > 512:
        raise ValueError("Publisher batch size must be between 1 and 512.")
    credential = AzureCliCredential(tenant_id=args.tenant)
    sql_token = credential.get_token("https://database.windows.net/.default").token.encode("utf-16-le")
    token_bytes = struct.pack("<I", len(sql_token)) + sql_token
    connection_string = (
        f"Driver={{ODBC Driver 18 for SQL Server}};Server=tcp:{args.server},1433;"
        f"Database={args.database};Encrypt=yes;TrustServerCertificate=no;"
    )

    def oauth(_: str) -> tuple[str, float]:
        token = credential.get_token(f"https://{args.namespace}.servicebus.windows.net/.default")
        return token.token, float(token.expires_on)

    producer = Producer({
        "bootstrap.servers": f"{args.namespace}.servicebus.windows.net:9093",
        "security.protocol": "SASL_SSL",
        "sasl.mechanism": "OAUTHBEARER",
        "oauth_cb": oauth,
        "client.id": "msflix-outbox-publisher",
        "compression.type": "none",
        "acks": "all",
        "message.timeout.ms": 60000,
    })
    sent = 0
    batches = 0
    started = time.monotonic()
    deadline = started + args.duration
    with pyodbc.connect(connection_string, attrs_before={1256: token_bytes}, autocommit=False) as database:
        cursor = database.cursor()
        cursor.execute(
            "DECLARE @result int; EXEC @result = sys.sp_getapplock "
            "@Resource=N'MSFlix-OutboxPublisher',@LockMode=N'Exclusive',"
            "@LockOwner=N'Session',@LockTimeout=0; SELECT @result;"
        )
        while cursor.description is None:
            if not cursor.nextset():
                raise RuntimeError("SQL publisher lock did not return a result.")
        lock_result = cursor.fetchone()[0]
        if lock_result < 0:
            raise RuntimeError("Another MSFlix publisher owns the operational outbox.")
        database.commit()
        while time.monotonic() < deadline and sent < args.max_messages:
            cursor.execute(
                "SELECT TOP (?) event_id,event_type,schema_version,entity_key,source_sequence,"
                "occurred_at,produced_at,run_id,correlation_id,payload,payload_json "
                "FROM dbo.Outboxes WHERE published_at IS NULL ORDER BY occurred_at,event_id;",
                min(args.batch_size, args.max_messages - sent),
            )
            records = cursor.fetchall()
            if not records:
                database.commit()
                producer.poll(0)
                time.sleep(1)
                continue
            columns = [column[0] for column in cursor.description]
            rows = [dict(zip(columns, record)) for record in records]
            sent += publish_batch(rows, producer, args.topic, cursor, database)
            batches += 1
        remaining = producer.flush(65)
        if remaining:
            raise RuntimeError(f"Publisher stopped with {remaining} unacknowledged messages.")
    return {"broker_acknowledged": sent, "committed_batches": batches,
            "duration_seconds": round(time.monotonic() - started, 2)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--server", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--topic", default="msflix-events")
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--max-messages", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=128)
    args = parser.parse_args()
    print(json.dumps(run(args), separators=(",", ":")))


if __name__ == "__main__":
    main()
