import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fabric.rest import DeploymentError
from sources.salesforce.bps.delivery import validate_snapshots


class MarketingAcceptanceTests(unittest.TestCase):
    def test_native_counts_and_foreign_keys_are_checked_without_fabricating_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "contact.silver.native.json").write_text(
                json.dumps([{"MSFlix_Key__c": "MSF-C0001"}]), encoding="utf-8",
            )
            records = {
                "campaign": [{"campaign_key": "MSF-MKT-1"}],
                "consent": [{"consent_key": "MSF-CONSENT-1", "customer_key": "MSF-C0001"}],
                "touch": [{"touch_key": "MSF-TOUCH-1", "customer_key": "MSF-C0001", "campaign_key": "MSF-MKT-1"}],
            }
            provenance = {}
            for entity, rows in records.items():
                path = directory / (entity + ".silver.native.json")
                path.write_text(json.dumps(rows), encoding="utf-8")
                provenance[entity] = {
                    "snapshot_file": str(path), "layer": "bronze", "processed_silver": False,
                    "delta_path": "observed", "sql_endpoint_id": "observed",
                    "schema": "MSFlixSF", "table": entity,
                }
            with patch("sources.salesforce.bps.delivery.EXPECTED", {name: 1 for name in records}), \
                 patch("sources.salesforce.bps.delivery.conform_salesforce", side_effect=lambda name, rows: rows):
                actual = validate_snapshots(directory, provenance)
                self.assertEqual("bronze", actual["touch"]["actual_source_layer"])
                self.assertFalse(actual["touch"]["processed_silver"])
                records["touch"][0]["customer_key"] = "UNKNOWN"
                (directory / "touch.silver.native.json").write_text(json.dumps(records["touch"]), encoding="utf-8")
                with self.assertRaises(DeploymentError):
                    validate_snapshots(directory, provenance)


if __name__ == "__main__":
    unittest.main()
