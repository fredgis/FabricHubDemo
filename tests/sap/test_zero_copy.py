"""Offline contract tests for an additive zero-copy SQL preview."""
import importlib
import importlib.util
import re
import sqlite3
import unittest
from pathlib import Path

from sources.sap.zero_copy import TABLES, business_views, ident, render_bundle, source_views


PREVIEW = Path(__file__).resolve().parents[2] / 'fabric/gold/sap-live-views.preview.sql'


def preview_contract():
    """Recover only source projections, never business logic or ignored evidence."""
    raw = PREVIEW.read_bytes()
    batches = raw.decode('utf-8').replace('\r\n', '\n').split('-- @batch\n')[1:]
    catalog = []
    for (name, table), batch in zip(TABLES.items(), batches, strict=False):
        match = re.fullmatch(
            r'CREATE VIEW \[sap_live\]\.\[' + re.escape(name) + r'\] AS\n'
            r'SELECT (?P<columns>s\.\[\w+\](?:,\n       s\.\[\w+\])*)\n'
            r'FROM \[bps_gold_<system_suffix>\]\.\[dbo\]\.\[' + re.escape(table)
            + r'\] AS s\nWHERE [^\n]+;\n', batch)
        if match is None:
            raise AssertionError('Invalid preview source projection: ' + name)
        catalog.extend({'TABLE_SCHEMA': 'dbo', 'TABLE_NAME': table, 'COLUMN_NAME': column}
                       for column in re.findall(r's\.\[(\w+)\]', match['columns']))
    if len(batches) != len(TABLES) + 2:
        raise AssertionError('Expected all source and both business views')
    return raw, catalog


