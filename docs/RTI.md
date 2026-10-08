# RTI: committed transactions, exact event IDs

**Checkpoint: 8 October 2026, 06:19 UTC.** The persistent cloud worker has
propagated **13,458 event IDs**. Its three-event acceptance reached Kafka, KQL,
native OneLake, deduplicated Raw, Gold and the ontology graph. Every remaining
Eventstream node is Running.

## The supported path being delivered

```text
Trusted command → operational SQL + transactional outbox
  → persistent bounded Kafka publisher → Event Hubs
  → MSFlixIngress Eventstream relay
  → MSFlixEvents.RawEvents in MSFlixEventhouse
  → native OneLake availability
  → physical MSFlixRaw.raw.events_ingress
  → Silver current state → Gold Warehouse → Ontology graph
```

**Eventstream is still required.** Direct Kafka-to-Eventhouse ingestion has not
been qualified. The failed direct Eventstream-to-Raw branch and its SQL operator
have been removed; the accepted path uses KQL native OneLake availability and
physical Raw materialization.

| Physical component | Actual identifier |
|---|---|
| Eventstream `MSFlixIngress` | `5b40dec1-85db-4b2b-b8b1-1487155cfaed` |
| Eventhouse `MSFlixEventhouse` | `df0f578d-6aa2-4901-a55e-39cc37db03f3` |
| KQL database `MSFlixEvents` | `2d7abed1-e7a7-4afd-9e35-4ab441423ac1` |
| Raw Lakehouse | `a37f4d51-ae84-4a46-880e-bb23d33fbd03` |
| Raw processing notebook | `f6cc6bb3-2f10-4cfa-a80d-ae041cb8c119` |
| Silver processing notebook | `5c3716a8-6fac-421d-b418-0cc9dfe17ff4` |

Ingress uses the approved Singapore Event Hubs namespace
`msflix-gki72e4smyneg`, hub `msflix-events`, through the workspace-identity
connection. The Eventstream and Eventhouse family are organized in
`03 RTI Transactions`; Raw and Silver remain separate Lakehouses.

## What is actually proved

| Boundary | Latest supplied result |
|---|---|
| Operational persistence | 13,458 committed events in the propagated checkpoint; pending outbox count 0. No extra orders were generated for the three-event acceptance. |
| Publisher | Persistent service active, enabled and unpaused. Latest Kafka ACKs: partition/offset `3/3554`, `3/3555`, `0/3433`. |
| Eventstream → KQL | All remaining stream nodes Running; all three newly acknowledged acceptance IDs observed in KQL. |
| KQL → native OneLake | Enabled with a five-minute target; all three acceptance IDs observed in the native Delta output before analytics processing. |
| Physical Raw | The worker's exact-ID gate found all three acceptance events in deduplicated physical Raw; propagated checkpoint 13,458 IDs. |
| Silver normalization | The 305 release-date mismatch and SQL seven-digit timestamp handling were corrected/persisted. No entity-sequence conflicts were found. |
| Gold publication | **1,003 order lines**; target order `973d963b-52dc-4b55-bf07-6a75e335f9d9` and its playback retain their exact latest event IDs/sequences. |
| Ontology graph | Refresh `783d0926-bed9-477d-bb90-aa60857167d3` completed; actual GQL returned the target order/customer/content path and playback. |
| Idle behavior | A subsequent service cycle completed without another Spark run. |

These counts are checkpoints, not immutable promises about later replay runs.
Replaying retained events can add physical duplicates while preserving the
same logical `event_id` set.

## The historical-coverage problem and actual repair

Native OneLake availability was enabled after part of the history had arrived,
with `Backfill=false`. Enabling a policy does not retroactively prove that all
old events are present.

The service rejected the attempted `Backfill=true` policy update with **HTTP
400**. No backfill success is claimed. Instead, the parent used the supported
KQL-destination pause/resume surface with
**CustomTime `2026-10-07T16:25:00Z`**, replaying retained, identical event IDs
through the enabled native OneLake path. **No KQL data was deleted.**

At the 7 October recovery checkpoint, KQL's native Delta output was materialized
into physical Raw idempotently. SQL confirmed 13,455 physical rows and 13,455
distinct event IDs. This is actual Raw coverage, not merely a configured policy
or nonempty shortcut. The first connected-events Silver/Gold publication has
also succeeded; native master refresh completed in a later run.
The failed direct Raw sink and its SQL operator have now been removed, with all
remaining Eventstream nodes Running. KQL and Raw contain the exact same 13,455
event IDs; RTI acceptance is complete.

Native OneLake availability is asynchronous; its five-minute target is not a
zero-latency guarantee. No larger-volume benchmark has been run.

## The Silver normalization fix is persisted

The earlier 305 content events carried `content.release_date` as ISO midnight
timestamps, where the contract requires a date value. Strict normalization and
SQL seven-digit timestamp handling have now been corrected/persisted, without
relaxing the contract or accepting arbitrary timestamps.

The other **13,150 events were valid**, with **zero entity-sequence conflicts**.
The first publication, `msflix-connected-events-20261007`, succeeded with
**1,002 Gold order lines**. The subsequent Oracle/BPS native-master refresh and
the automatic three-event acceptance have also completed.

## Why replay does not create another sale

- The publisher sends only rows already committed in `dbo.Outboxes`. It marks
  publication after broker ACK, not when a send is merely attempted.
- A crash after ACK but before the SQL update can replay the same event.
  `event_id` deduplication is therefore mandatory, not an optimization.
- KQL `DeduplicatedEvents()` retains one envelope per ID.
  `EventIdConflicts()` rejects conflicting content under a reused ID.
- Silver reconstructs current entity state by explicit source sequence, keeps
  tombstones and quarantines invalid/conflicting records.
- Gold counts current orders and sessions, **not state-change events**.
  Playback progress is not a new commercial order.
- The payload object and canonical `payload_json` remain available; no lossy
  string cast or fabricated message repairs a failed sink.

The current Silver implementation is a bounded replay/rebuild, not a claimed
unlimited-volume incremental engine.

## Bounded operation

The default path is `msflix-demo-worker.service` on the dedicated Oracle VM.
It checks the committed outbox every 30 seconds, publishes bounded batches and
waits for exact native OneLake coverage before refreshing Raw/Silver/Gold and
the graph. It uses managed identity and persists its checkpoint outside the
workstation. Pause/resume, recovery and full-master refresh procedures are in
the [automation runbook](DEMO-AUTOMATION.md).

For a deliberate manual recovery, the producer is independently rerunnable with
cached Entra authentication:

```powershell
py -3 services\publisher\publish.py --tenant <tenant> --server <app-sql-server> `
  --database <app-database> --namespace <namespace> --duration 120 --max-messages 1000
```

A SQL session lock prevents competing publishers. The implementation bounds
runs at 20,000 messages and 600 seconds plus the current acknowledgement wait.
Ordinary documentation refreshes should use the existing evidence, not replay
the entire retained stream.

The small acceptance condition is an exact `event_id` set across operational
outbox, deduplicated KQL and physical Raw, followed by reconciled current-state
Gold orders/amounts. A deployed item, Running sink or nonempty table alone is
insufficient.

## Implementation and references

- `services/publisher/README.md`, `services/publisher/publish.py`
- `fabric/rti/schema.kql`, `fabric/rti/reconcile.kql`, `fabric/rti.py`
- `fabric/spark_runtime.py`, `fabric/contracts.py`
- [Eventhouse OneLake availability](https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-house-onelake-availability)
- [Eventstream overview](https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/overview)
- [Warehouse and Ontology publication boundaries](WAREHOUSE-ONTOLOGY.md)
