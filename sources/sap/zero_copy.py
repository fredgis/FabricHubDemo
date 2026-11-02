"""Render SELECT-only source projections; no network or deployment side effects."""
from __future__ import annotations

import re


def grouped_sources(base, contracts):
    """One row per join grain; only a unique full projected row may resolve.

    Counts preserve duplicate evidence. Conflicts retain grain but NULL every
    non-grain field, never choosing MAX/MIN/ROW_NUMBER as a winner.
    """
    result = dict(base)
    for name, keys, columns in contracts:
        key_sql = ', '.join(map(ident, keys))
        result[name + '_distinct'] = 'SELECT DISTINCT ' + ', '.join(map(ident, columns)) + '\nFROM ' + ident(name)
        result[name + '_counts'] = ('SELECT ' + key_sql + ', COUNT_BIG(*) AS source_rows\nFROM '
                                  + ident(name) + '\nGROUP BY ' + key_sql)
        result[name + '_variants'] = ('SELECT ' + key_sql + ', COUNT_BIG(*) AS distinct_rows\nFROM '
                                    + ident(name + '_distinct') + '\nGROUP BY ' + key_sql)
        def equal(a, b):
            return ' AND '.join(
                f'({a}.{ident(k)} = {b}.{ident(k)} OR ({a}.{ident(k)} IS NULL AND {b}.{ident(k)} IS NULL))'
                for k in keys)
        result[name + '_safe'] = ('SELECT ' + ', '.join(
            ('n.' if c in keys else 'd.') + ident(c) for c in columns)
            + ', n.source_rows, v.distinct_rows\nFROM ' + ident(name + '_counts') + ' n\nJOIN '
            + ident(name + '_variants') + ' v ON ' + equal('n', 'v') + '\nLEFT JOIN '
            + ident(name + '_distinct') + ' d ON v.distinct_rows = 1 AND ' + equal('n', 'd'))
    return result


def cardinality_fields(sources):
    return ',\n    '.join(f'''COALESCE({alias}.source_rows, 0) AS {name}_source_rows,
    COALESCE({alias}.distinct_rows, 0) AS {name}_distinct_rows,
    CASE WHEN {alias}.source_rows IS NULL THEN 'missing'
      WHEN {alias}.distinct_rows > 1 THEN 'conflicting_matches'
      WHEN {alias}.source_rows > 1 THEN 'identical_duplicates'
      ELSE 'unique' END AS {name}_cardinality_status''' for name, alias in sources)


def _legacy_sources(base, sources):
    contracts = []
    for name, keys in sources:
        columns = sorted(set(c.replace(']]', ']') for c in
                             re.findall(r's\.\[((?:[^\]]|\]\])+)\]', base[name].split('\nFROM ')[0])))
        if not set(keys) <= set(columns):
            raise ValueError('Missing explicit source projection: ' + name)
        contracts.append((name, keys, columns))
    result = grouped_sources(base, contracts)
    names = tuple(n + suffix for n, _ in sources
                  for suffix in ('', '_distinct', '_counts', '_variants', '_safe'))
    return result, names


def _legacy_with(base, names, body):
    return 'WITH ' + ',\n'.join(ident(n) + ' AS (\n' + base[n] + '\n)' for n in names) + '\n' + body

TABLES = {
    'gl_line': 'I_GLACCOUNTLINEITEMRAWDATA',
    'operational_item': 'I_OPERATIONALACCTGDOCITEM',
    'invoice_line': 'C_BILLINGDOCITEMBASICDEX_1',
    'company': 'I_COMPANYCODE',
    'gl_account': 'I_GLACCOUNTINCHARTOFACCOUNTS',
    'fiscal_period': 'I_FISCALPERIODFORVARIANT',
    'customer': 'I_CUSTOMER',
    'supplier': 'I_SUPPLIER',
    'customer_link': 'ZMSF_CUSTOMER_LINK',
}


