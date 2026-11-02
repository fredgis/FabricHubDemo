"""Read-only, exact typed Silver/Gold operational qualification. No coercions."""
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import time
import re


def read_rows(con, sql):
    """Read exact driver values in small batches, always releasing the cursor."""
    cursor = con.cursor()
    try:
        cursor.execute(sql)
        names = [column[0] for column in cursor.description]
        rows = []
        while True:
            batch = cursor.fetchmany(128)
            if not batch:
                return rows
            if len(rows) + len(batch) > 10000:
                raise ValueError('Gold qualification query exceeds 10000 rows; truncation forbidden')
            rows.extend(dict(zip(names, row)) for row in batch)
    finally:
        cursor.close()


def run(root=None, *, job_binding=None):
    """Capture live observations and apply tested gates; GET and SELECT only."""
    from sources.sap.fabric_client import ScopedClient
    from sources.sap.warehouse import discover, connect, ident
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    out = root / '.state/sap/gold-qualification'
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report = {'data_verified': False, 'read_only': True, 'tables': {}, 'checks': {}, 'observations': {}, 'errors': []}
    def save():
        (out / 'qualification.json').write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
    def query(con, sql, name):
        if time.monotonic() - started > 480:
            raise TimeoutError('Bounded Gold qualification timeout')
        sql += " OPTION (LABEL = 'MSFlix_SAP_gold_qualification')"
        result = read_rows(con, sql)
        report['observations'][name] = {'sql': sql, 'rows': result}
        save()
        return result
    client = None
    connections = []
    try:
        package = root / '.state/sap/operational-native-offline-v1/package'
        contract = json.loads((package / 'contract.json').read_text())
        batches = json.loads((package / 'batches.json').read_text())
        snapshot = json.loads((package / 'final-snapshot.json').read_text())
        inventory = set().union(*(set(b['objects']) for b in batches)) - {'DD03ND'}
        report['inventory'] = sorted(inventory)
        report['package_sha256'] = {n: hashlib.sha256((package / n).read_bytes()).hexdigest() for n in ('contract.json', 'batches.json', 'final-snapshot.json')}
        coordination = json.loads((root / '.state/sap/coordinated-publication-v1/coordination.json').read_text())
        target = coordination['target']
        binding = job_binding if job_binding is not None else coordination.get('gold_job')
        if binding is None:
            checkpoint = root / '.state/sap/s2g-job.json'
            if checkpoint.exists():
                binding = json.loads(checkpoint.read_text())
        if not isinstance(binding, dict):
            raise ValueError('Explicit Gold pipeline/job binding required')
        if binding.get('workspace_id') != target['workspace_id'] or binding.get('stage') != 's2g':
            raise ValueError('Gold pipeline/job binding belongs to another target/stage')
        for key in ('workspace_id', 'pipeline_id', 'job_id'):
            if not isinstance(binding.get(key), str) or not re.fullmatch(
                    r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', binding[key]):
                raise ValueError('Invalid Gold pipeline/job coordinate grammar')
        report['job_binding'] = dict(binding)
        client = ScopedClient(target)
        original_http = client._http
        def readonly_http(method, url, body, skill):
            if method != 'GET':
                raise ValueError('Cloud writes forbidden')
            return original_http(method, url, body, 'sqldw-cli')
        client._http = readonly_http
        gold, wh = discover(client, 'gold')
        silver, _ = discover(client, 'silver')
        report['discovery'] = {'gold': gold, 'silver': silver, 'warehouse': wh}
        pipeline = client.item('bps_s2g_full_processing_pipeline_' + target['system_suffix'], 'DataPipeline')
        if pipeline.get('id') != binding['pipeline_id']:
            raise ValueError('Gold pipeline evidence mismatch')
        job_path = '/v1/workspaces/' + target['workspace_id'] + '/items/' + binding['pipeline_id'] + '/jobs/instances/' + binding['job_id']
        job = client.request('GET', job_path)[2]
        report['job'] = job
        report['checks']['job_completed'] = job.get('status') == 'Completed' and job.get('id') == binding['job_id']
        wc = connect(client, wh)
        connections.append(wc)
        wc.timeout = 30
        databases = [ident(item['displayName']) for item in (silver, gold)]
        report['transport'] = {'connection': 'MSFlixGold', 'databases': databases}
        sqls = ["SELECT TABLE_SCHEMA,TABLE_NAME,COLUMN_NAME,DATA_TYPE,CHARACTER_MAXIMUM_LENGTH,NUMERIC_PRECISION,NUMERIC_SCALE,DATETIME_PRECISION,IS_NULLABLE FROM " + db + ".INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='dbo' ORDER BY TABLE_NAME,ORDINAL_POSITION" for db in databases]
        schemas = [query(wc, sql, stage + '_schema') for sql, stage in zip(sqls, ('silver', 'gold'))]
        goldrows = {}
        for n in sorted(inventory):
            fields = contract['objects'][n]['fields']
            stage_rows = []
            table_schemas = []
            for i, db in enumerate(databases):
                columns = [r for r in schemas[i] if r['TABLE_SCHEMA'] == 'dbo' and r['TABLE_NAME'] == n]
                table_schemas.append(columns)
                available = {r['COLUMN_NAME'] for r in columns}
                if not {'_SystemName', '_Delete'} <= available:
                    raise ValueError(n + ': S4M/nondeleted filter schema missing')
                selected = ','.join(ident(f['name']) for f in fields)
                rows = query(wc, 'SELECT ' + selected + ' FROM ' + db + '.dbo.' + ident(n) + " WHERE [_SystemName]='S4M' AND [_Delete]=''", ('silver' if i == 0 else 'gold') + '_' + n)
                stage_rows.append(rows)
            report['tables'][n] = compare(fields, *table_schemas, *stage_rows, len(snapshot[n]))
            goldrows[n] = stage_rows[1]
            print(n, report['tables'][n]['matched'], len(stage_rows[1]), flush=True)
            save()
        db = ident(gold['displayName']) + '.dbo.'
        b = db + '[ZMSF_ORDER_LINK]'
        bill = db + '[C_BILLINGDOCITEMBASICDEX_1]'
        c = db + '[I_CUSTOMER]'
        filt = "[_SystemName]='S4M' AND [_Delete]=''"
        prefix = f'WITH b AS (SELECT * FROM {b} WHERE {filt}), i AS (SELECT * FROM {bill} WHERE {filt}), c AS (SELECT * FROM {c} WHERE {filt}), x AS (SELECT * FROM {db}[ZMSF_CUSTOMER_LINK] WHERE {filt}) '
        r = query(wc, prefix + 'SELECT COUNT_BIG(*) invalid FROM (SELECT BILLINGDOCUMENT,BILLINGDOCUMENTITEM FROM b GROUP BY BILLINGDOCUMENT,BILLINGDOCUMENTITEM HAVING COUNT_BIG(*)<>1 OR BILLINGDOCUMENT IS NULL OR BILLINGDOCUMENTITEM IS NULL) d', 'bridge_pk')
        report['checks']['bridge_pk'] = zero_gate(r, ('invalid',))
        r = query(wc, prefix + "SELECT COUNT_BIG(*) invalid FROM b LEFT JOIN c ON b.CUSTOMER=c.CUSTOMER AND b._SystemName=c._SystemName WHERE c.[Key] IS NULL OR c.[Key]=-1 OR b._key_ICUSTOMER IS NULL OR b._key_ICUSTOMER<>c.[Key]", 'customer_surrogates')
        multiplicity = query(wc, prefix + 'SELECT COUNT_BIG(*) joined_rows FROM b LEFT JOIN c ON b.CUSTOMER=c.CUSTOMER AND b._SystemName=c._SystemName', 'customer_join_multiplicity')
        report['checks']['customer_surrogates'] = zero_gate(r, ('invalid',)) and multiplicity == [{'joined_rows': len(goldrows['ZMSF_ORDER_LINK'])}]
        r = query(wc, prefix + 'SELECT (SELECT COUNT_BIG(*) FROM b LEFT JOIN [MSFlixGold].gold.fact_order_line o ON b.ORDER_ID=o.order_id AND b.ORDER_LINE_NUMBER=o.line_number WHERE o.order_id IS NULL) bridge_only, (SELECT COUNT_BIG(*) FROM [MSFlixGold].gold.fact_order_line o WHERE NOT EXISTS (SELECT 1 FROM b WHERE b.ORDER_ID=o.order_id AND b.ORDER_LINE_NUMBER=o.line_number)) orders_only, (SELECT COUNT_BIG(*) FROM b LEFT JOIN x ON b.CUSTOMER=x.CUSTOMER AND x._SystemName=b._SystemName LEFT JOIN [MSFlixGold].gold.fact_order_line o ON b.ORDER_ID=o.order_id AND b.ORDER_LINE_NUMBER=o.line_number WHERE x.CUSTOMER_KEY IS NULL OR o.customer_key IS NULL OR x.CUSTOMER_KEY<>o.customer_key) wrong_customer', 'orders_both_directions')
        report['checks']['orders_both_directions'] = zero_gate(r, ('bridge_only', 'orders_only', 'wrong_customer'))
        r = query(wc, prefix + 'SELECT COUNT_BIG(*) invalid FROM b LEFT JOIN i ON b.BILLINGDOCUMENT=i.BILLINGDOCUMENT AND b.BILLINGDOCUMENTITEM=i.BILLINGDOCUMENTITEM WHERE i.BILLINGDOCUMENT IS NULL OR i.SOLDTOPARTY<>b.CUSTOMER OR i.SOLDTOPARTY IS NULL OR (b.ORIGINAL_BILLINGDOCUMENT IS NOT NULL AND NOT EXISTS (SELECT 1 FROM i orig WHERE orig.BILLINGDOCUMENT=b.ORIGINAL_BILLINGDOCUMENT AND orig.BILLINGDOCUMENTITEM=b.ORIGINAL_BILLINGDOCUMENTITEM AND orig.SOLDTOPARTY=b.CUSTOMER))', 'billing_linkage')
        report['checks']['billing_linkage'] = zero_gate(r, ('invalid',))
        balanced = True
        for n in ('I_GLACCOUNTLINEITEMRAWDATA', 'I_OPERATIONALACCTGDOCITEM'):
            columns = {f['name'] for f in contract['objects'][n]['fields']}
            pairs = [('TRANSACTIONCURRENCY', 'AMOUNTINTRANSACTIONCURRENCY'), ('COMPANYCODECURRENCY', 'AMOUNTINCOMPANYCODECURRENCY'), ('FUNCTIONALCURRENCY', 'AMOUNTINFUNCTIONALCURRENCY'), ('GLOBALCURRENCY', 'AMOUNTINGLOBALCURRENCY'), ('ADDITIONALCURRENCY1', 'AMOUNTINADDITIONALCURRENCY1')]
            for currency, amount in pairs:
                if not {currency, amount} <= columns:
                    continue
                r = query(wc, f'SELECT COMPANYCODE,FISCALYEAR,ACCOUNTINGDOCUMENT,{ident(currency)} currency,SUM({ident(amount)}) balance,COUNT_BIG(*) line_count,COUNT_BIG({ident(amount)}) nonnull_amounts FROM {db}{ident(n)} WHERE {filt} GROUP BY COMPANYCODE,FISCALYEAR,ACCOUNTINGDOCUMENT,{ident(currency)}', n + '_' + currency)
                invalid = [v for v in r if v['currency'] is None or not isinstance(v['balance'], Decimal) or v['balance'] != Decimal(0) or v['line_count'] != v['nonnull_amounts']]
                report['observations'][n + '_' + currency]['invalid_groups'] = invalid
                balanced = balanced and bool(r) and not invalid
        report['checks']['journal_balance'] = balanced
        after = [query(wc, sql, stage + '_schema_after') for sql, stage in zip(sqls, ('silver', 'gold'))]
        report['checks']['schema_stable'] = schemas == after
        report['data_verified'] = verdict(report['tables'], report['checks'], inventory)
    except Exception as exc:
        report['errors'].append(type(exc).__name__ + ': ' + str(exc))
    finally:
        report['elapsed_seconds'] = time.monotonic() - started
        save()
        for con in connections:
            con.close()
    print(str(out / 'qualification.json'), report['data_verified'], report['checks'], report['errors'], flush=True)
    return report


SCHEMA_KEYS = ('DATA_TYPE', 'CHARACTER_MAXIMUM_LENGTH', 'NUMERIC_PRECISION', 'NUMERIC_SCALE', 'DATETIME_PRECISION', 'IS_NULLABLE')
GATES = {'bridge_pk', 'customer_surrogates', 'orders_both_directions', 'billing_linkage', 'journal_balance', 'job_completed', 'schema_stable'}


def zero_gate(rows, columns):
    return len(rows) == 1 and all(type(rows[0].get(c)) is int and rows[0][c] == 0 for c in columns)


def verdict(tables, checks, inventory):
    return (len(inventory) == 37 and set(tables) == set(inventory)
            and all(t.get('matched') is True for t in tables.values())
            and set(checks) == GATES and all(v is True for v in checks.values()))


def compare(fields, silver_schema, gold_schema, silver, gold, expected_count):
    names = [f['name'] for f in fields]
    errors = []
    schemas = [{r['COLUMN_NAME']: r for r in s} for s in (silver_schema, gold_schema)]
    for n in names:
        if any(n not in s for s in schemas):
            errors.append(n + ': missing schema field')
        elif any(schemas[0][n].get(k) != schemas[1][n].get(k) for k in SCHEMA_KEYS):
            errors.append(n + ': schema mismatch')
    encoded = []
    for stage, rows in (('silver', silver), ('gold', gold)):
        result = []
        for row in rows:
            values = []
            for f in fields:
                n = f['name']
                if n not in row:
                    errors.append(stage + '.' + n + ': missing value')
                    v = None
                else:
                    v = row[n]
                if v is None and (f.get('key') or not f.get('nullable', True)):
                    errors.append(stage + '.' + n + ': forbidden NULL')
                if isinstance(v, Decimal) and not v.is_finite():
                    errors.append(stage + '.' + n + ': nonfinite numeric')
                if type(v) not in (str, int, bool, Decimal, date, datetime, type(None)):
                    errors.append(stage + '.' + n + ': unsupported runtime type')
                payload = v.isoformat() if isinstance(v, (date, datetime)) else str(v) if isinstance(v, Decimal) else v
                values.append((type(v).__name__, payload))
            result.append(json.dumps(values, ensure_ascii=False, separators=(',', ':')))
        encoded.append(Counter(result))
    missing = encoded[0] - encoded[1]
    extra = encoded[1] - encoded[0]
    counts = len(silver) == len(gold) == expected_count
    return {'matched': not errors and counts and not missing and not extra, 'silver_rows': len(silver), 'gold_rows': len(gold), 'expected_rows': expected_count, 'schema_errors': sorted(set(errors)), 'silver_only_rows': sum(missing.values()), 'gold_only_rows': sum(extra.values()), 'silver_only_samples': list(missing.items())[:3], 'gold_only_samples': list(extra.items())[:3], 'silver_sha256': hashlib.sha256(json.dumps(sorted(encoded[0].items()), ensure_ascii=False).encode()).hexdigest(), 'gold_sha256': hashlib.sha256(json.dumps(sorted(encoded[1].items()), ensure_ascii=False).encode()).hexdigest()}
