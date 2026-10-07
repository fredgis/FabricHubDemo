import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fabric.rest import DeploymentError
from scripts.verify_oracle_mirror import oracle_phase, wait_territory


class MirrorCdcTests(unittest.TestCase):
    def test_insert_waits_for_exact_replicated_row(self):
        row = {"TERRITORY_CODE": "DE", "TERRITORY_NAME": "Germany", "CURRENCY_CODE": "EUR"}
        with patch("scripts.verify_oracle_mirror.execute", side_effect=[[], [row]]) as query:
            observed = wait_territory(object(), "Germany", 100, sleep=lambda _: None, clock=lambda: 0)
        self.assertEqual(observed, [row])
        self.assertEqual(query.call_count, 2)

    def test_delete_waits_until_the_row_is_actually_absent(self):
        row = {"TERRITORY_CODE": "DE", "TERRITORY_NAME": "Allemagne", "CURRENCY_CODE": "EUR"}
        with patch("scripts.verify_oracle_mirror.execute", side_effect=[[row], []]):
            self.assertEqual(wait_territory(object(), None, 100,
                                           sleep=lambda _: None, clock=lambda: 0), [])

    def test_wrong_update_is_not_success_and_times_out(self):
        row = {"TERRITORY_CODE": "DE", "TERRITORY_NAME": "Germany", "CURRENCY_CODE": "EUR"}
        times = iter([0, 100])
        with patch("scripts.verify_oracle_mirror.execute", return_value=[row]):
            with self.assertRaisesRegex(DeploymentError, "did not converge"):
                wait_territory(object(), "Allemagne", 50,
                               sleep=lambda _: None, clock=lambda: next(times))

    def test_oracle_requires_committed_marker_and_uses_only_msflix_vm(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("scripts.verify_oracle_mirror.ROOT", Path(directory)):
                with patch("scripts.verify_oracle_mirror.az_json",
                           return_value={"value": [{"message": "RPC succeeded but SQL did not commit"}]}) as azure:
                    with self.assertRaisesRegex(DeploymentError, "did not acknowledge"):
                        oracle_phase({"subscription_id": "fixture"}, {"resource_group": "fixture"}, "insert")
                    self.assertIn("msflix-oracle-vm", azure.call_args.args)
                    self.assertEqual(list((Path(directory) / ".state" / "oracle-cdc").glob("*.sh")), [])


if __name__ == "__main__":
    unittest.main()
