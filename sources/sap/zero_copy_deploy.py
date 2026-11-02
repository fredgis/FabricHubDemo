"""Target-bound two-phase operator. Importing this module never authenticates.

Parent integration API: NativeBackend(client, evidence_reader, validator), then
Operator(...).serving(apply_serving=True) and, separately, .retire(apply_retirement=True).
No CLI defaults, retries, schedule writes, row-count seed gates or native-feed edits.
Evidence callbacks MUST perform fresh reads, not return a cached qualification.
Unknown Fabric transactional DDL support is a blocking gate, not assumed success.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from pathlib import Path

from sources.sap.gold_qualification import read_rows
from sources.sap.retirement import plan
from sources.sap.zero_copy_guards import normalize_definition, validate_binding

HEADER = re.compile(r'\ACREATE OR ALTER (VIEW|FUNCTION) \[sap_live\]\.\[([a-z_]+)\]', re.I)
SCHEMA_SQL = "IF SCHEMA_ID('sap_live') IS NULL EXEC('CREATE SCHEMA [sap_live]');"


def reviewed_batches(data, approved_sha):
    if not re.fullmatch('[0-9a-f]{64}', approved_sha or '') or hashlib.sha256(data).hexdigest() != approved_sha:
        raise ValueError('Reviewed artifact hash mismatch')
    text = data.decode('utf-8')
    parts = text.removesuffix('\n').split('\n-- @batch\n')
    first = '\n'.join(line for line in parts[0].split('\n') if not line.startswith('-- '))
    if first != SCHEMA_SQL:
        raise ValueError('Unexpected schema batch')
    batches = {}
    for body in parts[1:]:
        match = HEADER.match(body)
        if not match or match[2] in batches:
            raise ValueError('Unexpected or duplicate serving DDL')
        batches[match[2]] = body
    if len(batches) != 35 or sum(HEADER.match(s)[1].upper() == 'FUNCTION' for s in batches.values()) != 5:
        raise ValueError('Expected exactly 30 views and five inline TVFs')
    return batches


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


class Journal:
    """Exclusive local operation ledger. Existing records forbid automatic rerun."""
    def __init__(self, path):
        self.path = Path(path)

    def start(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2, default=str)
            stream.flush()
            import os
            os.fsync(stream.fileno())

    def update(self, value):
        # Retain before definitions in every record, including ambiguous commits.
        temporary = self.path.with_suffix(self.path.suffix + '.tmp')
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2, default=str)
            stream.flush()
            import os
            os.fsync(stream.fileno())
        temporary.replace(self.path)


class NativeBackend:
    """Real scoped TDS adapter; host provides tested native qualification hooks.

    evidence_reader(client) returns live job, schedules, native feed definitions,
    and verified transactional_ddl_supported/evidence fields. validator(con,
    snapshot, names, nonce) executes all interfaces and independent cardinality/
    financial checks, returning the proof contract enforced below. Both hooks are
    deliberately mandatory: SELECT success cannot establish remote DDL support.
    """
    def __init__(self, client, evidence_reader, validator):
        self.client = client
        self.evidence_reader = evidence_reader
        self.validator = validator

    def open(self):
        from sources.sap.warehouse import discover, connect
        source, warehouse = discover(self.client, 'gold')
        con = connect(self.client, warehouse)
        return con, {'workspace_id': self.client.target['workspace_id'],
                     'warehouse_id': warehouse['id'], 'source_id': source['id'],
                     'source_database': source['displayName']}

    def snapshot(self, con, discovered):
        from sources.sap.warehouse import ident
        database = read_rows(con, 'SELECT DB_NAME() AS database_name')[0]['database_name']
        objects = read_rows(con, "SELECT s.name AS schema_name,o.name,o.type FROM sys.objects o JOIN sys.schemas s ON s.schema_id=o.schema_id WHERE o.is_ms_shipped=0 ORDER BY s.name,o.name")
        definitions = read_rows(con, "SELECT s.name AS schema_name,o.name,o.type,m.definition FROM sys.sql_modules m JOIN sys.objects o ON o.object_id=m.object_id JOIN sys.schemas s ON s.schema_id=o.schema_id ORDER BY s.name,o.name")
        dependencies = read_rows(con, "SELECT s.name AS referencing_schema,o.name AS referencing_name,d.referenced_database_name,d.referenced_schema_name,d.referenced_entity_name FROM sys.sql_expression_dependencies d JOIN sys.objects o ON o.object_id=d.referencing_id JOIN sys.schemas s ON s.schema_id=o.schema_id ORDER BY s.name,o.name,d.referenced_entity_name")
        schema = read_rows(con, 'SELECT TABLE_SCHEMA,TABLE_NAME,COLUMN_NAME,DATA_TYPE,CHARACTER_MAXIMUM_LENGTH,NUMERIC_PRECISION,NUMERIC_SCALE,DATETIME_PRECISION,IS_NULLABLE FROM ' + ident(discovered['source_database']) + ".INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='dbo' ORDER BY TABLE_NAME,ORDINAL_POSITION")
        external = self.evidence_reader(self.client)
        return {**discovered, 'database_name': database, 'objects': objects,
                'definitions': definitions, 'dependencies': dependencies,
                'native_schema': schema, 'external': external}

    def execute(self, con, sql):
        cursor = con.cursor()
        try:
            cursor.execute(sql)
        finally:
            cursor.close()

    def validate(self, con, snapshot, names, nonce):
        return self.validator(con, snapshot, names, nonce)


def _defs(snapshot, serving=False):
    return {(r['schema_name'], r['name']): r['definition']
            for r in snapshot['definitions'] if (r['schema_name'] == 'sap_live') == serving
            and (serving or not (r['schema_name'] == 'gold' and r['name'].startswith('sap_')))}


def _preserved(before, after):
    if _defs(before) != _defs(after) or before['external'] != after['external'] or before['native_schema'] != after['native_schema']:
        raise ValueError('Non-SAP definitions, native schema/jobs/feeds/schedules changed')


class Operator:
    def __init__(self, backend, artifact, approved_sha, preflight, reviewed_snapshot, journal, *, system, companies):
        self.backend = backend
        self.artifact = bytes(artifact)
        self.sha = approved_sha
        self.batches = reviewed_batches(self.artifact, approved_sha)
        self.preflight = dict(preflight)
        self.reviewed = reviewed_snapshot
        self.journal = journal
        self.system = system
        self.companies = companies

    def _capture(self):
        if reviewed_batches(self.artifact, self.sha) != self.batches:
            raise ValueError('Reviewed artifact hash/batch drift')
        con, discovered = self.backend.open()
        try:
            snapshot = self.backend.snapshot(con, discovered)
            validate_binding(self.preflight, self.sha, **{k: snapshot[k] for k in ('workspace_id', 'warehouse_id', 'source_id', 'database_name')})
            external = snapshot['external']
            if any(not isinstance(r.get('definition'), str) or not r['definition'] for r in snapshot['definitions']):
                raise ValueError('Catalog contains unreadable definitions; backup/preservation impossible')
            if len(_defs(snapshot, True)) != len([r for r in snapshot['definitions'] if r['schema_name'] == 'sap_live']):
                raise ValueError('Duplicate serving definitions')
            if external.get('active_jobs') != [] or external.get('gold_job', {}).get('status') != 'Completed':
                raise ValueError('Fresh completed Gold job and idle native jobs required')
            for key in ('schedules', 'native_definitions', 'gold_job'):
                if not external.get(key):
                    raise ValueError('Missing fresh preservation evidence: ' + key)
            if external.get('transactional_ddl_supported') is not True or not external.get('transactional_ddl_evidence'):
                raise ValueError('Transactional DDL capability unverified; no write permitted')
            return con, discovered, snapshot
        except BaseException:
            con.close()
            raise

    def _bodies(self, snapshot):
        actual = _defs(snapshot, True)
        if set(actual) != {('sap_live', n) for n in self.batches}:
            raise ValueError('Persisted serving inventory mismatch')
        for name, expected in self.batches.items():
            if normalize_definition(actual[('sap_live', name)] or '') != normalize_definition(expected):
                raise ValueError('Persisted DDL body mismatch: ' + name)

    def _proof(self, con, snapshot):
        nonce = secrets.token_hex(24)
        proof = self.backend.validate(con, snapshot, tuple(self.batches), nonce)
        if (proof.get('nonce') != nonce or proof.get('snapshot_sha256') != digest(snapshot)
                or proof.get('sql_sha256') != self.sha or proof.get('data_verified') is not True
                or proof.get('interface_checks') != dict.fromkeys(self.batches, True)
                or proof.get('cardinality_verified') is not True or proof.get('financial_verified') is not True):
            raise ValueError('Fresh complete 35-interface validation proof required')
        return proof

    def _transaction(self, phase, con, discovered, before, statements, check):
        record = {'phase': phase, 'status': 'prepared', 'sql_sha256': self.sha, 'before': before}
        try:
            self.journal.start(record)  # Immutable backup + exclusive rerun guard before BEGIN.
        except BaseException:
            con.close()
            raise
        begun = False
        committing = False
        try:
            self.backend.execute(con, 'BEGIN TRANSACTION;')
            begun = True
            current = self.backend.snapshot(con, discovered)
            if digest(current) != digest(before):
                raise ValueError('Fresh in-transaction preflight drift')
            for sql in statements:
                self.backend.execute(con, sql)
            after = self.backend.snapshot(con, discovered)
            check(after)
            _preserved(before, after)
            record['status'] = 'commit_pending'
            self.journal.update(record)
            committing = True
            self.backend.execute(con, 'COMMIT TRANSACTION;')
            begun = False
            record['status'] = 'committed_readback_pending'
            self.journal.update(record)
        except BaseException:
            record['status'] = 'ambiguous_commit' if committing else 'failed_before_commit'
            if begun:
                try:
                    self.backend.execute(con, 'ROLLBACK TRANSACTION;')
                    if not committing:
                        record['status'] = 'rolled_back'
                except BaseException:
                    record['status'] = 'ambiguous_commit' if committing else 'rollback_unconfirmed'
            self.journal.update(record)
            raise
        finally:
            con.close()
        # Never retry a commit. Verify exact target from a separately opened connection.
        try:
            fresh, _, after = self._capture()
            try:
                check(after)
                _preserved(before, after)
                self._bodies(after)
                record['proof'] = self._proof(fresh, after)
                record['status'] = 'verified'
                self.journal.update(record)
            finally:
                fresh.close()
        except BaseException:
            record['status'] = 'committed_verification_failed'
            self.journal.update(record)
            raise
        return record

    def serving(self, *, apply_serving=False):
        if apply_serving is not True:
            raise ValueError('Explicit apply_serving=True required')
        con, discovered, before = self._capture()
        try:
            if digest(before) != digest(self.reviewed):
                raise ValueError('Fresh target/schema/definitions/job preflight drift')
            from sources.sap.zero_copy_serving import render_bundle
            rendered = render_bundle(before['native_schema'], before['source_database'], self.system, self.companies).encode()
            if rendered != self.artifact:
                raise ValueError('Reviewed artifact differs from fresh renderer/schema')
            existing = _defs(before, True)
            if any(key[1] not in self.batches or not body for key, body in existing.items()):
                raise ValueError('Unexpected or unreadable replacement definitions')
        except BaseException:
            con.close()
            raise
        return self._transaction('serving', con, discovered, before,
                                 [SCHEMA_SQL, *self.batches.values()], self._bodies)

    def retire(self, *, apply_retirement=False):
        if apply_retirement is not True:
            raise ValueError('Explicit apply_retirement=True required')
        # This connection is always fresh; a serving-phase proof cannot unlock DROP.
        con, discovered, before = self._capture()
        try:
            self._bodies(before)
            _preserved(self.reviewed, before)
            self._proof(con, before)
            statements = plan(before['database_name'], before['objects'], before['dependencies'])
            if before['external'].get('external_consumers_acknowledged') is not True:
                raise ValueError('Dynamic/external consumer uncertainty requires operator acknowledgement')
        except BaseException:
            con.close()
            raise

        def absent(after):
            self._bodies(after)
            if any(o['schema_name'] == 'gold' and o['name'].startswith('sap_') for o in after['objects']):
                raise ValueError('Legacy retirement inventory remains')
            from sources.sap.retirement import TABLES, VIEWS
            if any(d['referenced_entity_name'] in TABLES + VIEWS
                   and d['referenced_database_name'] in (None, after['database_name'])
                   and d['referenced_schema_name'] in (None, 'gold') for d in after['dependencies']):
                raise ValueError('Legacy dependency remains')

        # Repeat definition/dependency/proof gates after BEGIN, before the first DROP.
        def drop_statements():
            current = self.backend.snapshot(con, discovered)
            self._bodies(current)
            _preserved(before, current)
            self._proof(con, current)
            fresh_plan = plan(current['database_name'], current['objects'], current['dependencies'])
            if fresh_plan != statements:
                raise ValueError('Retirement plan drift')
            yield from fresh_plan

        return self._transaction('retirement', con, discovered, before, drop_statements(), absent)
