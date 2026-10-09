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

The original deployment below excludes SAP and financial Planning. approved operator
subsequently authorized the [local SAP contract](#sap-pr-1-local-data-contract),
private SAP foundation and [native BPS integration](#sap-native-bps-and-warehouse-publication).
Planning remains deferred. approved operator owns SAP through `MSFlixGold`; app owner owns
cockpit changes and repository merges.

On 2026-10-08, the user authorized Flixy: a native Fabric Data Agent sourced from
the consolidated Gold Warehouse and business ontology, with a conversational
bubble available across the cockpit. Finish the existing deployment before
implementing Flixy. Give the agent its own folder and Task Flow task, preserving
the existing tasks and item assignments.

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

On 2026-10-08 approved operator approved the November scenario below and development on
`work/sap-data-contract`. This authorization is **local only**: no Azure/Fabric
deployment, source-system mutation, automatic PR publication or merge. The
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
publication into `MSFlixGold` remains an explicit, independently gated command,
not part of the operational demo worker or a newly scheduled Warehouse job.

After the latest B2S is Completed, qualify actual Silver rows and amounts:

```powershell
$b2s = Get-Content .state\sap-native\b2s-job.json -Raw | ConvertFrom-Json
$proof = ".state\sap-native\silver-qualified-$($b2s.job_id).json"
python -m sources.sap.warehouse `
  --target .state\sap-native\target.local.json `
  --processing-evidence .state\sap-native `
  --catalog $proof --run-id msflix-sap-november-2026-v1 --inspect-silver
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
  --run-id msflix-sap-november-2026-v1 --inspect-source
```

`--inspect-source` performs bounded reads only. The default mode is offline
preview. An unchanged qualified catalog, matching config/references and
Completed latest live B2S/S2G jobs are required before the same command with
`--apply` may publish. Use a new catalog path if explicit qualification must be
repeated; do not overwrite prior evidence to hide source drift.

### Shared Warehouse consumption boundary

`fabric\gold\sap-ddl.sql`, `sap-views.sql` and `sources.sap.warehouse` publish
22 dedicated `gold.sap_*` source tables and nine SAP views for Finance, current
AR/AP, payments, invoice items, subscriptions/contracts, fiscal periods and
account roles, plus `gold.sap_publication` and `gold.sap_writer_guard`.
These are separate from tables refreshed by the existing `fabric\gold\load.sql`.

All ingress is `INSERT ... SELECT` from actual native BPS Gold in the same
workspace. Local scenario totals are a reconciliation oracle, never the
ingestion payload. Native `_SystemName`, `_UpdateTimeStamp` and custom dimension
`Key` are checked; source NUMC keys and versions are reconstructed as padded
business text rather than exposed as dimension surrogates.
The two custom fact surrogates are also compared to their actual dimension
`Key`, using source-system and business keys (including contract version).
Null, sentinel, mismatched and multiplying joins block qualification. This
check runs during Gold inspection, before apply, and again inside the target
transaction. Silver qualification does not require Gold surrogates.

Publication replaces only its source/company/scenario scope transactionally,
records independent freshness and job lineage in `gold.sap_publication`, and
reconciles target rows before commit. Customer and catalog keys must agree with
existing shared masters, which are read but not mutated. GL and AR/AP remain
projections of one journal. Collections, refunds and supplier payments must
reference a non-self, same-partner, opposite-sign invoice/credit of the proper
document and account type; partial supplier payment remains open.

Fabric Warehouse rejects `SET XACT_ABORT ON`. Publication therefore uses explicit
`BEGIN TRANSACTION` / `COMMIT`, SQL `TRY/CATCH` with rollback and rethrow, and
client-side rollback on failure. No partial success or automatic retry is accepted.
The initial rejected batch left no SAP objects; the supported transaction then
published successfully.

### SQL handoff for cockpit integration

The published source is `S4M`, company scope `1710`, scenario and initial run
`msflix-sap-november-2026-v1`, with financial `as_of = 2026-11-30`. This is an
explicitly synthetic future-period demonstration, not today's production results.
The publication timestamp describes processing freshness, not the accounting date.

| Serving view in `gold` | Grain and consumption meaning |
| --- | --- |
| `sap_monthly_finance` | Company/scenario/run, calendar and fiscal period, currency; GL `0L` revenue, content expense and contribution after content cost only |
| `sap_current_balances` | Company/scenario/run at the publication `as_of`; AR EUR 12 and AP EUR 8.16 |
| `sap_ar_open_item_current` | One open customer journal item; includes `CUSTOMER_KEY` and Salesforce `source_customer_id` |
| `sap_ap_open_item_current` | Two open supplier journal items; signed amounts net to EUR 8.16, not two unpaid invoices |
| `sap_payment_journal` | Eight GL lines from four collection/refund/payment documents; not eight payments or cash-only lines |
| `sap_customer_invoice_item` | Four invoice/credit items with customer and subscription/service-period links |
| `sap_subscription_contract` | Three subscriptions with customer, plan and rights-contract version |
| `sap_calendar` | Twelve fiscal periods for variant `K4`, year `2026` |
| `sap_account_roles` | Eight GL accounts with explicit finance roles |

Every view is gated by `gold.sap_publication`. Filter source/company/scenario
explicitly; never use the operational `gold.publication` as SAP freshness.
For example:

```sql
SELECT p.as_of, p.completed_at AS sap_published_at,
       f.calendar_year, f.calendar_month, f.currency,
       f.recognized_subscription_revenue, f.content_expense,
       f.contribution_after_content_cost_only
FROM gold.sap_monthly_finance f
JOIN gold.sap_publication p
  ON p.source_system=f.source_system AND p.company_scope=f.company_scope
 AND p.scenario_id=f.scenario_id AND p.run_id=f.run_id
WHERE p.source_system='S4M' AND p.company_scope='1710'
  AND p.scenario_id='msflix-sap-november-2026-v1';
```

Contract detail is in `sap_rights_contract`, `sap_rights_coverage` and
`sap_contract_charge`. Join raw SAP tables to the same publication's
source/company/scenario/run, retaining contract ID and version. Customer links
use existing `customer_key`; coverage retains existing `content_key`.
The supplier and rights terms are fictional. Do not infer a real distributor
agreement, allocate portfolio content cost to individual films, or label the
EUR 14.40 contribution as whole-company profit. Never add GL revenue to the
same journal's AR/AP projection or to existing operational order revenue.

This change does not deploy a semantic model, Plan, SAP writeback, cockpit UI
or cockpit API. app owner owns integrating this published SQL contract into the
cockpit. Infrastructure and finance code are reviewed as separate change sets on
`work/sap-mirroring` and `work/sap-bps-finance`; app owner owns merges.
Planning remains deferred.

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
| Fabric capacity/workspace | F16 <capacity-name> and workspace MSFlix deployed in Southeast Asia |
| Private networking | Approved Fabric PE and private API/OneLake/Oracle connectivity proved from the dedicated gateway VM; public workspace access still Allow |
| Oracle source | 305 contents and 2,440 price rules loaded; Unicode titles repaired and propagated through the mirror, Gold and graph |
| Oracle gateway | <oracle-gateway-name> registered in tenant-default centralus; recognized by Fabric; other environment's gateway untouched |
| Oracle mirror | Five tables replicated into the mirror and Raw; insert, update and delete CDC validated |
| Salesforce/BPS | Native processed Silver provides 700 customers, 6 campaigns, 700 consents and 600 touches; all are loaded into MSFlix Gold. Optional BPS-native Touch Gold fact needs dataset relationships |
| RTI | 13,477 propagated event IDs after evening recovery; all 19 accumulated events verified in native OneLake and deduplicated Raw |
| Raw/Silver | Native Eventhouse Delta ingestion and all seven native reference inputs processed successfully |
| Gold | 1,008 order lines and 1,007 playback sessions match operational SQL after evening recovery |
| SAP | Native Datasphere mirror and BPS Silver/Gold processed; 22 domain tables and nine views published into MSFlixGold for the synthetic November finance case; native schedules restored, Warehouse refresh explicit |
| Ontology v2 | Gold bindings and 10-entity/12-relationship physical graph published; real GQL paths verified |
| Rayfin cockpit | Cinematic home, Gold business views, interactive graph and bounded Demo tab deployed; recovered licensed images and current-event ordering published |
| Film imagery | All 82 known licensed files cached; 47 films have a genuine still or poster. Other image categories are explicitly labelled; full film-specific coverage requires more rights-cleared assets |
| Demo propagation | Managed-identity worker active, enabled and unpaused; transient connection timeouts now recover with bounded durable backoff. The blocked cycle resumed without new orders/replay, 19 existing events propagated, then an idle cycle completed |
| Flixy | Native agent and global cockpit bubble deployed; authenticated answers match independent Gold counts and return real graph relationships; dedicated folder and 9-task/12-connector/47-assignment Task Flow persisted |
| GPU | No accelerated queries observed; Microsoft limited-preview enablement remains an external gate |
