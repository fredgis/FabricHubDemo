"""Attributed Fabric HTTP, bounded LROs, and Azure CLI cached authentication."""
from __future__ import annotations

import json
import re
import subprocess
import time
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

BASE = "https://api.fabric.microsoft.com"
_TOKEN_CACHE = {}


class DeploymentError(RuntimeError):
    pass


def safe_error_message(message, body=None):
    """Redact any credential echoed by a service before exposing diagnostics."""
    secrets = []
    def collect(value):
        if isinstance(value, dict):
            for name, child in value.items():
                if re.search(r"password|secret|token|key$", name, re.I) and isinstance(child, str):
                    secrets.append(child)
                else:
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
    collect(body)
    text = str(message)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)(Bearer\s+|SharedAccessKey=|[?&]sig=)[^\s;\"']+", r"\1[REDACTED]", text)
    text = re.sub(r"eyJ[A-Za-z0-9._-]+", "[REDACTED]", text)
    return text[:1200]


def az_json(*args):
    # Azure CLI is a .cmd launcher on Windows; shell=True is never needed.
    import shutil
    executable = shutil.which("az")
    if not executable:
        raise DeploymentError("Azure CLI missing; install it and authenticate to the approved tenant")
    result = subprocess.run([executable, *args, "-o", "json"], capture_output=True,
                            text=True, timeout=90, check=False)
    if result.returncode:
        # Do not echo raw CLI output: it can contain token/credential material.
        raise DeploymentError(f"Azure CLI failed for {args[0]} (exit {result.returncode}); check cached login/permissions")
    return json.loads(result.stdout)


def token(tenant_id, audience=BASE):
    key = (tenant_id, audience)
    cached = _TOKEN_CACHE.get(key)
    if cached and cached[1] > time.time() + 90:
        return cached[0]
    result = az_json("account", "get-access-token", "--tenant", tenant_id,
                     "--resource", audience)
    value = result["accessToken"]
    if result.get("expires_on") is not None:
        _TOKEN_CACHE[key] = (value, int(result["expires_on"]))
    return value


class FabricClient:
    def __init__(self, tenant_id, transport=None, sleep=time.sleep, clock=time.monotonic,
                 timeout=600):
        self.tenant_id = tenant_id
        self.transport = transport or self._http
        self.sleep, self.clock, self.timeout = sleep, clock, timeout
        self.evidence = []

    def _http(self, method, url, body, skill):
        if urlparse(url).netloc != "api.fabric.microsoft.com":
            raise DeploymentError("Refusing Fabric bearer token on another host")
        headers = {"Authorization": "Bearer " + token(self.tenant_id),
                   "x-ms-fabric-skill": skill, "Content-Type": "application/json"}
        request = Request(url, data=None if body is None else json.dumps(body).encode(),
                          headers=headers, method=method)
        try:
            with urlopen(request, timeout=60) as response:
                data = response.read()
                return response.status, dict(response.headers), json.loads(data) if data else {}
        except HTTPError as exc:
            data = exc.read()
            try:
                error = json.loads(data)
            except ValueError:
                error = {"errorCode": "NonJsonError"}
            return exc.code, dict(exc.headers), error

    def request(self, method, path, body=None, skill="spark-cli"):
        if not skill:
            raise DeploymentError("skill attribution is required")
        url = path if path.startswith("https://") else BASE + path
        if urlparse(url).netloc != "api.fabric.microsoft.com":
            raise DeploymentError("Unsupported Fabric pagination/LRO host")
        deadline = self.clock() + self.timeout
        for attempt in range(4):
            status, headers, result = self.transport(method, url, body, skill)
            headers = {k.lower(): v for k, v in headers.items()}
            if status != 429:
                break
            delay = max(1, min(60, int(headers.get("retry-after", 5))))
            if self.clock() + delay >= deadline:
                raise DeploymentError("Fabric throttle deadline exceeded")
            self.sleep(delay)
        self.evidence.append({"method": method, "path": urlparse(url).path,
                              "http_status": status, "skill": skill,
                              "operation_id": headers.get("x-ms-operation-id")})
        if status >= 400:
            error = result.get("error", result)
            code = error.get("errorCode", error.get("code", "Unknown"))
            # Avoid logging user payloads, names, tokens, or backend echoed content.
            hint = {401: "authentication/audience", 403: "permission denied",
                    404: "target not found", 409: "conflict; inspect existing state",
                    429: "throttled"}.get(status, "API rejected request")
            detail = safe_error_message(error.get("message", ""), body)
            raise DeploymentError(f"Fabric HTTP {status} [{code}]: {hint}; {detail}; no success claimed")
        return status, headers, result

    def operation(self, method, path, body=None, skill="spark-cli", result_required=False):
        status, headers, result = self.request(method, path, body, skill)
        if status != 202:
            return result
        opid = headers.get("x-ms-operation-id")
        location = headers.get("location")
        if opid:
            poll = f"/v1/operations/{opid}"
        elif location and urlparse(location).netloc == "api.fabric.microsoft.com":
            poll = location
        else:
            raise DeploymentError("202 without usable operation ID; ambiguous write, do not resubmit")
        deadline = self.clock() + self.timeout
        while self.clock() < deadline:
            self.sleep(max(1, min(60, int(headers.get("retry-after", 5)))))
            _, headers, result = self.request("GET", poll, skill=skill)
            state = result.get("status")
            if state == "Succeeded":
                if result_required:
                    return self.request("GET", poll + "/result", skill=skill)[2]
                return result
            if state in ("Failed", "Cancelled", "Canceled"):
                code = result.get("error", {}).get("errorCode", "Unknown")
                raise DeploymentError(f"LRO {state} [{code}], operation {opid}; no blind retry")
            if state not in ("NotStarted", "Running", "Undefined"):
                raise DeploymentError(f"Unexpected LRO state {state!r}; operation {opid}")
        raise DeploymentError(f"LRO deadline exceeded, operation {opid}; inspect before rerun")

    def list(self, path, skill="spark-cli"):
        rows, seen, original = [], set(), path
        while path:
            if len(seen) >= 1000:
                raise DeploymentError("Bounded Fabric pagination limit exceeded")
            if path in seen:
                raise DeploymentError("Fabric pagination cycle")
            seen.add(path)
            result = self.request("GET", path, skill=skill)[2]
            rows.extend(result.get("value", []))
            path = result.get("continuationUri")
            if not path and result.get("continuationToken"):
                from urllib.parse import quote
                separator = "&" if "?" in original else "?"
                path = original + separator + "continuationToken=" + quote(result["continuationToken"], safe="")
        return rows

    def ensure_item(self, workspace_id, collection, name, skill, extra=None):
        path = f"/v1/workspaces/{workspace_id}/{collection}"
        matches = [r for r in self.list(path, skill) if r["displayName"] == name]
        if len(matches) > 1:
            raise DeploymentError(f"Ambiguous item name: {name}")
        if not matches:
            self.operation("POST", path, {"displayName": name, **(extra or {})}, skill)
            matches = [r for r in self.list(path, skill) if r["displayName"] == name]
        if len(matches) != 1:
            raise DeploymentError(f"Write outcome ambiguous for {name}; inspect operation, do not retry")
        return self.request("GET", path + "/" + matches[0]["id"], skill=skill)[2]
