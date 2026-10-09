# MSFlix Business Control

## Delivered application

An authenticated, charcoal entertainment-business app with eight sections:
Overview, Catalog, Rentals & Purchases, Audiences & Campaigns, Business Graph,
MSFlix Insights, Demo, and Operations. It reads published Gold business views
through native read-only functions, operational entities through Rayfin
`client.data`, and native commands through `client.functions`. Flixy connects
the floating assistant to the native Fabric Data Agent.
No handwritten GraphQL, fabricated KPI series, bank payments, invoices,
published SAP finance or financial Planning are included.

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

## MSFlix Insights

Initial release verification (historical, 2026-10-09): frontend and functions
builds passed, with 51 frontend/Flixy tests and 70 backend tests. Full `rayfin up`
publication and `rayfin up status` succeeded on the existing MSFlix app. A native
`businessInsights` read returned 503 EUR orders and 292,497 booked minor units
for October 7–8, from the October 8 Gold publication. That initial release did
not include a complete browser acceptance run or an independent direct-SQL
comparison.

Open **MSFlix Insights**, immediately below **Business Graph**, to compare
booked sales, customers and associated playback in one Gold order cohort.
A cinematic summary introduces the booked amount and cohort counts over a
licensed Big Buck Bunny backdrop. The daily trend retains its day cursor and
exact-value table, alongside playback association and Salesforce context.
**Audience atlas** maps customers and booked sales by commercial territory;
its exact-value territory buttons filter the whole dashboard. The
territory-by-genre heatmap remains available below it. The former **The films
behind the figures** ranking is removed. The screen does not generate sample
metrics or imply that the backdrop depicts the selected orders.

### Reads and filters

`client.functions.businessInsights.invoke({ filtersJson })` is the read-only
native entry point. Its typed `GoldInsights` contract lives beside the function.
The browser submits an inclusive UTC order-date window, territory, genre,
TVOD/EST transaction type, and a currency or **ALL**. Empty filters still select
the latest 30 days of the global order-date extent and the most frequent
order-line currency; the maximum window is 366 days. A single currency filters
the entire cohort, including counts and associated playback, not just money.
ALL includes every currency in the summary, curve, map and breakdowns, while
retaining the other filters. The API marker is `currency: '*'`, not the ISO
currency code `ALL` (Albanian lek). Moving a filter or the date-window slider
does not issue a request until **Apply filters**.
Heatmap cells and territory buttons apply cross-filters immediately.

The Insights reader loads on the first visit, coalesces identical in-flight
requests, ignores out-of-order responses, and retains the last successful
selection on failure. Retry repeats the attempted filters. Navigation preserves
the draft; the header refresh and timestamp belong to Insights rather than the
operational pages. A failed, empty, or unpublished Gold read never substitutes
operational activity or frontend fixtures.

### Interpreting the measures

- All matching Gold fact rows contribute to totals and daily series. The
  heatmap shows up to 12 genres. Territory results are complete within the
  supported 50-territory boundary. The heatmap limit does not cap the totals,
  daily series or territory figures.
- Map locations are order territories, not customer residences. Customers can
  buy in several territories; adding territorial customer counts does not give
  the globally distinct customer count shown above the map. Unknown or unmapped
  territories retain their figures and filter buttons.
- Customers/booked-sales shading and Europe/World controls change the local map
  presentation without new backend reads or changes to the cohort. A territory
  button applies that territory while retaining the other applied filters. The
  Mercator map uses simplified country outlines, not equal-area geometry; tiny
  territories may be absent. Exact amounts remain in the adjacent list. In a
  multi-territory World view, country-code labels appear on list hover/focus
  rather than overlapping over Europe.
- Dates select orders. Associated playback can occur later than an order and
  is not a separate session-date activity count. Recorded position describes
  progress, not time watched. RTI transactions here are published Gold facts,
  not a live Eventhouse feed.
