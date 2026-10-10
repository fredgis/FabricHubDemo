# Existing MSFlix Demo automation

The deployed Demo's typed `placeOrder`, `startPlayback`, and `recordProgress`
functions persist the business change and `dbo.Outboxes` in the same SQL
transaction. This worker propagates those **existing** events and, when explicitly
enabled, consumes the Demo's native-source reload requests. It creates no business
transactions, exposes no HTTP endpoint, and does not implement Flixy.

## Runtime and trigger contract

- Host: an **existing dedicated MSFlix Oracle Linux VM**, selected by explicit
  ARM resource ID. No new VM, storage account, capacity, paid SKU, or inbound port.
- Unit: `msflix-demo-worker.service`, enabled at boot, running as the unprivileged
  local `msflix-demo` account. systemd restarts the process after failure.
- Authentication: `ManagedIdentityCredential` from IMDS only. No Azure CLI,
  copied administrator token, client secret, Kafka key, or workstation process.
- Configuration: `/etc/msflix-demo/config.json`, root-owned, group-readable.
  Environment must be `dev`, `test`, or `prod`; every identity/endpoint is
  deployment configuration, not a source-code literal.
- Releases: `/opt/msflix-demo/releases/<sha256-prefix>`; `current` is an atomic
  symlink. Durable checkpoint, ACK receipts, and status:
  `/var/lib/msflix-demo/{state.sqlite3,status.json}`.
- **Triggers:** an existing native command commits a new outbox row, or an
  operator requests `reload_oracle` / `reload_salesforce` in `dbo.ControlCommands`.
  The worker checks every 30 seconds. No new Fabric pipeline or HTTP endpoint is
  required; the client submits typed commands and polls their persisted status.
- With no new event IDs and no requested source reload, there is no OneLake scan,
  notebook execution, Gold load, or graph refresh. An initial deployment
  reconciles the already-published history once.

The publisher retains the original bounded interface: default batch 128,
maximum batch 512; maximum duration 600 seconds and maximum 20,000 messages per
invocation. The service uses shorter 30-second/2,000-message passes. Kafka OAuth
uses **`https://<namespace>.servicebus.windows.net/.default`**, never the generic
Event Hubs audience.

## Demo source reload buttons

`source_reload_enabled: true` enables the two source commands. The configuration
prepared by `scripts.demo_prepare` copies this flag from the Fabric configuration;
existing configurations default to disabled. Apply the accompanying column-level
ControlCommands permissions before deploying an enabled worker.

- **Reload Oracle:** read the current native `MSFlix_OracleMirror` snapshot for
  content, offers and distributors, then run the existing Raw, Silver, Gold and
  graph chain. This does not restart continuous Oracle CDC or change source rows.
- **Reload Salesforce:** run the existing BPS extraction, Silver, dimension and
  fact pipelines in that order, then conform their current native CRM snapshots
  through the same MSFlix Raw, Silver, Gold and graph chain. This is not an `sf`
  CLI export, and BPS Gold is not a substitute for the consolidated MSFlixGold.
- **SAP:** disabled in the cockpit; no SAP reload command is accepted.

The typed operator-only UDF inserts a request with an idempotency key and rejects
another Oracle or Salesforce reload while one is requested, running or blocked.
The worker finishes its current propagation cycle before claiming the request.
The existing SQL application lock and persisted job IDs serialize execution;
restarting the worker polls already-submitted jobs instead of rerunning them.

A request remains `running` through the entire chain. `completed` is written only
after reference proofs in Raw, Silver, Gold and OneLake, plus successful graph
refresh and a real graph query. A failed or ambiguous job becomes `blocked` with
a sanitized error, not a false completion. After investigating the recorded phase,
use the existing explicit `resume` command; a new button click is not a recovery
mechanism. The service must be running: an offline host leaves a request queued.

Snapshots are immutable per command under `Files/ingress/reloads/`. The Raw
notebook receives its existing complete configuration with only the selected
source paths and `snapshot_run_id` values overridden. Other reference snapshots,
event identities, the main `run_id` and worker bindings are unchanged. Routine
button reloads therefore need no notebook rebind or maintenance watermark reset.
The full maintenance procedure below still applies to changes in bindings or
source authority. Empty, truncated or duplicate-key native snapshots are refused.

## Publication gates

