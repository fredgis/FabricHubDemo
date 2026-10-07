# MSFlix Business Control

## Delivered application

An authenticated, charcoal entertainment-business app with six sections:
Overview, Catalog, Rentals & Purchases, Audiences & Campaigns, Business Graph,
Operations. It is not a consumer streaming clone. It reads entity data through
Rayfin `client.data` and invokes native commands through `client.functions`.
No handwritten GraphQL, fabricated KPI series, bank payment, invoices, SAP,
financial Planning or standalone Data Agent are included.

Catalog artwork is the parent's actual Blender open-film metadata, with source,
Creative Commons license and attribution shown in the catalog and spotlight.
All five supplied artwork URLs returned HTTP 200 with `image/webp`.
Agent 327 is excluded. Imported CRM names are fictional identities in actual
Salesforce Contact records, not frontend fixtures.

Controls have labels, keyboard focus, viewer-disabled commands, bounded inputs,
reduced-motion handling, and explicit loading, empty, connection and command
failure states. Revenue is calculated from persisted booked commercial rows,
grouped by currency; no currencies are added together. Pagination reads every
page or fails rather than showing partial KPIs.

## Live deployment, 2026-10-07

| Resource | Actual value |
|---|---|
| Workspace | MSFlix, `<WORKSPACE_ID>` |
| Capacity | F16 <capacity-name>, `<CAPACITY_ID>`, southeastasia |
| App item | `<APP_ITEM_ID>` |
| App URL | <https://<app-host>> |
| Portal launch | <https://app.fabric.microsoft.com/groups/<WORKSPACE_ID>/appbackends/<APP_ITEM_ID>?ctid=<TENANT_ID>> |
| App-linked SQL item | `<APP_SQL_ITEM_ID>` |
| SQL server | `<sql-server>` |
| SQL database | `MSFlix Business Control-<APP_SQL_ITEM_ID>` |
| Provisioned UDF item | `<APP_UDF_ITEM_ID>` |

The workspace's exact capacity was validated before `rayfin up`. Full
deployments completed with `status: success`, the same app item and no skipped
services. The first invocation with both workspace and capacity flags failed
local CLI validation before deployment; the successful commands used only the
exact, already capacity-validated workspace ID.

`rayfin up status --json` reports authenticated management reachability, not
proof of caller data or command health. Independently verified:

- App `__private/projectRuntimeSettings.userDbInfo.dbIdentifier` equals the SQL
  item above. This is not a database selected from broad workspace status.
- SQL item properties supplied its actual database name and server; the returned
  `,1433` suffix was removed from the driver's `server` field.
- Authenticated SQL connection, exact expected physical tables, runtime binding,
  additive constraints and serializable command transactions work.
- Runtime Functions settings are `auth.type: application`.
- Generated native runtime/deployment metadata declares `Sql` audiences.
- Protected static hosting rejects an unauthenticated HTTP request with
  `Authentication required`. Public asset access was not enabled.
- The Fabric portal app URL was launched after deployment.

### Native caller verification gate

The cached Rayfin authoring admin login remains valid and was reused. No login
or logout was performed. The current Azure CLI delegated token has the correct
tenant and Power BI audience but does not have `Item.Execute.All`. Direct SDK
Entra exchange correctly failed with `AUTH_FAILED`. Requesting only
`https://analysis.windows.net/powerbi/api/Item.Execute.All` from the existing
Azure CLI identity returned **AADSTS65002**, Microsoft first-party client/API
preauthorization. This is not a requirement for global `Tenant.ReadWrite`
roles or a reason to reset a working login.

The production UI uses the supported Fabric portal popup/embedded broker flow.
Native UDF end-user invocation and a signed-in browser screenshot are **not
claimed as verified** by the CLI checks. `tools/verify.mjs` supports a delegated
token from an approved app over stdin, keeps it in memory, and uses
`signInWithEntraToken`, `client.data`, and `client.functions`. It never bypasses
item Execute permission or server-side operator grants. Portal-broker caller
verification is the remaining app-auth gate.

## Exact physical SQL and SDK names

Rayfin CLI 1.36.2 pluralizes physical table names:

| SDK entity | Physical table |
|---|---|
| Content | `dbo.Contents` |
| Customer | `dbo.Customers` |
| Offer | `dbo.Offers` |
| Rental | `dbo.Rentals` |
| Playback | `dbo.Playbacks` |
| Outbox | `dbo.Outboxes` |
| ControlCommand | `dbo.ControlCommands` |
| Campaign | `dbo.Campaigns` |
| CampaignMember | `dbo.CampaignMembers` |
| IntegrationLink | `dbo.IntegrationLinks` |
| OperatorGrant | `dbo.OperatorGrants` |
| RuntimeBinding | `dbo.RuntimeBindings` |
| CommandReceipt | `dbo.CommandReceipts` |
| EventSequence | `dbo.EventSequences` |

