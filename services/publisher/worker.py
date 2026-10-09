"""Restart-safe, event-driven orchestration on an existing managed-identity VM."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sqlite3
import time
import uuid
from pathlib import Path

from fabric.rest import DeploymentError, safe_error_message
from services.publisher.access import check_access, validate_authorization
from services.publisher.publish import TransientSqlConnectionError
from services.publisher.runtime import GoldDeadlockError, Runtime, latest_targets, timestamp

ACTIVE = ("NotStarted", "InProgress", "Running")
FAILED = ("Failed", "Cancelled", "Canceled", "Deduped")
CONNECT_RETRY_DELAYS = (30, 60, 120, 240, 900)
GOLD_RETRY_DELAYS = (30, 60, 120, 240)


def validate_config(cfg):
    if cfg.get("environment") not in ("dev", "test", "prod"):
        raise ValueError("Explicit environment dev/test/prod required")
    if cfg.get("auth") != "managed-identity":
        raise ValueError("Deployed worker requires managed-identity; no CLI/user-token fallback")
    validate_authorization(cfg)
    for key in ("tenant_id", "subscription_id", "workspace_id", "capacity_id", "graph_id"):
        uuid.UUID(cfg[key])
    if cfg.get("rti_ingestion") != "eventhouse_onelake" or not cfg.get("run_id"):
        raise ValueError("Existing native OneLake route and completed master run_id required")
    if not 1 <= cfg.get("max_input_events", 0) <= 100000:
        raise ValueError("Input bound must be 1..100000")
    if not 15 <= cfg.get("poll_seconds", 30) <= 300:
        raise ValueError("Polling interval must be 15..300 seconds")
    if not 300 <= cfg.get("stage_timeout_seconds", 1800) <= 3600:
        raise ValueError("Stage timeout must be 300..3600 seconds")
    for layer in ("raw", "silver", "gold", "kql"):
        uuid.UUID(cfg["items"][layer]["id"])
    for value in cfg["notebooks"].values():
        uuid.UUID(value)
    # Configuration is deliberately not an arbitrary credential container.
    def inspect(value):
        if isinstance(value, dict):
            for name, child in value.items():
                if any(k in name.lower() for k in ("password", "secret", "access_token", "sas_token")):
                    raise ValueError("Secrets prohibited in worker configuration")
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)
        elif isinstance(value, str) and ("Bearer " in value or "SharedAccessKey=" in value or "?sig=" in value):
            raise ValueError("Credential material prohibited in worker configuration")
    inspect(cfg)
    return cfg


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.directory / "state.sqlite3")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS checkpoint (id INTEGER PRIMARY KEY, body TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS propagated (event_id TEXT PRIMARY KEY, cycle_id TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS receipts (id INTEGER PRIMARY KEY, body TEXT NOT NULL)")
        self.db.commit()

    def load(self):
        row = self.db.execute("SELECT body FROM checkpoint WHERE id=1").fetchone()
        return json.loads(row[0]) if row else {"phase": "idle", "last_cycle": None}

    def save(self, state):
        state["updated_at"] = time.time()
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO checkpoint VALUES (1,?)", (json.dumps(state),))
        public = {k: v for k, v in state.items() if k != "cycle"}
        if state.get("cycle"):
            cycle = state["cycle"]
            public["cycle"] = {k: v for k, v in cycle.items() if k not in ("events", "targets")}
            public["cycle"]["event_count"] = len(cycle["events"])
        temporary = self.directory / "status.json.tmp"
        temporary.write_text(json.dumps(public, indent=2), encoding="utf-8")
        os.replace(temporary, self.directory / "status.json")

    def pending(self, rows):
        known = {r[0] for r in self.db.execute("SELECT event_id FROM propagated")}
        return [r for r in rows if r["event_id"] not in known]

    def receipt(self, receipt):
        with self.db:
            self.db.execute("INSERT INTO receipts (body) VALUES (?)", (json.dumps(receipt),))
        print(json.dumps({"kind": "kafka_ack_sql_commit", **receipt}), flush=True)

    def complete(self, state):
        cycle = state["cycle"]
        summary = {k: v for k, v in cycle.items() if k not in ("events", "targets")}
        summary.update(event_count=len(cycle["events"]), completed_at=time.time())
        # The event checkpoint and cycle completion commit together. No
        # watermark can advance on mere broker ACK, job success, or row counts.
        next_state = {"phase": "idle", "last_cycle": summary, "updated_at": time.time()}
        with self.db:
            self.db.executemany("INSERT OR IGNORE INTO propagated VALUES (?,?)",
                               [(e["event_id"], cycle["id"]) for e in cycle["events"]])
            self.db.execute("INSERT OR REPLACE INTO checkpoint VALUES (1,?)", (json.dumps(next_state),))
        self.save(next_state)
        return next_state


class Worker:
    def __init__(self, cfg, runtime, store, clock=time.time):
        self.cfg, self.runtime, self.store, self.clock = cfg, runtime, store, clock
        self.state = store.load()
        identity = hashlib.sha256(json.dumps(
            {k: cfg[k] for k in ("workspace_id", "items", "notebooks", "graph_id", "run_id")},
            sort_keys=True).encode()).hexdigest()
        if self.state.get("binding_hash") not in (None, identity):
            raise DeploymentError("Worker bindings changed; reconcile existing checkpoint before promoting")
        self.binding_hash = identity

    def save(self):
        self.state["binding_hash"] = self.binding_hash
        self.store.save(self.state)

    def advance(self, phase):
        self.state["phase"] = phase
        self.state["stage_started_at"] = self.clock()
        self.state.pop("error", None)
        self.state.pop("failures", None)
        self.save()

    def block(self, exc, kind="nonretryable"):
        self.state["error"] = safe_error_message(str(exc))
        self.state["error_kind"] = kind
        self.state["blocked_phase"] = self.state["phase"]
        self.state["phase"] = "blocked"
        self.state.pop("retry", None)
        self.save()
        print(json.dumps({"phase": "blocked", "error": self.state["error"]}), flush=True)

    def run_pass(self):
        """Retry only failed connects or confirmed, rolled-back Gold deadlocks."""
        if self.state["phase"] == "blocked":
            return
        now = self.clock()
        retry = self.state.get("retry")
        if retry and now < retry["next_attempt_at"]:
            return
        if (retry and retry["kind"].startswith("sql_connect_") and
                retry["phase"] == self.state["phase"] and self.state["phase"] != "idle"):
            # SQL unavailability stopped all stage work. Exclude precisely that
            # downtime, not healthy OneLake/job wait time, from its deadline.
            self.state["stage_started_at"] += max(0, now - retry["suspended_at"])
            retry["suspended_at"] = now
            self.save()
        attempted_at = now
        try:
            self.state["publisher"] = self.runtime.publish(self.store.receipt)
            self.tick()
        except TransientSqlConnectionError as exc:
            previous = self.state.get("retry", {})
            if not previous.get("kind", "").startswith("sql_connect_"):
                previous = {}
            attempt = previous.get("attempt", 0) % len(CONNECT_RETRY_DELAYS) + 1
            failed_at = self.clock()
            self.state["retry"] = {
                "kind": exc.kind, "sqlstate": exc.sqlstate,
                "phase": self.state["phase"], "attempt": attempt,
                "total_failures": previous.get("total_failures", 0) + 1,
                "first_failure_at": previous.get("first_failure_at", attempted_at),
                "last_failure_at": failed_at,
                "suspended_at": previous.get("suspended_at", attempted_at),
                "next_attempt_at": failed_at + CONNECT_RETRY_DELAYS[attempt - 1],
                "cooldown": attempt == len(CONNECT_RETRY_DELAYS),
            }
            self.state["error"] = str(exc)
            self.state["error_kind"] = "transient_sql_connect"
            self.save()
            print(json.dumps({"phase": self.state["phase"], "error": self.state["error"],
                              "retry": self.state["retry"]}), flush=True)
            return
        except GoldDeadlockError as exc:
            if self.state["phase"] != "gold":
                self.block(exc)
                return
            history = self.state["cycle"].setdefault("gold_deadlocks", {
                "first_failure_at": attempted_at, "total_failures": 0})
            history["total_failures"] += 1
            attempt = history["total_failures"]
            if attempt > len(GOLD_RETRY_DELAYS):
                self.block("Gold deadlock retry limit reached after five failed attempts; "
                           "inspect competing writes before resume", "gold_deadlock_exhausted")
                return
            failed_at = self.clock()
            self.state["retry"] = {
                **history, "kind": "gold_deadlock", "sqlstate": "40001", "native_error": 1205,
                "phase": "gold", "attempt": attempt, "last_failure_at": failed_at,
                "next_attempt_at": failed_at + GOLD_RETRY_DELAYS[attempt - 1],
            }
            self.state["error"] = str(exc)
            self.state["error_kind"] = "transient_gold_deadlock"
            self.save()
            print(json.dumps({"phase": "gold", "error": self.state["error"],
                              "retry": self.state["retry"]}), flush=True)
            return
        except Exception as exc:
            # Permission/config/data faults, failed jobs, and statement/commit
            # timeouts are not safe connection retries. Preserve their exact
            # stage and any submission intent; no automatic write resubmission.
            self.block(exc)
            return
        recovered = self.state.pop("retry", None)
        if recovered:
            self.state["last_recovery"] = {
                "kind": recovered["kind"], "first_failure_at": recovered["first_failure_at"],
                "recovered_at": self.clock(), "total_failures": recovered["total_failures"],
            }
        self.state.pop("error", None)
        self.state.pop("error_kind", None)
        self.state.pop("failures", None)
        self.save()

    def _job(self, layer):
        graph = layer == "graph"
        skill = "fabriciq-ontology-cli" if graph else "spark-cli"
        item = self.cfg["graph_id"] if graph else self.cfg["notebooks"][layer]
        cycle = self.state["cycle"]
        ref = cycle.get(layer + "_job")
        intent = cycle.get(layer + "_intent")
        if ref:
            if self.clock() < ref.get("not_before", 0):
                return False
            job = self.runtime.get_job(item, ref["id"], skill)
            ref["status"] = job["status"]
            self.save()
            if job["status"] in FAILED:
                raise DeploymentError(f"{layer} job {ref['id']} ended {job['status']}; no automatic resubmission")
            if job["status"] == "Completed":
                cycle[layer + "_completed_at"] = timestamp(job["endTimeUtc"])
                if layer == "silver":
                    cycle["silver_started_at"] = timestamp(job["startTimeUtc"])
                return True
            if job["status"] not in ACTIVE:
                raise DeploymentError(f"Unknown job state {job['status']}")
            return False
        jobs = self.runtime.jobs(item, skill)
        if intent:
            # Saved before POST. Reconcile a crash/lost response rather than
            # issuing the same mutation again.
            matches = [j for j in jobs if j.get("startTimeUtc") and
                       timestamp(j["startTimeUtc"]) >= intent - 2]
            if len(matches) == 1:
                cycle[layer + "_job"] = {"id": matches[0]["id"], "adopted": True}
                self.save()
                return False
            if not matches and self.clock() - intent < 300:
                return False
            raise DeploymentError("Ambiguous saved job intent; inspect history before explicit resume")
        active = [j for j in jobs if j["status"] in ACTIVE]
        if active:
            # A graph run that began before our Gold commit cannot prove this
            # cycle. Wait for it; do not create a concurrent refresh.
            return False
        if not graph and any(j.get("startTimeUtc") and
                             self.clock() - timestamp(j["startTimeUtc"]) < 300 for j in jobs):
            return False
        if layer == "raw":
            # Don't write Raw while an external Silver or graph job is active.
            for other, other_item in (("spark-cli", self.cfg["notebooks"]["silver"]),
                                      ("fabriciq-ontology-cli", self.cfg["graph_id"])):
                if any(j["status"] in ACTIVE for j in self.runtime.jobs(other_item, other)):
                    return False
        cycle[layer + "_intent"] = self.clock()
        self.save()
        cycle[layer + "_job"] = self.runtime.submit_job(item, graph)
        self.save()
        return False

    def tick(self):
        phase = self.state["phase"]
        if phase == "blocked":
            return
        if phase != "idle" and self.clock() - self.state["stage_started_at"] > self.cfg.get("stage_timeout_seconds", 1800):
            raise DeploymentError(f"{phase} exceeded bounded stage deadline; no success claimed")
        if phase == "idle":
            pending = self.store.pending(self.runtime.published())
            if not pending:
                self.state["idle_checked_at"] = self.clock()
                self.save()
                return
            self.state["cycle"] = {
                "id": str(uuid.uuid4()), "started_at": self.clock(), "events": pending,
                "targets": latest_targets(pending, self.cfg),
                "event_ids_sha256": hashlib.sha256("\n".join(sorted(
                    r["event_id"] for r in pending)).encode()).hexdigest()}
            self.advance("waiting_native_onelake")
            return
        cycle = self.state["cycle"]
        ids = [row["event_id"] for row in cycle["events"]]
        if phase == "waiting_native_onelake":
            cycle["native_onelake"] = self.runtime.exact_ids("native", ids)
            self.save()
            if cycle["native_onelake"]["complete"]:
                self.advance("raw")
        elif phase == "raw":
            if self._job("raw"):
                self.advance("verify_raw")
        elif phase == "verify_raw":
            cycle["raw_proof"] = self.runtime.exact_ids("raw", ids)
            self.save()
            if cycle["raw_proof"]["complete"]:
                self.advance("silver")
        elif phase == "silver":
            if self._job("silver"):
                self.advance("silver_metadata")
        elif phase == "silver_metadata":
            self.runtime.refresh_metadata()
            self.advance("gold")
        elif phase == "gold":
            marker = self.runtime.gold(cycle)
            if marker:
                cycle["gold_publication"] = marker
                self.advance("waiting_gold_onelake")
        elif phase == "waiting_gold_onelake":
            if self.runtime.gold_onelake(cycle):
                cycle["gold_onelake_verified_at"] = self.clock()
                self.advance("graph")
        elif phase == "graph":
            if self._job("graph"):
                self.advance("verify_graph")
        elif phase == "verify_graph":
            proof = self.runtime.verify_graph(cycle["targets"])
            if proof is not None:
                cycle["graph_proof"] = proof
                self.state = self.store.complete(self.state)
                self.save()
        else:
            raise DeploymentError("Unknown persisted worker phase")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    cfg = validate_config(json.loads(args.config.read_text(encoding="utf-8")))
    store, runtime = Store(args.state), Runtime(cfg)
    access = check_access(runtime)
    worker = Worker(cfg, runtime, store)
    worker.state["authorization"] = access
    worker.save()
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    runtime.acquire_lock()
    try:
        while not stopped:
            runtime.heartbeat_lock()  # Deliberately outside retry handling.
            worker.state["paused"] = (args.state / "PAUSED").exists()
            worker.save()
            if not worker.state["paused"]:
                worker.run_pass()
            if args.once:
                break
            for _ in range(cfg.get("poll_seconds", 30)):
                if stopped:
                    break
                time.sleep(1)
    finally:
        runtime.close()
        store.db.close()


if __name__ == "__main__":
    main()
