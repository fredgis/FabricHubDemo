"""Read the deployed worker's durable checkpoint and broker receipts, without mutation."""
from __future__ import annotations

import argparse
import json
import shlex
from datetime import datetime, timezone
from pathlib import Path

from fabric.rest import DeploymentError
from scripts.demo_vm import Arm


def capture(cfg, directory):
    # Compact output stays below Run Command's output limit. Full event
    # membership remains in the durable VM SQLite database, not console logs.
    code = """
import json,sqlite3,pathlib,subprocess
p=pathlib.Path('/var/lib/msflix-demo')
s=json.loads((p/'status.json').read_text())
s.pop('authorization',None)
for key in ('cycle','last_cycle'):
    if s.get(key) and s[key].get('graph_proof'):
        s[key]['graph_proof']['sample']=s[key]['graph_proof'].get('sample',[])[:1]
db=sqlite3.connect('file:/var/lib/msflix-demo/state.sqlite3?mode=ro',uri=True)
receipts=[json.loads(r[0]) for r in db.execute('SELECT body FROM receipts ORDER BY id DESC LIMIT 3')]
service=subprocess.check_output(['systemctl','show','msflix-demo-worker.service','--property=MainPID','--property=NRestarts','--property=ActiveState','--property=SubState','--property=UnitFileState','--property=ExecMainStartTimestamp'],text=True)
result={'status':s,'paused_file':(p/'PAUSED').exists(),'propagated_count':db.execute('SELECT COUNT(*) FROM propagated').fetchone()[0],'broker_receipts':receipts,'service':dict(line.split('=',1) for line in service.splitlines() if '=' in line)}
db.close()
print(json.dumps(result,separators=(',',':')))
""".strip()
    directory.mkdir(parents=True, exist_ok=True)
    arm = Arm(cfg["tenant_id"])
    command = ["runuser -u msflix-demo -- /opt/msflix-demo/venv/bin/python -c " + shlex.quote(code)]
    job = directory / "vm-evidence-job.json"
    arm.submit(cfg["vm_resource_id"], command, job)
    result = arm.poll(job, 300)
    messages = result.get("properties", {}).get("output", {}).get("value", [])
    found = []
    for message in messages:
        for line in message.get("message", "").splitlines():
            if line.startswith('{"status":'):
                found.append(json.loads(line))
    if len(found) != 1:
        raise DeploymentError("Worker evidence missing/truncated; no status inferred")
    evidence = {"captured_at": datetime.now(timezone.utc).isoformat(), **found[0]}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (directory / f"vm-evidence-{stamp}.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    (directory / "vm-evidence-latest.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence))
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    capture(json.loads(args.config.read_text(encoding="utf-8")), args.state)


if __name__ == "__main__":
    main()
