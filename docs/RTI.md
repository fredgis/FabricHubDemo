# RTI: committed transactions, exact event IDs

**Checkpoint: 7 October 2026; RTI is complete. Exact event-ID sets match between
KQL and physical Raw, all 13,455 IDs are present, and every remaining Eventstream
node is Running.** Silver/Gold publication is a separate parent workstream.

## The supported path being delivered

```text
Trusted command → operational SQL + transactional outbox
  → bounded Kafka publisher → Event Hubs
  → MSFlixIngress Eventstream relay
  → MSFlixEvents.RawEvents in MSFlixEventhouse
  → native OneLake availability
  → physical MSFlixRaw.raw.events_ingress
  → Silver current state → Gold Warehouse
```

**Eventstream is still required.** Direct Kafka-to-Eventhouse ingestion has not
been qualified. The failed direct Eventstream-to-Raw branch and its SQL operator
have been removed; the accepted path uses KQL native OneLake availability and
physical Raw materialization.

| Physical component | Actual identifier |
|---|---|
| Eventstream `MSFlixIngress` | `<EVENTSTREAM_ID>` |
| Eventhouse `MSFlixEventhouse` | `<EVENTHOUSE_ID>` |
| KQL database `MSFlixEvents` | `<EVENTS_KQL_DATABASE_ID>` |
| Raw Lakehouse | `<RAW_LAKEHOUSE_ID>` |
| Raw processing notebook | `<RAW_NOTEBOOK_ID>` |
| Silver processing notebook | `<SILVER_NOTEBOOK_ID>` |

Ingress uses the approved Singapore Event Hubs namespace
`<event-hubs-namespace>`, hub `msflix-events`, through the workspace-identity
connection. The Eventstream and Eventhouse family are organized in
`03 RTI Transactions`; Raw and Silver remain separate Lakehouses.

## What is actually proved

| Boundary | Latest supplied result |
|---|---|
| Operational persistence | 1,002 orders, 1,001 playbacks, 13,455 outbox events. |
| Publisher | All 13,455 actual outbox events have Kafka broker acknowledgements. |
| Eventstream → KQL | All remaining stream nodes Running; exact reconciliation includes all 13,455 acknowledged IDs. |
| KQL → native OneLake | Enabled with a five-minute target. Only 3,285 late events were initially available; retained-event replay addressed the missing history, with resulting coverage now proved at the physical Raw SQL boundary. |
| Physical Raw | SQL confirms **13,455 actual rows = 13,455 distinct event IDs** in `raw.events_ingress`; the exact ID set equals KQL. |
| Silver normalization | The 305 release-date mismatch and SQL seven-digit timestamp handling were corrected/persisted. No entity-sequence conflicts were found. |
| Gold publication | `<CONNECTED_EVENTS_RUN_ID>` succeeded with **1,002 order lines**. Native master refresh and Gold-backed Ontology qualification continue separately. |

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

The parent has now materialized KQL's native Delta output into the physical
Raw ingress table idempotently. SQL confirms 13,455 physical rows and 13,455
distinct event IDs. This is actual Raw coverage, not merely a configured policy
or nonempty shortcut. The first connected-events Silver/Gold publication has
also succeeded; subsequent native master refresh is a separate run.
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
Publication `<CONNECTED_EVENTS_RUN_ID>` now reports success and
**1,002 Gold order lines**. The newly staged Oracle/BPS master data will be
processed in a separate downstream rerun.

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

The producer is independently rerunnable with cached Entra authentication:

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
