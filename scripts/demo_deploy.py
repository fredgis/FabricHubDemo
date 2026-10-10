"""Upload only allowlisted worker code and nonsecret bindings via ARM Run Command."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path

from scripts.demo_vm import Arm
from services.publisher.worker import validate_config

ROOT = Path(__file__).resolve().parents[1]


def bundle(cfg):
    paths = list((ROOT / "services/publisher").glob("*.py"))
    paths += [ROOT / "services/publisher/msflix-demo-worker.service"]
    paths += [ROOT / "fabric" / name for name in (
        "__init__.py", "build.py", "contracts.py", "rest.py", "sql.py", "native_references.py",
        "staging.py", "deploy.py", "connections.py", "rti.py")]
    paths += [ROOT / "sources/salesforce/bps" / name for name in (
        "__init__.py", "snapshot.py", "inspect.py", "jobs.py")]
    paths += [path for path in (ROOT / "sources/__init__.py", ROOT / "sources/salesforce/__init__.py")
              if path.is_file()]
    paths += list((ROOT / "fabric/gold").glob("*.sql"))
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            archive.writestr(path.relative_to(ROOT).as_posix(), path.read_bytes())
        archive.writestr("worker-config.json", json.dumps(validate_config(cfg)))
    content = memory.getvalue()
    return content, hashlib.sha256(content).hexdigest()


def deploy(cfg, state, *, paused=True):
    content, digest = bundle(cfg)
    # No shell heredocs, SAS, storage keys, inbound port or temporary web server.
    installer = (
        "import base64,io,zipfile,pathlib,os,shutil,grp;"
        f"d='{digest[:16]}';"
        "root=pathlib.Path('/opt/msflix-demo/releases')/d;root.mkdir(exist_ok=True);"
        f"data=base64.b64decode('{base64.b64encode(content).decode()}');"
        "z=zipfile.ZipFile(io.BytesIO(data));z.extractall(root);"
        "cfg=pathlib.Path('/etc/msflix-demo/config.json');"
        "shutil.copyfile(root/'worker-config.json',cfg);"
        "os.chown(cfg,0,grp.getgrnam('msflix-demo').gr_gid);os.chmod(cfg,0o640);"
        "(root/'worker-config.json').unlink();"
        "current=pathlib.Path('/opt/msflix-demo/current');tmp=current.with_suffix('.new');"
        "tmp.unlink(missing_ok=True);tmp.symlink_to(root);os.replace(tmp,current);"
        "shutil.copyfile(root/'services/publisher/msflix-demo-worker.service',"
        "'/etc/systemd/system/msflix-demo-worker.service')"
    )
    lines = ["set -eu", "systemctl stop msflix-demo-worker.service || true",
             "python3 -c " + "'" + installer.replace("'", "'\"'\"'") + "'",
             ("touch /var/lib/msflix-demo/PAUSED" if paused else
              "rm -f /var/lib/msflix-demo/PAUSED"),
             "chown msflix-demo:msflix-demo /var/lib/msflix-demo/PAUSED" if paused else "true",
             "systemctl daemon-reload", "systemctl enable msflix-demo-worker.service",
             "systemctl start msflix-demo-worker.service",
             "systemctl is-enabled msflix-demo-worker.service",
             "systemctl is-active msflix-demo-worker.service"]
    state.mkdir(parents=True, exist_ok=True)
    arm = Arm(cfg["tenant_id"])
    path = state / "deploy-job.json"
    arm.submit(cfg["vm_resource_id"], lines, path)
    result = arm.poll(path, 600)
    evidence = {"vm_resource_id": cfg["vm_resource_id"], "principal_id": cfg["managed_identity_principal_id"],
                "service": "msflix-demo-worker.service", "release_sha256": digest,
                "release_directory": f"/opt/msflix-demo/releases/{digest[:16]}",
                "state_directory": "/var/lib/msflix-demo", "paused": paused,
                "run_command_status": result["status"]}
    (state / "deployment.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--start", action="store_true", help="Unpause after dependency and permission verification")
    a = p.parse_args()
    deploy(json.loads(a.config.read_text(encoding="utf-8")), a.state, paused=not a.start)


if __name__ == "__main__":
    main()