Each entity has UUID primary key `id`. Shared natural string identifiers are
retained separately: `content_key`, `customer_key`, `offer_key`, `order_id`,
`session_id`, `event_id`. `order_id` and `session_id` are UUID-shaped strings,
not unrelated surrogate keys. All business entities are authenticated read-only
through DAB. OperatorGrant reads are scoped to `claims.sub == user_id`; browsers
cannot create or modify grants, prices, expiry, receipts or job statuses.

Schemas are in `apps/cockpit/rayfin/data/schema.ts`. Date decorators use SDK
`Date` types; serialized event timestamps are ISO UTC. Monetary columns are
SQL integer minor units, validated within SQL `int` bounds.

### Native UDF I/O

Context parameters are injected by the host and stripped by generated
`AppFunctionsSchema`. Do not hand-edit generated `types.ts`.

| Function | SDK `invoke` input | Output |
|---|---|---|
| capabilities | none | `{can_operate, reason}` |
| health | none | `{database, functions, outbox_pending, broker}` |
| placeOrder | `{input:{customer_key,offer_key,idempotency_key}}` | CommandResult |
| startPlayback | `{input:{order_id,idempotency_key}}` | CommandResult |
| recordProgress | `{input:{session_id,position_seconds,idempotency_key}}` | CommandResult |
| expireRentals | `{idempotency_key}` | CommandResult, at most 100 due rentals |
| requestControl | `{input:{type,limit,idempotency_key}}` | CommandResult |

`CommandResult = {entity_key, status, event_ids}`.
Control types are `simulate`, `start`, `stop`, `refresh`; limits are 1-100.
`requested` means persisted work request, not successful producer startup.

The UDF obtains authorization through caller-scoped `ctx.getDataClient()`,
then external SQL access through declared `AudienceType.Sql` and
`ctx.Tokens.Sql`. External tokens use the app owner identity. Before any write,
the SQL transaction rechecks the caller's time-bounded grant for revocation.
The runtime binding is read from the app and matched inside the SQL database.
No Azure CLI token is copied into deployed code, browser code or local settings.

**Identity limitation:** SDK 1.36.2 defines the deployed application identity as
the app item's owner, not a newly provisioned least-privilege service principal.
This demo was deployed by the cached tenant-admin owner. The code restricts SQL
access to its proven app-linked database and exposes no arbitrary endpoint or
query input, but it does not reduce that owner's underlying resource permissions.
For production, the parent must transfer deployment ownership to a dedicated
workspace-scoped identity and grant only the required SQL permissions.

### Transaction/expiry semantics

`storage.atomic` executes at SERIALIZABLE isolation:

1. Lock and recheck the enabled, unexpired operator grant.
2. Lock the unique idempotency receipt key.
3. Replay an identical command's exact persisted receipt; reject a key reused
   with different operation, parameters or actor.
4. Read the persisted offer and territory. Derive all prices/windows server-side.
5. Write the order/entitlement/playback, monotonic event sequence and full-state
   outbox records in the same transaction.
6. Write the receipt, commit; roll back everything on failure.

An offer with existing orders is immutable in the import hook. Changed terms
require a new offer key. Rental creation sets the first-start deadline from the
offer. First playback sets expiry from its play-window policy. Playback at or
after either applicable boundary is rejected. Purchase entitlements have no
rental expiry. Progress cannot be negative, fractional, decrease, or exceed
the actual film duration.

## Outbox publisher contract (parent-owned delivery)

Use `dbo.Outboxes`; do not query `dbo.Outbox`.

Columns, in addition to `id`:

```text
event_id nvarchar(128), event_type nvarchar(80), schema_version int,
entity_key nvarchar(128), source_sequence int,
occurred_at datetime2, produced_at datetime2,
run_id nvarchar(128), correlation_id nvarchar(128),
payload nvarchar(4000), payload_json nvarchar(4000),
published_at nullable datetime2
```

These types were confirmed from `sys.columns` on the actual database. Both JSON columns
contain the **same canonical full-state JSON string**. The published envelope:

```json
{
  "event_id": "<persisted-event-uuid>",
  "event_type": "rental.created",
  "schema_version": 1,
  "entity_key": "<order_id>",
  "source_sequence": 166,
  "occurred_at": "<persisted-ISO-UTC>",
  "produced_at": "<persisted-ISO-UTC>",
  "run_id": "<persisted-run-id>",
  "correlation_id": "<idempotency-key>",
  "payload": {"order_id": "<order_id>", "...": "full current row state"},
  "payload_json": "<identical canonical string from SQL>"
}
```

The example sequence is illustrative, not a live KPI. The parent must:

1. Select unpublished records ordered by `source_sequence`.
2. Parse stored `payload_json` into the envelope's `payload` object, retain the
   matching original canonical string.
3. Send to `msflix-events` in `<event-hubs-namespace>`.
4. Only after broker ACK, set `published_at=SYSUTCDATETIME()` for that event.

`apps/cockpit/tools/producer-contract.mjs` implements bounded reads and ACK
updates against an already authenticated SQL pool. Crash after ACK/before SQL
marking can redeliver; analytics must deduplicate `event_id`. No Kafka delivery
is performed or invented by the cockpit.

| Event type | Full payload / `entity_key` |
|---|---|
| content.upserted | Content fields / content_key |
| customer.upserted | Customer fields / customer_key |
| offer.upserted | Offer fields / offer_key |
| rental.created | Rental fields / order_id |
| rental.updated | Rental fields / order_id |
| rental.expired | Rental fields / order_id |
| playback.created | Playback fields / session_id |
| playback.updated | Playback fields / session_id |

Rental commercial statuses: `booked`, `active`, `purchased`, `expired`. Expired
rentals remain recorded sales. Playback statuses: `playing`, `completed`,
`expired`. No delete event or tombstone producer is implemented. Controls and
grants are never commercial facts. Reference import reruns emit events only
for changed rows, not identical repeats.

`operational.sql` creates `msflix_outbox_publisher` with only SELECT and UPDATE
on `published_at`, and `msflix_control_worker` with SELECT plus UPDATE on status,
completed_at and error. The parent must create its own Entra SQL principal and
add it to the required role. No principal was granted `db_owner` or `public`
writes by this workstream. `claimControl` atomically changes requested to running;
`finishControl` records completed/failed only after real worker execution.
Errors are redacted before persistence.

## Rerunnable imports and bound worker

From `apps/cockpit`:

```powershell
node tools/manage.mjs --binding tools/binding.live.local.json --initialize-binding `
  --catalog ../../data/catalog.json `
  --customers ../../.state/salesforce/customers.json `
  --campaigns ../../.state/salesforce/campaigns.json `
  --offer-policy tools/offers.policy.json
```

The binding file is git-ignored and externalizes actual discovered coordinates;
`binding.example.json` is deliberately unverified. Never set `verified:true`
without checking app `userDbInfo`, exact workspace/capacity, SQL item coordinates
and expected tables. The initial binding insert is explicit. Imports are
parameterized serializable transactions, bounded at 10,000 records/file.

Customer mapping: `MSFlix_Key__c` → customer_key; FirstName + LastName → name;
`MSFlix_Territory__c` → territory. Campaign mapping retains real Name/key/channel.
The supplied campaign export omits Status/StartDate/EndDate, so status is
explicitly `not_exported`, dates null; no successful campaign status or
conversion rate is invented. No campaign members export has been supplied.

`offers.policy.json` records the parent-approved demo policy:

- Keys `${content_key}:${territory}:RENTAL` and `:PURCHASE`; types TVOD/EST.
- FR/BE EUR: 399/1299 minor; CA CAD: 599/1899; CH CHF: 449/1399.
- TVOD start 720 hours, playback 48 hours. EST windows zero/no expiry.
- Five actual content keys × four territories × two categories = 40 persisted offers.

The trusted worker uses the **same** `commands.ts` and `storage.atomic` as
native UDFs, never a mocked `RayfinContext`. Its credential is server-side
DefaultAzureCredential and its actor requires an explicit existing operator
grant. It is a CLI/server interface, not a browser endpoint:

```powershell
node tools/worker.mjs --binding tools/binding.live.local.json `
  --operation placeOrder --actor-sub <existing-worker-grant> --input <command.json>
