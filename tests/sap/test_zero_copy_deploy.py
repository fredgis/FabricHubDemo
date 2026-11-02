"""Offline boundary tests; never opens a Fabric connection."""
import hashlib
import unittest
import copy
import tempfile
from pathlib import Path
from unittest.mock import patch
from sources.sap import zero_copy_deploy as deploy
from sources.sap.retirement import TABLES, VIEWS


def artifact():
    statements = [deploy.SCHEMA_SQL]
    for i in range(30):
        statements.append(f'CREATE OR ALTER VIEW [sap_live].[view_{chr(97 + i // 26)}{chr(97 + i % 26)}] AS\nSELECT 1 AS n;')
    for i in range(5):
        statements.append(f'CREATE OR ALTER FUNCTION [sap_live].[fn_{chr(97+i)}](@as_of date)\nRETURNS TABLE\nAS RETURN (SELECT 1 AS n);')
    return ('\n-- @batch\n'.join(statements) + '\n').encode()


class Connection:
    def __init__(self):
        self.closed = False
    def close(self):
        self.closed = True


class Ledger:
    def __init__(self):
        self.records = []
    def start(self, record):
        self.records.append(copy.deepcopy(record))
    def update(self, record):
        self.records.append(copy.deepcopy(record))


class Backend:
    def __init__(self, batches):
        self.batches = batches
        self.writes = []
        self.connections = []
        self.partial = False
        self.fail_commit = False
        self.drift_body = False
        self.s = {'workspace_id': 'ws', 'warehouse_id': 'wh', 'source_id': 'src',
                  'database_name': 'MSFlixGold', 'source_database': 'native',
                  'native_schema': [], 'dependencies': [],
                  'objects': [{'schema_name': 'gold', 'name': n, 'type': 'U'} for n in TABLES]
                  + [{'schema_name': 'gold', 'name': n, 'type': 'V'} for n in VIEWS],
                  'definitions': [{'schema_name': 'other', 'name': 'keep', 'type': 'V', 'definition': 'SELECT native'}],
                  'external': {'active_jobs': [], 'gold_job': {'status': 'Completed', 'id': 'job'},
                               'schedules': {'bps': {'enabled': True, 'times': ['10:00', '13:00']}},
                               'native_definitions': {'bps': 'unchanged'},
                               'transactional_ddl_supported': True, 'transactional_ddl_evidence': 'parent probe',
                               'external_consumers_acknowledged': True}}
    def open(self):
        c = Connection()
        self.connections.append(c)
        return c, {}
    def snapshot(self, con, discovered):
        return copy.deepcopy(self.s)
    def execute(self, con, sql):
        self.writes.append(sql)
        if sql == 'BEGIN TRANSACTION;':
            self.backup = copy.deepcopy(self.s)
        elif sql == 'ROLLBACK TRANSACTION;':
            self.s = self.backup
        elif sql == 'COMMIT TRANSACTION;' and self.fail_commit:
            raise OSError('lost acknowledgement')
        elif sql.startswith('CREATE OR ALTER'):
            name = deploy.HEADER.match(sql)[2]
            self.s['definitions'] = [r for r in self.s['definitions'] if not (r['schema_name'] == 'sap_live' and r['name'] == name)]
            self.s['definitions'].append({'schema_name': 'sap_live', 'name': name, 'definition': sql + (' ' if self.drift_body else ''), 'type': 'V'})
        elif sql.startswith('DROP'):
            name = sql.split('[gold].[')[1].split(']')[0]
            self.s['objects'] = [r for r in self.s['objects'] if r['name'] != name]
    def validate(self, con, snapshot, names, nonce):
        checks = dict.fromkeys(names, True)
        if self.partial:
            checks.pop(next(iter(checks)))
        return {'nonce': nonce, 'snapshot_sha256': deploy.digest(snapshot),
                'sql_sha256': hashlib.sha256(artifact()).hexdigest(), 'data_verified': True,
                'interface_checks': checks, 'cardinality_verified': True, 'financial_verified': True}
    def deploy_existing(self):
        self.s['definitions'] += [{'schema_name': 'sap_live', 'name': n, 'definition': sql, 'type': 'V'} for n, sql in self.batches.items()]


