"""Local fixtures only; none of these records are production ingress."""
import copy
import json
import unittest
from decimal import Decimal
from pathlib import Path

import jsonschema

from fabric.contracts import canonical, latest_state, minor_amount, validate_event, validate_record

MAP = {"order.state": "rental", "order.deleted": "rental", "playback.state": "playback"}
DELETES = ["order.deleted"]


def order_event(sequence=1, eid=None, deleted=False):
    state = {"order_id": "fixture-order", "customer_key": "fixture-customer",
             "offer_key": "fixture-offer", "status": "created", "amount_minor": 199,
             "currency": "EUR", "created_at": "2026-10-07T10:00:00Z"}
    if deleted:
        state = {"order_id": "fixture-order"}
    return {"event_id": eid or f"fixture-event-{sequence}", "event_type": "order.deleted" if deleted else "order.state",
            "schema_version": 1, "entity_key": "fixture-order", "source_sequence": sequence,
            "occurred_at": "2026-10-07T10:00:00Z", "produced_at": "2026-10-07T10:00:01Z",
            "run_id": "fixture-run", "correlation_id": "fixture-correlation", "payload": state}


class ContractsTests(unittest.TestCase):
    def test_at_least_once_dedup_and_latest_not_sum(self):
        first = order_event()
        later = order_event(2)
        later["payload"]["status"] = "expired"
        state = latest_state([later, first, first, later], MAP, DELETES)
        self.assertEqual(len(state), 1)
        current = state[("rental", "fixture-order")]
        self.assertEqual(current["source_sequence"], 2)
        self.assertEqual(current["payload"]["amount_minor"], 199)
        self.assertEqual(current["payload"]["status"], "expired")

    def test_update_then_delete_replay_does_not_resurrect(self):
        state = latest_state([order_event(1), order_event(3, deleted=True), order_event(2)], MAP, DELETES)
        self.assertTrue(state[("rental", "fixture-order")]["is_deleted"])
        self.assertEqual(state[("rental", "fixture-order")]["payload"]["order_id"], "fixture-order")

    def test_explicit_tombstone(self):
        event = order_event()
        event["payload"] = {"order_id": "fixture-order", "is_deleted": True}
        self.assertTrue(validate_event(event, MAP, DELETES)["is_deleted"])

    def test_conflicting_event_id_is_not_an_arbitrary_winner(self):
        a, b = order_event(), order_event()
        b["payload"]["amount_minor"] = 200
        with self.assertRaisesRegex(ValueError, "conflicting event_id"):
            latest_state([a, b], MAP, DELETES)

    def test_conflicting_sequence_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "entity sequence"):
            latest_state([order_event(eid="fixture-a"), order_event(eid="fixture-b")], MAP, DELETES)

    def test_invalid_envelopes_are_rejected(self):
        cases = [
            ("source_sequence", 0), ("source_sequence", True),
            ("source_sequence", 2**63), ("schema_version", 2), ("schema_version", True),
            ("occurred_at", "2026-10-07T10:00:00"), ("event_type", "control.completed"),
            ("entity_key", "wrong-order"), ("payload", []), ("payload", None)
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value), self.assertRaises((ValueError, TypeError)):
                e = order_event()
                e[field] = value
                validate_event(e, MAP, DELETES)

    def test_no_float_money_or_negative_amount(self):
        for value in (1.99, True, -1, "199"):
            e = order_event()
            e["payload"]["amount_minor"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_event(e, MAP, DELETES)

    def test_integer_minor_units_exact(self):
        self.assertEqual(minor_amount(199, 2), Decimal("1.99"))
        self.assertEqual(minor_amount(199, 0), Decimal("199"))
        self.assertEqual(minor_amount(1001, 3), Decimal("1.001"))
        self.assertEqual(minor_amount(9223372036854775807, 2), Decimal("92233720368547758.07"))
        with self.assertRaises(ValueError):
            minor_amount(1.99, 2)
        with self.assertRaises(ValueError):
            minor_amount(199, True)

    def test_payload_mirror_must_match(self):
        event = order_event()
        event["payload_json"] = canonical(event["payload"])
        self.assertEqual(validate_event(event, MAP, DELETES)["payload"]["amount_minor"], 199)
        event["payload_json"] = "{}"
        with self.assertRaisesRegex(ValueError, "does not match"):
            validate_event(event, MAP, DELETES)

    def test_rental_policy_and_utc(self):
        offer = {"offer_key": "fixture-offer", "content_key": "fixture-film", "territory": "DE",
                 "currency": "EUR", "transaction_type": "TVOD", "price_minor": 199}
        with self.assertRaisesRegex(ValueError, "windows"):
            validate_record("offer", offer)
        offer.update(start_window_hours=72, play_window_hours=48)
        self.assertEqual(validate_record("offer", offer)["play_window_hours"], 48)
        event = order_event()
        event["payload"]["expires_at"] = "2026-10-06T10:00:00Z"
        with self.assertRaisesRegex(ValueError, "precedes"):
            validate_event(event, MAP, DELETES)

    def test_wire_json_schema(self):
        path = Path(__file__).resolve().parents[2] / "fabric" / "event.schema.json"
        validator = jsonschema.Draft202012Validator(json.loads(path.read_text()),
                                                   format_checker=jsonschema.FormatChecker())
        validator.validate(order_event())
        invalid = order_event()
        invalid["source_sequence"] = 0
        self.assertTrue(list(validator.iter_errors(invalid)))

    def test_content_event_normalizes_only_exact_utc_midnight_dates(self):
        payload = {
            "content_key": "fixture-film", "title": "Fixture film",
            "release_date": "2010-09-27T00:00:00.000Z", "duration_seconds": 900,
            "genre": "Animation", "image_url": "/fixture.svg",
            "source_url": "https://example.invalid/fixture", "license": "Fixture only",
            "attribution": "Local test fixture",
        }
        event = {**order_event(), "event_type": "content.upserted",
                 "entity_key": "fixture-film", "payload": payload,
                 "payload_json": canonical(payload)}
        state = validate_event(event, {"content.upserted": "content"}, [])["payload"]
        self.assertEqual(state["release_date"], "2010-09-27")
        self.assertEqual(payload["release_date"], "2010-09-27T00:00:00.000Z")
        for value in ("2010-09-27T12:00:00Z", "2010-09-27T00:00:00", "2010-09-27T00:00:00+02:00"):
            event["payload"] = {**payload, "release_date": value}
            event["payload_json"] = canonical(event["payload"])
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_event(event, {"content.upserted": "content"}, [])

    def test_sql_seven_digit_timestamp_normalizes_to_fabric_microseconds(self):
        event = order_event()
        event["payload"]["created_at"] = "2026-10-07T13:40:01.9220000Z"
        event["payload_json"] = canonical(event["payload"])
        state = validate_event(event, MAP, DELETES)["payload"]
        self.assertEqual(state["created_at"], "2026-10-07T13:40:01.922000Z")
        self.assertEqual(event["payload"]["created_at"], "2026-10-07T13:40:01.9220000Z")


if __name__ == "__main__":
    unittest.main()
