import base64
import json
import unittest

from services.publisher.access import (
    POLICY, REQUIRED_SQL, REQUIRED_RELOAD_SQL, identity_claims, validate_authorization, validate_sql_permissions,
)


def config():
    cfg = {
        "tenant_id": "test-tenant",
        "workspace_id": "one-workspace",
        "vm_resource_id": "/subscriptions/test/resourceGroups/demo/providers/Microsoft.Compute/virtualMachines/demo",
        "managed_identity_principal_id": "the-object-id",
        "managed_identity_application_id": "the-client-id",
    }
    cfg["orchestration_authorization"] = {"mode": POLICY, "workspace_role": "Contributor", **cfg}
    return cfg


def token(claims):
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return "header." + encoded + ".signature"


class AccessTests(unittest.TestCase):
    def test_inherited_role_is_not_a_bypass_of_effective_denies(self):
        permissions = {"database_user": "msflix_demo_worker", "inherited_db_owner": 1, **REQUIRED_SQL}
        self.assertEqual(validate_sql_permissions(permissions), permissions)
        for field in REQUIRED_SQL:
            wrong = {**permissions, field: 1 - REQUIRED_SQL[field]}
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                validate_sql_permissions(wrong)

    def test_reload_grants_only_status_updates(self):
        permissions = {"database_user": "msflix_demo_worker", **REQUIRED_SQL, **REQUIRED_RELOAD_SQL}
        self.assertEqual(validate_sql_permissions(permissions, source_reload=True), permissions)
        for field in REQUIRED_RELOAD_SQL:
            wrong = {**permissions, field: 1 - REQUIRED_RELOAD_SQL[field]}
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                validate_sql_permissions(wrong, source_reload=True)

    def test_missing_effective_permission_cannot_pass(self):
        with self.assertRaises(RuntimeError):
            validate_sql_permissions({"database_user": "msflix_demo_worker", "inherited_db_owner": 0})

    def test_explicit_identity_authorization_is_required(self):
        cfg = config()
        cfg.pop("orchestration_authorization")
        with self.assertRaises(RuntimeError):
            validate_authorization(cfg)

    def test_policy_cannot_authorize_another_workspace(self):
        cfg = config()
        cfg["orchestration_authorization"]["workspace_id"] = "some-other-workspace"
        with self.assertRaises(RuntimeError):
            validate_authorization(cfg)

    def test_imds_identity_is_bound_to_object_client_tenant_and_vm(self):
        cfg = config()
        claims = {"tid": cfg["tenant_id"], "oid": cfg["managed_identity_principal_id"],
                  "appid": cfg["managed_identity_application_id"], "xms_mirid": cfg["vm_resource_id"]}
        self.assertEqual(identity_claims(token(claims), cfg)["principal_id"], claims["oid"])
        for field in claims:
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                identity_claims(token({**claims, field: "another-identity"}), cfg)

    def test_unmapped_virtual_sql_user_is_rejected(self):
        permissions = {"database_user": "client@tenant", "inherited_db_owner": 1, **REQUIRED_SQL}
        with self.assertRaises(RuntimeError):
            validate_sql_permissions(permissions)


if __name__ == "__main__":
    unittest.main()
