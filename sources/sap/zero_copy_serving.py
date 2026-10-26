"""Pure, versioned SAP serving SQL; no cloud access or data publication.

Supersedes sap-live-views.preview.sql (kept as historical evidence). Raw views
retain native business fields, Key, _key_* and the global unknown member.
Delta transport metadata is deliberately excluded, not a business interface.
_Delete is exposed, NEVER interpreted or filtered: the retirement inventory
observed blank flags in the scoped native records. NULL/nonblank markers need
operator investigation before claiming current-state semantics. This is a
query-time cutoff over native state, NOT a historical snapshot or publication.
"""
from __future__ import annotations

from .accounting import ACCOUNTS as SUBSCRIPTION_ACCOUNTS, CHART
from .zero_copy import (TABLES as PREVIEW_TABLES, business_views, ident, literal,
                        source_views, grouped_sources, cardinality_fields)

# Serving policy only: never change the native accounting generators.
ACCOUNTS = {**SUBSCRIPTION_ACCOUNTS,
    'revenue_tvod': ('0041000000', 'TVOD revenue', 'P'),
    'revenue_est': ('0042000000', 'EST revenue', 'P'),
    'deferred_tvod': ('0023100000', 'Deferred TVOD', 'X'),
    'deferred_est': ('0023200000', 'Deferred EST', 'X'),
    'operational_content_cost': ('0051000000', 'Operational content cost', 'P'),
}

TABLES = {
    **PREVIEW_TABLES,
    'fiscal_year': 'I_FISCALYEARFORCOMPANYCODE',
    'fiscal_variant': 'I_FISCALYEARVARIANT',
    'product': 'I_PRODUCT',
    'cost_center': 'I_COSTCENTER',
    'profit_center': 'I_PROFITCENTER',
    'gl_hierarchy': 'I_GLACCOUNTHIERARCHYNODE',
    'cost_hierarchy': 'I_COSTCENTERHIERARCHYNODE',
    'profit_hierarchy': 'I_PROFITCENTERHIERARCHYNODE',
    'plan': 'ZMSF_PLAN',
    'subscription': 'ZMSF_SUBSCRIPTION',
    'rights_contract': 'ZMSF_RIGHTS_CONTRACT',
    'rights_coverage': 'ZMSF_RIGHTS_COVERAGE',
    'billing_link': 'ZMSF_BILLING_LINK',
    'contract_charge': 'ZMSF_CONTRACT_CHARGE',
    'order_link': 'ZMSF_ORDER_LINK',
}

# Only identified Delta transport metadata; preserve native keys and markers.
TRANSPORT_COLUMNS = frozenset({'_commit_version', '_change_type'})


