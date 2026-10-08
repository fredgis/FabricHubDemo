# Warehouse business domains → Ontology → cockpit

MSFlix's consolidation model is organized by **catalogue, offers, audiences,
sales, playback and marketing**. These are business responsibilities, not Azure
resource metrics.

**Current checkpoint, 8 October 2026, 06:19 UTC:** automatic publication
**succeeded with 1,003 order lines** and the acceptance order's playback.
These are Warehouse results, not substituted operational-SQL KPIs.
The worker checkpoint contains **13,458 propagated event IDs**, with the three
latest events observed in KQL, native OneLake and physical Raw.
Strict date normalization and SQL seven-digit timestamp handling
have been corrected/persisted; no entity-sequence conflicts were found.
Generation-2 Ontology is now Gold-backed. Its 10-entity/12-relationship
projection was accepted through the public GraphModel API, and native
Gold-backed graph queries succeeded. The cockpit's native graph path is now
working and its interactive view renders real nodes and relationships.

The published masters come from **live Oracle: 305 films, 2,440 canonical
offers, 1 distributor**, and **actual native BPS: 700 MSFlix Contacts**.
Source provenance remains explicit; these source counts are not substituted
for independent Warehouse dimension-count readback.
After user registration, native marketing Silver job
`b692a6ed-486c-439f-92df-3643e5c2988d` completed with **6 campaigns, 700 consents
and 600 touches**. Handoff files now come from actual Silver `dbo` tables, with
`processed_silver=true`; they are no longer the earlier Bronze fallback.
All four CRM entity sets are loaded into MSFlix Gold. Optional BPS-native Touch
Gold still requires dataset relationships; it is not a prerequisite for this
Warehouse. Recorded campaign conversions remain **0**; none are inferred.

## Actual serving and business-context items

| Component | Actual identifier |
|---|---|
| Warehouse `MSFlixGold` | `7eb1318d-e4b5-4bc4-ae12-6c3a46b1b7f5` |
| Conformed Lakehouse `MSFlixSilver` | `3fa1c0b6-89da-4ea4-85c1-009f8cada6c1` |
| Ontology v2 `MSFlixBusiness` | `3534d696-e727-45b3-9387-bbd155a82a52` |
| Native Ontology graph | `1f368a35-95da-42a2-924d-ef4bb6bc9413` |
| Cockpit app | `6ab44a5c-cb98-4445-aa00-670e6219abc7` |
| App-linked operational SQL database | `cf1d77e0-b953-4de8-a0ca-38ae4aabe57c` |
| Trusted functions | `62904465-1297-4b4c-97aa-1e4228dcd54b` |

Gold is in `06 Gold Business Domains`; the Ontology and its native graph,
Eventhouse and KQL children are in `07 Ontology v2`. All four native cockpit
items are in `08 Cockpit`; their names, IDs and connections are unchanged.

## Six functional areas, with real physical mappings

The existing Warehouse uses the **`gold` schema**. The names below organize its
actual tables functionally; they are **not six already-deployed SQL schemas**.

| Business area | Current Warehouse / conformed data | Ontology mapping | Cockpit use |
|---|---|---|---|
| Catalogue | `gold.dim_content`, `dim_distributor`, `dim_territory` | `content`, `distributor`; `content_distributor` | Catalog, film details and provenance |
| Offers | `gold.dim_offer`, configured currency exponents; explicit territory and offer policies | `offer`; `offer_content`, `order_offer` | Eligible rental/purchase offer selection |
| Audiences | `gold.dim_customer`, `gold.fact_customer_consent` | `customer`, `consent`; `consent_customer` | Audiences, known identity and consent context |
| Sales | `gold.fact_order_line`, shared dimensions and approved commercial statuses | `rental` with `customer_order` and `order_offer` | Rentals & Purchases, actual booked activity |
| Playback | `gold.fact_playback_session` | `playback`; links to order, customer and content | Current sessions, progress and business graph |
| Marketing | `gold.dim_campaign`, `fact_campaign_conversion`, `fact_campaign_touch` | `campaign`, `touch`, `campaign_conversion`; customer/campaign/order links | Audiences & Campaigns, recorded attribution |

`rental` is the persisted Ontology entity name for the current order contract,
which supports TVOD rental and EST purchase. This report does not rename it or
invent a separate deployed purchase entity.

Native BPS has currently qualified **Contact extraction**, including 700 unique
MSFlix customer keys. Its native Silver job
`617be645-907f-4384-8610-9b50ba2be961` completed at
**2026-10-07 19:47:42.98 UTC**; processed native Silver customer readback qualified
700 MSFlix keys. Campaign, custom Consent and Touch are now user-registered and
processed through native Silver as well. The 6/700/600 handoffs are validated
through the parent's unchanged adapter and FK checks. Native BPS Gold is
separate; bootstrap exports are not substituted for native evidence.

## Useful business logic in the Warehouse

The baseline authored implementation contains seven dimensions, three
current-state fact tables and small publication/configuration tables. Extensions
include consent/touch facts and **12 `gold.link_*` junctions**, reusing canonical
properties from `gold.dim_*` and `gold.fact_*`. Gold-backed Ontology projection
and native graph queries have now succeeded.

