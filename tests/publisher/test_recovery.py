"""Regression at the actual persistent loop + ODBC connection boundary."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pyodbc

from services.publisher import publish, worker
from test_worker import config, event


LOGIN_TIMEOUT = ("HYT00", "[HYT00] [Microsoft][ODBC Driver 18 for SQL Server]"
                 "Login timeout expired (0) (SQLDriverConnect)")


class WorkerConnectionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.config = config()
        self.config["poll_seconds"] = 30
        self.config_path = self.path / "config.json"
        self.config_path.write_text(json.dumps(self.config))
        self.now = 1000.0
        self.store = worker.Store(self.path)
        self.runtime = Mock()
        self.runtime.exact_ids.return_value = {"complete": True}
        self.runtime.published.return_value = [event()]
        self.original_worker = worker.Worker
        instance = self.original_worker(self.config, self.runtime, self.store, lambda: self.now)
        instance.tick()
        self.cycle = copy.deepcopy(instance.state["cycle"])
        self.store.receipt({"event_ids": ["new-event"], "broker_acknowledged": 1, "sql_committed": True})
        credential = Mock()
        credential.get_token.return_value.token = "fixture-token-not-a-live-credential"

        def connect_pass(_receipt):
            connection = publish.sql_connect("sql.example", "demo", credential)
            connection.close()
            return {"broker_acknowledged": 0, "committed_batches": 0}

        self.runtime.publish.side_effect = connect_pass

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def once(self, error=None):
        args = ["worker", "--config", str(self.config_path), "--state", str(self.path), "--once"]
        factory = lambda cfg, runtime, store: self.original_worker(cfg, runtime, store, lambda: self.now)
        with patch("sys.argv", args), patch.object(worker, "validate_config", side_effect=lambda cfg: cfg), \
                patch.object(worker, "Runtime", return_value=self.runtime), \
                patch.object(worker, "check_access", return_value={}), \
                patch.object(worker, "Worker", side_effect=factory), \
                patch("pyodbc.connect", side_effect=error, return_value=Mock()) as connect:
            worker.main()
        return self.store.load(), connect.call_count

    def test_five_login_timeouts_do_not_permanently_block_native_wait(self):
        # Exactly the production failure pattern: publisher SQLDriverConnect
        # times out while an ACKed cycle waits for native OneLake coverage.
        for _ in range(5):
            state, calls = self.once(pyodbc.OperationalError(*LOGIN_TIMEOUT))
            self.assertEqual(calls, 1)
            # Move only to the durable retry time once the fix provides it.
            self.now = max(self.now + 30, state.get("retry", {}).get("next_attempt_at", 0))
        state, calls = self.once()
        self.assertEqual(calls, 1)
        self.assertEqual(state["phase"], "raw",
                         "A healthy connection must resume the same native-ID gate, not remain blocked")
        self.assertEqual(state["cycle"]["id"], self.cycle["id"])
        self.assertEqual(state["cycle"]["events"], self.cycle["events"])
        self.assertEqual(self.store.pending([event()]), [event()])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0], 1)
        self.runtime.submit_job.assert_not_called()

    def test_tls_connect_failure_recovers_from_idle_without_manual_resume(self):
        self.store.save({"phase": "idle", "last_cycle": None})
        error = pyodbc.OperationalError(
            "08001", "SSL Provider: certificate verify failed:unable to get local issuer certificate "
            "(SQLDriverConnect)")
        state, calls = self.once(error)
        self.assertEqual(calls, 1)
        self.assertEqual(state["phase"], "idle")
        self.assertEqual(state["retry"]["kind"], "sql_connect_unavailable")
        state, calls = self.once()
        self.assertEqual(calls, 0, "A TLS failure must observe the durable backoff")
        self.now = state["retry"]["next_attempt_at"]
        state, calls = self.once()
        self.assertEqual(calls, 1)
        self.assertEqual(state["phase"], "waiting_native_onelake")
        self.assertEqual(state["cycle"]["events"], [event()])
        self.assertEqual(state["last_recovery"]["kind"], "sql_connect_unavailable")
        self.assertEqual(self.store.pending([event()]), [event()])
        self.runtime.submit_job.assert_not_called()

    def test_unavailable_connection_preserves_an_inflight_cycle(self):
        state, _ = self.once(pyodbc.OperationalError("08001", "Unable to connect (SQLDriverConnect)"))
        self.now = state.get("retry", {}).get("next_attempt_at", self.now + 30)
        state, _ = self.once()
        self.assertEqual(state["phase"], "raw")
        self.assertEqual(state["cycle"]["id"], self.cycle["id"])
        self.assertEqual(state["cycle"]["events"], self.cycle["events"])
        self.runtime.submit_job.assert_not_called()

    def test_retryable_tls_failure_never_disables_certificate_validation(self):
        credential = Mock()
        credential.get_token.return_value.token = "fixture-token-not-a-live-credential"
        error = pyodbc.OperationalError("08001", "certificate verify failed (SQLDriverConnect)")
        with patch("pyodbc.connect", side_effect=error) as connect:
            with self.assertRaises(publish.TransientSqlConnectionError):
                publish.sql_connect("sql.example", "demo", credential)
        self.assertIn("Encrypt=yes;TrustServerCertificate=no;", connect.call_args.args[0])
        self.assertEqual(connect.call_count, 1)

    def test_established_connection_failure_is_not_retried(self):
        self.runtime.publish.side_effect = pyodbc.OperationalError(
            "08001", "Connection failed during SQLExecDirectW; write outcome unknown")
        state, _ = self.once()
        self.assertEqual(state["phase"], "blocked")
        self.assertEqual(state["error_kind"], "nonretryable")
        self.runtime.publish.reset_mock()
        self.runtime.publish.side_effect = None
        state, _ = self.once()
        self.runtime.publish.assert_not_called()
        self.assertEqual(state["phase"], "blocked")

    def test_permission_failure_remains_blocked_on_subsequent_healthy_connection(self):
        error = pyodbc.ProgrammingError("28000", "Login failed for user (18456) (SQLDriverConnect)")
        for _ in range(5):
            state, _ = self.once(error)
            self.now += 30
        state, _ = self.once()
        self.assertEqual(state["phase"], "blocked")
        self.assertEqual(state["blocked_phase"], "waiting_native_onelake")
        self.assertEqual(state["cycle"]["id"], self.cycle["id"])
        self.runtime.submit_job.assert_not_called()

    def test_retry_is_durable_rate_limited_and_cools_down_after_five_attempts(self):
        for attempt, delay in enumerate((30, 60, 120, 240, 900), start=1):
            state, calls = self.once(pyodbc.OperationalError(*LOGIN_TIMEOUT))
            self.assertEqual(calls, 1)
            self.assertEqual(state["retry"]["attempt"], attempt)
            self.assertEqual(state["retry"]["next_attempt_at"] - self.now, delay)
            state, calls = self.once(pyodbc.OperationalError(*LOGIN_TIMEOUT))
            self.assertEqual(calls, 0, "Process restart must not bypass the durable backoff")
            self.now = state["retry"]["next_attempt_at"]
        self.assertTrue(state["retry"]["cooldown"])
        state, calls = self.once(pyodbc.OperationalError(*LOGIN_TIMEOUT))
        self.assertEqual(calls, 1)
        self.assertEqual(state["retry"]["attempt"], 1)
        self.assertEqual(state["retry"]["total_failures"], 6)
        self.assertNotEqual(state["phase"], "blocked")

    def test_sql_outage_does_not_exhaust_the_native_wait_deadline(self):
        self.once(pyodbc.OperationalError(*LOGIN_TIMEOUT))
        self.now += self.config["stage_timeout_seconds"] * 2
        state, _ = self.once()
        self.assertEqual(state["phase"], "raw")
        self.assertEqual(state["last_recovery"]["total_failures"], 1)
        self.assertNotIn("retry", state)
        self.assertNotIn("error", state)

    def test_sql_statement_timeout_is_not_retried_as_a_login_timeout(self):
        self.runtime.publish.side_effect = pyodbc.OperationalError(
            "HYT00", "Timeout expired (SQLExecDirectW); write outcome unknown")
        state, _ = self.once()
        self.assertEqual(state["phase"], "blocked")
        self.assertEqual(state["error_kind"], "nonretryable")
        self.runtime.publish.reset_mock()
        self.runtime.publish.side_effect = None
        state, _ = self.once()
        self.runtime.publish.assert_not_called()
        self.assertEqual(state["phase"], "blocked")

    def test_lost_job_post_response_does_not_resubmit(self):
        state = self.store.load()
        state["phase"] = "raw"
        self.store.save(state)
        self.runtime.jobs.return_value = []
        self.runtime.submit_job.side_effect = TimeoutError("Lost POST response")
        state, _ = self.once()
        self.assertEqual(state["phase"], "blocked")
        self.assertEqual(state["blocked_phase"], "raw")
        self.assertIn("raw_intent", state["cycle"])
        state, _ = self.once()
        self.runtime.submit_job.assert_called_once()


if __name__ == "__main__":
    unittest.main()
