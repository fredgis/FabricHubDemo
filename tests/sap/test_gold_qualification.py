"""Strict Gold parity rejection probes; no cloud I/O."""
import importlib
import importlib.util
from datetime import date, datetime
from decimal import Decimal


def test_typed_multisets_preserve_duplicates_and_types():
    spec = importlib.util.find_spec('sources.sap.gold_qualification')
    assert spec is not None, 'Gold typed comparator is missing'
    from sources.sap.gold_qualification import compare
    fields = [{'name': 'ID', 'key': True, 'nullable': False}, {'name': 'VALUE', 'key': False, 'nullable': True}]
    schema = [{'COLUMN_NAME': f['name'], 'DATA_TYPE': 'varchar', 'CHARACTER_MAXIMUM_LENGTH': 8000, 'NUMERIC_PRECISION': None, 'NUMERIC_SCALE': None, 'DATETIME_PRECISION': None, 'IS_NULLABLE': 'YES'} for f in fields]
    rows = [{'ID': 'a', 'VALUE': None}, {'ID': 'a', 'VALUE': None}]
    assert compare(fields, schema, schema, rows, list(reversed(rows)), 2)['matched']
    for wrong in ([rows[0]], [rows[0], {'ID': 'a', 'VALUE': ''}], [rows[0], {'ID': 'a', 'VALUE': 0}], [rows[0], {'ID': 'a', 'VALUE': Decimal('0')}], [rows[0], {'ID': 'a', 'VALUE': date(2026, 1, 1)}], [rows[0], {'ID': 'a', 'VALUE': datetime(2026, 1, 1)}]):
        assert not compare(fields, schema, schema, rows, wrong, 2)['matched']
    changed = [dict(s) for s in schema]
    changed[0]['IS_NULLABLE'] = 'NO'
    assert not compare(fields, schema, changed, rows, rows, 2)['matched']
    changed[0] = dict(schema[0], DATA_TYPE='int')
    assert not compare(fields, schema, changed, rows, rows, 2)['matched']
    assert not compare(fields, schema, [], rows, rows, 2)['matched']
    assert not compare(fields, schema, schema, [{'ID': None, 'VALUE': None}], [{'ID': None, 'VALUE': None}], 1)['matched']


def test_verdict_requires_complete_inventory_and_every_gate():
    from sources.sap import gold_qualification as q
    assert hasattr(q, 'verdict'), 'Complete fail-closed verdict missing'
    tables = {str(i): {'matched': True} for i in range(37)}
    checks = {n: True for n in ('bridge_pk', 'customer_surrogates', 'orders_both_directions', 'billing_linkage', 'journal_balance', 'job_completed', 'schema_stable')}
    assert q.verdict(tables, checks, set(tables))
    for name in checks:
        bad = dict(checks, **{name: False})
        assert not q.verdict(tables, bad, set(tables))
        assert not q.verdict(tables, {k: v for k, v in checks.items() if k != name}, set(tables))
    assert not q.verdict({}, checks, set(tables))
    assert not q.verdict(tables, checks, set(tables) | {'other'})
    assert not q.verdict({k: {'matched': False} for k in tables}, checks, set(tables))




def qualification_fixture(tmp_path):
    import json
    from sources.sap import native
    from sources.sap.native_operational import schema_inventory
    schemas = schema_inventory(native.load_contract().schemas)
    required = {'C_BILLINGDOCITEMBASICDEX_1', 'ZMSF_ORDER_LINK', 'I_CUSTOMER',
                'ZMSF_CUSTOMER_LINK', 'I_GLACCOUNTLINEITEMRAWDATA', 'I_OPERATIONALACCTGDOCITEM'}
    names = required | set(sorted(set(schemas) - required - {'DD03ND'})[:31])
    schemas = {n: schemas[n] for n in names}
    objects = {name: {'fields': [{'name': f.name, 'key': f.key, 'nullable': True} for f in obj.fields]}
               for name, obj in schemas.items() if name != 'DD03ND'}
    package = tmp_path / '.state/sap/operational-native-offline-v1/package'
    package.mkdir(parents=True)
    for name, value in [('contract.json', {'objects': objects}), ('batches.json', [{'objects': objects}]),
                        ('final-snapshot.json', {n: [] for n in objects})]:
        (package / name).write_text(json.dumps(value))
    state = tmp_path / '.state/sap/coordinated-publication-v1'
    state.mkdir(parents=True)
    target = {'workspace_id': '00000000-0000-4000-8000-000000000201', 'system_suffix': 'a1b2c3d4'}
    binding = {'workspace_id': target['workspace_id'], 'stage': 's2g',
               'pipeline_id': '00000000-0000-4000-8000-000000000203',
               'job_id': '00000000-0000-4000-8000-000000000202'}
    (state / 'coordination.json').write_text(json.dumps({'target': target, 'gold_job': binding}))
    return tmp_path


