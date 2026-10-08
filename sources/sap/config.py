"""Bounded scenario configuration; no environment IDs, credentials or network I/O."""
from __future__ import annotations

import calendar
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import jsonschema

from sources.sap.accounting import money

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "scenario.example.json"
DEFAULT_REFERENCES = ROOT / "references.json"


def read_json(path: Path) -> dict:
    def unique_pairs(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError(f"Duplicate JSON key: {name}")
            result[name] = value
        return result

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def keyed(rows: list[dict], key: str) -> dict[str, dict]:
    result = {}
    for row in rows:
        value = row[key]
        if not isinstance(value, str) or not value or value in result:
            raise ValueError(f"Missing or duplicate reference key: {key}={value!r}")
        result[value] = row
    return result


def validate(config: dict, references: dict) -> None:
    for value, filename in ((config, "scenario.schema.json"), (references, "references.schema.json")):
        schema = read_json(ROOT / "contracts" / filename)
        jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker(),
        ).validate(value)
    start = date.fromisoformat(config["period_start"])
    if start.day != 1 or not 2000 <= start.year <= 2098:
        raise ValueError("The scenario must start on the first day of a month in 2000-2098")
    if references.get("schema_version") != 1:
        raise ValueError("Unsupported reference schema")
    observed = datetime.fromisoformat(references["observed_at_utc"].replace("Z", "+00:00"))
    if observed.tzinfo is None or observed.utcoffset().total_seconds() != 0:
        raise ValueError("Reference observation must be an explicit UTC timestamp")
    if start <= observed.date():
        raise ValueError("The synthetic period must follow the observed reference snapshot")
    if not references.get("gold_publication") or not references.get("provenance"):
        raise ValueError("Reference publication and provenance are required")
    customers = keyed(references["customers"], "customer_key")
    keyed(references["customers"], "salesforce_contact_id")
    contents = keyed(references["contents"], "content_key")
    distributors = keyed(references["distributors"], "distributor_key")
    selected = keyed(config["customers"], "customer_key")
    keyed(config["customers"], "sap_customer")
    if {r["role"] for r in selected.values()} != {"paid", "paid_with_credit", "unpaid"}:
        raise ValueError("Exactly one customer per scenario role is required")
    for key in selected:
        if key not in customers or customers[key]["territory"] != config["territory"]:
            raise ValueError(f"Missing customer or mismatched territory: {key}")
        if not customers[key].get("salesforce_contact_id") or not customers[key].get("name"):
            raise ValueError(f"Incomplete CRM reference: {key}")
    for key in config["content_keys"]:
        if key not in contents or contents[key]["distributor_key"] not in distributors:
            raise ValueError(f"Unresolved content/distributor reference: {key}")
    if Decimal(config["monthly_net"]) <= Decimal(config["credit_net"]):
        raise ValueError("Monthly net must exceed the nonnegative credit")
    if Decimal(config["credit_net"]) <= 0 or Decimal(config["fixed_content_cost"]) <= 0:
        raise ValueError("This scenario requires a positive credit and fixed content cost")
    if Decimal(config["content_revenue_share"]) <= 0:
        raise ValueError("This scenario requires a positive variable content share")
    net = Decimal(config["monthly_net"]) * len(selected) - Decimal(config["credit_net"])
    supplier_net = Decimal(config["fixed_content_cost"]) + money(net * Decimal(config["content_revenue_share"]))
    supplier_gross = supplier_net + money(supplier_net * Decimal(config["vat_rate"]))
    if not 0 < money(supplier_gross / 2) < supplier_gross:
        raise ValueError("Supplier invoice is too small for a nonzero partial cent payment")
    if "fictional" not in config["supplier_name"].lower():
        raise ValueError("The supplier must be explicitly labelled fictional")
    if any(r.get("sap_partner_code") == config["supplier_id"] for r in distributors.values()):
        raise ValueError("The fictional supplier must not impersonate an existing Oracle SAP partner")


def period(config: dict) -> tuple[date, date]:
    start = date.fromisoformat(config["period_start"])
    return start, date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])


def extraction_time(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=timezone.utc)
