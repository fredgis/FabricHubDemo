# MSFlix analytics workstream

## Current result

**Local authoring only. No Fabric items, notebook jobs, warehouse loads,
Eventstream ingestion, ontology instances or GPU results have been executed or
claimed successful.** The user explicitly revised the approved target to
**Southeast Asia (Singapore)** on the same tenant/subscription after Germany West
Central, East US, East US2 and South Central US showed quota **0**. Southeast Asia
has reported quota **512 CU**; the parent is deploying F16 **`msflixf16sea`** and
streaming resources in **`rg-msflix-demo-sea`**. Workspace/connection IDs are not
yet supplied, and provisioning success remains unverified here. This workstream
does not provision capacity, select another existing tenant capacity, or create
the workspace.

Authorized tenant: `1e45d0cb-b0dd-408c-8806-58b447605e96`.
Authorized subscription: `ce9dbfdd-c341-4e8d-a1fa-51617c74c3eb`.
Supply these as configuration parameters; neither is a code default.
The external `fabric/target-policy.json` pins the revised authorization boundary
and rejects other tenants, subscriptions, regions, resource groups and capacities.
Root implementation documents still describe the original Germany target; this
explicitly approved update supersedes that region for these owned analytics
artifacts. The parent owns updating root/the broader plan.
SAP, Planning and Data Agent are excluded.

Only `fabric/`, `tests/fabric/`, and this document belong to this workstream.
No commits are created. Source seeding, the operational worker, Azure resources
and cockpit remain the parent's responsibility.

## Artifacts

| Path | Responsibility |
|---|---|
| `fabric/contracts.py`, `fabric/event.schema.json` | Executable envelope/state contracts; exact integer money, UTC, natural keys, tombstones and conflict gates |
| `fabric/notebooks/MSFlixRaw.ipynb` | Valid Jupyter/Fabric metadata; bootstrap managed `raw` schema and ingest real staged catalog/CRM/reference exports |
| `fabric/notebooks/MSFlixSilver.ipynb` | Reconstruct latest state; managed entities, retained tombstone state, quarantine, relationship tables and publication gate |
| `fabric/spark_runtime.py`, `fabric/build.py` | Notebook runtime source and deterministic offline artifact build |
| `fabric/gold/{ddl,load,kpis}.sql` | Seven conformed dimensions, current order-line/session/conversion facts, atomic Warehouse load and read views |
| `fabric/rti/eventstream.template.json` | AzureEventHub source; processed KQL raw branch and full-payload Raw Lakehouse branch |
| `fabric/rti/schema.kql` | Raw envelopes, JSON mapping, bounded retention/cache, dedup/conflict and run-ID functions |
| `fabric/rti.py` | Exact parent event-type mapping into current-state KQL functions; definition renderer and Kusto management |
| `fabric/ontology/ids.json` | Persisted generation-2 logical/lineage IDs; never regenerated into different identities |
| `fabric/ontology/definition/` | TMDL database/model, entities, typed properties, DirectLake backing tables, junction-backed business relationships |
| `fabric/deploy.py`, `rest.py`, `sql.py` | Modular, parameterized, attributed deployment; ownership/target checks, LRO/job handling, SQL and reconciliation |

### Data correctness

* One current order line per `order_id` for the initial demo; one session per
  `session_id`. Gold never sums state-change events.
* Deduplicate `event_id`; reject conflicting event IDs and conflicting
  `(entity, entity_key, source_sequence)` values. Higher sequences win regardless
  of delivery time. Do not reset sequences on producer restart.
* Deletion is an exact configured delete-event type or boolean
  `payload.is_deleted=true`. Key-only delete payloads are supported. Tombstones
  remain in managed `silver.state_*`; active `silver.*` excludes them.
* Partial reference exports upsert by natural key. **Only** an explicitly complete,
  valid reference snapshot permits absence-based deletion. Its missing historical
  keys materialize as tombstones. A complete snapshot cannot also own an entity
  fed by sequenced events without a source watermark contract; the config rejects
  that ambiguity.
