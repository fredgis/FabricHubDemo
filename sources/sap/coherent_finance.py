"""Pure operational-order finance simulation; no files, cloud calls, or subscriptions.

``build(snapshot, demo_policy(...))`` returns immutable rows with Decimal money and
Python dates. Journal/billing rows are source business cores, NOT completed native
BPS inputs. The caller owns native.load_contract / native._complete, master data,
custom order-link registration, serialization, and append-only publication.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext
from hashlib import sha256
import json
from types import MappingProxyType
from collections.abc import Mapping

from sources.sap.schema import SCHEMAS

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
CONTEXT = Context(prec=64, rounding=ROUND_HALF_UP)
ACCOUNTS = MappingProxyType({
    "bank": "0011000000", "receivables": "0012000000", "input_vat": "0013000000",
    "payables": "0021000000", "output_vat": "0022000000", "content_cost": "0050000000",
    "deferred_TVOD": "0023100000", "deferred_EST": "0023200000",
    "revenue_TVOD": "0041000000", "revenue_EST": "0042000000",
})


def demo_policy(*, refunded_per_currency=1, unpaid_per_currency=1):
    """Explicit illustrative defaults, not assertions about real collections/tax."""
    return {
        "scenario_id": "msflix-operational-finance-v1", "simulation_only": True,
        "source_system": "S4M", "cutoff_date": "2026-10-11", "fiscal_year": 2026,
        "companies": {"EUR": "1710", "CAD": "1720", "CHF": "1730"},
        "tax_rate": "0.20", "price_basis": "gross", "rounding": "ROUND_HALF_UP",
        "refunded_per_currency": refunded_per_currency, "unpaid_per_currency": unpaid_per_currency,
        "supplier_share_rate": "0.20", "supplier_fixed_net": "0.00",
        "supplier_payment_fraction": "0.50",
    }


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(v) for v in value)
    return value


@dataclass(frozen=True)
class FinanceResult:
    documents: tuple
    journal: tuple
    gl: tuple
    billing: tuple
    payments: tuple
    clearings: tuple
    line_bridges: tuple
    customer_links: tuple
    totals: Mapping
    policy: Mapping


def _identifier(namespace, key):
    return namespace + f"{int(sha256(key.encode()).hexdigest(), 16) % 1_000_000_000:09d}"


def _post(documents, journal, *, document, kind, day, company, currency, billing,
          customer, entries, reference="", supplier=""):
    if any(row['document'] == document for row in documents):
        raise ValueError('Accounting document identifier collision')
    if sum((value for _, value in entries), ZERO) != ZERO:
        raise ValueError("Unbalanced document")
    documents.append({"document": document, "kind": kind, "posting_date": day,
                      "company": company, "currency": currency, "simulation_only": True})
    for index, (role, value) in enumerate(entries, 1):
        account_type = {"receivables": "D", "payables": "K"}.get(role, "S")
        debit = value > ZERO
        journal.append({
            "COMPANYCODE": company, "FISCALYEAR": str(day.year), "ACCOUNTINGDOCUMENT": document,
            "ACCOUNTINGDOCUMENTITEM": f"{index:03d}",
            "ACCOUNTINGDOCUMENTTYPE": {"invoice": "DR", "recognition": "SA", "cash": "DZ",
                                       "credit": "DG", "refund": "DZ",
                                       "supplier_invoice": "KR", "supplier_payment": "KZ"}[kind],
            "POSTINGDATE": day, "DOCUMENTDATE": day, "FISCALPERIOD": f"{day.month:03d}",
            "FISCALYEARVARIANT": "K4", "CHARTOFACCOUNTS": "MSFX", "GLACCOUNT": ACCOUNTS[role],
            "FINANCIALACCOUNTTYPE": account_type, "DEBITCREDITCODE": "S" if debit else "H",
            "POSTINGKEY": ("01" if debit else "15" if kind == "cash" else "11") if account_type == "D" else (("25" if debit else "31") if account_type == "K" else ("40" if debit else "50")),
            "TRANSACTIONCURRENCY": currency, "AMOUNTINTRANSACTIONCURRENCY": value,
            "COMPANYCODECURRENCY": currency, "AMOUNTINCOMPANYCODECURRENCY": value,
            "CUSTOMER": customer if account_type == "D" else "", "SUPPLIER": supplier if account_type == "K" else "",
            "DOCUMENTITEMTEXT": "Simulated " + kind, "BILLINGDOCUMENT": billing,
            "CLEARINGACCOUNTINGDOCUMENT": None, "CLEARINGDOCFISCALYEAR": None, "CLEARINGDATE": None,
            "NETDUEDATE": day if account_type in {"D", "K"} else None,
            "INVOICEREFERENCE": reference, "INVOICEREFERENCEFISCALYEAR": str(day.year) if reference else "",
            "INVOICEITEMREFERENCE": "001" if reference else "",
        })


def _exact(value):
    if not isinstance(value, (str, Decimal, int)) or isinstance(value, bool):
        raise ValueError('Exact decimal required')
    try:
        result = Decimal(value)
    except Exception as exc:
        raise ValueError('Invalid decimal') from exc
    if not result.is_finite():
        raise ValueError('Finite decimal required')
    return result


def _utc(value):
    """Interpret naive source timestamps as UTC; normalize offsets before use."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _validate(snapshot, policy):
    import re
    cutoff = date.fromisoformat(policy['cutoff_date'])
    if (policy.get('rounding') != ROUND_HALF_UP or policy.get('source_system') != 'S4M'
            or type(policy.get('fiscal_year')) is not int or policy['fiscal_year'] != 2026
            or cutoff.year != policy['fiscal_year']):
        raise ValueError('Only ROUND_HALF_UP S4M fiscal year 2026 policy is supported')
    if policy.get('simulation_only') is not True or policy.get('price_basis') != 'gross':
        raise ValueError('Only explicitly simulated gross-price policy is supported')
    for field in ('tax_rate', 'supplier_share_rate', 'supplier_payment_fraction'):
        if not ZERO <= _exact(policy[field]) <= Decimal(1):
            raise ValueError('Invalid rate: ' + field)
    if _exact(policy['supplier_fixed_net']) != ZERO:
        raise ValueError('Fixed supplier fees are not supported')
    for field in ('unpaid_per_currency', 'refunded_per_currency'):
        if type(policy[field]) is not int or policy[field] < 0:
            raise ValueError('Invalid selection count')
    seen = set()
    for row in snapshot['orders']:
        for field, length in (('order_id', 128), ('customer_key', 40), ('offer_key', 40),
                              ('content_key', 128), ('source_event_id', 128)):
            if not isinstance(row.get(field), str) or not row[field] or len(row[field]) > length:
                raise ValueError('Invalid literal identifier: ' + field)
        if not re.fullmatch(r'MSF-C[0-9]{4}', row['customer_key']):
            raise ValueError('Invalid customer key')
        if type(row['line_number']) is not int or not 0 < row['line_number'] <= 2147483647:
            raise ValueError('Invalid order line number')
        key = row['order_id'], row['line_number']
        if key in seen:
            raise ValueError('Duplicate order line')
        seen.add(key)
        if row['currency'] not in policy['companies'] or row['usage_type'] not in ('TVOD', 'EST'):
            raise ValueError('Unsupported currency or commercial type')
        gross = _exact(row['amount_decimal'])
        if (gross <= ZERO or gross != gross.quantize(CENT) or type(row['amount_minor']) is not int
                or gross * 100 != row['amount_minor']):
            raise ValueError('Invalid or inconsistent amount')
        ordered = _utc(row['ordered_at_utc'])
        first_play = (_utc(row['first_play_at_utc'])
                      if row.get('first_play_at_utc') else None)
        if ordered.year != policy['fiscal_year'] or (first_play and first_play.year != policy['fiscal_year']):
            raise ValueError('Source business dates must be in the approved fiscal year')
        if ordered.date() > cutoff:
            raise ValueError('Order after financial cutoff')
        if first_play and first_play < ordered:
            raise ValueError('Playback before order')