def validate_catalog(catalog):
    """Fail closed if business-critical native column contracts are absent."""
    required = {
        'gl_line': 'COMPANYCODE POSTINGDATE SOURCELEDGER CHARTOFACCOUNTS GLACCOUNT AMOUNTINTRANSACTIONCURRENCY FISCALYEAR FISCALPERIOD FISCALYEARVARIANT TRANSACTIONCURRENCY ACCOUNTINGDOCUMENTTYPE _key_IGLACCOUNTINCHARTOFACCOUNTS',
        'operational_item': 'COMPANYCODE POSTINGDATE CLEARINGDATE FINANCIALACCOUNTTYPE AMOUNTINTRANSACTIONCURRENCY TRANSACTIONCURRENCY CUSTOMER _key_ICUSTOMER',
        'invoice_line': 'COMPANYCODE BILLINGDOCUMENT BILLINGDOCUMENTITEM ACCOUNTINGDOCUMENT BILLINGDOCUMENTDATE BILLINGDOCUMENTCATEGORY SOLDTOPARTY PRODUCT TRANSACTIONCURRENCY NETAMOUNT TAXAMOUNT GROSSAMOUNT _key_ICUSTOMERSoldToParty',
        'company': 'Key COMPANYCODE CURRENCY',
        'gl_account': 'Key GLACCOUNT CHARTOFACCOUNTS GLACCOUNTTYPE',
        'customer': 'Key CUSTOMER CUSTOMERNAME',
        'customer_link': 'Key CUSTOMER CUSTOMER_KEY SALESFORCE_CONTACT_ID',
        'billing_link': 'BILLINGDOCUMENT BILLINGDOCUMENTITEM SUBSCRIPTION_ID SERVICE_FROM SERVICE_TO_EXCLUSIVE ORIGINAL_BILLINGDOCUMENT ORDER_ID _key_ZMSFSUBSCRIPTION',
        'order_link': 'BILLINGDOCUMENT BILLINGDOCUMENTITEM CUSTOMER ORDER_ID ORDER_LINE_NUMBER ORIGINAL_BILLINGDOCUMENT ORIGINAL_BILLINGDOCUMENTITEM SIMULATION_ONLY _key_ICUSTOMER',
        'subscription': 'Key CUSTOMER PLAN_ID PLAN_VERSION',
        'plan': 'Key PLAN_ID VERSION MONTHLY_NET VAT_RATE CURRENCY CONTRACT_ID CONTRACT_VERSION VALID_FROM VALID_TO_EXCLUSIVE',
        'fiscal_period': 'Key FISCALYEARVARIANT FISCALYEAR FISCALPERIOD FISCALYEARPERIOD FISCALPERIODSTARTDATE FISCALPERIODENDDATE',
        'fiscal_year': 'Key COMPANYCODE', 'cost_center': 'Key COMPANYCODE',
        'profit_center': 'Key COMPANYCODE', 'contract_charge': 'COMPANYCODE',
    }
    customer_outputs = ('native_customer_key CUSTOMER_KEY source_customer_id '
                        'native_customer_delete_marker native_crosswalk_delete_marker customer_mapping_status')
    added_outputs = {
        'invoice_line': customer_outputs + ' native_state_status SUBSCRIPTION_ID SERVICE_FROM SERVICE_TO_EXCLUSIVE '
            'ORIGINAL_BILLINGDOCUMENT ORDER_ID _key_ZMSFSUBSCRIPTION native_billing_link_delete_marker billing_mapping_status '
            'ORDER_LINE_NUMBER ORIGINAL_BILLINGDOCUMENTITEM SIMULATION_ONLY native_order_customer_key '
            'native_order_link_delete_marker billing_linkage_type order_customer_mapping_status '
            + ' '.join(n + suffix for n in ('customer', 'customer_link', 'billing_link', 'order_link')
                       for suffix in ('_source_rows', '_distinct_rows', '_cardinality_status')),
        'subscription': 'native_state_status CUSTOMER_KEY source_customer_id native_crosswalk_delete_marker '
            'native_plan_key native_plan_delete_marker MONTHLY_NET VAT_RATE CURRENCY CONTRACT_ID CONTRACT_VERSION '
            'plan_valid_from plan_valid_to_exclusive customer_mapping_status plan_mapping_status '
            + ' '.join(n + suffix for n in ('customer_link', 'plan')
                       for suffix in ('_source_rows', '_distinct_rows', '_cardinality_status')),
        'operational_item': customer_outputs + ' native_state_status as_of outstanding_signed outstanding_payable_signed '
            + ' '.join(n + suffix for n in ('customer', 'customer_link')
                       for suffix in ('_source_rows', '_distinct_rows', '_cardinality_status')),
        'gl_line': 'native_state_status as_of',
        'gl_account': 'native_state_status account_role account_mapping_status',
        'fiscal_period': 'native_state_status',
    }
    for name, table in TABLES.items():
        columns = [r['COLUMN_NAME'] for r in catalog
                   if r['TABLE_SCHEMA'] == 'dbo' and r['TABLE_NAME'] == table]
        folded = {c.casefold() for c in columns}
        if len(folded) != len(columns):
            raise ValueError('Duplicate native column contract: ' + name)
        if collision := folded & set(added_outputs.get(name, '').lower().split()):
            raise ValueError('Serving output column collision: ' + name + ': ' + ', '.join(sorted(collision)))
        needed = set(required.get(name, 'Key').split()) | {'_SystemName', '_Delete', '_UpdateTimeStamp'}
        if missing := needed - set(columns):
            raise ValueError('Missing native column contract: ' + name + ': ' + ', '.join(sorted(missing)))


def _with(base, names, body):
    return 'WITH ' + ',\n'.join(ident(n) + ' AS (\n' + base[n] + '\n)' for n in names) + '\n' + body


def _projection(catalog, name, alias):
    return ',\n    '.join(alias + '.' + ident(c) for c in sorted(
        r['COLUMN_NAME'] for r in catalog
        if r['TABLE_SCHEMA'] == 'dbo' and r['TABLE_NAME'] == TABLES[name]
        and r['COLUMN_NAME'].casefold() not in TRANSPORT_COLUMNS))


def _customer_join(alias, business_key, surrogate):
    return f'''LEFT JOIN customer c ON c.[Key] = {alias}.{ident(surrogate)}
 AND (c._SystemName = {alias}._SystemName OR (c.[Key] = -1 AND c._SystemName IS NULL))
LEFT JOIN customer_link l ON l._SystemName = {alias}._SystemName
 AND l.CUSTOMER = {alias}.{business_key} AND l.CUSTOMER = c.CUSTOMER AND c.[Key] <> -1'''


