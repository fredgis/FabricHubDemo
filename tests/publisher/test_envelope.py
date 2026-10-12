import importlib.util
import pathlib
import unittest
from datetime import datetime, timezone

path = pathlib.Path(__file__).parents[2] / "services" / "publisher" / "publish.py"
spec = importlib.util.spec_from_file_location("publisher", path)
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class EnvelopeTests(unittest.TestCase):
    def row(self):
        return {
            "event_id": "00000000-0000-4000-8000-000000000601",
            "event_type": "rental.created",
            "entity_key": "order-1",
            "source_sequence": 1,
            "occurred_at": datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc),
            "run_id": "run-1",
            "payload": '{"order_id":"order-1","amount_minor":399,"currency":"EUR"}',
        }

    def test_preserves_exact_money_and_payload_mirror(self):
        event = publisher.envelope(self.row())
        self.assertEqual(event["payload"]["amount_minor"], 399)
        self.assertEqual(event["payload_json"], '{"amount_minor":399,"currency":"EUR","order_id":"order-1"}')
        self.assertEqual(event["occurred_at"], "2026-10-07T12:00:00Z")

    def test_rejects_invalid_payload(self):
        row = self.row()
        row["payload"] = "[]"
        with self.assertRaises(ValueError):
            publisher.envelope(row)

    def test_rejects_nonpositive_or_boolean_sequence(self):
        for sequence in (0, -1, True):
            row = self.row()
            row["source_sequence"] = sequence
            with self.assertRaises(ValueError):
                publisher.envelope(row)

    def test_missing_identity_is_not_invented(self):
        row = self.row()
        row["event_id"] = ""
        with self.assertRaises(ValueError):
            publisher.envelope(row)


if __name__ == "__main__":
    unittest.main()

