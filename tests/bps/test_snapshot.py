import unittest
from datetime import datetime
from decimal import Decimal

from fabric.rest import DeploymentError
from sources.salesforce.bps.inspect import MAPPINGS
from sources.salesforce.bps.snapshot import customer_query, entity_query, json_native, normalize_row


class NativeSnapshotTests(unittest.TestCase):
    columns = [
        "Id", "FirstName", "LastName", "MSFlix_Key__c", "MSFlix_Territory__c",
        "IsDeleted", "SystemModstamp", "_SystemName", "_UpdatedTimeStamp",
    ]

    def test_latest_change_is_selected_before_tombstone_filter(self):
        query, scoped = customer_query("MSFlixSF", "Contact", self.columns)
        self.assertTrue(scoped)
        self.assertIn("[_SystemName]=?", query)
        self.assertLess(query.index("ROW_NUMBER()"), query.index("[IsDeleted]=0"))
        self.assertIn("TOP 100001", query)
        self.assertIn("AS [MSFlix_Key__c]", query)

    def test_case_is_restored_for_parent_raw_field_adapter(self):
        query, _ = customer_query("MSFlixSF", "contact", [c.lower() for c in self.columns])
        self.assertIn("[msflix_key__c] AS [MSFlix_Key__c]", query)
        self.assertIn("[firstname] AS [FirstName]", query)

    def test_missing_tombstone_or_watermark_is_not_silently_ignored(self):
        with self.assertRaises(DeploymentError):
            customer_query("MSFlixSF", "Contact", self.columns[:-4])

    def test_marketing_entities_keep_parent_raw_fields_and_scope(self):
        prefixes = {"campaign": "MSF-MKT-%", "consent": "MSF-CONSENT-%", "touch": "MSF-TOUCH-%"}
        for entity, prefix in prefixes.items():
            columns = list(MAPPINGS[entity]["fields"].values()) + ["IsDeleted", "SystemModstamp", "_SystemName"]
            query, scoped = entity_query(entity, "dbo", MAPPINGS[entity]["object"], columns)
            self.assertTrue(scoped)
            self.assertIn("LIKE '" + prefix + "'", query)
            for column in MAPPINGS[entity]["fields"].values():
                self.assertIn("AS [" + column + "]", query)

    def test_minor_units_remain_exact_integers_for_parent_validator(self):
        for value in (Decimal("250000"), 250000.0, 250000):
            row = normalize_row({"MSFlix_BudgetMinor__c": value})
            self.assertEqual(250000, row["MSFlix_BudgetMinor__c"])
            self.assertIs(type(row["MSFlix_BudgetMinor__c"]), int)
        with self.assertRaises(DeploymentError):
            normalize_row({"MSFlix_BudgetMinor__c": Decimal("250000.01")})

    def test_salesforce_datetime_is_serialized_as_explicit_utc(self):
        self.assertEqual("2026-10-07T12:30:00Z", json_native(datetime(2026, 10, 7, 12, 30)))


if __name__ == "__main__":
    unittest.main()