1. Acquire a SQL session application lock for the publisher. Produce the
   canonical envelope, including the payload object and matching `payload_json`.
   Require every broker ACK before committing `published_at`. Receipts retain
   exact event IDs, Kafka topic/partition/offset, and SQL-commit status, not
   payloads or tokens. Release the session lock explicitly on success and
   failure before returning the connection to ODBC's pool.
2. Snapshot pending published IDs in a durable cycle. Wait until **every exact
   ID** is in the Eventhouse's native OneLake `RawEvents` Delta snapshot.
   `TargetLatency=5min` is a target, not proof or a fixed sleep.
3. Run the existing Raw notebook; verify those IDs in actual
   `raw.events_ingress`, including absence of physical Raw duplicates.
4. Run the existing Silver notebook only after Raw succeeds. Refresh its SQL
   metadata, require a fresh successful publication marker and matching latest
   event-owned entity sequences.
5. Execute the existing `fabric/gold/load.sql` transaction. Its count,
   minor-unit, identity, and relation checks remain authoritative. Require
   actual Gold facts, then native OneLake facts **and all 12 link tables**
   before graph refresh.
6. Submit the documented
   `/graphModels/{id}/jobs/refreshGraph/instances`; wait for completion. Run real
   GQL against the refreshed graph: the customer → order → offer → content path,
   plus rental/playback business state matching Gold.
7. Only then commit the exact event IDs to the propagated checkpoint.

Kafka delivery remains **at least once**: an ACK followed by a lost SQL commit
can replay an event. Raw deduplicates `event_id`; physical KQL replay duplicates
are valid. A count alone, a completed notebook, or an accepted graph job never
advances the end-to-end checkpoint.

The pinned Delta 1.6.6 Rust-native `scan()` reader honors both **deletion vectors**
and **column mapping**. The older `to_pyarrow_dataset()` path does not; scanning
all Parquet files would be incorrect and is intentionally not a fallback.

## Permissions

The only Azure role added is **Azure Event Hubs Data Sender** on the existing
`msflix-events` topic, not its namespace or subscription. Local authentication
stays disabled.

The documented Notebook REST execution API requires the VM managed identity to
have **Contributor** on this dedicated Fabric workspace. The current official
Core Items API exposes no item-level Write/Execute grant operation, so the
deployment does not invent an undocumented sharing endpoint. The identity is
not assigned workspace Admin or any role in another workspace.
Contributor also inherits broad Fabric SQL access, so the
deployment creates an explicit external SQL user and applies native SQL DENYs
to restrict that inherited access:

- `SELECT` on `dbo.Outboxes`.
- Column-scoped `UPDATE (published_at)` only.
- When source reloads are enabled, `SELECT` on `dbo.ControlCommands` and
  `UPDATE (status, completed_at, error)` only. Command insertion/deletion and
  changes to type, parameters, identity and idempotency keys remain denied.
- Other outbox-column updates, outbox inserts/deletes, other business-table
  reads/writes, ownership and schema/user/role changes are denied.
- Session application locks use the existing `public` principal; no
  `db_owner` or broad stored-procedure grant is made.

For a Fabric SQL service principal, the external user's SID is the **application
(client) ID**, not the service-principal object ID. ARM/Fabric role assignments
use the object ID. The deployment resolves and records both; mixing them leaves
the SQL restrictions attached to an unused principal.

`services.publisher.check` runs on the VM using IMDS before unpausing; its
authorization checks also run on every worker process start. It requires:

- Token tenant, principal object ID, application ID and VM resource ID exactly
  match the explicit `orchestration_authorization` binding.
- The MI can see **only this workspace**, specifically as Contributor.
- **Zero explicit SQL `db_owner` memberships**.
- Permitted outbox SELECT/`published_at` update; denied payload modification,
  outbox deletion, and order reads/inserts.
- Working application locks and actual Fabric/OneLake/Gold/graph reads.

**Tradeoff:** Fabric Contributor makes `IS_MEMBER('db_owner')` report `1` even
with zero explicit SQL memberships. That inherited role bit is recorded, not
mistaken for the effective rights: the verified native SQL DENYs remain
mandatory. There is no generic “skip permission checks” flag. The explicit
authorization mode is `workspace-contributor-with-outbox-denies`, bound to the
one actual MI/workspace/VM. This is the required **orchestration** role, not an
extra SQL owner grant for publishing.

**Do not waive a failed effective-permission check.** New operational tables
require corresponding DENYs on redeployment; Contributor remains a wider
control-plane permission than the SQL publisher alone needs.

## Deployment

