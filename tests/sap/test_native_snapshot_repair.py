"""Offline repair tests: real Parquet, immutable chain, no cloud."""
import importlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone
from dataclasses import asdict
import pyarrow.parquet as pq
from sources.sap import native, native_delta
from sources.sap.datasphere import digest, json_bytes

STAMP = datetime(2026, 11, 1, tzinfo=timezone.utc)
APPEND = datetime(2026, 12, 1, tzinfo=timezone.utc)
REPAIR = datetime(2026, 12, 2, tzinfo=timezone.utc)
NAMES = ('I_DUNNINGAREA', 'I_SEGMENT', 'I_GLACCOUNTTEXT')

def api():
    assert importlib.util.find_spec('sources.sap.native_snapshot_repair'), 'repair module missing'
    return importlib.import_module('sources.sap.native_snapshot_repair')

class RepairTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'])
        self.addCleanup(temp.cleanup)
        self.scratch = Path(temp.name)
        self.base = self.scratch / 'base'
        self.base.mkdir()
        contract = native.load_contract()
        schemas = {n: contract.schemas[n] for n in (*NAMES, 'I_DUNNINGAREATEXT', 'I_SEGMENTTEXT', 'DD03ND')}
        rows = {n: [native._complete(schemas[n], {k: ('0'*f.length if f.ddic == 'NUMC' else 'X') for k in schemas[n].keys for f in schemas[n].fields if f.name == k})] for n in NAMES}
        rows['I_DUNNINGAREATEXT'] = [native._complete(schemas['I_DUNNINGAREATEXT'],
            dict(COMPANYCODE=str(1710+i*10), DUNNINGAREA='', LANGUAGE=lang))
            for i in range(3) for lang in ('E', 'F')]
        rows['I_SEGMENTTEXT'] = [native._complete(schemas['I_SEGMENTTEXT'],
            dict(SEGMENT=seg, LANGUAGE=lang)) for seg in ('MSFSVOD', 'ZORDER') for lang in ('E', 'F')]
        rows['DD03ND'] = native.dd03nd_rows(schemas)
        entries = {}
        for n, obj in schemas.items():
            folder = self.base / 'datasphere/S4M' / n
            for sub in ('', 'initial', 'delta'):
                path = folder / sub
                path.mkdir(parents=True, exist_ok=True)
                (path / '.sap.partfile.metadata').write_bytes(native.metadata(obj, 'S4M'))
            file = folder / 'initial' / ('part-' + 'a'*33 + '.parquet')
            pq.write_table(native.as_table(obj, [('L', r) for r in rows[n]], STAMP), file, compression='snappy')
            (folder / 'initial/_SUCCESS').write_bytes(b'')
            entries[n] = dict(file=file.relative_to(self.base).as_posix(), loads=len(rows[n]), upserts=0, deletes=0)
        values = {'contract.json': {'version': native.SCHEMA_VERSION, 'objects': {
            n: {'keys': list(o.keys), 'fields': [asdict(f) for f in o.fields],
                'financial_deletes_allowed': not o.financial, 'native_metadata': contract.objects.get(n, ['FACT', list(o.keys), True, ''])}
            for n, o in schemas.items()}}, 'batches.json': [{'timestamp': STAMP, 'objects': entries}],
            'final-snapshot.json': rows}
        for n, v in values.items(): (self.base / n).write_bytes(json_bytes(v))
        m = dict(format_version=1, schema_version=native.SCHEMA_VERSION, source_system='S4M', synthetic=True,
                 compatibility_scope='LOCAL_ASSERTED_ONLY', object_count=len(schemas), batch_count=1,
                 initial_as_of=STAMP, final_as_of=STAMP,
                 files={p.relative_to(self.base).as_posix(): digest(p.read_bytes()) for p in self.base.rglob('*') if p.is_file()})
        (self.base / 'manifest.json').write_bytes(json_bytes(m))
        self.base_hash = digest((self.base / 'manifest.json').read_bytes())
        self.predecessor = self.scratch / 'append'
        # No new rows: legacy append establishes the operational extraction clock.
        native_delta.write_package(self.base, schemas, {}, APPEND, 'operational', self.predecessor)
        self.pred_hash = digest((self.predecessor / 'manifest.json').read_bytes())
        self.output = self.scratch / 'repair'

    def write(self, stamp=REPAIR):
        return api().write_package(self.predecessor, self.base, stamp, self.output,
            expected_predecessor_sha256=self.pred_hash, expected_bootstrap_sha256=self.base_hash,
            profile=getattr(self, 'profile', None))

    def test_text_profile_full_snapshot_is_pinned_and_deterministic(self):
        m = api().write_package(self.predecessor, self.base, REPAIR, self.output,
            expected_predecessor_sha256=self.pred_hash, expected_bootstrap_sha256=self.base_hash,
            profile='sap-native-text-source-repair-v1')
        self.assertEqual(m['profile'], 'sap-native-text-source-repair-v1')
        self.assertEqual(m['format_version'], 'sap-native-full-snapshot-repair-v2')
        self.assertEqual({n: e['rows'] for n, e in m['objects'].items()},
                         {'I_DUNNINGAREATEXT': 6, 'I_SEGMENTTEXT': 4})
        snapshot = json.loads((self.predecessor / 'final-snapshot.json').read_bytes())
        for n, e in m['objects'].items():
            records = pq.read_table(self.output / e['file']).to_pylist()
            self.assertEqual([{f.name: r[f.name] for f in native.load_contract().schemas[n].fields}
                              for r in records], snapshot[n])
            self.assertTrue(all(r['__timestamp'] == REPAIR and r['__operation_type'] == 'U'
                                and r['__sequence_number'] is None for r in records))
        self.assertEqual(api().verify_package(self.output, self.predecessor, self.base,
            expected_manifest_sha256=digest((self.output / 'manifest.json').read_bytes()),
            expected_predecessor_sha256=self.pred_hash, expected_bootstrap_sha256=self.base_hash), m)

    def test_invalid_profile_rejected_before_chain_io(self):
        for profile in ('unknown', '', ['I_SEGMENTTEXT'], {'objects': ['I_SEGMENTTEXT']}, True):
            with self.subTest(profile=profile), self.assertRaisesRegex(ValueError, 'profile'):
                api().write_package(self.scratch / 'missing', self.base, REPAIR, self.output,
                    expected_predecessor_sha256=self.pred_hash,
                    expected_bootstrap_sha256=self.base_hash, profile=profile)
            self.assertFalse(self.output.exists())
        with self.assertRaises(TypeError):
            api().write_package(self.predecessor, self.base, REPAIR, self.output,
                expected_predecessor_sha256=self.pred_hash, expected_bootstrap_sha256=self.base_hash,
                objects=['I_SEGMENTTEXT'])

    def test_tampered_profile_scope_and_approval_hash_rejected(self):
        original = api().write_package(self.predecessor, self.base, REPAIR, self.output,
            expected_predecessor_sha256=self.pred_hash, expected_bootstrap_sha256=self.base_hash,
            profile='sap-native-text-source-repair-v1')
        original_hash = digest((self.output / 'manifest.json').read_bytes())
        changes = [dict(profile='unknown'), dict(profile=None),
                   dict(format_version='sap-native-full-snapshot-repair-v1'),
                   dict(objects={'I_SEGMENTTEXT': original['objects']['I_SEGMENTTEXT']}),
                   dict(ordered_files=list(reversed(original['ordered_files'])))]
        for change in changes:
            modified = dict(original, **change)
            (self.output / 'manifest.json').write_bytes(json_bytes(modified))
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'profile|scope|order'):
                api().verify_package(self.output, self.predecessor, self.base,
                    expected_manifest_sha256=digest(json_bytes(modified)),
                    expected_predecessor_sha256=self.pred_hash, expected_bootstrap_sha256=self.base_hash)
            with self.assertRaisesRegex(ValueError, 'manifest hash'):
                api().verify_package(self.output, self.predecessor, self.base,
                    expected_manifest_sha256=original_hash,
                    expected_predecessor_sha256=self.pred_hash, expected_bootstrap_sha256=self.base_hash)

    def test_text_metadata_gate_rejects_delta_contract_before_output_parent(self):
        from unittest.mock import patch
        verified = native_delta.verify_package(self.predecessor, self.base,
            expected_manifest_sha256=self.pred_hash, expected_predecessor_sha256=self.base_hash)
        contract = json.loads((self.predecessor / 'contract.json').read_bytes())
        contract['objects']['I_SEGMENTTEXT']['native_metadata'][2] = True
        (self.predecessor / 'contract.json').write_bytes(json_bytes(contract))
        output = self.scratch / 'must-not-create-parent' / 'repair'
        with patch.object(native_delta, 'verify_package', return_value=verified):
            with self.assertRaisesRegex(ValueError, 'non-delta'):
                api().write_package(self.predecessor, self.base, REPAIR, output,
                    expected_predecessor_sha256=self.pred_hash, expected_bootstrap_sha256=self.base_hash,
                    profile='sap-native-text-source-repair-v1')
        self.assertFalse(output.parent.exists())

    def test_future_append_rejects_non_delta_subset_before_output(self):
        base = native_delta.load_baseline(self.base)
        name = 'I_SEGMENT'
        row = dict(base.tables[name][0], SEGMENT='NEW')
        output = self.scratch / 'unsafe'
        with self.assertRaisesRegex(ValueError, 'non-delta.*full.snapshot'):
            native_delta.write_package(self.base, base.schemas, {name: [row]}, APPEND, 'unsafe', output)
        self.assertFalse(output.exists())

    def test_text_publisher_uses_only_two_allowlisted_payloads(self):
        self.profile = 'sap-native-text-source-repair-v1'
        self.test_publisher_rejects_collision_before_any_put_and_requires_readback()

    def test_publisher_rejects_collision_before_any_put_and_requires_readback(self):
        m = self.write()
        from sources.sap import native_delta_publish as transport
        target = {'tenant_id': '00000000-0000-4000-8000-000000000101',
            'subscription_id': '00000000-0000-4000-8000-000000000102',
            'workspace_id': '00000000-0000-4000-8000-000000000103',
            'landing_lakehouse_id': '00000000-0000-4000-8000-000000000104',
            'mirror_id': '00000000-0000-4000-8000-000000000105',
            'operator_id': '00000000-0000-4000-8000-000000000106',
            'source_system': 'S4M', 'system_suffix': 'a1b2c3d4'}
        from unittest.mock import patch
        policy = patch.object(transport, '_policy', return_value={
            'tenant_id': target['tenant_id'], 'subscription_id': target['subscription_id']})
        policy.start()
        self.addCleanup(policy.stop)
        approval = dict(target=target, manifest_sha256=digest((self.output / 'manifest.json').read_bytes()),
                        predecessor_manifest_sha256=self.pred_hash)
        class Store:
            def __init__(s):
                s.target = target.copy()
                s.client = type('Client', (), {'target': target.copy()})()
                s.base = f"https://onelake.dfs.fabric.microsoft.com/{target['workspace_id']}/{target['landing_lakehouse_id']}/Files"
                s.data = {p.relative_to(root).as_posix(): p.read_bytes()
                          for root in (self.base, self.predecessor) for p in root.rglob('datasphere/**/*') if p.is_file()}
                s.puts = []
                s.corrupt = False
            def request(s, method, name):
                return (200, {}, s.data[name]) if name in s.data else (404, {}, b'')
            def put(s, name, data):
                s.puts.append(name)
                s.data[name] = b'corrupt' if s.corrupt else data
                return 'created'
        def publish(store, **kw):
            return api().publish(self.output, self.predecessor, self.base, target, approval=approval,
                expected_bootstrap_sha256=self.base_hash, store=store, **kw)
        store = Store()
        preview = publish(store)
        self.assertFalse(preview['complete'])
        self.assertEqual(len(preview['ordered_files']), 2 if getattr(self, 'profile', None) else 3)
        self.assertFalse(store.puts)
        wrong_approval = dict(approval, manifest_sha256='0' * 64)
        with self.assertRaisesRegex(ValueError, 'manifest hash'):
            api().publish(self.output, self.predecessor, self.base, target,
                approval=wrong_approval, expected_bootstrap_sha256=self.base_hash)
        coord = dict(approval=approval, evidence_id='offline-test', schedule_paused=True,
                     ingestion_idle=True, exclusive_source_writer=True)
        with self.assertRaises(ValueError):
            publish(store, apply=True, checkpoint=self.scratch / 'checkpoint.json')
        store.data[m['ordered_files'][-1]] = b'collision'
        with self.assertRaisesRegex(ValueError, 'replacement'):
            publish(store, apply=True, coordination=coord, checkpoint=self.scratch / 'checkpoint.json')
        self.assertFalse(store.puts)
        del store.data[m['ordered_files'][-1]]
        store.corrupt = True
        with self.assertRaisesRegex(ValueError, 'readback'):
            publish(store, apply=True, coordination=coord, checkpoint=self.scratch / 'checkpoint.json')
        self.assertFalse(json.loads((self.scratch / 'checkpoint.json').read_bytes())['complete'])
        for n in m['ordered_files']: store.data.pop(n, None)
        store.corrupt = False
        result = publish(store, apply=True, coordination=coord, checkpoint=self.scratch / 'checkpoint.json')
        self.assertTrue(result['complete'])
        before = len(store.puts)
        self.assertTrue(publish(store, apply=True, coordination=coord, checkpoint=self.scratch / 'checkpoint.json')['complete'])
        self.assertEqual(len(store.puts), before)

    def test_full_snapshot_reemits_identical_keys_with_new_timestamp(self):
        m = self.write()
        self.assertEqual(set(m['objects']), set(NAMES))
        for n, entry in m['objects'].items():
            rows = pq.read_table(self.output / entry['file']).to_pylist()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['__timestamp'], REPAIR)
            self.assertEqual(rows[0]['__operation_type'], 'U')
            self.assertIsNone(rows[0]['__sequence_number'])
            self.assertEqual({f.name: rows[0][f.name] for f in native.load_contract().schemas[n].fields},
                             json.loads((self.predecessor / 'final-snapshot.json').read_bytes())[n][0])
        self.assertEqual(self.write(), m)
        api().verify_package(self.output, self.predecessor, self.base,
            expected_manifest_sha256=digest((self.output / 'manifest.json').read_bytes()),
            expected_predecessor_sha256=self.pred_hash, expected_bootstrap_sha256=self.base_hash)
