"""Offline append-only operational finance adapter. No cloud or warehouse I/O."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from calendar import monthrange
from collections import defaultdict
import operator
import ast
import json

from sources.sap import native
from sources.sap.datasphere import digest, json_bytes
from sources.sap.schema import Object

BRIDGE = 'ZMSF_ORDER_LINK'
BILLING = 'C_BILLINGDOCITEMBASICDEX_1'
OP = 'I_OPERATIONALACCTGDOCITEM'
GL = 'I_GLACCOUNTLINEITEMRAWDATA'


def schema_inventory(baseline_schemas):
    """Preserve every baseline field; add only the explicit operational bridge."""
    field = native.NativeField
    bridge = Object(BRIDGE, (
        field('BILLINGDOCUMENT', 'CHAR', 10, key=True),
        field('BILLINGDOCUMENTITEM', 'NUMC', 6, key=True),
        field('CUSTOMER', 'CHAR', 10), field('ORDER_ID', 'CHAR', 128),
        field('ORDER_LINE_NUMBER', 'INT4', 10),
        field('ORIGINAL_BILLINGDOCUMENT', 'CHAR', 10, nullable=True),
        field('ORIGINAL_BILLINGDOCUMENTITEM', 'NUMC', 6, nullable=True),
        field('SIMULATION_ONLY', 'CHAR', 1),
    ), financial=True)
    if BRIDGE in baseline_schemas and baseline_schemas[BRIDGE] != bridge:
        raise ValueError('Existing bridge schema differs')
    return {**baseline_schemas, BRIDGE: bridge}


@dataclass
class Adapted:
    schemas: dict
    additions: dict
    tables: dict
    report: dict


def validate_contract(contract, baseline):
    """Bind validation to the predecessor capture, not a caller's join count."""
    if hasattr(baseline, 'root'):
        raw = (baseline.root / 'contract.json').read_bytes()
        if digest(raw) != baseline.manifest['files'].get('contract.json'):
            raise ValueError('Baseline contract hash differs')
        expected = json.loads(raw)
    elif getattr(baseline, 'native_contract', None) is not None:
        # In-memory scenarios carry their own independently built contract.
        expected = baseline.native_contract.manifest()
    else:
        raise ValueError('Baseline contract evidence is required')
    if not contract.schemas or not contract.objects or not contract.joins or not contract.provenance:
        raise ValueError('Empty active contract')
    if contract.schemas != baseline.schemas:
        raise ValueError('Active contract schemas differ from baseline')
    contract.validate_schema()
    active = contract.manifest()
    def binding(manifest):
        return {key: manifest[key] for key in ('version', 'objects', 'joins', 'provenance', 'compatibility')}
    expected_hash = digest(json_bytes(binding(expected)))
    checked_hash = digest(json_bytes(binding(active)))
    if expected_hash != checked_hash:
        raise ValueError('Active contract inventory/provenance differs from baseline contract')
    return {'expected_sha256': expected_hash, 'checked_sha256': checked_hash,
            'expected_schemas': len(expected['objects']), 'checked_schemas': len(contract.schemas),
            'expected_relationships': len(expected['joins']), 'checked_relationships': len(contract.joins)}


