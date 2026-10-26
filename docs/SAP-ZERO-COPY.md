# SAP zero-copy — SQL contract and operations

## Verified live deployment and retirement

The expanded deployment and retirement were verified on 26 October 2026.
`MSFlixGold.sap_live` reads `bps_gold_<system_suffix>.dbo` directly: system `S4M`,
companies **1710/EUR, 1720/CAD and 1730/CHF**. No SAP business rows are
materialized in Warehouse tables by this serving layer.

**24 copies (22 business tables and two technical tables) and nine legacy views
were actually retired.** The retirement journal records `status=verified`,
`data_verified=true`, all **35 SQL interfaces: 30 views and five inline TVFs**
passing and all **20 expanded checks** passing. Post-commit readback verified
retired objects absent, serving definitions/data valid, and unchanged native
schema, non-SAP definitions and native pipeline configuration.

The [SQL artifact template](../fabric/gold/sap-live-serving.v1.sql) is bound to
the SHA-256 of the reviewed environment-rendered artifact in local deployment
proof. Private environment substitutions can change its bytes; the template
hash is not a claim about the live deployed hash.
Local evidence (ignored by Git):
- `.state/sap/zero-copy/expanded-preflight/run-20261026T084421Z/`: fresh native
  catalog and independent expanded qualification.
- `.state/sap/zero-copy/deployment-integration/retirement-journal.json`: reviewed
  before-state and verified retirement proof.

These documents contain metadata and aggregate counts, not business row exports
or credentials. Native SAP mirroring, authorized Datasphere/OneLake publication,
Silver checks and BPS processing remain. Daily schedules are unchanged: B2S
orchestration **10:00 UTC**, S2G full processing **13:00 UTC**. The cockpit was
**not modified and is not integrated with SAP**. Oracle, Salesforce, operational
workers and non-SAP Gold remain unchanged. **Planning is pending**: a separate
future semantic projection, with no forecast mixed into actuals.

## Business scenario and distinctions

Verified scope: **1,092 invoice/credit items**, split into four baseline November
SVOD subscription items and 1,088 October operational TVOD/EST items; **700 real
native customers** plus the unknown member; **7,642 GL lines and 7,642 operational
accounting items**. These are observed counts, not renderer limits.

The baseline retains `ZMSF_BILLING_LINK` → subscription → plan/version →
contract/version and its four null `ORDER_ID` values. Operational items instead
use native `ZMSF_ORDER_LINK` with `(ORDER_ID, ORDER_LINE_NUMBER)` and original
invoice/item references for credits: no fabricated subscription. All 1,088
operational bridge rows matched shared order/customer/currency references; all
1,092 invoice customer/CRM mappings passed. **72 monthly financial measure cells**
reconciled to independent native GL aggregates.

Operational demo conventions: tax-inclusive prices and illustrative uniform
**20% tax**, invoicing at order time, recognition at first observed playback,
simulated receipts, identified arrears and refunds/credit notes. Fictional
operational content cost is 20% of recognized net revenue after credits, without
a fixed fee, with partial supplier settlement and separate calculation per
currency. The baseline contract keeps its own charges. These are not real local
tax rules. Refunds preserve original invoice/item references and signs.

Ordered ≠ invoiced ≠ recognized ≠ collected. Do not add shared order revenue to
SAP revenue as two sales, or GL and operational accounting items as two journals.
Keep EUR/CAD/CHF separate; no invented FX. Contribution after content cost is not
full enterprise profit. Component, operational and total measures overlap and
must not be added together again.

## SQL interfaces

### 24 native projection views

