import copy
import unittest
from collections import defaultdict
from datetime import date
from decimal import Decimal as D

import jsonschema

from sources.sap.accounting import Journal, Line, money
from sources.sap.config import DEFAULT_CONFIG, DEFAULT_REFERENCES, read_json, validate
from sources.sap.scenario import build, validate_relations
from sources.sap.schema import SCHEMAS, contract


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.config = read_json(DEFAULT_CONFIG)
        self.refs = read_json(DEFAULT_REFERENCES)
        self.scenario = build(self.config, self.refs)
        self.final = self.scenario.snapshots[-1]

    def test_approved_totals(self):
        expected = {
            "recognized_revenue": "28.00", "content_cost": "13.60", "content_contribution": "14.40",
            "receivables": "12.00", "payables": "8.16", "net_bank_movement": "13.44",
            "net_vat_liability": "2.88", "deferred_revenue": "0.00", "net_billings": "28.00",
        }
        for field, value in expected.items():
            with self.subTest(field=field):
                self.assertEqual(self.final.summary[field], D(value))
        self.assertEqual(self.final.summary["accounting_documents"], 10)
        self.assertEqual(self.final.summary["journal_lines"], 25)
        self.assertEqual(self.final.summary["invoice_count"], 3)
        self.assertEqual(self.final.summary["credit_count"], 1)

    def test_each_document_and_projection_balances_at_every_checkpoint(self):
        for snapshot in self.scenario.snapshots:
            for name in ("I_OPERATIONALACCTGDOCITEM", "I_GLACCOUNTLINEITEMRAWDATA"):
                totals = defaultdict(lambda: D("0"))
                for row in snapshot.tables[name]:
                    key = row["COMPANYCODE"], row["FISCALYEAR"], row["ACCOUNTINGDOCUMENT"]
                    totals[key] += row["AMOUNTINTRANSACTIONCURRENCY"]
                    self.assertEqual(row["AMOUNTINCOMPANYCODECURRENCY"], row["AMOUNTINTRANSACTIONCURRENCY"])
                    self.assertEqual(row["DEBITCREDITCODE"], "S" if row["AMOUNTINTRANSACTIONCURRENCY"] > 0 else "H")
                self.assertTrue(totals)
                self.assertTrue(all(total == 0 for total in totals.values()))
            validate_relations(snapshot.tables)

    def test_deferred_revenue_is_not_recognized_on_invoice_or_cash_receipt(self):
        initial = self.scenario.snapshots[0].summary
        self.assertEqual(initial["receivables"], D("36"))
        self.assertEqual(initial["deferred_revenue"], D("30"))
        self.assertEqual(initial["recognized_revenue"], 0)
        for snapshot in self.scenario.snapshots[:-1]:
            self.assertEqual(snapshot.summary["recognized_revenue"], 0)
            self.assertEqual(snapshot.summary["content_cost"], 0)
        self.assertEqual(self.scenario.snapshots[-2].summary["deferred_revenue"], D("28"))

    def test_partial_supplier_payment_remains_open(self):
        rows = self.final.tables["I_OPERATIONALACCTGDOCITEM"]
        supplier = [r for r in rows if r["FINANCIALACCOUNTTYPE"] == "K"]
        self.assertEqual(len(supplier), 2)
        self.assertTrue(all(r["CLEARINGACCOUNTINGDOCUMENT"] is None for r in supplier))
        invoice = next(r for r in supplier if r["AMOUNTINTRANSACTIONCURRENCY"] < 0)
        payment = next(r for r in supplier if r["AMOUNTINTRANSACTIONCURRENCY"] > 0)
        self.assertEqual(invoice["AMOUNTINTRANSACTIONCURRENCY"], D("-16.32"))
        self.assertEqual(payment["AMOUNTINTRANSACTIONCURRENCY"], D("8.16"))
        self.assertEqual(payment["INVOICEREFERENCE"], invoice["ACCOUNTINGDOCUMENT"])
        self.assertEqual(invoice["NETDUEDATE"], date(2026, 12, 30))

    def test_customer_clearing_and_credit_are_linked(self):
        rows = self.final.tables["I_OPERATIONALACCTGDOCITEM"]
        open_ar = [r for r in rows if r["FINANCIALACCOUNTTYPE"] == "D" and r["CLEARINGDATE"] is None]
        self.assertEqual(len(open_ar), 1)
        self.assertEqual(open_ar[0]["CUSTOMER"], "0010000009")
        self.assertEqual(open_ar[0]["AMOUNTINTRANSACTIONCURRENCY"], D("12"))
        self.assertEqual(open_ar[0]["NETDUEDATE"], date(2026, 11, 8))
        credit = next(r for r in self.final.tables["C_BILLINGDOCITEMBASICDEX_1"]
                      if r["BILLINGDOCUMENTCATEGORY"] == "O")
        self.assertEqual((credit["NETAMOUNT"], credit["TAXAMOUNT"], credit["GROSSAMOUNT"]),
                         (D("-2"), D("-0.40"), D("-2.40")))
        link = next(r for r in self.final.tables["ZMSF_BILLING_LINK"]
                    if r["BILLINGDOCUMENT"] == credit["BILLINGDOCUMENT"])
        self.assertIsNotNone(link["ORIGINAL_BILLINGDOCUMENT"])
        cleared = [r for r in rows if r["CUSTOMER"] == "0010000005"]
        self.assertTrue(all(r["CLEARINGDATE"] is not None for r in cleared))

    def test_existing_keys_and_provenance_are_preserved_without_impersonation(self):
        links = self.final.tables["ZMSF_CUSTOMER_LINK"]
        self.assertEqual({r["CUSTOMER_KEY"] for r in links}, {"MSF-C0001", "MSF-C0005", "MSF-C0009"})
        self.assertEqual({r["SALESFORCE_CONTACT_ID"] for r in links},
                         {r["salesforce_contact_id"] for r in self.refs["customers"]})
        coverage = self.final.tables["ZMSF_RIGHTS_COVERAGE"]
        self.assertEqual({r["CONTENT_KEY"] for r in coverage}, set(self.config["content_keys"]))
        self.assertTrue(all(r["SIMULATION_ONLY"] == "X" and r["CATALOG_SAP_PARTNER_CODE"] is None for r in coverage))
        self.assertTrue(all(r["USAGE_TYPE"] == "SVOD" for r in coverage))
        self.assertIn("fictional", self.final.tables["I_SUPPLIER"][0]["SUPPLIERNAME"])
        self.assertTrue(all(r["ORDER_ID"] is None for r in self.final.tables["ZMSF_BILLING_LINK"]))
        self.assertEqual(self.refs, read_json(DEFAULT_REFERENCES))
        self.assertEqual(self.config, read_json(DEFAULT_CONFIG))

    def test_contract_cost_is_portfolio_level_and_net_of_credits(self):
        charges = {r["CHARGE_TYPE"]: r for r in self.final.tables["ZMSF_CONTRACT_CHARGE"]}
        self.assertEqual(charges["FIXED"]["CHARGE_NET"], D("8"))
        self.assertEqual(charges["VARIABLE"]["BASIS_NET"], D("28"))
        self.assertEqual(charges["VARIABLE"]["RATE"], D("0.20"))
        self.assertEqual(charges["VARIABLE"]["CHARGE_NET"], D("5.60"))
        self.assertNotIn("CONTENT_KEY", charges["VARIABLE"])

    def test_full_business_keys_and_decimals_are_kept(self):
        for snapshot in self.scenario.snapshots:
            self.assertEqual(len(snapshot.tables["I_CUSTOMER"][0]["CUSTOMER"]), 10)
            for name, rows in snapshot.tables.items():
                SCHEMAS[name].index(rows)
        self.assertFalse(contract()["native_bps_ready"])
        self.assertEqual(contract()["objects"]["ZMSF_PLAN"]["coverage"], "custom_simulation")

    def test_reordered_customers_do_not_change_generated_data(self):
        altered = copy.deepcopy(self.config)
        altered["customers"].reverse()
        actual = build(altered, self.refs)
        self.assertEqual(actual.snapshots, self.scenario.snapshots)

    def test_another_month_has_correct_exclusive_end_and_due_date(self):
        altered = copy.deepcopy(self.config)
        altered["period_start"] = "2027-02-01"
        actual = build(altered, self.refs)
        self.assertEqual(actual.snapshots[-1].summary["as_of"], date(2027, 2, 28))
        self.assertEqual(actual.snapshots[-1].tables["ZMSF_PLAN"][0]["VALID_TO_EXCLUSIVE"], date(2027, 3, 1))
        self.assertEqual(actual.snapshots[-1].summary["content_contribution"], D("14.40"))

    def test_invalid_inputs_are_not_silently_defaulted(self):
        cases = [
            ("monthly_net", 10.0), ("monthly_net", "NaN"), ("currency", "USD"),
            ("period_start", "2026-11-02"), ("period_start", "2026-10-01"),
            ("credit_net", "11.00"), ("supplier_name", "Blender Foundation"),
            ("unexpected", True), ("content_keys", ["UNKNOWN"]), ("plan_id", "../escape"),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                bad = copy.deepcopy(self.config)
                bad[key] = value
                with self.assertRaises((ValueError, jsonschema.ValidationError)):
                    build(bad, self.refs)

    def test_duplicate_reference_and_sap_keys_fail(self):
        duplicate = copy.deepcopy(self.refs)
        duplicate["customers"].append(duplicate["customers"][0])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate(self.config, duplicate)
        bad = copy.deepcopy(self.config)
        bad["customers"][1]["sap_customer"] = bad["customers"][0]["sap_customer"]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate(bad, self.refs)

    def test_broken_document_and_customer_links_fail(self):
        for table, column, value in (
            ("C_BILLINGDOCITEMBASICDEX_1", "ACCOUNTINGDOCUMENT", "0000000000"),
            ("ZMSF_CUSTOMER_LINK", "CUSTOMER", "0000000000"),
            ("ZMSF_SUBSCRIPTION", "PLAN_ID", "UNRESOLVED"),
        ):
            bad = copy.deepcopy(self.final.tables)
            bad[table][0][column] = value
            with self.subTest(table=table), self.assertRaisesRegex(ValueError, "Unresolved"):
                validate_relations(bad)

    def test_reference_shape_and_source_identity_are_explicit(self):
        bad = copy.deepcopy(self.refs)
        del bad["customers"][0]["salesforce_contact_id"]
        with self.assertRaises(jsonschema.ValidationError):
            build(self.config, bad)
        bad = copy.deepcopy(self.refs)
        bad["customers"][1]["salesforce_contact_id"] = bad["customers"][0]["salesforce_contact_id"]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build(self.config, bad)
        bad = copy.deepcopy(self.refs)
        bad["distributors"][0]["sap_partner_code"] = self.config["supplier_id"]
        with self.assertRaisesRegex(ValueError, "impersonate"):
            build(self.config, bad)

    def test_cent_credit_keeps_zero_tax_without_a_zero_journal_line(self):
        for credit in ("0.01", "0.02"):
            config = copy.deepcopy(self.config)
            config["credit_net"] = credit
            scenario = build(config, self.refs)
            final = scenario.snapshots[-1]
            memo = next(r for r in final.tables["C_BILLINGDOCITEMBASICDEX_1"] if r["BILLINGDOCUMENTCATEGORY"] == "O")
            self.assertEqual(memo["TAXAMOUNT"], D("0"))
            self.assertEqual(final.summary["recognized_revenue"], D("30") - D(credit))
            self.assertTrue(all(r["AMOUNTINTRANSACTIONCURRENCY"] != 0 for r in final.tables["I_OPERATIONALACCTGDOCITEM"]))

    def test_small_tax_free_rounded_amounts_and_partial_payment_bounds(self):
        config = copy.deepcopy(self.config)
        config.update(monthly_net="0.02", credit_net="0.01", fixed_content_cost="0.01")
        final = build(config, self.refs).snapshots[-1]
        self.assertEqual(final.summary["recognized_revenue"], D("0.05"))
        self.assertEqual(final.summary["payables"], D("0.01"))
        config["content_revenue_share"] = "0.01"
        with self.assertRaisesRegex(ValueError, "too small"):
            validate(config, self.refs)

    def test_long_customer_key_is_preserved_without_overflowing_subscription_key(self):
        config, refs = copy.deepcopy(self.config), copy.deepcopy(self.refs)
        key = "C" * 80
        config["customers"][0]["customer_key"] = key
        refs["customers"][0]["customer_key"] = key
        final = build(config, refs).snapshots[-1]
        self.assertIn(key, {r["CUSTOMER_KEY"] for r in final.tables["ZMSF_CUSTOMER_LINK"]})
        self.assertTrue(all(len(r["SUBSCRIPTION_ID"]) <= 80 for r in final.tables["ZMSF_SUBSCRIPTION"]))


class JournalTests(unittest.TestCase):
    def test_float_money_and_unbalanced_documents_fail(self):
        for value in (1.2, True, "Infinity"):
            with self.assertRaises(ValueError):
                money(value)
        self.assertEqual(money("0.005"), D("0.01"))
        journal = Journal("1710", "EUR")
        with self.assertRaisesRegex(ValueError, "Unbalanced"):
            journal.post(date(2026, 11, 1), "SA", "Bad", [Line("bank", D("1")), Line("revenue", D("-2"))])
        self.assertFalse(journal.rows)

    def test_partial_payment_cannot_be_cleared(self):
        journal = Journal("1710", "EUR")
        day = date(2026, 11, 1)
        invoice = journal.post(day, "KR", "Fee", [
            Line("payables", D("-10"), "0020000001"), Line("content_cost", D("10")),
        ])
        payment = journal.post(day, "KZ", "Partial", [
            Line("payables", D("5"), "0020000001"), Line("bank", D("-5")),
        ])
        with self.assertRaisesRegex(ValueError, "Partial"):
            journal.clear((invoice, payment), "K", "0020000001", payment, day)
        self.assertTrue(all(r["CLEARINGDATE"] is None for r in journal.rows))


if __name__ == "__main__":
    unittest.main()