def relationship_report(tables, schemas, joins):
    """Check every supplied relationship, including captured custom joins.

    SQL NULL never equals NULL. Only explicitly unassigned native dimensions
    and the nullable supplier-portfolio product assignment are exempted.
    Unsupported conditions are errors, never silently ignored.
    """
    joins = list(joins)
    issues, statistics, checked = [], [], []
    comparisons = {'==': operator.eq, '>=': operator.ge, '<=': operator.le}
    native_scopes = {(f, d, tuple(tuple(c) for c in conditions))
                     for f, d, conditions, _, _ in native.load_contract().joins}
    for entry in joins:
        if isinstance(entry, dict):
            fact, dim = entry['FactTable'], entry['DimensionTable']
            conditions = entry['JoinCondition']
            conditions = ast.literal_eval(conditions) if isinstance(conditions, str) else conditions
            label = entry.get('RelationshipName', fact + '->' + dim)
        else:
            fact, dim, conditions, _extra, label = entry
        if fact not in schemas or dim not in schemas:
            issues.append({'relationship': label, 'reason': 'undeclared object', 'fact': fact, 'dimension': dim})
            continue
        left = {f.name: f for f in schemas[fact].fields}
        right = {f.name: f for f in schemas[dim].fields}
        if not conditions or any(a not in left or b not in right or op not in comparisons for a, b, op in conditions):
            issues.append({'relationship': label, 'reason': 'unsupported condition', 'fact': fact, 'dimension': dim})
            continue
        equal = [(a, b) for a, b, op in conditions if op == '==']
        index = defaultdict(list)
        def cast(value, field):
            return int(value) if value is not None and field.ddic == 'NUMC' else value
        for row in tables.get(dim, []):
            index[tuple(cast(row[b], right[b]) for a, b in equal)].append(row)
        matched = skipped = missing = ambiguous = 0
        examples = []
        scope = (fact, dim, tuple(tuple(c) for c in conditions))
        optional = native.UNASSIGNED_RELATIONS.get(dim, set()) if scope in native_scopes else set()
        for row in tables.get(fact, []):
            if fact == BRIDGE and dim == BILLING and {a for a, b, op in conditions} == {'ORIGINAL_BILLINGDOCUMENT', 'ORIGINAL_BILLINGDOCUMENTITEM'} and all(row[a] is None for a, b, op in conditions):
                skipped += 1
                continue
            applicable = [a for a, b, op in conditions if a in optional]
            required_customer = dim == 'I_CUSTOMER' and fact in {OP, GL} and row['FINANCIALACCOUNTTYPE'] == 'D'
            if applicable and not required_customer and all(native._unassigned(row[a], left[a]) for a in applicable):
                skipped += 1
                continue
            product_field = {'I_PRODUCT': 'PRODUCT', 'I_PRODUCTGROUP_2': 'PRODUCTGROUP'}.get(dim)
            supplier_kind = {'KR': 'Simulated supplier_invoice', 'KZ': 'Simulated supplier_payment'}
            supplier_accounts = {'KR': {'0051000000': 'S', '0013000000': 'S', '0021000000': 'K'},
                                 'KZ': {'0021000000': 'K', '0011000000': 'S'}}
            doc_type = row.get('ACCOUNTINGDOCUMENTTYPE')
            if (product_field and fact in {OP, GL}
                    and [list(c) for c in conditions] == [[product_field, product_field, '==']]
                    and doc_type in supplier_kind and row.get('DOCUMENTITEMTEXT') == supplier_kind[doc_type]
                    and supplier_accounts[doc_type].get(row.get('GLACCOUNT')) == row.get('FINANCIALACCOUNTTYPE')
                    and row.get('CUSTOMER') == '' and row.get('BILLINGDOCUMENT') == ''
                    and row.get('SUPPLIER') == ('0099000001' if row['FINANCIALACCOUNTTYPE'] == 'K' else '')
                    and row[product_field] is None):
                skipped += 1
                continue
            candidates = index.get(tuple(cast(row[a], left[a]) for a, b in equal), [])
            count = sum(all(row[a] is not None and target[b] is not None and comparisons[op](cast(row[a], left[a]), cast(target[b], right[b]))
                            for a, b, op in conditions) for target in candidates)
            matched += count == 1
            missing += count == 0
            ambiguous += count > 1
            if count != 1 and len(examples) < 3:
                examples.append({k: row[k] for k in schemas[fact].keys})
        stat = {'relationship': label, 'fact': fact, 'dimension': dim, 'matched': matched,
                'unassigned': skipped, 'missing': missing, 'ambiguous': ambiguous}
        statistics.append(stat)
        checked.append(entry)
        if missing or ambiguous:
            issues.append({**stat, 'examples': examples})
    return {'unresolved_relationships': issues, 'relationships': statistics, 'valid': not issues,
            'relationship_coverage': {'expected': len(joins), 'checked': len(checked),
                                      'expected_sha256': digest(json_bytes(joins)),
                                      'checked_sha256': digest(json_bytes(checked))}}


