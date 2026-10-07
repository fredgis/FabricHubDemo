import base64
import copy
import json
import unittest

from fabric.build import ontology_definition, part, preserve_ontology_identity


class OntologyIdentityTests(unittest.TestCase):
    def definitions(self):
        desired = ontology_definition("fixture.datawarehouse.fabric.microsoft.com",
                                      "00000000-0000-0000-0000-000000000006", "MSFlixBusiness")
        old = copy.deepcopy(desired)
        platform = next(p for p in old["parts"] if p["path"] == ".platform")
        data = json.loads(base64.b64decode(platform["payload"]))
        data["config"]["logicalId"] = "00000000-0000-0000-0000-000000000000"
        platform.update(part(".platform", json.dumps(data)))
        return desired, old

    def test_unassigned_git_id_preserves_service_metadata_and_semantic_identity(self):
        desired, old = self.definitions()
        merged = preserve_ontology_identity(desired, old)
        self.assertEqual(next(p for p in merged["parts"] if p["path"] == ".platform"),
                         next(p for p in old["parts"] if p["path"] == ".platform"))

    def test_zero_git_id_does_not_disable_semantic_lineage_checks(self):
        desired, old = self.definitions()
        entity = next(p for p in old["parts"] if p["path"] == "entities/customer.tmdl")
        text = base64.b64decode(entity["payload"]).decode().replace("lineageTag:", "changedTag:", 1)
        entity.update(part(entity["path"], text))
        with self.assertRaisesRegex(ValueError, "semantic lineage"):
            preserve_ontology_identity(desired, old)

    def test_other_existing_parts_are_never_dropped(self):
        desired, old = self.definitions()
        old["parts"].append(part("unowned.tmdl", ""))
        with self.assertRaisesRegex(ValueError, "remove existing"):
            preserve_ontology_identity(desired, old)


if __name__ == "__main__":
    unittest.main()
