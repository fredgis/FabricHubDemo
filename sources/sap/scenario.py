"""Deterministic November-style scenario: three subscriptions, ten FI documents, no source writes."""
from __future__ import annotations

import calendar
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sources.sap.accounting import ACCOUNTS, CHART, Journal, Line, ZERO, money
from sources.sap.config import extraction_time, keyed, period, validate
from sources.sap.schema import SCHEMAS, dd03nd_rows


@dataclass
class Snapshot:
    label: str
    timestamp: datetime
    tables: dict[str, list[dict]]
    summary: dict


@dataclass
class Scenario:
    config: dict
    references: dict
    snapshots: list[Snapshot]
    documents: list[dict]


def master_data(config: dict, references: dict) -> dict[str, list[dict]]:
    start, end = period(config)
    stop = end + timedelta(days=1)
    customers = keyed(references["customers"], "customer_key")
    contents = keyed(references["contents"], "content_key")
    distributors = keyed(references["distributors"], "distributor_key")
    tables = {name: [] for name in SCHEMAS}
    tables["I_COMPANYCODE"] = [{
        "COMPANYCODE": config["company_code"], "COMPANYCODENAME": config["company_name"],
        "COUNTRY": "FR", "CURRENCY": "EUR", "CHARTOFACCOUNTS": CHART, "FISCALYEARVARIANT": "K4",
    }]
    tables["I_CHARTOFACCOUNTS"] = [{"CHARTOFACCOUNTS": CHART, "MAINTENANCELANGUAGE": "E"}]
    tables["I_LEDGER"] = [{"LEDGER": "0L", "ISLEADINGLEDGER": "X"}]
    tables["I_PRODUCT"] = [{"PRODUCT": config["plan_id"], "PRODUCTTYPE": "SERV"}]
    for number, name, kind in ACCOUNTS.values():
        tables["I_GLACCOUNTINCHARTOFACCOUNTS"].append({
            "CHARTOFACCOUNTS": CHART, "GLACCOUNT": number, "GLACCOUNTTYPE": kind,
            "ISBALANCESHEETACCOUNT": "X" if kind == "X" else "",
        })
        tables["I_GLACCOUNTTEXT"].append({
            "CHARTOFACCOUNTS": CHART, "GLACCOUNT": number, "LANGUAGE": "E", "GLACCOUNTNAME": name,
        })
    for month in range(1, 13):
        tables["I_FISCALPERIODFORVARIANT"].append({
            "FISCALYEARVARIANT": "K4", "FISCALYEAR": f"{start.year:04d}",
            "FISCALPERIOD": f"{month:03d}", "FISCALYEARPERIOD": f"{start.year:04d}{month:03d}",
            "FISCALPERIODSTARTDATE": date(start.year, month, 1),
            "FISCALPERIODENDDATE": date(start.year, month, calendar.monthrange(start.year, month)[1]),
            "FISCALYEARSTARTDATE": date(start.year, 1, 1), "FISCALYEARENDDATE": date(start.year, 12, 31),
            "ISSPECIALPERIOD": "",
        })
    tables["I_SUPPLIER"] = [{
        "SUPPLIER": config["supplier_id"], "SUPPLIERNAME": config["supplier_name"], "COUNTRY": "FR",
    }]
    tables["ZMSF_PLAN"] = [{
        "PLAN_ID": config["plan_id"], "VERSION": "0001", "NAME": config["plan_name"],
        "PRODUCT": config["plan_id"], "TERRITORY": "FR", "CURRENCY": "EUR",
        "MONTHLY_NET": Decimal(config["monthly_net"]), "VAT_RATE": Decimal(config["vat_rate"]),
        "VALID_FROM": start, "VALID_TO_EXCLUSIVE": stop,
        "CONTRACT_ID": config["contract_id"], "CONTRACT_VERSION": "0001",
    }]
    for selection in sorted(config["customers"], key=lambda r: r["customer_key"]):
        customer = customers[selection["customer_key"]]
        tables["I_CUSTOMER"].append({
            "CUSTOMER": selection["sap_customer"], "CUSTOMERNAME": customer["name"], "COUNTRY": "FR",
        })
        tables["ZMSF_CUSTOMER_LINK"].append({
            "CUSTOMER": selection["sap_customer"], "CUSTOMER_KEY": customer["customer_key"],
            "SALESFORCE_CONTACT_ID": customer["salesforce_contact_id"],
        })
        tables["ZMSF_SUBSCRIPTION"].append({
            "SUBSCRIPTION_ID": "SUB-" + selection["sap_customer"], "CUSTOMER": selection["sap_customer"],
            "PLAN_ID": config["plan_id"], "PLAN_VERSION": "0001",
            "SERVICE_FROM": start, "SERVICE_TO_EXCLUSIVE": stop,
            "STATUS": "ACTIVE", "RENEWAL_POLICY": "MANUAL_NEXT_PERIOD",
        })
    tables["ZMSF_RIGHTS_CONTRACT"] = [{
        "CONTRACT_ID": config["contract_id"], "VERSION": "0001", "SUPPLIER": config["supplier_id"],
        "VALID_FROM": start, "VALID_TO_EXCLUSIVE": stop, "CURRENCY": "EUR",
        "FIXED_NET": Decimal(config["fixed_content_cost"]),
        "REVENUE_SHARE": Decimal(config["content_revenue_share"]),
        "REVENUE_BASIS": "NET_SUBSCRIPTION_BILLINGS_AFTER_CREDITS", "SIMULATION_ONLY": "X",
    }]
    for key in sorted(config["content_keys"]):
        content = contents[key]
        distributor = distributors[content["distributor_key"]]
        tables["ZMSF_RIGHTS_COVERAGE"].append({
            "CONTRACT_ID": config["contract_id"], "VERSION": "0001", "CONTENT_KEY": key,
            "TERRITORY": "FR", "USAGE_TYPE": "SVOD", "CATALOG_DISTRIBUTOR_KEY": content["distributor_key"],
            "CATALOG_SAP_PARTNER_CODE": distributor["sap_partner_code"],
            "VALID_FROM": start, "VALID_TO_EXCLUSIVE": stop, "SIMULATION_ONLY": "X",
        })
    tables["DD03ND"] = dd03nd_rows()
    return tables


