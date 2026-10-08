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
real customer identities; SAP cloud integration remains excluded.
Budget: reasonable demo-sized SKUs, bounded producers, no unapproved capacity
increase. Reuse existing Azure and Salesforce authentication caches.

SAP, SAP mirroring, Datasphere, simulated SAP invoices/contracts and financial
Planning are excluded from the deployed implementation described below. The
separately authorized local SAP work is described in [SAP PR 1](#sap-pr-1-local-data-contract).
SAP cloud integration and Planning remain future parts of the architecture.

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
| RTI | 13,458 propagated event IDs; the three-event automatic acceptance reached KQL, native OneLake and deduplicated Raw; all active Eventstream nodes Running |
| Raw/Silver | Native Eventhouse Delta ingestion and all seven native reference inputs processed successfully |
| Gold | 1,003 order lines and native Oracle/BPS references published; automatic acceptance order and playback reconciled |
| Ontology v2 | Gold bindings and 10-entity/12-relationship physical graph published; real GQL paths verified |
| Rayfin cockpit | Cinematic home, Gold business views, interactive graph and bounded Demo tab deployed; recovered licensed images and current-event ordering published |
| Film imagery | All 82 known licensed files cached; 47 films have a genuine still or poster. Other image categories are explicitly labelled; full film-specific coverage requires more rights-cleared assets |
| Demo propagation | Managed-identity worker active, enabled and unpaused; real Kafka ACKs, Raw/Silver/Gold publication and target graph path proved; subsequent idle cycle ran without another Spark job |
| Flixy | Native agent and global cockpit bubble deployed; authenticated answers match independent Gold counts and return real graph relationships; dedicated folder and 9-task/12-connector/47-assignment Task Flow persisted |
| GPU | No accelerated queries observed; Microsoft limited-preview enablement remains an external gate |
