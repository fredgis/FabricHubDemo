import json
import unittest
from unittest.mock import Mock, patch

from fabric.deploy import dispatch
from fabric.rest import DeploymentError
from test_artifacts import fixture_config


class EventHubConnectionTests(unittest.TestCase):
    def qualify(self, path):
        cfg = fixture_config()
        cfg["eventhub_namespace"] = "msflix-gki72e4smyneg.servicebus.windows.net"
        client = Mock()
        client.request.return_value = (200, {}, {
            "id": cfg["eventhub_connection_id"],
            "connectionDetails": {"type": "EventHub", "path": path},
        })
        with patch("fabric.deploy.preflight", return_value={"id": "fixture-workspace"}), \
                patch("fabric.deploy.verify_eventhub_region"), \
                patch("fabric.deploy.resolve", side_effect=[{}, {}]), \
                patch("fabric.deploy.connect", side_effect=DeploymentError("qualified connection reached SQL gate")):
            dispatch(cfg, client, "rti")

    def test_actual_workspace_identity_namespace_name_path(self):
        path = json.dumps({"endpoint": "msflix-gki72e4smyneg",
                           "entityPath": "msflix-events", "consumerGroup": "$Default"})
        with self.assertRaisesRegex(DeploymentError, "reached SQL gate"):
            self.qualify(path)

    def test_fully_qualified_namespace_path(self):
        path = json.dumps({"endpoint": "msflix-gki72e4smyneg.servicebus.windows.net",
                           "entityPath": "msflix-events"})
        with self.assertRaisesRegex(DeploymentError, "reached SQL gate"):
            self.qualify(path)

    def test_similar_hub_name_is_not_the_authorized_topic(self):
        path = json.dumps({"endpoint": "msflix-gki72e4smyneg.servicebus.windows.net",
                           "entityPath": "msflix-events-unrelated"})
        with self.assertRaisesRegex(DeploymentError, "does not qualify"):
            self.qualify(path)

    def test_similar_namespace_is_not_the_authorized_namespace(self):
        path = json.dumps({"endpoint": "msflix-gki72e4smyneg-unrelated",
                           "entityPath": "msflix-events"})
        with self.assertRaisesRegex(DeploymentError, "does not qualify"):
            self.qualify(path)

    def test_malformed_or_missing_path_is_rejected(self):
        for path in ("", "{", "msflix-gki72e4smyneg", "{}"):
            with self.subTest(path=path), self.assertRaisesRegex(DeploymentError, "does not qualify"):
                self.qualify(path)


if __name__ == "__main__":
    unittest.main()