* Reference ingestion skips already completed `(entity, run_id)` batches; use a
  new run ID for a genuinely new export. Event history is retained and replayable.
* Silver is a bounded full replay/rebuild (default 100,000 events), not a claimed
  untested streaming incremental engine. This deliberately avoids event-time
  watermarks losing delayed events. Reference ingestion and Delta upserts are
  replay-safe. For larger production volumes, add an explicit sequence/cursor
  checkpoint and archival strategy before raising the bound.
* Invalid records are persisted in Raw/Silver quarantine. Default rejection
  threshold is zero. Unresolved relation endpoints block serving; no fabricated
  unknown members or implicit cascading deletes are inserted.
* Silver withdraws its previous publication marker before writing. Only a
  completed run republishes it; Gold and new ontology bindings require that exact
  run ID. Delta tables are not collectively transactional—**serialize writers**.
* Amounts come exclusively from `amount_minor` / `price_minor`. Configure the
  currency's minor-unit exponent; all division is decimal/integer, never float.
  KPIs remain grouped by currency. No FX conversion, bank charge, invoice,
  royalties, margin or SAP revenue is invented.
* `gold.commercial_activity` includes only parent-approved booked statuses and
  `TVOD` / `EST`. Playback is grouped by its actual status, not an assumed status
  vocabulary. Optional distributors/campaigns/conversions stay empty until real
  reference records/events exist. Catalog licensing is provenance, not evidence
  of commercial distribution rights.

## Parent interfaces to wire

Copy `fabric/config.example.json` to an external config or ignored
`fabric/config.dev.local.json`; **do not put secrets in it**.

1. Set explicit `environment` (`dev`/`test`/`prod`), tenant/subscription, and the
   approved F16 `capacity_resource_id` after infrastructure actually exists.
   The capacity must be tagged MSFlix and active in Southeast Asia, with exact
   name `msflixf16sea` in `rg-msflix-demo-sea`.
   Optional `workspace_id` is validated against the name/capacity; otherwise
   the deployer discovers the single exact MSFlix workspace.
2. Provide a real Fabric AzureEventHub cloud `eventhub_connection_id`, the actual
   `eventhub_namespace`, topic `msflix-events`, and a dedicated existing consumer
   group such as `msflix-fabric`. Connection credentials remain in Fabric.
   The deployer checks the nonsecret connection type/path; it never retrieves keys.
   Use the parent's new Southeast Asia connection, not the temporary Germany Event
   Hubs instance, which the parent is cleaning up after regional deployment.
   The RTI stage checks the actual namespace's ARM region in `rg-msflix-demo-sea`
   before authoring Fabric topology; temporary Germany ingress is rejected.
3. **Payload preservation requirement:** keep the specified `payload` object and
   also emit `payload_json = json.dumps(payload, sort_keys=True,
   separators=(",", ":"), ensure_ascii=False)`. Set
   `producer_payload_json_mirror=true` only after the producer is wired and tested.
   Eventstream cannot safely cast arbitrary records to text for a Lakehouse sink.
   The KQL branch stores the original object; the Lakehouse SQL operator stores
   the identical JSON string as `payload`, retaining all envelope fields.
   There is no silently lossy fallback.
4. Supply **exact** `event_entity_map` entries mapping the worker's real event
   names to `content`, `customer`, `offer`, `rental`, `playback`, `distributor`,
   `campaign`, or `campaign_conversion`. Supply exact `delete_event_types`.
   No event-name guessing is implemented. Events must contain complete current
   state, not deltas/patches; all natural keys are strings. Outbox envelopes are
   ingress, not an additional fact. Control commands must not map to rental sales.