- Booked amounts remain exact integer strings through the native response.
  A single currency uses its original minor units. ALL adds nominal amounts
  without exchange-rate conversion: each value is aligned using
  `gold.currency.minor_exponent`, then all `bookedMinor` fields use a common
  scale of 10,000 units per nominal unit. Counts remain distinct across the
  combined cohort. The UI labels ALL as nominal with no FX, uses no currency
  symbol, and preserves up to four decimals. This is not a financially
  comparable converted total. These figures are not bank receipts, invoices,
  recognized revenue, or margin.
- Contactability uses the latest effective marketing consent at publication
  among cohort customers. Campaign inventory is selected-territory/all-dates;
  touches use cohort customers and the selected date window. Conversions must
  match the selected orders and customers. Campaign activity is descriptive
  context, not causal attribution of sales.
- Each source lists its actual published Gold tables in an expandable section.
  Oracle supplies catalogue/offer context, Salesforce supplies CRM context,
  and RTI supplies order/playback facts. SAP is explicitly **Not published**
  until its contribution is present in the Warehouse. The local SAP contract
  alone is not a live connection or a financial fact source.
- Publication time is distinct from query time and is not a live source-health
  claim. Fact `run_id` values identify producers; they are not a filter for
  membership in the latest publication.

### Visual decisions

The requested MSFlix identity sets **ENERGY 2 / RHYTHM 3 / MOTION 2**: a cinema
analysis screen for operators comparing sales, audiences and playback.

| Decision | Reason |
|---|---|
| Fixed charcoal, silver and vermilion | Continue the cockpit's cinema identity; reserve vermilion for selections and analytical magnitude. |
| Segoe UI with tabular figures | Match the Microsoft/Fabric environment and keep changing numeric values aligned. |
| Licensed animated-film still beside the sales summary | Add the requested cinema character without repeating a film-card catalogue. |
| Dark image scrim; separate mobile image strip | Preserve readable numbers over the brightest photograph and keep mobile copy outside the image. |
| Summary, trend/playback, geographic map, then genre matrix | Answer amount, timing, audience location and genre questions with different compositions. |
| Local country outlines plus an exact-value list | Show distribution while keeping figures and filters accessible without precise map clicks. |
| Small control and panel radii; no glass or shadow | Distinguish controls from grouped analysis without decorative elevation. |
| Chart gradient, territory scale and playback ring | Encode magnitude and association; labels and tables remain usable without color. |
| Responsive spacing and stacked panels | Keep the content readable as the available width narrows; contain table scrolling. |
| One 1.4-second backdrop settle, never a loop | Introduce the cinematic scene once without moving values during analysis; reduced motion disables it. |
| Visible focus, 44px controls and explicit statuses | Keep the analysis operable by keyboard and touch, including empty/error states. |

### Artwork and map provenance

The backdrop reuses the locally bundled **Big Buck Bunny (2008), Blender
Foundation**, licensed [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/).
The existing optimized WebP derivatives retain their recorded attribution;
the image-credit disclosure also states the CSS cropping and darkening. This
is catalogue decoration, not a claim about the selected cohort or film rights.
An image failure removes only the decoration, leaving the real figures intact.

