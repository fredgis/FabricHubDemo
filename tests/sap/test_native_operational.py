"""Offline native operational adapter tests; no private reference data required."""
import importlib
import unittest


class NativeOperationalTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('sources.sap.native_operational'),
                             'native operational adapter is missing')
        return importlib.import_module('sources.sap.native_operational')

    def fixture(self):
        from sources.sap import native, coherent_finance
        from sources.sap.config import DEFAULT_CONFIG, DEFAULT_REFERENCES, read_json
        from tests.sap.test_coherent_finance import order, snapshot
        from types import SimpleNamespace
        scenario = native.build(read_json(DEFAULT_CONFIG), read_json(DEFAULT_REFERENCES))
        base = SimpleNamespace(schemas=scenario.schemas, tables=scenario.snapshots[-1].tables,
                               native_contract=scenario.native_contract)
        rows = [order(i, currency=c, territory=t, first_play_at_utc='2026-10-08 12:00:00')
                for i, c, t in [(1, 'EUR', 'FR'), (2, 'CAD', 'CA'), (3, 'CHF', 'CH')]]
        for i, row in enumerate(rows, 1):
            row['offer_key'] = 'FILM:' + row['territory'] + ':RENTAL'
            row['customer_key'] = f'MSF-C{i:04d}'
            row['salesforce_contact_id'] = f'003TEST{i:011d}'
        # Existing identity is authoritative and cannot be relabelled.
        rows[0]['salesforce_contact_id'] = '003aj00002Tu8h7AAB'
        refs = {'queries': {'crm_customers': {'rows': [
            {'customer_key': row['customer_key'], 'name': 'Camille Delorme' if i == 0 else f'Test {i}',
             'territory': row['territory'], 'source_customer_id': row['salesforce_contact_id']}
            for i, row in enumerate(rows)]}}}
        source = snapshot(*rows)
        result = coherent_finance.build(source, coherent_finance.demo_policy(
            unpaid_per_currency=0, refunded_per_currency=1))
        return base, result, source, refs, scenario.native_contract

    def test_end_to_end_additions_preserve_baseline_and_link_all_items(self):
        import copy
        from decimal import Decimal
        from sources.sap.datasphere import digest, json_bytes
        base, result, source, refs, contract = self.fixture()
        fingerprints = {n: digest(json_bytes(rows)) for n, rows in base.tables.items()}
        self.assertTrue(hasattr(self.api(), 'adapt'), 'adapt API missing')
        adapted = self.api().adapt(result, source, refs, base, contract=contract)
        self.assertEqual(fingerprints, {n: digest(json_bytes(rows)) for n, rows in base.tables.items()})
        for n, obj in base.schemas.items():
            self.assertEqual(adapted.schemas[n], obj)
            old = obj.index(base.tables[n])
            combined = obj.index(adapted.tables[n])
            self.assertTrue(all(combined[k] == r for k, r in old.items()))
        billing = adapted.additions['C_BILLINGDOCITEMBASICDEX_1']
        links = adapted.additions['ZMSF_ORDER_LINK']
        self.assertEqual(len(billing), len(result.billing))
        self.assertEqual(len(links), len(billing))
        self.assertEqual({(r['BILLINGDOCUMENT'], r['BILLINGDOCUMENTITEM']) for r in links},
                         {(r['BILLINGDOCUMENT'], r['BILLINGDOCUMENTITEM']) for r in billing})
        self.assertTrue(all(r['BASEUNIT'] == r['BILLINGQUANTITYUNIT'] == 'EA' for r in billing))
        self.assertEqual({r['PRODUCT'] for r in billing}, {r['offer_key'] for r in source['orders']})
        self.assertTrue(all(r['BILLINGDOCUMENTTYPE'] in {'ZF2', 'ZG2'} for r in billing))
        self.assertFalse(set(adapted.additions) & {'ZMSF_SUBSCRIPTION', 'ZMSF_BILLING_LINK', 'ZMSF_PLAN'})
        for name, rows in adapted.additions.items():
            adapted.schemas[name].index(rows)
            self.assertTrue(all(set(r) == {f.name for f in adapted.schemas[name].fields} for r in rows))
        companies = {r['COMPANYCODE']: r for r in adapted.tables['I_COMPANYCODE']}
        controls = {r['CONTROLLINGAREA']: r for r in adapted.tables['I_CONTROLLINGAREA']}
        for r in adapted.additions['I_OPERATIONALACCTGDOCITEM']:
            self.assertEqual(companies[r['COMPANYCODE']]['CURRENCY'], r['TRANSACTIONCURRENCY'])
            self.assertEqual(controls[r['CONTROLLINGAREA']]['CONTROLLINGAREACURRENCY'], r['GLOBALCURRENCY'])
            self.assertEqual(r['AMOUNTINGLOBALCURRENCY'], r['AMOUNTINTRANSACTIONCURRENCY'])
        self.assertEqual(adapted.report['unresolved_relationships'], [])
        self.assertTrue(adapted.report['valid'])

    def test_rejects_inconsistent_signed_posting_roles(self):
        from dataclasses import replace
        base, result, source, refs, contract = self.fixture()
        for field, value in [('DEBITCREDITCODE', 'H'), ('POSTINGKEY', '50'),
                             ('POSTINGKEY', '11'), ('FINANCIALACCOUNTTYPE', 'S'),
                             ('GLACCOUNT', '0011000000'), ('GLACCOUNT', '0099999999')]:
            journal = [dict(r) for r in result.journal]
            next(r for r in journal if r['FINANCIALACCOUNTTYPE'] == 'D'
                 and r['AMOUNTINTRANSACTIONCURRENCY'] > 0)[field] = value
            gl = [{**r, 'SOURCELEDGER': '0L', 'LEDGERGLLINEITEM': r['ACCOUNTINGDOCUMENTITEM'].zfill(6)}
                  for r in journal]
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, 'posting role'):
                self.api().adapt(replace(result, journal=journal, gl=gl), source, refs, base, contract=contract)

    def test_customer_links_require_unique_complete_order_customer_coverage(self):
        from dataclasses import replace
        base, result, source, refs, contract = self.fixture()
        for links in [(), result.customer_links[:-1], result.customer_links + result.customer_links[:1]]:
            with self.subTest(links=links), self.assertRaisesRegex(ValueError, 'customer link'):
                self.api().adapt(replace(result, customer_links=links), source, refs, base, contract=contract)

    def test_each_order_crm_identity_is_checked_independently_of_links(self):
        import copy
        from dataclasses import replace
        from sources.sap import coherent_finance
        base, result, source, refs, contract = self.fixture()
        bad_source = copy.deepcopy(source)
        bad_source['orders'][1]['salesforce_contact_id'] = '003BOGUS0000000000'
        bad_result = coherent_finance.build(bad_source, result.policy)
        for links in [(), result.customer_links]:
            with self.subTest(links=links), self.assertRaisesRegex(ValueError, 'actual CRM identity'):
                self.api().adapt(replace(bad_result, customer_links=links), bad_source, refs, base, contract=contract)

    def test_contract_is_bound_to_baseline_inventory_and_provenance(self):
        import copy
        from dataclasses import replace
        base, result, source, refs, contract = self.fixture()
        substituted = copy.deepcopy(contract.joins)
        substituted[0] = copy.deepcopy(substituted[1])  # Same count is not coverage.
        cases = [replace(contract, joins=[], schemas={}, objects={}, provenance={}, excluded_relationships=[]),
                 replace(contract, joins=substituted), replace(contract, schemas={}),
                 replace(contract, objects={}), replace(contract, provenance={}),
                 replace(contract, excluded_relationships=[])]
        for index, bad in enumerate(cases):
            with self.subTest(case=index), self.assertRaisesRegex(ValueError, 'contract'):
                self.api().adapt(result, source, refs, base, contract=bad)
        changed_base = copy.deepcopy(base)
        changed_base.native_contract = replace(contract, provenance={**contract.provenance, 'scope': 'other capture'})
        with self.assertRaisesRegex(ValueError, 'contract'):
            self.api().adapt(result, source, refs, changed_base, contract=contract)

    def test_relationship_coverage_reports_expected_checked_inventory_hashes(self):
        base, result, source, refs, contract = self.fixture()
        adapted = self.api().adapt(result, source, refs, base, contract=contract)
        coverage = adapted.report.get('relationship_coverage', {})
        self.assertEqual(coverage.get('expected'), len(contract.joins) + 3)
        self.assertEqual(coverage.get('checked'), coverage.get('expected'))
        self.assertEqual(len(coverage['expected_sha256']), 64)
        self.assertEqual(coverage['checked_sha256'], coverage['expected_sha256'])
        self.assertEqual(adapted.report['contract_binding']['expected_sha256'],
                         adapted.report['contract_binding']['checked_sha256'])
        unknown = ['ZMSF_ORDER_LINK', 'UNKNOWN', [], [], 'unknown']
        report = self.api().relationship_report(adapted.tables, adapted.schemas, [unknown])
        self.assertEqual(report['relationship_coverage']['expected'], 1)
        self.assertEqual(report['relationship_coverage']['checked'], 0)
        self.assertNotEqual(report['relationship_coverage']['expected_sha256'],
                            report['relationship_coverage']['checked_sha256'])

    def test_mandatory_bridge_customer_never_uses_native_initial_exemption(self):
        base, result, source, refs, contract = self.fixture()
        adapted = self.api().adapt(result, source, refs, base, contract=contract)
        row = adapted.tables['ZMSF_ORDER_LINK'][0]
        for value in ['', None]:
            row['CUSTOMER'] = value
            report = self.api().relationship_report(adapted.tables, adapted.schemas,
                [['ZMSF_ORDER_LINK', 'I_CUSTOMER', [['CUSTOMER', 'CUSTOMER', '==']], [], 'customer']])
            with self.subTest(value=value):
                self.assertFalse(report['valid'])
                self.assertEqual(report['relationships'][0]['unassigned'], 0)

    def test_nullable_product_exemption_requires_explicit_supplier_portfolio(self):
        from sources.sap import coherent_finance
        base, result, source, refs, contract = self.fixture()
        result = coherent_finance.build(source, coherent_finance.demo_policy(refunded_per_currency=0, unpaid_per_currency=0))
        adapted = self.api().adapt(result, source, refs, base, contract=contract)
        for fact in ['I_OPERATIONALACCTGDOCITEM', 'I_GLACCOUNTLINEITEMRAWDATA']:
            customer = dict(next(r for r in adapted.additions[fact] if r['FINANCIALACCOUNTTYPE'] == 'D'))
            customer.update(BILLINGDOCUMENT='', PRODUCT=None, PRODUCTGROUP=None)
            supplier_rows = [r for r in adapted.additions[fact] if r['ACCOUNTINGDOCUMENTTYPE'] in {'KR', 'KZ'}]
            for dim, field in [('I_PRODUCT', 'PRODUCT'), ('I_PRODUCTGROUP_2', 'PRODUCTGROUP')]:
                join = [[fact, dim, [[field, field, '==']], [], 'product']]
                with self.subTest(fact=fact, dim=dim):
                    bad = self.api().relationship_report({**adapted.tables, fact: [customer]}, adapted.schemas, join)
                    self.assertFalse(bad['valid'])
                    good = self.api().relationship_report({**adapted.tables, fact: supplier_rows}, adapted.schemas, join)
                    self.assertTrue(good['valid'])
                    self.assertEqual(good['relationships'][0]['unassigned'], len(supplier_rows))
                    fake = {**supplier_rows[0], 'DOCUMENTITEMTEXT': 'not supplier portfolio'}
                    self.assertFalse(self.api().relationship_report(
                        {**adapted.tables, fact: [fake]}, adapted.schemas, join)['valid'])

    def test_existing_account_classification_conflicts_fail_without_baseline_edits(self):
        import copy
        base, result, source, refs, contract = self.fixture()
        for account, changes in [
                ('0011000000', {'ISBALANCESHEETACCOUNT': '', 'ISPROFITLOSSACCOUNT': 'X', 'GLACCOUNTTYPE': 'P'}),
                ('0012000000', {'ISPROFITLOSSACCOUNT': 'X'}),
                ('0011000000', {'GLACCOUNTTYPE': 'P'}),
                ('0041000000', {'ISBALANCESHEETACCOUNT': 'X', 'ISPROFITLOSSACCOUNT': '', 'GLACCOUNTTYPE': 'X'})]:
            bad = copy.deepcopy(base)
            rows = bad.tables['I_GLACCOUNTINCHARTOFACCOUNTS']
            row = next((r for r in rows if r['GLACCOUNT'] == account), None)
            if row is None:
                template = next(r for r in rows if r['GLACCOUNT'] == '0011000000')
                row = {**template, 'GLACCOUNT': account}
                rows.append(row)
            row.update(changes)
            before = copy.deepcopy(bad.tables)
            with self.subTest(account=account, changes=changes), self.assertRaisesRegex(ValueError, 'account classification'):
                self.api().adapt(result, source, refs, bad, contract=contract)
            self.assertEqual(bad.tables, before)

    def test_rejects_tampered_finance_source_links_and_payments(self):
        from dataclasses import replace
        from decimal import Decimal
        import copy
        base, result, source, refs, contract = self.fixture()
        changed_gl = [dict(r) for r in result.gl]
        changed_gl[0]['AMOUNTINTRANSACTIONCURRENCY'] += Decimal('0.01')
        changed_links = [dict(r) for r in result.line_bridges]
        changed_links[0]['order_id'] = 'not-an-actual-order'
        changed_payments = [dict(r) for r in result.payments]
        changed_payments[0]['gross'] += Decimal('0.01')
        changed_credit = [dict(r) for r in result.line_bridges]
        next(r for r in changed_credit if r['original_billing_document'])['original_billing_document'] = '7999999999'
        cases = [replace(result, gl=changed_gl), replace(result, line_bridges=changed_links),
                 replace(result, payments=changed_payments), replace(result, line_bridges=changed_credit),
                 replace(result, billing=result.billing + result.billing[:1]),
                 replace(result, line_bridges=result.line_bridges[:-1])]
        for bad in cases:
            with self.subTest(case=cases.index(bad)), self.assertRaises(ValueError):
                self.api().adapt(bad, source, refs, base, contract=contract)

    def test_unresolved_declared_custom_relationship_fails_closed(self):
        base, result, source, refs, contract = self.fixture()
        join = ['ZMSF_ORDER_LINK', 'ZMSF_SUBSCRIPTION',
                [['ORDER_ID', 'SUBSCRIPTION_ID', '==']], [], 'forbidden_subscription_requirement']
        adapted = self.api().adapt(result, source, refs, base, contract=contract, extra_relationships=[join])
        self.assertFalse(adapted.report['valid'])
        self.assertEqual(adapted.report['unresolved_relationships'][0]['missing'], len(result.billing))
        self.assertEqual(len(base.tables['ZMSF_SUBSCRIPTION']), len(adapted.tables['ZMSF_SUBSCRIPTION']))

    def test_native_widths_and_identity_collisions_are_rejected(self):
        import copy
        from dataclasses import replace
        base, result, source, refs, contract = self.fixture()
        bad = copy.deepcopy(refs)
        bad['queries']['crm_customers']['rows'][0]['name'] = 'Changed old customer'
        with self.assertRaisesRegex(ValueError, 'conflicting existing key'):
            self.api().adapt(result, source, bad, base, contract=contract)
        adapted = self.api().adapt(result, source, refs, base, contract=contract)
        schema = adapted.schemas['ZMSF_ORDER_LINK']
        row = adapted.additions['ZMSF_ORDER_LINK'][0]
        for field, value in [('BILLINGDOCUMENT', '1' * 11), ('BILLINGDOCUMENTITEM', '1'),
                             ('ORDER_LINE_NUMBER', True), ('ORDER_LINE_NUMBER', 2147483648),
                             ('ORDER_ID', 'x' * 129), ('BILLINGDOCUMENTITEM', '\u0660' * 6)]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                schema.index([{**row, field: value}])
        base.tables['C_BILLINGDOCITEMBASICDEX_1'].append(adapted.additions['C_BILLINGDOCITEMBASICDEX_1'][0])
        base.tables['C_BILLINGDOCITEMBASICDEX_1'][-1]['NETAMOUNT'] += 1
        with self.assertRaisesRegex(ValueError, 'conflicting existing key'):
            self.api().adapt(result, source, refs, base, contract=contract)

    def test_rejects_wrong_clearing_customer_and_credit_invoice_reference(self):
        from dataclasses import replace
        base, result, source, refs, contract = self.fixture()
        for field, value, kind in [('CLEARINGACCOUNTINGDOCUMENT', '8999999999', 'DR'),
                                   ('INVOICEREFERENCE', '8999999999', 'DG')]:
            journal = [dict(r) for r in result.journal]
            next(r for r in journal if r['ACCOUNTINGDOCUMENTTYPE'] == kind and r['FINANCIALACCOUNTTYPE'] == 'D')[field] = value
            gl = [{**r, 'SOURCELEDGER': '0L', 'LEDGERGLLINEITEM': r['ACCOUNTINGDOCUMENTITEM'].zfill(6)} for r in journal]
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.api().adapt(replace(result, journal=journal, gl=gl), source, refs, base, contract=contract)

    def test_bridge_foreign_keys_and_nullable_credit_reference_are_checked(self):
        base, result, source, refs, contract = self.fixture()
        adapted = self.api().adapt(result, source, refs, base, contract=contract)
        names = {r['relationship'] for r in adapted.report['relationships']}
        self.assertTrue({'order_billing', 'order_customer', 'order_original_billing'} <= names)

    def test_relationship_validator_rejects_unknown_and_ambiguous_targets(self):
        from sources.sap import native
        base, result, source, refs, contract = self.fixture()
        adapted = self.api().adapt(result, source, refs, base, contract=contract)
        join = ['ZMSF_ORDER_LINK', 'I_CUSTOMER', [['CUSTOMER', 'CUSTOMER', '==']], [], 'customer']
        row = adapted.tables['ZMSF_ORDER_LINK'][0]
        row['CUSTOMER'] = '9999999999'
        report = self.api().relationship_report(adapted.tables, adapted.schemas, [join])
        self.assertFalse(report['valid'])
        self.assertEqual(report['unresolved_relationships'][0]['missing'], 1)
        row['CUSTOMER'] = adapted.tables['I_CUSTOMER'][0]['CUSTOMER']
        adapted.tables['I_CUSTOMER'].append(adapted.tables['I_CUSTOMER'][0])
        report = self.api().relationship_report(adapted.tables, adapted.schemas, [join])
        self.assertFalse(report['valid'])
        self.assertGreater(report['unresolved_relationships'][0]['ambiguous'], 0)
        bad = ['ZMSF_ORDER_LINK', 'UNKNOWN', [], [], 'unknown']
        self.assertFalse(self.api().relationship_report(adapted.tables, adapted.schemas, [bad])['valid'])

    def test_report_distinguishes_scoped_and_excluded_relationships(self):
        base, result, source, refs, contract = self.fixture()
        adapted = self.api().adapt(result, source, refs, base, contract=contract)
        self.assertEqual(adapted.report.get('excluded_global_relationships'), contract.excluded_relationships)
        self.assertEqual(adapted.report.get('finance_validated'), True)

    def test_supplier_is_explicit_demo_and_not_a_catalog_distributor(self):
        import copy
        from sources.sap import coherent_finance
        base, result, source, refs, contract = self.fixture()
        before = copy.deepcopy(source)
        result = coherent_finance.build(source, coherent_finance.demo_policy(refunded_per_currency=0, unpaid_per_currency=0))
        adapted = self.api().adapt(result, source, refs, base, contract=contract)
        self.assertTrue(adapted.report['valid'])
        self.assertEqual(source, before)
        suppliers = adapted.additions['I_SUPPLIER']
        self.assertEqual([r['SUPPLIER'] for r in suppliers], ['0099000001'])
        self.assertIn('synthetic', suppliers[0]['SUPPLIERNAME'])
        self.assertNotIn('ZMSF_RIGHTS_COVERAGE', adapted.additions)
        self.assertTrue(any(r['GLACCOUNT'] == '0051000000' for r in adapted.additions['I_OPERATIONALACCTGDOCITEM']))

    def test_only_new_schema_is_exact_native_order_bridge(self):
        from sources.sap import native
        schemas = native.load_contract().schemas
        result = self.api().schema_inventory(schemas)
        self.assertEqual(set(result) - set(schemas), {'ZMSF_ORDER_LINK'})
        self.assertTrue(all(result[n] == obj for n, obj in schemas.items()))
        bridge = result['ZMSF_ORDER_LINK']
        self.assertTrue(bridge.financial)
        self.assertEqual(bridge.keys, ('BILLINGDOCUMENT', 'BILLINGDOCUMENTITEM'))
        self.assertEqual([(f.name, f.ddic, f.length, f.nullable) for f in bridge.fields], [
            ('BILLINGDOCUMENT', 'CHAR', 10, False),
            ('BILLINGDOCUMENTITEM', 'NUMC', 6, False),
            ('CUSTOMER', 'CHAR', 10, False), ('ORDER_ID', 'CHAR', 128, False),
            ('ORDER_LINE_NUMBER', 'INT4', 10, False),
            ('ORIGINAL_BILLINGDOCUMENT', 'CHAR', 10, True),
            ('ORIGINAL_BILLINGDOCUMENTITEM', 'NUMC', 6, True),
            ('SIMULATION_ONLY', 'CHAR', 1, False)])


if __name__ == '__main__':
    unittest.main()