```

Supported operations: placeOrder, startPlayback, recordProgress, expireRentals,
requestControl. The input includes an idempotency_key; the worker does not
accept a price or expiry. SQL data permissions remain independent of the grant:
a publisher principal cannot execute commercial writes. Do not run a worker
with a deployment administrator identity in production.

## Actual acceptance evidence

Executed on the proven app-linked SQL database, using the bound worker/shared
native command core (not claimed as browser UDF invocation):

| Command | Persisted key | Result |
|---|---|---|
| TVOD rental | `<ACCEPTANCE_RENTAL_ORDER_ID>` | EUR 399 minor; initially booked; exact replay same order/event |
| EST purchase | `<ACCEPTANCE_PURCHASE_ORDER_ID>` | EUR 1299 minor; purchased; null rental expiry |
| Start playback | `<ACCEPTANCE_PLAYBACK_ID>` | Playing; exact replay same session/two events |

The rental created event is `<RENTAL_CREATED_EVENT_ID>`.
The purchase created event is `<PURCHASE_CREATED_EVENT_ID>`.
Playback activation produced Rental update `<RENTAL_UPDATED_EVENT_ID>`
and Playback created `<PLAYBACK_CREATED_EVENT_ID>`.

At the final SQL integrity read (`2026-10-07T11:57:36.767Z`): 5 Contents,
120 Customers, 40 Offers, 6 Campaigns, 2 Rentals, 1 Playback, 170 Outboxes,
5 CommandReceipts; zero duplicate event IDs, zero invalid or mismatching
canonical JSON payloads, zero acknowledged events. Playback progress was
persisted at 60 seconds and exact replay returned the same event
`<PLAYBACK_PROGRESS_EVENT_ID>`. The expiry sweep correctly found zero due
rentals. The rental is active: first play `2026-10-07T11:50:52.491Z`, expiry
`2026-10-09T11:50:52.491Z` (48 hours); its original first-start deadline is
`2026-11-06T11:49:33.392Z` (720 hours after booking).

An actual bound-worker command with ungranted actor `msflix:viewer` was rejected
with `Operator permission required. Viewers cannot issue commands.` It did not
create a transaction. Catalog/CRM/campaign import replay changed zero rows.
Parent delivery/analytics reconciliation remains a separate gate.

Focused verification:

```text
npm run build:fabric: TypeScript + Vite passed
rayfin/functions npm run build: passed
npm run lint: 0 errors, 1 existing AuthContext Fast Refresh warning
npm test: 4 files passed, 26 tests passed
node --check tools/manage.mjs / producer-contract.mjs / worker.mjs: passed
```

Tests cover exact minor units, first-start and play-expiry boundaries,
purchase no-expiry, unexpired/revoked operator permissions, bounded controls,
canonical JSON, full pagination and errors, serializable receipts, identical
idempotent replay, conflicting-key rejection, rollback, and UI empty/loading/
connection-error/retry behavior, and disabled commerce for viewers. These unit tests use isolated test doubles;
the production app never uses those doubles.

Dependency audit was captured without changing the version-locked SDK:
the app scaffold/toolchain reports 13 findings (2 critical, 8 high, 3 moderate);
the critical findings are Vitest/tinypool development tooling. Native functions
report 3 moderate findings in mssql/tedious/sprintf-js. Suggested automated fixes
included incompatible downgrades of Rayfin CLI and the Fabric-compatible SQL
driver, so no `npm audit fix --force` was run. A dependency maintenance pass is
required before production use; this demo is not claimed dependency-audit clean.

## Paths and ownership

- `apps/cockpit/src/pages/HomePage.tsx`: six business sections and controls.
- `apps/cockpit/src/main.css`: responsive charcoal visual system.
- `apps/cockpit/src/services/business.ts`: entity reads, pagination, currency/error helpers.
- `apps/cockpit/src/services/bootstrap.ts`: real endpoint-required auth, no mock fallback.
- `apps/cockpit/rayfin/data/schema.ts`: decorated entities/read permissions.
- `apps/cockpit/rayfin/functions/src/function_app.ts`: native UDF registrations.
- `apps/cockpit/rayfin/functions/src/commands.ts`: shared trusted business commands.
- `apps/cockpit/rayfin/functions/src/storage.ts`: SQL lifecycle/transaction/outbox.
- `apps/cockpit/rayfin/functions/src/domain.ts`: exact money/expiry/control policy.
- `apps/cockpit/rayfin/sql/operational.sql`: additive constraints/least-privilege roles.
- `apps/cockpit/tools/`: actual imports, worker, publisher adapter and SDK verification.
- `apps/cockpit/tools/deploy.mjs`: validates exact MSFlix workspace/capacity
  before invoking full CLI 1.36.2 `up`. `npm run rayfin:up` uses this guard.
- `apps/cockpit/README.md`: app-local usage and matching brand tokens.
- `tests/cockpit/`: policy, atomicity/idempotency and UI-state tests.

The scaffold's unused mock-auth implementation was removed. `npm run dev` is
now loopback frontend-only and cannot silently deploy into a default or unrelated
workspace. All production builds require the actual endpoint/environment.

No edits to root files, fabric, infra, sources, scripts or data; no commits or
subagents. Direct authoring Fabric REST calls carried `x-ms-fabric-skill: rayfin`;
SDK calls own their headers internally.

## Gold Warehouse dashboard binding (supersedes operational-summary design)

Business-dashboard summaries now use **only the actual MSFlixGold Warehouse**.
Operational SQL remains the command/order/entitlement ledger and catalog/CRM
reference directory; it is not a fallback consolidated business KPI source.
The UI explicitly labels the operational ledger separately.

Validated coordinates:

```text
Workspace: <WORKSPACE_ID>
Warehouse item/initial catalog: <WAREHOUSE_ID>
Name: MSFlixGold
Server: <warehouse-sql-server>
Capacity: existing <CAPACITY_ID> F16
```

New read-only entity **AnalyticsBinding**, physical **`dbo.AnalyticsBindings`**,
stores `binding_key=business-gold`, name, sql_server, sql_database, item_id,
workspace_id, capacity_id, verified. `tools/gold.mjs bind` verifies the exact
live Warehouse/workspace/endpoint through attributed Fabric API reads before
persisting coordinates. Verified coordinates are **not** a claim that Gold is
loaded or its views are available.

Native **`businessDashboard`** takes no caller-selected endpoint/query/input.
It obtains the configured binding through caller-scoped Rayfin data access,
matches its workspace/capacity to the actual operational app binding, and reads
Gold with declared `AudienceType.Sql` / `ctx.Tokens.Sql`. Source queries are a
closed allow-list:

- `gold.commercial_activity` (currency/category order lines and exact booked amounts)
- `gold.playback_activity` (content/status current sessions and furthest position)
- `gold.campaign_activity` (recorded campaign conversions)
- `gold.dim_customer`, `gold.dim_content` for curated dimension counts
- `gold.publication` for the last completed publication run, timestamp and order-line count

The parent-owned view contract was read from `fabric/gold/kpis.sql` and DDL
from `fabric/gold/ddl.sql`; neither file was modified. No bank/SAP margin or
forecast measure was invented. Monetary/count values cross SQL/JSON as exact
strings; UI aggregation/display uses BigInt, not floating-point totals.

Dashboard states:

- Connection/missing-view/permission failures: readable **Gold unavailable**
  error; no operational substitution.
- No `gold.publication` row: **unpublished**, no consolidated KPI values.
- Completed publication but no activity: explicit **empty** state.
- Qualified data: **ready**, with Warehouse source, exact view names, query UTC
  time and actual `gold.publication.completed_at/run_id`.

Overview business performance and campaign-performance summaries use this
surface. The app command ledger and CRM directory remain clearly operational.
Freshness does not relabel the query timestamp as a source-load timestamp.

Authoring verification uses the same reader as native UDFs:

```powershell
node tools/gold.mjs bind
node tools/gold.mjs read
```

The initial real read returned `EREQUEST` while parent Gold publication/views
were still being deployed. This is preserved as a blocker, not converted to
operational KPI success. End-user portal invocation remains separately manual.
Gold-only publication/precision and no-operational-fallback UI tests were added;
the combined suite has **42 passing tests**, native/production builds pass,
lint has 0 errors plus the existing Fast Refresh warning.

After parent applied its views/load, the same real Gold reader succeeded at
`2026-10-07T13:57:50.154Z` with state **empty**, publication
`<INITIAL_PUBLICATION_RUN_ID>`, actual publication completion
`2026-10-07T13:57:06.368Z`, published order_lines **0**, curated Content **5** and
Customer **120**. Commercial/playback/campaign view rows were empty. The validated
AnalyticsBinding was persisted in the app database. This proves the Warehouse
read path with current authoring credentials, **not** native end-user invocation
or expanded-data reconciliation. The UI does not substitute the operational
1,002 orders or 305/700 references for this empty Gold publication.

Remaining parent integration: wire/authorize its Event Hubs publisher and
control worker, qualify analytics/Ontology, then update IntegrationLink
qualification descriptions (`--links`). Four parent-provided, actually
provisioned Raw/Silver/Gold/Eventhouse links were registered with pending
qualification descriptions. The operational relationship graph is explicitly not
presented as a deployed Ontology. SAP and fake contract links remain excluded.

## Bounded persisted volume follow-up

The volume tools do **not** generate event-only traffic or invoke the frontend
50,000 times. `volume-batch.ts` uses the same `storage.atomic` serializable
operator/grant/receipt boundary as the native commands. Its input is a bounded
`BulkBatchSourceTransactions` CSV chunk containing only:

```csv
source_transaction_key,customer_key,offer_key
```

Prices, currency, start deadline, expiry, first-play policy and duration are
resolved from the actual SQL Offer/Customer/Content rows. Each chunk executes
set-based INSERT/UPDATE statements with `OUTPUT`, obtains the actual full row
states from those mutations, reserves a contiguous sequence range, inserts
canonical outbox rows in one batch, updates the checkpoint, and writes the
idempotency receipt in the same transaction. No source success or Kafka ACK is
invented.

Default profiles:

| Profile | Orders | Progress writes/order | Actual changes/order | Planned events |
|---|---:|---:|---:|---:|
| `volume.test-1000.profile.json` | 1,000 | 7 | 10 | 10,000 |
| `volume.profile.json` | 50,000 | 7 | 10 | 500,000 |

The 10 states are order creation, first-play entitlement update, playback
creation and seven strictly increasing persisted playback positions ending at
the actual film duration. Playback's final status is `completed`, earlier
positions `playing`. TVOD becomes `active`; EST remains `purchased`. These are
real persisted **demo** business commands, not a claim that a human watched
50,000 streams or a bank charged 50,000 cards. Transaction timestamps are real
commit-time UTC, not invented historical traffic.

Immutable natural order/session/event IDs derive from the run key and source
transaction key. Replaying a chunk returns its exact receipt without adding
another order or event. Reusing a batch key with changed inputs fails. The
manifest is unique across the entire run; duplicate source keys are rejected.
SQL primary/natural-key uniqueness is a further protection against overlapping
chunks.

### Run schema and operational status

New read-only Rayfin entity **VolumeRun**, physical table **`dbo.VolumeRuns`**:

```text
id,run_key,user_id,fingerprint,profile_json,source_manifest_hash,policy_hash,
status,total_orders,total_events,committed_orders,committed_events,
committed_batches,cancel_requested,lease_id,lease_expires_at,requested_at,updated_at
```

Only trusted backend tools mutate it. Run states: `paused`, `running`,
`completed`, `cancelled`. Profile/source-policy hashes are frozen. A two-minute
worker lease prevents two independent processes from owning one run; successful
chunks renew it. Cancellation is checked in the transaction and scheduler.
Completed counters and chunk receipts, not the local JSON file, are the
authoritative checkpoint. A crash after commit/before writing a local file is
safe to resume.

Read status:

```powershell
node tools/volume.mjs status --binding tools/binding.live.local.json `
  --plan tools/volume-state/<run_key>/plan.json
```

