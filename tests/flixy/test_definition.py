import base64
import json
import unittest

from fabric.rest import DeploymentError
from scripts.prepare_flixy import (
    INSTRUCTIONS_PATH, SOURCE_PATH, WAREHOUSE, WORKSPACE, canonical, definition,
)


class FlixyDraftTests(unittest.TestCase):
    def test_native_draft_is_read_only_and_unpublished(self):
        parts = definition("Only answer from authorized sources.")["parts"]
        files = {part["path"]: json.loads(base64.b64decode(part["payload"])) for part in parts}
        self.assertFalse(any("/published/" in path or "publish_info" in path for path in files))
        self.assertEqual(files[INSTRUCTIONS_PATH]["aiInstructions"], "Only answer from authorized sources.")
        source = files[SOURCE_PATH]
        self.assertEqual(source["artifactId"], WAREHOUSE)
        self.assertEqual(source["workspaceId"], WORKSPACE)
        self.assertEqual(source["type"], "data_warehouse")
        self.assertEqual(source["elements"], [])

    def test_definition_is_stable(self):
        self.assertEqual(definition("Read only."), definition("Read only."))

    def test_empty_instructions_are_rejected(self):
        with self.assertRaises(DeploymentError):
            definition(" ")

    def test_native_defaults_do_not_weaken_identity_or_selection_checks(self):
        expected = {"artifactId": WAREHOUSE, "elements": [{"is_selected": True}]}
        native = {"artifactId": WAREHOUSE, "metadata": {},
                  "elements": [{"is_selected": True, "description": None}]}
        self.assertEqual(canonical(native), expected)
        native["elements"][0]["is_selected"] = False
        self.assertNotEqual(canonical(native), expected)


if __name__ == "__main__":
    unittest.main()
