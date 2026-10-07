"""Run a native BPS Salesforce stage; completed and active runs are reused."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fabric.deploy import preflight, validate_config
from fabric.rest import DeploymentError, FabricClient
from sources.salesforce.bps.jobs import STAGES, run_stage, validate_suffix


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "fabric" / "config.live.local.json")
    parser.add_argument("--system-suffix", required=True)
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--poll-seconds", type=int, default=20)
    parser.add_argument(
        "--after-completed-job",
        help="Acknowledge the exact latest completed job only when another native run is necessary",
    )
    args = parser.parse_args()
    validate_suffix(args.system_suffix)
    cfg = validate_config(json.loads(args.config.read_text(encoding="utf-8-sig")), "check")
    client = FabricClient(cfg["tenant_id"])
    ws = preflight(cfg, client)["id"]
    run_stage(
        client, ws, args.system_suffix, args.stage, ROOT / ".state" / "bps",
        timeout=args.timeout_seconds, poll_seconds=args.poll_seconds,
        after_completed_job=args.after_completed_job,
        notify=lambda evidence: print(json.dumps(evidence), flush=True),
    )


if __name__ == "__main__":
    try:
        main()
    except DeploymentError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
