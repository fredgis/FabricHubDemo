"""Publish an inspected native package via the private OneLake ADLS shortcut, never reset source data."""
from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath

from fabric.rest import DeploymentError
from sources.sap.config import read_json
from sources.sap.datasphere import digest, json_bytes
from sources.sap.fabric_client import OneLakeFiles, ScopedClient, load_target


def publication_files(package: Path, source: str) -> list[str]:
    manifest = read_json(package / "manifest.json")
    if manifest.get("synthetic") is not True or manifest["source_system"] != source:
        raise ValueError("Source package is not the inspected synthetic SAP source")
    if manifest.get("compatibility_scope") != "LOCAL_ASSERTED_ONLY":
        raise ValueError("Publication requires the native local input-contract package")
    prefix = f"datasphere/{source}/"
    files = manifest["files"]
    for name, checksum in files.items():
        part = PurePosixPath(name)
        if part.is_absolute() or ".." in part.parts or "\\" in name:
            raise ValueError("Unsafe package manifest path")
        path = package.joinpath(*part.parts)
        if not path.is_file() or path.is_symlink() or digest(path.read_bytes()) != checksum:
            raise ValueError(f"Package file is absent, linked or modified: {name}")
    source_files = [name for name in files if name.startswith(prefix)]
    metadata = sorted(name for name in source_files if name.endswith("/.sap.partfile.metadata"))
    initial = sorted(name for name in source_files if "/initial/part-" in name)
    markers = sorted(name for name in source_files if name.endswith("/initial/_SUCCESS"))
    # batches.json is an array in both the native and PR1 package formats.
    import json
    ordered_batches = json.loads((package / "batches.json").read_text())
    deltas = [
        entry["file"] for batch in ordered_batches[1:] for _, entry in sorted(batch["objects"].items())
    ]
    ordered = metadata + initial + markers + deltas
    if set(ordered) != set(source_files) or len(ordered) != len(set(ordered)):
        raise ValueError("Unclassified, duplicate or missing source files in the package")
    if not markers or len(markers) != len(initial):
        raise ValueError("Every initial object requires its completion marker")
    return ordered


def publish(package: Path, target: dict, evidence: Path) -> dict:
    files = publication_files(package, target["source_system"])
    store = OneLakeFiles(ScopedClient(target))
    results = []
    for name in files:
        state = store.put(name, package.joinpath(*PurePosixPath(name).parts).read_bytes())
        results.append({"file": name, "state": state})
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_bytes(json_bytes({"source_system": target["source_system"],
                                         "complete": len(results) == len(files), "files": results}))
    return {"complete": True, "files": len(files), "created": sum(r["state"] == "created" for r in results),
            "mode": "Full synthetic historical bootstrap; not a real-time checkpoint demonstration"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    target = load_target(args.target)
    try:
        if args.apply:
            result = publish(args.package, target, args.evidence)
        else:
            result = {"mode": "preview", "files": len(publication_files(args.package, target["source_system"]))}
    except (ValueError, OSError, DeploymentError) as exc:
        parser.exit(2, f"SAP publication failed: {exc}\n")
    print(json_bytes(result).decode(), end="")


if __name__ == "__main__":
    main()