def business_views(base):
    """Readable zero-copy examples, not a replacement for every BPS measure.

    Preserve unmatched facts via LEFT JOIN. Identical dimension records collapse
    at the join grain; conflicting full records remain unresolved with cardinality
    diagnostics. Facts and their monetary values are never deduplicated.
    """
    invoice = ('WITH invoice_line AS (' + base['invoice_line'] + '),\n'
               'customer AS (' + base['customer'] + '),\n'
               'customer_link AS (' + base['customer_link'] + ')\n' + '''SELECT
    b._SystemName, b.COMPANYCODE, b.BILLINGDOCUMENT, b.BILLINGDOCUMENTITEM,
    b.ACCOUNTINGDOCUMENT, b.BILLINGDOCUMENTDATE, b.BILLINGDOCUMENTCATEGORY,
    b.SOLDTOPARTY, b.PRODUCT, b.TRANSACTIONCURRENCY,
    b.NETAMOUNT, b.TAXAMOUNT, b.GROSSAMOUNT,
    b.[_key_ICUSTOMERSoldToParty], c.[Key] AS native_customer_key,
    c.CUSTOMERNAME AS sap_customer_name, l.CUSTOMER_KEY AS mapped_customer_key,
    l.SALESFORCE_CONTACT_ID, m.customer_key AS shared_customer_key,
    m.name AS shared_customer_name,
    CASE
      WHEN c.[Key] IS NULL OR c.[Key] = -1 THEN 'missing_native_customer'
      WHEN c.CUSTOMER <> b.SOLDTOPARTY OR c.CUSTOMER IS NULL
        OR b.SOLDTOPARTY IS NULL THEN 'native_key_mismatch'
      WHEN l.CUSTOMER_KEY IS NULL THEN 'missing_crosswalk'
      WHEN m.customer_key IS NULL THEN 'missing_shared_customer'
      WHEN m.source_customer_id IS NULL OR l.SALESFORCE_CONTACT_ID IS NULL
        OR m.source_customer_id <> l.SALESFORCE_CONTACT_ID THEN 'crm_id_mismatch'
      ELSE 'matched' END AS customer_mapping_status,
    b._UpdateTimeStamp AS native_update_timestamp,
    b._Delete AS native_fact_delete_marker,
    c._Delete AS native_customer_delete_marker,
    l._Delete AS native_crosswalk_delete_marker
FROM invoice_line b
LEFT JOIN customer c ON c.[Key] = b.[_key_ICUSTOMERSoldToParty]
 AND (c._SystemName = b._SystemName OR (c.[Key] = -1 AND c._SystemName IS NULL))
LEFT JOIN customer_link l ON l._SystemName = c._SystemName AND l.CUSTOMER = c.CUSTOMER
LEFT JOIN gold.dim_customer m ON m.customer_key = l.CUSTOMER_KEY''')
    balance = ('WITH gl_line AS (' + base['gl_line'] + '),\n'
               'gl_account AS (' + base['gl_account'] + ')\n' + '''SELECT
    g._SystemName, g.COMPANYCODE, g.SOURCELEDGER,
    g.FISCALYEARVARIANT, g.FISCALYEAR, g.FISCALPERIOD,
    g.CHARTOFACCOUNTS, g.GLACCOUNT, g.TRANSACTIONCURRENCY,
    g.[_key_IGLACCOUNTINCHARTOFACCOUNTS], a.[Key] AS native_account_key,
    a.GLACCOUNTTYPE, g._Delete AS native_fact_delete_marker,
    a._Delete AS native_account_delete_marker,
    COUNT_BIG(*) AS journal_lines,
    SUM(g.AMOUNTINTRANSACTIONCURRENCY) AS signed_movement,
    SUM(ABS(g.AMOUNTINTRANSACTIONCURRENCY)) AS absolute_movement,
    MAX(g._UpdateTimeStamp) AS native_update_timestamp,
    CASE WHEN a.[Key] IS NULL OR a.[Key] = -1 THEN 'missing_native_account'
      WHEN a.GLACCOUNT <> g.GLACCOUNT OR a.CHARTOFACCOUNTS <> g.CHARTOFACCOUNTS
        OR a.GLACCOUNT IS NULL OR a.CHARTOFACCOUNTS IS NULL
        OR g.GLACCOUNT IS NULL OR g.CHARTOFACCOUNTS IS NULL THEN 'native_key_mismatch'
      ELSE 'matched' END AS account_mapping_status
FROM gl_line g
LEFT JOIN gl_account a ON a.[Key] = g.[_key_IGLACCOUNTINCHARTOFACCOUNTS]
 AND (a._SystemName = g._SystemName OR (a.[Key] = -1 AND a._SystemName IS NULL))
GROUP BY g._SystemName, g.COMPANYCODE, g.SOURCELEDGER,
    g.FISCALYEARVARIANT, g.FISCALYEAR, g.FISCALPERIOD,
    g.CHARTOFACCOUNTS, g.GLACCOUNT, g.TRANSACTIONCURRENCY,
    g.[_key_IGLACCOUNTINCHARTOFACCOUNTS], a.[Key], a.GLACCOUNTTYPE,
    a.GLACCOUNT, a.CHARTOFACCOUNTS, g._Delete, a._Delete''')
    invoice_base, invoice_names = _legacy_sources(base, (
        ('customer', ('_SystemName', 'Key')),
        ('customer_link', ('_SystemName', 'CUSTOMER'))))
    invoice_base['shared_customer'] = 'SELECT customer_key, source_customer_id, name FROM gold.dim_customer'
    invoice_base = grouped_sources(invoice_base, (
        ('shared_customer', ('customer_key',), ('customer_key', 'source_customer_id', 'name')),))
    invoice_names += tuple('shared_customer' + s for s in ('', '_distinct', '_counts', '_variants', '_safe'))
    invoice = invoice[invoice.index('SELECT\n'):]
    invoice = invoice.replace('JOIN customer c', 'JOIN customer_safe c').replace(
        'JOIN customer_link l', 'JOIN customer_link_safe l').replace(
        'JOIN gold.dim_customer m', 'JOIN shared_customer_safe m')
    invoice = invoice.replace('(c._SystemName = b._SystemName OR (c.[Key] = -1 AND c._SystemName IS NULL))',
        '((c.[Key] <> -1 AND c._SystemName = b._SystemName) OR (c.[Key] = -1 AND c._SystemName IS NULL))')
    invoice = invoice.replace('CASE\n      WHEN', "CASE\n      WHEN c.distinct_rows > 1 THEN 'ambiguous_native_customer'\n"
        "      WHEN l.distinct_rows > 1 THEN 'ambiguous_crosswalk'\n"
        "      WHEN m.distinct_rows > 1 THEN 'ambiguous_shared_customer'\n      WHEN", 1)
    # Grain keys remain for diagnostics; unresolved shared identities do not resolve.
    invoice = invoice.replace('m.customer_key AS shared_customer_key',
        'CASE WHEN m.distinct_rows = 1 THEN m.customer_key END AS shared_customer_key')
    invoice = invoice.replace('FROM invoice_line b', ',\n    ' + cardinality_fields(
        (('customer', 'c'), ('customer_link', 'l'), ('shared_customer', 'm'))) + '\nFROM invoice_line b')
    balance_base, balance_names = _legacy_sources(base, (('gl_account', ('_SystemName', 'Key')),))
    balance = balance[balance.index('SELECT\n'):].replace('JOIN gl_account a', 'JOIN gl_account_safe a')
    balance = balance.replace('(a._SystemName = g._SystemName OR (a.[Key] = -1 AND a._SystemName IS NULL))',
        '((a.[Key] <> -1 AND a._SystemName = g._SystemName) OR (a.[Key] = -1 AND a._SystemName IS NULL))')
    balance = balance.replace('CASE WHEN a.[Key] IS NULL',
        "CASE WHEN a.distinct_rows > 1 THEN 'ambiguous_native_account'\n      WHEN a.[Key] IS NULL")
    balance = balance.replace('FROM gl_line g', ',\n    ' + cardinality_fields((('gl_account', 'a'),)) + '\nFROM gl_line g')
    balance += ', a.source_rows, a.distinct_rows'
    return {'invoice_customer': _legacy_with(invoice_base, ('invoice_line',) + invoice_names, invoice),
            'gl_account_balance': _legacy_with(balance_base, ('gl_line',) + balance_names, balance)}