def validate_relations(tables: dict[str, list[dict]]) -> None:
    if set(tables) != set(SCHEMAS):
        raise ValueError("Snapshot must contain exactly the declared source objects")
    for name, rows in tables.items():
        SCHEMAS[name].index(rows)
    customers = {r["CUSTOMER"] for r in tables["I_CUSTOMER"]}
    suppliers = {r["SUPPLIER"] for r in tables["I_SUPPLIER"]}
    accounts = {r["GLACCOUNT"] for r in tables["I_GLACCOUNTINCHARTOFACCOUNTS"]}
    subscriptions = keyed(tables["ZMSF_SUBSCRIPTION"], "SUBSCRIPTION_ID")
    plans = {(r["PLAN_ID"], r["VERSION"]) for r in tables["ZMSF_PLAN"]}
    rights = {(r["CONTRACT_ID"], r["VERSION"]) for r in tables["ZMSF_RIGHTS_CONTRACT"]}
    for row in tables["ZMSF_CUSTOMER_LINK"]:
        if row["CUSTOMER"] not in customers:
            raise ValueError("Unresolved customer crosswalk")
    for row in subscriptions.values():
        if row["CUSTOMER"] not in customers or (row["PLAN_ID"], row["PLAN_VERSION"]) not in plans:
            raise ValueError("Unresolved subscription customer/plan")
    for row in tables["ZMSF_PLAN"]:
        if (row["CONTRACT_ID"], row["CONTRACT_VERSION"]) not in rights:
            raise ValueError("Unresolved plan rights contract")
    for row in tables["ZMSF_RIGHTS_CONTRACT"]:
        if row["SUPPLIER"] not in suppliers:
            raise ValueError("Unresolved contract supplier")
    for row in tables["ZMSF_RIGHTS_COVERAGE"]:
        if (row["CONTRACT_ID"], row["VERSION"]) not in rights:
            raise ValueError("Unresolved content coverage contract")
    operational = SCHEMAS["I_OPERATIONALACCTGDOCITEM"].index(tables["I_OPERATIONALACCTGDOCITEM"])
    projected = [
        {key: value for key, value in row.items() if key not in ("SOURCELEDGER", "LEDGERGLLINEITEM")}
        for row in tables["I_GLACCOUNTLINEITEMRAWDATA"]
    ]
    if SCHEMAS["I_OPERATIONALACCTGDOCITEM"].index(projected) != operational:
        raise ValueError("GL and AR/AP must be projections of exactly the same journal")
    documents = {key[:3] for key in operational}
    for row in operational.values():
        if row["GLACCOUNT"] not in accounts:
            raise ValueError("Unresolved GL account")
        if row["CUSTOMER"] and row["CUSTOMER"] not in customers:
            raise ValueError("Unresolved accounting customer")
        if row["SUPPLIER"] and row["SUPPLIER"] not in suppliers:
            raise ValueError("Unresolved accounting supplier")
    bills = SCHEMAS["C_BILLINGDOCITEMBASICDEX_1"].index(tables["C_BILLINGDOCITEMBASICDEX_1"])
    links = SCHEMAS["ZMSF_BILLING_LINK"].index(tables["ZMSF_BILLING_LINK"])
    if set(bills) != set(links):
        raise ValueError("Every billing line requires exactly one source link")
    for key, row in bills.items():
        link = links[key]
        sub = subscriptions.get(link["SUBSCRIPTION_ID"])
        if sub is None or sub["CUSTOMER"] != row["SOLDTOPARTY"]:
            raise ValueError("Unresolved billing customer/subscription")
        if (row["COMPANYCODE"], row["FISCALYEAR"], row["ACCOUNTINGDOCUMENT"]) not in documents:
            raise ValueError("Unresolved billing accounting document")
        if link["ORIGINAL_BILLINGDOCUMENT"] and (link["ORIGINAL_BILLINGDOCUMENT"], "000010") not in bills:
            raise ValueError("Credit must reference its original invoice")
    for row in tables["ZMSF_CONTRACT_CHARGE"]:
        if (row["CONTRACT_ID"], row["VERSION"]) not in rights or (
            row["COMPANYCODE"], row["FISCALYEAR"], row["ACCOUNTINGDOCUMENT"]
        ) not in documents:
            raise ValueError("Unresolved contract charge")


