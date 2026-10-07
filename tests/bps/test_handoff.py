import unittest

from fabric.rest import DeploymentError
from sources.salesforce.bps.inspect import MAPPINGS, mapping_evidence, quoted_identifier


class HandoffTests(unittest.TestCase):
    def test_missing_native_table_is_not_claimed_available(self):
        result = mapping_evidence(MAPPINGS["campaign"], [])
        self.assertFalse(result["available"])
        self.assertNotIn("delta_path", result)

    def test_customer_mapping_preserves_actual_field_names(self):
        mapping = MAPPINGS["customer"]
        table = {
            "schema": "MSFlixSF", "table": "Contact", "row_count": 720,
            "delta_path": "https://onelake.dfs.fabric.microsoft.com/ws/lh/Tables/MSFlixSF/Contact",
            "columns": {name: "varchar" for name in mapping["fields"].values()},
            "customer_quality": {"customer_rows": 700, "distinct_customer_keys": 700},
        }
        result = mapping_evidence(mapping, [table])
        self.assertTrue(result["available"])
        self.assertEqual("MSFlix_Key__c", result["actual_fields"]["customer_key"])
        self.assertEqual(700, result["customer_quality"]["distinct_customer_keys"])
        self.assertEqual(720, result["row_count"])

    def test_missing_custom_column_blocks_mapping(self):
        result = mapping_evidence(MAPPINGS["customer"], [{
            "schema": "MSFlixSF", "table": "Contact", "row_count": 700,
            "delta_path": "observed", "columns": {"Id": "varchar"},
        }])
        self.assertFalse(result["available"])
        self.assertIn("MSFlix_Key__c", result["missing_columns"])

    def test_duplicate_table_name_in_other_schema_is_ambiguous(self):
        table = {"table": "Contact"}
        self.assertFalse(mapping_evidence(MAPPINGS["customer"], [table, table])["available"])

    def test_sql_identifiers_are_quoted_not_interpolated(self):
        self.assertEqual("[a]]b]", quoted_identifier("a]b"))
        with self.assertRaises(DeploymentError):
            quoted_identifier("bad\nname")


if __name__ == "__main__":
    unittest.main()
