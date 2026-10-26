"""Scoped cached authentication and native Fabric transport; no new login or credentials."""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from uuid import UUID

from fabric.rest import FabricClient, DeploymentError, az_json
from sources.sap.config import read_json

POLICY = Path(__file__).resolve().parents[2] / "fabric" / "target-policy.json"


def load_target(path: Path) -> dict:
    target, policy = read_json(path), read_json(POLICY)
    allowed = {"tenant_id", "subscription_id", "workspace_id", "source_system",
               "system_suffix", "operator_id", "landing_lakehouse_id", "mirror_id"}
    if set(target) != allowed:
        raise ValueError("SAP target must contain exactly the declared non-secret coordinates")
    for key in ("tenant_id", "subscription_id"):
        if target[key] != policy[key]:
            raise ValueError(f"SAP target is outside the approved MSFlix {key}")
    for key in allowed - {"source_system", "system_suffix"}:
        UUID(target[key])
    if target["source_system"] != "S4M" or target["system_suffix"] != "fea347cc":
        raise ValueError("Only the provisioned MSFlix SAP source is authorized")
    return target


class ScopedClient(FabricClient):
    def __init__(self, target: dict):
        super().__init__(target["tenant_id"], timeout=900)
        self.target = target
        self.tokens = {}

    def token(self, audience: str) -> str:
        cached = self.tokens.get(audience)
        if cached and cached[1] > time.time() + 120:
            return cached[0]
        result = az_json("account", "get-access-token", "--subscription", self.target["subscription_id"],
                         "--resource", audience)
        value = result["accessToken"]
        claims = json.loads(base64.urlsafe_b64decode(value.split(".")[1] + "==="))
        if claims.get("tid") != self.target["tenant_id"] or claims.get("oid") != self.target["operator_id"]:
            raise DeploymentError("Cached token does not belong to the approved SAP operator/tenant")
        if claims.get("aud", "").rstrip("/") != audience.rstrip("/"):
            raise DeploymentError("Token audience differs from the requested data/control plane")
        self.tokens[audience] = value, int(claims["exp"])
        return value

    def _http(self, method, url, body, skill):
        if urlparse(url).netloc != "api.fabric.microsoft.com":
            raise DeploymentError("Refusing the Fabric token on an unapproved host")
        request = Request(url, data=None if body is None else json.dumps(body).encode(), method=method,
                          headers={"Authorization": "Bearer " + self.token("https://api.fabric.microsoft.com"),
                                   "Content-Type": "application/json", "x-ms-fabric-skill": skill})
        try:
            with urlopen(request, timeout=90) as response:
                data = response.read()
                return response.status, dict(response.headers), json.loads(data) if data else {}
        except HTTPError as exc:
            data = exc.read()
            return exc.code, dict(exc.headers), json.loads(data) if data else {}

    def workspace(self) -> dict:
        result = self.request("GET", "/v1/workspaces/" + self.target["workspace_id"])[2]
        policy = read_json(POLICY)
        if result["displayName"] != policy["workspace_name"] or not result.get("capacityId"):
            raise DeploymentError("Target workspace is not the approved capacity-backed MSFlix")
        return result

    def item(self, name: str, item_type: str) -> dict:
        root = "/v1/workspaces/" + self.target["workspace_id"]
        matches = [r for r in self.list(root + "/items") if r["displayName"] == name and r["type"] == item_type]
        if len(matches) != 1:
            raise DeploymentError(f"Native SAP item missing or ambiguous: {name}")
        return matches[0]


class _RejectPublicationRedirects(HTTPRedirectHandler):
    """Never forward publication credentials or payloads to a redirected URL."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, msg, headers, fp)


class OneLakeFiles:
    def __init__(self, client: ScopedClient):
        self.client = client
        self.target = client.target
        client.workspace()
        lake = client.request("GET", f"/v1/workspaces/{self.target['workspace_id']}/lakehouses/"
                              + self.target["landing_lakehouse_id"])[2]
        if lake["displayName"] != "MSFlixSAPLanding":
            raise DeploymentError("SAP publication must use its dedicated landing lakehouse")
        self.base = lake["properties"]["oneLakeFilesPath"].rstrip("/")
        self.directories = set()
        parsed = urlparse(self.base)
        if parsed.scheme != "https" or not parsed.netloc.endswith(".dfs.fabric.microsoft.com"):
            raise DeploymentError("Unexpected OneLake files endpoint")

    def request(self, method: str, path: str, query="", data=None, headers=None, *, blob=False):
        # Bound publishers use a private view; cover internal put/directory calls.
        guard = getattr(self, "_publication_guard", None)
        if guard is not None:
            guard()
        if "\\" in path or path.startswith("/") or any(p in ("", ".", "..") for p in path.split("/")):
            raise ValueError("Unsafe OneLake source path")
        expected = "datasphere/" + self.target["source_system"]
        if path != "datasphere" and path != expected and not path.startswith(expected + "/"):
            raise ValueError("OneLake write/read exceeds the dedicated SAP source path")
        base = self.base.replace(".dfs.fabric.microsoft.com", ".blob.fabric.microsoft.com") if blob else self.base
        url = base + "/" + quote(path, safe="/") + ("?" + query if query else "")
        request = Request(url, method=method, data=data, headers={
            "Authorization": "Bearer " + self.client.token("https://storage.azure.com/"),
            "x-ms-version": "2021-06-08", "Content-Type": "application/octet-stream", **(headers or {}),
        })
        if guard is not None:
            guard()
        try:
            # Per-request opener leaves the unguarded/global transport unchanged.
            open_request = build_opener(_RejectPublicationRedirects()).open if guard is not None else urlopen
            with open_request(request, timeout=90) as response:
                return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
        except HTTPError as exc:
            if method in ("GET", "HEAD", "DELETE") and exc.code == 404:
                return exc.code, dict(exc.headers), b""
            raise DeploymentError(f"OneLake {method} HTTP {exc.code} for {path}; no publication claimed") from exc
        finally:
            if guard is not None:
                guard()

    def directory(self, path: str):
        if path in self.directories:
            return
        status, headers, _ = self.request("HEAD", path)
        if status == 404:
            self.request("PUT", path, "resource=directory", b"", {"If-None-Match": "*"})
        elif headers.get("x-ms-resource-type") != "directory":
            raise DeploymentError(f"Expected an existing directory: {path}")
        self.directories.add(path)

    def put(self, path: str, data: bytes) -> str:
        status, _, existing = self.request("GET", path)
        if status == 200:
            if existing != data:
                raise DeploymentError(f"Existing source file differs: {path}; replacement is prohibited")
            return "unchanged"
        for count in range(1, len(path.split("/"))):
            self.directory("/".join(path.split("/")[:count]))
        # Put Blob commits the complete file atomically; DFS rename through an external shortcut is unsupported.
        self.request("PUT", path, data=data, headers={
            "x-ms-blob-type": "BlockBlob", "If-None-Match": "*",
        }, blob=True)
        _, _, actual = self.request("GET", path)
        if actual != data:
            raise DeploymentError("Final source readback differs from the package")
        return "created"