Parent SQL status:

```sql
SELECT run_key,status,total_orders,total_events,committed_orders,committed_events,
       committed_batches,cancel_requested,lease_expires_at,updated_at
FROM dbo.VolumeRuns WHERE run_key=@run_key;

SELECT event_type,COUNT(*) AS event_count
FROM dbo.Outboxes WHERE run_id=@run_key GROUP BY event_type;
```

Run receipt keys: `volume:<run_key>:batch:<index>`. All batch events use
`run_id=<run_key>` and `correlation_id=<batch receipt key>`. Event vocabulary and
envelope schema_version 1 remain unchanged; no new Control/VolumeRun event is
introduced into commercial analytics.

### Explicit parent approval and budget limits

`plan` reads actual imported sources and writes a frozen CSV/plan under the
owned, git-ignored `apps/cockpit/tools/volume-state/<run_key>/`. It creates **no
SQL business rows**. Execution requires both `--execute` and an approval JSON
matching exact run/source/policy hashes, app database, workspace/capacity,
order/event ceilings, source/storage confirmations and an unexpired approval.
The default example has `approved:false`. This prevents accidentally starting
50k volume while parent checks Salesforce DE's 5 MB source limit.

The parent confirmed source storage at 700 actual Contacts/700 Consents/600
Touches/6 Campaigns and approved **only the 1,000-order test after imports**.
The 50k profile remains unapproved; it has not run. Capacity stays existing F16.
Volume SQL does not create additional Salesforce records.