def build(snapshot, policy):
    """Build an immutable financial ledger from the supplied fixed snapshot."""
    with localcontext(CONTEXT):
        _validate(snapshot, policy)
        documents, journal, billing, bridges, customers, totals = [], [], [], [], {}, {}
        payments, clearings = [], []
        cutoff = date.fromisoformat(policy["cutoff_date"])
        ordered = sorted(snapshot['orders'], key=lambda r: (r['order_id'], r['line_number']))
        unpaid, refunded = set(), set()
        for currency in sorted({r['currency'] for r in ordered}):
            candidates = [r for r in ordered if r['currency'] == currency]
            unpaid.update((r['order_id'], r['line_number'])
                          for r in candidates[:policy['unpaid_per_currency']])
            start = policy['unpaid_per_currency']
            refunded.update((r['order_id'], r['line_number']) for r in
                            candidates[start:start + policy['refunded_per_currency']])
        selections = {'selected_unpaid_order_lines': sorted(unpaid),
                      'selected_refunded_order_lines': sorted(refunded)}
        for field, selected in selections.items():
            if field in policy:
                supplied = policy[field]
                if (not isinstance(supplied, (list, tuple))
                        or any(not isinstance(key, (list, tuple)) or len(key) != 2
                               or not isinstance(key[0], str) or type(key[1]) is not int
                               for key in supplied)
                        or [tuple(key) for key in supplied] != selected):
                    raise ValueError('Selection mismatch: ' + field)
        policy = {**policy, **selections}
        for row in ordered:
            currency = row["currency"]
            company = policy["companies"][currency]
            key = json.dumps([policy["scenario_id"], company, row["order_id"], row["line_number"]])
            document, bill = _identifier("8", key + "invoice"), _identifier("7", key + "invoice")
            gross = Decimal(row["amount_decimal"])
            net = (gross / (Decimal(1) + Decimal(policy["tax_rate"]))).quantize(CENT)
            tax = gross - net
            day = _utc(row["ordered_at_utc"]).date()
            customer = f"{10000000 + int(row['customer_key'][5:]):010d}"
            customers[customer] = {"CUSTOMER": customer, "CUSTOMER_KEY": row["customer_key"],
                                   "SALESFORCE_CONTACT_ID": row.get("salesforce_contact_id", "")}
            _post(documents, journal, document=document, kind="invoice", day=day, company=company,
                  currency=currency, billing=bill, customer=customer,
                  entries=[("receivables", gross), ("deferred_" + row["usage_type"], -net), ("output_vat", -tax)])
            billing.append({
                "BILLINGDOCUMENT": bill, "BILLINGDOCUMENTITEM": "000001", "BILLINGDOCUMENTTYPE": "F2",
                "BILLINGDOCUMENTCATEGORY": "M", "BILLINGDOCUMENTDATE": day, "COMPANYCODE": company,
                "FISCALYEAR": str(day.year), "ACCOUNTINGDOCUMENT": document, "SOLDTOPARTY": customer,
                "PRODUCT": row["offer_key"], "TRANSACTIONCURRENCY": currency,
                "NETAMOUNT": net, "TAXAMOUNT": tax, "GROSSAMOUNT": gross,
            })
            bridges.append({**row, "billing_document": bill, "accounting_document": document,
                            "original_billing_document": None})
            current = totals.setdefault(currency, {"deferred_net": ZERO, "recognized_net": ZERO,
                                                   "receivables": ZERO, "customer_cash_net": ZERO})
            current["deferred_net"] += net
            first_play = _utc(row['first_play_at_utc']) if row.get('first_play_at_utc') else None
            if first_play and first_play.date() <= cutoff:
                _post(documents, journal, document=_identifier("8", key + "recognition"),
                      kind="recognition", day=first_play.date(), company=company,
                      currency=currency, billing=bill, customer=customer, reference=document,
                      entries=[("deferred_" + row["usage_type"], net), ("revenue_" + row["usage_type"], -net)])
                current["deferred_net"] -= net
                current["recognized_net"] += net
            if (row['order_id'], row['line_number']) in unpaid:
                current['receivables'] += gross
                continue
            cash = _identifier("8", key + "cash")
            _post(documents, journal, document=cash, kind="cash", day=cutoff, company=company,
                  currency=currency, billing=bill, customer=customer, reference=document,
                  entries=[("receivables", -gross), ("bank", gross)])
            current["customer_cash_net"] += gross
            payments.append({"document": cash, "invoice_document": document, "gross": gross,
                             "currency": currency, "company": company, "simulation_only": True})
            clearings.append({"document": cash, "documents": (document, cash), "date": cutoff,
                              "currency": currency, "company": company, "account_type": "D"})
            for item in journal:
                if item["ACCOUNTINGDOCUMENT"] in {document, cash} and item["FINANCIALACCOUNTTYPE"] == "D":
                    item.update(CLEARINGACCOUNTINGDOCUMENT=cash, CLEARINGDOCFISCALYEAR=str(cutoff.year),
                                CLEARINGDATE=cutoff)
            if (row['order_id'], row['line_number']) in refunded:
                credit = _identifier("8", key + "credit")
                credit_bill = _identifier("7", key + "credit")
                refund = _identifier("8", key + "refund")
                recognized = bool(first_play and first_play.date() <= cutoff)
                role = ("revenue_" if recognized else "deferred_") + row['usage_type']
                _post(documents, journal, document=credit, kind="credit", day=cutoff,
                      company=company, currency=currency, billing=credit_bill, customer=customer,
                      reference=document, entries=[("receivables", -gross), (role, net), ("output_vat", tax)])
                original = next(b for b in billing if b['BILLINGDOCUMENT'] == bill)
                billing.append({**original, 'BILLINGDOCUMENT': credit_bill,
                                'BILLINGDOCUMENTTYPE': 'G2', 'BILLINGDOCUMENTCATEGORY': 'O',
                                'BILLINGDOCUMENTDATE': cutoff, 'ACCOUNTINGDOCUMENT': credit,
                                'NETAMOUNT': -net, 'TAXAMOUNT': -tax, 'GROSSAMOUNT': -gross})
                bridges.append({**row, 'billing_document': credit_bill, 'accounting_document': credit,
                                'original_billing_document': bill})
                _post(documents, journal, document=refund, kind="refund", day=cutoff,
                      company=company, currency=currency, billing=credit_bill, customer=customer,
                      reference=credit, entries=[("receivables", gross), ("bank", -gross)])
                payments.append({'document': refund, 'invoice_document': credit, 'gross': -gross,
                                 'currency': currency, 'company': company, 'simulation_only': True})
                clearings.append({'document': refund, 'documents': (credit, refund), 'date': cutoff,
                                  'currency': currency, 'company': company, 'account_type': 'D'})
                for item in journal:
                    if item['ACCOUNTINGDOCUMENT'] in {credit, refund} and item['FINANCIALACCOUNTTYPE'] == 'D':
                        item.update(CLEARINGACCOUNTINGDOCUMENT=refund, CLEARINGDOCFISCALYEAR=str(cutoff.year),
                                    CLEARINGDATE=cutoff)
                current['recognized_net' if recognized else 'deferred_net'] -= net
                current['customer_cash_net'] -= gross
        for currency, current in sorted(totals.items()):
            company = policy['companies'][currency]
            cost = (current['recognized_net'] * Decimal(policy['supplier_share_rate'])).quantize(CENT)
            tax = (cost * Decimal(policy['tax_rate'])).quantize(CENT)
            gross = cost + tax
            paid = (gross * Decimal(policy['supplier_payment_fraction'])).quantize(CENT)
            current.update(content_cost=cost, supplier_cash=paid, payables=gross-paid,
                           bank_net=current['customer_cash_net']-paid)
            if cost == ZERO:
                continue
            # One fictitious portfolio supplier, not an inferred Oracle distributor.
            supplier = '0099000001'
            key = json.dumps([policy['scenario_id'], company, policy['cutoff_date'], 'supplier'])
            document = _identifier('8', key + 'invoice')
            _post(documents, journal, document=document, kind='supplier_invoice', day=cutoff,
                  company=company, currency=currency, billing='', customer='', supplier=supplier,
                  entries=[('content_cost', cost), ('input_vat', tax), ('payables', -gross)])
            payment = _identifier('8', key + 'payment')
            _post(documents, journal, document=payment, kind='supplier_payment', day=cutoff,
                  company=company, currency=currency, billing='', customer='', supplier=supplier,
                  reference=document, entries=[('payables', paid), ('bank', -paid)])
            payments.append({'document': payment, 'invoice_document': document, 'gross': -paid,
                             'currency': currency, 'company': company, 'simulation_only': True,
                             'account_type': 'K', 'supplier': supplier})
        SCHEMAS["I_OPERATIONALACCTGDOCITEM"].index(journal)
        SCHEMAS["C_BILLINGDOCITEMBASICDEX_1"].index(billing)
        gl = [{**row, "SOURCELEDGER": "0L", "LEDGERGLLINEITEM": row["ACCOUNTINGDOCUMENTITEM"].zfill(6)}
              for row in journal]
        return FinanceResult(*map(_freeze, (documents, journal, gl, billing, payments, clearings, bridges,
                                           list(customers.values()), totals, policy)))