class MappingSemanticsTests(unittest.TestCase):
    def invoice_fixture(self):
        return {
            'invoice_line': [{'_SystemName': 'S4M', 'COMPANYCODE': '1710',
                              'BILLINGDOCUMENT': 'invoice-1', 'BILLINGDOCUMENTITEM': '10',
                              'SOLDTOPARTY': 'C001', '_key_ICUSTOMERSoldToParty': 101,
                              'NETAMOUNT': 100, 'TAXAMOUNT': 20, 'GROSSAMOUNT': 120}],
            'customer': [{'_SystemName': 'S4M', 'Key': 101, 'CUSTOMER': 'C001',
                          'CUSTOMERNAME': 'Native customer'}],
            'customer_link': [{'_SystemName': 'S4M', 'CUSTOMER': 'C001',
                               'CUSTOMER_KEY': 'shared-1', 'SALESFORCE_CONTACT_ID': 'crm-1'}],
            'shared_customer': [{'customer_key': 'shared-1', 'source_customer_id': 'crm-1',
                                 'name': 'Shared customer'}],
        }

    def balance_fixture(self):
        return {
            'gl_line': [{'_SystemName': 'S4M', 'COMPANYCODE': '1710', 'SOURCELEDGER': '0L',
                         'FISCALYEARVARIANT': 'K4', 'FISCALYEAR': 2026, 'FISCALPERIOD': 10,
                         'GLACCOUNT': '400000', 'CHARTOFACCOUNTS': 'YCOA',
                         'TRANSACTIONCURRENCY': 'EUR', '_key_IGLACCOUNTINCHARTOFACCOUNTS': 201,
                         'AMOUNTINTRANSACTIONCURRENCY': -100, '_UpdateTimeStamp': '2026-10-01'}],
            'gl_account': [{'_SystemName': 'S4M', 'Key': 201, 'GLACCOUNT': '400000',
                            'CHARTOFACCOUNTS': 'YCOA', 'GLACCOUNTTYPE': 'P'}],
        }

    def test_null_fact_account_fields_are_native_key_mismatch(self):
        for null_fields in (('GLACCOUNT',), ('CHARTOFACCOUNTS',), ('GLACCOUNT', 'CHARTOFACCOUNTS')):
            with self.subTest(null_fields=null_fields):
                fixtures = self.balance_fixture()
                fixtures['gl_line'][0].update(dict.fromkeys(null_fields))
                rows = self.query('gl_account_balance', fixtures)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['account_mapping_status'], 'native_key_mismatch')
                self.assertEqual(rows[0]['native_account_key'], 201)
                self.assertEqual(rows[0]['journal_lines'], 1)
                self.assertEqual(rows[0]['signed_movement'], -100)
                self.assertEqual(rows[0]['absolute_movement'], 100)

    def query(self, view, fixtures):
        """Execute generated SELECTs using SQL NULL/CASE/LEFT JOIN semantics.

        SQLite is not a Fabric integration test. The only dialect adaptations
        are the native database/schema qualifier and COUNT_BIG -> COUNT; CASE,
        filters, joins, grouping and duplicate rows are evaluated unchanged.
        """
        _, catalog = preview_contract()
        base = source_views(catalog, 'bps_gold_a1b2c3d4', 'S4M', '1710', TABLES)
        sql = business_views(base)[view].replace('[bps_gold_a1b2c3d4].[dbo].', 'native.')
        sql = sql.replace('COUNT_BIG(*)', 'COUNT(*)')
        connection = sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        connection.execute("ATTACH DATABASE ':memory:' AS native")
        connection.execute("ATTACH DATABASE ':memory:' AS gold")
        for table in TABLES.values():
            columns = [ident(row['COLUMN_NAME']) for row in catalog if row['TABLE_NAME'] == table]
            connection.execute('CREATE TABLE native.' + ident(table) + ' (' + ', '.join(columns) + ')')
        connection.execute('CREATE TABLE gold.dim_customer (customer_key, source_customer_id, name)')
        for name, rows in fixtures.items():
            table = 'gold.dim_customer' if name == 'shared_customer' else 'native.' + ident(TABLES[name])
            for row in rows:
                columns = ', '.join(ident(column) for column in row)
                placeholders = ', '.join('?' for _ in row)
                connection.execute('INSERT INTO ' + table + ' (' + columns + ') VALUES ('
                                   + placeholders + ')', tuple(row.values()))
        return [dict(row) for row in connection.execute(sql)]

    def test_null_sold_to_party_is_native_key_mismatch(self):
        fixtures = self.invoice_fixture()
        fixtures['invoice_line'][0]['SOLDTOPARTY'] = None
        rows = self.query('invoice_customer', fixtures)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['customer_mapping_status'], 'native_key_mismatch')
        self.assertEqual(rows[0]['shared_customer_key'], 'shared-1')
        self.assertEqual(rows[0]['NETAMOUNT'], 100)

    def test_invoice_mapping_status_boundaries(self):
        cases = [
            ('matched', {}, (), 'matched'),
            ('fact_mismatch', {'invoice_line': {'SOLDTOPARTY': 'other'}}, (), 'native_key_mismatch'),
            ('dimension_null', {'customer': {'CUSTOMER': None}}, (), 'native_key_mismatch'),
            ('both_null', {'invoice_line': {'SOLDTOPARTY': None}, 'customer': {'CUSTOMER': None}},
             (), 'native_key_mismatch'),
            ('missing_native', {}, ('customer',), 'missing_native_customer'),
            ('null_surrogate', {'invoice_line': {'_key_ICUSTOMERSoldToParty': None}},
             (), 'missing_native_customer'),
            ('global_unknown', {'invoice_line': {'_key_ICUSTOMERSoldToParty': -1, 'SOLDTOPARTY': None},
                                'customer': {'Key': -1, '_SystemName': None, 'CUSTOMER': None}},
             (), 'missing_native_customer'),
            ('cross_system_native', {'customer': {'_SystemName': 'OTHER'}}, (), 'missing_native_customer'),
            ('cross_system_link', {'customer_link': {'_SystemName': 'OTHER'}}, (), 'missing_crosswalk'),
            ('missing_crosswalk', {}, ('customer_link',), 'missing_crosswalk'),
            ('missing_shared', {}, ('shared_customer',), 'missing_shared_customer'),
            ('crm_null_shared', {'shared_customer': {'source_customer_id': None}}, (), 'crm_id_mismatch'),
            ('crm_null_link', {'customer_link': {'SALESFORCE_CONTACT_ID': None}}, (), 'crm_id_mismatch'),
            ('crm_mismatch', {'shared_customer': {'source_customer_id': 'other'}}, (), 'crm_id_mismatch'),
        ]
        for label, overrides, empty_tables, expected in cases:
            with self.subTest(case=label):
                fixtures = self.invoice_fixture()
                for table, values in overrides.items():
                    fixtures[table][0].update(values)
                for table in empty_tables:
                    fixtures[table] = []
                rows = self.query('invoice_customer', fixtures)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['customer_mapping_status'], expected)
                self.assertEqual(rows[0]['NETAMOUNT'], 100)
                if label == 'global_unknown':
                    self.assertEqual(rows[0]['native_customer_key'], -1)
                if label == 'cross_system_native':
                    self.assertIsNone(rows[0]['native_customer_key'])

    def test_account_mapping_status_boundaries(self):
        cases = [
            ('matched', {}, (), 'matched'),
            ('fact_account_mismatch', {'gl_line': {'GLACCOUNT': 'other'}}, (), 'native_key_mismatch'),
            ('fact_chart_mismatch', {'gl_line': {'CHARTOFACCOUNTS': 'other'}}, (), 'native_key_mismatch'),
            ('dimension_account_null', {'gl_account': {'GLACCOUNT': None}}, (), 'native_key_mismatch'),
            ('dimension_chart_null', {'gl_account': {'CHARTOFACCOUNTS': None}}, (), 'native_key_mismatch'),
            ('both_dimension_fields_null', {'gl_account': {'GLACCOUNT': None, 'CHARTOFACCOUNTS': None}},
             (), 'native_key_mismatch'),
            ('all_business_keys_null', {'gl_line': {'GLACCOUNT': None, 'CHARTOFACCOUNTS': None},
                                       'gl_account': {'GLACCOUNT': None, 'CHARTOFACCOUNTS': None}},
             (), 'native_key_mismatch'),
            ('missing_native', {}, ('gl_account',), 'missing_native_account'),
            ('null_surrogate', {'gl_line': {'_key_IGLACCOUNTINCHARTOFACCOUNTS': None}},
             (), 'missing_native_account'),
            ('global_unknown', {'gl_line': {'_key_IGLACCOUNTINCHARTOFACCOUNTS': -1,
                                           'GLACCOUNT': None, 'CHARTOFACCOUNTS': None},
                                'gl_account': {'Key': -1, '_SystemName': None,
                                               'GLACCOUNT': None, 'CHARTOFACCOUNTS': None}},
             (), 'missing_native_account'),
            ('cross_system_native', {'gl_account': {'_SystemName': 'OTHER'}}, (), 'missing_native_account'),
        ]
        for label, overrides, empty_tables, expected in cases:
            with self.subTest(case=label):
                fixtures = self.balance_fixture()
                for table, values in overrides.items():
                    fixtures[table][0].update(values)
                for table in empty_tables:
                    fixtures[table] = []
                rows = self.query('gl_account_balance', fixtures)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['account_mapping_status'], expected)
                self.assertEqual(rows[0]['journal_lines'], 1)
                self.assertEqual(rows[0]['signed_movement'], -100)
                self.assertEqual(rows[0]['absolute_movement'], 100)
                if label == 'global_unknown':
                    self.assertEqual(rows[0]['native_account_key'], -1)
                if label == 'cross_system_native':
                    self.assertIsNone(rows[0]['native_account_key'])

    def test_invoice_dimensions_collapse_duplicates_and_reject_conflicting_matches(self):
        for table, field, output, status in (
            ('customer', 'CUSTOMERNAME', 'sap_customer_name', 'ambiguous_native_customer'),
            ('customer_link', 'CUSTOMER_KEY', 'mapped_customer_key', 'ambiguous_crosswalk'),
            ('shared_customer', 'name', 'shared_customer_name', 'ambiguous_shared_customer'),
        ):
            for conflict in (False, True):
                with self.subTest(table=table, conflict=conflict):
                    fixtures = self.invoice_fixture()
                    fixtures['invoice_line'].append(dict(fixtures['invoice_line'][0]))
                    duplicate = dict(fixtures[table][0])
                    if conflict:
                        duplicate[field] = 'OTHER'
                    fixtures[table].append(duplicate)
                    rows = self.query('invoice_customer', fixtures)
                    self.assertEqual(len(rows), 2, 'dimension joins must preserve physical fact rows')
                    self.assertEqual(sum(row['NETAMOUNT'] for row in rows), 200)
                    self.assertEqual(sum(row['GROSSAMOUNT'] for row in rows), 240)
                    for row in rows:
                        self.assertEqual(row['customer_mapping_status'], status if conflict else 'matched')
                        alias = 'shared_customer' if table == 'shared_customer' else table
                        self.assertEqual(row[alias + '_source_rows'], 2)
                        self.assertEqual(row[alias + '_distinct_rows'], 2 if conflict else 1)
                        self.assertEqual(row[alias + '_cardinality_status'],
                                         'conflicting_matches' if conflict else 'identical_duplicates')
                        if conflict:
                            self.assertIsNone(row[output])

    def test_balance_dimension_cardinality_preserves_fact_grain_and_measures(self):
        for field in (None, 'GLACCOUNTTYPE', 'GLACCOUNT', '_Delete', '_UpdateTimeStamp'):
            with self.subTest(conflicting_field=field):
                fixtures = self.balance_fixture()
                fixtures['gl_line'].append(dict(fixtures['gl_line'][0]))
                duplicate = dict(fixtures['gl_account'][0])
                if field:
                    duplicate[field] = 'OTHER'
                fixtures['gl_account'].append(duplicate)
                rows = self.query('gl_account_balance', fixtures)
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertEqual(row['account_mapping_status'], 'ambiguous_native_account' if field else 'matched')
                self.assertEqual(row['journal_lines'], 2)
                self.assertEqual(row['signed_movement'], -200)
                self.assertEqual(row['absolute_movement'], 200)
                self.assertEqual(row['gl_account_source_rows'], 2)
                self.assertEqual(row['gl_account_distinct_rows'], 2 if field else 1)
                if field:
                    self.assertIsNone(row['GLACCOUNTTYPE'])
                    self.assertIsNone(row['native_account_delete_marker'])

    def test_legacy_unknown_member_never_matches_system_local_unknown(self):
        for view, make_fixture, fact_table, dim_table, surrogate in (
            ('invoice_customer', self.invoice_fixture, 'invoice_line', 'customer', '_key_ICUSTOMERSoldToParty'),
            ('gl_account_balance', self.balance_fixture, 'gl_line', 'gl_account', '_key_IGLACCOUNTINCHARTOFACCOUNTS'),
        ):
            fixtures = make_fixture()
            fixtures[fact_table][0][surrogate] = -1
            dimension = fixtures[dim_table][0]
            fixtures[dim_table] = [{**dimension, 'Key': -1, '_SystemName': None},
                                   {**dimension, 'Key': -1, '_SystemName': 'S4M'}]
            rows = self.query(view, fixtures)
            self.assertEqual(len(rows), 1)
            if view == 'gl_account_balance':
                self.assertEqual(rows[0]['journal_lines'], 1)
                self.assertEqual(rows[0]['signed_movement'], -100)
            else:
                self.assertEqual(rows[0]['GROSSAMOUNT'], 120)

    def test_fact_source_scope_excludes_other_systems_and_companies(self):
        for view, make_fixture, table in (
            ('invoice_customer', self.invoice_fixture, 'invoice_line'),
            ('gl_account_balance', self.balance_fixture, 'gl_line'),
        ):
            for column, value in (('_SystemName', 'OTHER'), ('COMPANYCODE', '9999')):
                with self.subTest(view=view, column=column):
                    fixtures = make_fixture()
                    fixtures[table][0][column] = value
                    self.assertEqual(self.query(view, fixtures), [])


