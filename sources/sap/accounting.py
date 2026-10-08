"""Small balanced FI journal, adapted from the prior local SAP demo without FX or cloud dependencies."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal("0.00")
CHART = "MSFX"
ACCOUNTS = {
    "bank": ("0011000000", "Bank", "X"),
    "receivables": ("0012000000", "Trade receivables", "X"),
    "input_vat": ("0013000000", "Input VAT", "X"),
    "payables": ("0021000000", "Trade payables", "X"),
    "output_vat": ("0022000000", "Output VAT", "X"),
    "deferred_revenue": ("0023000000", "Deferred subscription revenue", "X"),
    "revenue": ("0040000000", "Subscription revenue", "P"),
    "content_cost": ("0050000000", "Content contract expense", "P"),
}


def money(value: Decimal | str | int) -> Decimal:
    if isinstance(value, (float, bool)):
        raise ValueError("Floating-point money is not accepted")
    number = Decimal(value)
    if not number.is_finite():
        raise ValueError("Money must be finite")
    return number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Line:
    account: str
    amount: Decimal
    partner: str = ""
    due: date | None = None
    invoice_reference: str = ""


class Journal:
    def __init__(self, company: str, currency: str):
        self.company, self.currency = company, currency
        self.rows: list[dict] = []
        self.documents: list[dict] = []

    def post(self, day: date, kind: str, description: str, lines: list[Line], billing="") -> str:
        if len(lines) < 2 or any(
            not isinstance(ln.amount, Decimal) or money(ln.amount) != ln.amount or not ln.amount
            for ln in lines
        ):
            raise ValueError("Journal lines require nonzero exact cent amounts")
        if sum((ln.amount for ln in lines), ZERO) != ZERO:
            raise ValueError("Unbalanced accounting document")
        for ln in lines:
            if ln.account not in ACCOUNTS:
                raise ValueError(f"Unknown account: {ln.account}")
            if (ln.account in ("receivables", "payables")) != bool(ln.partner):
                raise ValueError("Only AR/AP lines must carry a business partner")
        number = f"{9000000001 + len(self.documents):010d}"
        rows = []
        for i, ln in enumerate(lines, 1):
            account_type = {"receivables": "D", "payables": "K"}.get(ln.account, "S")
            debit = ln.amount > ZERO
            posting_key = {
                ("D", True): "01", ("D", False): "15" if kind == "DZ" else "11",
                ("K", True): "25" if kind == "KZ" else "21", ("K", False): "31",
                ("S", True): "40", ("S", False): "50",
            }[account_type, debit]
            rows.append({
                "COMPANYCODE": self.company, "FISCALYEAR": f"{day.year:04d}",
                "ACCOUNTINGDOCUMENT": number, "ACCOUNTINGDOCUMENTITEM": f"{i:03d}",
                "ACCOUNTINGDOCUMENTTYPE": kind, "POSTINGDATE": day, "DOCUMENTDATE": day,
                "FISCALPERIOD": f"{day.month:03d}", "FISCALYEARVARIANT": "K4",
                "CHARTOFACCOUNTS": CHART, "GLACCOUNT": ACCOUNTS[ln.account][0],
                "FINANCIALACCOUNTTYPE": account_type, "DEBITCREDITCODE": "S" if debit else "H",
                "POSTINGKEY": posting_key, "TRANSACTIONCURRENCY": self.currency,
                "AMOUNTINTRANSACTIONCURRENCY": ln.amount, "COMPANYCODECURRENCY": self.currency,
                "AMOUNTINCOMPANYCODECURRENCY": ln.amount,
                "CUSTOMER": ln.partner if account_type == "D" else "",
                "SUPPLIER": ln.partner if account_type == "K" else "",
                "DOCUMENTITEMTEXT": description, "BILLINGDOCUMENT": billing,
                "CLEARINGACCOUNTINGDOCUMENT": None, "CLEARINGDOCFISCALYEAR": None,
                "CLEARINGDATE": None, "NETDUEDATE": ln.due,
                "INVOICEREFERENCE": ln.invoice_reference,
                "INVOICEREFERENCEFISCALYEAR": f"{day.year:04d}" if ln.invoice_reference else "",
                "INVOICEITEMREFERENCE": "001" if ln.invoice_reference else "",
            })
        self.rows.extend(rows)
        self.documents.append({"document": number, "posting_date": day, "type": kind, "description": description})
        return number

    def clear(self, documents: tuple[str, ...], account_type: str, partner: str, clearing: str, day: date) -> None:
        field = {"D": "CUSTOMER", "K": "SUPPLIER"}[account_type]
        matches = [
            r for r in self.rows if r["ACCOUNTINGDOCUMENT"] in documents
            and r["FINANCIALACCOUNTTYPE"] == account_type and r[field] == partner
        ]
        if {r["ACCOUNTINGDOCUMENT"] for r in matches} != set(documents) or clearing not in documents:
            raise ValueError("Clearing must reference each existing partner document")
        if any(r["CLEARINGDATE"] is not None or r["POSTINGDATE"] > day for r in matches):
            raise ValueError("Cannot clear already-cleared or future items")
        if sum((r["AMOUNTINTRANSACTIONCURRENCY"] for r in matches), ZERO) != ZERO:
            raise ValueError("Partial payments must remain open, not falsely fully cleared")
        for row in matches:
            row.update(CLEARINGACCOUNTINGDOCUMENT=clearing, CLEARINGDOCFISCALYEAR=f"{day.year:04d}", CLEARINGDATE=day)

    def gl(self) -> list[dict]:
        return [
            {**row, "SOURCELEDGER": "0L", "LEDGERGLLINEITEM": row["ACCOUNTINGDOCUMENTITEM"].zfill(6)}
            for row in self.rows
        ]

    def balances(self) -> dict[str, Decimal]:
        reverse = {definition[0]: role for role, definition in ACCOUNTS.items()}
        result = {role: ZERO for role in ACCOUNTS}
        for row in self.rows:
            result[reverse[row["GLACCOUNT"]]] += row["AMOUNTINTRANSACTIONCURRENCY"]
        return result

    def reconcile(self) -> None:
        totals = defaultdict(lambda: ZERO)
        for row in self.rows:
            key = (row["COMPANYCODE"], row["FISCALYEAR"], row["ACCOUNTINGDOCUMENT"])
            totals[key] += row["AMOUNTINTRANSACTIONCURRENCY"]
        if any(totals.values()) or sum(self.balances().values(), ZERO):
            raise ValueError("Accounting documents or trial balance do not reconcile")