5. Stage `data/catalog.json` and `data/customers.json` in actual OneLake Files or
   supply real Parquet/Delta mirror/export paths via `sources`. Local Windows
   files are not accessible to remote Spark. Example source configuration:

   ```json
   {
     "sources": {
       "content": {
         "path": "Files/ingress/catalog.json",
         "format": "json",
         "multiline": true,
         "snapshot_complete": true
       },
       "customer": {
         "path": "Files/ingress/customers.json",
         "format": "json",
         "multiline": true,
         "snapshot_complete": false,
         "column_mapping": {"salesforce_id": "salesforce_source_id"}
       }
     }
   }
   ```

   `column_mapping` is explicit original-to-contract naming, not a fake source-ID
   generator. Use the parent seed's actual ID field. JSON arrays and Parquet/Delta
   table paths are supported. Optional `events_path` is a real NDJSON outbox/replay
   file path; do not use it as a substitute for a claimed healthy Eventstream.
6. Source content fields: `content_key,title,release_date,duration_seconds,genre,
   image_url,source_url,license,attribution`; preserve the parent's actual Blender
   metadata/provenance. Reference strings are scalar; integer fields stay integers.
   Source customer fields: `customer_key,name,territory,salesforce_source_id`
   (actual Salesforce ID when seeded). Optional `distributor_key` joins only to
   a supplied distributor reference.
7. Operational field contracts match `Content`, `Customer`, `Offer`, `Rental`
   and `Playback` from the implementation plan. Canonical offer categories are
   `TVOD`, `EST`, `SVOD`; TVOD needs positive `start_window_hours` and
   `play_window_hours`. Required currency/status/time fields are not synthesized.
   If the worker uses other category labels, normalize them explicitly at ingress.
   `campaign_conversion` requires a real `conversion_key,campaign_key,customer_key,
   order_id,converted_at`; campaign attribution is not inferred from chronology.
8. Provide a nonempty `commercial_statuses` list from actual persisted order
   semantics, `currency_exponents`, and the explicit scenario `run_id`.
   Serialize source processing, Silver publication, Gold load and ontology
   binding/refresh. The cockpit should read Gold views, current KQL functions or
   qualified ontology instances—not quarantine/state-change totals.

## Commands

Run from the repository root:

```powershell
python -m pip install -r fabric/requirements-test.txt
python -m fabric.build
python -m unittest discover -s tests/fabric -v
python -m compileall -q fabric tests/fabric
```

Standalone SQL automation additionally needs ODBC Driver 18 for SQL Server,
`python -m pip install -r fabric/requirements-deploy.txt`, and TCP 1433 access.
It obtains tenant-specific SQL tokens from Azure CLI's cache; no SQL password is
accepted. For interactive agent-side execution, the Fabric SQL Endpoint MCP is
the primary surface; these files are also single-batch SQL suitable for that tool.
The standalone entrypoint is intentionally independently runnable through TDS.

After infrastructure/source prerequisites exist:

```powershell
$config = "fabric/config.dev.local.json"
python -m fabric.deploy --config $config --stage validate
python -m fabric.deploy --config $config --stage check
python -m fabric.deploy --config $config --stage foundation
python -m fabric.deploy --config $config --stage notebooks
python -m fabric.deploy --config $config --stage bootstrap
python -m fabric.deploy --config $config --stage rti
# Produce an actual persisted transaction and acknowledged bounded event batch.
# Wait at least five minutes after bootstrap before another run of the same notebook.
python -m fabric.deploy --config $config --stage process
python -m fabric.deploy --config $config --stage reconcile
python -m fabric.deploy --config $config --stage gold
# Review fabric/ontology/definition and supply explicit write approval:
python -m fabric.deploy --config $config --stage ontology --approve-ontology
```

Each invocation records **only its actual stage** in ignored
`fabric/evidence/last-run.json`. To preserve separate invocations, specify
`--evidence fabric/evidence/<stage>-<run>.json`. Evidence paths are restricted to
`fabric/`; the parent can copy real evidence to its root `.state/`.
Missing configuration, auth/permissions, failed/canceled LROs, ambiguous submissions,
unknown job states and timeouts produce exit **2**, not success.
All Fabric API requests, retries, pagination, LRO polls, job polls and definition
readbacks carry `x-ms-fabric-skill`; tokens are never written to evidence.
HTTP failures are sanitized; inspect service-side diagnostics for their details.
Recent jobs block duplicates. Do not resubmit an ambiguous write.

