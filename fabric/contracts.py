"""Shared, executable contracts. No source connection or environment IDs live here."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal

# Fields are strings unless specified otherwise. Optional means genuinely absent,
# not an invitation to manufacture a distributor, campaign, payment or invoice.
ENTITIES = {
    "content": {"key": "content_key", "fields": {
        "content_key": "string", "title": "string", "release_date": "date",
        "duration_seconds": "long", "genre": "string", "image_url": "string",
        "source_url": "string", "license": "string", "attribution": "string",
        "distributor_key": "string"}, "required": [
            "content_key", "title", "release_date", "duration_seconds", "genre",
            "image_url", "source_url", "license", "attribution"]},
    "customer": {"key": "customer_key", "fields": {
        "customer_key": "string", "name": "string", "territory": "string",
        "source_customer_id": "string"}, "required": [
            "customer_key", "name", "territory"]},
    "offer": {"key": "offer_key", "fields": {
        "offer_key": "string", "content_key": "string", "territory": "string",
        "currency": "string", "transaction_type": "string", "price_minor": "long",
        "start_window_hours": "long", "play_window_hours": "long"},
        "required": ["offer_key", "content_key", "territory", "currency",
                     "transaction_type", "price_minor"]},
    "rental": {"key": "order_id", "fields": {
        "order_id": "string", "customer_key": "string", "offer_key": "string",
        "status": "string", "amount_minor": "long", "currency": "string",
        "created_at": "timestamp", "start_deadline": "timestamp",
        "first_play_at": "timestamp", "expires_at": "timestamp",
        "campaign_key": "string"}, "required": [
            "order_id", "customer_key", "offer_key", "status", "amount_minor",
            "currency", "created_at"]},
    "playback": {"key": "session_id", "fields": {
        "session_id": "string", "order_id": "string", "content_key": "string",
        "customer_key": "string", "position_seconds": "long", "status": "string"},
        "required": ["session_id", "order_id", "content_key", "customer_key",
                     "position_seconds", "status"]},
    "distributor": {"key": "distributor_key", "fields": {
        "distributor_key": "string", "name": "string"},
        "required": ["distributor_key", "name"]},
    "campaign": {"key": "campaign_key", "fields": {
        "campaign_key": "string", "name": "string", "territory": "string",
        "budget_minor": "long", "currency": "string", "channel": "string",
        "source_campaign_id": "string"},
        "required": ["campaign_key", "name"]},
    "consent": {"key": "consent_key", "fields": {
        "consent_key": "string", "customer_key": "string", "purpose": "string",
        "channel": "string", "granted": "boolean", "effective_at": "timestamp",
        "source_consent_id": "string"}, "required": [
            "consent_key", "customer_key", "purpose", "channel", "granted", "effective_at"]},
    "touch": {"key": "touch_key", "fields": {
        "touch_key": "string", "customer_key": "string", "campaign_key": "string",
        "channel": "string", "touch_type": "string", "occurred_at": "timestamp",
        "tracking_token": "string", "source_touch_id": "string"}, "required": [
            "touch_key", "customer_key", "campaign_key", "channel", "touch_type", "occurred_at"]},
    "campaign_conversion": {"key": "conversion_key", "fields": {
        "conversion_key": "string", "campaign_key": "string",
        "customer_key": "string", "order_id": "string",
        "converted_at": "timestamp"},
        "required": ["conversion_key", "campaign_key", "customer_key",
                     "order_id", "converted_at"]},
}

LINKS = {
    "customer_order": ("customer", "customer_key", "rental", "order_id", "rental"),
    "order_offer": ("rental", "order_id", "offer", "offer_key", "rental"),
    "offer_content": ("offer", "offer_key", "content", "content_key", "offer"),
    "playback_order": ("playback", "session_id", "rental", "order_id", "playback"),
    "playback_content": ("playback", "session_id", "content", "content_key", "playback"),
    "playback_customer": ("playback", "session_id", "customer", "customer_key", "playback"),
    "content_distributor": ("content", "content_key", "distributor", "distributor_key", "content"),
    "conversion_campaign": ("campaign_conversion", "conversion_key", "campaign", "campaign_key", "campaign_conversion"),
    "conversion_order": ("campaign_conversion", "conversion_key", "rental", "order_id", "campaign_conversion"),
    "consent_customer": ("consent", "consent_key", "customer", "customer_key", "consent"),
    "touch_customer": ("touch", "touch_key", "customer", "customer_key", "touch"),
    "touch_campaign": ("touch", "touch_key", "campaign", "campaign_key", "touch"),
}

GOLD_TABLES = {
    "content": "dim_content", "customer": "dim_customer", "offer": "dim_offer",
    "rental": "fact_order_line", "playback": "fact_playback_session",
    "distributor": "dim_distributor", "campaign": "dim_campaign",
    "consent": "fact_customer_consent", "touch": "fact_campaign_touch",
    "campaign_conversion": "fact_campaign_conversion",
}


def utc_timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO UTC string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("timestamp must include UTC Z or +00:00")
    return parsed


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def validate_record(entity, row, deleted=False):
    spec = ENTITIES[entity]
    if not isinstance(row, dict):
        raise ValueError("state payload must be an object")
    normalized = {name: row.get(name) for name in spec["fields"]}
    required = [spec["key"]] if deleted else spec["required"]
    for name in required:
        if row.get(name) is None or row.get(name) == "":
            raise ValueError(f"{entity}: missing {name}")
    for name, kind in spec["fields"].items():
        value = row.get(name)
        if value is None:
            continue
        if kind == "long":
            if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 2**63 - 1:
                raise ValueError(f"{name}: expected nonnegative int64")
        elif kind == "boolean":
            if type(value) is not bool:
                raise ValueError(f"{name}: expected boolean")
        elif kind == "timestamp":
            normalized[name] = utc_timestamp(value).isoformat(timespec="microseconds").replace("+00:00", "Z")
        elif kind == "date":
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                datetime.strptime(value, "%Y-%m-%d")
            else:
                timestamp = utc_timestamp(value)
                if any((timestamp.hour, timestamp.minute, timestamp.second, timestamp.microsecond)):
                    raise ValueError(f"{name}: a calendar date cannot discard a non-midnight time")
                normalized[name] = timestamp.date().isoformat()
        elif not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name}: expected nonempty string")
    if not deleted:
        if "currency" in row and not re.fullmatch("[A-Z]{3}", row["currency"]):
            raise ValueError("currency: expected uppercase ISO code")
        if entity == "content" and row["duration_seconds"] <= 0:
            raise ValueError("duration_seconds must be positive")
        if entity == "offer":
            if row["transaction_type"] not in ("TVOD", "EST", "SVOD"):
                raise ValueError("transaction_type must be TVOD, EST or SVOD")
            if row["transaction_type"] == "TVOD" and any(
                not row.get(f) for f in ("start_window_hours", "play_window_hours")
            ):
                raise ValueError("TVOD requires positive explicit playback policy windows")
        if entity == "rental":
            created = utc_timestamp(row["created_at"])
            for field in ("start_deadline", "first_play_at", "expires_at"):
                if row.get(field) and utc_timestamp(row[field]) < created:
                    raise ValueError(f"{field} precedes created_at")
    return normalized


def validate_event(event, event_entity_map, delete_event_types):
    for field in ("event_id", "event_type", "entity_key", "run_id", "correlation_id"):
        if not isinstance(event.get(field), str) or not event[field].strip():
            raise ValueError(f"envelope: missing {field}")
    seq = event.get("source_sequence")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1 or seq > 2**63 - 1:
        raise ValueError("source_sequence must be a positive int64")
    if type(event.get("schema_version")) is not int or event["schema_version"] != 1:
        raise ValueError("only schema_version 1 is implemented")
    utc_timestamp(event.get("occurred_at"))
    utc_timestamp(event.get("produced_at"))
    entity = event_entity_map.get(event["event_type"])
    if entity not in ENTITIES:
        raise ValueError("unmapped event_type; commands/outbox control are not business sales")
    payload = event.get("payload")
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ValueError("state payload must be an object")
    if event.get("payload_json") is not None:
        if json.loads(event["payload_json"]) != payload:
            raise ValueError("payload_json does not match payload")
    if "is_deleted" in payload and type(payload["is_deleted"]) is not bool:
        raise ValueError("is_deleted must be a boolean")
    deleted = event["event_type"] in delete_event_types or payload.get("is_deleted") is True
    state = validate_record(entity, payload, deleted)
    key = ENTITIES[entity]["key"]
    if state[key] != event["entity_key"]:
        raise ValueError("entity_key does not match payload natural key")
    return {**event, "entity": entity, "payload": state, "is_deleted": deleted}


def latest_state(events, event_entity_map, delete_event_types):
    """Reference reducer used in unit tests; Spark mirrors these conflict gates."""
    seen, sequence, latest = {}, {}, {}
    for raw in events:
        event = validate_event(raw, event_entity_map, delete_event_types)
        eid, fingerprint = event["event_id"], digest(raw)
        if eid in seen:
            if seen[eid] != fingerprint:
                raise ValueError("conflicting event_id")
            continue
        seen[eid] = fingerprint
        key = (event["entity"], event["entity_key"])
        position = (*key, event["source_sequence"])
        if position in sequence and sequence[position] != fingerprint:
            raise ValueError("conflicting entity sequence")
        sequence[position] = fingerprint
        if key not in latest or event["source_sequence"] > latest[key]["source_sequence"]:
            latest[key] = event
    # Tombstones are retained; callers filter them only when publishing active tables.
    return latest


def minor_amount(value, exponent):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("money must come from integer minor units")
    if type(exponent) is not int or not 0 <= exponent <= 4:
        raise ValueError("currency exponent must be explicitly supplied (0..4)")
    return Decimal(value).scaleb(-exponent)