Use cached administration authentication; the scripts never invoke `az login`.
Coordinate the existing VM's Run Command extension with any concurrent source
maintenance. Only one Run Command may execute on that VM at a time.

```powershell
.\scripts\Deploy-DemoAutomation.ps1 `
  -FabricConfig fabric\config.live.local.json `
  -VmResourceId <existing-approved-vm-resource-id> `
  -OperationalItemId <existing-app-sql-item-id> `
  -OperationalServer <discovered-app-sql-server> `
  -OperationalDatabase <actual-physical-database-name> `
  -GraphId <existing-ontology-child-graph-id> `
  -InstallPrerequisites
```

Deployment is **paused by default** so the IMDS permission check and upstream
maintenance handoff can complete before the first Spark run:

```powershell
python -m scripts.demo_control --config .state/demo-automation/config.json `
  --state .state/demo-automation --action preflight
python -m scripts.demo_control --config .state/demo-automation/config.json `
  --state .state/demo-automation --action unpause
```

`-Start` removes that deployment pause; use it only after verification.
The prerequisite installer adds Python/ODBC and an isolated virtual
environment. It does **not** rerun Oracle provisioning, touch a gateway,
change Eventstream topology, or modify notebooks/ontology definitions.

## Status, restart, and recovery

```powershell
python -m scripts.demo_control --config .state/demo-automation/config.json `
  --state .state/demo-automation --action status
```

Other actions: `pause`, `unpause`, `restart`, `resume`. `pause` suppresses new
worker ticks; it does not cancel an already-running Fabric job. Before external
Raw/Silver/Gold maintenance, stop new Demo commands, let the current event cycle
finish, then pause and confirm the saved status has `paused: true` and phase
`idle`, with no active Fabric jobs. If the paused phase is not `idle`, do not start the master refresh: finish
that event cycle first. `restart` preserves the checkpoint and recorded job
IDs. `resume` follows repair of a blocked stage; it does not discard job intent.

- One SQL session lock serializes deployed orchestrators. A lost lock terminates
  the process; it cannot keep writing as an unfenced worker.
- The worker checks active/recent notebook jobs and active graph refreshes
  before submitting. It stores submission intent before POST and the returned
  job ID immediately afterwards. A crash/lost response is reconciled against
  job history; it never blindly submits the same job again.
- While a Demo event cycle is pending, the worker verifies the pinned
  Eventstream source and destination, not just the DefaultStream's status.
  The `ingress` binding contains the discovered Eventstream, source and
  destination IDs. Only the existing Event Hubs → `RawEvents` route can be
  resumed; a changed topology or target is rejected. Paused nodes resume
  destination-first with `startType: WhenLastStopped`, never `Now`. No
  topology, connection or retention setting is changed. The operator's worker
  pause still suppresses every tick and therefore every automatic resume.
  Resume intent and operation IDs survive restart. A lost response is checked
  against topology without another POST; an unresolved resume blocks after
  ten minutes and requires inspection. Running nodes alone never unlock Raw:
  every expected event ID must also exist in native OneLake.
- A missing-ID result in `waiting_native_onelake` remains a read-only wait.
  After 30 minutes, status exposes `native_onelake.overdue` and probes every
  five minutes instead of permanently blocking. The same cycle and IDs are
  retained across restart. Only the exact native-wait deadline error from
  older workers is automatically recovered; other blocked errors are not.
  This cannot recover messages that have expired from upstream retention:
  persistent missing IDs still require investigation, not a new Start Demo.
- Other stages have a 30-minute deadline. SQL **connection-establishment** timeouts
  (`HYT00`/`HYT01`) and unavailable connections (`08001`, including transient TLS
  handshake failures) from `SQLDriverConnect`, before any statement is submitted,
  keep the same cycle/phase and persist their error plus next retry time.
  Every attempt retains `Encrypt=yes;TrustServerCertificate=no`; retries never
  accept an untrusted certificate or bypass authentication. A persistent TLS
  failure still requires repairing the certificate chain, not weakening TLS.
  The retry kind distinguishes `sql_connect_timeout` from `sql_connect_unavailable`.
  Retry delays are 30, 60, 120, and 240 seconds; after the fifth failed
  connection the worker waits 900 seconds before another bounded burst.
  No attempts occur during the persisted backoff, including after restart.
  Only time when SQL is unavailable is excluded from bounded stage deadlines;
  job and post-Gold OneLake waits still have their original bound.