Example flow:

```powershell
node tools/volume.mjs plan --binding tools/binding.live.local.json `
  --profile tools/volume.test-1000.profile.json

# Only after the parent confirms the exact frozen plan:
node tools/volume.mjs execute --binding tools/binding.live.local.json `
  --plan tools/volume-state/<run_key>/plan.json `
  --actor-sub <existing-enabled-operator-grant> `
  --approval <explicit-parent-approval.json> --execute `
  --rate 10 --concurrency 1 --max-seconds 300 --max-pending-events 20000
```

Supported ceilings: 100k orders/profile, chunks 1-100, progress updates 1-16,
concurrency 1-2, 1-100 orders/second, at most 3,600 seconds per run segment,
pending-outbox bound 1,000-100,000 (default 20k). A publisher-backlog limit pauses
the segment instead of flooding F16. The pool itself is bounded to two
connections. Deadlock/transient retries use the **same chunk key** and are
bounded to two retries with backoff. No Azure SKU/capacity change occurs.

Cancellation: Ctrl+C/SIGTERM or create `volume-state/<run_key>/CANCEL` for a
checkpoint-preserving pause. Authorized permanent cancellation:

```powershell
node tools/volume.mjs cancel --binding tools/binding.live.local.json `
  --plan tools/volume-state/<run_key>/plan.json --actor-sub <run-owner-grant>
```

