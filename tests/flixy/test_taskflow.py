import unittest

from scripts.workspace_taskflow import in_scope, mapping, task_graph


class FlixyTaskFlowTests(unittest.TestCase):
    def test_original_graph_is_unchanged_without_native_agent(self):
        tasks, edges = task_graph([])
        self.assertEqual(len(tasks), 8)
        self.assertEqual(len(edges), 9)
        self.assertNotIn("flixy", {task[0] for task in tasks})

    def test_native_agent_adds_one_task_and_three_connectors(self):
        item = {"id": "44444444-4444-4444-8444-444444444444",
                "displayName": "Flixy", "type": "DataAgent"}
        mapped = mapping([item])
        self.assertEqual(mapped[0]["logical_task"], "flixy")
        tasks, edges = task_graph(mapped)
        self.assertEqual(len(tasks), 9)
        self.assertEqual(len(edges), 12)
        self.assertEqual({(a, b) for a, b, _ in edges if "flixy" in (a, b)},
                         {("gold", "flixy"), ("ontology", "flixy"), ("flixy", "cockpit")})

    def test_name_alone_does_not_expand_item_scope(self):
        self.assertFalse(in_scope({"displayName": "Flixy", "type": "Lakehouse"}))


if __name__ == "__main__":
    unittest.main()
