"""Replay a native deadlock through SQL execution, Gold reconciliation and the checkpoint."""
import copy
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pyodbc

from fabric.contracts import ENTITIES, LINKS
from fabric.sql import render_load
from services.publisher.publish import TransientSqlConnectionError
from services.publisher.runtime import Runtime
from services.publisher.worker import Store, Worker
from test_worker import config, event


DEADLOCK = (
    "40001", "[40001] [Microsoft][ODBC Driver 18 for SQL Server][SQL Server]"
    "Transaction (Process ID 160) was deadlocked on lock resources with another "
    "process and has been chosen as the deadlock victim. Rerun the transaction. "
    "(1205) (SQLExecDirectW)",
)


class GoldRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.store = Store(self.path)
        self.cfg = config()
        self.cfg.update(tenant_id=self.cfg["workspace_id"], currency_exponents={"EUR": 2},
                        commercial_statuses=["completed"], max_input_events=1000)
        self.cfg["items"]["silver"]["displayName"] = "MSFlixSilver"
        self.cfg["items"]["gold"] = {"id": "gold"}
        self.now = 1000
        self.failure = pyodbc.OperationalError(*DEADLOCK)
        self.fail_at = "load"
        self.sql = render_load(self.cfg, self.cfg["items"]["silver"])
        self.gold_marker = self.marker(800)
        self.connections = []
        self.loads = []
        self.runtime = Runtime(self.cfg, credential=Mock())
        self.runtime.analytics = Mock(side_effect=self.connection)
        self.runtime.publish = Mock(return_value={"broker_acknowledged": 0})
        self.runtime.published = Mock(return_value=[event()])
        self.runtime.submit_job = Mock()
        instance = Worker(self.cfg, self.runtime, self.store, lambda: self.now)
        instance.tick()
        instance.state["cycle"].update(
            silver_started_at=900, raw_intent=850, silver_intent=900,
            raw_job={"id": "raw-completed", "status": "Completed"},
            silver_job={"id": "silver-completed", "status": "Completed"})
        instance.advance("gold")
        self.cycle = copy.deepcopy(instance.state["cycle"])

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def marker(self, completed):
        return {"run_id": self.cfg["run_id"],
                "completed_at": datetime.fromtimestamp(completed, timezone.utc), "order_lines": 1}

    def connection(self, layer):
        connection = Mock()
        self.connections.append((layer, connection))

        def cursor_factory():
            cursor = Mock()
            cursor.nextset.return_value = False

            def run(query, *params):
                if query == self.sql:
                    self.loads.append(connection)
                    if self.failure and self.fail_at == "load":
                        raise self.failure
                    self.gold_marker = self.marker(self.now)
                    rows = []
                elif "INFORMATION_SCHEMA.COLUMNS" in query:
                    rows = [{"TABLE_NAME": name, "COLUMN_NAME": column}
                            for name, spec in ENTITIES.items() for column in spec["fields"]]
                    rows += [{"TABLE_NAME": "link_" + name, "COLUMN_NAME": column}
                             for name, (_, left, _, right, _) in LINKS.items() for column in (left, right)]
                elif "silver.publication" in query:
                    rows = [self.marker(950)]
                elif "gold.publication" in query:
                    if self.failure and self.fail_at == "marker":
                        raise self.failure
                    rows = [self.gold_marker]
                elif "source_sequence" in query:
                    rows = [{"order_id": "order-1", "source_sequence": 1}]
                else:
                    raise AssertionError("Unexpected SQL in Gold recovery fixture: " + query)
                cursor.description = [(key,) for key in rows[0]] if rows else None
                cursor.fetchmany.return_value = [tuple(row.values()) for row in rows]
                return cursor

            cursor.execute.side_effect = run
            return cursor

        connection.cursor.side_effect = cursor_factory
        return connection

    def once(self):
        self.store.db.close()
        self.store = Store(self.path)
        Worker(self.cfg, self.runtime, self.store, lambda: self.now).run_pass()
        return self.store.load()

    def assert_preserved(self, state):
        for key, value in self.cycle.items():
            self.assertEqual(state["cycle"][key], value)
        self.assertNotIn("gold_publication", state["cycle"])
        self.assertEqual(self.store.pending([event()]), [event()])
        self.runtime.submit_job.assert_not_called()

    def test_deadlock_recovers_same_cycle_on_fresh_connection_after_restart(self):
        state = self.once()
        self.assertEqual(state["phase"], "gold", "A rolled-back Gold deadlock must not strand Start Demo")
        self.assertEqual(state["retry"]["kind"], "gold_deadlock")
        self.assertEqual(state["retry"]["next_attempt_at"], self.now + 30)
        self.assert_preserved(state)
        self.failure = None
        calls = self.runtime.analytics.call_count
        self.once()
        self.assertEqual(self.runtime.analytics.call_count, calls, "Restart must respect the saved retry time")
        self.now = state["retry"]["next_attempt_at"]
        state = self.once()
        self.assertEqual(state["phase"], "waiting_gold_onelake")
        self.assertEqual(state["cycle"]["id"], self.cycle["id"])
        self.assertEqual(state["cycle"]["gold_publication"]["order_lines"], 1)
        self.assertEqual(len(self.loads), 2)
        self.assertIsNot(self.loads[0], self.loads[1])
        for _, connection in self.connections:
            connection.close.assert_called_once()
        self.assertEqual(state["last_recovery"]["kind"], "gold_deadlock")
        self.assertEqual(self.store.pending([event()]), [event()])
        self.runtime.submit_job.assert_not_called()

    def test_fifth_deadlock_blocks_without_discarding_completed_jobs(self):
        for attempt, delay in enumerate((30, 60, 120, 240), start=1):
            state = self.once()
            self.assertEqual(state["phase"], "gold")
            self.assertEqual(state["retry"]["attempt"], attempt)
            self.assertEqual(state["retry"]["next_attempt_at"] - self.now, delay)
            self.assert_preserved(state)
            self.now = state["retry"]["next_attempt_at"]
        state = self.once()
        self.assertEqual(state["phase"], "blocked")
        self.assertEqual(state["blocked_phase"], "gold")
        self.assertEqual(state["error_kind"], "gold_deadlock_exhausted")
        self.assertNotIn("retry", state)
        self.assert_preserved(state)
        self.failure = None
        self.once()
        self.assertEqual(len(self.loads), 5)

    def test_deadlock_backoff_does_not_extend_the_gold_deadline(self):
        state = self.once()
        self.assertEqual(state["phase"], "gold")
        self.now += self.cfg["stage_timeout_seconds"] + 1
        state = self.once()
        self.assertEqual(state["phase"], "blocked")
        self.assertIn("bounded stage deadline", state["error"])
        self.assertEqual(state["stage_started_at"], 1000)
        self.assertEqual(len(self.loads), 1)
        self.assert_preserved(state)

    def test_recovery_reads_existing_commit_instead_of_reloading(self):
        self.fail_at = "marker"
        state = self.once()
        self.assertEqual(state["phase"], "gold")
        self.failure = None
        self.gold_marker = self.marker(1000)
        self.now = state["retry"]["next_attempt_at"]
        state = self.once()
        self.assertEqual(state["phase"], "waiting_gold_onelake")
        self.assertEqual(self.loads, [])
        self.assertEqual(state["cycle"]["gold_publication"]["order_lines"], 1)
        self.assertEqual(self.store.pending([event()]), [event()])

    def test_other_execution_failures_are_not_misclassified_as_deadlock(self):
        for error in (
            pyodbc.OperationalError("HYT00", "Timeout; outcome unknown (1205) (SQLExecDirectW)"),
            pyodbc.OperationalError("40001", "Serialization conflict (3960) (SQLExecDirectW)"),
            pyodbc.OperationalError("40001", "Other error (12050) (SQLExecDirectW)"),
            pyodbc.ProgrammingError("42000", "Permission denied (229) (SQLExecDirectW)"),
            RuntimeError(*DEADLOCK),
        ):
            with self.subTest(error=error):
                self.store.save({"phase": "gold", "stage_started_at": self.now,
                                 "cycle": copy.deepcopy(self.cycle)})
                self.failure = error
                state = self.once()
                self.assertEqual(state["phase"], "blocked")
                self.assertEqual(state["error_kind"], "nonretryable")
                self.assertNotIn("retry", state)
                self.assert_preserved(state)

    def test_outbox_deadlock_is_not_retried_as_gold_work(self):
        self.runtime.publish.side_effect = pyodbc.OperationalError(*DEADLOCK)
        state = self.once()
        self.assertEqual(state["phase"], "blocked")
        self.assertEqual(state["error_kind"], "nonretryable")
        self.assertEqual(self.loads, [])
        self.assert_preserved(state)

    def test_connection_outage_between_deadlocks_does_not_reset_gold_budget(self):
        state = self.once()
        self.assertEqual(state["phase"], "gold")
        self.now = state["retry"]["next_attempt_at"]
        self.runtime.publish.side_effect = TransientSqlConnectionError("08001")
        state = self.once()
        self.assertEqual(state["retry"]["kind"], "sql_connect_unavailable")
        self.assertEqual(state["retry"]["attempt"], 1)
        self.now = state["retry"]["next_attempt_at"]
        self.runtime.publish.side_effect = None
        state = self.once()
        self.assertEqual(state["retry"]["kind"], "gold_deadlock")
        self.assertEqual(state["retry"]["attempt"], 2)
        self.assertEqual(state["stage_started_at"], 1030)
        self.assert_preserved(state)


if __name__ == "__main__":
    unittest.main()