- Permission, configuration, invalid data, terminal failed Spark jobs, and
  statement/commit timeouts enter `blocked` immediately with the original
  phase, error and job intent preserved. Publishing and propagation stop until
  explicit repair/resume. A query/write timeout is **not** reclassified as a
  login timeout, and an uncertain job POST is never blindly resubmitted.
  A successful connection-retry pass records `last_recovery`; none of these
  states claim that downstream data has caught up.
  If an older version already persisted an `08001` connection failure as
  `blocked`, verify a secure connection, deploy the fix, and `resume` once.
  Keep its checkpoint and job IDs; do not rerun Start Demo to retry delivery.
- During Gold reconciliation, a native ODBC SQLSTATE `40001` with SQL Server
  deadlock code `1205` is retryable: SQL Server has rolled back the victim
  transaction. The worker persists `gold_deadlock` and retries the **whole**
  reconciliation on fresh connections after 30, 60, 120, and 240 seconds.
  Each attempt checks the publication marker first and verifies the target
  rows afterwards; it never retries an isolated statement inside a transaction.
  Completed Raw/Silver jobs, event IDs and the same cycle are preserved.
  These waits count toward the Gold stage deadline. A fifth deadlock blocks
  with `gold_deadlock_exhausted`; restarts or intervening connection outages
  do not reset the cycle's deadlock budget. Inspect competing writers before
  explicitly resuming. Other SQL execution errors, including ambiguous
  statement/commit timeouts and Outbox failures, remain nonretryable.
  After deploying this fix over an older `1205` blocked checkpoint, `resume`
  once to retry that same Gold stage, without rerunning Start Demo.
- Keep `/var/lib/msflix-demo`; deleting it forces historical reconciliation.
  SQLite uses WAL and synchronous FULL. The status JSON is an atomic, compact
  read model; the database is authoritative.
- Stop persistent operation on the VM with
  `sudo systemctl disable --now msflix-demo-worker.service`.

There is no automatic reference re-extraction. **Event-only refresh reuses the
completed native Oracle/BPS snapshots and the same configured `run_id`**, so the
Raw snapshot-batch guard skips them. For a requested CRM/master refresh, first
refresh the native BPS SQL snapshots and Oracle CDC/staging, then redeploy the
coordinated notebook definitions and worker configuration. Never replace those
sources with CLI Salesforce exports. Changing bindings beneath an unfinished
cycle is deliberately rejected.

### Full native-master refresh: pause, align configuration, then unpause

These are maintenance instructions, not another acceptance scenario.
From the repository root, pause the **idle** worker:

```powershell
python -m scripts.demo_control --config .state/demo-automation/config.json `
  --state .state/demo-automation --action pause
python -m scripts.demo_control --config .state/demo-automation/config.json `
  --state .state/demo-automation --action status
```

Run the existing full-refresh sequence while paused: refresh the native
Oracle/BPS snapshots, stage a **new `run_id`**, persist that configuration in the
existing Raw/Silver notebook definitions, and finish Raw → Silver → Gold →
graph. Staging new files alone is not sufficient.

**Before unpausing, refresh the worker configuration too.** For a snapshot-only
refresh with unchanged item IDs and contracts, copy the newly completed master
`run_id` into the ignored worker config, then deploy that config **paused**:

```powershell
$previousMasterRunId = (Get-Content .state/demo-automation/config.json -Raw | ConvertFrom-Json).run_id
python -c 'import json; from pathlib import Path; p=Path(".state/demo-automation/config.json"); c=json.loads(p.read_text()); m=json.loads(Path("fabric/config.live.local.json").read_text()); assert c["workspace_id"] == m["workspace_id"]; c["run_id"]=m["run_id"]; p.write_text(json.dumps(c,indent=2),encoding="utf-8")'
python -m scripts.demo_deploy --config .state/demo-automation/config.json `
  --state .state/demo-automation
```

Do **not** use `--start`. A changed `run_id` changes the saved `binding_hash`,
even at an idle checkpoint; deployment alone therefore leaves the startup guard
closed until the explicit rebind below. On the existing Linux VM, through the
usual authenticated administration/Run Command path, substitute the captured
`$previousMasterRunId` and run:

```bash
set -eu
PREVIOUS_MASTER_RUN_ID='<value captured before updating the worker config>'
sudo systemctl stop msflix-demo-worker.service
cd /opt/msflix-demo/current
sudo -u msflix-demo /opt/msflix-demo/venv/bin/python -c '
import hashlib, json, sys
from pathlib import Path
from contextlib import closing
from fabric.sql import execute
from services.publisher.runtime import Runtime
from services.publisher.worker import Store, validate_config
cfg = validate_config(json.loads(Path("/etc/msflix-demo/config.json").read_text()))
previous = {**cfg, "run_id": sys.argv[1]}
def digest(c):
    return hashlib.sha256(json.dumps({k:c[k] for k in ("workspace_id","items","notebooks","graph_id","run_id")}, sort_keys=True).encode()).hexdigest()
