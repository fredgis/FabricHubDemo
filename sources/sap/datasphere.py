"""Local Datasphere-format initial/delta files, adapted from the earlier ADLS emulator."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from sources.sap.scenario import Scenario
from sources.sap.schema import Field, Object, SCHEMAS, contract


def json_bytes(value: object) -> bytes:
    def encode(obj):
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        raise TypeError(f"Unsupported JSON value: {type(obj).__name__}")

    return (json.dumps(value, default=encode, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def arrow_type(field: Field) -> pa.DataType:
    if field.ddic in ("CURR", "DEC"):
        return pa.decimal128(field.length, field.scale)
    if field.ddic == "DATS":
        return pa.date32()
    return pa.string()


def field_metadata(field: Field) -> dict:
    result = {"name": field.name, "nullable": not field.key}
    if field.key:
        result["primaryKey"] = True
    if field.ddic in ("CURR", "DEC"):
        result.update(dataType="DECIMAL", precision=field.length, scale=field.scale)
        template = "decimal"
    elif field.ddic == "DATS":
        result.update(dataType="DATE")
        template = "date"
    else:
        result.update(dataType="NVARCHAR", length=field.length)
        template = "string"
    result["properties"] = [{"namespace": "com.sap.vflow", "name": "vtype-template", "value": template}]
    return result


def metadata(obj: Object, source_system: str) -> bytes:
    technical = [
        {"name": "__operation_type", "dataType": "NVARCHAR", "length": 1, "template": "string"},
        {"name": "__sequence_number", "dataType": "DECIMAL", "precision": 20, "scale": 0, "template": "uint64"},
        {"name": "__timestamp", "dataType": "TIMESTAMP", "template": "timestamp"},
    ]
    for field in technical:
        template = field.pop("template")
        field.update(nullable=True, properties=[
            {"namespace": "com.sap.vflow", "name": "vtype-template", "value": template},
            {"namespace": "com.sap.rms", "name": "semanticType", "value": "_change_mode"},
        ])
    return json_bytes({
        "version": 3, "format": "PARQUET",
        "properties": [
            {"namespace": "com.sap.rms", "name": "loadType", "value": "REPLICATE"},
            {"namespace": "com.sap.rms", "name": "replicationTaskID",
             "value": uuid.uuid5(uuid.NAMESPACE_URL, f"msflix-sap-v1:{source_system}:{obj.name}").hex.upper()},
            {"namespace": "com.sap.rms", "name": "groupDeltaFilesBy", "value": "NONE"},
        ],
        "columns": technical + [field_metadata(f) for f in obj.fields],
    })


def changes(obj: Object, before: list[dict], after: list[dict]) -> list[tuple[str, dict]]:
    old, new = obj.index(before), obj.index(after)
    removed = old.keys() - new.keys()
    if removed and obj.financial:
        raise ValueError(f"{obj.name}: financial deletes are prohibited; post a credit/reversal")
    updates = [("U", new[k]) for k in sorted(new) if k not in old or old[k] != new[k]]
    return updates + [("X", {name: old[k][name] for name in obj.keys}) for k in sorted(removed)]


def as_table(obj: Object, operations: list[tuple[str, dict]], stamp: datetime) -> pa.Table:
    if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
        raise ValueError("Extraction timestamps must be UTC")
    rows = []
    seen = set()
    for op, row in operations:
        if op in ("L", "U"):
            obj.index([row])
        elif op == "X" and not obj.financial:
            if set(row) != set(obj.keys):
                raise ValueError("A deletion must contain exactly the primary-key columns")
            for f in obj.fields:
                if f.key:
                    f.validate(row[f.name])
        else:
            raise ValueError(f"Unsupported operation {op} for {obj.name}")
        key = tuple(row[name] for name in obj.keys)
        if key in seen:
            raise ValueError("A source batch cannot contain duplicate keys")
        seen.add(key)
        rows.append({
            "__operation_type": op, "__sequence_number": None, "__timestamp": stamp,
            **{f.name: row.get(f.name) for f in obj.fields},
        })
    schema = pa.schema([
        pa.field("__operation_type", pa.string()),
        pa.field("__sequence_number", pa.decimal128(20, 0)),
        pa.field("__timestamp", pa.timestamp("us", tz="UTC")),
        *[pa.field(f.name, arrow_type(f), nullable=not f.key) for f in obj.fields],
    ])
    return pa.Table.from_pylist(rows, schema=schema)


def write_package(root: Path, scenario: Scenario) -> dict:
    """Write only to a newly created, caller-owned staging directory."""
    if not root.is_dir() or any(root.iterdir()):
        raise ValueError("Package staging directory must exist and be empty")
    batches = []
    source = scenario.config["source_system"]
    previous = None
    for snapshot in scenario.snapshots:
        batch = {"label": snapshot.label, "timestamp": snapshot.timestamp, "objects": {}, "summary": snapshot.summary}
        for name, obj in SCHEMAS.items():
            rows = snapshot.tables[name]
            index = obj.index(rows)
            operations = (
                [("L", index[key]) for key in sorted(index)]
                if previous is None else changes(obj, previous.tables[name], rows)
            )
            folder = root / "datasphere" / source / name
            if previous is None:
                for target in (folder, folder / "initial", folder / "delta"):
                    target.mkdir(parents=True, exist_ok=True)
                    (target / ".sap.partfile.metadata").write_bytes(metadata(obj, source))
            if not operations and previous is not None:
                continue
            fingerprint = digest(json_bytes({"object": name, "time": snapshot.timestamp, "rows": operations}))
            initial = previous is None
            name_part = fingerprint[:33] if initial else f"{snapshot.timestamp:%Y%m%d%H%M%S}-{fingerprint[:24]}-01"
            path = folder / ("initial" if initial else "delta") / f"part-{name_part}.parquet"
            pq.write_table(as_table(obj, operations, snapshot.timestamp), path, compression="snappy")
            if initial:
                (folder / "initial" / "_SUCCESS").write_bytes(b"")
            batch["objects"][name] = {
                "file": path.relative_to(root).as_posix(),
                "loads": sum(op == "L" for op, _ in operations),
                "upserts": sum(op == "U" for op, _ in operations),
                "deletes": sum(op == "X" for op, _ in operations),
            }
        batches.append(batch)
        previous = snapshot
    payloads = {
        "scenario.json": scenario.config, "references.json": scenario.references,
        "contract.json": contract(), "batches.json": batches,
        "journal.json": scenario.documents, "final-snapshot.json": scenario.snapshots[-1].tables,
        "summary.json": scenario.snapshots[-1].summary,
    }
    for name, value in payloads.items():
        (root / name).write_bytes(json_bytes(value))
    files = {
        path.relative_to(root).as_posix(): digest(path.read_bytes())
        for path in sorted(root.rglob("*")) if path.is_file()
    }
    manifest = {
        "format_version": 1, "scenario_id": scenario.config["scenario_id"], "source_system": source,
        "synthetic": True, "native_bps_ready": False, "network_operations": 0,
        "reference_observed_at": scenario.references["observed_at_utc"], "pyarrow_version": pa.__version__,
        "initial_as_of": scenario.snapshots[0].timestamp, "final_as_of": scenario.snapshots[-1].timestamp,
        "object_count": len(SCHEMAS), "batch_count": len(batches), "files": files,
        "replay": "Initial L records, then batches in timestamp order; U is full-row upsert and X is key deletion.",
        "publication_warning": "Local staged history only. Do not upload all deltas at once to demonstrate individual live checkpoints.",
        "commercial_warning": "All SAP transactions and rights terms are synthetic; no real distribution agreement is claimed.",
    }
    (root / "manifest.json").write_bytes(json_bytes(manifest))
    return manifest