Cancellation completes in-flight atomic chunks; it does not fabricate a rollback
of already committed transactions. A revoked/expired operator grant prevents
new chunks and replay; renew only through an explicitly authorized admin.
Resuming an unchanged paused plan reads its SQL receipts and skips committed
chunks. Expired worker leases are recoverable without reinitializing the DB.

### Expanded catalog/CRM CSV and provenance contract

`manage.mjs` now accepts JSON or UTF-8 RFC-4180 CSV, BOM, quoted/multiline credits,
up to 100k records / 64 MiB, parameterized set-based chunks (`--chunk-size`, default
100, maximum 1,000). Each chunk atomically commits real reference changes and
outbox events. A failed import is safely rerunnable; identical source rows do
not emit another event. `--dry-run` validates without writes. Used commercial
offers remain immutable.

Catalog required CSV fields:

```text
content_key,title,release_date,duration_seconds,genre,image_url,source_url,license,attribution
```

Optional provenance columns, persisted and included additively in Content events:

```text
metadata_license,metadata_date_precision,artwork_available,artwork_license,
artwork_source_url,artwork_author
```

`duration_seconds` and monetary/window fields are decimal-free integers.
`artwork_available` CSV values are `true`/`false`. Unavailable assets must use
exactly `/catalog-unavailable.svg` and false; metadata-only licensing never
implies artwork or commercial distribution rights. The owned branded SVG and
visible label **Visuel non disponible** are not presented as a film photo.
Reusable artwork licenses are explicit CC BY/CC BY-SA/CC0/Public domain; ND is
rejected for cropped display. Root film/license verification remains the
parent's responsibility.

Wikidata `metadata_date_precision=source-not-qualified` is preserved. Catalog
UI renders release **year only**, with a precision warning in source details,
and does not pretend the supplied January 1 means a qualified release day.
No distributor/supplier relation is inferred for unknown Wikidata titles.

Customer CSV uses `customer_key,name,territory`, or the actual Salesforce export
fields `MSFlix_Key__c,FirstName,LastName,MSFlix_Territory__c`. Offer CSV:

```text
offer_key,content_key,territory,currency,transaction_type,price_minor,start_window_hours,play_window_hours
```

The expanded import was committed and verified: **305 Contents, 700 Customers,
2,440 Offers, 6 Campaigns**. It emitted **3,285 actual reference changes**
(305 Content updates/inserts, 580 new Customer rows, 2,400 new Offers). Total
outbox before volume acceptance: **3,455**, with the original **170 ACK-marked**.
The existing 120 Contacts and 40 Offers were not duplicated. 77 new Commons
artwork records plus the five original Blender assets are available; 223 use the
explicit unavailable asset. Consent/Touch source exports remain parent-owned;
they are not silently invented or re-created by this app importer.

At 500k outbox rows, the UI intentionally reads only the **latest 1,000 event
trail records**, labelled as a read window, not a whole-history total. Financial
KPIs still derive from all persisted commercial orders, not the window.

### Verification

`tools/volume-verify.mjs` exercised the **actual live set-based SQL** with two
eligible source transactions, 20 INSERT/UPDATE-derived full states, actual
server prices, strictly increasing completion positions and batched canonical
outbox insertion. It always rolled back; **zero live verification orders/events
were committed**. This is not a native-portal invocation claim.

The expanded suite has **39 passing tests** in 9 files: replay/conflicting-key/
rollback/revoked-grant checks, 50k/500k profile arithmetic, cancellation/resume,
runtime/backlog bounds, exact source approval, quoted CSV, truthful unavailable
artwork and UTC checkpoint timestamps, alongside existing commercial/UI tests.
Production/native builds pass; lint has 0 errors and the existing Fast Refresh
warning. The native end-user health gate remains manual; no browser polling.

Read-only actual replay of an already committed chunk:

