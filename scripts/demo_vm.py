"""Bounded ARM Run Command transport; never uploads credentials or user tokens."""
from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fabric.rest import DeploymentError, safe_error_message, token


class Arm:
    def __init__(self, tenant):
        self.tenant = tenant

    def request(self, method, url, body=None):
        if urlparse(url).hostname != "management.azure.com":
            raise DeploymentError("Refusing ARM token on another host")
        request = Request(url, method=method,
                          data=None if body is None else json.dumps(body).encode(),
                          headers={"Authorization": "Bearer " + token(self.tenant, "https://management.azure.com/"),
                                   "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=90) as response:
                content = response.read()
                return response.status, {k.lower(): v for k, v in response.headers.items()}, (
                    json.loads(content) if content else {})
        except HTTPError as exc:
            detail = safe_error_message(exc.read().decode(errors="replace"), body)
            raise DeploymentError(f"ARM HTTP {exc.code}: {detail}") from None

    def submit(self, vm_id, lines, state_path):
        marker = "MSFLIX_DEMO_COMMAND_OK_" + uuid.uuid4().hex
        _, headers, result = self.request(
            "POST", f"https://management.azure.com{vm_id}/runCommand?api-version=2024-07-01",
            {"commandId": "RunShellScript", "script": ["set -eu", *lines, f"printf '%s\\n' '{marker}'"]})
        evidence = {"vm_id": vm_id, "poll": headers.get("azure-asyncoperation"),
                    "location": headers.get("location"), "result": result, "success_marker": marker}
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        # ARM LRO URLs can carry signed query strings. Persist only in ignored
        # state; never echo them in deployment output.
        print(json.dumps({"vm_id": vm_id, "state_file": str(state_path), "submitted": True}), flush=True)
        return evidence

    def poll(self, path, timeout=600):
        job = json.loads(path.read_text(encoding="utf-8"))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            _, headers, result = self.request("GET", job["poll"])
            job["result"] = result
            path.write_text(json.dumps(job, indent=2), encoding="utf-8")
            state = result.get("status")
            if state in ("Succeeded", "Failed", "Canceled", "Cancelled"):
                output = result.get("properties", {}).get("output", {})
                print(json.dumps({"state": state, "output": output}), flush=True)
                if state != "Succeeded":
                    raise DeploymentError("VM Run Command did not succeed")
                if job.get("success_marker") and not any(
                        job["success_marker"] in row.get("message", "") for row in output.get("value", [])):
                    # Run Command's ARM provisioning success does NOT mean
                    # that the submitted shell script exited successfully.
                    raise DeploymentError("VM script failed before its completion marker; inspect saved output")
                return result
            time.sleep(max(5, min(30, int(headers.get("retry-after", 15)))))
        raise DeploymentError("VM command still running; resume with --poll, do not resubmit")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--vm-id")
    parser.add_argument("--script", type=Path)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--poll", action="store_true")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    client = Arm(args.tenant)
    if not args.poll:
        if not args.vm_id or not args.script:
            parser.error("--vm-id and --script required to submit")
        client.submit(args.vm_id, args.script.read_text(encoding="utf-8").splitlines(), args.state)
    client.poll(args.state, args.timeout)


if __name__ == "__main__":
    main()
