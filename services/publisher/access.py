"""Explicit orchestrator authorization; never waive effective publisher rights."""
from __future__ import annotations

import base64
import json
from contextlib import closing

from fabric.rest import DeploymentError
from fabric.sql import execute

POLICY = "workspace-contributor-with-outbox-denies"
REQUIRED_SQL = {
    "explicit_db_owner_memberships": 0,
    "can_read_outbox": 1,
    "can_mark_published": 1,
    "can_change_payload": 0,
    "can_delete_events": 0,
    "can_insert_orders": 0,
    "can_read_orders": 0,
}


def validate_authorization(cfg):
    policy = cfg.get("orchestration_authorization", {})
    if policy.get("mode") != POLICY or policy.get("workspace_role") != "Contributor":
        raise DeploymentError("An explicit scoped orchestration authorization is required")
    for field in ("tenant_id", "workspace_id", "vm_resource_id",
                  "managed_identity_principal_id", "managed_identity_application_id"):
        if not cfg.get(field) or policy.get(field, "").lower() != cfg[field].lower():
            raise DeploymentError(f"Orchestration authorization does not match configured {field}")
    return policy


def identity_claims(access_token, cfg):
    """Compare the IMDS-issued token to the explicitly approved machine identity."""
    validate_authorization(cfg)
    try:
        payload = access_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, IndexError, TypeError) as exc:
        raise DeploymentError("IMDS returned an unreadable identity token") from exc
    expected = {
        "tid": cfg["tenant_id"],
        "oid": cfg["managed_identity_principal_id"],
        "appid": cfg["managed_identity_application_id"],
        "xms_mirid": cfg["vm_resource_id"],
    }
    observed = {key: claims.get(key, claims.get("azp") if key == "appid" else "") for key in expected}
    if any(str(observed[key]).rstrip("/").lower() != value.rstrip("/").lower()
           for key, value in expected.items()):
        raise DeploymentError("Runtime identity differs from the explicitly authorized VM managed identity")
    return {"tenant_id": expected["tid"], "principal_id": expected["oid"],
            "application_id": expected["appid"], "vm_resource_id": expected["xms_mirid"]}


def validate_sql_permissions(permissions):
    if any(permissions.get(key) != value for key, value in REQUIRED_SQL.items()):
        raise DeploymentError("Effective SQL permission preflight failed: " + json.dumps(permissions))
    if permissions.get("database_user") != "msflix_demo_worker":
        raise DeploymentError("Expected the explicitly mapped managed-identity SQL user")
    # IS_MEMBER(db_owner) reflects the required Fabric Contributor role. It is
    # audit data, NOT a bypass of the effective permissions above. An explicit
    # SQL db_owner membership remains forbidden.
    return permissions


def check_access(runtime):
    cfg = runtime.cfg
    identity = identity_claims(runtime.credential.get_token(
        "https://api.fabric.microsoft.com/.default").token, cfg)
    workspaces = runtime.client.list("/v1/workspaces", "e2e-medallion-architecture")
    if {w["id"] for w in workspaces} != {cfg["workspace_id"]}:
        raise DeploymentError("Managed identity must be scoped to this one approved Fabric workspace")
    contributors = runtime.client.list("/v1/workspaces?roles=Contributor", "e2e-medallion-architecture")
    if {w["id"] for w in contributors} != {cfg["workspace_id"]}:
        raise DeploymentError("Managed identity does not have exactly the approved Contributor scope")
    with closing(runtime.operational()) as connection:
        permissions = execute(connection, """
            SELECT USER_NAME() AS database_user, IS_MEMBER('db_owner') AS inherited_db_owner,
              (SELECT COUNT(*) FROM sys.database_role_members m
               JOIN sys.database_principals role ON role.principal_id=m.role_principal_id
               WHERE role.name='db_owner' AND m.member_principal_id=USER_ID()) AS explicit_db_owner_memberships,
              HAS_PERMS_BY_NAME('dbo.Outboxes','OBJECT','SELECT') AS can_read_outbox,
              HAS_PERMS_BY_NAME('dbo.Outboxes','OBJECT','UPDATE','published_at','COLUMN') AS can_mark_published,
              HAS_PERMS_BY_NAME('dbo.Outboxes','OBJECT','UPDATE','payload','COLUMN') AS can_change_payload,
              HAS_PERMS_BY_NAME('dbo.Outboxes','OBJECT','DELETE') AS can_delete_events,
              HAS_PERMS_BY_NAME('dbo.Rentals','OBJECT','INSERT') AS can_insert_orders,
              HAS_PERMS_BY_NAME('dbo.Rentals','OBJECT','SELECT') AS can_read_orders;
        """)[0]
        validate_sql_permissions(permissions)
        lock = execute(connection,
            "DECLARE @r int; EXEC @r=sys.sp_getapplock "
            "@Resource=N'MSFlix-DemoPreflight',@LockMode=N'Exclusive',"
            "@LockOwner=N'Session',@LockTimeout=0; SELECT @r AS result;")[0]["result"]
        if lock < 0:
            raise DeploymentError("SQL application-lock preflight failed")
        execute(connection,
            "EXEC sys.sp_releaseapplock @Resource=N'MSFlix-DemoPreflight',@LockOwner=N'Session';")
    return {"identity": identity, "sql_permissions": permissions, "sql_applock": "verified",
            "workspace_scope": [cfg["workspace_id"]], "workspace_role": "Contributor",
            "authorization_mode": POLICY}
