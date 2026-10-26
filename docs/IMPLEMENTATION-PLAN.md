# MSFlix execution plan

Approved 2026-10-07. This file is the repository's implementation contract.

## Deployment target

The approved tenant/subscription are supplied as deployment parameters, not
inferred from unrelated workspaces. The subscription display name is
`<subscription-name>`.

Region: `southeastasia` (Singapore). Capacity: F16. Workspace: MSFlix.
The user authorized a region change on 2026-10-07: Germany West Central and all
three GPU-supported US regions had zero Fabric CU quota; Southeast Asia had
512 CU available. This moves the demo outside the EU. The dataset contains no
real customer identities; SAP is separately authorized as described below.
Budget: reasonable demo-sized SKUs, bounded producers, no unapproved capacity
increase. Reuse existing Azure and Salesforce authentication caches.

The original deployment below excludes SAP and financial Planning. The approved
operator subsequently authorized the [local SAP contract](#sap-pr-1-local-data-contract),
private SAP foundation and [native BPS integration](#sap-native-bps-and-warehouse-publication).
Planning remains deferred. The approved operator owns SAP through `MSFlixGold`;
the app owner owns cockpit changes and repository merges.

On 2026-10-08, the user authorized Flixy: a native Fabric Data Agent sourced from
the consolidated Gold Warehouse and business ontology, with a conversational
bubble available across the cockpit. Finish the existing deployment before
implementing Flixy. Give the agent its own folder and Task Flow task, preserving
the existing tasks and item assignments.

## SAP zero-copy serving — live delivery verified

The approved operator authorized full retirement of the 24 copied `gold.sap_*` tables and
all BPS-Gold-to-Warehouse feeding/recreation paths on 11 October 2026 and
confirmed the app owner has not implemented SAP in the cockpit. Cockpit code,
Oracle, Salesforce, shared operational facts, native mirroring and BPS
processing are outside this migration's write scope. Git push and PR creation
are authorized but pending; the app owner retains merge ownership.

The target is **BPS Gold + SQL views/inline table functions only**, not a
permanent hybrid. `sap_live` retains native source fields and surrogate keys.
The original eleven views were deployed and operator-verified on 11 October 2026.
The expanded serving layer and retirement were verified on 26 October 2026:
all **35 SQL interfaces (30 views and five inline TVFs)** and **20 expanded checks**
passed fresh post-commit readback; **24 copied tables and nine legacy views**
were retired. Native schema, non-SAP definitions and native pipeline configuration
were unchanged. Local validation recorded **339 tests with two skips**.
Live delivery is verified; Git publication/PR and Planning remain pending.
Do not infer completion from source files or this plan alone.

The new [SAP data model](SAP-DATA-MODEL.md) contains the native table/column
catalogue, facts, grains, relationships and actual cross-domain mappings.
[Visual model](assets/sap-msflix-model.html) and
[structural JSON dictionary](assets/sap-native-model.json) are shareable and
contain no extracted business rows. Native source evidence stays ignored.

Detailed [SQL interfaces and operations runbook](SAP-ZERO-COPY.md).

### Serving and retirement contract

- Expose all 22 previously copied native objects plus `I_CUSTOMER` through
  explicit projections; preserve the two original enriched examples and the
  nine business responsibilities (finance, AR/AP, balances, payments,
  invoices, subscriptions, calendar, account roles).
- Require an explicit accounting cutoff for date-dependent functions. No
  default-to-today and no fabricated `sap_publication`/run/scenario metadata.
  Filtering current BPS by a past date is not an immutable historical snapshot.
- Qualify native delete markers, surrogate/business-key agreement, source scope,
  unique grains, joins and monetary preservation before the switch.
- Retire every writer entry point, not only the CLI flag. Keep Silver/Gold
  read-only qualification and the version-1 proof consumed by `process.py`.
  `sources.sap.publish` remains the upstream Datasphere/OneLake publisher.
- Use `sources.sap.retirement.plan()` to validate the exact 24-table/nine-view
  deletion allowlist and dependencies. It cannot connect or execute SQL.
  No source BPS, shared `gold.dim_*`/`gold.fact_*`, or sap_live deletion is allowed.
- Execute scoped SQL in a transaction with a before-state, then use a fresh
  connection to read every persisted definition and query each new interface.
  On ambiguity, inspect actual state; never blindly rerun destructive DDL.
- The original CREATE-only `sap-live-views.preview.sql` is historical. The new
  versioned serving artifact is the deployment authority after validation.

### Evidence already observed before the final cutover

The retirement study compared 22 business projections with native BPS and
reproduced nine old business query results at the same explicit test cutoff.
The native scenario has 25 GL lines, 25 operational accounting items and four
invoice/credit lines; the three CRM crosswalks and three content-coverage rows
resolve once. `ORDER_ID` is null: the migration cannot create a missing
facture–commande link. The separate local TVOD/EST simulator is not deployed.

Audit found one repository Warehouse publisher (`warehouse.py`); no tracked
scheduler invokes it. The worker only executes `ddl.sql`, `load.sql`, `kpis.sql`.
Its SQL distribution is restricted to those files so SAP previews cannot be
accidentally shipped. Native B2S/S2G schedules are preserved. Published Flixy
selection has no SAP objects; its code/configuration is not changed here.
Older releases, other machines and untracked wrappers cannot be globally
revoked by this repository change; never rerun the retired version's publisher.

The live Fabric iTVF capability was exercised on 11 October 2026 in a rolled-back
SAP-only transaction. Invocation returned the 25 expected GL lines; a fresh
connection verified the probe was absent after rollback. This proves capability,
not the expanded business layer's parity or deployment.

Readback files under `.state/sap/zero-copy/` include the initial deployment,
retirement study and model evidence. Operator access is proven; consumer-specific
permissions, cockpit SAP integration and native Planning are separate work.

## Materialized deliverables

| Component | Deliverable | Acceptance |
|---|---|---|
| Infrastructure | F16, Event Hubs Standard, isolated Oracle/gateway network | Correct subscription/region and tagged resource inventory |
| Oracle | Additive reference migrations, private Oracle Free, gateway and mirror | Source/mirror row counts and insert/update/delete CDC |
| Salesforce | Objects, fictional CRM seed and supported BPS ingestion | Real records, shared identifiers, change/delete handling |
| Operational domain | Rentals, purchases, rights, playback and transactional outbox | Idempotent persisted commands, UTC expiry and no duplicate sales |
| RTI | Bounded Kafka producer, Eventstream, Eventhouse/KQL and Raw sink | Acknowledged event IDs observed in both branches |
| Raw/Silver | Separate schema-enabled Lakehouses and notebooks | Metadata, deduplication, conformed identities and quarantine |
| Gold | Warehouse DDL/load and real measures | Reconciled transaction counts and amounts, no financial invention |
| GPU | Eligibility check, enablement and benchmark | `queryinsights.exec_requests_history.is_accelerated = 1` |
| Ontology | v2 business model and supported bindings | Correct version, persisted entities/relations and instances |
| Cockpit | Premium authenticated Rayfin control/visualization app | Real data, real commands, no synthetic KPI counters |
| Flixy | Native Data Agent and global cockpit conversation panel | Actual source-grounded answers, authenticated access, source attribution and explicit errors |
| Operations | Deployment scripts, tests, evidence and start/stop runbook | Restart/replay preserves state and permissions |

## Business behavior

MSFlix is an entertainment company, not an infrastructure-dashboard brand.
Use sourced film titles, release dates, duration, genre and reusable artwork.
Record every asset's source, license and attribution. Never imply that reference
metadata grants commercial distribution rights.

Separate subscription access (SVOD), rental (TVOD) and purchase (EST). First
delivery executes rental and purchase commands with a shared operational model.
Subscription reference offers remain compatible with the later external SAP
integration, without inventing SAP subscription records.

A rental has a commercial offer, territory, currency, exact decimal amount,
purchase time, deadline for first playback and a duration after first playback.
An explicit offer policy determines expiry; do not blindly assume all providers
have identical windows. Playback cannot begin after expiry. Repeated commands
reuse an idempotency key and must not create another purchase or event.

Customer names and contact data are synthetic. Actual demonstration transactions
are persisted and propagated, but no bank charge, SAP invoice or royalty
settlement is performed.

## Execution order

1. Verify cached access, provider registration, quotas and actual SKU availability.
2. Provision capacity and create the workspace; capture discovered IDs.
3. Prepare the shared catalog/CRM/event identity contract.
4. Deploy Oracle and Salesforce independently, with additive source seeds.
5. Create operational storage, outbox and Kafka-compatible ingestion.
6. Deploy and execute Raw/Silver/Gold processing with reconciled counts.
7. Persist Ontology v2 bindings and demonstrate actual entities/relations.
8. Deploy Rayfin cockpit and connect its real control and read surfaces.
9. Verify GPU usage if approved; clearly retain an external approval blocker
   otherwise, while continuing unrelated work.
10. Run the smallest end-to-end acceptance scenario and deliver evidence.
11. Once delivery and validation are complete, commit and push the repository
    to the user-approved `https://github.com/<repository-owner>/FabricHubDemo.git`.
    Authentication caches, secrets and local operational state remain excluded.

## SAP PR 1: local data contract

On 2026-10-08 the approved operator authorized the November scenario below and
development on `work/sap-data-contract`. This authorization is **local only**: no
Azure/Fabric deployment, source-system mutation, automatic PR publication or merge. The
eventual SAP BPS item will be separate from Salesforce, under `02bis SAP BPS`;
neither that item nor the folder is created by this code.

The architectural responsibilities remain:
Salesforce supplies customers/marketing; Oracle supplies catalog/offers/reference
distributors; RTI supplies persisted orders/playback; SAP supplies subscriptions,
billing, distributor contracts and financial data. The generator does not invoke
any of those services. It consumes a small, dated reference fixture rather than
pretending to have a live CRM or catalog connection.

### Run locally

From the repository root, use Python 3.12 or later:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r sources\sap\requirements.txt
.\.venv\Scripts\python.exe -m sources.sap
.\.venv\Scripts\python.exe -m unittest discover -s tests\sap -p "test_*.py"
```

The default output is `.state\sap\november-2026-v1`. Optional inputs:

```powershell
.\.venv\Scripts\python.exe -m sources.sap `
  --config sources\sap\scenario.example.json `
  --references sources\sap\references.json `
  --output .state\sap\november-2026-v1
```

Only child directories of this repository's ignored `.state\sap` or `.local\sap`
are accepted as output. There is no overwrite/reset option. A byte-identical
rerun returns `unchanged` without replacing existing files; modified or incomplete
output is rejected. Use a new directory for a changed scenario or different
Parquet writer version. The package is prepared in a sibling temporary directory
and exposed only after generation succeeds.

Configuration is deliberately bounded: three distinct FR customers, exactly one
per scenario role, one EUR company, one full month and an illustrative 20% VAT
rate. Amounts/rates are decimal strings, not floats. The simulation month must
follow the reference observation. Company `1710` is a local SAP-format identifier
for fictional MSFlix Europe, not an assertion about a deployed SAP company.
A half-payment is rounded to cents and must remain strictly between zero and the
invoice total. Zero VAT after rounding is retained in billing data without a
zero-valued journal posting. Subscription IDs derive from the bounded SAP customer
identifier; the complete CRM key remains in the crosswalk.

### Actual references versus simulated business

`references.json` records the bounded read on 8 October 2026 and the source Gold
publication. It contains fictional MSFlix CRM customers `MSF-C0001`, `MSF-C0005`,
`MSF-C0009` and their actual Salesforce record identifiers, plus the existing
`MSF-FILM-BUNNY`, `MSF-FILM-SINTEL`, `MSF-FILM-SPRING` catalog keys.

Oracle's only distributor in this sample is `BLENDER-FOUNDATION`; its
`SAP_PARTNER_CODE` is null. The generated supplier is **MSFlix Demo Content
Partner (fictional)**. `ZMSF_RIGHTS_COVERAGE` preserves catalog provenance but
marks every contractual association `SIMULATION_ONLY=X`. This is not a claim
that Blender signed an agreement or that the fictional supplier owns rights.
No Oracle partner mapping or catalog record is changed.

The new **MSFlix Essentiel FR** formula provides modeled SVOD access to the three
films during November. Its coverage uses half-open date intervals:
`2026-11-01 <= date < 2026-12-01`. Subscriptions have a manual-next-period renewal
policy; automatic renewal, proration, cancellation workflows, dunning, DRM and
subscription playback commands are not implemented. Existing October TVOD/EST
orders, prices and rights remain unchanged. Their price tax basis is unknown,
so the generator neither reinterprets nor rebills them.

### Approved accounting scenario

All dates and transactions below are simulated. The isolated scenario begins
with zero balances; it is not the company's historical financial statement.

| Date | Event | Amount |
|---|---|---|
| November 1 | Three subscription invoices; net initially deferred | 36.00 TTC = 30.00 HT + 6.00 VAT |
| November 2 and 3 | First two customers pay | 24.00 received |
| November 15 | Credit to the second customer | 2.40 TTC = 2.00 HT + 0.40 VAT |
| November 16 | Credit refunded | 2.40 paid |
| November 30 | Completed service recognized | 28.00 net revenue |
| November 30 | Content fee: 8.00 fixed + 20% of net billings after credits | 13.60 HT + 2.72 VAT = 16.32 TTC |
| November 30 | Half of supplier invoice paid | 8.16 paid; 8.16 outstanding |

Closing balances: customer receivable **12.00**, supplier payable **8.16**, net
bank movement **13.44**, net VAT liability **2.88**, content contribution
**14.40**. That contribution excludes all other costs and is not company profit
or per-film margin. There is no fabricated film-level allocation.

Ten FI documents contain 25 lines. GL and operational AR/AP are **two projections
of those same lines**, never two additive revenue sources. Customer invoice and
payment items are explicitly cleared in both projections; the credit/refund
pair has its own clearing reference. The supplier partial payment and original
invoice both remain open, linked by invoice reference: their net payable is
8.16. The unpaid customer is due November 8; the supplier remainder December 30.

Local billing credit values are signed negative. Their correspondence with a
future native O2C template's sign conventions must be qualified before loading
that template; a negative line is not a second positive sale.

### Source objects and coverage

| Surface | Objects / grain | Coverage |
|---|---|---|
| Customers | `I_CUSTOMER`; `ZMSF_CUSTOMER_LINK` to CRM key and Contact ID | Standard-column subset plus explicit crosswalk |
| Suppliers | `I_SUPPLIER` | Fictional supplier, not a new Oracle master |
| Formula/subscription | `ZMSF_PLAN`, `ZMSF_SUBSCRIPTION` | Custom simulated source objects, not standard SAP CDS |
| Content contracts | `ZMSF_RIGHTS_CONTRACT`, `ZMSF_RIGHTS_COVERAGE` | Version/content/territory/usage/validity |
| Billing | `C_BILLINGDOCITEMBASICDEX_1`, `ZMSF_BILLING_LINK` | Invoice item to subscription/service period; `ORDER_ID` remains null |
| Supplier expense | FI/AP and `ZMSF_CONTRACT_CHARGE` | Fixed/variable portfolio charges; no MM goods receipt or full P2P chain |
| GL | `I_GLACCOUNTLINEITEMRAWDATA` | Company/year/document/source ledger/GL line |
| AR/AP | `I_OPERATIONALACCTGDOCITEM` | Company/year/document/item, with partner and clearing |
| Supporting data | Company, chart/accounts/texts, ledger, product, fiscal periods, `DD03ND` | Bounded references for the local contract |

The source-system identity is in the `datasphere\S4M` path. Retain it when
combining sources; SAP-native keys alone are not globally unique. Long external
keys stay in explicit crosswalks, not truncated SAP reference fields.

**This package is not native-BPS-ready.** The standard objects deliberately
contain the fields needed by this local contract, not all columns and dimensions
required by a deployed template. `contract.json` and `manifest.json` explicitly
set `native_bps_ready=false`. A later PR must compare the new native dataset
metadata, complete template columns/texts/hierarchies, register custom objects
or provide a supported separate curated path, and qualify the actual native
mirroring/Silver/Gold chain. The candidate native datasets are Finance + AR + AP,
with the required O2C billing surface; full MM/P2P is not assumed.

### Files and replay

The package contains 20 objects and six chronological checkpoints. Under each
object, the initial batch has `L` operations and an `_SUCCESS` marker written
last. Later files contain full-row `U` operations for inserted or changed records,
including clearing updates to existing invoices. `__sequence_number` is null,
matching the prior ABAP emulator; `__timestamp` is deterministic UTC per batch.
`DD03ND` describes every exported business column, with zero-padded character
keys, decimal amounts, and real date columns.

The approved scenario needs no deletes. The local writer supports key-only `X`
for nonfinancial objects, but rejects financial deletion; credit/reversal
documents are required instead. Replaying the same batch is idempotent by key.
Process batches in timestamp order, not filesystem enumeration order.

`batches.json` lists exact files and counts per checkpoint; `summary.json` gives
the closing balances, `final-snapshot.json` the final source rows, and
`manifest.json` the file hashes, writer version and scope warnings. Every
scenario has the same deterministic output under the same dependency versions.
Decimal values are strings in JSON and fixed-precision decimals in Parquet.

All deltas are generated **locally** up front for review. A future publisher must
stage them progressively to demonstrate separate live checkpoints; uploading
the complete history at once would show only the final mirrored state.

### Repository and PR boundaries

Implementation lives in `sources\sap`, with cases in `tests\sap`. Generated
files stay under ignored directories. No credentials, Azure resource IDs, live
tokens, industrial demo datasets, or old BPS deployment bindings are copied.
The old local accounting/type/Datasphere patterns are adapted without importing
their environment-dependent modules.

PR 1 prepares the local contract/generator. Later reviewed branches handle
ADLS + the dedicated SAP BPS/mirror foundation, then native Gold processing.
Warehouse Finance publication, cockpit, ontology/Flixy and Planning are outside
this local PR. No infrastructure or existing pipeline is changed.

## SAP native BPS and Warehouse publication

### Scope and current checkpoint

The dedicated `MSFlixSAP` source is `S4M`, simulated S/4HANA 2023 via SAP
Datasphere. Its resources are isolated from Salesforce in `02bis SAP BPS`;
the native BPS launcher remains at workspace root because its supported move
returned `EntityNotFound`. BPS provisioned the SAP mirror itself: do not create
a second mirror or substitute local Parquet reads for native processing.

The private ADLS account `<sap-storage-account>` has public network and shared-key
access disabled. The landing shortcut uses workspace identity. Its write role
is limited to the `datasphere` container; no existing networking was relaxed.
Azure provisioning belongs to the separate `work/sap-mirroring` change set.

Activated native datasets cover Finance, Accounts Payable, Accounts Receivable,
Order-to-Cash Billing and `MSFlixSubscriptionsAndContracts`. Four templates
provide 85 distinct standard objects; the seven `ZMSF_*` objects are explicitly
custom simulation objects registered and imported through the native BPS UI.
`native-input-v1.json` captures the standard contract and 71 applicable cube
relationships; relationships belonging to inactive facts are excluded.

The custom dataset also requires these two native fact-to-dimension relationships.
Register them with **Manage relationship** in `MSFlixSubscriptionsAndContracts`
before S2G; importing the tables alone does not create a cube configuration.

| Fact | Dimension | Join condition | Surrogate column |
| --- | --- | --- | --- |
| `ZMSF_BILLING_LINK` | `ZMSF_SUBSCRIPTION` | `SUBSCRIPTION_ID = SUBSCRIPTION_ID` | `_key_ZMSFSUBSCRIPTION` |
| `ZMSF_CONTRACT_CHARGE` | `ZMSF_RIGHTS_CONTRACT` | `CONTRACT_ID = CONTRACT_ID` and `VERSION = VERSION` | `_key_ZMSFRIGHTSCONTRACT` |

Both use join order `0`, equality predicates and no imported dimension columns
(`DimColumns = []`). Use the BPS tuple syntax for the predicates, for example
`[("CONTRACT_ID", "CONTRACT_ID", "=="), ("VERSION", "VERSION", "==")]`.
Native processing retains source-system isolation. Preserve the composite
contract/version key; joining on contract alone can multiply charges across
versions. Validate that each fact resolves to exactly one actual dimension row,
not the native `Key = -1` sentinel. Do not bypass the managed fact notebook's
required `p_cubeConfig` validation or write internal metadata directly.

The new native adapter supplies all 92 admitted business objects plus `DD03ND`,
with native columns, types, texts, calendars and financial hierarchies. The
original 20-object PR1 package is unchanged and must not be used as the native
input package. Unused standard dimensions are honestly empty, not fabricated
industrial data. Local contract coverage is not proof of successful native
Silver or Gold processing.

Checkpoint on 9 October 2026: all 478 source files were published, all 93 tables
were Replicating without mirror errors, and SQL readback showed 25 GL items,
25 operational items, four billing items, three subscriptions and two contract
charges. Billing net is EUR 28. Mirroring processed-row metrics are cumulative
events, not current table cardinalities.

The first B2S run failed repeatedly because library
`ei_common_lib-1.0.5` imports `_to_seq`, unavailable in Runtime 2.0. That owned
run was cancelled. Only the dedicated SAP environment was published to Runtime
1.3, preserving libraries and all other compute settings. The replacement manual
B2S run completed successfully. Native BPS's existing daily B2S at 10:00 UTC
started a scheduled replay during its final seconds; that exact existing run
was followed without submitting another job and is now Completed. Full SQL
qualification of the 22 Silver domain tables agrees with the approved financial
scenario and existing CRM/catalog masters. The first native S2G run stopped on
missing empty-dimension structures; the schema-only recovery below completed.
The next attempt reached the custom facts but failed because their relationships
had not yet been registered (`p_cubeConfig` was empty). Both relationships above
are now registered through native BPS. Readback confirms every in-scope fact has
a configuration; the four billing links and two charges each resolve exactly
once. The controlled S2G retry completed on 9 October at 16:09 UTC, including
the final native view notebook. Actual Gold rows, surrogate relationships and
financial totals qualified successfully; pipeline status alone is not sufficient,
because managed notebooks can capture errors without failing their job.

The first shared Warehouse publication committed at 16:20 UTC. A new SQL
connection confirmed all 22 domain tables, nine serving views, SAP lineage and
the exact qualified data fingerprints. The synthetic November 2026 case contains
10 accounting documents / 25 journal lines: EUR 28 net billings and recognized
revenue, EUR 13.60 content cost, EUR 14.40 contribution after content cost only,
EUR 12 receivables, EUR 8.16 payables, EUR 13.44 net bank movement and EUR 2.88
net VAT liability. Operational masters/facts remain at 700 customers, 305 contents
and 1,008 order lines, with the same operational publication marker.
Ignored `warehouse-qualified-v1.json` and `warehouse-persisted-v1.json` retain
the native qualification and committed readback respectively.

Runtime 1.3 is a demo compatibility recovery with lifecycle limitations, not a
production upgrade strategy. Salesforce runtime and pipelines were not changed.

### Operator sequence and rerun safeguards

Use the existing Python environment, the SAP requirements and
`fabric\requirements-deploy.txt` for declared SQL connectivity. The publication
client uses ODBC 18 when available, otherwise `mssql-python`; it does not silently
fall back to ODBC 17.

Keep source metadata captures, generated files and all job evidence under ignored
`.state\sap-native`. Copy `sources\sap\target.example.json` to
`.state\sap-native\target.local.json` only when that file does not already exist;
replace the zero `operator_id` with the approved operator's Entra object ID.
Existing authentication must match the exact tenant, operator and token audience.
No password, SAS, shared key or access token belongs in configuration or Git.
The helpers deliberately support only this provisioned MSFlix SAP source.

`native-contract-with-custom.json` is the captured admitted native metadata,
not a hand-written replacement for registration. Dataset configuration remains
through the native UI; do not mutate the internal metadata database directly.

```powershell
# Offline generation and source-publication preview.
python -m sources.sap.native `
  --metadata .state\sap-native\native-contract-with-custom.json `
  --output .state\sap-native\november-2026-native-v3
python -m sources.sap.publish `
  --target .state\sap-native\target.local.json `
  --package .state\sap-native\november-2026-native-v3 `
  --evidence .state\sap-native\publication.json

# Resume the checkpointed B2S job; do not submit another run blindly.
python -m sources.sap.process `
  --target .state\sap-native\target.local.json `
  --stage b2s --evidence .state\sap-native --apply
```

The publisher requires `--apply` to write. It commits complete files using
conditional atomic Put Blob through the OneLake shortcut, verifies the bytes,
keeps identical existing files and refuses differing files. It publishes metadata,
initial Parquet, completion markers and chronological deltas. This is a full
synthetic historical bootstrap, not a live six-day checkpoint demonstration.
Never reset or replace source files to recover a processing failure.

Accepted jobs are checkpointed before polling. A failed/cancelled native job
requires `--retry-failed-job` with its exact latest ID; an explicit completed
rerun requires `--after-completed-job`. A newer checkpoint cannot be overwritten
by retrying an old failure while native history is lagging. Ambiguous submission
is a stop condition requiring reconciliation, not permission to POST again.
Inspect child activities in the native monitor: Core job history does not
necessarily list child `ExecutePipeline` runs.

Native BPS provisioned daily B2S at 10:00 UTC and S2G at 13:00 UTC under the
approved operator. They run independently of these local wrappers. During the
empty-dimension recovery, only the daily SAP Gold schedule was temporarily paused
to avoid overlapping its retry. After committed Warehouse readback it was restored
on 9 October, preserving the same schedule ID, owner and complete configuration.
Ignored `s2g-schedule-recovery.json` retains the before/after evidence and
`state: restored`. No Salesforce or other schedule was changed.
An already-running scheduled SAP job can be explicitly followed with
`--adopt-scheduled-job` and its exact latest ID. The helper checks the live pipeline
identity and `invokeType=Scheduled`, preserves an accepted different job, and does
not POST a new run during adoption. These schedules refresh native BPS only:
SAP consumption in `MSFlixGold` now targets SQL zero-copy interfaces, not a
separate copied-table publication. No Warehouse feeding job is required.

After the latest B2S is Completed, qualify actual Silver rows and amounts:

```powershell
$b2s = Get-Content .state\sap-native\b2s-job.json -Raw | ConvertFrom-Json
$proof = ".state\sap-native\silver-qualified-$($b2s.job_id).json"
python -m sources.sap.warehouse `
  --target .state\sap-native\target.local.json `
  --processing-evidence .state\sap-native `
  --catalog $proof --run-id "<SAP_PUBLICATION_RUN_ID>" --inspect-silver
python -m sources.sap.process `
  --target .state\sap-native\target.local.json `
  --stage s2g --evidence .state\sap-native --apply
```

Silver inspection shares the full business/accounting gates, but does not
invent Gold dimension `Key` values: B2S intentionally has no such surrogates.
The job-qualified proof cannot overwrite evidence from a prior B2S run. The
local S2G runner refuses missing/mismatched proof or a newer B2S job. If SQL
metadata lags after native processing, refresh that exact SAP SQL endpoint's
metadata using the supported API/UI; do not change source tables or relax
catalog checks.

### Empty-dimension compatibility

The managed B2S ABAP notebook exits successfully on zero source rows before
materializing a typed Silver table. Its S2G dimension notebook can also return
an error in `exitValue` while the notebook/pipeline status is Succeeded.
Consequently, the first fact processing correctly failed
`CubeConfigValidationFailed` for `I_PLANT` and `I_PERSONWORKAGREEMENT_1`.
The scenario intentionally has no plants or employee work agreements.

`sources.sap.empty_dimensions` deploys the owned
`MSFlixSAPEmptyDimensionSchemas` notebook in `02bis SAP BPS`, bound to the
dedicated SAP Silver and environment. It checks the actual native mirrored
tables are genuinely empty and contain the declared business columns, then
creates **only missing typed, zero-row Silver Delta structures**. It never
creates a plant, employee, contract or journal row, never writes Gold, never
overwrites a non-Delta path/existing data, and never edits managed BPS notebooks
or internal metadata. Native S2G remains responsible for all Gold processing.

```powershell
python -m sources.sap.empty_dimensions `
  --target .state\sap-native\target.local.json `
  --evidence .state\sap-native --apply
```

The command refuses concurrent native SAP processing and checkpoints its
accepted notebook job before polling; a repeated invocation resumes that
exact job instead of submitting another. Native SQL readback confirmed both
initially repaired dimensions have **zero rows**. The version-2 adapter covers
all 12 declared empty objects, including the seven additional structures exposed
by the subsequent S2G failure. Those seven have valid Delta logs and SQL-visible
zero-row tables; the Silver catalog now contains all 92 business tables.
`DD03ND` remains source metadata, not an expected Silver business table.
If endpoint visibility lags, refresh only that SAP endpoint's metadata.
Repairing these unrelated empty structures does not change the qualified
22-table financial Silver domain.

Only then qualify native Gold:

```powershell
python -m sources.sap.warehouse `
  --target .state\sap-native\target.local.json `
  --processing-evidence .state\sap-native `
  --catalog .state\sap-native\warehouse-qualified-v1.json `
  --run-id "<SAP_PUBLICATION_RUN_ID>" --inspect-source
```

`--inspect-source` performs bounded reads only. The default mode is offline
inspection preview. Warehouse publication is retired: `--apply` and the old
Python writer entry points fail before connection or mutation. Use a new catalog
path when explicit qualification must be repeated; preserve earlier evidence.
This does not remove `--apply` from the distinct upstream publisher or BPS
processing commands.

### Shared Warehouse consumption boundary — zero-copy

The old Warehouse publisher and its `sap-ddl.sql` / `sap-views.sql` creation
paths are retired in this change. The 9 October publication remains a historical
checkpoint, not an instruction to rebuild copied SAP tables.

SAP business serving moves to `sap_live`, reading native BPS Gold in the same
workspace. Oracle/Salesforce masters are read for cross-domain reconciliation,
never rewritten by this transition. The non-SAP worker, mirroring, upstream
source publication and BPS schedules remain in place.

### SQL handoff for later cockpit integration

Use the [SAP data model](SAP-DATA-MODEL.md) and the final cutover evidence.
The synthetic source is `S4M`, company `1710`; the November scenario's accounting
cutoff is `2026-11-30`, not today's results. Date-dependent functions require an
explicit cutoff; other interfaces are views. No run/scenario/commit timestamp
is fabricated as SAP freshness. Native timestamps and successful BPS processing
are distinct from the accounting cutoff and operational `gold.publication`.

Customer mappings use shared customer keys; rights coverage uses existing
content/distributor keys. Preserve contract ID/version. The supplier and terms
are fictional. Do not infer a real distribution agreement, allocate portfolio
cost to films without a rule, or add GL revenue to its AR/AP projection or the
same commercial order as an additional revenue stream.

This transition does not deploy a semantic model, Plan, writeback, cockpit UI
or cockpit API. The app owner owns application integration and repository merges.
Infrastructure and finance remain separate reviewed change sets on
`work/sap-mirroring` and `work/sap-bps-finance`. Git publication/PR and Planning
remain pending; the upstream TVOD/EST simulator rollout remains a separate task.

## UI direction

A cinematic premium business app: restrained dark surfaces, strong film imagery,
clear editorial hierarchy, accessible controls and responsive catalog layouts.
Home: business activity and films, not Azure SKU cards. Main sections: Overview,
Catalog, Rentals & Purchases, Audiences & Campaigns, Business Graph, Operations.
Technical diagnostics live in Operations and context panels.

Real empty/loading/error states are mandatory. A failed connection is an error,
not a mock dataset. Operators can issue approved commands; viewers cannot inherit
the deployment administrator's privileges. Artwork remains legible alongside
prices, expiry and availability. Respect reduced motion and keyboard navigation.

## External gates

- GPU preview access may require the user's Microsoft approval request.
- Ontology v2 and Fabric Apps/Rayfin must actually be available in the tenant.
- BPS onboarding and a distinct Salesforce OAuth consent can need portal actions.
- Salesforce must be ingested through Business Process Solutions. The current
  CLI exports are bootstrap snapshots only, never a substitute for BPS onboarding.
- If no private-VM SKU is allowed in the target region, report the subscription
  availability constraint instead of silently changing the capacity region.
- Flixy on the Singapore capacity requires Azure OpenAI cross-region processing
  and conversation storage. The user enabled both switches on 8 October;
  their enabled state was verified. Deployment scripts did not change them.
- Microsoft currently documents an issue adding new-experience ontologies to
  Data Agents ([known issue 1987](https://support.fabric.microsoft.com/known-issues/?active=true&fixed=true&sort=published&issueId=1987)).
  Native attachment returned `OntologyAddAsDataSourceBlocked`. Flixy uses the
  supported ontology-owned GraphModel alongside Gold, explicitly labelled
  "Ontology via native graph", not direct ontology context.

## Current state

| Area | State |
|---|---|
| Repository | MSFlix implementation, cinematic README/banner and architecture present; deployment continues |
| Azure/Fabric authentication | Verified cached access |
| Salesforce authentication/API | Authorized and verified |
| Fabric capacity/workspace | F16 `<capacity-name>` and workspace MSFlix deployed in Southeast Asia |
| Private networking | Approved Fabric PE and private API/OneLake/Oracle connectivity proved from the dedicated gateway VM; public workspace access still Allow |
| Oracle source | 305 contents and 2,440 price rules loaded; Unicode titles repaired and propagated through the mirror, Gold and graph |
| Oracle gateway | `<oracle-gateway-name>` registered in tenant-default centralus; recognized by Fabric; other environment's gateway untouched |
| Oracle mirror | Five tables replicated into the mirror and Raw; insert, update and delete CDC validated |
| Salesforce/BPS | Native processed Silver provides 700 customers, 6 campaigns, 700 consents and 600 touches; all are loaded into MSFlix Gold. Optional BPS-native Touch Gold fact needs dataset relationships |
| RTI | 13,477 propagated event IDs after evening recovery; all 19 accumulated events verified in native OneLake and deduplicated Raw |
| Raw/Silver | Native Eventhouse Delta ingestion and all seven native reference inputs processed successfully |
| Gold | 1,008 order lines and 1,007 playback sessions match operational SQL after evening recovery |
| SAP | Live zero-copy verified on 26 October 2026: 35 interfaces (30 views, five inline TVFs), 20 expanded checks; 24 copied tables and nine legacy views retired. Native mirror/BPS and non-SAP assets preserved. Local validation: 339 tests, two skips. Git publication/PR and Planning pending; cockpit SAP integration pending. |
| Ontology v2 | Gold bindings and 10-entity/12-relationship physical graph published; real GQL paths verified |
| Rayfin cockpit | Cinematic home, Gold business views, interactive graph and bounded Demo tab deployed; recovered licensed images and current-event ordering published |
| Film imagery | All 82 known licensed files cached; 47 films have a genuine still or poster. Other image categories are explicitly labelled; full film-specific coverage requires more rights-cleared assets |
| Demo propagation | Managed-identity worker active, enabled and unpaused; transient connection timeouts now recover with bounded durable backoff. The blocked cycle resumed without new orders/replay, 19 existing events propagated, then an idle cycle completed |
| Flixy | Native agent and global cockpit bubble deployed; authenticated answers match independent Gold counts and return real graph relationships; dedicated folder and 9-task/12-connector/47-assignment Task Flow persisted |
| GPU | No accelerated queries observed; Microsoft limited-preview enablement remains an external gate |