def test_run_routes_schema_and_data_through_one_warehouse_connection(tmp_path):
    from pathlib import Path
    from unittest.mock import patch
    from sources.sap import gold_qualification as q
    from sources.sap import warehouse
    root = qualification_fixture(tmp_path)
    calls = []
    class Client:
        def __init__(self, target):
            self._http = lambda *args: None
        def item(self, name, kind):
            assert (name, kind) == ('bps_s2g_full_processing_pipeline_a1b2c3d4', 'DataPipeline')
            return {'id': '00000000-0000-4000-8000-000000000203'}
        def request(self, *args):
            return (None, None, {'status': 'Completed', 'id': '00000000-0000-4000-8000-000000000202'})
    class Connection:
        timeout = 0
        def close(self):
            pass
    con = Connection()
    def discovery(client, stage):
        return ({'displayName': 'bps_' + stage + '_a1b2c3d4'}, {'displayName': 'MSFlixGold'})
    def execute(connection, sql):
        assert connection is con
        calls.append(sql)
        if 'INFORMATION_SCHEMA' in sql:
            return [{'TABLE_SCHEMA': 'dbo', 'TABLE_NAME': 'C_BILLINGDOCITEMBASICDEX_1', 'COLUMN_NAME': name}
                    for name in ('_SystemName', '_Delete')]
        raise RuntimeError('bounded routing probe')
    with patch('sources.sap.fabric_client.ScopedClient', Client), patch.object(warehouse, 'discover', discovery), patch.object(warehouse, 'connect', return_value=con) as connect, patch.object(q, 'read_rows', execute), patch.object(Path, 'write_text'):
        report = q.run(root)
    assert connect.call_count == 1, 'qualification must open only MSFlixGold'
    assert connect.call_args.args[1]['displayName'] == 'MSFlixGold'
    assert len(connect.call_args.args) == 2, 'never select lakehouse transport'
    assert '[bps_silver_a1b2c3d4].INFORMATION_SCHEMA.COLUMNS' in calls[0]
    assert '[bps_gold_a1b2c3d4].INFORMATION_SCHEMA.COLUMNS' in calls[1]
    assert 'FROM [bps_silver_a1b2c3d4].dbo.[C_BILLINGDOCITEMBASICDEX_1]' in calls[2]
    assert "[_SystemName]='S4M' AND [_Delete]=''" in calls[2]
    assert report['data_verified'] is False
    assert report['errors'] == ['RuntimeError: bounded routing probe']


def test_all_qualification_queries_use_explicit_database_coordinates(tmp_path):
    import json
    from pathlib import Path
    from unittest.mock import patch
    from sources.sap import gold_qualification as q
    from sources.sap import warehouse
    root = qualification_fixture(tmp_path)
    contract = json.loads((root / '.state/sap/operational-native-offline-v1/package/contract.json').read_text())
    calls = []
    class Client:
        def __init__(self, target):
            self._http = lambda *args: None
        def item(self, name, kind):
            assert (name, kind) == ('bps_s2g_full_processing_pipeline_a1b2c3d4', 'DataPipeline')
            return {'id': '00000000-0000-4000-8000-000000000203'}
        def request(self, *args):
            return (None, None, {'status': 'Completed', 'id': '00000000-0000-4000-8000-000000000202'})
    class Connection:
        timeout = 0
        def close(self):
            pass
    con = Connection()
    def discovery(client, stage):
        return ({'displayName': 'bps_' + stage + '_a1b2c3d4'}, {'displayName': 'MSFlixGold'})
    def execute(connection, sql):
        assert connection is con
        calls.append(sql)
        if 'INFORMATION_SCHEMA' in sql:
            return [{'TABLE_SCHEMA': 'dbo', 'TABLE_NAME': n, 'COLUMN_NAME': f}
                    for n, obj in contract['objects'].items()
                    for f in [v['name'] for v in obj['fields']] + ['_SystemName', '_Delete']]
        if 'joined_rows' in sql:
            return [{'joined_rows': 0}]
        if 'bridge_only' in sql:
            return [{'bridge_only': 0, 'orders_only': 0, 'wrong_customer': 0}]
        if ' invalid ' in sql:
            return [{'invalid': 0}]
        return []
    with patch('sources.sap.fabric_client.ScopedClient', Client), patch.object(warehouse, 'discover', discovery), patch.object(warehouse, 'connect', return_value=con) as connect, patch.object(q, 'read_rows', execute), patch.object(Path, 'write_text'):
        report = q.run(root)
    assert not report['errors']
    assert len(report['tables']) == 37
    assert connect.call_count == 1
    assert all('FROM dbo.' not in sql for sql in calls)
    order_sql = report['observations']['orders_both_directions']['sql']
    assert 'x.CUSTOMER_KEY' in order_sql, 'retain the observed schema mapping field'
    assert '[MSFlixGold].gold.fact_order_line' in order_sql
    assert ' gold.fact_order_line' not in order_sql
    assert '[bps_gold_a1b2c3d4].dbo.[ZMSF_CUSTOMER_LINK]' in order_sql
    assert 'x._SystemName=b._SystemName' in order_sql
    assert report['checks']['schema_stable'] is True
    assert report['data_verified'] is False, 'empty fixture must not pass data gates'


