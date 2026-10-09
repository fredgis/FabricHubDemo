-- @batch
CREATE OR ALTER VIEW gold.sap_monthly_finance AS
SELECT g.source_system, g.company_scope, g.scenario_id, g.run_id,
       YEAR(g.POSTINGDATE) AS calendar_year, MONTH(g.POSTINGDATE) AS calendar_month,
       g.FISCALYEARVARIANT, g.FISCALYEAR, g.FISCALPERIOD, g.TRANSACTIONCURRENCY AS currency,
       -SUM(CASE WHEN g.GLACCOUNT={{ACCOUNT_REVENUE}} THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) AS recognized_subscription_revenue,
       SUM(CASE WHEN g.GLACCOUNT={{ACCOUNT_CONTENT_COST}} THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) AS content_expense,
       -SUM(CASE WHEN g.GLACCOUNT IN ({{ACCOUNT_REVENUE}},{{ACCOUNT_CONTENT_COST}}) THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) AS contribution_after_content_cost_only,
       SUM(CASE WHEN g.GLACCOUNT={{ACCOUNT_BANK}} THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) AS net_bank_movement,
       -SUM(CASE WHEN g.GLACCOUNT={{ACCOUNT_OUTPUT_VAT}} THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) AS output_vat_liability,
       SUM(CASE WHEN g.GLACCOUNT={{ACCOUNT_INPUT_VAT}} THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) AS input_vat_recoverable,
       -SUM(CASE WHEN g.GLACCOUNT IN ({{ACCOUNT_OUTPUT_VAT}},{{ACCOUNT_INPUT_VAT}}) THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) AS net_vat_liability,
       -SUM(CASE WHEN g.GLACCOUNT={{ACCOUNT_DEFERRED_REVENUE}} THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) AS deferred_subscription_liability
FROM gold.sap_gl_line g
JOIN gold.sap_publication p ON p.source_system=g.source_system AND p.company_scope=g.company_scope
 AND p.scenario_id=g.scenario_id AND p.run_id=g.run_id
WHERE g.SOURCELEDGER='0L' AND g.CHARTOFACCOUNTS={{CHART}} AND g.POSTINGDATE<=p.as_of
GROUP BY g.source_system, g.company_scope, g.scenario_id, g.run_id,
         YEAR(g.POSTINGDATE), MONTH(g.POSTINGDATE), g.FISCALYEARVARIANT,
         g.FISCALYEAR, g.FISCALPERIOD, g.TRANSACTIONCURRENCY;
-- @batch
CREATE OR ALTER VIEW gold.sap_ar_open_item_current AS
SELECT o.*, c.CUSTOMER_KEY, c.SALESFORCE_CONTACT_ID AS source_customer_id,
       o.AMOUNTINTRANSACTIONCURRENCY AS outstanding_signed
FROM gold.sap_operational_item o
JOIN gold.sap_publication p ON p.source_system=o.source_system AND p.company_scope=o.company_scope
 AND p.scenario_id=o.scenario_id AND p.run_id=o.run_id
JOIN gold.sap_customer_link c ON c.source_system=o.source_system AND c.company_scope=o.company_scope
 AND c.scenario_id=o.scenario_id AND c.run_id=o.run_id AND c.CUSTOMER=o.CUSTOMER
WHERE o.FINANCIALACCOUNTTYPE='D' AND o.POSTINGDATE<=p.as_of
 AND (o.CLEARINGDATE IS NULL OR o.CLEARINGDATE>p.as_of);
-- @batch
CREATE OR ALTER VIEW gold.sap_ap_open_item_current AS
SELECT o.*, -o.AMOUNTINTRANSACTIONCURRENCY AS outstanding_payable_signed
FROM gold.sap_operational_item o
JOIN gold.sap_publication p ON p.source_system=o.source_system AND p.company_scope=o.company_scope
 AND p.scenario_id=o.scenario_id AND p.run_id=o.run_id
WHERE o.FINANCIALACCOUNTTYPE='K' AND o.POSTINGDATE<=p.as_of
 AND (o.CLEARINGDATE IS NULL OR o.CLEARINGDATE>p.as_of);
-- @batch
CREATE OR ALTER VIEW gold.sap_current_balances AS
SELECT p.source_system, p.company_scope, p.scenario_id, p.run_id, p.as_of,
       COALESCE((SELECT SUM(a.outstanding_signed) FROM gold.sap_ar_open_item_current a
                 WHERE a.source_system=p.source_system AND a.company_scope=p.company_scope
                  AND a.scenario_id=p.scenario_id AND a.run_id=p.run_id),0) AS receivables_outstanding,
       COALESCE((SELECT SUM(a.outstanding_payable_signed) FROM gold.sap_ap_open_item_current a
                 WHERE a.source_system=p.source_system AND a.company_scope=p.company_scope
                  AND a.scenario_id=p.scenario_id AND a.run_id=p.run_id),0) AS payables_outstanding