def summarize(journal: Journal, tables: dict[str, list[dict]], as_of: date) -> dict:
    balances = journal.balances()
    bills = tables["C_BILLINGDOCITEMBASICDEX_1"]
    ar = [r for r in journal.rows if r["FINANCIALACCOUNTTYPE"] == "D" and r["CLEARINGDATE"] is None]
    ap = [r for r in journal.rows if r["FINANCIALACCOUNTTYPE"] == "K" and r["CLEARINGDATE"] is None]
    receivables = sum((r["AMOUNTINTRANSACTIONCURRENCY"] for r in ar), ZERO)
    payables = -sum((r["AMOUNTINTRANSACTIONCURRENCY"] for r in ap), ZERO)
    if receivables != balances["receivables"] or payables != -balances["payables"]:
        raise ValueError("Open item balances differ from GL reconciliation accounts")
    net_billings = sum((r["NETAMOUNT"] for r in bills), ZERO)
    if net_billings != -balances["deferred_revenue"] - balances["revenue"]:
        raise ValueError("Billing, deferred revenue and recognized revenue do not reconcile")
    return {
        "as_of": as_of, "currency": journal.currency, "synthetic": True,
        "accounting_documents": len(journal.documents), "journal_lines": len(journal.rows),
        "invoice_count": sum(r["BILLINGDOCUMENTCATEGORY"] == "M" for r in bills),
        "credit_count": sum(r["BILLINGDOCUMENTCATEGORY"] == "O" for r in bills),
        "net_billings": net_billings, "recognized_revenue": -balances["revenue"],
        "deferred_revenue": -balances["deferred_revenue"],
        "content_cost": balances["content_cost"],
        "content_contribution": -balances["revenue"] - balances["content_cost"],
        "receivables": receivables, "payables": payables, "net_bank_movement": balances["bank"],
        "net_vat_liability": -balances["output_vat"] - balances["input_vat"],
        "open_customer_items": len(ar), "open_supplier_items": len(ap),
        "debit_positive_trial_balance": balances,
    }