class FetchCursor:
    def __init__(self, rows, failure=None):
        self.rows = list(rows)
        self.description = [('ID',), ('VALUE',)]
        self.sizes = []
        self.closed = False
        self.failure = failure

    def execute(self, sql):
        self.sql = sql
        if self.failure == 'execute':
            raise RuntimeError('execute failed')

    def fetchmany(self, size):
        self.sizes.append(size)
        if self.failure == 'fetch':
            raise RuntimeError('fetch failed')
        result, self.rows = self.rows[:size], self.rows[size:]
        return result

    def close(self):
        self.closed = True


class FetchConnection:
    def __init__(self, cursor):
        self.reader = cursor

    def cursor(self):
        return self.reader


def test_local_read_fetches_only_bounded_batches_preserving_types():
    from sources.sap import gold_qualification as q
    assert hasattr(q, 'read_rows'), 'bounded local SQL reader missing'
    values = [(str(i), Decimal('1.00')) for i in range(1092)]
    cursor = FetchCursor(values)
    result = q.read_rows(FetchConnection(cursor), 'SELECT ID,VALUE')
    assert result == [{'ID': a, 'VALUE': b} for a, b in values]
    assert all(type(row['VALUE']) is Decimal for row in result)
    assert cursor.sizes and set(cursor.sizes) == {128}
    assert cursor.sql == 'SELECT ID,VALUE'
    assert cursor.closed


def test_local_read_rejects_more_than_10000_rows_without_truncation():
    from sources.sap import gold_qualification as q
    from unittest import TestCase
    cursor = FetchCursor([(str(i), None) for i in range(10001)])
    with TestCase().assertRaisesRegex(ValueError, '10000'):
        q.read_rows(FetchConnection(cursor), 'SELECT ID,VALUE')
    assert cursor.closed
    assert set(cursor.sizes) == {128}
    boundary = FetchCursor([(str(i), None) for i in range(10000)])
    assert len(q.read_rows(FetchConnection(boundary), 'SELECT ID,VALUE')) == 10000
    assert boundary.closed


def test_local_read_closes_cursor_on_execute_and_fetch_exceptions():
    from sources.sap import gold_qualification as q
    from unittest import TestCase
    for failure in ('execute', 'fetch'):
        cursor = FetchCursor([], failure=failure)
        with TestCase().assertRaisesRegex(RuntimeError, failure + ' failed'):
            q.read_rows(FetchConnection(cursor), 'SELECT ID,VALUE')
        assert cursor.closed, failure + ' exception leaked cursor'


def test_sql_zero_gate_rejects_empty_null_and_nonzero():
    from sources.sap import gold_qualification as q
    assert hasattr(q, 'zero_gate'), 'SQL observation gate missing'
    assert q.zero_gate([{'invalid': 0}], ('invalid',))
    for rows in ([], [{'invalid': None}], [{'invalid': 1}], [{}], [{'invalid': False}], [{'invalid': 0}, {'invalid': 0}]):
        assert not q.zero_gate(rows, ('invalid',))


def test_missing_job_binding_fails_before_cloud_or_sql(tmp_path):
    import json
    from unittest.mock import patch
    from sources.sap import gold_qualification as q
    package = tmp_path / '.state/sap/operational-native-offline-v1/package'
    package.mkdir(parents=True)
    for name, value in [('contract.json', {}), ('batches.json', [{'objects': {}}]), ('final-snapshot.json', {})]:
        (package / name).write_text(json.dumps(value))
    state = tmp_path / '.state/sap/coordinated-publication-v1'
    state.mkdir(parents=True)
    (state / 'coordination.json').write_text(json.dumps({'target': {'workspace_id': '00000000-0000-4000-8000-000000000001'}}))
    with patch('sources.sap.fabric_client.ScopedClient') as client, patch('sources.sap.warehouse.connect') as connect:
        report = q.run(tmp_path)
    assert report['data_verified'] is False
    assert report['errors'] == ['ValueError: Explicit Gold pipeline/job binding required']
    client.assert_not_called()
    connect.assert_not_called()