| `sap_live` view | Native BPS `dbo` object |
|---|---|
| `gl_line` | `I_GLACCOUNTLINEITEMRAWDATA` |
| `operational_item` | `I_OPERATIONALACCTGDOCITEM` |
| `invoice_line` | `C_BILLINGDOCITEMBASICDEX_1` |
| `company` | `I_COMPANYCODE` |
| `gl_account` | `I_GLACCOUNTINCHARTOFACCOUNTS` |
| `fiscal_period` | `I_FISCALPERIODFORVARIANT` |
| `customer` | `I_CUSTOMER` |
| `supplier` | `I_SUPPLIER` |
| `customer_link` | `ZMSF_CUSTOMER_LINK` |
| `fiscal_year` | `I_FISCALYEARFORCOMPANYCODE` |
| `fiscal_variant` | `I_FISCALYEARVARIANT` |
| `product` | `I_PRODUCT` |
| `cost_center` | `I_COSTCENTER` |
| `profit_center` | `I_PROFITCENTER` |
| `gl_hierarchy` | `I_GLACCOUNTHIERARCHYNODE` |
| `cost_hierarchy` | `I_COSTCENTERHIERARCHYNODE` |
| `profit_hierarchy` | `I_PROFITCENTERHIERARCHYNODE` |
| `plan` | `ZMSF_PLAN` |
| `subscription` | `ZMSF_SUBSCRIPTION` |
| `rights_contract` | `ZMSF_RIGHTS_CONTRACT` |
| `rights_coverage` | `ZMSF_RIGHTS_COVERAGE` |
| `billing_link` | `ZMSF_BILLING_LINK` |
| `contract_charge` | `ZMSF_CONTRACT_CHARGE` |
| `order_link` | `ZMSF_ORDER_LINK` |

Columns are explicit and catalog-driven, preserving business keys, `Key`,
`_key_*`, watermarks and native markers. Only identified Delta transport fields
`_commit_version` and `_change_type` are excluded; observed `__SEQUENCE_NUMBER`
and `__TIMESTAMP` remain. Raw facts are not cast, aggregated or deduplicated.
Objects with `COMPANYCODE` use the three-company filter; shared dimensions
without that column are system-scoped. Raw dimensions retain native global
unknown `Key=-1` / null system; it is not a real company/customer/subscription.

### Six business views

| View | Grain / meaning |
|---|---|
| `invoice_customer` | Invoice/credit item with sold-to SK, native crosswalk and full shared `gold.dim_customer` CRM identity check |
| `gl_account_balance` | Signed/absolute movement, not cumulative balance; account, ledger, fiscal period, currency, SK and marker grain |
| `customer_invoice_item` | Invoice/credit item, exclusive subscription/order bridge, order line and original credit item; no implicit date filter |
| `subscription_contract` | Real baseline subscription, plan/version, customer, contract/version; excludes unknown member |
| `calendar` | Valid fiscal periods, excluding unknown member; no implicit cutoff |
| `account_roles` | Thirteen explicit MSFX demo roles: eight baseline plus five operational; unmapped accounts diagnosed |

`customer_mapping_status='matched'` in native-enriched interfaces validates the
native crosswalk and relevant SK, not a new shared CRM identity check. Use
`invoice_customer` for shared identity. `billing_linkage_type` separates
`subscription` and `operational_order`; missing, dual, conflicting or wrong-client
bridges are not silently accepted. Order customer code and SK must agree with
invoice sold-to code and SK.

### Five inline TVFs — cutoff mandatory

| Function | Grain / meaning |
|---|---|
| `monthly_finance(@as_of date)` | System/company/ledger/chart/calendar month/fiscal period/currency/marker; native GL through inclusive cutoff |
| `ar_open_items(@as_of date)` | Customer D items posted by cutoff, not cleared then; signed receivable |
| `ap_open_items(@as_of date)` | Supplier K items under same date rules; payable sign inverted |
| `balances(@as_of date)` | System/company/currency AR/AP; known empty scope gives zero; missing amount gives NULL plus counters |
| `payment_journal(@as_of date)` | All GL lines of DZ/DA/KZ documents through cutoff, ledger preserved; not one row per payment |

Null cutoff is not “now” and returns no reporting period. `CLEARINGDATE > @as_of`
keeps later-cleared items open at cutoff. Partial supplier payments may remain
separate open items. Operational items have no source ledger: do not invent a
ledger join. Select GL ledger explicitly; never sum ledgers as different sales.

### 15 monetary interfaces and safeguards

The tested monetary set comprises six raw projections (`gl_line`,
`operational_item`, `invoice_line`, `plan`, `rights_contract`, `contract_charge`),
four business views (`invoice_customer`, `gl_account_balance`,
`customer_invoice_item`, `subscription_contract`) and the five TVFs.
`order_link` is additionally guarded as a mapping source for monetary attribution.

- Facts and amounts are never deduplicated. LEFT JOIN preserves unmatched facts
  but does not alone prevent fan-out.
