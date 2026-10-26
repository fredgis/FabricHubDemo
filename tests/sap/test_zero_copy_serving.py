"""Executable SQLite semantics, not Fabric/T-SQL capability validation."""
import importlib
import importlib.util
import re
import sqlite3
import unittest
from pathlib import Path

from sources.sap.zero_copy import ident

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / 'fabric/gold/sap-live-serving.v1.sql'
EXPECTED_TABLES = {
    'gl_line': 'I_GLACCOUNTLINEITEMRAWDATA',
    'operational_item': 'I_OPERATIONALACCTGDOCITEM',
    'invoice_line': 'C_BILLINGDOCITEMBASICDEX_1',
    'company': 'I_COMPANYCODE',
    'gl_account': 'I_GLACCOUNTINCHARTOFACCOUNTS',
    'fiscal_period': 'I_FISCALPERIODFORVARIANT',
    'customer': 'I_CUSTOMER',
    'supplier': 'I_SUPPLIER',
    'customer_link': 'ZMSF_CUSTOMER_LINK',
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
ORDER_COLUMNS = ('BILLINGDOCUMENT BILLINGDOCUMENTITEM CUSTOMER ORDER_ID ORDER_LINE_NUMBER '
                 'ORIGINAL_BILLINGDOCUMENT ORIGINAL_BILLINGDOCUMENTITEM SIMULATION_ONLY '
                 '_SystemName _Delete _UpdateTimeStamp _key_ICUSTOMER').split()


def serving_contract():
    """Offline schema from explicit artifact projections, never ignored evidence."""
    raw = ARTIFACT.read_bytes()
    batches = raw.decode('utf-8').split('-- @batch\n')
    catalog = []
    historical = {k: v for k, v in EXPECTED_TABLES.items() if k != 'order_link'}
    for (name, table), batch in zip(historical.items(), batches[1:], strict=False):
        match = re.fullmatch(
            r'CREATE OR ALTER VIEW \[sap_live\]\.\[' + re.escape(name) + r'\] AS\n'
            r'SELECT (?P<columns>s\.\[\w+\](?:,\n       s\.\[\w+\])*)\n'
            r'FROM \[bps_gold_<system_suffix>\]\.\[dbo\]\.\[' + re.escape(table)
            + r'\] AS s\nWHERE [^\n]+;\n', batch)
        if match is None:
            raise AssertionError('Invalid serving projection: ' + name)
        catalog.extend({'TABLE_SCHEMA': 'dbo', 'TABLE_NAME': table, 'COLUMN_NAME': column}
                       for column in re.findall(r's\.\[(\w+)\]', match['columns']))
    catalog.extend({'TABLE_SCHEMA': 'dbo', 'TABLE_NAME': 'ZMSF_ORDER_LINK', 'COLUMN_NAME': c}
                   for c in ORDER_COLUMNS)
    return raw, catalog, batches


class ServingTests(unittest.TestCase):
    def test_complete_monetary_interface_inventory_and_join_cardinality(self):
        """Discover monetary interfaces, then exhaustively exercise their joins.

        Raw monetary views preserve physical records. Dimension duplicates must
        never alter fact measures; conflicting plan prices are intentionally NULL.
        Any added monetary interface or join requires an explicit audited entry.
        """
        from collections import Counter
        from sources.sap.accounting import ACCOUNTS, CHART
        m = self.module()
        _, catalog, _ = serving_contract()
        base = m.raw_views(catalog, 'native_db', 'S4M', ('1710', '1720', '1730'))
        interfaces = {**base, **m.serving_views(catalog, base), **m.function_selects(catalog, base)}
        monetary_columns = {r['COLUMN_NAME'] for r in catalog if re.search(
            r'AMOUNT|(?:^|_)NET(?:$|_)|^VAT_RATE$|^RATE$', r['COLUMN_NAME'])}
        discovered = {name for name, sql in interfaces.items() if any(
            re.search(r'\b' + re.escape(c) + r'\b', sql) for c in monetary_columns)}
        # name -> monetary output, input dimensions joined to this interface
        inventory = {
            'gl_line': ('AMOUNTINTRANSACTIONCURRENCY', ()),
            'operational_item': ('AMOUNTINTRANSACTIONCURRENCY', ()),
            'invoice_line': ('GROSSAMOUNT', ()),
            'plan': ('MONTHLY_NET', ()), 'rights_contract': ('FIXED_NET', ()),
            'contract_charge': ('CHARGE_NET', ()),
            'invoice_customer': ('GROSSAMOUNT', ('customer', 'customer_link', 'shared_customer')),
            'gl_account_balance': ('signed_movement', ('gl_account',)),
            'customer_invoice_item': ('GROSSAMOUNT', ('customer', 'customer_link', 'billing_link', 'order_link')),
            'subscription_contract': ('MONTHLY_NET', ('customer_link', 'plan')),
            'monthly_finance': ('recognized_total_revenue', ()),
            'ar_open_items': ('outstanding_signed', ('customer', 'customer_link')),
            'ap_open_items': ('outstanding_payable_signed', ()),
            'balances': ('receivables_outstanding', ('company',)),
            'payment_journal': ('AMOUNTINTRANSACTIONCURRENCY', ()),
        }
        self.assertEqual(discovered, set(inventory), 'every monetary interface needs an audit/fixture')
        common = {'_SystemName': 'S4M', '_Delete': '', '_UpdateTimeStamp': '2026-10-01'}
        invoice = {**common, 'COMPANYCODE': '1710', 'BILLINGDOCUMENT': 'B', 'BILLINGDOCUMENTITEM': 1,
                   'SOLDTOPARTY': 'C', '_key_ICUSTOMERSoldToParty': 1, 'NETAMOUNT': 100,
                   'TAXAMOUNT': 20, 'GROSSAMOUNT': 120, 'TRANSACTIONCURRENCY': 'EUR'}
        gl = {**common, 'COMPANYCODE': '1710', 'SOURCELEDGER': '0L', 'TRANSACTIONCURRENCY': 'EUR',
              'CHARTOFACCOUNTS': CHART, 'GLACCOUNT': ACCOUNTS['revenue'][0],
              '_key_IGLACCOUNTINCHARTOFACCOUNTS': 2, 'AMOUNTINTRANSACTIONCURRENCY': -100,
              'POSTINGDATE': '2026-10-01', 'ACCOUNTINGDOCUMENTTYPE': 'DZ', 'FISCALYEAR': 2026,
              'FISCALYEARVARIANT': 'K4', 'FISCALPERIOD': 10}
        fixtures = {
            'invoice_line': [invoice, dict(invoice)], 'gl_line': [gl, dict(gl)],
            'operational_item': [{**common, 'COMPANYCODE': '1710', 'POSTINGDATE': '2026-10-01',
                'FINANCIALACCOUNTTYPE': kind, 'AMOUNTINTRANSACTIONCURRENCY': value,
                'CUSTOMER': 'C', '_key_ICUSTOMER': 1, 'TRANSACTIONCURRENCY': 'EUR'}
                for kind, value in (('D', 120), ('D', 120), ('K', -60))],
            'customer': [{**common, 'Key': 1, 'CUSTOMER': 'C', 'CUSTOMERNAME': 'Native'}],
            'customer_link': [{**common, 'CUSTOMER': 'C', 'CUSTOMER_KEY': 'shared', 'SALESFORCE_CONTACT_ID': 'crm'}],
            'shared_customer': [{'customer_key': 'shared', 'name': 'Shared', 'source_customer_id': 'crm'}],
            'gl_account': [{**common, 'Key': 2, 'GLACCOUNT': gl['GLACCOUNT'], 'CHARTOFACCOUNTS': CHART, 'GLACCOUNTTYPE': 'P'}],
            'company': [{**common, 'Key': 3, 'COMPANYCODE': '1710', 'CURRENCY': 'EUR'}],
            'subscription': [{**common, 'Key': 4, 'CUSTOMER': 'C', 'PLAN_ID': 'P', 'PLAN_VERSION': '1'}],
            'plan': [{**common, 'Key': 5, 'PLAN_ID': 'P', 'VERSION': '1', 'MONTHLY_NET': 100, 'CURRENCY': 'EUR'}],
            'rights_contract': [{**common, 'Key': 6, 'FIXED_NET': 90}],
            'contract_charge': [{**common, 'COMPANYCODE': '1710', 'CHARGE_NET': 10}],
            'billing_link': [{**common, 'BILLINGDOCUMENT': 'B', 'BILLINGDOCUMENTITEM': 1, 'SUBSCRIPTION_ID': 'S'}],
            'order_link': [{**common, 'BILLINGDOCUMENT': 'B', 'BILLINGDOCUMENTITEM': 1,
                            'CUSTOMER': 'C', '_key_ICUSTOMER': 1, 'ORDER_ID': 'O'}],
        }
        conflict_field = {'customer': 'CUSTOMERNAME', 'customer_link': 'CUSTOMER_KEY',
                          'shared_customer': 'name', 'gl_account': 'GLACCOUNTTYPE',
                          'plan': 'MONTHLY_NET', 'company': '_Delete',
                          'billing_link': 'SUBSCRIPTION_ID', 'order_link': 'ORDER_ID'}
        grain = ('_SystemName', 'COMPANYCODE', 'SOURCELEDGER', 'TRANSACTIONCURRENCY', 'currency',
                 'BILLINGDOCUMENT', 'BILLINGDOCUMENTITEM', 'FISCALYEAR', 'FISCALPERIOD')
        for name, (measure, dimensions) in inventory.items():
            with self.subTest(interface=name):
                sql = interfaces[name]
                joins = [bracketed or plain for bracketed, plain in
                         re.findall(r'\bJOIN\s+(?:\[([^\]]+)\]|([\w.]+))', sql, re.I)]
                allowed = {d + suffix for d in dimensions if d != 'company'
                           for suffix in ('_safe', '_variants', '_distinct')}
                if name == 'balances':
                    allowed = {'company_markers', 'open_totals'}
                self.assertEqual(set(joins), allowed, 'unaudited join in ' + name)
                baseline = self.query(name, fixtures, '2026-10-01', ('1710', '1720', '1730'))
                self.assertTrue(baseline, 'inventory fixture must exercise ' + name)
                expected_baselines = {
                    'gl_line': (2, -200), 'operational_item': (3, 180), 'invoice_line': (2, 240),
                    'plan': (1, 100), 'rights_contract': (1, 90), 'contract_charge': (1, 10),
                    'invoice_customer': (2, 240), 'gl_account_balance': (1, -200),
                    'customer_invoice_item': (2, 240), 'subscription_contract': (1, 100),
                    'monthly_finance': (1, 200), 'ar_open_items': (2, 240),
                    'ap_open_items': (1, 60), 'balances': (1, 240), 'payment_journal': (2, -200),
                }
                self.assertEqual((len(baseline), sum(r[measure] for r in baseline)), expected_baselines[name])
                measure_fields = tuple(sorted(k for k in baseline[0] if
                    k in monetary_columns or k == measure or k in ('signed_movement', 'absolute_movement',
                    'receivables_outstanding', 'payables_outstanding', 'outstanding_signed',
                    'outstanding_payable_signed', 'journal_lines')))
                signature = lambda rows: Counter(tuple(r.get(k) for k in grain + measure_fields) for r in rows)
                for dimension in dimensions:
                    for conflict in (False, True):
                        changed = {k: [dict(r) for r in rows] for k, rows in fixtures.items()}
                        duplicate = dict(changed[dimension][0])
                        if conflict:
                            duplicate[conflict_field[dimension]] = 200 if dimension == 'plan' else 'OTHER'
                        changed[dimension].append(duplicate)
                        rows = self.query(name, changed, '2026-10-01', ('1710', '1720', '1730'))
                        self.assertEqual(len(rows), len(baseline), (name, dimension, conflict))
                        if conflict and dimension == 'plan':
                            self.assertTrue(all(r[measure] is None for r in rows))
                            self.assertTrue(all(r['plan_mapping_status'] == 'ambiguous_plan_version' for r in rows))
                        else:
                            self.assertEqual(signature(rows), signature(baseline), (name, dimension, conflict))

    def test_schema_drift_transport_metadata_not_in_serving_contract(self):
        m = self.module()
        _, catalog, _ = serving_contract()
        extra = [{'TABLE_SCHEMA': 'dbo', 'TABLE_NAME': table, 'COLUMN_NAME': c}
                 for table in EXPECTED_TABLES.values() for c in ('_COMMIT_VERSION', '_change_type')]
        expected = m.render_bundle(catalog, 'db', 'S4M', ('1710', '1720', '1730'))
        self.assertEqual(expected, m.render_bundle(catalog + extra, 'db', 'S4M', ('1710', '1720', '1730')))
        self.assertIn('[_key_ICUSTOMERSoldToParty]', expected)
        self.assertIn('[_Delete]', expected)

    def test_optional_bridge_markers_and_ambiguous_linkage_remain_explicit(self):
        fact = {'_SystemName': 'S4M', 'COMPANYCODE': '1710', 'BILLINGDOCUMENT': 'B',
                'BILLINGDOCUMENTITEM': '000001', 'SOLDTOPARTY': 'C', '_key_ICUSTOMERSoldToParty': 1, '_Delete': ''}
        order = {'_SystemName': 'S4M', 'BILLINGDOCUMENT': 'B', 'BILLINGDOCUMENTITEM': '000001',
                 'ORDER_ID': 'O', 'ORDER_LINE_NUMBER': 2, 'CUSTOMER': 'C', '_key_ICUSTOMER': 1, '_Delete': ''}
        fixtures = {'invoice_line': [fact], 'order_link': [order],
                    'customer': [{'_SystemName': 'S4M', 'Key': 1, 'CUSTOMER': 'C', '_Delete': ''}],
                    'customer_link': [{'_SystemName': 'S4M', 'CUSTOMER': 'C', 'CUSTOMER_KEY': 'shared', '_Delete': ''}]}
        row = self.query('customer_invoice_item', fixtures)[0]
        self.assertEqual(row['billing_mapping_status'], 'matched')
        self.assertEqual(row['billing_linkage_type'], 'operational_order')
        self.assertEqual(row['native_state_status'], 'observed_blank_markers')
        for marker in (None, 'X'):
            order['_Delete'] = marker
            self.assertEqual(self.query('customer_invoice_item', fixtures)[0]['native_state_status'], 'unverified_native_markers')
        order['_Delete'] = ''
        fixtures['billing_link'] = [{'_SystemName': 'S4M', 'BILLINGDOCUMENT': 'B', 'BILLINGDOCUMENTITEM': '000001', '_Delete': ''}]
        row = self.query('customer_invoice_item', fixtures)[0]
        self.assertEqual(row['billing_mapping_status'], 'ambiguous_billing_link')
        self.assertEqual(row['billing_linkage_type'], 'ambiguous')
        fixtures['order_link'] = []
        fixtures['billing_link'] = []
        row = self.query('customer_invoice_item', fixtures)[0]
        self.assertEqual(row['billing_linkage_type'], 'unlinked')
        self.assertEqual(row['billing_mapping_status'], 'missing_billing_link')
        self.assertEqual(row['native_state_status'], 'observed_blank_markers')

    def test_operational_account_measures_reconcile_by_company_currency_ledger(self):
        from sources.sap.accounting import ACCOUNTS, CHART
        amounts = {ACCOUNTS['revenue'][0]: -100, '0041000000': -30, '0042000000': -20,
                   ACCOUNTS['content_cost'][0]: 10, '0051000000': 5,
                   ACCOUNTS['deferred_revenue'][0]: -40, '0023100000': -8, '0023200000': -2}
        facts = []
        for company, currency, ledger in [('1710', 'EUR', '0L'), ('1720', 'CAD', '0L'),
                                          ('1730', 'CHF', '0L'), ('1710', 'EUR', '2L')]:
            facts += [{'_SystemName': 'S4M', 'COMPANYCODE': company, 'TRANSACTIONCURRENCY': currency,
                       'SOURCELEDGER': ledger, 'CHARTOFACCOUNTS': CHART, 'POSTINGDATE': '2026-10-01',
                       'GLACCOUNT': code, 'AMOUNTINTRANSACTIONCURRENCY': value, '_Delete': ''}
                      for code, value in amounts.items()]
        rows = self.query('monthly_finance', {'gl_line': facts}, '2026-10-01', ('1710', '1720', '1730'))
        self.assertEqual(len(rows), 4)
        for r in rows:
            self.assertEqual(r['recognized_subscription_revenue'], 100)
            self.assertEqual(r['recognized_tvod_revenue'], 30)
            self.assertEqual(r['recognized_est_revenue'], 20)
            self.assertEqual(r['recognized_operational_revenue'], 50)
            self.assertEqual(r['recognized_total_revenue'], 150)
            self.assertEqual(r['subscription_content_expense'], 10)
            self.assertEqual(r['operational_content_expense'], 5)
            self.assertEqual(r['content_expense'], 15)
            self.assertEqual(r['contribution_after_content_cost_only'], 135)
            self.assertEqual(r['deferred_subscription_liability'], 40)
            self.assertEqual(r['deferred_tvod_liability'], 8)
            self.assertEqual(r['deferred_est_liability'], 2)
            self.assertEqual(r['deferred_operational_liability'], 10)
            self.assertEqual(r['deferred_total_liability'], 50)
        accounts = [{'_SystemName': 'S4M', 'Key': i + 1, 'CHARTOFACCOUNTS': CHART, 'GLACCOUNT': c, '_Delete': ''}
                    for i, c in enumerate(('0041000000', '0042000000', '0023100000', '0023200000', '0051000000'))]
        roles = self.query('account_roles', {'gl_account': accounts})
        self.assertEqual({r['GLACCOUNT']: r['account_role'] for r in roles},
                         {'0041000000': 'revenue_tvod', '0042000000': 'revenue_est',
                          '0023100000': 'deferred_tvod', '0023200000': 'deferred_est',
                          '0051000000': 'operational_content_cost'})
        facts.append({**facts[0], 'GLACCOUNT': '0041000000', 'AMOUNTINTRANSACTIONCURRENCY': None})
        main = next(r for r in self.query('monthly_finance', {'gl_line': facts}, '2026-10-01',
                                         ('1710', '1720', '1730')) if r['COMPANYCODE'] == '1710' and r['SOURCELEDGER'] == '0L')
        self.assertIsNone(main['recognized_total_revenue'])
        self.assertIsNone(main['recognized_operational_revenue'])
        self.assertEqual(main['recognized_subscription_revenue'], 100)

    def test_expanded_invoice_baseline_order_credit_grain(self):
        fact = {'_SystemName': 'S4M', 'COMPANYCODE': '1710', 'BILLINGDOCUMENTITEM': '000001',
                'SOLDTOPARTY': 'C1', '_key_ICUSTOMERSoldToParty': 1, '_Delete': '', 'NETAMOUNT': 10}
        facts, baseline, orders = [], [], []
        for i in range(1092):
            company, currency = ('1710', 'EUR') if i < 553 else (('1720', 'CAD') if i < 811 else ('1730', 'CHF'))
            doc = 'B' + str(i)
            facts.append({**fact, 'COMPANYCODE': company, 'TRANSACTIONCURRENCY': currency, 'BILLINGDOCUMENT': doc})
            if i < 4:
                baseline.append({'_SystemName': 'S4M', 'BILLINGDOCUMENT': doc, 'BILLINGDOCUMENTITEM': '000001',
                                 'SUBSCRIPTION_ID': 'S1', '_Delete': ''})
            else:
                orders.append({'_SystemName': 'S4M', 'BILLINGDOCUMENT': doc, 'BILLINGDOCUMENTITEM': '000001',
                               'CUSTOMER': 'C1', '_key_ICUSTOMER': 1, 'ORDER_ID': 'O' + str(i),
                               'ORDER_LINE_NUMBER': 1, 'SIMULATION_ONLY': 'X', '_Delete': ''})
        orders[-1].update(ORIGINAL_BILLINGDOCUMENT='B1090', ORIGINAL_BILLINGDOCUMENTITEM='000001')
        facts[-1]['NETAMOUNT'] = -10
        fixtures = {'invoice_line': facts, 'billing_link': baseline, 'order_link': orders,
                    'customer': [{'_SystemName': 'S4M', 'Key': 1, 'CUSTOMER': 'C1', '_Delete': ''}],
                    'customer_link': [{'_SystemName': 'S4M', 'CUSTOMER': 'C1', 'CUSTOMER_KEY': 'shared', '_Delete': ''}]}
        rows = self.query('customer_invoice_item', fixtures, company=('1710', '1720', '1730'))
        self.assertEqual(len(rows), 1092)
        self.assertEqual(sum(r['NETAMOUNT'] for r in rows), sum(r['NETAMOUNT'] for r in facts))
        self.assertEqual(len({(r['_SystemName'], r['BILLINGDOCUMENT'], r['BILLINGDOCUMENTITEM']) for r in rows}), 1092)
        self.assertEqual(sum(r['billing_linkage_type'] == 'subscription' for r in rows), 4)
        self.assertEqual(sum(r['billing_linkage_type'] == 'operational_order' for r in rows), 1088)
        self.assertTrue(all(r['native_state_status'] == 'observed_blank_markers' for r in rows))
        for r in rows:
            if r['billing_linkage_type'] == 'subscription':
                self.assertIsNone(r['ORDER_ID'])
            else:
                self.assertIsNone(r['SUBSCRIPTION_ID'])
                self.assertEqual(r['SIMULATION_ONLY'], 'X')
        by_doc = {r['BILLINGDOCUMENT']: r for r in rows}
        self.assertIsNone(by_doc['B1090']['ORIGINAL_BILLINGDOCUMENTITEM'])
        self.assertEqual(by_doc['B1091']['ORIGINAL_BILLINGDOCUMENTITEM'], '000001')
        self.assertEqual(by_doc['B1091']['ORDER_LINE_NUMBER'], 1)
        self.assertEqual(by_doc['B1091']['native_order_customer_key'], 1)
        self.assertEqual({c: sum(r['TRANSACTIONCURRENCY'] == c for r in rows) for c in ('EUR', 'CAD', 'CHF')},
                         {'EUR': 553, 'CAD': 258, 'CHF': 281})
        orders.append({**orders[0], 'BILLINGDOCUMENTITEM': '000002'})
        orders.append({**orders[0], '_SystemName': 'OTHER'})
        self.assertEqual(len(self.query('customer_invoice_item', fixtures, company=('1710', '1720', '1730'))), 1092)
        orders.append(dict(orders[0]))
        rows = self.query('customer_invoice_item', fixtures, company=('1710', '1720', '1730'))
        self.assertEqual(len(rows), 1092)
        duplicated = next(r for r in rows if r['BILLINGDOCUMENT'] == orders[0]['BILLINGDOCUMENT'])
        self.assertEqual(duplicated['order_link_source_rows'], 2)
        self.assertEqual(duplicated['order_link_cardinality_status'], 'identical_duplicates')
        self.assertEqual(duplicated['billing_mapping_status'], 'matched')

    def test_invoice_conflicts_preserve_fact_and_suppress_resolved_matches(self):
        fact = {'_SystemName': 'S4M', 'COMPANYCODE': '1710', 'BILLINGDOCUMENT': 'B',
                'BILLINGDOCUMENTITEM': 1, 'SOLDTOPARTY': 'C', '_key_ICUSTOMERSoldToParty': 1,
                'NETAMOUNT': 100, '_Delete': ''}
        customer = {'_SystemName': 'S4M', 'Key': 1, 'CUSTOMER': 'C', '_Delete': ''}
        crosswalk = {'_SystemName': 'S4M', 'CUSTOMER': 'C', 'CUSTOMER_KEY': 'shared', '_Delete': ''}
        order = {'_SystemName': 'S4M', 'BILLINGDOCUMENT': 'B', 'BILLINGDOCUMENTITEM': 1,
                 'CUSTOMER': 'C', '_key_ICUSTOMER': 1, 'ORDER_ID': 'O', '_Delete': ''}
        billing = {'_SystemName': 'S4M', 'BILLINGDOCUMENT': 'B', 'BILLINGDOCUMENTITEM': 1,
                   'SUBSCRIPTION_ID': 'S', '_key_ZMSFSUBSCRIPTION': 9, 'ORDER_ID': 'SO', '_Delete': ''}
        for alias, original, changed, status in (
            ('order_link', order, {**order, 'ORDER_ID': 'OTHER'}, 'ambiguous_billing_link'),
            ('billing_link', billing, {**billing, 'SUBSCRIPTION_ID': 'OTHER'}, 'ambiguous_billing_link'),
            ('customer', customer, {**customer, 'CUSTOMER': 'OTHER'}, 'ambiguous_native_customer'),
            ('customer_link', crosswalk, {**crosswalk, 'CUSTOMER_KEY': 'OTHER'}, 'ambiguous_crosswalk'),
        ):
            with self.subTest(alias=alias):
                fixtures = {'invoice_line': [fact], 'customer': [customer], 'customer_link': [crosswalk]}
                fixtures[alias] = [original, changed]
                rows = self.query('customer_invoice_item', fixtures)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['NETAMOUNT'], 100)
                self.assertEqual(rows[0][alias + '_source_rows'], 2)
                self.assertEqual(rows[0][alias + '_distinct_rows'], 2)
                self.assertEqual(rows[0][alias + '_cardinality_status'], 'conflicting_matches')
                field = 'billing_mapping_status' if alias.endswith('link') and alias != 'customer_link' else 'customer_mapping_status'
                self.assertEqual(rows[0][field], status)
                if field == 'billing_mapping_status':
                    self.assertEqual(rows[0]['billing_linkage_type'], 'ambiguous')
                    self.assertIsNone(rows[0]['ORDER_ID'])
                    self.assertIsNone(rows[0]['SUBSCRIPTION_ID'])
                else:
                    self.assertIsNone(rows[0]['CUSTOMER_KEY'])
                self.assertEqual(rows[0]['native_state_status'], 'unverified_native_markers')

    def test_invoice_order_customer_mismatch_and_dual_bridge_never_resolve(self):
        fact = {'_SystemName': 'S4M', 'COMPANYCODE': '1710', 'BILLINGDOCUMENT': 'B',
                'BILLINGDOCUMENTITEM': 1, 'SOLDTOPARTY': 'C', '_key_ICUSTOMERSoldToParty': 1, '_Delete': ''}
        order = {'_SystemName': 'S4M', 'BILLINGDOCUMENT': 'B', 'BILLINGDOCUMENTITEM': 1,
                 'CUSTOMER': 'C', '_key_ICUSTOMER': 1, 'ORDER_ID': 'O', 'ORDER_LINE_NUMBER': 2,
                 'ORIGINAL_BILLINGDOCUMENT': 'ORIG', 'ORIGINAL_BILLINGDOCUMENTITEM': 1,
                 'SIMULATION_ONLY': 'X', '_Delete': ''}
        fixtures = {'invoice_line': [fact], 'order_link': [order],
                    'customer': [{'_SystemName': 'S4M', 'Key': 1, 'CUSTOMER': 'C', '_Delete': ''}],
                    'customer_link': [{'_SystemName': 'S4M', 'CUSTOMER': 'C', 'CUSTOMER_KEY': 'shared', '_Delete': ''}]}
        for customer, surrogate in (('WRONG', 1), ('C', 99), (None, 1), ('C', None), ('C', -1)):
            with self.subTest(customer=customer, surrogate=surrogate):
                order.update(CUSTOMER=customer, _key_ICUSTOMER=surrogate)
                row = self.query('customer_invoice_item', fixtures)[0]
                self.assertEqual(row['billing_mapping_status'], 'order_customer_mismatch')
                self.assertEqual(row['order_customer_mapping_status'], 'native_key_mismatch')
                self.assertIsNone(row['ORDER_ID'])
        order.update(CUSTOMER='C', _key_ICUSTOMER=1)
        fixtures['billing_link'] = [{'_SystemName': 'S4M', 'BILLINGDOCUMENT': 'B', 'BILLINGDOCUMENTITEM': 1,
                                    'SUBSCRIPTION_ID': 'S', '_key_ZMSFSUBSCRIPTION': 9,
                                    'SERVICE_FROM': '2026-10-01', 'SERVICE_TO_EXCLUSIVE': '2026-11-01',
                                    'ORIGINAL_BILLINGDOCUMENT': 'DIFFERENT', 'ORDER_ID': 'SO', '_Delete': ''}]
        row = self.query('customer_invoice_item', fixtures)[0]
        self.assertEqual(row['billing_mapping_status'], 'ambiguous_billing_link')
        self.assertEqual(row['billing_linkage_type'], 'ambiguous')
        for field in ('SUBSCRIPTION_ID', 'SERVICE_FROM', 'SERVICE_TO_EXCLUSIVE', '_key_ZMSFSUBSCRIPTION',
                      'ORDER_ID', 'ORDER_LINE_NUMBER', 'ORIGINAL_BILLINGDOCUMENT',
                      'ORIGINAL_BILLINGDOCUMENTITEM', 'SIMULATION_ONLY'):
            self.assertIsNone(row[field], field)

    def test_monthly_account_exclusions_are_visible_without_changing_known_measures(self):
        from sources.sap.accounting import ACCOUNTS, CHART
        fact = {'_SystemName': 'S4M', 'COMPANYCODE': '1710', 'POSTINGDATE': '2026-10-01',
                'SOURCELEDGER': '0L', 'CHARTOFACCOUNTS': CHART, 'TRANSACTIONCURRENCY': 'EUR',
                'GLACCOUNT': ACCOUNTS['revenue'][0], 'AMOUNTINTRANSACTIONCURRENCY': -100, '_Delete': ''}
        rows = self.query('monthly_finance', {'gl_line': [fact,
            {**fact, 'GLACCOUNT': None, 'AMOUNTINTRANSACTIONCURRENCY': -20},
            {**fact, 'GLACCOUNT': 'unknown', 'AMOUNTINTRANSACTIONCURRENCY': 5},
            {**fact, 'GLACCOUNT': 'unknown', 'AMOUNTINTRANSACTIONCURRENCY': None}]}, '2026-10-01')
        row = rows[0]
        self.assertEqual(row['recognized_total_revenue'], 100)
        self.assertEqual(row.get('missing_gl_account_rows'), 1)
        self.assertEqual(row.get('unmapped_gl_account_rows'), 2)
        self.assertEqual(row.get('excluded_account_rows'), 3)
        self.assertEqual(row.get('excluded_account_missing_amount_rows'), 1)
        self.assertIsNone(row.get('excluded_account_signed_amount'))
        self.assertEqual(row.get('account_completeness_status'), 'incomplete_account_mapping')
        row = self.query('monthly_finance', {'gl_line': [fact,
            {**fact, 'GLACCOUNT': None, 'AMOUNTINTRANSACTIONCURRENCY': -20},
            {**fact, 'GLACCOUNT': 'unknown', 'AMOUNTINTRANSACTIONCURRENCY': 5}]}, '2026-10-01')[0]
        self.assertEqual(row['excluded_account_signed_amount'], -15)
        clean = self.query('monthly_finance', {'gl_line': [fact]}, '2026-10-01')[0]
        self.assertEqual(clean['account_completeness_status'], 'complete_account_mapping')
        self.assertEqual(clean['excluded_account_rows'], 0)
        self.assertEqual(clean['excluded_account_signed_amount'], 0)
        accounts = [{'_SystemName': 'S4M', 'Key': i + 1, 'CHARTOFACCOUNTS': CHART,
                     'GLACCOUNT': code, '_Delete': ''} for i, code in enumerate((None, 'unknown', fact['GLACCOUNT']))]
        by_code = {r['GLACCOUNT']: r for r in self.query('account_roles', {'gl_account': accounts})}
        self.assertEqual(by_code[None].get('account_mapping_status'), 'missing_gl_account')
        self.assertEqual(by_code['unknown'].get('account_mapping_status'), 'unmapped_gl_account')
        self.assertEqual(by_code[fact['GLACCOUNT']].get('account_mapping_status'), 'matched')

    def test_invoice_global_unknown_customer_cannot_fan_out(self):
        fact = {'_SystemName': 'S4M', 'COMPANYCODE': '1710', 'BILLINGDOCUMENT': 'B',
                'BILLINGDOCUMENTITEM': 1, '_key_ICUSTOMERSoldToParty': -1, 'SOLDTOPARTY': 'C'}
        rows = self.query('customer_invoice_item', {'invoice_line': [fact],
            'customer': [{'Key': -1, '_SystemName': None}, {'Key': -1, '_SystemName': 'S4M'}]})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['customer_mapping_status'], 'missing_native_customer')
        self.assertIsNone(rows[0]['CUSTOMER_KEY'])

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('sources.sap.zero_copy_serving'),
                             'full zero-copy renderer missing')
        return importlib.import_module('sources.sap.zero_copy_serving')

    def query(self, name, fixtures, cutoff=None, company='1710', extra_columns=()):
        m = self.module()
        self.assertTrue(hasattr(m, 'function_selects'), 'parameterized SELECT factory missing')
        _, catalog, _ = serving_contract()
        catalog += list(extra_columns)
        base = m.raw_views(catalog, 'native_db', 'S4M', company)
        selects = {**base, **m.function_selects(catalog, base), **m.serving_views(catalog, base)}
        self.assertIn(name, list(selects), 'serving interface missing')
        sql = selects[name].replace('[native_db].[dbo].', 'native.').replace('COUNT_BIG(', 'COUNT(')
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.row_factory = sqlite3.Row
        db.create_function('YEAR', 1, lambda s: int(s[:4]) if s else None)
        db.create_function('MONTH', 1, lambda s: int(s[5:7]) if s else None)
        db.execute("ATTACH DATABASE ':memory:' AS native")
        db.execute("ATTACH DATABASE ':memory:' AS gold")
        db.execute('CREATE TABLE gold.dim_customer (customer_key, source_customer_id, name)')
        for table in EXPECTED_TABLES.values():
            columns = [ident(r['COLUMN_NAME']) for r in catalog if r['TABLE_NAME'] == table]
            db.execute('CREATE TABLE native.' + ident(table) + '(' + ','.join(columns) + ')')
        for alias, rows in fixtures.items():
            for row in rows:
                table = 'gold.dim_customer' if alias == 'shared_customer' else 'native.' + ident(EXPECTED_TABLES[alias])
                db.execute('INSERT INTO ' + table + '(' + ','.join(map(ident, row))
                           + ') VALUES (' + ','.join('?' for _ in row) + ')', tuple(row.values()))
        cursor = db.execute(sql, {'as_of': cutoff})
        names = [c[0].casefold() for c in cursor.description]
        self.assertEqual(len(names), len(set(names)), 'duplicate output columns would fail a T-SQL view')
        return [dict(r) for r in cursor]

    def test_monthly_cutoff_keeps_ledgers_currency_chart_and_null_dates(self):
        from sources.sap.accounting import ACCOUNTS, CHART
        row = {'_SystemName': 'S4M', 'COMPANYCODE': '1710', 'POSTINGDATE': '2026-11-15',
               'SOURCELEDGER': '0L', 'CHARTOFACCOUNTS': CHART, 'GLACCOUNT': ACCOUNTS['revenue'][0],
               'AMOUNTINTRANSACTIONCURRENCY': -100, 'TRANSACTIONCURRENCY': 'EUR',
               'FISCALYEARVARIANT': 'K4', 'FISCALYEAR': 2026, 'FISCALPERIOD': 11, '_Delete': ''}
        facts = [row, {**row, 'SOURCELEDGER': '2L', 'AMOUNTINTRANSACTIONCURRENCY': -50},
                 {**row, 'TRANSACTIONCURRENCY': 'USD', 'AMOUNTINTRANSACTIONCURRENCY': -30},
                 {**row, 'GLACCOUNT': ACCOUNTS['content_cost'][0], 'AMOUNTINTRANSACTIONCURRENCY': 10},
                 {**row, 'CHARTOFACCOUNTS': 'OTHER', 'AMOUNTINTRANSACTIONCURRENCY': -999},
                 {**row, 'POSTINGDATE': None}, {**row, 'POSTINGDATE': '2026-12-01'},
                 {**row, '_SystemName': 'OTHER'}, {**row, 'COMPANYCODE': '9999'}]
        self.assertEqual(self.query('monthly_finance', {'gl_line': facts}, '2026-11-14'), [])
        rows = self.query('monthly_finance', {'gl_line': facts}, '2026-11-15')
        self.assertEqual(len(rows), 3)
        main = next(r for r in rows if r['SOURCELEDGER'] == '0L' and r['currency'] == 'EUR')
        self.assertEqual(main['recognized_subscription_revenue'], 100)
        self.assertEqual(main['content_expense'], 10)
        self.assertEqual(main['contribution_after_content_cost_only'], 90)
        self.assertEqual(main['as_of'], '2026-11-15')
        self.assertEqual(self.query('monthly_finance', {'gl_line': facts}, None), [])

    def test_ar_dimensional_cardinality_preserves_120_base_amount(self):
        fact = {'_SystemName': 'S4M', 'COMPANYCODE': '1710', 'POSTINGDATE': '2026-11-01',
                'FINANCIALACCOUNTTYPE': 'D', 'CUSTOMER': 'C', '_key_ICUSTOMER': 1,
                'ACCOUNTINGDOCUMENT': 'AR', 'ACCOUNTINGDOCUMENTITEM': 1,
                'AMOUNTINTRANSACTIONCURRENCY': 120, '_Delete': ''}
        customer = {'_SystemName': 'S4M', 'Key': 1, 'CUSTOMER': 'C', '_Delete': ''}
        link = {'_SystemName': 'S4M', 'CUSTOMER': 'C', 'CUSTOMER_KEY': 'shared',
                'SALESFORCE_CONTACT_ID': 'contact', '_Delete': ''}
        fixtures = {'operational_item': [fact], 'customer': [customer, dict(customer)],
                    'customer_link': [link, dict(link)]}
        rows = self.query('ar_open_items', fixtures, '2026-11-01')
        self.assertEqual(len(rows), 1)
        self.assertEqual(sum(r['outstanding_signed'] for r in rows), 120)
        self.assertEqual(rows[0]['CUSTOMER_KEY'], 'shared')
        for alias in ('customer', 'customer_link'):
            self.assertEqual(rows[0][alias + '_source_rows'], 2)
            self.assertEqual(rows[0][alias + '_distinct_rows'], 1)
            self.assertEqual(rows[0][alias + '_cardinality_status'], 'identical_duplicates')
        for alias, original, field, status in (
            ('customer', customer, 'CUSTOMER', 'ambiguous_native_customer'),
            ('customer_link', link, 'CUSTOMER_KEY', 'ambiguous_crosswalk'),
        ):
            with self.subTest(alias=alias):
                conflicting = {**fixtures, alias: [original, {**original, field: 'OTHER'}]}
                rows = self.query('ar_open_items', conflicting, '2026-11-01')
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['outstanding_signed'], 120)
                self.assertEqual(rows[0][alias + '_distinct_rows'], 2)
                self.assertEqual(rows[0][alias + '_cardinality_status'], 'conflicting_matches')
                self.assertEqual(rows[0]['customer_mapping_status'], status)
                self.assertIsNone(rows[0]['CUSTOMER_KEY'])
                self.assertIsNone(rows[0]['source_customer_id'])
                self.assertEqual(rows[0]['native_state_status'], 'unverified_native_markers')
        unknown = {**fact, '_key_ICUSTOMER': -1}
        rows = self.query('ar_open_items', {'operational_item': [unknown], 'customer': [
            {'Key': -1, '_SystemName': None}, {'Key': -1, '_SystemName': 'S4M'}]}, '2026-11-01')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['customer_mapping_status'], 'missing_native_customer')

    def test_open_items_boundary_dates_and_invalid_customer_key_do_not_drop_fact(self):
        row = {'_SystemName': 'S4M', 'COMPANYCODE': '1710', 'POSTINGDATE': '2026-11-01',
               'FINANCIALACCOUNTTYPE': 'D', 'CUSTOMER': 'C1', '_key_ICUSTOMER': 1,
               'AMOUNTINTRANSACTIONCURRENCY': 120, 'TRANSACTIONCURRENCY': 'EUR',
               'ACCOUNTINGDOCUMENT': 'doc', 'ACCOUNTINGDOCUMENTITEM': 1, 'FISCALYEAR': 2026,
               'CLEARINGDATE': '2026-11-15', '_Delete': ''}
        fixtures = {'operational_item': [row],
                    'customer': [{'_SystemName': 'S4M', 'Key': 1, 'CUSTOMER': 'WRONG'}],
                    'customer_link': [{'_SystemName': 'S4M', 'CUSTOMER': 'WRONG', 'CUSTOMER_KEY': 'bad'}]}
        rows = self.query('ar_open_items', fixtures, '2026-11-14')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['outstanding_signed'], 120)
        self.assertIsNone(rows[0]['CUSTOMER_KEY'])
        self.assertEqual(rows[0]['customer_mapping_status'], 'native_key_mismatch')
        self.assertEqual(rows[0]['_key_ICUSTOMER'], 1)
        self.assertEqual(self.query('ar_open_items', fixtures, '2026-11-15'), [])
        self.assertEqual(self.query('ar_open_items', fixtures, '2026-10-31'), [])
        row['CLEARINGDATE'] = None
        self.assertEqual(len(self.query('ar_open_items', fixtures, '2026-12-01')), 1)
        row['FINANCIALACCOUNTTYPE'] = 'K'
        row['AMOUNTINTRANSACTIONCURRENCY'] = -60
        self.assertEqual(self.query('ap_open_items', fixtures, '2026-11-01')[0]['outstanding_payable_signed'], 60)
        row['POSTINGDATE'] = None
        self.assertEqual(self.query('ap_open_items', fixtures, '2026-12-01'), [])

    def test_balances_zero_empty_scope_currency_and_null_amounts(self):
        company = {'_SystemName': 'S4M', 'COMPANYCODE': '1710', 'CURRENCY': 'EUR', 'Key': 1, '_Delete': ''}
        row = {'_SystemName': 'S4M', 'COMPANYCODE': '1710', 'POSTINGDATE': '2026-11-01',
               'FINANCIALACCOUNTTYPE': 'D', 'AMOUNTINTRANSACTIONCURRENCY': 120,
               'TRANSACTIONCURRENCY': 'USD', 'CLEARINGDATE': '2026-11-15', '_Delete': ''}
        fixtures = {'company': [company], 'operational_item': [row, {**row, 'FINANCIALACCOUNTTYPE': 'K',
                    'AMOUNTINTRANSACTIONCURRENCY': -60, 'CLEARINGDATE': None}]}
        early = self.query('balances', fixtures, '2026-10-31')
        self.assertEqual([(r['currency'], r['receivables_outstanding'], r['payables_outstanding'])
                          for r in early], [('EUR', 0, 0)])
        current = {r['currency']: r for r in self.query('balances', fixtures, '2026-11-14')}
        self.assertEqual(set(current), {'EUR', 'USD'})
        self.assertEqual(current['USD']['receivables_outstanding'], 120)
        self.assertEqual(current['USD']['payables_outstanding'], 60)
        self.assertEqual(current['EUR']['receivables_outstanding'], 0)
        after = {r['currency']: r for r in self.query('balances', fixtures, '2026-11-15')}
        self.assertEqual(after['USD']['receivables_outstanding'], 0)
        row.update(AMOUNTINTRANSACTIONCURRENCY=None, TRANSACTIONCURRENCY=None, CLEARINGDATE=None)
        unknown = next(r for r in self.query('balances', fixtures, '2026-11-14') if r['currency'] is None)
        self.assertIsNone(unknown['receivables_outstanding'])
        self.assertEqual(unknown['ar_missing_amount_rows'], 1)
        self.assertEqual(self.query('balances', {}, '2026-11-14'), [])
        self.assertEqual(self.query('balances', fixtures, None), [])

    def test_payment_cutoff_preserves_native_ledger_and_line_grain(self):
        row = {'_SystemName': 'S4M', 'COMPANYCODE': '1710', 'POSTINGDATE': '2026-11-15',
               'ACCOUNTINGDOCUMENTTYPE': 'DZ', 'SOURCELEDGER': '2L', 'LEDGERGLLINEITEM': 1,
               'AMOUNTINTRANSACTIONCURRENCY': 10, '_Delete': 'X'}
        facts = [row, {**row, 'ACCOUNTINGDOCUMENTTYPE': 'DA', 'LEDGERGLLINEITEM': 2},
                 {**row, 'ACCOUNTINGDOCUMENTTYPE': 'KZ', 'LEDGERGLLINEITEM': 3},
                 {**row, 'ACCOUNTINGDOCUMENTTYPE': 'DR'}, {**row, 'POSTINGDATE': None}]
        self.assertEqual(self.query('payment_journal', {'gl_line': facts}, '2026-11-14'), [])
        rows = self.query('payment_journal', {'gl_line': facts}, '2026-11-15')
        self.assertEqual(len(rows), 3)
        self.assertEqual({r['LEDGERGLLINEITEM'] for r in rows}, {1, 2, 3})
        self.assertTrue(all(r['SOURCELEDGER'] == '2L' and r['_Delete'] == 'X' for r in rows))

    def test_invoice_native_billing_link_preserves_order_without_fanout(self):
        fact = {'_SystemName': 'S4M', 'COMPANYCODE': '1710', 'BILLINGDOCUMENT': 'B1',
                'BILLINGDOCUMENTITEM': 10, 'SOLDTOPARTY': 'C1', '_key_ICUSTOMERSoldToParty': 1,
                'NETAMOUNT': 100, '_Delete': ''}
        link = {'_SystemName': 'S4M', 'BILLINGDOCUMENT': 'B1', 'BILLINGDOCUMENTITEM': 10,
                'ORDER_ID': 'native-not-commerce-order', 'SUBSCRIPTION_ID': 'S1',
                '_key_ZMSFSUBSCRIPTION': 91, '_Delete': ''}
        fixtures = {'invoice_line': [fact], 'billing_link': [link, {**link, '_SystemName': 'OTHER'},
                    {**link, 'BILLINGDOCUMENTITEM': 20}],
                    'customer': [{'_SystemName': 'S4M', 'Key': 1, 'CUSTOMER': 'C1'}],
                    'customer_link': [{'_SystemName': 'S4M', 'CUSTOMER': 'C1', 'CUSTOMER_KEY': 'shared'}]}
        rows = self.query('customer_invoice_item', fixtures)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['ORDER_ID'], 'native-not-commerce-order')
        self.assertEqual(rows[0]['_key_ZMSFSUBSCRIPTION'], 91)
        self.assertEqual(rows[0]['CUSTOMER_KEY'], 'shared')
        fixtures['billing_link'].append(dict(link))
        rows = self.query('customer_invoice_item', fixtures)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['billing_link_source_rows'], 2)
        self.assertEqual(rows[0]['billing_link_cardinality_status'], 'identical_duplicates')
        self.assertEqual(rows[0]['ORDER_ID'], 'native-not-commerce-order')
        fixtures['billing_link'] = []
        rows = self.query('customer_invoice_item', fixtures)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['ORDER_ID'])
        self.assertEqual(rows[0]['billing_mapping_status'], 'missing_billing_link')

    def test_subscription_business_view_excludes_global_unknown(self):
        unknown = {'_SystemName': None, 'Key': -1, 'SUBSCRIPTION_ID': None, '_Delete': None}
        self.assertEqual(self.query('subscription_contract', {'subscription': [unknown]}), [])

    def test_subscription_dimensional_cardinality_preserves_100_monthly_net(self):
        sub = {'_SystemName': 'S4M', 'Key': 12, 'SUBSCRIPTION_ID': 'S', 'CUSTOMER': 'C',
               'PLAN_ID': 'P', 'PLAN_VERSION': '2', '_Delete': ''}
        plan = {'_SystemName': 'S4M', 'Key': 21, 'PLAN_ID': 'P', 'VERSION': '2',
                'MONTHLY_NET': 100, 'VAT_RATE': 0.2, 'CURRENCY': 'EUR',
                'CONTRACT_ID': 'R', 'CONTRACT_VERSION': '3', '_Delete': ''}
        link = {'_SystemName': 'S4M', 'CUSTOMER': 'C', 'CUSTOMER_KEY': 'shared',
                'SALESFORCE_CONTACT_ID': 'contact', '_Delete': ''}
        fixtures = {'subscription': [sub], 'plan': [plan, dict(plan)],
                    'customer_link': [link, dict(link)]}
        rows = self.query('subscription_contract', fixtures)
        self.assertEqual(len(rows), 1)
        self.assertEqual(sum(r['MONTHLY_NET'] for r in rows), 100)
        for alias in ('plan', 'customer_link'):
            self.assertEqual(rows[0][alias + '_source_rows'], 2)
            self.assertEqual(rows[0][alias + '_distinct_rows'], 1)
            self.assertEqual(rows[0][alias + '_cardinality_status'], 'identical_duplicates')
        for alias, original, field, changed, status in (
            ('plan', plan, 'MONTHLY_NET', 200, 'ambiguous_plan_version'),
            ('plan', plan, 'Key', 22, 'ambiguous_plan_version'),
            ('plan', plan, '_Delete', 'X', 'ambiguous_plan_version'),
            ('customer_link', link, 'CUSTOMER_KEY', 'OTHER', 'ambiguous_crosswalk'),
            ('customer_link', link, 'SALESFORCE_CONTACT_ID', 'OTHER', 'ambiguous_crosswalk'),
        ):
            with self.subTest(alias=alias, field=field):
                rows = self.query('subscription_contract', {**fixtures,
                    alias: [original, {**original, field: changed}]})
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['Key'], 12)
                self.assertEqual(rows[0][alias + '_source_rows'], 2)
                self.assertEqual(rows[0][alias + '_distinct_rows'], 2)
                self.assertEqual(rows[0][alias + '_cardinality_status'], 'conflicting_matches')
                mapping = 'plan_mapping_status' if alias == 'plan' else 'customer_mapping_status'
                self.assertEqual(rows[0][mapping], status)
                fields = ('MONTHLY_NET', 'native_plan_key', 'VAT_RATE', 'CURRENCY', 'CONTRACT_ID',
                          'CONTRACT_VERSION') if alias == 'plan' else ('CUSTOMER_KEY', 'source_customer_id')
                for output in fields:
                    self.assertIsNone(rows[0][output], output)
                if alias == 'customer_link':
                    self.assertEqual(rows[0]['MONTHLY_NET'], 100)
                self.assertEqual(rows[0]['native_state_status'], 'unverified_native_markers')

    def test_subscription_version_customer_scope_nulls_and_no_fanout(self):
        sub = {'_SystemName': 'S4M', 'Key': 12, 'SUBSCRIPTION_ID': 'S1', 'CUSTOMER': 'C1',
               'PLAN_ID': 'P1', 'PLAN_VERSION': '0002', 'STATUS': 'ACTIVE', '_Delete': ''}
        plan = {'_SystemName': 'S4M', 'Key': 21, 'PLAN_ID': 'P1', 'VERSION': '0002',
                'MONTHLY_NET': 100, 'VAT_RATE': 0.2, 'CURRENCY': 'EUR',
                'CONTRACT_ID': 'R1', 'CONTRACT_VERSION': '0003', '_Delete': ''}
        link = {'_SystemName': 'S4M', 'CUSTOMER': 'C1', 'CUSTOMER_KEY': 'shared', '_Delete': ''}
        fixtures = {'subscription': [sub, {**sub, '_SystemName': 'OTHER'}],
                    'plan': [plan, {**plan, 'VERSION': '0001'}, {**plan, '_SystemName': 'OTHER'}],
                    'customer_link': [link, {**link, '_SystemName': 'OTHER'}]}
        rows = self.query('subscription_contract', fixtures)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['Key'], 12)
        self.assertEqual(rows[0]['CUSTOMER_KEY'], 'shared')
        self.assertEqual(rows[0]['MONTHLY_NET'], 100)
        self.assertEqual(rows[0]['CONTRACT_VERSION'], '0003')
        self.assertEqual(rows[0]['plan_mapping_status'], 'matched')
        fixtures['plan'].append(dict(plan))
        rows = self.query('subscription_contract', fixtures)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['plan_source_rows'], 2)
        self.assertEqual(rows[0]['plan_cardinality_status'], 'identical_duplicates')
        fixtures['plan'] = [plan]
        fixtures['customer_link'].append(dict(link))
        rows = self.query('subscription_contract', fixtures)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['customer_link_source_rows'], 2)
        self.assertEqual(rows[0]['customer_link_cardinality_status'], 'identical_duplicates')
        fixtures['customer_link'] = [link]
        sub['PLAN_VERSION'] = None
        sub['CUSTOMER'] = None
        row = self.query('subscription_contract', fixtures)[0]
        self.assertIsNone(row['MONTHLY_NET'])
        self.assertIsNone(row['CUSTOMER_KEY'])
        self.assertEqual(row['plan_mapping_status'], 'missing_plan_version')
        self.assertEqual(row['customer_mapping_status'], 'missing_crosswalk')

    def test_calendar_excludes_unknown_invalid_and_foreign_periods(self):
        period = {'_SystemName': 'S4M', 'Key': 1, 'FISCALYEARVARIANT': 'K4',
                  'FISCALYEAR': '2026', 'FISCALPERIOD': '011', 'FISCALYEARPERIOD': '2026011',
                  'FISCALPERIODSTARTDATE': '2026-11-01', 'FISCALPERIODENDDATE': '2026-11-30',
                  'ISSPECIALPERIOD': '', '_Delete': ''}
        variants = [period, {**period, 'Key': -1}, {**period, 'Key': None},
                    {**period, '_SystemName': 'OTHER'}, {**period, 'FISCALYEAR': None},
                    {**period, 'FISCALPERIOD': None}, {**period, 'FISCALYEARVARIANT': None},
                    {**period, 'FISCALYEARVARIANT': ''}, {**period, 'FISCALYEARPERIOD': None},
                    {**period, 'FISCALPERIODSTARTDATE': None},
                    {**period, 'FISCALPERIODENDDATE': '2026-10-30'},
                    {**period, 'Key': 13, 'FISCALPERIOD': '013', 'ISSPECIALPERIOD': 'X'}]
        rows = self.query('calendar', {'fiscal_period': variants})
        self.assertEqual([r['Key'] for r in rows], [1, 13])
        self.assertEqual(rows[1]['ISSPECIALPERIOD'], 'X')
        self.assertEqual(rows[0]['FISCALYEARPERIOD'], '2026011')

    def test_calendar_rejects_nonpositive_native_period_identifiers(self):
        period = {'_SystemName': 'S4M', 'Key': 1, 'FISCALYEARVARIANT': 'K4',
                  'FISCALYEAR': 2026, 'FISCALPERIOD': 11, 'FISCALYEARPERIOD': 2026011,
                  'FISCALPERIODSTARTDATE': '2026-11-01', 'FISCALPERIODENDDATE': '2026-11-30'}
        for field in ('FISCALYEAR', 'FISCALPERIOD', 'FISCALYEARPERIOD'):
            for invalid in (0, -1):
                with self.subTest(field=field, invalid=invalid):
                    self.assertEqual(self.query('calendar', {'fiscal_period': [{**period, field: invalid}]}), [])

    def test_account_roles_are_explicit_chart_scoped_and_not_inferred(self):
        from sources.sap.accounting import ACCOUNTS, CHART
        accounts = [{'_SystemName': 'S4M', 'Key': i + 1, 'CHARTOFACCOUNTS': CHART,
                     'GLACCOUNT': code, 'GLACCOUNTTYPE': 'P', '_Delete': ''}
                    for i, (code, _, _) in enumerate(ACCOUNTS.values())]
        accounts += [{**accounts[0], 'GLACCOUNT': 'unknown'},
                     {**accounts[0], 'GLACCOUNT': None},
                     {**accounts[0], 'CHARTOFACCOUNTS': 'OTHER'},
                     {**accounts[0], '_SystemName': 'OTHER'},
                     {**accounts[0], 'Key': -1}]
        rows = self.query('account_roles', {'gl_account': accounts})
        self.assertEqual(len(rows), len(ACCOUNTS) + 2)
        by_code = {r['GLACCOUNT']: r['account_role'] for r in rows}
        self.assertEqual({code: by_code[code] for code, _, _ in ACCOUNTS.values()},
                         {code: role for role, (code, _, _) in ACCOUNTS.items()})
        self.assertIsNone(by_code['unknown'])
        self.assertIsNone(by_code[None])

    def test_serving_markers_require_review_without_reinterpreting_x(self):
        invoice = {'_SystemName': 'S4M', 'COMPANYCODE': '1710', 'BILLINGDOCUMENT': 'B',
                   'BILLINGDOCUMENTITEM': 1, 'SOLDTOPARTY': 'C', '_key_ICUSTOMERSoldToParty': 1, '_Delete': ''}
        fixtures = {'invoice_line': [invoice],
                    'customer': [{'_SystemName': 'S4M', 'Key': 1, 'CUSTOMER': 'C', '_Delete': ''}],
                    'customer_link': [{'_SystemName': 'S4M', 'CUSTOMER': 'C', 'CUSTOMER_KEY': 'shared', '_Delete': ''}],
                    'billing_link': [{'_SystemName': 'S4M', 'BILLINGDOCUMENT': 'B', 'BILLINGDOCUMENTITEM': 1, '_Delete': ''}]}
        self.assertEqual(self.query('customer_invoice_item', fixtures)[0].get('native_state_status'), 'observed_blank_markers')
        for alias in fixtures:
            for marker in ('X', None):
                with self.subTest(alias=alias, marker=marker):
                    fixtures[alias][0]['_Delete'] = marker
                    rows = self.query('customer_invoice_item', fixtures)
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0]['native_state_status'], 'unverified_native_markers')
                    fixtures[alias][0]['_Delete'] = ''
        for view, alias, fact in (
            ('subscription_contract', 'subscription', {'Key': 1}),
            ('account_roles', 'gl_account', {'Key': 1, 'CHARTOFACCOUNTS': 'MSFX'}),
            ('calendar', 'fiscal_period', {'Key': 1, 'FISCALYEARVARIANT': 'K4', 'FISCALYEAR': 2026,
                'FISCALPERIOD': 11, 'FISCALYEARPERIOD': '2026011',
                'FISCALPERIODSTARTDATE': '2026-11-01', 'FISCALPERIODENDDATE': '2026-11-30'}),
            ('ar_open_items', 'operational_item', {'COMPANYCODE': '1710', 'FINANCIALACCOUNTTYPE': 'D', 'POSTINGDATE': '2026-11-01'}),
            ('ap_open_items', 'operational_item', {'COMPANYCODE': '1710', 'FINANCIALACCOUNTTYPE': 'K', 'POSTINGDATE': '2026-11-01'}),
            ('payment_journal', 'gl_line', {'COMPANYCODE': '1710', 'ACCOUNTINGDOCUMENTTYPE': 'DZ', 'POSTINGDATE': '2026-11-01'}),
        ):
            with self.subTest(view=view):
                row = self.query(view, {alias: [{**fact, '_SystemName': 'S4M', '_Delete': 'X'}]}, '2026-11-01')[0]
                self.assertEqual(row.get('native_state_status'), 'unverified_native_markers')
                self.assertEqual(row['_Delete'], 'X')

    def test_balances_report_unverified_markers_without_losing_empty_scope(self):
        company = {'_SystemName': 'S4M', 'COMPANYCODE': '1710', 'CURRENCY': 'EUR', 'Key': 1, '_Delete': 'X'}
        row = self.query('balances', {'company': [company]}, '2026-11-01')[0]
        self.assertEqual(row.get('native_state_status'), 'unverified_native_markers')
        self.assertEqual(row.get('scope_unverified_marker_rows'), 1)
        self.assertEqual(row['receivables_outstanding'], 0)
        company['_Delete'] = ''
        item = {'_SystemName': 'S4M', 'COMPANYCODE': '1710', 'TRANSACTIONCURRENCY': 'EUR',
                'POSTINGDATE': '2026-11-01', 'FINANCIALACCOUNTTYPE': 'D', 'AMOUNTINTRANSACTIONCURRENCY': None,
                '_Delete': 'X'}
        row = self.query('balances', {'company': [company], 'operational_item': [item]}, '2026-11-01')[0]
        self.assertEqual(row['native_state_status'], 'unverified_native_markers')
        self.assertEqual(row['unverified_marker_rows'], 1)
        self.assertIsNone(row['receivables_outstanding'])
        row = self.query('balances', {'company': [company]}, '2026-11-01')[0]
        self.assertEqual(row['native_state_status'], 'observed_blank_markers')
        self.assertEqual(row['scope_unverified_marker_rows'], 0)

    def test_monthly_partial_null_amounts_are_not_reported_as_complete_totals(self):
        from sources.sap.accounting import ACCOUNTS, CHART
        row = {'_SystemName': 'S4M', 'COMPANYCODE': '1710', 'POSTINGDATE': '2026-11-01',
               'SOURCELEDGER': '0L', 'CHARTOFACCOUNTS': CHART, 'TRANSACTIONCURRENCY': 'EUR',
               'GLACCOUNT': ACCOUNTS['revenue'][0], 'AMOUNTINTRANSACTIONCURRENCY': -100, '_Delete': ''}
        rows = self.query('monthly_finance', {'gl_line': [row,
            {**row, 'AMOUNTINTRANSACTIONCURRENCY': None},
            {**row, 'GLACCOUNT': ACCOUNTS['content_cost'][0], 'AMOUNTINTRANSACTIONCURRENCY': 10}]}, '2026-11-01')
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['recognized_subscription_revenue'])
        self.assertIsNone(rows[0]['contribution_after_content_cost_only'])
        self.assertEqual(rows[0]['content_expense'], 10)
        self.assertEqual(rows[0]['net_bank_movement'], 0)
        self.assertEqual(rows[0].get('missing_amount_rows'), 1)
        self.assertEqual(rows[0].get('native_state_status'), 'observed_blank_markers')
        rows = self.query('monthly_finance', {'gl_line': [{**row, '_Delete': 'X'}]}, '2026-11-01')
        self.assertEqual(rows[0]['native_state_status'], 'unverified_native_markers')

    def test_render_bundle_ordered_select_only_contract(self):
        m = self.module()
        self.assertTrue(hasattr(m, 'render_bundle'), 'full bundle renderer missing')
        self.assertTrue(ARTIFACT.exists(), 'versioned serving artifact missing')
        raw, catalog, batches = serving_contract()
        rendered = m.render_bundle(catalog, 'bps_gold_a1b2c3d4', 'S4M', '1710')
        # Artifact remains a historical schema fixture; parent owns regeneration
        # and exact artifact-byte parity outside this renderer-only task.
        batches = rendered.split('-- @batch\n')
        self.assertNotIn(b'\r', raw)
        self.assertEqual(rendered, m.render_bundle(list(reversed(catalog)), 'bps_gold_a1b2c3d4', 'S4M', '1710'))
        base = m.raw_views(catalog, 'bps_gold_a1b2c3d4', 'S4M', '1710')
        business = m.serving_views(catalog, base)
        functions = m.function_selects(catalog, base)
        self.assertEqual(set(business), {'invoice_customer', 'gl_account_balance', 'customer_invoice_item',
                                       'subscription_contract', 'calendar', 'account_roles'})
        self.assertEqual(set(functions), {'monthly_finance', 'ar_open_items', 'ap_open_items', 'balances', 'payment_journal'})
        self.assertEqual(len(batches), 36)
        expected = [('VIEW', name, body) for name, body in {**base, **business}.items()]
        expected += [('FUNCTION', name, body) for name, body in functions.items()]
        for batch, (kind, name, body) in zip(batches[1:], expected, strict=True):
            with self.subTest(name=name):
                signature = (' AS\n' if kind == 'VIEW' else '(@as_of date)\nRETURNS TABLE\nAS RETURN (\n')
                ending = ';\n' if kind == 'VIEW' else '\n);\n'
                self.assertEqual(batch, 'CREATE OR ALTER ' + kind + ' [sap_live].' + ident(name) + signature + body + ending)
                self.assertNotRegex(body, r'(?i)\b(?:INSERT|UPDATE|DELETE|MERGE|DROP|CREATE|ALTER|EXEC|INTO)\b')
                self.assertNotIn('gold.sap_', body.lower())
                self.assertNotRegex(body, r'(?i)\b(?:scenario_id|run_id|published_at|GETDATE|CURRENT_TIMESTAMP)\b')
                self.assertNotRegex(body, r'(?i)SELECT\s+(?:\w+\.)?\*')
                if kind == 'FUNCTION':
                    self.assertIn('@as_of', body)
        self.assertNotRegex(rendered, r'(?i)CREATE\s+TABLE|\b(?:INSERT|MERGE|TRUNCATE|DROP)\b')

    def test_invoice_customer_null_unknown_mismatch_and_fanout_are_visible(self):
        fact = {'_SystemName': 'S4M', 'COMPANYCODE': '1710', 'BILLINGDOCUMENT': 'B1',
                'BILLINGDOCUMENTITEM': 1, 'SOLDTOPARTY': 'C1', '_key_ICUSTOMERSoldToParty': 1,
                'NETAMOUNT': None, '_Delete': ''}
        customer = {'_SystemName': 'S4M', 'Key': 1, 'CUSTOMER': 'C1', '_Delete': ''}
        link = {'_SystemName': 'S4M', 'CUSTOMER': 'C1', 'CUSTOMER_KEY': 'shared', '_Delete': ''}
        fixtures = {'invoice_line': [fact, {**fact, 'COMPANYCODE': '9999'}, {**fact, '_SystemName': 'OTHER'}],
                    'customer': [customer, {**customer, '_SystemName': 'OTHER'}], 'customer_link': [link]}
        row = self.query('customer_invoice_item', fixtures)[0]
        self.assertEqual(row['customer_mapping_status'], 'matched')
        self.assertIsNone(row['NETAMOUNT'])
        for fact_key, customer_key, expected in (
            (None, 'C1', 'native_key_mismatch'), ('C1', None, 'native_key_mismatch'),
            ('C1', 'WRONG', 'native_key_mismatch'),
        ):
            with self.subTest(fact_key=fact_key, customer_key=customer_key):
                fact['SOLDTOPARTY'], customer['CUSTOMER'] = fact_key, customer_key
                rows = self.query('customer_invoice_item', fixtures)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['customer_mapping_status'], expected)
                self.assertIsNone(rows[0]['CUSTOMER_KEY'])
        fact['SOLDTOPARTY'], customer['CUSTOMER'] = 'C1', 'C1'
        fixtures['customer'].append(dict(customer))
        rows = self.query('customer_invoice_item', fixtures)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['customer_cardinality_status'], 'identical_duplicates')
        self.assertEqual(rows[0]['customer_source_rows'], 2)
        fixtures['customer'] = [customer]
        fixtures['customer_link'].append(dict(link))
        rows = self.query('customer_invoice_item', fixtures)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['customer_link_cardinality_status'], 'identical_duplicates')
        self.assertEqual(rows[0]['customer_link_source_rows'], 2)
        fact['_key_ICUSTOMERSoldToParty'] = -1
        fixtures['customer'] = [{'Key': -1, '_SystemName': None, 'CUSTOMER': 'C1'}]
        row = self.query('customer_invoice_item', fixtures)[0]
        self.assertEqual(row['native_customer_key'], -1)
        self.assertEqual(row['customer_mapping_status'], 'missing_native_customer')
        self.assertIsNone(row['CUSTOMER_KEY'])
        fixtures['customer'] = []
        row = self.query('customer_invoice_item', fixtures)[0]
        self.assertEqual(row['customer_mapping_status'], 'missing_native_customer')
        fact['BILLINGDOCUMENT'] = None
        fixtures['billing_link'] = [{'_SystemName': 'S4M', 'BILLINGDOCUMENT': None, 'BILLINGDOCUMENTITEM': 1}]
        self.assertEqual(self.query('customer_invoice_item', fixtures)[0]['billing_mapping_status'], 'missing_billing_link')

    def test_catalog_gate_rejects_output_collisions_and_duplicate_columns(self):
        m = self.module()
        _, catalog, _ = serving_contract()
        for alias, column in (('invoice_line', 'CUSTOMER_KEY'), ('subscription', 'MONTHLY_NET'),
                              ('invoice_line', 'order_customer_mapping_status'),
                              ('invoice_line', 'customer_source_rows'),
                              ('invoice_line', 'order_link_cardinality_status'),
                              ('operational_item', 'customer_source_rows'),
                              ('operational_item', 'customer_link_distinct_rows'),
                              ('operational_item', 'customer_link_cardinality_status'),
                              ('subscription', 'plan_source_rows'),
                              ('subscription', 'plan_distinct_rows'),
                              ('subscription', 'plan_cardinality_status'),
                              ('subscription', 'customer_link_source_rows'),
                              ('subscription', 'customer_link_cardinality_status'),
                              ('gl_account', 'account_mapping_status'),
                              ('operational_item', 'as_of'), ('gl_line', 'native_state_status'),
                              ('fiscal_period', 'native_state_status'), ('gl_account', 'account_role')):
            with self.subTest(alias=alias):
                broken = catalog + [{'TABLE_SCHEMA': 'dbo', 'TABLE_NAME': EXPECTED_TABLES[alias], 'COLUMN_NAME': column}]
                with self.assertRaisesRegex(ValueError, 'column'):
                    m.render_bundle(broken, 'db', 'S', '1710')
        duplicate = catalog + [catalog[0]]
        with self.assertRaisesRegex(ValueError, 'column'):
            m.validate_catalog(duplicate)
        with self.assertRaisesRegex(ValueError, 'column'):
            m.raw_views(duplicate, 'db', 'S', '1710')
        with self.assertRaisesRegex(ValueError, 'column'):
            m.validate_catalog(catalog + [{**catalog[0], 'COLUMN_NAME': catalog[0]['COLUMN_NAME'].lower()}])

    def test_catalog_gate_blocks_missing_dependencies_in_every_select_factory(self):
        m = self.module()
        _, catalog, _ = serving_contract()
        m.validate_catalog(catalog)
        base = m.raw_views(catalog, 'native_db', 'S4M', '1710')
        required = {
            'gl_line': 'AMOUNTINTRANSACTIONCURRENCY FISCALYEAR FISCALPERIOD FISCALYEARVARIANT TRANSACTIONCURRENCY ACCOUNTINGDOCUMENTTYPE _key_IGLACCOUNTINCHARTOFACCOUNTS',
            'operational_item': 'COMPANYCODE POSTINGDATE CLEARINGDATE FINANCIALACCOUNTTYPE AMOUNTINTRANSACTIONCURRENCY TRANSACTIONCURRENCY CUSTOMER _key_ICUSTOMER',
            'invoice_line': 'COMPANYCODE BILLINGDOCUMENT BILLINGDOCUMENTITEM ACCOUNTINGDOCUMENT BILLINGDOCUMENTDATE BILLINGDOCUMENTCATEGORY SOLDTOPARTY PRODUCT TRANSACTIONCURRENCY NETAMOUNT TAXAMOUNT GROSSAMOUNT _key_ICUSTOMERSoldToParty',
            'customer': 'Key CUSTOMER CUSTOMERNAME',
            'customer_link': 'CUSTOMER CUSTOMER_KEY SALESFORCE_CONTACT_ID',
            'billing_link': 'BILLINGDOCUMENT BILLINGDOCUMENTITEM SUBSCRIPTION_ID SERVICE_FROM SERVICE_TO_EXCLUSIVE ORIGINAL_BILLINGDOCUMENT ORDER_ID _key_ZMSFSUBSCRIPTION',
            'order_link': 'BILLINGDOCUMENT BILLINGDOCUMENTITEM CUSTOMER ORDER_ID ORDER_LINE_NUMBER ORIGINAL_BILLINGDOCUMENT ORIGINAL_BILLINGDOCUMENTITEM SIMULATION_ONLY _key_ICUSTOMER',
            'subscription': 'Key CUSTOMER PLAN_ID PLAN_VERSION',
            'plan': 'Key PLAN_ID VERSION MONTHLY_NET VAT_RATE CURRENCY CONTRACT_ID CONTRACT_VERSION VALID_FROM VALID_TO_EXCLUSIVE',
            'company': 'COMPANYCODE CURRENCY',
            'gl_account': 'Key GLACCOUNT CHARTOFACCOUNTS GLACCOUNTTYPE',
            'fiscal_period': 'Key FISCALYEARVARIANT FISCALYEAR FISCALPERIOD FISCALYEARPERIOD FISCALPERIODSTARTDATE FISCALPERIODENDDATE',
        }
        for alias, columns in required.items():
            for column in columns.split() + ['_SystemName', '_Delete', '_UpdateTimeStamp']:
                with self.subTest(alias=alias, column=column):
                    broken = [r for r in catalog if (r['TABLE_NAME'], r['COLUMN_NAME']) != (EXPECTED_TABLES[alias], column)]
                    for factory in (lambda: m.validate_catalog(broken),
                                    lambda: m.serving_views(broken, base),
                                    lambda: m.function_selects(broken, base),
                                    lambda: m.render_bundle(broken, 'native_db', 'S4M', '1710')):
                        with self.assertRaisesRegex(ValueError, 'column'):
                            factory()

    def test_all_selects_compile_against_artifact_schema(self):
        m = self.module()
        _, catalog, _ = serving_contract()
        base = m.raw_views(catalog, 'native_db', 'S4M', '1710')
        for name in {**m.function_selects(catalog, base), **m.serving_views(catalog, base)}:
            with self.subTest(name=name):
                self.assertEqual(self.query(name, {}, '2026-11-01'), [])
        from sources.sap.zero_copy import business_views
        self.assertEqual({name: m.serving_views(catalog, base)[name] for name in business_views(base)}, business_views(base))

    def test_schema_gate_requires_native_metadata_and_referenced_columns(self):
        m = self.module()
        catalog = [{'TABLE_SCHEMA': 'dbo', 'TABLE_NAME': table, 'COLUMN_NAME': col}
                   for table in EXPECTED_TABLES.values()
                   for col in ('_SystemName', '_Delete', 'Key')]
        self.assertTrue(hasattr(m, 'validate_catalog'), 'schema gate missing')
        with self.assertRaisesRegex(ValueError, 'column'):
            m.validate_catalog(catalog)
        with self.assertRaisesRegex(ValueError, 'column'):
            m.raw_views([r for r in catalog if r['COLUMN_NAME'] != '_Delete'], 'db', 'S', 'C')

    def test_full_raw_contract_preserves_columns_keys_unknown_and_markers(self):
        m = self.module()
        self.assertEqual(m.TABLES, EXPECTED_TABLES)
        self.assertEqual(len(m.TABLES), 24)
        catalog = [{'TABLE_SCHEMA': 'dbo', 'TABLE_NAME': table, 'COLUMN_NAME': col}
                   for table in EXPECTED_TABLES.values()
                   for col in ('_SystemName', '_Delete', 'Key', '_key_Other', 'SOURCE_VALUE')]
        views = m.raw_views(catalog, 'native_db', 'S4M', '1710')
        for sql in views.values():
            self.assertIn('s.[Key]', sql)
            self.assertIn('s.[_key_Other]', sql)
            self.assertIn('s.[SOURCE_VALUE]', sql)
            self.assertIn('s.[_Delete]', sql)
            self.assertIn('s.[Key] = -1 AND s.[_SystemName] IS NULL', sql)
            self.assertNotIn("[_Delete] =", sql)
        self.assertEqual(views, m.raw_views(list(reversed(catalog)), 'native_db', 'S4M', '1710'))


if __name__ == '__main__':
    unittest.main()