class ZeroCopyTests(unittest.TestCase):
    def test_grouped_sources_quotes_reserved_plan_cte_references(self):
        from sources.sap.zero_copy import grouped_sources

        base = {'plan': "SELECT 1 AS [Key], 'basic' AS [name]"}
        grouped = grouped_sources(base, [('plan', ('Key',), ('Key', 'name'))])
        expected_references = {
            'plan_distinct': [('FROM', 'plan')],
            'plan_counts': [('FROM', 'plan')],
            'plan_variants': [('FROM', 'plan_distinct')],
            'plan_safe': [('FROM', 'plan_counts'), ('JOIN', 'plan_variants'),
                          ('LEFT JOIN', 'plan_distinct')],
        }
        for cte, references in expected_references.items():
            for clause, name in references:
                with self.subTest(cte=cte, reference=name):
                    self.assertIn(clause + ' ' + ident(name), grouped[cte])
        sql = 'WITH ' + ',\n'.join(
            ident(name) + ' AS (\n' + body + '\n)' for name, body in grouped.items())
        sql += '\nSELECT * FROM [plan_safe]'
        connection = sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        self.assertEqual(list(connection.execute(sql.replace('COUNT_BIG(*)', 'COUNT(*)'))),
                         [(1, 'basic', 1, 1)])

    def test_approved_company_sequence_preserves_scope_and_unknown(self):
        catalog = [{'TABLE_SCHEMA': 'dbo', 'TABLE_NAME': 'I_COMPANYCODE', 'COLUMN_NAME': c}
                   for c in ('Key', '_SystemName', 'COMPANYCODE', 'CURRENCY')]
        sql = source_views(catalog, 'db', 'S4M', ('1730', '1710', '1720'),
                           {'company': 'I_COMPANYCODE'})['company']
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute("ATTACH DATABASE ':memory:' AS native")
        db.execute('CREATE TABLE native.I_COMPANYCODE ([Key], _SystemName, COMPANYCODE, CURRENCY)')
        db.executemany('INSERT INTO native.I_COMPANYCODE VALUES (?, ?, ?, ?)', [
            (1, 'S4M', '1710', 'EUR'), (2, 'S4M', '1720', 'CAD'), (3, 'S4M', '1730', 'CHF'),
            (4, 'S4M', '9999', 'USD'), (5, 'OTHER', '1710', 'EUR'), (-1, None, None, None)])
        rows = list(db.execute(sql.replace('[db].[dbo].', 'native.')))
        self.assertEqual({r[0] for r in rows}, {1, 2, 3, -1})
        self.assertEqual(sql, source_views(catalog, 'db', 'S4M', ('1710', '1720', '1730'),
                                          {'company': 'I_COMPANYCODE'})['company'])
        for bad in ('9999', '1710 ', '01710', 1710, (), ('1710', '9999'), ('1710', '1710')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                source_views(catalog, 'db', 'S4M', bad, {'company': 'I_COMPANYCODE'})

    def test_historical_preview_source_contract_remains_unchanged(self):
        raw, catalog = preview_contract()
        base = source_views(catalog, 'bps_gold_a1b2c3d4', 'S4M', '1710', TABLES)
        # Historical artifact is schema evidence, not the revised monetary logic.
        # Regeneration and deployment belong to the parent operator.
        historical_batches = raw.decode('utf-8').replace('bps_gold_<system_suffix>', 'bps_gold_a1b2c3d4').split('-- @batch\n')
        for index, (name, sql) in enumerate(base.items(), 1):
            self.assertEqual(historical_batches[index],
                             'CREATE VIEW [sap_live].' + ident(name) + ' AS\n' + sql + ';\n')
        generated = render_bundle({**base, **business_views(base)})
        self.assertNotIn(b'\r', raw)
        self.assertEqual(generated, render_bundle({**base, **business_views(base)}))

    def test_preview_keeps_fact_keys_and_reads_native_source_only(self):
        self.assertIsNotNone(importlib.util.find_spec('sources.sap.zero_copy'),
                             'zero-copy preview renderer is not implemented')
        m = importlib.import_module('sources.sap.zero_copy')
        catalog = [{'TABLE_SCHEMA': 'dbo', 'TABLE_NAME': 'I_GLACCOUNTLINEITEMRAWDATA',
                    'COLUMN_NAME': n} for n in ['ACCOUNTINGDOCUMENT', 'COMPANYCODE', '_SystemName',
                    '_key_ICOMPANYCODE', '_key_ICUSTOMER', '_Delete']]
        views = m.source_views(catalog, 'bps_gold_a1b2c3d4', 'S4M', '1710',
                               {'gl_line': 'I_GLACCOUNTLINEITEMRAWDATA'})
        sql = views['gl_line']
        self.assertIn('s.[_key_ICOMPANYCODE]', sql)
        self.assertIn('s.[_key_ICUSTOMER]', sql)
        self.assertIn('[bps_gold_a1b2c3d4].[dbo].[I_GLACCOUNTLINEITEMRAWDATA]', sql)
        self.assertIn("s.[_SystemName] = 'S4M'", sql)
        self.assertIn("s.[COMPANYCODE] = '1710'", sql)
        self.assertNotIn('SELECT *', sql)
        self.assertTrue(sql.startswith('SELECT'))
        self.assertNotIn('gold.sap_', sql)

    def test_business_queries_keep_unmatched_rows_and_no_old_publication(self):
        m = importlib.import_module('sources.sap.zero_copy')
        self.assertTrue(hasattr(m, 'business_views'), 'business SELECTs missing')
        _, catalog = preview_contract()
        base = m.source_views(catalog, 'db', 'S4M', '1710', m.TABLES)
        views = m.business_views(base)
        invoice = views['invoice_customer']
        self.assertIn('LEFT JOIN customer', invoice)
        self.assertIn('FROM gold.dim_customer', invoice)
        self.assertIn('LEFT JOIN shared_customer_safe', invoice)
        self.assertIn('[_key_ICUSTOMERSoldToParty]', invoice)
        self.assertIn('customer_mapping_status', invoice)
        self.assertNotIn('gold.sap_publication', invoice)
        self.assertIn('SELECT DISTINCT', invoice)
        self.assertNotRegex(invoice, r'SELECT DISTINCT\s+b\.')
        self.assertNotIn('INNER JOIN', invoice)
        balance = views['gl_account_balance']
        self.assertIn('[_key_IGLACCOUNTINCHARTOFACCOUNTS]', balance)
        self.assertIn('GROUP BY', balance)
        self.assertIn('TRANSACTIONCURRENCY', balance)

    def test_dimension_unknown_members_and_identifier_escaping(self):
        from sources.sap.zero_copy import source_views, ident, literal
        catalog = [{'TABLE_SCHEMA': 'dbo', 'TABLE_NAME': 'I_CUSTOMER', 'COLUMN_NAME': n}
                   for n in ['Key', 'CUSTOMER', '_SystemName']]
        sql = source_views(catalog, 'db]name', "S'4M", '1710', {'customer': 'I_CUSTOMER'})['customer']
        self.assertIn('[db]]name]', sql)
        self.assertIn("'S''4M'", sql)
        self.assertIn('s.[Key] = -1 AND s.[_SystemName] IS NULL', sql)
        for bad in ['', 'x\n', 'x' * 129, None]:
            with self.assertRaises(ValueError):
                ident(bad)
            with self.assertRaises(ValueError):
                literal(bad)
        with self.assertRaises(ValueError):
            source_views(catalog + [catalog[0]], 'db', 'S4M', '1710', {'c': 'I_CUSTOMER'})
        with self.assertRaises(ValueError):
            source_views([], 'db', 'S4M', '1710', {'c': 'I_CUSTOMER'})

    def test_sql_bundle_is_additive_schema_and_views_only(self):
        m = importlib.import_module('sources.sap.zero_copy')
        self.assertTrue(hasattr(m, 'render_bundle'), 'SQL bundle renderer missing')
        sql = m.render_bundle({'gl_line': 'SELECT 1 AS sample'})
        self.assertIn('CREATE SCHEMA [sap_live]', sql)
        self.assertIn('CREATE VIEW [sap_live].[gl_line]', sql)
        self.assertNotIn('ALTER', sql)
        self.assertNotIn('INSERT', sql)
        self.assertNotIn('DROP', sql)
        self.assertNotIn('CREATE TABLE', sql)
        self.assertIn('not executed', sql)


if __name__ == '__main__':
    unittest.main()