def ident(value):
    if not isinstance(value, str) or not value or len(value) > 128 or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid SQL identifier')
    return '[' + value.replace(']', ']]') + ']'


def literal(value):
    if not isinstance(value, str) or not value or len(value) > 128 or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid scope value')
    return "'" + value.replace("'", "''") + "'"


def source_views(catalog, database, system, company, tables):
    """Preserve supplied columns, including native surrogate references.

    company accepts an existing scalar code or a nonempty list/tuple of exact
    approved codes (1710/1720/1730). No currency conversion or inferred scope.

    Dimensions retain their native global unknown member; no fabricated member,
    aggregate, casts, deduplication, delete filtering or replacement of source keys.
    Schema changes require regenerating/reviewing the explicit column contract.
    """
    companies = (company,) if isinstance(company, str) else company
    if (not isinstance(companies, (tuple, list)) or not companies
            or any(c not in ('1710', '1720', '1730') for c in companies)
            or len(set(companies)) != len(companies)):
        raise ValueError('Invalid approved company scope')
    companies = sorted(companies)
    views = {}
    for view, table in tables.items():
        columns = [r['COLUMN_NAME'] for r in catalog
                   if r['TABLE_SCHEMA'] == 'dbo' and r['TABLE_NAME'] == table]
        if not columns or len(set(columns)) != len(columns) or '_SystemName' not in columns:
            raise ValueError('Missing/duplicate native column contract: ' + table)
        where = 's.[_SystemName] = ' + literal(system)
        if 'COMPANYCODE' in columns:
            where += (' AND s.[COMPANYCODE] = ' + literal(companies[0]) if len(companies) == 1
                      else ' AND s.[COMPANYCODE] IN (' + ', '.join(map(literal, companies)) + ')')
        if 'Key' in columns:
            where = '(' + where + ') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL)'
        select = ',\n       '.join('s.' + ident(c) for c in columns)
        views[view] = ('SELECT ' + select + '\nFROM ' + ident(database) + '.[dbo].' + ident(table)
                       + ' AS s\nWHERE ' + where)
    return views


def render_bundle(views):
    """Preview only. CREATE (not ALTER) refuses to overwrite an existing object.

    -- @batch separates execution batches; review and authorize before deployment.
    This function renders text only and is not an arbitrary SQL execution API.
    """
    batches = ["-- Candidate DDL: not executed; no source/target business data copied.\n"
               "-- Revalidate permissions, source state, schema and joins before use.\n"
               "IF SCHEMA_ID('sap_live') IS NULL EXEC('CREATE SCHEMA [sap_live]');"]
    for name, select in views.items():
        batches.append('CREATE VIEW [sap_live].' + ident(name) + ' AS\n' + select + ';')
    return '\n-- @batch\n'.join(batches) + '\n'