class OperatorTests(unittest.TestCase):
    def setUp(self):
        self.raw = artifact()
        self.sha = hashlib.sha256(self.raw).hexdigest()
        self.backend = Backend(deploy.reviewed_batches(self.raw, self.sha))
        self.ledger = Ledger()
        self.before = copy.deepcopy(self.backend.s)
        self.preflight = {'status': 'preflight_passed', 'sql_sha256': self.sha, **{k: self.before[k] for k in ('workspace_id', 'warehouse_id', 'source_id', 'database_name')}}
        self.op = deploy.Operator(self.backend, self.raw, self.sha, self.preflight, self.before, self.ledger, system='S4M', companies=('1710','1720','1730'))

    def serving(self):
        with patch('sources.sap.zero_copy_serving.render_bundle', return_value=self.raw.decode()):
            return self.op.serving(apply_serving=True)

    def test_wrong_target_forbids_begin(self):
        self.backend.s['warehouse_id'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'binding'):
            self.serving()
        self.assertEqual([], self.backend.writes)
        self.assertTrue(self.backend.connections[0].closed)

    def test_unverified_transaction_support_forbids_begin(self):
        self.backend.s['external']['transactional_ddl_supported'] = False
        with self.assertRaisesRegex(ValueError, 'capability'):
            self.serving()
        self.assertEqual([], self.backend.writes)

    def test_partial_proof_forbids_drop(self):
        self.backend.deploy_existing()
        self.backend.partial = True
        with self.assertRaisesRegex(ValueError, '35-interface'):
            self.op.retire(apply_retirement=True)
        self.assertEqual([], self.backend.writes)

    def test_wrong_body_forbids_drop(self):
        self.backend.deploy_existing()
        self.backend.s['definitions'][-1]['definition'] += ' '
        with self.assertRaisesRegex(ValueError, 'body'):
            self.op.retire(apply_retirement=True)
        self.assertEqual([], self.backend.writes)

    def test_serving_individual_batches_and_fresh_readback(self):
        result = self.serving()
        self.assertEqual('verified', result['status'])
        self.assertEqual('BEGIN TRANSACTION;', self.backend.writes[0])
        self.assertEqual('COMMIT TRANSACTION;', self.backend.writes[-1])
        self.assertEqual(35, len([s for s in self.backend.writes if s.startswith('CREATE OR ALTER')]))
        self.assertEqual(2, len(self.backend.connections))
        self.assertEqual(self.before['objects'], self.backend.s['objects'])
        self.assertEqual(self.before['definitions'], result['before']['definitions'])

    def test_persisted_body_mismatch_rolls_back_before_commit(self):
        self.backend.drift_body = True
        with self.assertRaisesRegex(ValueError, 'body'):
            self.serving()
        self.assertEqual('ROLLBACK TRANSACTION;', self.backend.writes[-1])
        self.assertNotIn('COMMIT TRANSACTION;', self.backend.writes)
        self.assertEqual(self.before, self.backend.s)

    def test_retirement_exact_order_and_fresh_connections(self):
        self.backend.deploy_existing()
        result = self.op.retire(apply_retirement=True)
        self.assertEqual('verified', result['status'])
        self.assertEqual([f'DROP VIEW [gold].[{n}];' for n in VIEWS] + [f'DROP TABLE [gold].[{n}];' for n in TABLES], self.backend.writes[1:-1])
        self.assertEqual(2, len(self.backend.connections))
        self.assertEqual([], self.backend.s['objects'])

    def test_ambiguous_commit_is_recorded_never_retried(self):
        self.backend.fail_commit = True
        with self.assertRaises(OSError):
            self.serving()
        self.assertEqual('ambiguous_commit', self.ledger.records[-1]['status'])
        self.assertEqual(1, self.backend.writes.count('COMMIT TRANSACTION;'))

    def test_non_sap_drift_forbids_retirement(self):
        self.backend.deploy_existing()
        self.backend.s['definitions'][0]['definition'] += ' drift'
        with self.assertRaisesRegex(ValueError, 'Non-SAP'):
            self.op.retire(apply_retirement=True)
        self.assertEqual([], self.backend.writes)

    def test_partial_proof_inside_transaction_rolls_back_without_drop(self):
        self.backend.deploy_existing()
        validate = self.backend.validate
        def changed(con, snapshot, names, nonce):
            if 'BEGIN TRANSACTION;' in self.backend.writes:
                self.backend.partial = True
            return validate(con, snapshot, names, nonce)
        self.backend.validate = changed
        with self.assertRaisesRegex(ValueError, '35-interface'):
            self.op.retire(apply_retirement=True)
        self.assertEqual(['BEGIN TRANSACTION;', 'ROLLBACK TRANSACTION;'], self.backend.writes)

    def test_retirement_dependency_forbids_write(self):
        self.backend.deploy_existing()
        self.backend.s['dependencies'] = [{'referencing_schema': 'other', 'referencing_name': 'consumer', 'referenced_database_name': None, 'referenced_schema_name': 'gold', 'referenced_entity_name': TABLES[0]}]
        with self.assertRaisesRegex(ValueError, 'dependency'):
            self.op.retire(apply_retirement=True)
        self.assertEqual([], self.backend.writes)

    def test_drop_error_rolls_back_exact_before_state(self):
        self.backend.deploy_existing()
        before = copy.deepcopy(self.backend.s)
        execute = self.backend.execute
        def fail(con, sql):
            execute(con, sql)
            if sql.startswith('DROP TABLE'):
                raise OSError('DDL rejected')
        self.backend.execute = fail
        with self.assertRaises(OSError):
            self.op.retire(apply_retirement=True)
        self.assertEqual(before, self.backend.s)
        self.assertEqual('ROLLBACK TRANSACTION;', self.backend.writes[-1])
        self.assertNotIn('COMMIT TRANSACTION;', self.backend.writes)

    def test_unreadable_non_sap_definitions_forbid_write(self):
        self.backend.s['definitions'][0]['definition'] = None
        self.op.reviewed = copy.deepcopy(self.backend.s)
        with self.assertRaisesRegex(ValueError, 'unreadable'):
            self.serving()
        self.assertEqual([], self.backend.writes)

    def test_schedules_drift_forbids_drop(self):
        self.backend.deploy_existing()
        self.backend.s['external']['schedules']['bps']['enabled'] = False
        with self.assertRaisesRegex(ValueError, 'Non-SAP'):
            self.op.retire(apply_retirement=True)
        self.assertEqual([], self.backend.writes)

    def test_existing_journal_closes_connection_before_any_write(self):
        def refuse(record):
            raise FileExistsError('manual reconciliation required')
        self.ledger.start = refuse
        with self.assertRaises(FileExistsError):
            self.serving()
        self.assertEqual([], self.backend.writes)
        self.assertTrue(self.backend.connections[0].closed)

    def test_no_apply_flags_forbid_connection(self):
        for method in (self.op.serving, self.op.retire):
            with self.assertRaises(ValueError):
                method()
        self.assertEqual([], self.backend.connections)

    def test_reviewed_hash_changed_after_construction_forbids_write(self):
        self.op.artifact += b'-- changed'
        with self.assertRaisesRegex(ValueError, 'hash'):
            self.serving()
        self.assertEqual([], self.backend.writes)

    def test_serving_prebegin_drift_forbids_ddl(self):
        original = self.backend.snapshot
        count = [0]
        def drift(con, discovered):
            count[0] += 1
            if count[0] == 2:
                self.backend.s['definitions'][0]['definition'] += ' drift'
            return original(con, discovered)
        self.backend.snapshot = drift
        with self.assertRaisesRegex(ValueError, 'drift'):
            self.serving()
        self.assertEqual(['BEGIN TRANSACTION;', 'ROLLBACK TRANSACTION;'], self.backend.writes)


class JournalTests(unittest.TestCase):
    def test_existing_ledger_blocks_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = deploy.Journal(Path(directory) / 'operation.json')
            journal.start({'status': 'ambiguous_commit'})
            with self.assertRaises(FileExistsError):
                journal.start({'status': 'prepared'})


class ArtifactTests(unittest.TestCase):
    def test_wrong_hash_rejected(self):
        with self.assertRaisesRegex(ValueError, 'hash'):
            deploy.reviewed_batches(b'not SQL', '0' * 64)


if __name__ == '__main__':
    unittest.main()