### Live gates still open

* **F16:** the original regions had quota 0. Southeast Asia quota is reported
  512 CU, and the parent is provisioning the now-approved `msflixf16sea`.
  Workspace/capacity IDs and actual completed provisioning remain external gates;
  no live deployment attempted by this workstream.
* **Eventstream:** actual AzureEventHub Fabric connection and consumer group,
  producer JSON mirror, source schema/runtime health and observed event IDs in
  **both** sinks must be qualified. Equal nonempty `event_id` sets for the exact
  `run_id` are required; a deployed topology is not ingestion success. Acknowledge
  eventual fan-out, not a distributed transaction.
* **Ontology v2:** current documented APIs support TMDL generation 2, but actual
  tenant rollout/permissions and instances remain unverified. The deployer refuses
  generation 1, verifies generation 2 plus entity/key/table readback, and reports
  `instances_verified=false` until separately qualified. No documented v2 instance
  refresh API has been assumed; use the tenant's supported portal refresh and
  demonstrate real instances/links before claiming end-to-end ontology success.
* **GPU:** not tested or enabled here; no accelerated-query evidence exists.
* Parent source/worker definitions were not yet available outside the copied
  Oracle reference during authoring; event names, Salesforce column naming,
  commercial statuses and real ingress paths therefore remain explicit parameters.
* The parent confirmed Rayfin native server UDFs in SDK 1.36.2. This analytics
  workstream does not implement or modify cockpit UDFs; its source contract is
  unchanged.

## Official wire-format references checked

The current docs are newer than the bundled old JSON ontology examples. The code
uses their supported generation-2 format, not `EntityTypes/.../definition.json`.

* [Ontology new definition](https://learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/ontology-definition):
  `.platform` config `2.0`, compatibility level `1000000`, typed backing
  configurations, junction relationships, DirectLake expressions and stable lineage.
* [Create Ontology](https://learn.microsoft.com/en-us/rest/api/fabric/ontology/items/create-ontology)
  and [Get Ontology](https://learn.microsoft.com/en-us/rest/api/fabric/ontology/items/get-ontology):
  `/v1/workspaces/{id}/ontologies`; read-only `properties.generation=2`.
* [Canonical Eventstream definition](https://github.com/microsoft/fabric-event-streams/blob/main/API%20Templates/eventstream-definition.json):
  read source properties, `inputNodes`, processed KQL destination ID, Lakehouse
  `schema` and sink batching directly from the official template.
* [Create Eventhouse](https://learn.microsoft.com/en-us/rest/api/fabric/eventhouse/items/create-eventhouse)
  and [Create KQL Database](https://learn.microsoft.com/en-us/rest/api/fabric/kqldatabase/items/create-kql-database):
  actual `ReadWrite` creation payload and `parentEventhouseItemId`.
* [Run item job](https://learn.microsoft.com/en-us/rest/api/fabric/core/job-scheduler/run-on-demand-item-job):
  current `/jobs/RunNotebook/instances`, not control-plane operation polling.
* [CAST limitations](https://learn.microsoft.com/en-us/stream-analytics-query/cast-azure-stream-analytics):
  no assumed record-to-JSON-text conversion in the Raw branch.

Local tests validate Jupyter and event JSON schemas, generated artifacts, bindings,
IDs, natural-key grains, exact money, replay/update/delete, conflict/quarantine
gates, target/config checks, attribution, LRO failures and bounded jobs.
They do **not** claim to execute Spark, T-SQL, KQL or the tenant's TMDL parser.

Executed local validation on 2026-10-07: **32 tests passed**, artifact rebuild and
`compileall` passed. Running the deployer's `check` stage with the intentionally
unconfigured example returned exit **2**, `live_success=false`,
`Missing/invalid required config: tenant_id`, and **zero API calls**. This verifies
fail-closed configuration behavior, not cloud readiness.
