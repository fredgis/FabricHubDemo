"""Explicit, immutable publication of reviewed SAP native append packages.

publish(package, baseline, target, *, approval, apply=False, store=None,
        checkpoint=None, coordination=None)

Preview performs local package verification only (the existing verifier uses
local temporary regeneration); no transport, authentication or checkpoint I/O.
Approval binds manifest SHA256, predecessor SHA256 and the complete load_target
coordinates. Apply accepts only the exact HTTPS OneLake DFS endpoint formed from
those workspace/lakehouse IDs, and checks both store and client target coordinates.
A private transport view rechecks the caller's binding before/after every request
(including internal directory/create/readback operations and token acquisition).
Supply the existing OneLakeFiles instance only for apply. Its real conditional-
create transport remains responsible for atomic remote creation. Construction and
credential acquisition remain caller-owned; this is not a sandbox for untrusted
transport implementations or protection against arbitrary in-process code changes.

Caller owns SAP schedule/ingestion coordination, credential acquisition and BPS
UI registration. Publication does not establish native Silver/Gold readiness.

approval = {"manifest_sha256": reviewed_hash,
            "predecessor_manifest_sha256": trusted_bootstrap_hash,
            "target": complete_target_coordinates}
coordination = {"approval": approval, "evidence_id": caller_evidence_reference,
                "schedule_paused": True, "ingestion_idle": True,
                "exclusive_source_writer": True}
These are caller attestations, not proof of live schedule state. Maintain the
exclusive writer/idle ingestion gate throughout apply and final verification;
paused ingestion and an exclusive writer are required. GET checks cannot provide
a multi-object transaction or detect unknown extra source files. All known
predecessors are re-read at the start and end only. Concurrent predecessor drift
during the payload phase is detected at final verification; publication cannot
guarantee zero partial writes. Package bytes are snapshotted in memory after
hash verification.
Use a caller-owned checkpoint outside both inputs, with one local writer. Errors
propagate without success claims; the last atomic checkpoint remains incomplete
once an attempt begins. Resume validates its binding but trusts fresh remote
bytes, never checkpoint state. No source deletion or remote audit JSON is used.
"""
from __future__ import annotations

from copy import copy, deepcopy
import json
import os
from pathlib import Path
import re
import tempfile

from sources.sap import native_delta
from sources.sap.fabric_client import OneLakeFiles
from sources.sap.datasphere import digest, json_bytes


_TARGET_KEYS = {"tenant_id", "subscription_id", "workspace_id", "source_system",
                "system_suffix", "operator_id", "landing_lakehouse_id", "mirror_id"}


def _policy():
    return json.loads((Path(__file__).resolve().parents[2] / "fabric/target-policy.json").read_bytes())