def _customer_fields(alias, business_key):
    return f'''c.[Key] AS native_customer_key, l.CUSTOMER_KEY,
    l.SALESFORCE_CONTACT_ID AS source_customer_id,
    c._Delete AS native_customer_delete_marker, l._Delete AS native_crosswalk_delete_marker,
    CASE WHEN c.[Key] IS NULL OR c.[Key] = -1 THEN 'missing_native_customer'
      WHEN c.CUSTOMER IS NULL OR {alias}.{business_key} IS NULL
        OR c.CUSTOMER <> {alias}.{business_key} THEN 'native_key_mismatch'
      WHEN l.CUSTOMER_KEY IS NULL THEN 'missing_crosswalk'
      ELSE 'matched' END AS customer_mapping_status'''


def _state(*aliases):
    """Blank is observed, not proof of activity; NULL/other markers block claims."""
    return ('CASE WHEN ' + ' AND '.join(a + "._Delete = ''" for a in aliases)
            + " THEN 'observed_blank_markers' ELSE 'unverified_native_markers' END AS native_state_status")


def _invoice_sources(catalog, base, sources=None):
    """Collapse identical source rows; conflicting records expose no winner.

    COUNTs retain physical and distinct cardinality. MAX/ROW_NUMBER must never
    select an arbitrary record: only a single distinct full native row resolves.
    """
    contracts = []
    for name, keys in (sources if sources is not None else (
        ('customer', ('_SystemName', 'Key')),
        ('customer_link', ('_SystemName', 'CUSTOMER')),
        ('billing_link', ('_SystemName', 'BILLINGDOCUMENT', 'BILLINGDOCUMENTITEM')),
        ('order_link', ('_SystemName', 'BILLINGDOCUMENT', 'BILLINGDOCUMENTITEM')),
    )):
        columns = sorted(r['COLUMN_NAME'] for r in catalog
                         if r['TABLE_SCHEMA'] == 'dbo' and r['TABLE_NAME'] == TABLES[name]
                         and r['COLUMN_NAME'].casefold() not in TRANSPORT_COLUMNS)
        contracts.append((name, keys, columns))
    return grouped_sources(base, contracts)


def _cardinality_fields(sources):
    return cardinality_fields(sources)


