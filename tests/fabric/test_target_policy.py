import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fabric.deploy import load_target_policy
from fabric.rest import DeploymentError
from test_artifacts import fixture_policy


class TargetPolicyTests(unittest.TestCase):
    def test_missing_private_policy_fails_with_setup_instructions(self):
        with tempfile.TemporaryDirectory() as directory, patch("fabric.deploy.ROOT", Path(directory)):
            with self.assertRaisesRegex(DeploymentError, "target-policy.example.json"):
                load_target_policy()

    def test_private_expected_target_is_read_without_fallback(self):
        expected = fixture_policy()
        with tempfile.TemporaryDirectory() as directory, patch("fabric.deploy.ROOT", Path(directory)):
            (Path(directory) / "target-policy.json").write_text(json.dumps(expected), encoding="utf-8")
            self.assertEqual(load_target_policy(), expected)


if __name__ == "__main__":
    unittest.main()
