import unittest
from unittest.mock import patch

from fabric.rest import DeploymentError
from scripts import materialize_gold_graph as graph


class GraphTargetTests(unittest.TestCase):
    def test_preserves_the_independently_approved_graph_name(self):
        name = "MSFlixBusiness_graph_00000000000040008000000000000701"
        with patch.object(graph, "load_target_policy", return_value={"ontology_graph_name": name}):
            self.assertEqual(name, graph.expected_graph_name())

    def test_invalid_or_missing_graph_name_stops_before_external_calls(self):
        for name in (None, "", 42, "graph", "MSFlixBusiness_graph_not-an-item-id"):
            with self.subTest(name=name), \
                    patch.object(graph, "load_target_policy", return_value={"ontology_graph_name": name}), \
                    patch.object(graph, "FabricClient") as client, \
                    patch.object(graph, "connect") as connect:
                with self.assertRaises(DeploymentError):
                    graph.main()
                client.assert_not_called()
                connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