def serving_views(catalog, base):
    """Exact SELECT bodies for non-parameter business interfaces and examples."""
    validate_catalog(catalog)
    invoice_state = ("CASE WHEN b._Delete = '' AND c._Delete = '' AND l._Delete = '' "
        "AND (k.BILLINGDOCUMENT IS NULL OR k._Delete = '') "
        "AND (q.BILLINGDOCUMENT IS NULL OR q._Delete = '') "
        "THEN 'observed_blank_markers' ELSE 'unverified_native_markers' END AS native_state_status")
    invoice = 'SELECT ' + _projection(catalog, 'invoice_line', 'b') + ',\n    ' + invoice_state + ''',
    ''' + _customer_fields('b', 'SOLDTOPARTY') + ''',
    k.SUBSCRIPTION_ID, k.SERVICE_FROM, k.SERVICE_TO_EXCLUSIVE,
    COALESCE(q.ORIGINAL_BILLINGDOCUMENT, k.ORIGINAL_BILLINGDOCUMENT) AS ORIGINAL_BILLINGDOCUMENT,
    COALESCE(q.ORDER_ID, k.ORDER_ID) AS ORDER_ID, k._key_ZMSFSUBSCRIPTION,
    q.ORDER_LINE_NUMBER, q.ORIGINAL_BILLINGDOCUMENTITEM, q.SIMULATION_ONLY,
    q._key_ICUSTOMER AS native_order_customer_key,
    q._Delete AS native_order_link_delete_marker,
    k._Delete AS native_billing_link_delete_marker,
    CASE WHEN k.BILLINGDOCUMENT IS NOT NULL AND q.BILLINGDOCUMENT IS NOT NULL THEN 'ambiguous_billing_link'
      WHEN k.BILLINGDOCUMENT IS NULL AND q.BILLINGDOCUMENT IS NULL THEN 'missing_billing_link'
      ELSE 'matched' END AS billing_mapping_status
    , CASE WHEN k.BILLINGDOCUMENT IS NOT NULL AND q.BILLINGDOCUMENT IS NOT NULL THEN 'ambiguous'
      WHEN q.BILLINGDOCUMENT IS NOT NULL THEN 'operational_order'
      WHEN k.BILLINGDOCUMENT IS NOT NULL THEN 'subscription'
      ELSE 'unlinked' END AS billing_linkage_type
FROM invoice_line b
''' + _customer_join('b', 'SOLDTOPARTY', '_key_ICUSTOMERSoldToParty') + '''
LEFT JOIN billing_link k ON k._SystemName = b._SystemName
 AND k.BILLINGDOCUMENT = b.BILLINGDOCUMENT AND k.BILLINGDOCUMENTITEM = b.BILLINGDOCUMENTITEM
LEFT JOIN order_link q ON q._SystemName = b._SystemName
 AND q.BILLINGDOCUMENT = b.BILLINGDOCUMENT AND q.BILLINGDOCUMENTITEM = b.BILLINGDOCUMENTITEM'''
    invoice_base = _invoice_sources(catalog, base)
    source_names = ('customer', 'customer_link', 'billing_link', 'order_link')
    for name, alias in zip(source_names, ('c', 'l', 'k', 'q')):
        invoice = invoice.replace('JOIN ' + name + ' ' + alias, 'JOIN ' + name + '_safe ' + alias)
        invoice = invoice.replace('FROM invoice_line b',
            f'''COALESCE({alias}.source_rows, 0) AS {name}_source_rows,
    COALESCE({alias}.distinct_rows, 0) AS {name}_distinct_rows,
    CASE WHEN {alias}.source_rows IS NULL THEN 'missing'
      WHEN {alias}.distinct_rows > 1 THEN 'conflicting_matches'
      WHEN {alias}.source_rows > 1 THEN 'identical_duplicates'
      ELSE 'unique' END AS {name}_cardinality_status,
FROM invoice_line b''')
    invoice = invoice.replace(' AS billing_linkage_type\n', ' AS billing_linkage_type,\n')
    invoice = invoice.replace(',\nFROM invoice_line b', '\nFROM invoice_line b')
    invoice = invoice.replace(
        '(c._SystemName = b._SystemName OR (c.[Key] = -1 AND c._SystemName IS NULL))',
        '((c.[Key] <> -1 AND c._SystemName = b._SystemName) OR (c.[Key] = -1 AND c._SystemName IS NULL))')
    invoice = invoice.replace("CASE WHEN c.[Key] IS NULL", "CASE WHEN c.distinct_rows > 1 THEN 'ambiguous_native_customer'\n      WHEN l.distinct_rows > 1 THEN 'ambiguous_crosswalk'\n      WHEN c.[Key] IS NULL")
    invoice = invoice.replace("CASE WHEN k.BILLINGDOCUMENT IS NOT NULL AND q.BILLINGDOCUMENT IS NOT NULL THEN",
        "CASE WHEN k.distinct_rows > 1 OR q.distinct_rows > 1\n        OR (k.BILLINGDOCUMENT IS NOT NULL AND q.BILLINGDOCUMENT IS NOT NULL) THEN")
    order_valid = ('q.distinct_rows = 1 AND q.CUSTOMER = b.SOLDTOPARTY '
                   'AND q._key_ICUSTOMER = b._key_ICUSTOMERSoldToParty '
                   'AND q._key_ICUSTOMER <> -1')
    bridge_safe = ('(k.source_rows IS NULL OR k.distinct_rows = 1) '
                   'AND (q.source_rows IS NULL OR (' + order_valid + ')) '
                   'AND (k.source_rows IS NULL OR q.source_rows IS NULL)')
    resolved = (
        ('SUBSCRIPTION_ID', 'k.SUBSCRIPTION_ID'), ('SERVICE_FROM', 'k.SERVICE_FROM'),
        ('SERVICE_TO_EXCLUSIVE', 'k.SERVICE_TO_EXCLUSIVE'),
        ('ORIGINAL_BILLINGDOCUMENT', 'COALESCE(q.ORIGINAL_BILLINGDOCUMENT, k.ORIGINAL_BILLINGDOCUMENT)'),
        ('ORDER_ID', 'COALESCE(q.ORDER_ID, k.ORDER_ID)'),
        ('_key_ZMSFSUBSCRIPTION', 'k._key_ZMSFSUBSCRIPTION'),
        ('ORDER_LINE_NUMBER', 'q.ORDER_LINE_NUMBER'),
        ('ORIGINAL_BILLINGDOCUMENTITEM', 'q.ORIGINAL_BILLINGDOCUMENTITEM'),
        ('SIMULATION_ONLY', 'q.SIMULATION_ONLY'),
    )
    invoice = invoice.replace('    k.SUBSCRIPTION_ID, k.SERVICE_FROM, k.SERVICE_TO_EXCLUSIVE,\n'
        '    COALESCE(q.ORIGINAL_BILLINGDOCUMENT, k.ORIGINAL_BILLINGDOCUMENT) AS ORIGINAL_BILLINGDOCUMENT,\n'
        '    COALESCE(q.ORDER_ID, k.ORDER_ID) AS ORDER_ID, k._key_ZMSFSUBSCRIPTION,\n'
        '    q.ORDER_LINE_NUMBER, q.ORIGINAL_BILLINGDOCUMENTITEM, q.SIMULATION_ONLY,',
        '    ' + ',\n    '.join('CASE WHEN ' + bridge_safe + ' THEN ' + expression + ' END AS ' + ident(name)
                                for name, expression in resolved) + ',')
    mismatch = 'q.source_rows IS NOT NULL AND CASE WHEN ' + order_valid + ' THEN 0 ELSE 1 END = 1'
    invoice = invoice.replace("      ELSE 'matched' END AS billing_mapping_status",
        "      WHEN " + mismatch + " THEN 'order_customer_mismatch'\n      ELSE 'matched' END AS billing_mapping_status")
    invoice = invoice.replace("      WHEN q.BILLINGDOCUMENT IS NOT NULL THEN 'operational_order'",
        "      WHEN " + mismatch + " THEN 'invalid_order'\n      WHEN q.BILLINGDOCUMENT IS NOT NULL THEN 'operational_order'")
    invoice = invoice.replace(' AS billing_linkage_type,\n',
        " AS billing_linkage_type,\n    CASE WHEN q.source_rows IS NULL THEN 'missing_order_link'\n"
        "      WHEN q.distinct_rows > 1 THEN 'ambiguous_order_link'\n"
        "      WHEN " + order_valid + " THEN 'matched' ELSE 'native_key_mismatch' END AS order_customer_mapping_status,\n")
    invoice_names = ('invoice_line',) + tuple(
        n + suffix for n in source_names for suffix in ('', '_distinct', '_counts', '_variants', '_safe'))
    subscription = 'SELECT ' + _projection(catalog, 'subscription', 's') + ',\n    ' + _state('s', 'l', 'p') + ''',
    l.CUSTOMER_KEY, l.SALESFORCE_CONTACT_ID AS source_customer_id,
    l._Delete AS native_crosswalk_delete_marker,
    p.[Key] AS native_plan_key, p._Delete AS native_plan_delete_marker,
    p.MONTHLY_NET, p.VAT_RATE, p.CURRENCY, p.CONTRACT_ID, p.CONTRACT_VERSION,
    p.VALID_FROM AS plan_valid_from, p.VALID_TO_EXCLUSIVE AS plan_valid_to_exclusive,
    CASE WHEN l.distinct_rows > 1 THEN 'ambiguous_crosswalk'
      WHEN l.CUSTOMER_KEY IS NULL THEN 'missing_crosswalk' ELSE 'matched' END AS customer_mapping_status,
    CASE WHEN p.distinct_rows > 1 THEN 'ambiguous_plan_version'
      WHEN p.PLAN_ID IS NULL THEN 'missing_plan_version' ELSE 'matched' END AS plan_mapping_status,
    ''' + _cardinality_fields((('customer_link', 'l'), ('plan', 'p'))) + '''
FROM subscription s
LEFT JOIN customer_link_safe l ON l._SystemName = s._SystemName AND l.CUSTOMER = s.CUSTOMER
LEFT JOIN plan_safe p ON p._SystemName = s._SystemName
 AND p.PLAN_ID = s.PLAN_ID AND p.VERSION = s.PLAN_VERSION
WHERE s._SystemName IS NOT NULL AND s.[Key] <> -1'''
    subscription_sources = (('customer_link', ('_SystemName', 'CUSTOMER')),
                            ('plan', ('_SystemName', 'PLAN_ID', 'VERSION')))
    # Unknown/NULL plan keys were never eligible; exclude before counting, not
    # after conflict resolution (which intentionally NULLs non-grain columns).
    subscription_base = _invoice_sources(catalog, {**base,
        'plan': 'SELECT ' + ', '.join(ident(r['COLUMN_NAME']) for r in sorted(catalog,
            key=lambda r: r['COLUMN_NAME']) if r['TABLE_SCHEMA'] == 'dbo'
            and r['TABLE_NAME'] == TABLES['plan']
            and r['COLUMN_NAME'].casefold() not in TRANSPORT_COLUMNS)
        + '\nFROM (\n' + base['plan'] + '\n) eligible_plan WHERE [Key] <> -1'}, subscription_sources)
    subscription_names = ('subscription',) + tuple(n + suffix for n, _ in subscription_sources
        for suffix in ('', '_distinct', '_counts', '_variants', '_safe'))
    return {**business_views(base),
        'customer_invoice_item': _with(invoice_base, invoice_names, invoice),
        'subscription_contract': _with(subscription_base, subscription_names, subscription),
        'calendar': _with(base, ('fiscal_period',), 'SELECT ' + _projection(catalog, 'fiscal_period', 'p') + ',\n    ' + _state('p') + '''
FROM fiscal_period p
WHERE p.[Key] <> -1 AND p._SystemName IS NOT NULL
 AND NULLIF(p.FISCALYEARVARIANT, '') IS NOT NULL AND p.FISCALYEAR > 0
 AND p.FISCALPERIOD > 0 AND p.FISCALYEARPERIOD > 0
 AND p.FISCALPERIODSTARTDATE <= p.FISCALPERIODENDDATE'''),
        'account_roles': _with(base, ('gl_account',), 'SELECT ' + _projection(catalog, 'gl_account', 'a')
            + ',\n    ' + _state('a') + ',\n    CASE a.GLACCOUNT\n'
            + '\n'.join('      WHEN ' + literal(code) + ' THEN ' + literal(role)
                        for role, (code, _, _) in ACCOUNTS.items())
            + '\n    END AS account_role,\n    CASE WHEN a.GLACCOUNT IS NULL THEN \'missing_gl_account\'\n'
            + '      WHEN a.GLACCOUNT IN (' + ', '.join(literal(v[0]) for v in ACCOUNTS.values())
            + ") THEN 'matched' ELSE 'unmapped_gl_account' END AS account_mapping_status\nFROM gl_account a\nWHERE a.[Key] <> -1 AND a.CHARTOFACCOUNTS = " + literal(CHART)),
    }


