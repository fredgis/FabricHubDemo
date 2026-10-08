"""Operate the existing VM worker through authenticated, bounded ARM commands."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.demo_vm import Arm


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--action", choices=("status", "preflight", "pause", "unpause", "restart", "resume"), required=True)
    a = p.parse_args()
    cfg = json.loads(a.config.read_text(encoding="utf-8"))
    base = ["set -eu", "cd /opt/msflix-demo/current"]
    if a.action == "pause":
        base += ["touch /var/lib/msflix-demo/PAUSED", "chown msflix-demo:msflix-demo /var/lib/msflix-demo/PAUSED"]
    elif a.action == "unpause":
        base += ["runuser -u msflix-demo -- /opt/msflix-demo/venv/bin/python "
                 "-m services.publisher.check --config /etc/msflix-demo/config.json "
                 "--output /var/lib/msflix-demo/preflight.json",
                 "rm -f /var/lib/msflix-demo/PAUSED"]
    elif a.action == "restart":
        base += ["systemctl restart msflix-demo-worker.service"]
    elif a.action == "resume":
        # Preserve job IDs/intents. This never turns an uncertain POST into a
        # blind retry; history reconciliation is still required by the worker.
        code = ("from services.publisher.worker import Store;import time;"
                "s=Store('/var/lib/msflix-demo');v=s.load();"
                "v['phase']=v.pop('blocked_phase',v['phase']);"
                "v.pop('error',None);v.pop('failures',None);"
                "v['stage_started_at']=time.time();s.save(v);s.db.close()")
        base += ["systemctl stop msflix-demo-worker.service",
                 "runuser -u msflix-demo -- /opt/msflix-demo/venv/bin/python -c " +
                 "'" + code.replace("'", "'\"'\"'") + "'",
                 "systemctl start msflix-demo-worker.service"]
    elif a.action == "preflight":
        base += ["runuser -u msflix-demo -- /opt/msflix-demo/venv/bin/python "
                 "-m services.publisher.check --config /etc/msflix-demo/config.json "
                 "--output /var/lib/msflix-demo/preflight.json"]
    base += [
        "systemctl show msflix-demo-worker.service --property=ActiveState --property=SubState "
        "--property=UnitFileState --property=MainPID --property=NRestarts",
        "test ! -f /var/lib/msflix-demo/status.json || cat /var/lib/msflix-demo/status.json",
    ]
    a.state.mkdir(parents=True, exist_ok=True)
    path = a.state / (a.action + "-job.json")
    arm = Arm(cfg["tenant_id"])
    arm.submit(cfg["vm_resource_id"], base, path)
    arm.poll(path, 600)


if __name__ == "__main__":
    main()