The 177 country outlines come from
[Natural Earth v5.1.2](https://github.com/nvkelso/natural-earth-vector/blob/v5.1.2/geojson/ne_110m_admin_0_countries.geojson),
under its [public-domain terms](https://www.naturalearthdata.com/about/terms-of-use/).
`apps\cockpit\tools\build-insights-map.mjs` generates the checked-in geometry
in `src\assets\insights-world.generated.json`; run it with Node from the app
folder to reproduce the asset. Source SHA-256:
`6866c877d39cba9c357620878839b336d569f8c662d3cfab4cb1dbe2d39c977f`.
Country lookup uses `ISO_A2_EH`, including France. Geometry is bundled locally;
viewing or filtering the map sends no business data to a map service.

### Cinema and geography verification (2026-10-09)

- **PASS, functional tests:** 27 focused tests across UI, geography, presentation,
  read lifecycle and navigation, including exact amounts beyond JavaScript's
  safe integer limit, unmapped territories, overlap and disabled cross-filters.
- **PASS, native data:** authenticated Edge at 19:57 UTC reconciled the displayed
  summary and territory amounts against `businessInsights`, with no mocked
  business response. October 9/EUR showed €79.80: Belgium and France each had
  €39.90, one customer, ten orders and ten associated sessions. CAD and CHF
  selections also returned their own amounts. This is not an independent SQL
  reconciliation or accounting-revenue assertion.
- **PASS, interaction and recovery:** keyboard-operated map controls caused no
  new native reads; selecting France retained the other filters and reconciled
  its sales. Credits opened by keyboard. A real empty date window, a deliberately
  aborted refresh, retry and an image-error event preserved honest states and
  recovered without sample data. No unexpected console errors were observed.
- **PASS, responsive/accessibility checks:** ten widths from 1440 to 320 CSS px,
  including 720px as 200%-equivalent reflow, had no page overflow or clipped
  summary/territory text. Changed controls met 44px targets. Keyboard focus had
  a 3px outline with space in the scrollable territory list, including
  forced-colors mode. Reduced motion disabled the backdrop animation.
- **PASS, computed contrast:** 31 changed-surface text, outline, focus and bar
  pairs passed their thresholds. The minimum text ratio was 5.64:1, including
  the worst-case white photograph under the summary scrim; minimum checked
  non-text contrast was 3.05:1. These are computed and browser checks, not a
  claim of a full WCAG certification.

Local screenshots and detailed results are in the ignored
`.state\insights\cinema-map` directory. The visual decisions above document the
2/3/2 design direction and each treatment's purpose; no new testimonials,
marketing claims, navigation destinations or sample metrics were introduced.

Delivery gate for the changed cinema and geography sections:

| Gate | Result and evidence |
|---|---|
| Function, truthful content and accessibility | PASS: native Gold values, real filters, licensed artwork, empty/error recovery, keyboard and responsive checks above; changed copy has no em dashes. |
| Purpose | PASS: the visual-decisions table ties the image, scrim, palette, layouts and motion to reading the analysis; no decorative glass, glow or card catalogue. |
| Character and composition | PASS: declared 2/3/2 direction, booked-sales focal point, cinema backdrop, map/list and heatmap compositions, restrained vermilion accent. |
| Craft | PASS: 27 tests, browser checks and production build; functional controls and documented limitations, without invented metrics or claims. |

Full CLI 1.36.2 `rayfin up` published this revision to the existing app with no
excluded services or warnings. Before deployment, the approved subscription's
cached identity verified the exact MSFlix workspace and capacity. This replaced
only the wrapper's failed default-account credential lookup; the default Azure
account, target checks and application access policy were unchanged.
`rayfin up status` then confirmed the expected app, authenticated management
endpoint (HTTP 200), auth and data services.

The production build produced `index-BS9y6Q5q.css` and `index-DXZSVxsn.js`.
At 20:06 UTC, a post-deployment typed native read again returned 20 orders,
two customers, 20 associated sessions and €79.80 for October 9/EUR, with Gold
publication time 19:17:50.867 UTC. Browser acceptance used local Edge connected
to that deployed backend. Direct bearer-only requests to protected static
hosting returned 401, so this evidence does not claim served-asset hash parity
or a complete hosted-browser acceptance run. Protected access was not relaxed.

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
| businessInsights | `{filtersJson: JSON.stringify(filters)}` | GoldInsights, including resolved filters, exact amounts, source tables and freshness |
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

## Demo tab — bounded native journeys, 2026-10-07

The dedicated **Demo** navigation entry preserves the existing cockpit design.
It defaults to **10 journeys**, accepts **1–100**, and runs rental, purchase,
or alternating scenarios using existing territorial offers. **Customer** keeps
the existing single-customer mode. **Random Customer** lets the operator choose
how many distinct eligible customers to simulate. Journey count remains the
total for the run, not a per-customer multiplier; every selected customer gets
at least one journey. The requested customer count cannot exceed either the
journey count or the eligible customer pool. Films are selected randomly from
catalogue offers eligible for each customer's territory and the chosen scenario.
Mixed runs with more than one total journey require both TVOD and EST offers
for every selected customer; a one-journey mixed run requires only TVOD.
Customers and offers are fixed in the immutable run plan before execution, so
retry/resume cannot draw new transactions. The default interval is one second
between sequential commands.
Each journey invokes the typed `placeOrder`, `startPlayback`, and
`recordProgress` functions. Order/session IDs come from the preceding receipt;
prices, rental rights, actor authorization, and persistence remain server-owned.

Start/resume rechecks the current caller's `capabilities`. A command failure
stops the chain visibly. Cancel stops unsent commands after the in-flight native
invocation returns; it does not roll back committed business activity.
Retry/resume retains the immutable plan, confirmed receipts, and original
idempotency keys. The page remains mounted across tab changes.

The UI displays actual entity IDs, event IDs, statuses, and retry keys.
**Generated** counts only confirmed event receipts. **Kafka ACK** uses matching
outbox `published_at` markers; missing rows in the current outbox window are
unknown, not acknowledged or assumed pending. The total pending count comes
from a read-only `health` invocation. **Gold published** shows the existing
Gold reader's last publication timestamp and matching orders/sessions in its
current window, never inferring event-level propagation from a timestamp alone.

**Refresh receipts & publication** calls `health` and the cockpit's existing
operational/Gold refresh callback. It does not start an external publisher,
execute pipeline jobs, or publish Gold. Persistent publisher integration and
live end-to-end qualification remain with the parent. This change ran only
mocked/pure tests, not a live Demo scenario, and awaits the parent's deployment
to the existing app.
# Published application update: 2026-10-07

The deployed home restores the licensed Big Buck Bunny cinematic image above
the real Gold KPIs. Purchase offers with no rental windows no longer reject the
whole Gold response. The app's native user calls to health, Gold business views
and the ontology graph succeeded; the current administrator has a time-bounded
operator grant rather than elevated permissions for every viewer.

Business Graph now renders actual ontology nodes and directional relationships
with React Flow and a Dagre layout. It supports search, 6/12/24/50-journey views,
zoom, pan, node selection and a relationship inspector. Returning to the tab
keeps the existing graph; **Refresh graph** requests fresh source data. The
default six-journey view is an explicitly labelled subset of the loaded result,
not a count of the full business.

The Demo tab is deployed with bounded real transaction commands and receipt
tracking. Its refresh action reads status; it does not itself run the Kafka
publisher or the Raw/Silver/Gold processing chain. Automatic propagation,
additional real film imagery and optional native BPS Touch fact relationship
configuration remain follow-up work.

## Published application and automatic propagation: 2026-10-08

The full cockpit update is published at the existing URL. All 82 known licensed
artwork files are cached, including 25 recovered files, and the Big Buck Bunny
hero is unchanged. This is not 82 official posters: primary presentations use
37 film stills, 10 posters, 4 labelled publicity photos, 17 labelled title
graphics and 237 honest editorial fallbacks. Fourteen unsuitable source
references remain archived. Full film-specific still/poster coverage requires
additional rights-cleared assets.

Oracle title corrections have reached Gold and the graph. The operational
outbox window now sorts by `occurred_at`, not by unrelated per-entity sequence
numbers, so recent Demo events are not hidden behind older high-sequence rows.
The published app's native user health, Gold and graph calls succeeded.

The Demo controls still execute only the authorized business commands.
Automatic propagation is supplied by the persistent managed-identity worker,
not by the browser's refresh button: committed outbox -> Kafka -> KQL/native
OneLake -> Raw/Silver/Gold -> ontology graph. At 06:19 UTC, all three existing
acceptance events had propagated, Gold contained 1,003 order lines, and actual
GQL returned the target order and playback. The worker is active, enabled and
unpaused; an idle cycle did not launch another Spark job. See
[Demo automation](DEMO-AUTOMATION.md) for operation and recovery.

The user has enabled the required Azure OpenAI cross-region processing and
conversation-storage settings. The actual Data Agent **Flixy** is published,
with Gold and the ontology's native graph as selected sources. Direct ontology
attachment is currently blocked by Microsoft, so this supported graph route
is explicit rather than hidden behind a false direct-context claim.

The new floating Flixy panel is wired to the real typed `flixyAsk` function on
every authenticated tab. It retains context while closed, supports keyboard
focus/escape, clear, retry and stop-waiting, and displays explicit service errors.
Named caller authorization prevents viewers from inheriting the app owner's
external-resource permissions. See [Flixy](FLIXY.md) for the complete source,
runtime and deployment contract.

## Interactive read and image performance

Gold metrics and page details share **one SQL connection and one query batch**.
The home page requests only its six latest orders/sessions and their related
reference rows. Catalogue, audiences and Demo use their own bounded read scopes;
the existing full `businessViews` API remains available to authoring tools.
Audience metrics reuse the same response rather than making a second query.

Operational collections load only for Orders, Demo and Operations. Their
paginated reads use batches of 5,000 rows instead of 500; the outbox remains a
bounded 1,000-event recency window. Page results live only in the mounted user's
session. A page revisit within 30 seconds reuses its last read, and **Refresh**
always requests that page again. Duplicate concurrent refreshes are coalesced.
Successful data and artwork stay visible during refresh or a read failure,
with an explicit refreshing/error notice and the original source timestamp.

Business Graph initially requests **six actual source paths**, not 50 paths
that are then hidden. Selecting 12, 24 or 50 loads the larger source sample;
reducing the display count reuses the loaded sample. Search is limited to that
sample. After the first successful Gold page read, the six-path graph is
prefetched once in the background without mounting its canvas. Opening the
graph tab reuses that actual result instead of waiting for a cold native query;
there is no polling or fabricated graph. An immediate visit before the prefetch
finishes can still wait for Fabric. Explicit refresh performs a fresh GQL query.

Interactive graph reads use the administrator-qualified `OntologyBinding` row;
the native function requires its actual `verified=true` flag and the approved
workspace before issuing a bounded, permission-checked GQL request. The browser
cannot supply or modify that binding. A full definition export is not part of
an interactive read. Rebinding the ontology or GraphModel requires requalifying
this managed binding, as with the Warehouse binding.

Standalone callers without a qualified binding still check the full definition.
Only their successful definition qualification is cached for **two minutes**,
in a bounded cache keyed by all coordinates and a hash of the exact access
token. Failures and actual graph answers are never cached.

Licensed source images and their original hashes remain unchanged. The browser
uses generated, content-hashed WebP display derivatives at up to **320, 640 and
1,200 pixels**, with responsive `srcset`, asynchronous decoding and lazy-loaded
cards. The hero image is preloaded before the Gold read finishes. The 68 licensed
primary images total **11,126,764 bytes** as originals versus **851,418 bytes**
for the small-card derivatives, a **92.3% reduction**. This is a byte-size result,
not a promise about every user's network latency. Editorial SVGs remain intact.

Run `npm run artwork:optimize` from `apps\cockpit` after updating licensed image
sources. The normal `tools\artwork.mjs` generator also rebuilds these derivatives.
`public\artwork-variants.json` preserves each original hash, license, attribution
and the declared resize/re-encoding modification.

Evening native read measurements: the Gold/home refresh went from **18.3 seconds
to 7.7 seconds**; the operational snapshot from **6.5 to 4.7 seconds**, and it is
no longer needed for the initial home view. These are observed samples, not an
SLA. A cold Fabric graph invocation can still take about **nine seconds**;
the bounded background prefetch removes that wait when its result is ready
before the user opens the graph tab.

The Demo worker's evening SQL connection-timeout incident was repaired without
creating transactions or replaying Kafka. Its original blocked cycle processed
19 existing events; the propagated checkpoint now contains **13,477 IDs**.
Gold and operational SQL agree on **1,008 orders and 1,007 playback sessions**.
The graph includes the five affected orders, and a subsequent idle cycle
completed with zero unpublished events. See the recovery details in
[Demo automation](DEMO-AUTOMATION.md).
