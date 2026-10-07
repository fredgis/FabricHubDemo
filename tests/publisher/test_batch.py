import unittest
from unittest.mock import Mock

import test_envelope

publisher = test_envelope.publisher


class Producer:
    def __init__(self, errors):
        self.errors = errors
        self.callbacks = []
        self.acknowledged = []

    def produce(self, topic, key, value, on_delivery):
        self.callbacks.append(on_delivery)

    def poll(self, timeout):
        index = len(self.acknowledged)
        if index < len(self.errors):
            self.callbacks[index](self.errors[index], None)
            self.acknowledged.append(index)


class BatchTests(unittest.TestCase):
    def rows(self):
        row = test_envelope.EnvelopeTests().row()
        return [row, {**row, "event_id": "another-event", "entity_key": "order-2"}]

    def test_all_broker_acks_precede_one_atomic_sql_commit(self):
        producer = Producer([None, None])
        cursor, database = Mock(), Mock()
        cursor.rowcount = 2

        def update(*args):
            self.assertEqual(len(producer.acknowledged), 2)
            self.assertEqual(args[1:], tuple(row["event_id"] for row in self.rows()))

        cursor.execute.side_effect = update
        self.assertEqual(publisher.publish_batch(self.rows(), producer, "fixture", cursor, database), 2)
        cursor.execute.assert_called_once()
        database.commit.assert_called_once()
        database.rollback.assert_not_called()

    def test_one_failed_ack_keeps_all_sql_delivery_state_unchanged(self):
        producer = Producer([None, "broker failure"])
        cursor, database = Mock(), Mock()
        with self.assertRaisesRegex(RuntimeError, "acknowledgement failed"):
            publisher.publish_batch(self.rows(), producer, "fixture", cursor, database)
        cursor.execute.assert_not_called()
        database.rollback.assert_called_once()
        database.commit.assert_not_called()

    def test_sql_count_mismatch_rolls_back_and_allows_event_replay(self):
        producer = Producer([None, None])
        cursor, database = Mock(), Mock()
        cursor.rowcount = 1
        with self.assertRaisesRegex(RuntimeError, "changed after broker ACK"):
            publisher.publish_batch(self.rows(), producer, "fixture", cursor, database)
        database.rollback.assert_called_once()
        database.commit.assert_not_called()

    def test_missing_ack_cannot_be_marked_published(self):
        producer = Producer([None])
        cursor, database = Mock(), Mock()
        times = iter([0, 0, 0, 66])
        with self.assertRaisesRegex(RuntimeError, "acknowledgement failed"):
            publisher.publish_batch(self.rows(), producer, "fixture", cursor, database,
                                    clock=lambda: next(times))
        cursor.execute.assert_not_called()
        database.rollback.assert_called_once()
        database.commit.assert_not_called()

    def test_duplicate_event_ids_are_rejected_before_kafka_production(self):
        producer = Producer([None, None])
        cursor, database = Mock(), Mock()
        row = self.rows()[0]
        with self.assertRaisesRegex(ValueError, "Duplicate event_id"):
            publisher.publish_batch([row, row], producer, "fixture", cursor, database)
        self.assertEqual(producer.callbacks, [])
        cursor.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