def function_selects(catalog, base):
    """Exact inline-TVF bodies. Bind @as_of as date; no inferred/default cutoff.

    The account-role rules are the explicit MSFX subscription/operational simulation,
    not universal SAP classifications. Unlike the old 0L-only interface, monthly
    totals keep SOURCELEDGER in the grain; consumers choose a ledger explicitly.
    """
    validate_catalog(catalog)
    def amount(roles):
        codes = ', '.join(literal(ACCOUNTS[r][0]) for r in roles)
        condition = 'g.GLACCOUNT IN (' + codes + ')'
        return ('(CASE WHEN SUM(CASE WHEN ' + condition
                + ' AND g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) > 0 THEN NULL ELSE '
                + 'SUM(CASE WHEN ' + condition + ' THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) END)')

    measures = [
        ('recognized_subscription_revenue', ('revenue',), '-'),
        ('recognized_tvod_revenue', ('revenue_tvod',), '-'),
        ('recognized_est_revenue', ('revenue_est',), '-'),
        ('recognized_operational_revenue', ('revenue_tvod', 'revenue_est'), '-'),
        ('recognized_total_revenue', ('revenue', 'revenue_tvod', 'revenue_est'), '-'),
        ('subscription_content_expense', ('content_cost',), ''),
        ('operational_content_expense', ('operational_content_cost',), ''),
        ('content_expense', ('content_cost', 'operational_content_cost'), ''),
        ('contribution_after_content_cost_only', ('revenue', 'revenue_tvod', 'revenue_est', 'content_cost', 'operational_content_cost'), '-'),
        ('net_bank_movement', ('bank',), ''),
        ('output_vat_liability', ('output_vat',), '-'),
        ('input_vat_recoverable', ('input_vat',), ''),
        ('net_vat_liability', ('output_vat', 'input_vat'), '-'),
        ('deferred_subscription_liability', ('deferred_revenue',), '-'),
        ('deferred_tvod_liability', ('deferred_tvod',), '-'),
        ('deferred_est_liability', ('deferred_est',), '-'),
        ('deferred_operational_liability', ('deferred_tvod', 'deferred_est'), '-'),
        ('deferred_total_liability', ('deferred_revenue', 'deferred_tvod', 'deferred_est'), '-'),
    ]
    known_accounts = ', '.join(literal(v[0]) for v in ACCOUNTS.values())
    excluded = '(g.GLACCOUNT IS NULL OR g.GLACCOUNT NOT IN (' + known_accounts + '))'
    completeness = (
        "SUM(CASE WHEN g.GLACCOUNT IS NULL THEN 1 ELSE 0 END) AS missing_gl_account_rows,\n    "
        + 'SUM(CASE WHEN g.GLACCOUNT NOT IN (' + known_accounts + ') THEN 1 ELSE 0 END) AS unmapped_gl_account_rows,\n    '
        + 'SUM(CASE WHEN ' + excluded + ' THEN 1 ELSE 0 END) AS excluded_account_rows,\n    '
        + 'SUM(CASE WHEN ' + excluded + ' AND g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) AS excluded_account_missing_amount_rows,\n    '
        + 'CASE WHEN SUM(CASE WHEN ' + excluded + ' AND g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) > 0 THEN NULL\n'
        + '      ELSE SUM(CASE WHEN ' + excluded + ' THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) END AS excluded_account_signed_amount,\n    '
        + 'CASE WHEN SUM(CASE WHEN ' + excluded + " THEN 1 ELSE 0 END) > 0 THEN 'incomplete_account_mapping'\n"
        + "      ELSE 'complete_account_mapping' END AS account_completeness_status,\n    "
    )
    monthly = '''SELECT g._SystemName, g.COMPANYCODE, g.SOURCELEDGER, g.CHARTOFACCOUNTS,
    @as_of AS as_of, YEAR(g.POSTINGDATE) AS calendar_year, MONTH(g.POSTINGDATE) AS calendar_month,
    g.FISCALYEARVARIANT, g.FISCALYEAR, g.FISCALPERIOD, g.TRANSACTIONCURRENCY AS currency,
    g._Delete AS native_fact_delete_marker, COUNT_BIG(*) AS journal_lines,
    SUM(CASE WHEN g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) AS missing_amount_rows,
    ''' + completeness + _state('g') + ',\n    ' + ',\n    '.join(sign + amount(roles) + ' AS ' + name for name, roles, sign in measures) + '''
FROM gl_line g
WHERE g.POSTINGDATE <= @as_of AND g.CHARTOFACCOUNTS = ''' + literal(CHART) + '''
GROUP BY g._SystemName, g.COMPANYCODE, g.SOURCELEDGER, g.CHARTOFACCOUNTS,
    YEAR(g.POSTINGDATE), MONTH(g.POSTINGDATE), g.FISCALYEARVARIANT,
    g.FISCALYEAR, g.FISCALPERIOD, g.TRANSACTIONCURRENCY, g._Delete'''
    ar = 'SELECT ' + _projection(catalog, 'operational_item', 'o') + ',\n    ' + _state('o', 'c', 'l') + ''',
    @as_of AS as_of, o.AMOUNTINTRANSACTIONCURRENCY AS outstanding_signed,
    ''' + _customer_fields('o', 'CUSTOMER') + '''
FROM operational_item o
''' + _customer_join('o', 'CUSTOMER', '_key_ICUSTOMER') + '''
WHERE o.FINANCIALACCOUNTTYPE = 'D' AND o.POSTINGDATE <= @as_of
 AND (o.CLEARINGDATE IS NULL OR o.CLEARINGDATE > @as_of)'''
    ar_sources = (('customer', ('_SystemName', 'Key')),
                  ('customer_link', ('_SystemName', 'CUSTOMER')))
    ar_base = _invoice_sources(catalog, base, ar_sources)
    ar_names = ('operational_item',) + tuple(
        n + suffix for n, _ in ar_sources for suffix in ('', '_distinct', '_counts', '_variants', '_safe'))
    ar = ar.replace('JOIN customer c', 'JOIN customer_safe c').replace(
        'JOIN customer_link l', 'JOIN customer_link_safe l')
    ar = ar.replace('(c._SystemName = o._SystemName OR (c.[Key] = -1 AND c._SystemName IS NULL))',
        '((c.[Key] <> -1 AND c._SystemName = o._SystemName) OR (c.[Key] = -1 AND c._SystemName IS NULL))')
    ar = ar.replace("CASE WHEN c.[Key] IS NULL", "CASE WHEN c.distinct_rows > 1 THEN 'ambiguous_native_customer'\n"
        "      WHEN l.distinct_rows > 1 THEN 'ambiguous_crosswalk'\n      WHEN c.[Key] IS NULL")
    ar = ar.replace('FROM operational_item o', ',\n    ' + _cardinality_fields(
        (('customer', 'c'), ('customer_link', 'l'))) + '\nFROM operational_item o')
    ap = 'SELECT ' + _projection(catalog, 'operational_item', 'o') + ',\n    ' + _state('o') + ''',
    @as_of AS as_of, -o.AMOUNTINTRANSACTIONCURRENCY AS outstanding_payable_signed
FROM operational_item o
WHERE o.FINANCIALACCOUNTTYPE = 'K' AND o.POSTINGDATE <= @as_of
 AND (o.CLEARINGDATE IS NULL OR o.CLEARINGDATE > @as_of)'''
    # UNION defines the scope/currency spine, never deduplicates monetary facts.
    # No ledger join: operational items have no SOURCELEDGER in the native schema.
    balance_base = {**base,
        'company_markers': '''SELECT _SystemName, COMPANYCODE,
    SUM(CASE WHEN _Delete IS NULL OR _Delete <> '' THEN 1 ELSE 0 END) AS unverified_marker_rows
FROM company GROUP BY _SystemName, COMPANYCODE''',
        'scopes': '''SELECT _SystemName, COMPANYCODE, CURRENCY AS currency FROM company
WHERE _SystemName IS NOT NULL AND COMPANYCODE IS NOT NULL AND @as_of IS NOT NULL
UNION
SELECT _SystemName, COMPANYCODE, TRANSACTIONCURRENCY FROM operational_item WHERE POSTINGDATE <= @as_of
UNION
SELECT _SystemName, COMPANYCODE, TRANSACTIONCURRENCY FROM gl_line WHERE POSTINGDATE <= @as_of''',
        'open_totals': '''SELECT _SystemName, COMPANYCODE, TRANSACTIONCURRENCY AS currency,
    SUM(CASE WHEN FINANCIALACCOUNTTYPE = 'D' THEN AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) AS ar_amount,
    -SUM(CASE WHEN FINANCIALACCOUNTTYPE = 'K' THEN AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) AS ap_amount,
    SUM(CASE WHEN FINANCIALACCOUNTTYPE = 'D' AND AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) AS ar_missing,
    SUM(CASE WHEN FINANCIALACCOUNTTYPE = 'K' AND AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) AS ap_missing,
    SUM(CASE WHEN _Delete IS NULL OR _Delete <> '' THEN 1 ELSE 0 END) AS unverified_marker_rows,
    COUNT_BIG(*) AS open_item_rows
FROM operational_item
WHERE POSTINGDATE <= @as_of AND (CLEARINGDATE IS NULL OR CLEARINGDATE > @as_of)
 AND FINANCIALACCOUNTTYPE IN ('D', 'K')
GROUP BY _SystemName, COMPANYCODE, TRANSACTIONCURRENCY'''}
    balances = '''SELECT s._SystemName, s.COMPANYCODE, s.currency, @as_of AS as_of,
    CASE WHEN t.ar_missing > 0 THEN NULL ELSE COALESCE(t.ar_amount, 0) END AS receivables_outstanding,
    CASE WHEN t.ap_missing > 0 THEN NULL ELSE COALESCE(t.ap_amount, 0) END AS payables_outstanding,
    COALESCE(t.ar_missing, 0) AS ar_missing_amount_rows,
    COALESCE(t.ap_missing, 0) AS ap_missing_amount_rows,
    COALESCE(t.unverified_marker_rows, 0) AS unverified_marker_rows,
    COALESCE(c.unverified_marker_rows, 0) AS scope_unverified_marker_rows,
    CASE WHEN c.COMPANYCODE IS NULL OR c.unverified_marker_rows > 0 OR t.unverified_marker_rows > 0
      THEN 'unverified_native_markers' ELSE 'observed_blank_markers' END AS native_state_status,
    COALESCE(t.open_item_rows, 0) AS open_item_rows
FROM scopes s
LEFT JOIN company_markers c ON c._SystemName = s._SystemName AND c.COMPANYCODE = s.COMPANYCODE
LEFT JOIN open_totals t ON t._SystemName = s._SystemName AND t.COMPANYCODE = s.COMPANYCODE
 AND (t.currency = s.currency OR (t.currency IS NULL AND s.currency IS NULL))'''
    return {
        'monthly_finance': _with(base, ('gl_line',), monthly),
        'ar_open_items': _with(ar_base, ar_names, ar),
        'ap_open_items': _with(base, ('operational_item',), ap),
        'balances': _with(balance_base, ('company', 'operational_item', 'gl_line', 'company_markers', 'scopes', 'open_totals'), balances),
        'payment_journal': _with(base, ('gl_line',), 'SELECT ' + _projection(catalog, 'gl_line', 'g') + ',\n    ' + _state('g') + ''',
    @as_of AS as_of
FROM gl_line g
WHERE g.ACCOUNTINGDOCUMENTTYPE IN ('DZ', 'DA', 'KZ') AND g.POSTINGDATE <= @as_of'''),
    }


