"""Offline, stdlib-only finance tests; fixtures are not the private order snapshot."""
import copy
import importlib
import unittest
from datetime import date
from decimal import Decimal as D


def order(number=1, **changes):
    row = {
        "order_id": f"00000000-0000-4000-8000-{number:012d}", "line_number": 1,
        "customer_key": "MSF-C0001", "offer_key": "FILM:FR:RENTAL",
        "content_key": "FILM", "territory": "FR", "currency": "EUR", "usage_type": "TVOD",
        "amount_minor": 399, "amount_decimal": "3.9900",
        "ordered_at_utc": "2026-10-07 10:00:00.000000", "first_play_at_utc": None,
        "status": "active", "source_event_id": f"10000000-0000-4000-8000-{number:012d}",
        "salesforce_contact_id": "003aj00002Tu8h7AAB", "catalog_distributor_key": None,
    }
    row.update(changes)
    return row


def snapshot(*rows):
    return {"provenance": "unit test", "source_observed_at": "2026-10-11 18:46:54.321679",
            "orders": list(rows)}


class FinanceTests(unittest.TestCase):
    def engine(self):
        try:
            return importlib.import_module("sources.sap.coherent_finance")
        except ModuleNotFoundError:
            self.fail("The new pure coherent_finance engine has not been implemented")

    def build(self, *rows, **policy):
        engine = self.engine()
        return engine.build(snapshot(*rows), engine.demo_policy(
            refunded_per_currency=0, unpaid_per_currency=0, **policy))

    def test_unpaid_selection_is_explicit_and_keeps_receivable_open(self):
        engine = self.engine()
        policy = engine.demo_policy(refunded_per_currency=0, unpaid_per_currency=1)
        result = engine.build(snapshot(order(1), order(2)), policy)
        self.assertEqual(result.totals['EUR']['receivables'], D('3.99'))
        self.assertEqual(result.totals['EUR']['customer_cash_net'], D('3.99'))
        self.assertEqual(len([p for p in result.payments if p.get('account_type') != 'K']), 1)
        self.assertEqual(len(result.policy['selected_unpaid_order_lines']), 1)
        ar = [r for r in result.journal if r['FINANCIALACCOUNTTYPE'] == 'D'
              and r['CLEARINGDATE'] is None]
        self.assertEqual(len(ar), 1)
        self.assertEqual(ar[0]['AMOUNTINTRANSACTIONCURRENCY'], D('3.99'))

    def test_refund_reverses_recognized_invoice_without_changing_order(self):
        engine = self.engine()
        source = snapshot(order(1, first_play_at_utc='2026-10-08 12:00:00'), order(2))
        before = copy.deepcopy(source)
        result = engine.build(source, engine.demo_policy(refunded_per_currency=1, unpaid_per_currency=0))
        self.assertEqual(source, before)
        self.assertEqual(len(result.billing), 3)
        credit = next(r for r in result.billing if r['NETAMOUNT'] < 0)
        self.assertEqual(credit['GROSSAMOUNT'], D('-3.99'))
        self.assertEqual(result.totals['EUR']['recognized_net'], D('0.00'))
        self.assertEqual(result.totals['EUR']['customer_cash_net'], D('3.99'))
        self.assertEqual(len(result.policy['selected_refunded_order_lines']), 1)
        self.assertTrue(all(r['CLEARINGDATE'] is not None for r in result.journal
                            if r['FINANCIALACCOUNTTYPE'] == 'D'))
        credit_link = next(r for r in result.line_bridges if r['original_billing_document'])
        self.assertEqual(credit_link['order_id'], order(1)['order_id'])

    def test_supplier_cost_and_partial_payment_are_separate_per_currency(self):
        result = self.build(order(first_play_at_utc='2026-10-08 12:00:00'),
                            order(2, currency='CAD', territory='CA', first_play_at_utc='2026-10-08 12:00:00'))
        for currency in ('EUR', 'CAD'):
            self.assertEqual(result.totals[currency]['content_cost'], D('0.67'))
            self.assertEqual(result.totals[currency]['payables'], D('0.40'))
            self.assertEqual(result.totals[currency]['supplier_cash'], D('0.40'))
            ap = [r for r in result.journal if r['TRANSACTIONCURRENCY'] == currency
                  and r['FINANCIALACCOUNTTYPE'] == 'K']
            self.assertEqual(sum(r['AMOUNTINTRANSACTIONCURRENCY'] for r in ap), D('-0.40'))
            self.assertTrue(all(r['SUPPLIER'] and r['CLEARINGDATE'] is None for r in ap))
        for doc in result.documents:
            self.assertEqual(sum(r['AMOUNTINTRANSACTIONCURRENCY'] for r in result.journal
                                 if r['ACCOUNTINGDOCUMENT'] == doc['document']), D('0.00'))

    def test_rejects_invalid_financial_inputs_before_generating_rows(self):
        engine = self.engine()
        invalid = [dict(amount_decimal=3.99), dict(amount_decimal='NaN'),
                   dict(amount_minor=400), dict(line_number=True), dict(customer_key='BAD-C0001'),
                   dict(currency='USD'), dict(usage_type='SVOD'), dict(order_id=''),
                   dict(ordered_at_utc='2026-10-12 00:00:00'),
                   dict(first_play_at_utc='2026-10-06 00:00:00')]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                engine.build(snapshot(order(**changes)), engine.demo_policy())
        with self.assertRaises(ValueError):
            engine.build(snapshot(order(), order()), engine.demo_policy())
        for changes in ({'simulation_only': False}, {'tax_rate': 'NaN'},
                        {'unpaid_per_currency': -1}, {'supplier_fixed_net': '1.00'},
                        {'supplier_payment_fraction': '2.0'}):
            with self.subTest(policy=changes), self.assertRaises(ValueError):
                engine.build(snapshot(order()), {**engine.demo_policy(), **changes})

    def test_rejects_policy_contradicting_fixed_demo_contract(self):
        engine = self.engine()
        for changes in ({'rounding': 'ROUND_DOWN'}, {'source_system': 'OTHER'},
                        {'fiscal_year': 2025}, {'fiscal_year': True},
                        {'fiscal_year': '2026'}, {'cutoff_date': '2025-12-31'}):
            with self.subTest(policy=changes), self.assertRaisesRegex(ValueError, 'policy'):
                engine.build(snapshot(order()), {**engine.demo_policy(), **changes})

    def test_rejects_source_business_dates_outside_approved_fiscal_year(self):
        cases = ({'ordered_at_utc': '2025-12-31 12:00:00'},
                 {'first_play_at_utc': '2027-01-01 00:00:00'})
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'fiscal year'):
                self.build(order(**changes))

    def test_mixed_naive_and_aware_timestamps_use_utc(self):
        for ordered, played in (
                ('2026-10-07 10:00:00', '2026-10-08T12:00:00Z'),
                ('2026-10-07T10:00:00Z', '2026-10-08 12:00:00')):
            with self.subTest(ordered=ordered, played=played):
                result = self.build(order(ordered_at_utc=ordered, first_play_at_utc=played))
                self.assertEqual(result.totals['EUR']['recognized_net'], D('3.33'))
        with self.assertRaisesRegex(ValueError, 'Playback before order'):
            self.build(order(first_play_at_utc='2026-10-07T10:30:00+01:00'))

    def test_utc_playback_after_cutoff_remains_deferred_including_refund(self):
        engine = self.engine()
        row = order(ordered_at_utc='2026-10-07T10:00:00Z',
                    first_play_at_utc='2026-10-11T23:30:00-02:00')
        result = self.build(row)
        self.assertEqual(result.totals['EUR']['deferred_net'], D('3.33'))
        self.assertEqual(result.totals['EUR']['recognized_net'], D('0.00'))
        result = engine.build(snapshot(row), engine.demo_policy(
            refunded_per_currency=1, unpaid_per_currency=0))
        self.assertFalse(any(d['kind'] == 'recognition' for d in result.documents))
        credit = [r for r in result.journal if r['ACCOUNTINGDOCUMENTTYPE'] == 'DG']
        self.assertIn(engine.ACCOUNTS['deferred_TVOD'], {r['GLACCOUNT'] for r in credit})
        self.assertNotIn(engine.ACCOUNTS['revenue_TVOD'], {r['GLACCOUNT'] for r in credit})

    def test_utc_order_after_cutoff_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Order after financial cutoff'):
            self.build(order(ordered_at_utc='2026-10-11T23:30:00-02:00'))

    def test_posting_and_billing_dates_are_extracted_after_utc_conversion(self):
        result = self.build(order(ordered_at_utc='2026-10-08T00:30:00+02:00',
                                  first_play_at_utc='2026-10-12T00:30:00+02:00'))
        self.assertEqual(result.billing[0]['BILLINGDOCUMENTDATE'], date(2026, 10, 7))
        dates = {d['kind']: d['posting_date'] for d in result.documents}
        self.assertEqual(dates['invoice'], date(2026, 10, 7))
        self.assertEqual(dates['recognition'], date(2026, 10, 11))
        self.assertEqual(result.totals['EUR']['recognized_net'], D('3.33'))
        self.assertTrue(all(r['FISCALYEAR'] == '2026' for r in result.journal))

    def test_fiscal_year_validation_uses_utc_business_dates(self):
        for changes in ({'ordered_at_utc': '2026-01-01T00:30:00+02:00'},
                        {'first_play_at_utc': '2026-12-31T23:30:00-02:00'}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'fiscal year'):
                self.build(order(**changes))
        result = self.build(order(ordered_at_utc='2025-12-31T23:30:00-02:00'))
        self.assertEqual(result.billing[0]['BILLINGDOCUMENTDATE'], date(2026, 1, 1))

    def test_supplied_selections_reject_population_drift(self):
        engine = self.engine()
        source = snapshot(order(2), order(3), order(4))
        for field, counts in (
                ('selected_unpaid_order_lines', {'unpaid_per_currency': 1, 'refunded_per_currency': 0}),
                ('selected_refunded_order_lines', {'unpaid_per_currency': 0, 'refunded_per_currency': 1})):
            policy = engine.build(source, engine.demo_policy(**counts)).policy
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                engine.build(snapshot(order(1), *source['orders']), policy)

    def test_supplied_selections_allow_identical_tuple_and_json_list_replay(self):
        engine = self.engine()
        source = snapshot(order(1), order(2), order(3))
        result = engine.build(source, engine.demo_policy())
        self.assertEqual(engine.build(source, result.policy), result)
        policy = dict(result.policy)
        policy['companies'] = dict(policy['companies'])
        for field in ('selected_unpaid_order_lines', 'selected_refunded_order_lines'):
            policy[field] = [list(key) for key in policy[field]]
        before = copy.deepcopy(policy)
        self.assertEqual(engine.build(snapshot(*reversed(source['orders'])), policy), result)
        self.assertEqual(policy, before)

    def test_supplied_selections_reject_mismatched_or_malformed_output_fields(self):
        engine = self.engine()
        for field in ('selected_unpaid_order_lines', 'selected_refunded_order_lines'):
            for supplied in ([], None, [[order()['order_id'], True]],
                             [[order()['order_id'], 2]], [[order()['order_id'], 1]] * 2):
                policy = engine.demo_policy(
                    unpaid_per_currency=int(field == 'selected_unpaid_order_lines'),
                    refunded_per_currency=int(field == 'selected_refunded_order_lines'))
                policy[field] = supplied
                with self.subTest(field=field, supplied=supplied), self.assertRaisesRegex(ValueError, field):
                    engine.build(snapshot(order()), policy)

    def test_document_id_collision_is_rejected(self):
        from unittest.mock import patch
        engine = self.engine()
        with patch.object(engine, '_identifier', return_value='8000000000'):
            with self.assertRaisesRegex(ValueError, 'collision'):
                self.build(order())

    def test_stable_immutable_output_and_low_caller_precision(self):
        from decimal import localcontext
        rows = [order(1), order(2, line_number=2, usage_type='EST')]
        expected = self.build(*rows)
        with localcontext() as ctx:
            ctx.prec = 3
            self.assertEqual(self.build(*reversed(rows)), expected)
        with self.assertRaises(TypeError):
            expected.totals['EUR']['receivables'] = D('1')
        with self.assertRaises(TypeError):
            expected.policy['companies']['EUR'] = '9999'
        self.assertEqual(len({b['order_id'] for b in expected.line_bridges}), 2)

    def test_invoice_preserves_original_gross_and_defers_unplayed_net(self):
        result = self.build(order())
        invoice = result.billing[0]
        self.assertEqual((invoice["NETAMOUNT"], invoice["TAXAMOUNT"], invoice["GROSSAMOUNT"]),
                         (D("3.33"), D("0.66"), D("3.99")))
        self.assertEqual(result.totals["EUR"]["deferred_net"], D("3.33"))
        self.assertEqual(result.totals["EUR"]["recognized_net"], D("0.00"))
        self.assertEqual(result.documents[0]["posting_date"], date(2026, 10, 7))
        self.assertEqual(result.line_bridges[0]["order_id"], order()["order_id"])
        self.assertEqual(result.customer_links[0]["CUSTOMER"], "0010000001")
        self.assertTrue(all(row["GLACCOUNT"] not in {"0023000000", "0040000000"}
                            for row in result.journal))

    def test_recognition_follows_playback_and_cash_fully_clears_invoice(self):
        result = self.build(order(first_play_at_utc="2026-10-08 12:00:00"))
        self.assertEqual([d["kind"] for d in result.documents if not d['kind'].startswith('supplier_')],
                         ["invoice", "recognition", "cash"])
        self.assertEqual(result.documents[1]["posting_date"], date(2026, 10, 8))
        self.assertEqual(result.totals["EUR"]["recognized_net"], D("3.33"))
        self.assertEqual(result.totals["EUR"]["deferred_net"], D("0.00"))
        self.assertEqual(result.totals["EUR"]["receivables"], D("0.00"))
        self.assertEqual(result.totals["EUR"]["customer_cash_net"], D("3.99"))
        ar = [r for r in result.journal if r["FINANCIALACCOUNTTYPE"] == "D"]
        self.assertEqual(len(ar), 2)
        self.assertTrue(all(r["CLEARINGDATE"] == date(2026, 10, 11) for r in ar))
        self.assertEqual(ar[1]["INVOICEREFERENCE"], ar[0]["ACCOUNTINGDOCUMENT"])
        self.assertEqual(len([p for p in result.payments if p.get('account_type') != 'K']), 1)
        self.assertEqual(len(result.clearings), 1)
        self.assertEqual(result.payments[0]["gross"], D("3.99"))
        for op, gl in zip(result.journal, result.gl):
            self.assertEqual(op, {k: v for k, v in gl.items()
                                  if k not in {"SOURCELEDGER", "LEDGERGLLINEITEM"}})
            self.assertEqual(gl["SOURCELEDGER"], "0L")


if __name__ == "__main__":
    unittest.main()