def validate_finance(result, source):
    """Reject incoherent engine cores without repairing the finance engine."""
    def unique(rows, keys, label):
        index = {tuple(r[k] for k in keys): r for r in rows}
        if len(index) != len(rows):
            raise ValueError('Duplicate ' + label)
        return index
    orders = unique(source['orders'], ('order_id', 'line_number'), 'source order')
    billing = unique(result.billing, ('BILLINGDOCUMENT', 'BILLINGDOCUMENTITEM'), 'billing item')
    links = unique(result.line_bridges, ('billing_document',), 'billing bridge')
    if {k[0] for k in billing} != {k[0] for k in links} or len(links) != len(billing):
        raise ValueError('Billing bridge coverage differs')
    cutoff = date.fromisoformat(result.policy['cutoff_date'])
    if result.policy['simulation_only'] is not True or dict(result.policy['companies']) != {'EUR': '1710', 'CAD': '1720', 'CHF': '1730'}:
        raise ValueError('Unsupported operational company policy')
    invoiced = set()
    for key, bill in billing.items():
        link = links[(key[0],)]
        order_key = (link['order_id'], link['line_number'])
        order = orders.get(order_key)
        if order is None or any(link.get(k) != v for k, v in order.items()):
            raise ValueError('Bridge differs from actual source order line')
        customer = f"{10000000 + int(order['customer_key'][5:]):010d}"
        if bill['SOLDTOPARTY'] != customer or bill['PRODUCT'] != order['offer_key'] or bill['TRANSACTIONCURRENCY'] != order['currency']:
            raise ValueError('Billing customer/product/currency differs from source')
        if bill['COMPANYCODE'] != result.policy['companies'][order['currency']] or bill['BILLINGDOCUMENTDATE'] > cutoff:
            raise ValueError('Billing company or cutoff differs')
        original = link['original_billing_document']
        sign = -1 if original else 1
        if bill['GROSSAMOUNT'] != sign * Decimal(order['amount_decimal']) or bill['NETAMOUNT'] + bill['TAXAMOUNT'] != bill['GROSSAMOUNT']:
            raise ValueError('Billing amounts differ from source')
        if original:
            previous = links.get((original,))
            if not previous or previous['original_billing_document'] or (previous['order_id'], previous['line_number']) != order_key:
                raise ValueError('Invalid original credit crosslink')
            old = billing.get((original, key[1]))
            if old is None or any(bill[f] != -old[f] for f in ('NETAMOUNT', 'TAXAMOUNT', 'GROSSAMOUNT')) or bill['BILLINGDOCUMENTTYPE'] != 'G2':
                raise ValueError('Credit does not reverse original')
        else:
            if order_key in invoiced or bill['BILLINGDOCUMENTTYPE'] != 'F2':
                raise ValueError('Duplicate original order invoice')
            invoiced.add(order_key)
    if invoiced != set(orders):
        raise ValueError('Not every actual order was invoiced')
    keys = ('COMPANYCODE', 'FISCALYEAR', 'ACCOUNTINGDOCUMENT', 'ACCOUNTINGDOCUMENTITEM')
    op = unique(result.journal, keys, 'journal key')
    gl = unique(result.gl, keys, 'GL key')
    if set(op) != set(gl) or any(any(gl[k].get(f) != v for f, v in row.items()) or
            gl[k]['SOURCELEDGER'] != '0L' or gl[k]['LEDGERGLLINEITEM'] != row['ACCOUNTINGDOCUMENTITEM'].zfill(6)
            for k, row in op.items()):
        raise ValueError('GL differs from operational journal')
    # Explicit operational account roles; master existence alone proves no role.
    account_types = {account: 'S' for account in (
        '0011000000', '0013000000', '0022000000', '0050000000',
        '0023100000', '0023200000', '0041000000', '0042000000')}
    account_types.update({'0012000000': 'D', '0021000000': 'K'})
    posting_roles = {'01': ('D', 'S'), '11': ('D', 'H'), '15': ('D', 'H'),
                     '21': ('K', 'S'), '25': ('K', 'S'), '31': ('K', 'H'),
                     '40': ('S', 'S'), '50': ('S', 'H')}
    docs = defaultdict(list)
    for row in result.journal:
        account_type = row['FINANCIALACCOUNTTYPE']
        # The engine emits zero-valued legs as credits; preserve that convention.
        side = 'S' if row['AMOUNTINTRANSACTIONCURRENCY'] > 0 else 'H'
        if (account_types.get(row['GLACCOUNT']) != account_type
                or row['DEBITCREDITCODE'] != side
                or posting_roles.get(row['POSTINGKEY']) != (account_type, side)):
            raise ValueError('Inconsistent signed posting role')
        docs[(row['COMPANYCODE'], row['FISCALYEAR'], row['ACCOUNTINGDOCUMENT'])].append(row)
        if row['POSTINGDATE'] > cutoff or row['DOCUMENTDATE'] > cutoff:
            raise ValueError('Business date exceeds cutoff')
        if row['COMPANYCODE'] != result.policy['companies'][row['TRANSACTIONCURRENCY']] or row['COMPANYCODECURRENCY'] != row['TRANSACTIONCURRENCY']:
            raise ValueError('Journal company currency differs')
        if row['AMOUNTINTRANSACTIONCURRENCY'] != row['AMOUNTINCOMPANYCODECURRENCY']:
            raise ValueError('Unapproved currency conversion')
    for rows in docs.values():
        if sum(r['AMOUNTINTRANSACTIONCURRENCY'] for r in rows) != 0:
            raise ValueError('Unbalanced accounting document')
    for bill in result.billing:
        rows = docs.get((bill['COMPANYCODE'], bill['FISCALYEAR'], bill['ACCOUNTINGDOCUMENT']), [])
        ar = [r for r in rows if r['FINANCIALACCOUNTTYPE'] == 'D']
        if len(ar) != 1 or ar[0]['CUSTOMER'] != bill['SOLDTOPARTY'] or ar[0]['AMOUNTINTRANSACTIONCURRENCY'] != bill['GROSSAMOUNT'] or ar[0]['BILLINGDOCUMENT'] != bill['BILLINGDOCUMENT']:
            raise ValueError('Billing does not reconcile to receivable')
        original = links[(bill['BILLINGDOCUMENT'],)]['original_billing_document']
        if original and ar[0]['INVOICEREFERENCE'] != billing[(original, bill['BILLINGDOCUMENTITEM'])]['ACCOUNTINGDOCUMENT']:
            raise ValueError('Credit accounting crosslink differs from original invoice')
    for clearing in result.clearings:
        members = [r for r in result.journal if r['COMPANYCODE'] == clearing['company'] and
                   r['ACCOUNTINGDOCUMENT'] in clearing['documents'] and r['FINANCIALACCOUNTTYPE'] == clearing['account_type']]
        if len(members) != len(clearing['documents']) or sum(r['AMOUNTINTRANSACTIONCURRENCY'] for r in members) != 0 or len({r['CUSTOMER'] for r in members}) != 1:
            raise ValueError('Clearing members do not reconcile')
        if any(r['CLEARINGACCOUNTINGDOCUMENT'] != clearing['document'] or r['CLEARINGDATE'] != clearing['date'] or r['CLEARINGDOCFISCALYEAR'] != str(clearing['date'].year) for r in members):
            raise ValueError('Clearing document/date differs')
    payments = unique(result.payments, ('company', 'document'), 'payment')
    for payment in payments.values():
        rows = [r for k, entries in docs.items() if k[0] == payment['company'] and k[2] == payment['document'] for r in entries]
        bank = [r for r in rows if r['GLACCOUNT'] == '0011000000']
        acct = payment.get('account_type', 'D')
        counterpart = [r for r in rows if r['FINANCIALACCOUNTTYPE'] == acct]
        if len(bank) != 1 or bank[0]['AMOUNTINTRANSACTIONCURRENCY'] != payment['gross'] or len(counterpart) != 1 or counterpart[0]['AMOUNTINTRANSACTIONCURRENCY'] != -payment['gross'] or counterpart[0]['INVOICEREFERENCE'] != payment['invoice_document']:
            raise ValueError('Payment does not reconcile to bank and open item')
        if acct == 'D' and any(r['CLEARINGACCOUNTINGDOCUMENT'] != payment['document'] for r in counterpart):
            raise ValueError('Customer payment clearing differs')
    expected = {(r['COMPANYCODE'], r['ACCOUNTINGDOCUMENT']) for r in result.journal if r['GLACCOUNT'] == '0011000000'}
    if set(payments) != expected:
        raise ValueError('Payment coverage differs')


