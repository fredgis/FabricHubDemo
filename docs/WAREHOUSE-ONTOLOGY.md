# Warehouse business domains → Ontology → cockpit

MSFlix's consolidation model is organized by **catalogue, offers, audiences,
sales, playback and marketing**. These are business responsibilities, not Azure
resource metrics.

**Current checkpoint, 7 October 2026:** Gold publication
`<CONNECTED_EVENTS_RUN_ID>` **succeeded with 1,002 order lines**. These are
Warehouse publication results, not substituted operational-SQL KPIs.
Physical Raw contains **13,455 rows and 13,455 distinct event IDs**, exactly
matching KQL. Strict date normalization and SQL seven-digit timestamp handling
have been corrected/persisted; no entity-sequence conflicts were found.
Generation-2 Ontology is now Gold-backed. Its 10-entity/12-relationship
projection was accepted through the public GraphModel API, and native
Gold-backed graph queries succeeded. The cockpit's native graph path still
returns **HTTP 500** and is being fixed; app integration is not declared complete.

The newest masters are staged from **live Oracle: 305 films, 2,440 canonical
offers, 1 distributor**, and **actual native BPS: 700 MSFlix Contacts**.
Source provenance remains explicit; these source counts are not substituted
for independent Warehouse dimension-count readback.
After user registration, native marketing Silver job
`<CRM_MARKETING_SILVER_JOB_ID>` completed with **6 campaigns, 700 consents
and 600 touches**. Handoff files now come from actual Silver `dbo` tables, with
`processed_silver=true`; they are no longer the earlier Bronze fallback.
Native BPS Gold dimensions/facts continue sequentially. Recorded campaign
conversions remain **0**; no conversion is inferred or manufactured.

## Actual serving and business-context items

| Component | Actual identifier |
|---|---|
| Warehouse `MSFlixGold` | `<WAREHOUSE_ID>` |
| Conformed Lakehouse `MSFlixSilver` | `<SILVER_LAKEHOUSE_ID>` |
| Ontology v2 `MSFlixBusiness` | `<ONTOLOGY_ID>` |
| Native Ontology graph | `<GRAPH_MODEL_ID>` |
| Cockpit app | `<APP_ITEM_ID>` |
| App-linked operational SQL database | `<APP_SQL_ITEM_ID>` |
| Trusted functions | `<APP_UDF_ITEM_ID>` |

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
`<CRM_CONTACT_SILVER_JOB_ID>` completed at
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
queries succeeded. The remaining app HTTP 500 is an integration defect, not a
claim that the native Gold binding is still absent.

Completing the chain requires the Warehouse load, generation-two definition
readback against Gold and demonstrable entity/relationship instances. Creating
an Ontology or GraphModel alone does not pass that gate. No unsupported
instance-refresh endpoint or silently substituted generation-one model is used.

## Cockpit reads and writes have different responsibilities

The deployed app is hosted at
[MSFlix Business Control](https://<app-host>).
Full cockpit deployment **succeeded** at the same hosting, with
`excludedServices=[]`, `skippedConnectors=[]`, `warnings=[]`.
It includes Gold business views, real GraphQL business-graph integration and
**305 local film presentations: 57 licensed cached images and 248 clearly
labelled original editorial images**, with original fallbacks for every film.
Local **49 tests and build passed**. Native Gold-backed graph queries succeeded,
but the app's native graph view currently returns **HTTP 500** and remains under
repair. Deployment and local checks do not prove all runtime paths are healthy.

- Trusted commands persist orders, rights, playback and outbox state in the
  app-linked SQL database.
- Analytics reads the real Gold Warehouse. An empty or unavailable Gold result
  must remain an honest empty/error state, not an operational-SQL KPI fallback.
- Business Graph is wired to the real native service. Its app HTTP 500 remains
  unresolved even though native Gold-backed query tests succeeded.
- End-user operator/viewer invocation and graph-instance acceptance are
  separate from deployment readiness.

See [COCKPIT.md](COCKPIT.md) for the version-locked app implementation.

## Promotion boundaries and bounded operation

Historical events are physically materialized in Raw, their exact ID set matches
KQL, and the first connected-events Gold publication succeeded. Gold-backed
Ontology queries also succeeded. Remaining native BPS Gold refresh and the
app's graph-integration fix are tracked separately. Existing staged entry
points are:

```powershell
py -3 -m fabric.deploy --config <ignored-local-config> --stage process
py -3 -m fabric.deploy --config <ignored-local-config> --stage reconcile
py -3 -m fabric.deploy --config <ignored-local-config> --stage gold
```

These are real jobs/loads, not a documentation refresh. Do not run another writer
while the parent is completing the publication. GPU acceleration remains
unqualified until actual execution evidence reports `is_accelerated = 1`.

## Implementation and references

- `fabric/gold/ddl.sql`, `load.sql`, `kpis.sql`
- `fabric/ontology/definition/expressions.tmdl`,
  `entityRelationships.tmdl`, `entities/`, `tables/`
- `fabric/spark_runtime.py`, `fabric/contracts.py`
- [Ontology generation-2 definition](https://learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/ontology-definition)
- [Get Ontology and generation property](https://learn.microsoft.com/en-us/rest/api/fabric/ontology/items/get-ontology)
- [Current source/event flow](ARCHITECTURE.md) · [Exact item inventory](TASK-FLOW.md)
