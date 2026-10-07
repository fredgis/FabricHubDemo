"""Bounded live Oracle CDC proof on the dedicated MSFlix environment."""
import argparse
import json
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from fabric.deploy import validate_config
from fabric.rest import DeploymentError, FabricClient, az_json
from fabric.sql import connect, execute

ROOT = Path(__file__).resolve().parents[1]
PROBE_ID = 973099
PHASE_SQL = {
    "insert": """
declare n number;
begin
  select count(*) into n from DEMO_DW.REF_TERRITORY
    where TERRITORY_ID=973099 or TERRITORY_CODE='DE';
  if n<>0 then raise_application_error(-20001,'CDC territory already exists; refusing overwrite'); end if;
  insert into DEMO_DW.REF_TERRITORY
    (TERRITORY_ID,TERRITORY_CODE,TERRITORY_NAME,CURRENCY_CODE)
    values(973099,'DE','Germany','EUR');
end;
/
""",
    "update": """
begin
  update DEMO_DW.REF_TERRITORY set TERRITORY_NAME='Allemagne'
    where TERRITORY_ID=973099 and TERRITORY_CODE='DE'
      and TERRITORY_NAME='Germany' and CURRENCY_CODE='EUR';
  if sql%rowcount<>1 then raise_application_error(-20002,'CDC territory ownership mismatch'); end if;
end;
/
""",
    "delete": """
delete from DEMO_DW.REF_TERRITORY
  where TERRITORY_ID=973099 and TERRITORY_CODE='DE'
    and TERRITORY_NAME in ('Germany','Allemagne') and CURRENCY_CODE='EUR';
""",
}


def oracle_phase(cfg, policy, phase):
    sql = PHASE_SQL[phase]
    script = f"""#!/usr/bin/env bash
set -euo pipefail
sudo demo-sqlplus <<'MSFLIX_CDC_SQL'
whenever oserror exit failure rollback
whenever sqlerror exit failure rollback
set define off
alter session set container=FREEPDB1;
{sql}
commit;
alter session set container=CDB$ROOT;
alter system archive log current;
exit success
MSFLIX_CDC_SQL
echo MSFLIX_CDC_{phase.upper()}_COMMITTED=true
"""
    directory = ROOT / ".state" / "oracle-cdc"
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                     suffix=".sh", dir=directory, delete=False) as handle:
        handle.write(script)
        path = Path(handle.name)
    try:
        result = az_json("vm", "run-command", "invoke", "--subscription", cfg["subscription_id"],
                         "--resource-group", policy["resource_group"], "--name", "msflix-oracle-vm",
                         "--command-id", "RunShellScript", "--scripts", "@" + str(path))
        output = "\n".join(row.get("message", "") for row in result.get("value", []))
        if not re.search(rf"(?m)^MSFLIX_CDC_{phase.upper()}_COMMITTED=true\s*$", output):
            raise DeploymentError(f"Oracle {phase} did not acknowledge a committed mutation")
    finally:
        path.unlink()


def wait_territory(connection, expected, deadline, sleep=time.sleep, clock=time.monotonic):
    last = None
    while clock() < deadline:
        last = execute(connection, """
            SELECT TOP (2) TERRITORY_CODE, TERRITORY_NAME, CURRENCY_CODE
            FROM DEMO_DW.REF_TERRITORY WHERE TERRITORY_ID=?""", (PROBE_ID,))
        if expected is None and not last:
            return last
        if expected is not None and last == [{
            "TERRITORY_CODE": "DE", "TERRITORY_NAME": expected, "CURRENCY_CODE": "EUR"
        }]:
            return last
        sleep(10)
    raise DeploymentError(f"Oracle CDC did not converge to {expected!r}; last mirror state: {last!r}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "fabric" / "config.live.local.json")
    parser.add_argument("--evidence", type=Path, default=ROOT / ".state" / "oracle-cdc-proof.json")
    args = parser.parse_args()
    cfg = validate_config(json.loads(args.config.read_text(encoding="utf-8-sig")), "check")
    policy = json.loads((ROOT / "fabric" / "target-policy.json").read_text())
    client = FabricClient(cfg["tenant_id"])
    base = f"/v1/workspaces/{cfg['workspace_id']}/mirroredDatabases"
    matches = [item for item in client.list(base, "sqldw-cli")
               if item["displayName"] == "MSFlix_OracleMirror"]
    if len(matches) != 1:
        raise DeploymentError("Expected exactly one dedicated MSFlix Oracle mirror")
    mirror = client.request("GET", base + "/" + matches[0]["id"], skill="sqldw-cli")[2]
    catalog_size = len(json.loads((ROOT / "data" / "catalog.json").read_text()))
    expected = {"REF_CONTENT": catalog_size, "REF_OFFER": 2, "REF_DISTRIBUTOR": 1,
                "REF_TERRITORY": 4, "REF_PRICE_RULE": catalog_size * 8}
    query = " UNION ALL ".join(
        f"SELECT '{name}' AS table_name, COUNT_BIG(*) AS row_count FROM DEMO_DW.[{name}]"
        for name in expected)
    evidence = {"started_at": datetime.now(timezone.utc).isoformat(),
                "workspace_id": cfg["workspace_id"], "mirror_id": mirror["id"], "cdc": []}
    with connect(cfg, mirror, lakehouse=True) as connection:
        snapshot = {row["table_name"]: row["row_count"] for row in execute(connection, query)}
        if snapshot != expected:
            raise DeploymentError(f"Oracle snapshot mismatch: expected {expected}, actual {snapshot}")
        existing = execute(connection, """SELECT TOP (2) TERRITORY_ID FROM DEMO_DW.REF_TERRITORY
            WHERE TERRITORY_ID=? OR TERRITORY_CODE='DE'""", (PROBE_ID,))
        if existing:
            raise DeploymentError("CDC territory already present; refusing to overwrite it")
        evidence["snapshot"] = snapshot
        deadline = time.monotonic() + 1200
        inserted = False
        completed = False
        try:
            for phase, name in (("insert", "Germany"), ("update", "Allemagne"), ("delete", None)):
                oracle_phase(cfg, policy, phase)
                inserted = inserted or phase == "insert"
                observed = wait_territory(connection, name, deadline)
                result = {"phase": phase, "source_committed": True, "mirror_rows": observed}
                evidence["cdc"].append(result)
                print(json.dumps(result), flush=True)
            completed = True
        finally:
            if inserted and not completed:
                oracle_phase(cfg, policy, "delete")
        restored = {row["table_name"]: row["row_count"] for row in execute(connection, query)}
        if restored != expected:
            raise DeploymentError("Oracle mirror counts were not restored after CDC validation")
    evidence.update(completed_at=datetime.now(timezone.utc).isoformat(), live_success=True)
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"live_success": True, "snapshot": evidence["snapshot"],
                      "cdc_phases": [row["phase"] for row in evidence["cdc"]]}), flush=True)


if __name__ == "__main__":
    main()
