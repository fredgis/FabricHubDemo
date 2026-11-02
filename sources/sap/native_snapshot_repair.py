"""SAP-only full-snapshot repair: explicit bootstrap -> legacy append -> repair.

All business rows come from hash-verified replay, never caller-supplied subsets.
Null decimal128(20,0) sequence is the established native protocol; filenames
carry a later UTC clock and sequence suffix -01. No networking on import/build.
"""
from pathlib import Path
import json
import shutil
import tempfile
import pyarrow as pa
import pyarrow.parquet as pq
from sources.sap import native, native_delta
from sources.sap.datasphere import digest, json_bytes

OBJECTS = ('I_DUNNINGAREA', 'I_SEGMENT', 'I_GLACCOUNTTEXT')
TEXT_PROFILE = 'sap-native-text-source-repair-v1'


def _profile_objects(profile):
    # No caller-selected table inventory; the legacy default preserves V1 bytes.
    if profile is None:
        return OBJECTS
    if type(profile) is str and profile == TEXT_PROFILE:
        return ('I_DUNNINGAREATEXT', 'I_SEGMENTTEXT')
    raise ValueError('Unsupported repair profile')


def write_package(predecessor, bootstrap, extraction_timestamp, output, *,
                  expected_predecessor_sha256, expected_bootstrap_sha256, profile=None):
    objects = _profile_objects(profile)
    base = native_delta.verify_package(predecessor, bootstrap,
        expected_manifest_sha256=expected_predecessor_sha256,
        expected_predecessor_sha256=expected_bootstrap_sha256)
    stamp = native_delta._stamp(extraction_timestamp)
    if stamp <= base.watermark:
        raise ValueError('Repair timestamp must exceed predecessor watermark')
    output = native_delta._local(output)
    bootstrap = native_delta._local(bootstrap)
    if any(output.is_relative_to(p) or p.is_relative_to(output) for p in (base.root, bootstrap)):
        raise ValueError('Repair output must not overlap chain')
    contract = json.loads((base.root / 'contract.json').read_bytes())
    for name in objects:
        if contract['objects'][name]['native_metadata'][2] is not False:
            raise ValueError('Repair requires explicit non-delta contract')
        if not base.tables[name]:
            raise ValueError('Empty repair snapshot is prohibited')
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.repair-pending-', dir=output.parent))
    try:
        entries = {}
        for name in objects:
            obj = base.schemas[name]
            rows = base.tables[name]
            fingerprint = digest(json_bytes({'predecessor': base.manifest_sha256,
                                             'object': name, 'timestamp': stamp, 'rows': rows}))
            file = f'datasphere/S4M/{name}/delta/part-{stamp:%Y%m%d%H%M%S}-{fingerprint[:24]}-01.parquet'
            path = staging / file
            path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(native.as_table(obj, [('U', r) for r in rows], stamp), path, compression='snappy')
            entries[name] = {'file': file, 'rows': len(rows), 'business_sha256': digest(json_bytes(rows))}
        (staging / 'snapshot.json').write_bytes(json_bytes({n: base.tables[n] for n in objects}))
        manifest = {'format_version': 'sap-native-full-snapshot-repair-v1',
                    'source_system': 'S4M', 'schema_version': native.SCHEMA_VERSION,
                    'predecessor_manifest_sha256': base.manifest_sha256,
                    'bootstrap_manifest_sha256': expected_bootstrap_sha256,
                    'predecessor_final_as_of': base.watermark.isoformat(),
                    'final_as_of': stamp.isoformat(), 'objects': entries,
                    'ordered_files': [entries[n]['file'] for n in objects],
                    'pyarrow_version': pa.__version__, 'network_operations': 0,
                    'native_bps_ready': False,
                    'files': {p.relative_to(staging).as_posix(): digest(p.read_bytes())
                              for p in sorted(staging.rglob('*')) if p.is_file()}}
        if profile is not None:
            manifest.update(format_version='sap-native-full-snapshot-repair-v2', profile=profile)
        (staging / 'manifest.json').write_bytes(json_bytes(manifest))
        if output.exists():
            for p in output.rglob('*'): native_delta._local(p)
            actual = {p.relative_to(output).as_posix(): p.read_bytes() for p in output.rglob('*') if p.is_file()}
            wanted = {p.relative_to(staging).as_posix(): p.read_bytes() for p in staging.rglob('*') if p.is_file()}
            if actual != wanted:
                raise FileExistsError('Existing repair differs; replacement prohibited')
        else:
            staging.rename(output)
        return manifest
    finally:
        if staging.exists(): shutil.rmtree(staging)