def build(config: dict, references: dict) -> Scenario:
    validate(config, references)
    start, end = period(config)
    stop = end + timedelta(days=1)
    tables = master_data(config, references)
    journal = Journal(config["company_code"], config["currency"])
    snapshots = []
    selections = sorted(config["customers"], key=lambda r: r["customer_key"])
    roles = {r["role"]: r for r in selections}
    monthly = Decimal(config["monthly_net"])
    vat = Decimal(config["vat_rate"])
    invoice_tax = money(monthly * vat)
    gross = monthly + invoice_tax
    invoices = {}

    def snapshot(label: str, day: date) -> None:
        tables["I_OPERATIONALACCTGDOCITEM"] = deepcopy(journal.rows)
        tables["I_GLACCOUNTLINEITEMRAWDATA"] = journal.gl()
        journal.reconcile()
        validate_relations(tables)
        snapshots.append(Snapshot(label, extraction_time(day), deepcopy(tables), summarize(journal, tables, day)))

    def billing(selection: dict, day: date, net: Decimal, original: str | None = None) -> tuple[str, str]:
        number = f"{9100000001 + len(tables['C_BILLINGDOCITEMBASICDEX_1']):010d}"
        tax = money(net * vat)
        total = net + tax
        credit = net < ZERO
        document = journal.post(day, "DG" if credit else "DR", "Subscription credit" if credit else "Subscription invoice", [
            Line("receivables", total, selection["sap_customer"], start + timedelta(days=7)),
            Line("deferred_revenue", -net),
            *([Line("output_vat", -tax)] if tax else []),
        ], billing=number)
        tables["C_BILLINGDOCITEMBASICDEX_1"].append({
            "BILLINGDOCUMENT": number, "BILLINGDOCUMENTITEM": "000010",
            "BILLINGDOCUMENTTYPE": "G2" if credit else "F2", "BILLINGDOCUMENTCATEGORY": "O" if credit else "M",
            "BILLINGDOCUMENTDATE": day, "COMPANYCODE": config["company_code"],
            "FISCALYEAR": str(day.year), "ACCOUNTINGDOCUMENT": document,
            "SOLDTOPARTY": selection["sap_customer"], "PRODUCT": config["plan_id"],
            "TRANSACTIONCURRENCY": "EUR", "NETAMOUNT": net, "TAXAMOUNT": tax, "GROSSAMOUNT": total,
        })
        tables["ZMSF_BILLING_LINK"].append({
            "BILLINGDOCUMENT": number, "BILLINGDOCUMENTITEM": "000010",
            "SUBSCRIPTION_ID": "SUB-" + selection["sap_customer"], "SERVICE_FROM": start,
            "SERVICE_TO_EXCLUSIVE": stop, "ORIGINAL_BILLINGDOCUMENT": original, "ORDER_ID": None,
        })
        return number, document

    for selection in selections:
        invoices[selection["customer_key"]] = billing(selection, start, monthly)
    snapshot("initial-invoices", start)
    for role, offset in (("paid", 1), ("paid_with_credit", 2)):
        selection = roles[role]
        _, invoice = invoices[selection["customer_key"]]
        day = start + timedelta(days=offset)
        payment = journal.post(day, "DZ", "Customer collection", [
            Line("bank", gross), Line("receivables", -gross, selection["sap_customer"], invoice_reference=invoice),
        ])
        journal.clear((invoice, payment), "D", selection["sap_customer"], payment, day)
        snapshot(f"collection-{offset}", day)

    credited = roles["paid_with_credit"]
    credit = Decimal(config["credit_net"])
    credit_day = start + timedelta(days=14)
    _, credit_doc = billing(credited, credit_day, -credit, invoices[credited["customer_key"]][0])
    snapshot("credit", credit_day)
    refund_day = credit_day + timedelta(days=1)
    refund_gross = credit + money(credit * vat)
    refund = journal.post(refund_day, "DA", "Refund of customer credit", [
        Line("receivables", refund_gross, credited["sap_customer"], invoice_reference=credit_doc),
        Line("bank", -refund_gross),
    ])
    journal.clear((credit_doc, refund), "D", credited["sap_customer"], refund, refund_day)
    snapshot("refund", refund_day)

    revenue = monthly * len(selections) - credit
    journal.post(end, "SA", "Completed monthly service recognition", [
        Line("deferred_revenue", revenue), Line("revenue", -revenue),
    ])
    fixed = Decimal(config["fixed_content_cost"])
    share = Decimal(config["content_revenue_share"])
    variable = money(revenue * share)
    cost = fixed + variable
    input_vat = money(cost * vat)
    invoice_gross = cost + input_vat
    supplier_doc = journal.post(end, "KR", "Fictional monthly content fee", [
        Line("payables", -invoice_gross, config["supplier_id"], end + timedelta(days=30)),
        Line("content_cost", cost),
        *([Line("input_vat", input_vat)] if input_vat else []),
    ])
    for kind, base, rate, charge in (("FIXED", fixed, Decimal("1"), fixed), ("VARIABLE", revenue, share, variable)):
        tables["ZMSF_CONTRACT_CHARGE"].append({
            "CONTRACT_ID": config["contract_id"], "VERSION": "0001", "PERIOD_START": start,
            "CHARGE_TYPE": kind, "BASIS_NET": base, "RATE": rate, "CHARGE_NET": charge,
            "COMPANYCODE": config["company_code"], "FISCALYEAR": str(start.year),
            "ACCOUNTINGDOCUMENT": supplier_doc,
        })
    paid = money(invoice_gross / 2)
    journal.post(end, "KZ", "Partial supplier payment", [
        Line("payables", paid, config["supplier_id"], end + timedelta(days=30), supplier_doc),
        Line("bank", -paid),
    ])
    # A partial payment does not clear the original invoice: both items remain open.
    snapshot("month-end", end)
    return Scenario(deepcopy(config), deepcopy(references), snapshots, deepcopy(journal.documents))