def raw_views(catalog, database, system, company):
    """Deterministic explicit raw SELECTs; schema inventory is supplied by caller."""
    for table in TABLES.values():
        columns = {r['COLUMN_NAME'] for r in catalog
                   if r['TABLE_SCHEMA'] == 'dbo' and r['TABLE_NAME'] == table}
        if not {'_SystemName', '_Delete'} <= columns:
            raise ValueError('Missing native column contract: ' + table)
    ordered = sorted((r for r in catalog if r['COLUMN_NAME'].casefold() not in TRANSPORT_COLUMNS),
                     key=lambda r: (r['TABLE_SCHEMA'], r['TABLE_NAME'], r['COLUMN_NAME']))
    return source_views(ordered, database, system, company, TABLES)


def render_bundle(catalog, database, system, company):
    """Render v1 DDL only. Caller owns authorization, preflight and execution.

    Source projections are repeated in business CTEs so every interface reads
    native BPS directly. No warehouse materialization or implicit cutoff.
    """
    validate_catalog(catalog)
    base = raw_views(catalog, database, system, company)
    batches = [
        '-- SAP live serving v1: query-time native state, not historical snapshots.\n'
        '-- Review schema, mapping cardinality and native marker semantics before use.\n'
        '-- Nonblank/NULL _Delete markers are unverified, not assumed deleted.\n'
        '-- Monthly/payment retain SOURCELEDGER; filter 0L for legacy-ledger comparisons.\n'
        '-- Account roles are the explicit MSFX simulation, not universal SAP classifications.\n'
        '-- Examples invoice_customer/gl_account_balance preserve measures with cardinality-safe mappings.\n'
        "IF SCHEMA_ID('sap_live') IS NULL EXEC('CREATE SCHEMA [sap_live]');"
    ]
    for name, body in {**base, **serving_views(catalog, base)}.items():
        batches.append('CREATE OR ALTER VIEW [sap_live].' + ident(name) + ' AS\n' + body + ';')
    for name, body in function_selects(catalog, base).items():
        batches.append('CREATE OR ALTER FUNCTION [sap_live].' + ident(name)
                       + '(@as_of date)\nRETURNS TABLE\nAS RETURN (\n' + body + '\n);')
    return '\n-- @batch\n'.join(batches) + '\n'