def _approval(target, approval):
    if not isinstance(target, dict) or set(target) != _TARGET_KEYS:
        raise ValueError("Target must contain exact SAP coordinates")
    for key in _TARGET_KEYS - {"source_system", "system_suffix"}:
        if not isinstance(target[key], str) or not re.fullmatch(
                r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", target[key]):
            raise ValueError("Invalid target coordinate grammar")
    policy = _policy()
    if (any(target[k] != policy[k] for k in ("tenant_id", "subscription_id"))
            or target["source_system"] != "S4M"
            or not isinstance(target["system_suffix"], str)
            or not re.fullmatch(r"[0-9a-f]{8}", target["system_suffix"])):
        raise ValueError("Target outside approved SAP source scope")
    if not isinstance(approval, dict) or set(approval) != {
            "manifest_sha256", "predecessor_manifest_sha256", "target"}:
        raise ValueError("Explicit manifest/predecessor/target approval required")
    if approval["target"] != target:
        raise ValueError("Approved target binding differs")
    for key in ("manifest_sha256", "predecessor_manifest_sha256"):
        if not isinstance(approval[key], str) or not re.fullmatch(r"[0-9a-f]{64}", approval[key]):
            raise ValueError("Invalid approved SHA256")


def _atomic_checkpoint(path, evidence):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(json_bytes(evidence))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _binding(store, target):
    if store.target != target or getattr(getattr(store, "client", None), "target", None) != target:
        raise ValueError("Concurrent client/store target binding drift")
    endpoint = ("https://onelake.dfs.fabric.microsoft.com/"
                f"{target['workspace_id']}/{target['landing_lakehouse_id']}/Files")
    # Exact comparison rejects alternate hosts, credentials, ports, URL escapes,
    # query/fragment suffixes and noncanonical paths; metadata is not authority.
    if getattr(store, "base", None) != endpoint:
        raise ValueError("OneLake endpoint differs from approved target")


def _get(store, name, target):
    # OneLakeFiles exposes request("GET", path), not a get() method.
    _binding(store, target)
    status, _, data = store.request("GET", name)
    _binding(store, target)
    if status == 404:
        return None
    if status != 200 or not isinstance(data, bytes):
        raise ValueError("Source GET did not return verified bytes")
    return data


def publish(package: Path, baseline: Path, target: dict, *, approval: dict,
            apply: bool = False, store=None, checkpoint: Path | None = None,
            coordination: dict | None = None) -> dict:
    if type(apply) is not bool:
        raise ValueError("apply must be an explicit boolean")
    _approval(target, approval)
    if apply:
        if (not isinstance(coordination, dict) or coordination.get("approval") != approval
                or any(coordination.get(k) is not True for k in (
                    "schedule_paused", "ingestion_idle", "exclusive_source_writer"))
                or not isinstance(coordination.get("evidence_id"), str)
                or not coordination["evidence_id"].strip()):
            raise ValueError("Bound SAP schedule/ingestion coordination evidence required")
        if checkpoint is None or store is None or getattr(store, "target", None) != target:
            raise ValueError("Bound store and local checkpoint required")
        _binding(store, target)
    target, approval = deepcopy(target), deepcopy(approval)
    verified = native_delta.verify_package(
        package, baseline, expected_manifest_sha256=approval["manifest_sha256"],
        expected_predecessor_sha256=approval["predecessor_manifest_sha256"])
    base = native_delta.load_baseline(
        baseline, expected_manifest_sha256=approval["predecessor_manifest_sha256"])
    result = {
        "mode": "preview", "complete": False, "native_bps_ready": False,
        "ordered_files": verified.manifest["ordered_files"],
        "predecessor_files": sum(n.startswith("datasphere/") for n in base.manifest["files"]),
        "requires_bps_ui_registration": verified.manifest["requires_bps_ui_registration"],
    }
    payloads = {n: native_delta._local(verified.root / n).read_bytes()
                for n in result["ordered_files"]}
    predecessors = {n: native_delta._local(base.root / n).read_bytes() for n in base.manifest["files"]
                    if n.startswith("datasphere/")}
    for snapshot, checked in ((payloads, verified), (predecessors, base)):
        if (digest((checked.root / "manifest.json").read_bytes()) != checked.manifest_sha256
                or any(digest(data) != checked.manifest["files"][n] for n, data in snapshot.items())):
            raise ValueError("Local manifest/payload hash drift after verification")
    if not apply:
        return result
    if isinstance(store, OneLakeFiles):
        # Private per-attempt view: do not install mutable hooks on caller's store.
        original = store
        store = copy(original)
        store.directories = set(original.directories)
        def guard():
            _binding(original, target)
            _binding(store, target)
        store._publication_guard = guard
    _binding(store, target)
    checkpoint = native_delta._local(checkpoint)
    if any(checkpoint.is_relative_to(root) or root.is_relative_to(checkpoint)
           for root in (verified.root, base.root)):
        raise ValueError("Checkpoint must not overlap immutable package/baseline")
    result.update(mode="apply", approval=approval, coordination=deepcopy(coordination), files=[])
    if checkpoint.exists():
        previous = json.loads(checkpoint.read_bytes())
        if (previous.get("approval") != approval
                or previous.get("ordered_files") != result["ordered_files"]
                or not isinstance(previous.get("files"), list)):
            raise ValueError("Checkpoint approval/order binding differs")
        entries = previous["files"]
        if len(entries) > len(payloads):
            raise ValueError("Checkpoint file inventory differs")
        for name, entry in zip(payloads, entries):
            if (not isinstance(entry, dict) or entry.get("file") != name
                    or entry.get("sha256") != verified.manifest["files"][name]
                    or entry.get("state") not in {"created", "unchanged"}):
                raise ValueError("Checkpoint file/hash/state differs")
    _atomic_checkpoint(checkpoint, result)
    def check_predecessors():
        _binding(store, target)
        for name, data in predecessors.items():
            if _get(store, name, target) != data:
                raise ValueError("Remote predecessor hash/bytes mismatch: " + name)
        _binding(store, target)

    check_predecessors()
    for name, data in payloads.items():
        existing = _get(store, name, target)
        if existing is not None and existing != data:
            raise ValueError("Existing payload differs; replacement prohibited: " + name)
    for name, data in payloads.items():
        existing = _get(store, name, target)
        if existing is not None and existing != data:
            raise ValueError("Existing payload differs; replacement prohibited: " + name)
        _binding(store, target)
        state = "unchanged" if existing is not None else store.put(name, data)
        _binding(store, target)
        if state not in {"created", "unchanged"}:
            raise ValueError("Unexpected immutable transport state")
        result["files"].append({"file": name, "sha256": digest(data), "state": state})
        _atomic_checkpoint(checkpoint, result)
    for name, data in payloads.items():
        if _get(store, name, target) != data:
            raise ValueError("Final remote payload readback differs: " + name)
    check_predecessors()
    result["complete"] = True
    _atomic_checkpoint(checkpoint, result)
    return result