```powershell
node tools/volume-replay.mjs --binding tools/binding.live.local.json `
  --plan tools/volume-state/<run_key>/plan.json --actor-sub <run-owner-grant> --batch 0
```

It refuses uncommitted chunks, compares exact receipts and SQL checkpoint
cardinality before/after, and reports distinct run order/event counts and
canonical payload integrity. It cannot generate new volume.

### Actual approved 1,000-order acceptance result

Run **`<VOLUME_TEST_RUN_ID>`** finished `completed`, requested at
`2026-10-07T13:39:17.858Z`, completed checkpoint updated at
`2026-10-07T13:40:56.263Z`. SQL counters: **1,000 committed orders, 10,000 committed
events, 10 committed batches**. These are actual committed SQL rows.

Run-specific outbox:

```text
rental.created     1000
rental.updated     1000
playback.created   1000
playback.updated   7000
```

Entitlement updates: **800 active TVOD, 200 purchased EST**. Playback updates:
**6,000 playing snapshots and 1,000 completed snapshots**. No rental.expired
event was fabricated.

Actual committed batch 0 was replayed twice via `volume-replay.mjs`; it returned
the same persisted 100-order/1,000-event receipt (source_sequence 3456-4455),
without changing the checkpoint. SQL confirmed **1,000 distinct created
orders, 10,000 distinct run event IDs, zero invalid canonical payloads**.

At `2026-10-07T13:42:11.988Z`, whole app SQL totals were **305 Contents,
700 Customers, 2,440 Offers, 1,002 Rentals, 1,001 Playbacks, 13,455 Outboxes**.
Artwork flags: **82 available** (5 original + 77 Commons), **223 unavailable**.
Only the original 170 events were ACK-marked at that captured time; run ACK count
was zero. No publisher delivery success is inferred from committed outbox rows.

The 50,000-order / 500,000-event profile has **not run**. Its approval gate,
source/storage confirmation and parent publisher qualification remain required.

## Final bounded deployment/readback and stop, 2026-10-07

The final already-pending guarded command was:

```powershell
Set-Location $env:USERPROFILE\repo-fabricroadshow\apps\cockpit
npm run rayfin:up
```

It returned `status: success`, `excludedServices: []`, no skipped connectors and
no warnings, targeting the same approved app/workspace/F16. No further deployment
was started after the parent's sequential-work priority correction.

Live readback:

- App `<APP_ITEM_ID>`, hosting
  <https://<app-host>>.
- Hosting management reports `deployedCodeOrigin=User`,
  `lastSuccessfulDeploymentAt=2026-10-07T14:12:10Z` (16:12:10 local).
- Active Data API schema version **10**; Functions enabled with
  `auth.type=application`; app-linked SQL remains
  `<APP_SQL_ITEM_ID>`.
- Actual UDF artifact `<APP_UDF_ITEM_ID>` metadata reports
  **deploy.status=Complete**, **resourceStatus=Ready**, **functionsKind=RAYFIN**,
  and includes `businessDashboard` with all existing seven command/health
  functions. This proves deployment/registration, not an end-user invocation.
- The completed deployment's diagnostic build records
  `index-C_Fg62fp.js` and `index-D9uCodHO.css`. A tiny post-upload cosmetic
  publication-count line was not deployed; it was removed locally rather than
  launching a prohibited additional deployment. The rebuilt current source
  now produces **those exact two asset hashes**, so source and the successfully
  uploaded frontend are coherent. The Gold empty-state test remains in place.
- All **43 tests passed** before final source alignment; the four targeted
  Gold/UI tests passed again after alignment. Production/native builds pass;
  lint has 0 errors and the existing Fast Refresh warning; scoped diff check
  passes.

Actual Gold read at `2026-10-07T14:27:00.514Z` still returned source
**MSFlixGold**, state **empty**, publication `<INITIAL_PUBLICATION_RUN_ID>` completed
`2026-10-07T13:57:06.368Z`, order_lines **0**, curated Content **5** and Customer
**120**, and no commercial/playback/campaign rows. The UI preserves that real
empty publication rather than substituting operational totals.

**Lineage remains truthful:** the imported 700-customer dataset is an actual
Salesforce **CLI-export snapshot**. It is **not** a deployed Salesforce BPS
pipeline. Mandatory BPS, Oracle private-network/gateway/mirror completion and
RTI ingestion are owned and sequenced by the parent.

End-user Fabric broker invocation remains genuinely unverified. No native-user
auth task, browser polling, new volume, 50k run, additional app feature, extra
agent or additional deployment was started for this final readback. The app
workstream stops here pending the parent's next explicit authorization.
