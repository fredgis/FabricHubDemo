"""Explicit local contracts, not a claim of complete native BPS template coverage."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Field:
    name: str
    ddic: str = "CHAR"
    length: int = 80
    scale: int = 0
    key: bool = False
    nullable: bool = False

    def validate(self, value: object) -> None:
        if value is None:
            if self.nullable and not self.key:
                return
            raise ValueError(f"{self.name} cannot be null")
        if self.ddic in ("CURR", "DEC"):
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f"{self.name} requires an exact finite Decimal")
            quantum = Decimal(1).scaleb(-self.scale)
            if value != value.quantize(quantum) or abs(value) >= Decimal(10) ** (self.length - self.scale):
                raise ValueError(f"{self.name} exceeds decimal precision/scale")
        elif self.ddic == "DATS":
            if type(value) is not date:
                raise ValueError(f"{self.name} requires a date")
        else:
            if not isinstance(value, str) or len(value) > self.length:
                raise ValueError(f"{self.name} requires at most {self.length} characters")
            if self.key and not value:
                raise ValueError(f"{self.name} key cannot be empty")
            if self.ddic == "NUMC" and (not value.isascii() or not value.isdigit() or len(value) != self.length):
                raise ValueError(f"{self.name} requires {self.length} zero-padded digits")


@dataclass(frozen=True)
class Object:
    name: str
    fields: tuple[Field, ...]
    financial: bool = False

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields if f.key)

    def index(self, rows: list[dict]) -> dict[tuple, dict]:
        result = {}
        names = {f.name for f in self.fields}
        for row in rows:
            if set(row) != names:
                raise ValueError(f"{self.name}: missing/unknown columns {set(row) ^ names}")
            for field in self.fields:
                field.validate(row[field.name])
            key = tuple(row[name] for name in self.keys)
            if key in result:
                raise ValueError(f"{self.name}: duplicate key {key}")
            result[key] = row
        return result


def text(name, length=80, *, key=False, nullable=False, ddic="CHAR"):
    return Field(name, ddic, length, key=key, nullable=nullable)


def numc(name, length, *, key=False):
    return Field(name, "NUMC", length, key=key)


def day(name, *, key=False, nullable=False):
    return Field(name, "DATS", 8, key=key, nullable=nullable)


def amount(name):
    return Field(name, "CURR", 23, 2)


def fraction(name):
    return Field(name, "DEC", 9, 4)


COMPANY = text("COMPANYCODE", 4, key=True)
YEAR = numc("FISCALYEAR", 4, key=True)
DOCUMENT = text("ACCOUNTINGDOCUMENT", 10, key=True)
ITEM = numc("ACCOUNTINGDOCUMENTITEM", 3, key=True)
CURRENCY = text("TRANSACTIONCURRENCY", 5, ddic="CUKY")
JOURNAL_FIELDS = (
    COMPANY, YEAR, DOCUMENT, ITEM, text("ACCOUNTINGDOCUMENTTYPE", 2),
    day("POSTINGDATE"), day("DOCUMENTDATE"), numc("FISCALPERIOD", 3),
    text("FISCALYEARVARIANT", 2), text("CHARTOFACCOUNTS", 4), text("GLACCOUNT", 10),
    text("FINANCIALACCOUNTTYPE", 1), text("DEBITCREDITCODE", 1), text("POSTINGKEY", 2),
    CURRENCY, amount("AMOUNTINTRANSACTIONCURRENCY"),
    text("COMPANYCODECURRENCY", 5, ddic="CUKY"), amount("AMOUNTINCOMPANYCODECURRENCY"),
    text("CUSTOMER", 10), text("SUPPLIER", 10),
    text("DOCUMENTITEMTEXT", 50), text("BILLINGDOCUMENT", 10),
    text("CLEARINGACCOUNTINGDOCUMENT", 10, nullable=True),
    text("CLEARINGDOCFISCALYEAR", 4, nullable=True), day("CLEARINGDATE", nullable=True),
    day("NETDUEDATE", nullable=True), text("INVOICEREFERENCE", 10),
    text("INVOICEREFERENCEFISCALYEAR", 4), text("INVOICEITEMREFERENCE", 3),
)

OBJECTS = [
    Object("I_CUSTOMER", (text("CUSTOMER", 10, key=True), text("CUSTOMERNAME"), text("COUNTRY", 3))),
    Object("I_SUPPLIER", (text("SUPPLIER", 10, key=True), text("SUPPLIERNAME"), text("COUNTRY", 3))),
    Object("I_COMPANYCODE", (
        COMPANY, text("COMPANYCODENAME"), text("COUNTRY", 3), text("CURRENCY", 5, ddic="CUKY"),
        text("CHARTOFACCOUNTS", 4), text("FISCALYEARVARIANT", 2),
    )),
    Object("I_CHARTOFACCOUNTS", (text("CHARTOFACCOUNTS", 4, key=True), text("MAINTENANCELANGUAGE", 1, ddic="LANG"))),
    Object("I_GLACCOUNTINCHARTOFACCOUNTS", (
        text("CHARTOFACCOUNTS", 4, key=True), text("GLACCOUNT", 10, key=True),
        text("GLACCOUNTTYPE", 1), text("ISBALANCESHEETACCOUNT", 1),
    )),
    Object("I_GLACCOUNTTEXT", (
        text("CHARTOFACCOUNTS", 4, key=True), text("GLACCOUNT", 10, key=True),
        text("LANGUAGE", 1, key=True, ddic="LANG"), text("GLACCOUNTNAME"),
    )),
    Object("I_LEDGER", (text("LEDGER", 2, key=True), text("ISLEADINGLEDGER", 1))),
    Object("I_PRODUCT", (text("PRODUCT", 40, key=True), text("PRODUCTTYPE", 4))),
    Object("I_FISCALPERIODFORVARIANT", (
        text("FISCALYEARVARIANT", 2, key=True), YEAR, numc("FISCALPERIOD", 3, key=True),
        numc("FISCALYEARPERIOD", 7), day("FISCALPERIODSTARTDATE"), day("FISCALPERIODENDDATE"),
        day("FISCALYEARSTARTDATE"), day("FISCALYEARENDDATE"), text("ISSPECIALPERIOD", 1),
    )),
    Object("I_OPERATIONALACCTGDOCITEM", JOURNAL_FIELDS, financial=True),
    Object("I_GLACCOUNTLINEITEMRAWDATA", tuple(
        Field(f.name, f.ddic, f.length, f.scale, False if f.name == ITEM.name else f.key, f.nullable)
        for f in JOURNAL_FIELDS
    ) + (text("SOURCELEDGER", 2, key=True), numc("LEDGERGLLINEITEM", 6, key=True)), financial=True),
    Object("C_BILLINGDOCITEMBASICDEX_1", (
        text("BILLINGDOCUMENT", 10, key=True), numc("BILLINGDOCUMENTITEM", 6, key=True),
        text("BILLINGDOCUMENTTYPE", 4), text("BILLINGDOCUMENTCATEGORY", 1),
        day("BILLINGDOCUMENTDATE"), text("COMPANYCODE", 4), numc("FISCALYEAR", 4),
        text("ACCOUNTINGDOCUMENT", 10), text("SOLDTOPARTY", 10), text("PRODUCT", 40),
        CURRENCY, amount("NETAMOUNT"), amount("TAXAMOUNT"), amount("GROSSAMOUNT"),
    ), financial=True),
    Object("ZMSF_CUSTOMER_LINK", (
        text("CUSTOMER", 10, key=True), text("CUSTOMER_KEY", 128), text("SALESFORCE_CONTACT_ID", 18),
    )),
    Object("ZMSF_PLAN", (
        text("PLAN_ID", 80, key=True), numc("VERSION", 4, key=True), text("NAME"),
        text("PRODUCT", 40), text("TERRITORY", 2), text("CURRENCY", 5, ddic="CUKY"),
        amount("MONTHLY_NET"), fraction("VAT_RATE"), day("VALID_FROM"), day("VALID_TO_EXCLUSIVE"),
        text("CONTRACT_ID"), numc("CONTRACT_VERSION", 4),
    )),
    Object("ZMSF_SUBSCRIPTION", (
        text("SUBSCRIPTION_ID", 80, key=True), text("CUSTOMER", 10), text("PLAN_ID"),
        numc("PLAN_VERSION", 4), day("SERVICE_FROM"), day("SERVICE_TO_EXCLUSIVE"),
        text("STATUS", 20), text("RENEWAL_POLICY", 30),
    )),
    Object("ZMSF_RIGHTS_CONTRACT", (
        text("CONTRACT_ID", 80, key=True), numc("VERSION", 4, key=True), text("SUPPLIER", 10),
        day("VALID_FROM"), day("VALID_TO_EXCLUSIVE"), text("CURRENCY", 5, ddic="CUKY"),
        amount("FIXED_NET"), fraction("REVENUE_SHARE"), text("REVENUE_BASIS"),
        text("SIMULATION_ONLY", 1),
    )),
    Object("ZMSF_RIGHTS_COVERAGE", (
        text("CONTRACT_ID", 80, key=True), numc("VERSION", 4, key=True),
        text("CONTENT_KEY", 128, key=True), text("TERRITORY", 2, key=True), text("USAGE_TYPE", 4, key=True),
        text("CATALOG_DISTRIBUTOR_KEY", 128), text("CATALOG_SAP_PARTNER_CODE", 80, nullable=True),
        day("VALID_FROM"), day("VALID_TO_EXCLUSIVE"), text("SIMULATION_ONLY", 1),
    )),
    Object("ZMSF_BILLING_LINK", (
        text("BILLINGDOCUMENT", 10, key=True), numc("BILLINGDOCUMENTITEM", 6, key=True),
        text("SUBSCRIPTION_ID"), day("SERVICE_FROM"), day("SERVICE_TO_EXCLUSIVE"),
        text("ORIGINAL_BILLINGDOCUMENT", 10, nullable=True), text("ORDER_ID", 128, nullable=True),
    ), financial=True),
    Object("ZMSF_CONTRACT_CHARGE", (
        text("CONTRACT_ID", 80, key=True), numc("VERSION", 4, key=True),
        day("PERIOD_START", key=True), text("CHARGE_TYPE", 10, key=True),
        amount("BASIS_NET"), fraction("RATE"), amount("CHARGE_NET"),
        text("COMPANYCODE", 4), numc("FISCALYEAR", 4), text("ACCOUNTINGDOCUMENT", 10),
    ), financial=True),
    Object("DD03ND", (
        text("STRUCOBJN", 30, key=True), text("FIELDNAME", 30, key=True),
        text("DATATYPE", 4), numc("LENG", 6), numc("DECIMALS", 6),
    )),
]
SCHEMAS = {obj.name: obj for obj in OBJECTS}


def dd03nd_rows() -> list[dict]:
    return [
        {"STRUCOBJN": obj.name, "FIELDNAME": f.name, "DATATYPE": f.ddic,
         "LENG": f"{f.length:06d}", "DECIMALS": f"{f.scale:06d}"}
        for obj in OBJECTS for f in obj.fields
    ]


def contract() -> dict:
    return {
        "version": 1,
        "native_bps_ready": False,
        "scope": "Local source contract only; no native mirroring or BPS processing claimed.",
        "gates": [
            "Compare these intentionally bounded standard-column projections with the new BPS dataset metadata.",
            "Complete required template columns, texts, financial hierarchies and transformations before native BPS processing.",
            "Register custom ZMSF objects/relationships or explicitly supply a separate curated path.",
            "Confirm billing credit-memo sign conventions against the selected BPS O2C transformation.",
            "Deploy and qualify ADLS, SAP mirroring and a separate SAP BPS item only in later approved lots.",
        ],
        "objects": {
            obj.name: {
                "keys": list(obj.keys), "source_system_in_path": True,
                "coverage": "custom_simulation" if obj.name.startswith("ZMSF_") else "standard_projection_subset",
                "financial_deletes_allowed": False if obj.financial else None,
                "fields": [asdict(f) for f in obj.fields],
            } for obj in OBJECTS
        },
    }
