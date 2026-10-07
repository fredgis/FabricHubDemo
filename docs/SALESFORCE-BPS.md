# Native Salesforce BPS delivery

This integration uses the **actual Microsoft Business Process Solutions (BPS)
workload**, its Salesforce OAuth connection, generated metadata database, native
pipelines, notebooks, environment and Delta Lakehouses. Salesforce CLI exports
are bootstrap snapshots only and are not evidence of BPS ingestion.

## Environment and authentication

Supply `--config` with the approved external deployment configuration, including
an explicit `environment` (`dev`, `test` or `prod`). All resource IDs remain in
the local deployment configuration and ignored `.state/bps/` evidence, not in
integration source. The configured target is checked against the repository's
deployment policy: the existing MSFlix workspace, F16, Southeast Asia.

Authentication reuses the approved administrator's Azure CLI cache. These
commands never invoke `az login`, MFA, or a browser. Every Fabric REST request,
retry and poll is attributed by `x-ms-fabric-skill`. SQL reads use ODBC 18,
`Encrypt=yes`, and an in-memory cached token for `database.windows.net`.
SQLDb connections use the discovered `properties.databaseName`; Lakehouse
connections use the actual `properties.sqlEndpointProperties.id`.

## Runtime recovery

The native BPS Bronze→Silver notebook failed while importing `_to_seq` from
`pyspark.sql.column`. Its environment was published on runtime 2.0. The notebook
was already bound to that environment and did not override its runtime.

Recovery changed **only the native BPS environment runtime to 1.3**. Published
and staging compute/libraries were compared before mutation. The
`ei_common_lib-1.0.5-py3-none-any.whl` dependency was retained; driver/executor
cores, memory, dynamic allocation, pool and Spark properties were unchanged.
The actual publication succeeded and published settings/libraries were read
back. There was no workspace-wide runtime change, capacity scaling, private
PySpark monkeypatch, or custom replacement pipeline.

Runtime 1.3 is the documented Spark 3.5 / Python 3.11 / Delta 3.2 runtime. It is
currently in the end-of-support-announced stage, not a permanent upgrade
strategy. A BPS-specific compatibility matrix was not found; actual native job
success must establish this recovery's operational acceptance.

Inspect without changing anything:

```powershell
python -m sources.salesforce.bps.runtime `
  --config fabric/config.live.local.json --system-suffix <discovered-suffix>
```

The same command with `--apply` explicitly permits the runtime-only recovery.
It refuses an active BPS stage, pending publication, differing staging settings
or library dependencies. It never republishes an already-recovered environment.
Publication evidence is `.state/bps/runtime-recovery.json`.

## Native stage execution

Run these **sequentially**, sharing the bounded F16 capacity with other work:

```powershell
$config = "fabric/config.live.local.json"
$suffix = "<discovered-suffix>"
python scripts/run_bps_stage.py --config $config --system-suffix $suffix --stage extraction
python scripts/run_bps_stage.py --config $config --system-suffix $suffix --stage silver
python scripts/run_bps_stage.py --config $config --system-suffix $suffix --stage dimensions
python scripts/run_bps_stage.py --config $config --system-suffix $suffix --stage facts
```

The runner discovers an **exact native name plus suffix**, verifies the latest
prerequisite jobs, rejects concurrent native stages, checkpoints the accepted
job ID immediately, and polls without submitting another job. The default
deadline is 30 minutes; `--timeout-seconds` can reduce it. Completed runs are
read back and reused, not rerun. An ambiguous submission blocks further POSTs.
A failure/deadline is not recorded as successful data verification.

For a justified incremental rerun (for example after adding the missing native
dataset objects), acknowledge the **exact latest completed job ID**:

```powershell
python scripts/run_bps_stage.py --config $config --system-suffix $suffix `
  --stage extraction --after-completed-job <latest-completed-job-id>
```

Use the same acknowledgement for downstream stages when their previously
completed output must be updated. Do not rerun the already-completed extraction
merely to recover the Spark processing environment.

## Actual data and parent handoff

The active native dataset includes `Contact`. Native Bronze contains **720 total
Contact rows**, of which **700 are MSFlix customers**, with **700 distinct
`MSFlix_Key__c` values**, and **0 rows marked `IsDeleted`** at the initial
readback. The shared natural key is **`MSFlix_Key__c`**, not a guessed
`MSFlix_Customer_Key__c`. The 20 non-MSFlix Contact rows must not become demo
customers.