FROM gold.sap_publication p;
-- @batch
CREATE OR ALTER VIEW gold.sap_payment_journal AS
SELECT g.*
FROM gold.sap_gl_line g
JOIN gold.sap_publication p ON p.source_system=g.source_system AND p.company_scope=g.company_scope
 AND p.scenario_id=g.scenario_id AND p.run_id=g.run_id
WHERE g.SOURCELEDGER='0L' AND g.ACCOUNTINGDOCUMENTTYPE IN ('DZ','DA','KZ') AND g.POSTINGDATE<=p.as_of;
-- @batch
CREATE OR ALTER VIEW gold.sap_customer_invoice_item AS
SELECT b.*, c.CUSTOMER_KEY, c.SALESFORCE_CONTACT_ID AS source_customer_id,
       l.SUBSCRIPTION_ID, l.SERVICE_FROM, l.SERVICE_TO_EXCLUSIVE,
       l.ORIGINAL_BILLINGDOCUMENT, l.ORDER_ID
FROM gold.sap_invoice_item b
JOIN gold.sap_publication p ON p.source_system=b.source_system AND p.company_scope=b.company_scope
 AND p.scenario_id=b.scenario_id AND p.run_id=b.run_id
JOIN gold.sap_billing_link l ON l.source_system=b.source_system AND l.company_scope=b.company_scope
 AND l.scenario_id=b.scenario_id AND l.run_id=b.run_id
 AND l.BILLINGDOCUMENT=b.BILLINGDOCUMENT AND l.BILLINGDOCUMENTITEM=b.BILLINGDOCUMENTITEM
JOIN gold.sap_customer_link c ON c.source_system=b.source_system AND c.company_scope=b.company_scope
 AND c.scenario_id=b.scenario_id AND c.run_id=b.run_id AND c.CUSTOMER=b.SOLDTOPARTY;
-- @batch
CREATE OR ALTER VIEW gold.sap_subscription_contract AS
SELECT s.*, c.CUSTOMER_KEY, c.SALESFORCE_CONTACT_ID AS source_customer_id,
       f.MONTHLY_NET, f.VAT_RATE, f.CURRENCY, f.CONTRACT_ID, f.CONTRACT_VERSION
FROM gold.sap_subscription s
JOIN gold.sap_publication p ON p.source_system=s.source_system AND p.company_scope=s.company_scope
 AND p.scenario_id=s.scenario_id AND p.run_id=s.run_id
JOIN gold.sap_plan f ON f.source_system=s.source_system AND f.company_scope=s.company_scope
 AND f.scenario_id=s.scenario_id AND f.run_id=s.run_id
 AND f.PLAN_ID=s.PLAN_ID AND f.VERSION=s.PLAN_VERSION
JOIN gold.sap_customer_link c ON c.source_system=s.source_system AND c.company_scope=s.company_scope
 AND c.scenario_id=s.scenario_id AND c.run_id=s.run_id AND c.CUSTOMER=s.CUSTOMER;
-- @batch
CREATE OR ALTER VIEW gold.sap_calendar AS
SELECT c.source_system, c.company_scope, c.scenario_id, c.run_id,
       c.FISCALYEARVARIANT, c.FISCALYEAR, c.FISCALPERIOD, c.FISCALYEARPERIOD,
       c.FISCALPERIODSTARTDATE, c.FISCALPERIODENDDATE, c.FISCALYEARSTARTDATE,
       c.FISCALYEARENDDATE, c.ISSPECIALPERIOD, c.NEXTFISCALPERIOD, c.NEXTFISCALPERIODFISCALYEAR
FROM gold.sap_period c
JOIN gold.sap_publication p ON p.source_system=c.source_system AND p.company_scope=c.company_scope
 AND p.scenario_id=c.scenario_id AND p.run_id=c.run_id;
-- @batch
CREATE OR ALTER VIEW gold.sap_account_roles AS
SELECT a.*, CASE a.GLACCOUNT
 WHEN {{ACCOUNT_BANK}} THEN 'bank'
 WHEN {{ACCOUNT_RECEIVABLES}} THEN 'receivables'
 WHEN {{ACCOUNT_PAYABLES}} THEN 'payables'
 WHEN {{ACCOUNT_INPUT_VAT}} THEN 'input_vat'
 WHEN {{ACCOUNT_OUTPUT_VAT}} THEN 'output_vat'
 WHEN {{ACCOUNT_DEFERRED_REVENUE}} THEN 'deferred_revenue'
 WHEN {{ACCOUNT_REVENUE}} THEN 'revenue'
 WHEN {{ACCOUNT_CONTENT_COST}} THEN 'content_cost'
 END AS account_role
FROM gold.sap_account a
JOIN gold.sap_publication p ON p.source_system=a.source_system AND p.company_scope=a.company_scope
 AND p.scenario_id=a.scenario_id AND p.run_id=a.run_id
WHERE a.CHARTOFACCOUNTS={{CHART}};
-- Contract coverage is a fictional portfolio mapping. No per-film cost allocation,
-- commercial Blender license, operating profit or TVOD/EST order revenue is asserted.