- Mapping sources resolve only a unique distinct full projected row per join
  grain. Identical duplicate mappings collapse without multiplying money;
  `*_source_rows`, `*_distinct_rows`, `*_cardinality_status` retain evidence.
  Conflicts leave non-grain fields unresolved; no arbitrary MAX/MIN/first-row
  winner. DISTINCT is confined to mapping resolution, not duplicate-fact repair.
- `_Delete` is exposed, never assumed deleted or silently filtered. Blank markers
  are observed; null/nonblank markers are unverified. Inspect `native_state_status`
  or explicit marker fields before current-state claims.
- Monthly finance separates subscription/TVOD/EST/operational/total revenue,
  content expenses and deferred liabilities. It exposes missing/unmapped/excluded
  account counts, excluded signed amount and `account_completeness_status`.
  Relevant missing amounts yield NULL, not plausible partial metrics. AR/AP
  balances expose missing-amount and scope-marker counters. The movement example
  retains native SUM semantics; check completeness independently.

## Read-only examples

This explicit demo cutoff is neither processing time nor a Planning forecast.

```sql
DECLARE @as_of date = '2026-11-30';
SELECT _SystemName, COMPANYCODE, calendar_year, calendar_month, currency,
       recognized_subscription_revenue, recognized_tvod_revenue,
       recognized_est_revenue, recognized_total_revenue,
       subscription_content_expense, operational_content_expense,
       missing_amount_rows, account_completeness_status, native_state_status
FROM sap_live.monthly_finance(@as_of)
WHERE SOURCELEDGER = '0L';

SELECT _SystemName, COMPANYCODE, currency, as_of,
       receivables_outstanding, payables_outstanding,
       ar_missing_amount_rows, ap_missing_amount_rows, native_state_status
FROM sap_live.balances(@as_of);

SELECT billing_linkage_type, COMPANYCODE, TRANSACTIONCURRENCY,
       COUNT_BIG(*) AS invoice_items
FROM sap_live.customer_invoice_item
GROUP BY billing_linkage_type, COMPANYCODE, TRANSACTIONCURRENCY;
```

## Freshness, retirement and recovery

Cutoffs select business dates in **current native state**, not immutable source
snapshots. BPS corrections can change past-cutoff results. Do not reconstruct
`sap_publication`, invent scenario/run IDs or substitute operational
`gold.publication` for SAP freshness. Distinguish observation time, watermarks
and completed BPS jobs; recheck keys, markers and cardinality after refresh.

Retirement used a closed 24-table/nine-view list, dependency order, reviewed
SQL/hash binding, transactional DDL evidence and fresh post-commit readback.
No native BPS table was dropped. Catalog checks cannot disprove all dynamic
consumers; authorization explicitly scoped retirement and excluded cockpit and
native ingestion. Resolve ambiguous commits by reading state before retry.

`sources.sap.warehouse` remains an inspector (`--inspect-silver`,
`--inspect-source`); legacy `publish()`, non-inspection `run()` and `--apply` are
refused before connection/input loading. `sap-ddl.sql` and `sap-views.sql` are no
longer distributed. `sources.sap.publish` remains the authorized **upstream**
Datasphere/OneLake publisher, not the retired Warehouse writer. Do not disable
it or B2S/S2G schedules. Non-SAP bundle: `ddl.sql`, `load.sql`, `kpis.sql`.

DROP removed retired Warehouse table history. No continuously fed backup copy
was created; recovery repairs zero-copy, not the legacy publisher. Future
cockpit/Planning identities must separately validate Warehouse and BPS access;
no new GRANT or integration is claimed.

## Development and tests

```bash
python -m unittest tests.sap.test_zero_copy tests.sap.test_zero_copy_serving
python -m unittest tests.sap.test_retirement tests.sap.test_zero_copy_checks
python -m unittest tests.sap.test_zero_copy_deploy tests.sap.test_zero_copy_guards
```

Use project dependencies. SQLite tests validate logic, not the Fabric engine;
live SELECT/TVF and post-commit proof are separate. The pure renderer must
reproduce the reviewed artifact from the current native catalog and three-company
scope; it performs no cloud write or business DML.

See [SAP data model](SAP-DATA-MODEL.md), [standalone diagram](assets/sap-msflix-model.html)
and [metadata dictionary](assets/sap-native-model.json).