The verified Bronze output is `MSFlixSF.Contact`, under the discovered Bronze
Lakehouse `Tables/MSFlixSF/Contact`. It includes `Id`, `FirstName`, `LastName`,
`MSFlix_Key__c`, `MSFlix_Territory__c`, `IsDeleted`, `SystemModstamp`,
`_SystemName`, and `_UpdatedTimeStamp`.

Native Bronze→Silver completed successfully on 2026-10-07 at 19:47:42 UTC.
The physical Silver tables are in **`dbo`**, not the Bronze `MSFlixSF` schema.
The actual processed customer output is **`dbo.Contact`** at
**`Tables/dbo/Contact`** in the native Silver Lakehouse. Its verified live MSFlix
snapshot has **700 records and 700 distinct natural keys**; the full native
Silver table contains **721 rows**, compared with **720** in Bronze. The extra
non-MSFlix native row is excluded from the canonical customer snapshot.
Original Salesforce
field names are preserved. All 13 active native object folders and Delta logs,
plus the native checkpoint table, were observed in Silver.

Do not infer Silver/Gold schema paths from the Bronze namespace; use each
layer's actual handoff manifest.

Generate an actual output manifest without modifying BPS or the parent
`fabric/` code:

```powershell
python -m sources.salesforce.bps.inspect --config $config `
  --system-suffix $suffix --source-system MSFlixSF --dataset MSFlixCRM
```

`.state/bps/handoff.json` records all discovered native Bronze/Silver/Gold SQL
schemas, column names/types, Delta paths, real row counts, tombstone counts,
customer-key uniqueness, stage job IDs/statuses and missing business entities.
Mappings use actual observed column names. Missing tables/columns are marked
unavailable, never fabricated. Use the manifest's latest verified Silver/Gold
customer path for the parent Raw/Silver adapter; do not mix a bootstrap export
with a claimed native BPS path.

For a bounded actual-row handoff to the parent's `fabric.staging.conform_salesforce`
adapter, without modifying that adapter or writing Raw from this task:

```powershell
python -m sources.salesforce.bps.snapshot --config $config `
  --system-suffix $suffix --source-system MSFlixSF --layer bronze
```

Use `--layer silver` once its native Contact table is ready. The output is
`.state/bps/contact.<layer>.native.json`, an array with the original Salesforce
field names, plus `contact.<layer>.provenance.json` with its actual source path,
SQL endpoint and count. Rank by latest Salesforce `Id`/`SystemModstamp` before
excluding tombstones; filtering tombstones first would resurrect an older
Bronze append. The snapshot contains only live `MSF-C%` customer keys and rejects
duplicate business keys. It is a SQL read of actual BPS output, never an
`sf` CLI export.

Both `contact.bronze.native.json` and `contact.silver.native.json` were actually
materialized with 700 rows in this recovery. Prefer the processed Silver
snapshot for the parent's canonical adapter. The associated provenance files
record the discovered native item IDs/endpoints, counts and read time.
The unchanged parent `fabric.staging.conform_salesforce("customer", rows)` was
executed against the actual Silver snapshot and returned **700 valid canonical
customers with 700 unique keys**.

### Bounded handoff at 2026-10-07 20:07 UTC

- Native extraction: completed; not rerun for runtime recovery.
- Native Bronze→Silver: completed, with the actual rows verified above.
- Native Gold dimensions: completed at 20:00:44 UTC.
- Native Gold facts: submitted and in progress; not yet claimed complete.
- Marketing entities below: still absent from native dataset registration.

Current job IDs/statuses are in `.state/bps/handoff.current.json`. The existing
facts runner monitors its accepted job without resubmission. This current
handoff is intentionally available before the facts pipeline finishes.

## Native marketing dataset registration and refresh

The user confirmed at **2026-10-07 22:27 +02:00** that the following tables were
added/imported through native BPS configuration into `MSFlixSF → MSFlixCRM`.
The previous registration gate is therefore resolved:

| Salesforce object | BPS type | Native primary key | Canonical business keys |
| --- | --- | --- | --- |
| `Campaign` | DIMENSION | `Id` | `MSFlix_Key__c` |
| `MSFlix_Consent__c` | DIMENSION | `Id` | `MSFlix_Key__c`, `CustomerKey__c` |
| `MSFlix_Touch__c` | FACT | `Id` | `MSFlix_Key__c`, `CustomerKey__c`, `CampaignKey__c` |

The Microsoft-documented action used for this registration is:

1. In the existing BPS item, open **Datasets / Set up your datasets**.
2. Expand **MSFlixSF → MSFlixCRM**.
3. Select **Import tables**. Select an existing table if available; otherwise
   select **New Table**.
