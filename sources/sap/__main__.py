"""Generate a local-only source package; this entrypoint cannot deploy or publish."""
from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

import jsonschema

from sources.sap.config import DEFAULT_CONFIG, DEFAULT_REFERENCES, read_json
from sources.sap.datasphere import json_bytes, write_package
from sources.sap.scenario import build

REPOSITORY = Path(__file__).resolve().parents[2]


def local_output(path: Path) -> Path:
    absolute = path.absolute()
    if str(absolute).startswith(("\\\\", "//")):
        raise ValueError("UNC output paths are not local scenario storage")
    for parent in (absolute, *absolute.parents):
        if parent.is_symlink() or parent.is_junction():
            raise ValueError("Output paths must not traverse symlinks or junctions")
    resolved = absolute.resolve()
    roots = [REPOSITORY / ".state" / "sap", REPOSITORY / ".local" / "sap"]
    if not any(resolved.is_relative_to(root) and resolved != root for root in roots):
        raise ValueError("Output must be a child of this repository's .state/sap or .local/sap")
    return resolved


def generate(output: Path, config_path=DEFAULT_CONFIG, references_path=DEFAULT_REFERENCES) -> dict:
    target = local_output(output)
    scenario = build(read_json(Path(config_path)), read_json(Path(references_path)))
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".sap-pending-", dir=target.parent))
    try:
        manifest = write_package(staging, scenario)
        if target.exists():
            if not target.is_dir():
                raise FileExistsError("Output exists and is not a scenario directory")
            expected = {p.relative_to(staging) for p in staging.rglob("*") if p.is_file()}
            actual = {p.relative_to(target) for p in target.rglob("*") if p.is_file()}
            linked = any(p.is_symlink() or p.is_junction() for p in target.rglob("*"))
            if linked or expected != actual or any(
                (target / name).read_bytes() != (staging / name).read_bytes() for name in expected
            ):
                raise FileExistsError("Output differs from this complete deterministic package; choose a new output directory")
            return {"status": "unchanged", "output": str(target), "summary": scenario.snapshots[-1].summary}
        staging.rename(target)
        return {"status": "created", "output": str(target), "objects": manifest["object_count"],
                "batches": manifest["batch_count"], "summary": scenario.snapshots[-1].summary}
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--references", type=Path, default=DEFAULT_REFERENCES)
    parser.add_argument("--output", type=Path, default=REPOSITORY / ".state" / "sap" / "november-2026-v1")
    args = parser.parse_args()
    try:
        result = generate(args.output, args.config, args.references)
    except (ValueError, OSError, jsonschema.ValidationError) as exc:
        parser.exit(2, f"SAP generation failed: {exc}\n")
    print(json_bytes(result).decode(), end="")


if __name__ == "__main__":
    main()
