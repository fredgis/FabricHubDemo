# MSFlix execution plan

Approved 2026-10-07. This file is the repository's implementation contract.

## Deployment target

The approved tenant/subscription are supplied as deployment parameters, not
inferred from unrelated workspaces. The subscription display name is
`ME-MngEnvMCAP029985-frgisber-2`.

Region: `southeastasia` (Singapore). Capacity: F16. Workspace: MSFlix.
The user authorized a region change on 2026-10-07: Germany West Central and all
three GPU-supported US regions had zero Fabric CU quota; Southeast Asia had
512 CU available. This moves the demo outside the EU. The dataset contains no
real customer identities; SAP remains excluded.
Budget: reasonable demo-sized SKUs, bounded producers, no unapproved capacity
increase. Reuse existing Azure and Salesforce authentication caches.

SAP, SAP mirroring, Datasphere, simulated SAP invoices/contracts, financial
Planning and a standalone Data Agent are excluded from this delivery.

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
    to the user-approved `https://github.com/fredgis/FabricHubDemo.git`.
    Authentication caches, secrets and local operational state remain excluded.

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

## Current state

| Area | State |
|---|---|
| Repository | MSFlix implementation, cinematic README/banner and architecture present; deployment continues |
| Azure/Fabric authentication | Verified cached access |
| Salesforce authentication/API | Authorized and verified |
| Fabric capacity/workspace | F16 msflixf16sea and workspace MSFlix deployed in Southeast Asia |
| Private networking | Approved Fabric PE and private API/OneLake/Oracle connectivity proved from the dedicated gateway VM; public workspace access still Allow |
| Oracle source | 305 contents and 2,440 price rules loaded; private source TCP reachable |
| Oracle gateway | MSFlix Oracle Gateway Fabric registered in tenant-default centralus; recognized by Fabric; other environment's gateway untouched |
| Oracle mirror | Dedicated connection/mirror deployment in progress; no snapshot or CDC success claimed yet |
| Salesforce/BPS | 700 customers, 6 campaigns, 700 consents and 600 touches exist; bootstrap exports staged; mandatory BPS ingestion not yet onboarded |
| RTI | 170 Kafka ACKs; workspace-identity reader connection created; Eventstream validation/deployment unfinished |
| Raw/Silver | Expanded reference-processing notebook jobs completed |
| Gold | Warehouse publication exists; 0 order lines until real RTI ingestion |
| Ontology v2 | Generation-two definition deployed/read back; graph instances not yet qualified |
| Rayfin cockpit | Final app deployment complete, Gold reader bound; 1,002 persisted orders and 13,455 outbox rows; native end-user invocation unverified |
| GPU | Access not yet verified |