4. Add the exact three API object names above, set their type and key `["Id"]`,
   enable delta processing, and **Save**. Keep the existing dataset activated.
5. Confirm the objects appear enabled/in-scope in native metadata. The native
   metadata population step must discover their actual Salesforce fields.
6. Resume the native extraction, Silver, dimensions and facts stages using the
   runner's explicit completed-job acknowledgements, then regenerate the
   manifest.

The complete field requirements and optional touch-to-Contact/Campaign native
relationships are in `sources/salesforce/bps/dataset-extension.json`. Custom
business objects already exist in Salesforce; they must be admitted through
native BPS dataset configuration, not replaced with Salesforce exports.

The earlier automation gate was that public `getDefinition` for the actual BPS workload item returns HTTP 400
`OperationNotSupportedForItem`. A supported dataset REST configuration surface
was not found, and the saved portal state is at an interactive authentication
gate. No new browser/login/MFA was attempted. Direct writes to
`extractionMetadata` or other private workload metadata are intentionally not a
supported substitute. Evidence is `.state/bps/dataset-api-gate.json`.

The approved follow-up deliberately reruns native extraction, Silver,
dimensions and facts once each, using exact completed-job acknowledgements and
the runner's active-job guard. Marketing snapshots are emitted immediately
after extraction, without waiting for the final facts pipeline:

```powershell
python -m sources.salesforce.bps.snapshot --config $config `
  --system-suffix $suffix --source-system MSFlixSF --layer silver --entity campaign
python -m sources.salesforce.bps.snapshot --config $config `
  --system-suffix $suffix --source-system MSFlixSF --layer silver --entity consent
python -m sources.salesforce.bps.snapshot --config $config `
  --system-suffix $suffix --source-system MSFlixSF --layer silver --entity touch
```

Stable parent handoff files are `.state/bps/campaign.silver.native.json`,
`consent.silver.native.json`, and `touch.silver.native.json`, with matching
`.provenance.json` files. If actual Bronze rows are handed off while processing
continues, provenance explicitly records `layer: bronze` and
`processed_silver: false`; the filename alone is not a lineage claim. The
bounded delivery continuation replaces these files with actual processed
Silver snapshots immediately after Silver completes.

Acceptance uses the unchanged parent `conform_salesforce` adapter, exact
MSFlix-key scopes, and actual foreign keys: **6 campaigns, 700 consents,
600 touches**. Minor-unit campaign budgets remain integers and Salesforce
datetimes are serialized as explicit UTC. The reusable continuation is
`sources.salesforce.bps.delivery`; current milestones/jobs/snapshot provenance
are checkpointed in `.state/bps/marketing-delivery.json`.

## Incremental and deletion acceptance

The native extraction pipeline has `includeDeletedObjects=true`. Its initial
load appends selected objects to Bronze; subsequent extraction uses a
`SystemModstamp` watermark from the native metadata checkpoint and appends
changes. The native processing notebook deduplicates by Salesforce `Id` and
latest `SystemModstamp`, retains source-system identity, and merges the result.

Do **not** infer successful deletion propagation from `0` tombstones. A native
insert/update/delete round trip was not executed in this recovery, and the
manifest labels that acceptance as unqualified. Preserve the source tombstone
and watermark semantics when the parent consumes the native output. Inspect
the native notebook's handling of tombstones before claiming a curated delete
has been demonstrated.

## Validation and evidence

```powershell
python -m unittest discover -s tests/bps -p "test_*.py" -v
```

Tests cover exact native discovery, active/completed duplicate prevention,
single-stage capacity guardrails, prerequisite completion, ambiguous submission,
job-ID checkpointing, bounded timeouts, unchanged runtime dependencies, SQL
identifier safety, observed field mappings and truthful missing-table status.
Live evidence remains in ignored `.state/bps/`; it contains no credential
tokens. No commit or push is part of this bounded task.

## Authoritative references

- [BPS dataset configuration and custom tables](https://learn.microsoft.com/en-us/azure/sap/business-process-solutions/manage-datasets)
- [Native Salesforce extraction and processing order](https://learn.microsoft.com/en-us/azure/sap/business-process-solutions/run-extraction-data-processing)
- [Environment staging Spark compute PATCH](https://learn.microsoft.com/en-us/rest/api/fabric/environment/staging/update-spark-compute)
- [Environment publication](https://learn.microsoft.com/en-us/rest/api/fabric/environment/items/publish-environment)
- [Fabric Runtime 1.3 components and lifecycle](https://learn.microsoft.com/en-us/fabric/data-engineering/runtime-1-3)
