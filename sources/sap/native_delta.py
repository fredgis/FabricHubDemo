"""Offline native append packages. No authentication, transport or publication.

load_baseline replays a hash-checked native bootstrap, not its JSON snapshot.
An optional externally captured manifest hash pins the trust anchor; without it
integrity is checked but provenance is not authenticated.

Public API:
    base = load_baseline(bootstrap, expected_manifest_sha256=trusted_hash)
    manifest = write_package(bootstrap, schemas, additions, utc_stamp, batch_id, output,
                             expected_manifest_sha256=base.manifest_sha256)
    verified = verify_package(output, bootstrap)

Only S4M/native.SCHEMA_VERSION is accepted. All old schemas must be supplied
unchanged; the only allowed new object is a caller-declared keyed financial
ZMSF_ORDER_LINK. Its DD03ND rows and bootstrap metadata are generated locally;
registration in BPS UI is a separate parent-owned gate. ordered_files contains
only transport payloads, never local audit JSON. SHA256(manifest.json bytes)
binds their order, hashes, predecessor and explicit UTC extraction timestamp.

Limits: a bootstrap is the only supported predecessor (no append-chain loader).
This module checks source protocol, not accounting/foreign-key/business coherence.
Omission is never deletion; a renamed key is indistinguishable from an intentional
new key, so business identity mapping remains the caller's responsibility. Do not
pass these packages to the historical-bootstrap publisher. Deterministic bytes
are tied to the recorded PyArrow version. Use caller-owned local directories;
link checks are not a defense against a concurrent hostile filesystem writer.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from copy import deepcopy
import shutil
import tempfile
import pyarrow as pa
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path, PurePosixPath
import re

import pyarrow.parquet as pq

from sources.sap import native
from sources.sap.datasphere import digest, json_bytes
from sources.sap.schema import Object


@dataclass
class Baseline:
    root: Path
    manifest: dict
    manifest_sha256: str
    schemas: dict[str, Object]
    tables: dict[str, list[dict]]
    watermark: datetime


def _local(path: Path) -> Path:
    path = Path(path).absolute()
    if str(path).startswith(("\\\\", "//")) or any(
        p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in (path, *path.parents)
    ):
        raise ValueError("Package paths must be local and must not traverse links")
    return path.resolve()


def _relative(name: str) -> None:
    if not isinstance(name, str) or not name or any(c in name for c in "\\\\:%") or any(
        p in {"", ".", ".."} or p.endswith((".", " ")) for p in name.split("/")
    ) or PurePosixPath(name).is_absolute():
        raise ValueError("Unsafe package path")


def _stamp(value) -> datetime:
    stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
        raise ValueError("Extraction timestamp must be explicit UTC")
    return stamp


def load_baseline(root: Path, *, expected_manifest_sha256: str | None = None) -> Baseline:
    """Verify every declared file and replay the ordered native history."""
    root = _local(root)
    for path in root.rglob("*"):
        _local(path)
    raw = (root / "manifest.json").read_bytes()
    fingerprint = digest(raw)
    if expected_manifest_sha256 is not None and fingerprint != expected_manifest_sha256:
        raise ValueError("Baseline manifest hash differs from expected manifest hash")
    manifest = json.loads(raw)
    if (manifest.get("format_version") != 1 or manifest.get("schema_version") != native.SCHEMA_VERSION
            or manifest.get("source_system") != "S4M" or manifest.get("synthetic") is not True
            or manifest.get("compatibility_scope") != "LOCAL_ASSERTED_ONLY"):
        raise ValueError("Unsupported baseline native source contract")
    for name, checksum in manifest["files"].items():
        _relative(name)
        path = root / name
        if not path.is_file() or digest(path.read_bytes()) != checksum:
            raise ValueError(f"Baseline file hash mismatch: {name}")
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != set(manifest["files"]) | {"manifest.json"}:
        raise ValueError("Unlisted or missing baseline files")
    contract = json.loads((root / "contract.json").read_bytes())
    if contract["version"] != native.SCHEMA_VERSION:
        raise ValueError("Baseline schema version mismatch")
    schemas = {name: Object(name, tuple(native.NativeField(**f) for f in entry["fields"]),
                            financial=not entry["financial_deletes_allowed"])
               for name, entry in contract["objects"].items()}
    expected_source = set()
    for name, obj in schemas.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", name) or not obj.keys or list(obj.keys) != contract["objects"][name]["keys"]:
            raise ValueError("Invalid object or schema keys")
        folder = f"datasphere/S4M/{name}"
        for part in ("", "/initial", "/delta"):
            file = f"{folder}{part}/.sap.partfile.metadata"
            if file not in manifest["files"] or (root / file).read_bytes() != native.metadata(obj, "S4M"):
                raise ValueError("Baseline metadata differs from schema/source identity")
            expected_source.add(file)
        marker = f"{folder}/initial/_SUCCESS"
        if marker not in manifest["files"] or (root / marker).read_bytes() != b"":
            raise ValueError("Missing or invalid initial completion marker")
        expected_source.add(marker)
    indexes = {name: {} for name in schemas}
    batches = json.loads((root / "batches.json").read_bytes())
    if not batches or len(batches) != manifest["batch_count"] or len(schemas) != manifest["object_count"]:
        raise ValueError("Baseline batch/object count mismatch")
    previous = None
    for number, batch in enumerate(batches):
        stamp = _stamp(batch["timestamp"])
        if previous is not None and stamp <= previous:
            raise ValueError("Baseline timestamps must be monotonic")
        previous = stamp
        if number == 0 and set(batch["objects"]) != set(schemas):
            raise ValueError("Initial batch must contain every object")
        for name, entry in batch["objects"].items():
            if name not in schemas:
                raise ValueError("Unknown batch object")
            obj = schemas[name]
            file = entry["file"]
            prefix = f"datasphere/S4M/{name}/{'initial' if number == 0 else 'delta'}/part-"
            if file not in manifest["files"] or not file.startswith(prefix) or not file.endswith(".parquet") or file in expected_source:
                raise ValueError("Invalid or repeated batch file path")
            expected_source.add(file)
            table = pq.read_table(root / file)
            if table.schema != native.as_table(obj, [], stamp).schema:
                raise ValueError("Parquet schema differs from native contract")
            counts = {"L": 0, "U": 0, "X": 0}
            seen = set()
            for record in table.to_pylist():
                op = record["__operation_type"]
                if op not in ({"L"} if number == 0 else {"U", "X"}) or record["__sequence_number"] is not None or record["__timestamp"] != stamp:
                    raise ValueError("Invalid native operation, sequence or extraction timestamp")
                counts[op] += 1
                row = {f.name: record[f.name] for f in obj.fields}
                key = tuple(row[k] for k in obj.keys)
                if key in seen:
                    raise ValueError("Duplicate native batch key")
                seen.add(key)
                if op == "X":
                    if obj.financial or key not in indexes[name] or any(row[f.name] is not None for f in obj.fields if not f.key):
                        raise ValueError("Invalid historical deletion")
                    for f in obj.fields:
                        if f.key:
                            f.validate(row[f.name])
                    del indexes[name][key]
                else:
                    obj.index([row])
                    indexes[name][key] = row
            if [entry[k] for k in ("loads", "upserts", "deletes")] != [counts[k] for k in ("L", "U", "X")]:
                raise ValueError("Batch operation count mismatch")
    if expected_source != {n for n in manifest["files"] if n.startswith("datasphere/")}:
        raise ValueError("Unclassified source file")
    if _stamp(manifest["initial_as_of"]) != _stamp(batches[0]["timestamp"]) or _stamp(manifest["final_as_of"]) != previous:
        raise ValueError("Baseline watermark mismatch")
    tables = {name: [index[k] for k in sorted(index)] for name, index in indexes.items()}
    snapshot = json.loads((root / "final-snapshot.json").read_bytes())
    if set(snapshot) != set(tables):
        raise ValueError("Final snapshot object inventory mismatch")
    for name, obj in schemas.items():
        for row in snapshot[name]:
            for f in obj.fields:
                if row.get(f.name) is not None:
                    if f.ddic in {"DEC", "CURR", "QUAN"}:
                        row[f.name] = Decimal(row[f.name])
                    elif f.ddic == "DATS":
                        row[f.name] = date.fromisoformat(row[f.name])
        if obj.index(snapshot[name]) != obj.index(tables[name]):
            raise ValueError("Replayed history differs from final snapshot")
    return Baseline(root, manifest, fingerprint, schemas, tables,
                    datetime.fromisoformat(manifest["final_as_of"]))


def verify_package(package: Path, baseline_root: Path, *, expected_manifest_sha256: str | None = None,
                   expected_predecessor_sha256: str | None = None) -> Baseline:
    """Offline verification by deterministic regeneration against a verified bootstrap.

    Uses a temporary sibling directory, removed on completion. The returned
    manifest_sha256 binds predecessor, timestamp, ordered paths and file hashes.
    Append packages are not accepted as bootstrap predecessors in this version.
    """
    package = _local(package)
    for path in package.rglob("*"):
        _local(path)
    raw = (package / "manifest.json").read_bytes()
    if expected_manifest_sha256 is not None and digest(raw) != expected_manifest_sha256:
        raise ValueError("Append manifest hash mismatch")
    manifest = json.loads(raw)
    if manifest.get("format_version") != "sap-native-append-v1":
        raise ValueError("Unsupported append format")
    base = load_baseline(baseline_root, expected_manifest_sha256=expected_predecessor_sha256)
    if manifest["predecessor_manifest_sha256"] != base.manifest_sha256:
        raise ValueError("Append predecessor hash mismatch")
    for name, checksum in manifest["files"].items():
        _relative(name)
        path = package / name
        if not path.is_file() or digest(path.read_bytes()) != checksum:
            raise ValueError("Append file hash mismatch")
    actual = {p.relative_to(package).as_posix() for p in package.rglob("*") if p.is_file()}
    if actual != set(manifest["files"]) | {"manifest.json"}:
        raise ValueError("Unlisted append files")
    contract = json.loads((package / "contract.json").read_bytes())
    schemas = {name: Object(name, tuple(native.NativeField(**f) for f in entry["fields"]),
                            financial=not entry["financial_deletes_allowed"])
               for name, entry in contract["objects"].items()}
    batches = json.loads((package / "batches.json").read_bytes())
    if len(batches) != 1:
        raise ValueError("Append requires exactly one batch")
    additions = {}
    for name, entry in batches[0]["objects"].items():
        file = entry["file"]
        if file not in manifest["files"] or name not in schemas:
            raise ValueError("Unknown append batch file/object")
        additions[name] = [{f.name: row[f.name] for f in schemas[name].fields}
                           for row in pq.read_table(package / file).to_pylist()]
    new_names = set(schemas) - set(base.schemas)
    if new_names:
        additions["DD03ND"] = [r for r in additions.get("DD03ND", []) if r["STRUCOBJN"] not in new_names]
    with tempfile.TemporaryDirectory(prefix=".append-verify-", dir=package.parent) as folder:
        expected = Path(folder) / "expected"
        regenerated = _write_package(base.root, schemas, additions, _stamp(manifest["final_as_of"]),
                                    manifest["batch_id"], expected,
                                    expected_manifest_sha256=base.manifest_sha256)
        if regenerated != manifest or any((expected / name).read_bytes() != (package / name).read_bytes() for name in actual):
            raise ValueError("Append differs from deterministic append-only replay")
    tables = deepcopy(base.tables)
    for name, rows in additions.items():
        index = schemas[name].index(tables.get(name, []))
        index.update(schemas[name].index(rows))
        tables[name] = [index[k] for k in sorted(index)]
    if new_names:
        index = schemas["DD03ND"].index(tables["DD03ND"])
        index.update(schemas["DD03ND"].index(native.dd03nd_rows({n: schemas[n] for n in sorted(new_names)})))
        tables["DD03ND"] = [index[k] for k in sorted(index)]
    return Baseline(package, manifest, digest(raw), schemas, tables, _stamp(manifest["final_as_of"]))


def write_package(baseline_root: Path, schemas: dict[str, Object], additions: dict[str, list[dict]],
                  extraction_timestamp: datetime, batch_id: str, output: Path, *,
                  expected_manifest_sha256: str | None = None) -> dict:
    """Reject new non-delta subsets; historical verifier retains exact replay."""
    base = load_baseline(baseline_root, expected_manifest_sha256=expected_manifest_sha256)
    contract = json.loads((base.root / 'contract.json').read_bytes())
    for name, rows in additions.items():
        metadata = contract['objects'].get(name, {}).get('native_metadata')
        if metadata and metadata[2] is False:
            old = schemas[name].index(base.tables[name])
            if schemas[name].index(rows).keys() - old.keys():
                raise ValueError(f'{name}: non-delta additions require full-snapshot publication, not append subsets')
    return _write_package(baseline_root, schemas, additions, extraction_timestamp, batch_id, output,
                          expected_manifest_sha256=base.manifest_sha256)


def _write_package(baseline_root: Path, schemas: dict[str, Object], additions: dict[str, list[dict]],
                  extraction_timestamp: datetime, batch_id: str, output: Path, *,
                  expected_manifest_sha256: str | None = None) -> dict:
    """Write an immutable local append package; additions are NOT a replacement snapshot.

    Omitted rows/objects are preserved. Identical existing keys are no-ops.
    The caller must supply the complete unchanged schema inventory. This writer
    never generates source IDs, business dates or version values.
    """
    base = load_baseline(baseline_root, expected_manifest_sha256=expected_manifest_sha256)
    stamp = _stamp(extraction_timestamp)
    if stamp <= base.watermark:
        raise ValueError("Extraction timestamp must exceed predecessor watermark")
    if not isinstance(batch_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", batch_id):
        raise ValueError("Invalid batch identifier")
    new_names = set(schemas) - set(base.schemas)
    if new_names - {"ZMSF_ORDER_LINK"} or any(schemas.get(n) != obj for n, obj in base.schemas.items()):
        raise ValueError("Existing schema inventory, keys and deletion policy must not change")
    for name in new_names:
        obj = schemas[name]
        if obj.name != name or not obj.financial or not obj.keys or len({f.name for f in obj.fields}) != len(obj.fields):
            raise ValueError("New bridge must be a keyed financial object")
        if any(not re.fullmatch(r"[A-Z][A-Z0-9_]*", f.name) for f in obj.fields):
            raise ValueError("Invalid new bridge column")
        native.as_table(obj, [], stamp)
    if set(additions) - set(schemas):
        raise ValueError("Unknown addition object")
    additions = deepcopy(additions)
    if new_names:
        additions.setdefault("DD03ND", []).extend(native.dd03nd_rows({n: schemas[n] for n in sorted(new_names)}))
        for name in new_names:
            additions.setdefault(name, [])
    for name, rows in additions.items():
        proposed = schemas[name].index(rows)
        for row in rows:
            for f in schemas[name].fields:
                if f.ddic in {"DEC", "CURR", "QUAN"} and row[f.name] is not None:
                    row[f.name] = row[f.name].quantize(Decimal(1).scaleb(-f.scale))
        old = schemas[name].index(base.tables.get(name, []))
        if any(old[k] != proposed[k] for k in old.keys() & proposed.keys()):
            raise ValueError(f"{name}: mutation of existing key prohibited")
    dd = schemas["DD03ND"]
    dictionary = dd.index(base.tables["DD03ND"])
    dictionary.update(dd.index(additions.get("DD03ND", [])))
    if dictionary != dd.index(native.dd03nd_rows(schemas)):
        raise ValueError("DD03ND must describe exactly the declared source fields")
    tables = deepcopy(base.tables)
    batches = {"label": batch_id, "timestamp": stamp, "objects": {}}
    output = _local(output)
    if output.is_relative_to(base.root) or base.root.is_relative_to(output):
        raise ValueError("Output must not overlap baseline")
    if output.exists():
        if not output.is_dir():
            raise FileExistsError("Output is not a directory")
        for path in output.rglob("*"):
            _local(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".append-pending-", dir=output.parent))
    try:
        ordered = []
        contract = json.loads((base.root / "contract.json").read_bytes())
        for name in sorted(new_names):
            obj = schemas[name]
            contract["objects"][name] = {
                "keys": list(obj.keys), "fields": [asdict(f) for f in obj.fields],
                "financial_deletes_allowed": False, "coverage": "custom_simulation",
                "native_metadata": ["FACT", list(obj.keys), True, ""],
            }
            for part in ("", "/initial", "/delta"):
                file = f"datasphere/S4M/{name}{part}/.sap.partfile.metadata"
                path = staging / file
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(native.metadata(obj, "S4M"))
                ordered.append(file)
        for name in sorted(additions):
            obj = schemas[name]
            initial = name in new_names
            old = obj.index(tables.get(name, []))
            proposed = obj.index(additions[name])
            rows = [proposed[k] for k in sorted(proposed) if k not in old]
            old.update(proposed)
            tables[name] = [old[k] for k in sorted(old)]
            if not rows and not initial:
                continue
            operations = [("L" if initial else "U", row) for row in rows]
            fingerprint = digest(json_bytes({"predecessor": base.manifest_sha256, "object": name,
                                             "time": stamp, "rows": operations}))
            suffix = fingerprint[:33] if initial else f"{stamp:%Y%m%d%H%M%S}-{fingerprint[:24]}-01"
            file = f"datasphere/S4M/{name}/{'initial' if initial else 'delta'}/part-{suffix}.parquet"
            path = staging / file
            path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(native.as_table(obj, operations, stamp), path, compression="snappy")
            ordered.append(file)
            if initial:
                marker = f"datasphere/S4M/{name}/initial/_SUCCESS"
                (staging / marker).write_bytes(b"")
                ordered.append(marker)
            batches["objects"][name] = {"file": file, "loads": len(rows) if initial else 0,
                                         "upserts": 0 if initial else len(rows), "deletes": 0}
        for name, value in {"batches.json": [batches], "final-snapshot.json": tables,
                            "contract.json": contract}.items():
            (staging / name).write_bytes(json_bytes(value))
        manifest = {
            "format_version": "sap-native-append-v1", "schema_version": native.SCHEMA_VERSION,
            "source_system": "S4M", "synthetic": True, "compatibility_scope": "LOCAL_ASSERTED_ONLY",
            "network_operations": 0, "pipeline_qualified": False, "native_bps_ready": False,
            "predecessor_manifest_sha256": base.manifest_sha256,
            "predecessor_final_as_of": base.watermark.isoformat(), "final_as_of": stamp.isoformat(),
            "batch_id": batch_id, "object_count": len(schemas), "batch_count": 1,
            "requires_bps_ui_registration": sorted(new_names),
            "ordered_files": ordered, "pyarrow_version": pa.__version__,
            "files": {p.relative_to(staging).as_posix(): digest(p.read_bytes())
                      for p in sorted(staging.rglob("*")) if p.is_file()},
        }
        (staging / "manifest.json").write_bytes(json_bytes(manifest))
        if output.exists():
            expected = {p.relative_to(staging): p.read_bytes() for p in staging.rglob("*") if p.is_file()}
            actual = {p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()}
            if actual != expected:
                raise FileExistsError("Existing append output differs; replacement prohibited")
        else:
            staging.rename(output)
        return manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging)