store = Store("/var/lib/msflix-demo")
state = store.load()
assert Path("/var/lib/msflix-demo/PAUSED").exists(), "Maintenance pause required"
assert state["phase"] == "idle" and not state.get("cycle"), "Finish the event cycle first"
assert state.get("binding_hash") in (digest(previous), digest(cfg)), "More than the master run_id changed"
with closing(Runtime(cfg).analytics("gold")) as sql:
    assert len(execute(sql, "SELECT run_id FROM gold.publication WHERE run_id=?", (cfg["run_id"],))) == 1, "New master Gold publication required"
state["binding_hash"] = digest(cfg)
store.save(state)
store.db.close()
' "$PREVIOUS_MASTER_RUN_ID"
# Continue only if the rebind command succeeded:
sudo systemctl start msflix-demo-worker.service
```

This preserves the `propagated` event membership, broker receipts, and prior
cycle evidence; never delete the SQLite state to bypass the guard. It is
idempotent for the same completed master run and refuses an unfinished cycle
or a different item binding.

Finally, from the repository root:

```powershell
python -m scripts.demo_control --config .state/demo-automation/config.json `
  --state .state/demo-automation --action unpause
```

`unpause` reruns the managed-identity/effective-permission preflight before
removing `PAUSED`. `resume` only repairs a blocked-stage checkpoint; it neither
removes `PAUSED` nor updates the master configuration/binding hash. Do not
unpause with the older worker config: it is out of step with the refreshed
notebooks and their Silver/Gold publication markers.

## Bounded acceptance and evidence

```powershell
python -m unittest discover -s tests/publisher -v
python -m scripts.demo_evidence --config .state/demo-automation/config.json `
  --state .state/demo-automation
python -m scripts.demo_verify --config .state/demo-automation/config.json `
  --target .state/demo-automation/pending-acceptance.json `
  --vm-evidence .state/demo-automation/vm-evidence-latest.json `
  --output .state/demo-automation/acceptance.json
```

Acceptance reuses the three already-persisted native Demo events for one order
and one playback. The target is captured from the existing SQL outbox into the
ignored file; verification creates **no additional orders or events**.
It requires the exact broker receipts, native OneLake and Raw event IDs, the
latest Gold order/playback event IDs and sequences, actual post-refresh GQL,
the durable propagated checkpoint, and a subsequent real idle worker cycle.
The CLI is only an independent read-only observer; processing runs on the VM.

Keep deployment details, ARM LRO resumable URLs, exact journey IDs, Kafka
receipts, Raw/Gold queries, and post-refresh GQL results in ignored
`.state/demo-automation/`. Do not commit state, credentials, or live bindings.
The existing app's client-side idempotency and native UDF integration are not
changed by this worker.

### Verified ingress recovery, 10 October 2026

The incident had a Running DefaultStream but Paused source and destination
nodes, followed by an older worker's permanent native-wait deadline block.
The deployed recovery resumed the pinned nodes and the original checkpoint,
without replaying events or creating a replacement Demo run. Verification
found all 20 original event IDs in native OneLake, all 20 durable propagation
receipts, and an idle worker without error. Gold contained the expected five
orders, five sessions and five distinct customers, with exact values and no
duplicate or missing records. The 48 targeted publisher tests passed.

The published Insights function and the authenticated local UI showed those
five orders and sessions on **10 October**, totaling **20.95 in ALL** (nominal
EUR + CHF, no FX conversion), with BE/CH/FR on the map. A direct hosting check
returned HTTP 401 with CLI credentials; the hosted SSO journey was not
validated by this check and is not claimed as a successful browser smoke.

References:
[Notebook API unattended execution](https://learn.microsoft.com/fabric/data-engineering/notebook-public-api),
[SQL authorization and DENY precedence](https://learn.microsoft.com/fabric/database/sql/authorization),
[Graph refresh API and managed identity support](https://learn.microsoft.com/rest/api/fabric/graphmodel/background-jobs/run-on-demand-refresh-graph).