def verify_package(package, predecessor, bootstrap, *, expected_manifest_sha256,
                   expected_predecessor_sha256, expected_bootstrap_sha256):
    package = native_delta._local(package)
    for p in package.rglob('*'): native_delta._local(p)
    raw = (package / 'manifest.json').read_bytes()
    if digest(raw) != expected_manifest_sha256:
        raise ValueError('Repair manifest hash mismatch')
    manifest = json.loads(raw)
    version = manifest.get('format_version')
    if version == 'sap-native-full-snapshot-repair-v1' and 'profile' not in manifest:
        profile = None
    elif version == 'sap-native-full-snapshot-repair-v2' and manifest.get('profile') == TEXT_PROFILE:
        profile = manifest['profile']
    else:
        raise ValueError('Unsupported repair format/profile')
    objects = _profile_objects(profile)
    if set(manifest.get('objects', {})) != set(objects):
        raise ValueError('Repair scope differs from allowlisted profile')
    if manifest.get('ordered_files') != [manifest['objects'][n]['file'] for n in objects]:
        raise ValueError('Repair order differs from allowlisted profile')
    for name, checksum in manifest['files'].items():
        native_delta._relative(name)
        if digest((package / name).read_bytes()) != checksum:
            raise ValueError('Repair file hash mismatch')
    actual = {p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file()}
    if actual != set(manifest['files']) | {'manifest.json'}:
        raise ValueError('Unlisted repair files')
    with tempfile.TemporaryDirectory(prefix='.repair-verify-', dir=package.parent) as folder:
        expected = Path(folder) / 'expected'
        regenerated = write_package(predecessor, bootstrap, manifest['final_as_of'], expected,
            expected_predecessor_sha256=expected_predecessor_sha256,
            expected_bootstrap_sha256=expected_bootstrap_sha256, profile=profile)
        if regenerated != manifest or any((expected / n).read_bytes() != (package / n).read_bytes() for n in actual):
            raise ValueError('Repair differs from full predecessor snapshot')
    return manifest


def publish(package, predecessor, bootstrap, target, *, approval,
            expected_bootstrap_sha256, apply=False, store=None, checkpoint=None, coordination=None):
    """Conditional-create only profile payloads; exact chain GETs before/after.

    Partial writes are possible: ingestion must remain paused until readback.
    Preview has no transport/authentication/checkpoint operations.
    """
    from copy import copy, deepcopy
    from sources.sap import native_delta_publish as transport
    from sources.sap.fabric_client import OneLakeFiles
    if type(apply) is not bool: raise ValueError('apply must be explicit boolean')
    transport._approval(target, approval)
    if apply:
        if (not isinstance(coordination, dict) or coordination.get('approval') != approval
                or any(coordination.get(k) is not True for k in ('schedule_paused', 'ingestion_idle', 'exclusive_source_writer'))
                or not isinstance(coordination.get('evidence_id'), str) or not coordination['evidence_id'].strip()
                or checkpoint is None or store is None):
            raise ValueError('Bound coordination, store and checkpoint required')
        transport._binding(store, target)
    target, approval = deepcopy(target), deepcopy(approval)
    manifest = verify_package(package, predecessor, bootstrap,
        expected_manifest_sha256=approval['manifest_sha256'],
        expected_predecessor_sha256=approval['predecessor_manifest_sha256'],
        expected_bootstrap_sha256=expected_bootstrap_sha256)
    package, predecessor, bootstrap = map(native_delta._local, (package, predecessor, bootstrap))
    payloads = {n: (package / n).read_bytes() for n in manifest['ordered_files']}
    predecessors = {}
    for root, expected_hash in ((bootstrap, expected_bootstrap_sha256), (predecessor, approval['predecessor_manifest_sha256'])):
        raw = (root / 'manifest.json').read_bytes()
        if digest(raw) != expected_hash: raise ValueError('Local chain manifest drift')
        for n, checksum in json.loads(raw)['files'].items():
            if not n.startswith('datasphere/'): continue
            data = (root / n).read_bytes()
            if digest(data) != checksum or (n in predecessors and predecessors[n] != data):
                raise ValueError('Local chain payload drift/collision')
            predecessors[n] = data
    if digest((package / 'manifest.json').read_bytes()) != approval['manifest_sha256'] or any(digest(d) != manifest['files'][n] for n, d in payloads.items()):
        raise ValueError('Local repair drift')
    result = dict(mode='preview', complete=False, native_bps_ready=False,
                  ordered_files=list(payloads), predecessor_files=len(predecessors), approval=approval, files=[])
    if not apply: return result
    checkpoint = native_delta._local(checkpoint)
    if any(checkpoint.is_relative_to(p) or p.is_relative_to(checkpoint) for p in (package, predecessor, bootstrap)):
        raise ValueError('Checkpoint must not overlap chain/package')
    if checkpoint.exists():
        previous = json.loads(checkpoint.read_bytes())
        if previous.get('approval') != approval or previous.get('ordered_files') != list(payloads):
            raise ValueError('Checkpoint approval/order differs')
    if isinstance(store, OneLakeFiles):
        original = store
        store = copy(original)
        store.directories = set(original.directories)
        def guard():
            transport._binding(original, target)
            transport._binding(store, target)
        store._publication_guard = guard
    result.update(mode='apply', coordination=deepcopy(coordination))
    transport._atomic_checkpoint(checkpoint, result)
    def check_chain():
        for n, data in predecessors.items():
            if transport._get(store, n, target) != data:
                raise ValueError('Remote predecessor bytes mismatch: ' + n)
    check_chain()
    for n, data in payloads.items():
        existing = transport._get(store, n, target)
        if existing is not None and existing != data:
            raise ValueError('Existing repair differs; replacement prohibited: ' + n)
    for n, data in payloads.items():
        existing = transport._get(store, n, target)
        if existing is not None and existing != data:
            raise ValueError('Existing repair differs; replacement prohibited: ' + n)
        transport._binding(store, target)
        state = 'unchanged' if existing is not None else store.put(n, data)
        transport._binding(store, target)
        if state not in {'created', 'unchanged'}: raise ValueError('Invalid immutable put state')
        result['files'].append(dict(file=n, sha256=digest(data), state=state))
        transport._atomic_checkpoint(checkpoint, result)
    for n, data in payloads.items():
        if transport._get(store, n, target) != data:
            raise ValueError('Final repair readback differs: ' + n)
    check_chain()
    result['complete'] = True
    transport._atomic_checkpoint(checkpoint, result)
    return result