def adapt(result, source, references, baseline, *, contract=None, extra_relationships=()):
    """FinanceResult + captured orders/CRM -> native_delta schema/additions.

    No baseline row is overwritten. Identity conflicts raise ValueError. Native
    relationship failures are returned in report (valid=False); callers MUST
    gate publication on that report. Extraction time is intentionally not a
    business input. New accounting labels are explicit demo policy, not claims
    about real distributor contracts or exchange rates.
    """
    validate_finance(result, source)
    contract = contract or native.load_contract()
    contract_binding = validate_contract(contract, baseline)
    schemas = schema_inventory(baseline.schemas)
    indexes = {n: o.index(deepcopy(baseline.tables.get(n, []))) for n, o in schemas.items()}
    additions = defaultdict(list)

    def add(name, **values):
        obj = schemas[name]
        row = native._complete(obj, values)
        key = tuple(row[k] for k in obj.keys)
        if key in indexes[name]:
            # Compare only explicit claims; never relabel existing rows.
            if any(indexes[name][key][k] != v for k, v in values.items()):
                raise ValueError(f'{name}: conflicting existing key {key}')
            return indexes[name][key]
        indexes[name][key] = row
        additions[name].append(row)
        return row

    def text(name, keys, label):
        for language in ('E', 'F'):
            values = {**keys, 'LANGUAGE': language}
            for f in schemas[name].fields:
                if not f.key and (f.name.endswith('NAME') or f.name in {'PRODUCTDESCRIPTION', 'HIERARCHYNODETEXT'}):
                    values[f.name] = label[:f.length]
            add(name, **values)

    def simple(name, text_name, key, value, label):
        add(name, **{key: value})
        text(text_name, {key: value}, label)

    crm = references['queries']['crm_customers']['rows']
    crm_by_key = {r['customer_key']: r for r in crm}
    if len(crm_by_key) != len(crm):
        raise ValueError('Duplicate CRM customer key')
    # Reconcile actual orders first; optional/forged link rows cannot hide drift.
    for order in source['orders']:
        ref = crm_by_key.get(order['customer_key'])
        if not ref or not ref['source_customer_id'] or ref['source_customer_id'] != order['salesforce_contact_id']:
            raise ValueError('Missing or inconsistent actual CRM identity')
    links_by_key = {r['CUSTOMER_KEY']: r for r in result.customer_links}
    if (len(links_by_key) != len(result.customer_links)
            or set(links_by_key) != {r['customer_key'] for r in source['orders']}):
        raise ValueError('Duplicate or incomplete customer link coverage')
    for link in result.customer_links:
        ref = crm_by_key.get(link['CUSTOMER_KEY'])
        if not ref or not ref['source_customer_id'] or ref['source_customer_id'] != link['SALESFORCE_CONTACT_ID']:
            raise ValueError('Missing or inconsistent actual CRM identity')
        if link['CUSTOMER'] != f"{10000000 + int(link['CUSTOMER_KEY'][5:]):010d}":
            raise ValueError('Inconsistent customer link identity')
    # Include captured actual CRM population, never invent Salesforce IDs.
    import re
    for ref in crm:
        if not re.fullmatch(r'MSF-C[0-9]{4}', ref['customer_key']):
            raise ValueError('Invalid literal CRM customer key')
        customer = f"{10000000 + int(ref['customer_key'][5:]):010d}"
        if not ref['source_customer_id']:
            raise ValueError('Missing actual Salesforce identifier')
        add('I_CUSTOMER', CUSTOMER=customer, CUSTOMERNAME=ref['name'],
            CUSTOMERFULLNAME=ref['name'], COUNTRY=ref['territory'])
        add('ZMSF_CUSTOMER_LINK', CUSTOMER=customer, CUSTOMER_KEY=ref['customer_key'],
            SALESFORCE_CONTACT_ID=ref['source_customer_id'])
    simple('I_BUSINESSAREA', 'I_BUSINESSAREATEXT', 'BUSINESSAREA', 'ZOPS', 'Demo operational orders')
    simple('I_FUNCTIONALAREA', 'I_FUNCTIONALAREATEXT', 'FUNCTIONALAREA', 'ZORDER', 'Demo operational orders')
    simple('I_SEGMENT', 'I_SEGMENTTEXT', 'SEGMENT', 'ZORDER', 'Demo operational orders')
    simple('I_CUSTOMERGROUP', 'I_CUSTOMERGROUPTEXT', 'CUSTOMERGROUP', 'ZO', 'Operational order customers')
    simple('I_DIVISION', 'I_DIVISIONTEXT', 'DIVISION', 'ZO', 'Operational digital offers')
    for usage in sorted({r['usage_type'] for r in source['orders']}):
        simple('I_PRODUCTGROUP_2', 'I_PRODUCTGROUPTEXT_2', 'PRODUCTGROUP', usage, usage + ' digital offers')
    offers = {}
    for order in source['orders']:
        product, usage = order['offer_key'], order['usage_type']
        if product in offers and offers[product] != usage:
            raise ValueError('Conflicting offer usage')
        offers[product] = usage
        add('I_PRODUCT', PRODUCT=product, PRODUCTTYPE='SERV', PRODUCTGROUP=usage, BASEUNIT='EA')
        text('I_PRODUCTDESCRIPTION', {'PRODUCT': product}, product)
    for code, category, label in [('ZF2', 'M', 'Demo operational invoice'), ('ZG2', 'O', 'Demo operational credit')]:
        add('I_BILLINGDOCUMENTTYPE', BILLINGDOCUMENTTYPE=code, BILLINGDOCUMENTCATEGORY=category, SDDOCUMENTCATEGORY=category)
        text('I_BILLINGDOCUMENTTYPETEXT', {'BILLINGDOCUMENTTYPE': code}, label)
    companies = {}
    low, high = date(2026, 1, 1), date(9999, 12, 31)
    for currency, company, country in [('EUR', '1710', 'FR'), ('CAD', '1720', 'CA'), ('CHF', '1730', 'CH')]:
        if currency not in result.totals:
            continue
        existing = indexes['I_COMPANYCODE'].get((company,))
        area = existing['CONTROLLINGAREA'] if existing else {'CAD': 'ZCAD', 'CHF': 'ZCHF', 'EUR': 'ZEUR'}[currency]
        if existing:
            if existing['CURRENCY'] != currency or existing['CHARTOFACCOUNTS'] != 'MSFX' or existing['FISCALYEARVARIANT'] != 'K4':
                raise ValueError('Existing company currency/chart/calendar conflicts')
            companies[company] = existing
        else:
            companies[company] = add('I_COMPANYCODE', COMPANYCODE=company, COMPANY=company,
                COMPANYCODENAME='Demo operational ' + currency, CURRENCY=currency, COUNTRY=country,
                CHARTOFACCOUNTS='MSFX', FISCALYEARVARIANT='K4', CONTROLLINGAREA=area, LANGUAGE='E')
            add('I_GLOBALCOMPANY', COMPANY=company, COMPANYNAME='Demo operational ' + currency,
                CURRENCY=currency, COUNTRY=country, LANGUAGE='E')
        control = indexes['I_CONTROLLINGAREA'].get((area,))
        if control:
            if control['CONTROLLINGAREACURRENCY'] != currency:
                raise ValueError('Currency conversion is not approved')
        else:
            add('I_CONTROLLINGAREA', CONTROLLINGAREA=area, CONTROLLINGAREANAME='Demo operational ' + currency,
                CONTROLLINGAREACURRENCY=currency, CONTROLLINGAREACURRENCYROLE='20', CHARTOFACCOUNTS='MSFX', FISCALYEARVARIANT='K4')
        dimkeys = {'CONTROLLINGAREA': area, 'VALIDITYENDDATE': high}
        add('I_COSTCENTER', **dimkeys, COSTCENTER='ZORDER', VALIDITYSTARTDATE=low, COMPANYCODE=company,
            BUSINESSAREA='ZOPS', FUNCTIONALAREA='ZORDER', PROFITCENTER='ZORDER', COSTCENTERCURRENCY=currency,
            COSTCENTERCATEGORY='W', COUNTRY=country, LANGUAGE='E')
        text('I_COSTCENTERTEXT', {**dimkeys, 'COSTCENTER': 'ZORDER'}, 'Demo order operations')
        add('I_PROFITCENTER', **dimkeys, PROFITCENTER='ZORDER', VALIDITYSTARTDATE=low,
            COMPANYCODE=company, COUNTRY=country, SEGMENT='ZORDER', LANGUAGE='E')
        text('I_PROFITCENTERTEXT', {**dimkeys, 'PROFITCENTER': 'ZORDER'}, 'Demo order portfolio')
        sales = 'Z' + company[-3:]
        add('I_SALESORGANIZATION', SALESORGANIZATION=sales, COMPANYCODE=company, SALESORGANIZATIONCURRENCY=currency)
        text('I_SALESORGANIZATIONTEXT', {'SALESORGANIZATION': sales}, 'Demo operational ' + currency)
        add('I_DUNNINGAREA', COMPANYCODE=company, DUNNINGAREA='')
        if not existing:
            text('I_DUNNINGAREATEXT', {'COMPANYCODE': company, 'DUNNINGAREA': ''}, 'No separate dunning area')
    for year in sorted({r['POSTINGDATE'].year for r in result.journal}):
        for company in companies:
            add('I_FISCALYEARFORCOMPANYCODE', COMPANYCODE=company, FISCALYEAR=str(year),
                FISCALYEARSTARTDATE=date(year, 1, 1), FISCALYEARENDDATE=date(year, 12, 31))
        for month in range(1, 13):
            add('I_FISCALPERIODFORVARIANT', FISCALYEAR=str(year), FISCALPERIOD=f'{month:03d}', FISCALYEARVARIANT='K4',
                FISCALPERIODSTARTDATE=date(year, month, 1), FISCALPERIODENDDATE=date(year, month, monthrange(year, month)[1]),
                FISCALYEARSTARTDATE=date(year, 1, 1), FISCALYEARENDDATE=date(year, 12, 31),
                FISCALYEARPERIOD=f'{year}{month:03d}', ISSPECIALPERIOD='', NEXTFISCALPERIOD=f'{month % 12 + 1:03d}',
                NEXTFISCALPERIODFISCALYEAR=str(year + (month == 12)))
    labels = {'0023100000': 'Deferred TVOD orders', '0023200000': 'Deferred EST orders',
              '0041000000': 'TVOD order revenue', '0042000000': 'EST order revenue',
              '0051000000': 'Demo operational content cost'}
    for account in sorted({r['GLACCOUNT'] for r in result.journal}):
        account = '0051000000' if account == '0050000000' else account
        kind = 'P' if account.startswith(('004', '005')) else 'X'
        existing_account = indexes['I_GLACCOUNTINCHARTOFACCOUNTS'].get(('MSFX', account))
        if existing_account is not None:
            classification = {'GLACCOUNTTYPE': kind,
                              'ISBALANCESHEETACCOUNT': 'X' if kind == 'X' else '',
                              'ISPROFITLOSSACCOUNT': 'X' if kind == 'P' else ''}
            if any(existing_account[field] != value for field, value in classification.items()):
                raise ValueError(f'Existing account classification conflicts: {account}')
            continue
        add('I_GLACCOUNTINCHARTOFACCOUNTS', CHARTOFACCOUNTS='MSFX', GLACCOUNT=account,
            GLACCOUNTTYPE=kind, GLACCOUNTGROUP='PL' if kind == 'P' else 'BS',
            ISBALANCESHEETACCOUNT='X' if kind == 'X' else '', ISPROFITLOSSACCOUNT='X' if kind == 'P' else '')
        text('I_GLACCOUNTTEXT', {'CHARTOFACCOUNTS': 'MSFX', 'GLACCOUNT': account}, labels[account])
    if any(r['SUPPLIER'] for r in result.journal):
        add('I_SUPPLIER', SUPPLIER='0099000001', COUNTRY='',
            SUPPLIERNAME='Demo operational supplier (synthetic)', SUPPLIERFULLNAME='Demo operational supplier (synthetic)')
    bridges = {r['billing_document']: r for r in result.line_bridges}
    for original in result.billing:
        row = dict(original)
        link = bridges[row['BILLINGDOCUMENT']]
        customer, company, currency = row['SOLDTOPARTY'], row['COMPANYCODE'], row['TRANSACTIONCURRENCY']
        row.update(BILLINGDOCUMENTTYPE={'F2': 'ZF2', 'G2': 'ZG2'}[row['BILLINGDOCUMENTTYPE']],
            BASEUNIT='EA', BILLINGQUANTITYUNIT='EA', BILLINGQUANTITY=Decimal('1.000'),
            BILLINGQUANTITYINBASEUNIT=Decimal('1.000'), BILLTOPARTY=customer, PAYERPARTY=customer, SHIPTOPARTY=customer,
            BUSINESSAREA='ZOPS', CONTROLLINGAREA=companies[company]['CONTROLLINGAREA'], COSTCENTER='ZORDER', PROFITCENTER='ZORDER',
            CUSTOMERGROUP='ZO', DISTRIBUTIONCHANNEL='01', DIVISION='ZO', FISCALYEARVARIANT='K4',
            FISCALPERIOD=f"{row['BILLINGDOCUMENTDATE'].month:03d}", PRODUCTGROUP=link['usage_type'],
            OVERALLBILLINGSTATUS='C', SALESORGANIZATION='Z' + company[-3:], SALESORGANIZATIONCURRENCY=currency,
            CURRENCY=currency, BILLINGDOCUMENTITEMTEXT='Demo operational ' + link['usage_type'])
        add(BILLING, **row)
        add(BRIDGE, BILLINGDOCUMENT=row['BILLINGDOCUMENT'], BILLINGDOCUMENTITEM=row['BILLINGDOCUMENTITEM'],
            CUSTOMER=customer, ORDER_ID=link['order_id'], ORDER_LINE_NUMBER=link['line_number'],
            ORIGINAL_BILLINGDOCUMENT=link['original_billing_document'],
            ORIGINAL_BILLINGDOCUMENTITEM='000001' if link['original_billing_document'] else None, SIMULATION_ONLY='X')
    for name, originals in [(OP, result.journal), (GL, result.gl)]:
        for original in originals:
            row = dict(original)
            company, currency = row['COMPANYCODE'], row['TRANSACTIONCURRENCY']
            link = bridges.get(row['BILLINGDOCUMENT'])
            row.update(BUSINESSAREA='ZOPS', CONTROLLINGAREA=companies[company]['CONTROLLINGAREA'],
                COSTCENTER='ZORDER', PROFITCENTER='ZORDER', FUNCTIONALAREA='ZORDER', SEGMENT='ZORDER',
                COMPANY=companies[company]['COMPANY'], CUSTOMERGROUP='ZO',
                PRODUCT=link['offer_key'] if link else None, PRODUCTGROUP=link['usage_type'] if link else None,
                FISCALYEARPERIOD=row['FISCALYEAR'] + row['FISCALPERIOD'], LEDGERFISCALYEAR=row['FISCALYEAR'],
                GLOBALCURRENCY=currency, AMOUNTINGLOBALCURRENCY=row['AMOUNTINTRANSACTIONCURRENCY'],
                ISOPENITEMMANAGED='X' if row['FINANCIALACCOUNTTYPE'] in {'D', 'K'} else '')
            for code, amount in native.CURRENCIES.values():
                row[code], row[amount] = currency, row['AMOUNTINTRANSACTIONCURRENCY']
            if row['GLACCOUNT'] == '0050000000':
                row['GLACCOUNT'] = '0051000000'
            add(name, **row)
    tables = {n: list(index.values()) for n, index in indexes.items()}
    bridge_joins = [
        [BRIDGE, BILLING, [['BILLINGDOCUMENT', 'BILLINGDOCUMENT', '=='], ['BILLINGDOCUMENTITEM', 'BILLINGDOCUMENTITEM', '==']], [], 'order_billing'],
        [BRIDGE, 'I_CUSTOMER', [['CUSTOMER', 'CUSTOMER', '==']], [], 'order_customer'],
        [BRIDGE, BILLING, [['ORIGINAL_BILLINGDOCUMENT', 'BILLINGDOCUMENT', '=='], ['ORIGINAL_BILLINGDOCUMENTITEM', 'BILLINGDOCUMENTITEM', '==']], [], 'order_original_billing'],
    ]
    report = relationship_report(tables, schemas, [*contract.joins, *extra_relationships, *bridge_joins])
    report.update(simulation_only=True, network_operations=0, native_bps_ready=False,
                  contract_binding=contract_binding,
                  finance_validated=True, excluded_global_relationships=deepcopy(contract.excluded_relationships),
                  requires_bps_ui_registration=[BRIDGE], source_order_lines=len(source['orders']))
    return Adapted(schemas, dict(additions), tables, report)