- **Sales grain:** one current order line per order, not one line per outbox
  event. `gold.commercial_activity` includes only approved booked statuses and
  `TVOD` / `EST`, grouped by currency and commercial type.
- **Money:** `amount_minor` stays integer; decimal display amounts use an
  explicitly configured currency exponent. Amounts reconcile per currency;
  there is no invented FX rate or combined-currency revenue.
- **Playback:** `gold.playback_activity` reports current sessions by content and
  actual status, plus the furthest observed position. It does not interpret
  progress updates as additional plays or sales.
- **Marketing:** `gold.campaign_activity` counts recorded conversion keys.
  A touch near an order in time is not enough to fabricate a conversion.
- **Publication:** `load.sql` requires the exact completed Silver run, rejects
  duplicate natural keys, unresolved dimensions and currency mismatches, and
  reconciles order counts and minor-unit amounts before publishing.
- **Atomicity:** the Warehouse replacement is transactional locally.
  Eventstream sinks, Raw and Silver are not part of that SQL transaction.
  Writers must be serialized.

`gold.dim_date` is derived from observed business dates. `gold.currency` and
`gold.commercial_status` are explicit technical/reference configuration; they
are not extra external business feeds. Column-level mapping remains in the SQL
and Ontology definitions rather than crowding the README lineage diagram.

No bank charge, invoice, royalties, distributor profitability or SVOD
subscription financial fact is inferred from today's demo orders.

## Ontology v2: definition is not instances

The deployed item is generation two, with persisted TMDL metadata and native
graph children. The current authored model contains **10 entity types and 12
business relationships**, with stable lineage and junction-backed joins.

The delivery chain is **Raw → Silver → Gold business areas → Ontology and
cockpit**. The earlier Silver backing has been replaced by Gold. The
10-entity/12-relationship projection was accepted and native Gold-backed graph
queries succeeded. The former app HTTP 500 was fixed by validating only the
actual source coordinates, not ORM metadata alongside those coordinates.
The native user's app graph invocation also succeeded.

Completing the chain requires the Warehouse load, generation-two definition
readback against Gold and demonstrable entity/relationship instances. Creating
an Ontology or GraphModel alone does not pass that gate. No unsupported
instance-refresh endpoint or silently substituted generation-one model is used.

## Cockpit reads and writes have different responsibilities

The deployed app is hosted at
[MSFlix Business Control](https://green-frost-25a604b469-southeastasia.webapp.fabricapps.net).
Full cockpit deployment **succeeded** at the same hosting, with
`excludedServices=[]`, `skippedConnectors=[]`, `warnings=[]`.
It includes Gold business views, native GQL business-graph integration and
**305 local film presentations**. All **82 known licensed files** are cached;
primary images comprise **37 film stills, 10 posters, 4 labelled publicity
photos, 17 labelled title graphics and 237 editorial fallbacks**. Another 14
unsuitable source references are archived rather than displayed as film images.
The Big Buck Bunny cinematic hero is preserved. Native user calls to health,
Gold business views and the graph succeeded after the full app publication.

- Trusted commands persist orders, rights, playback and outbox state in the
  app-linked SQL database.
- Analytics reads the real Gold Warehouse. An empty or unavailable Gold result
  must remain an honest empty/error state, not an operational-SQL KPI fallback.
- Business Graph is wired to the real native service. Its default six-journey
  view is a labelled subset, not a total for the whole ontology.
- End-user operator/viewer invocation and graph-instance acceptance are
  separate from deployment readiness.

See [COCKPIT.md](COCKPIT.md) for the version-locked app implementation.

## Promotion boundaries and bounded operation

Historical and newly acknowledged events are physically materialized in Raw.
Gold and the native ontology graph have been refreshed by the persistent worker.
The optional BPS-native Touch Gold relationship gate is separate from this
working serving path. Manual staged entry points are:

```powershell
py -3 -m fabric.deploy --config <ignored-local-config> --stage process
py -3 -m fabric.deploy --config <ignored-local-config> --stage reconcile
py -3 -m fabric.deploy --config <ignored-local-config> --stage gold
```

These are real jobs/loads, not a documentation refresh. Pause the automatic
worker and wait for its current cycle before running another writer. When
master snapshot paths change, follow the
[automation runbook](DEMO-AUTOMATION.md) before resuming the worker.
GPU acceleration remains unqualified until actual execution evidence reports
`is_accelerated = 1`.

## Implementation and references

- `fabric/gold/ddl.sql`, `load.sql`, `kpis.sql`
- `fabric/ontology/definition/expressions.tmdl`,
  `entityRelationships.tmdl`, `entities/`, `tables/`
- `fabric/spark_runtime.py`, `fabric/contracts.py`
- [Ontology generation-2 definition](https://learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/ontology-definition)
- [Get Ontology and generation property](https://learn.microsoft.com/en-us/rest/api/fabric/ontology/items/get-ontology)
- [Current source/event flow](ARCHITECTURE.md) · [Exact item inventory](TASK-FLOW.md)
