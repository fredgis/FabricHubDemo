"""Local native BPS source adapter. PR1 accounting and source contracts remain unchanged.

Parent wiring: use build(config, references, metadata_path=...) and this module's
write_package, not datasphere.write_package (which deliberately owns PR1 schemas).
No notebook, mirror, pipeline, tenant, or network operation is performed here.
"""
from __future__ import annotations

import argparse
import ast
import operator
import shutil
import uuid
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from sources.sap.accounting import ACCOUNTS, CHART, ZERO
from sources.sap.config import DEFAULT_CONFIG, DEFAULT_REFERENCES, period, read_json
from sources.sap.datasphere import changes, digest, json_bytes, metadata as pr1_metadata
from sources.sap.scenario import Scenario, Snapshot, build as build_pr1
from sources.sap.schema import Field, Object, SCHEMAS as PR1_SCHEMAS

REPOSITORY = Path(__file__).resolve().parents[2]
INPUT_CONTRACT = Path(__file__).parent / "contracts" / "native-input-v1.json"
SCHEMA_VERSION = "msflix-native-source-v1"
FINANCIAL_FACTS = (
    "C_BILLINGDOCITEMBASICDEX_1", "I_GLACCOUNTLINEITEMRAWDATA", "I_OPERATIONALACCTGDOCITEM",
)
CURRENCIES = {
    "CC": ("COMPANYCODECURRENCY", "AMOUNTINCOMPANYCODECURRENCY"),
    "FC": ("FUNCTIONALCURRENCY", "AMOUNTINFUNCTIONALCURRENCY"),
    "TC": ("TRANSACTIONCURRENCY", "AMOUNTINTRANSACTIONCURRENCY"),
    "GC": ("ADDITIONALCURRENCY1", "AMOUNTINADDITIONALCURRENCY1"),
}

# These are SAP initial domain values, not fabricated equipment/asset/employee rows.
INITIAL_KEYS = {
    "ACCOUNTINGDOCUMENTCATEGORY", "SPECIALGLCODE", "PAYMENTBLOCKINGREASON",
    "DUNNINGKEY", "DUNNINGAREA", "PAYMENTTERMS", "CUSTOMERPAYMENTTERMS",
    "BILLINGPLANRULE", "PARENTNODE",
}
UNASSIGNED_RELATIONS = {
    "I_CUSTOMER": {"CUSTOMER", "PAYERPARTY", "BILLTOPARTY", "SHIPTOPARTY", "SOLDTOPARTY"},
    "I_SUPPLIER": {"SUPPLIER"},
    "I_GLOBALCOMPANY": {"PARTNERCOMPANY"},
    "I_EQUIPMENT": {"EQUIPMENT"},
    "I_FIXEDASSET": {"FIXEDASSET", "MASTERFIXEDASSET"},
    "I_FUNCTIONALLOCATION": {"FUNCTIONALLOCATION"},
    "I_WBSELEMENTDATA_2": {"WBSELEMENTINTERNALID"},
    "I_COSTCENTERACTIVITYTYPE": {"COSTCTRACTIVITYTYPE"},
    "I_PERSONWORKAGREEMENT_1": {"SALESEMPLOYEE"},
    "I_PLANT": {"PLANT"},
    "I_SHIPPINGPOINT": {"SHIPPINGPOINT"},
}
EMPTY_OBJECTS = {
    "I_EQUIPMENT", "I_EQUIPMENTTEXT", "I_FIXEDASSET", "I_FUNCTIONALLOCATION",
    "I_FUNCTIONALLOCATIONTEXT", "I_WBSELEMENTDATA_2", "I_COSTCENTERACTIVITYTYPE",
    "I_COSTCENTERACTIVITYTYPETEXT", "I_PERSONWORKAGREEMENT_1", "I_PLANT",
    "I_SHIPPINGPOINT", "I_SHIPPINGPOINTTEXT",
}
NOT_SOURCE = {
    "KEY", "EN", "FR", "DE", "ES", "_ISOLANGUAGE", "_SYSTEMNAME", "_UPDATETIMESTAMP",
    "_DELETE", "_CHANGE_TYPE", "_REPROCESS", "COST_CENTER_NODE_KEY", "TL",
}

# Reviewed source projection: native cube keys, raw text attributes, Gold SQL's
# source references, PR1 journal fields, and the four balance currency inputs.
# Model-only surrogate keys, pivots, calculated columns and measures are excluded.
SOURCE_COLUMNS = {
    "I_ACCOUNTINGDOCUMENTCATEGORY": "ACCOUNTINGDOCUMENTCATEGORY",
    "I_ACCOUNTINGDOCUMENTCATEGORYT": "ACCOUNTINGDOCUMENTCATEGORY LANGUAGE ACCOUNTINGDOCUMENTCATEGORYNAME",
    "I_ACCOUNTINGDOCUMENTTYPE": "ACCOUNTINGDOCUMENTTYPE ACCOUNTINGDOCUMENTNUMBERRANGE ALLOWEDFINANCIALACCOUNTTYPES",
    "I_ACCOUNTINGDOCUMENTTYPETEXT": "ACCOUNTINGDOCUMENTTYPE LANGUAGE ACCOUNTINGDOCUMENTTYPENAME",
    "I_BILLINGDOCUMENTTYPE": "BILLINGDOCUMENTTYPE BILLINGDOCUMENTCATEGORY SDDOCUMENTCATEGORY",
    "I_BILLINGDOCUMENTTYPETEXT": "BILLINGDOCUMENTTYPE LANGUAGE BILLINGDOCUMENTTYPENAME",
    "I_BILLINGPLANRULE": "BILLINGPLANRULE",
    "I_BILLINGPLANRULETEXT": "BILLINGPLANRULE LANGUAGE BILLINGPLANRULENAME",
    "I_BUSINESSAREA": "BUSINESSAREA",
    "I_BUSINESSAREATEXT": "BUSINESSAREA LANGUAGE BUSINESSAREANAME",
    "I_CHARTOFACCOUNTS": "CHARTOFACCOUNTS MAINTENANCELANGUAGE CHARTOFACCTSISBLOCKED CORPORATEGROUPCHARTOFACCOUNTS",
    "I_CHARTOFACCOUNTSTEXT": "CHARTOFACCOUNTS LANGUAGE CHARTOFACCOUNTSNAME",
    "I_COMPANYCODE": "COMPANYCODE COMPANYCODENAME COUNTRY CURRENCY CHARTOFACCOUNTS FISCALYEARVARIANT COMPANY CONTROLLINGAREA LANGUAGE",
    "I_CONTROLLINGAREA": "CONTROLLINGAREA CONTROLLINGAREANAME CONTROLLINGAREACURRENCY CONTROLLINGAREACURRENCYROLE CHARTOFACCOUNTS FISCALYEARVARIANT OPERATINGCONCERN",
    "I_COSTCENTER": "CONTROLLINGAREA COSTCENTER VALIDITYENDDATE VALIDITYSTARTDATE COMPANYCODE BUSINESSAREA FUNCTIONALAREA PROFITCENTER COSTCENTERCURRENCY COSTCENTERCATEGORY COSTCENTERSTANDARDHIERAREA COUNTRY LANGUAGE",
    "I_COSTCENTERACTIVITYTYPE": "CONTROLLINGAREA COSTCTRACTIVITYTYPE VALIDITYENDDATE VALIDITYSTARTDATE COSTCTRACTIVITYTYPEQTYUNIT COSTCTRACTIVITYTYPEOUTPQTYUNIT",
    "I_COSTCENTERACTIVITYTYPETEXT": "CONTROLLINGAREA COSTCTRACTIVITYTYPE VALIDITYENDDATE LANGUAGE COSTCTRACTIVITYTYPENAME",
    "I_COSTCENTERHIERARCHYNODE": "CONTROLLINGAREA COSTCENTERHIERARCHY HIERARCHYNODE VALIDITYENDDATE VALIDITYSTARTDATE PARENTNODE NODETYPE COSTCENTER",
    "I_COSTCENTERHIERARCHYNODET": "CONTROLLINGAREA COSTCENTERHIERARCHY HIERARCHYNODE VALIDITYENDDATE LANGUAGE HIERARCHYNODENAME",
    "I_COSTCENTERTEXT": "CONTROLLINGAREA COSTCENTER VALIDITYENDDATE LANGUAGE COSTCENTERNAME HIERARCHYNODETEXT",
    "I_CUSTOMER": "CUSTOMER CUSTOMERNAME CUSTOMERFULLNAME COUNTRY",
    "I_CUSTOMERGROUP": "CUSTOMERGROUP",
    "I_CUSTOMERGROUPTEXT": "CUSTOMERGROUP LANGUAGE CUSTOMERGROUPNAME",
    "I_CUSTOMERPAYMENTTERMS": "CUSTOMERPAYMENTTERMS",
    "I_CUSTOMERPAYMENTTERMSTEXT": "CUSTOMERPAYMENTTERMS LANGUAGE CUSTOMERPAYMENTTERMSNAME",
    "I_DEBITCREDITCODE": "DEBITCREDITCODE",
    "I_DEBITCREDITCODETEXT": "DEBITCREDITCODE LANGUAGE DEBITCREDITCODENAME",
    "I_DISTRIBUTIONCHANNEL": "DISTRIBUTIONCHANNEL",
    "I_DISTRIBUTIONCHANNELTEXT": "DISTRIBUTIONCHANNEL LANGUAGE DISTRIBUTIONCHANNELNAME",
    "I_DIVISION": "DIVISION",
    "I_DIVISIONTEXT": "DIVISION LANGUAGE DIVISIONNAME",
    "I_DUNNINGAREA": "COMPANYCODE DUNNINGAREA",
    "I_DUNNINGAREATEXT": "COMPANYCODE DUNNINGAREA LANGUAGE DUNNINGAREANAME COMPANYCODENAME",
    "I_DUNNINGKEY": "DUNNINGKEY MAXIMUMDUNNINGLEVEL",
    "I_DUNNINGKEYTEXT": "DUNNINGKEY LANGUAGE DUNNINGKEYNAME",
    "I_EQUIPMENT": "EQUIPMENT",
    "I_EQUIPMENTTEXT": "EQUIPMENT LANGUAGE EQUIPMENTNAME",
    "I_FISCALPERIODFORVARIANT": "FISCALPERIOD FISCALYEAR FISCALYEARVARIANT FISCALYEARPERIOD FISCALPERIODSTARTDATE FISCALPERIODENDDATE FISCALYEARSTARTDATE FISCALYEARENDDATE ISSPECIALPERIOD NEXTFISCALPERIOD NEXTFISCALPERIODFISCALYEAR",
    "I_FISCALYEARFORCOMPANYCODE": "COMPANYCODE FISCALYEAR FISCALYEARSTARTDATE FISCALYEARENDDATE",
    "I_FISCALYEARVARIANT": "FISCALYEARVARIANT NUMBEROFPOSTINGPERIODS NUMBEROFSPECIALPERIODS FISCALYEARISCALENDARYEAR",
    "I_FIXEDASSET": "COMPANYCODE FIXEDASSET MASTERFIXEDASSET",
    "I_FUNCTIONALAREA": "FUNCTIONALAREA",
    "I_FUNCTIONALAREATEXT": "FUNCTIONALAREA LANGUAGE FUNCTIONALAREANAME",
    "I_FUNCTIONALLOCATION": "FUNCTIONALLOCATION",
    "I_FUNCTIONALLOCATIONTEXT": "FUNCTIONALLOCATION LANGUAGE FUNCTIONALLOCATIONNAME",
    "I_GLACCOUNTHIERARCHYNODE": "GLACCOUNTHIERARCHY HIERARCHYNODE VALIDITYENDDATE VALIDITYSTARTDATE PARENTNODE HIERARCHYVERSION CHARTOFACCOUNTS NODETYPE GLACCOUNT",
    "I_GLACCOUNTHIERARCHYNODET": "GLACCOUNTHIERARCHY HIERARCHYNODE VALIDITYENDDATE LANGUAGE HIERARCHYNODENAME",
    "I_GLACCOUNTINCHARTOFACCOUNTS": "CHARTOFACCOUNTS GLACCOUNT GLACCOUNTTYPE ISBALANCESHEETACCOUNT ISPROFITLOSSACCOUNT GLACCOUNTGROUP",
    "I_GLACCOUNTTEXT": "CHARTOFACCOUNTS GLACCOUNT LANGUAGE GLACCOUNTNAME GLACCOUNTLONGNAME HIERARCHYNODETEXT",
    "I_GLOBALCOMPANY": "COMPANY COMPANYNAME COUNTRY CURRENCY LANGUAGE",
    "I_LANGUAGE": "LANGUAGE LANGUAGECODE",
    "I_LANGUAGETEXT": "LANGUAGE LANGUAGECODE LANGUAGENAME",
    "I_LEDGER": "LEDGER ISLEADINGLEDGER",
    "I_LEDGERTEXT": "LEDGER LANGUAGE LEDGERNAME",
    "I_OVERALLBILLINGSTATUS": "OVERALLBILLINGSTATUS DOMAINVALUE",
    "I_OVERALLBILLINGSTATUSTEXT": "OVERALLBILLINGSTATUS LANGUAGE OVERALLBILLINGSTATUSNAME",
    "I_PAYMENTBLOCKINGREASON": "PAYMENTBLOCKINGREASON",
    "I_PAYMENTBLOCKINGREASONTEXT": "PAYMENTBLOCKINGREASON LANGUAGE PAYMENTBLOCKINGREASONNAME",
    "I_PAYMENTTERMS": "PAYMENTTERMS",
    "I_PAYMENTTERMSTEXT": "PAYMENTTERMS LANGUAGE PAYMENTTERMSNAME",
    "I_PERSONWORKAGREEMENT_1": "PERSONWORKAGREEMENT PERSON PERSONFULLNAME",
    "I_PLANT": "PLANT PLANTNAME",
    "I_POSTINGKEY": "POSTINGKEY DEBITCREDITCODE FINANCIALACCOUNTTYPE REVERSALPOSTINGKEY ISSALESRELATED ISSPECIALGLTRANSACTION ISUSEDINPAYMENTTRANSACTION",
    "I_POSTINGKEYTEXT": "POSTINGKEY LANGUAGE POSTINGKEYNAME",
    "I_PRODUCT": "PRODUCT PRODUCTTYPE PRODUCTGROUP BASEUNIT",
    "I_PRODUCTDESCRIPTION": "PRODUCT LANGUAGE PRODUCTNAME PRODUCTDESCRIPTION",
    "I_PRODUCTGROUP_2": "PRODUCTGROUP",
    "I_PRODUCTGROUPTEXT_2": "PRODUCTGROUP LANGUAGE PRODUCTGROUPNAME",
    "I_PROFITCENTER": "CONTROLLINGAREA PROFITCENTER VALIDITYENDDATE VALIDITYSTARTDATE COMPANYCODE COUNTRY SEGMENT LANGUAGE PROFITCENTERSTANDARDHIERARCHY",
    "I_PROFITCENTERHIERARCHYNODE": "CONTROLLINGAREA PROFITCENTERHIERARCHY HIERARCHYNODE VALIDITYENDDATE VALIDITYSTARTDATE PARENTNODE NODETYPE PROFITCENTER",
    "I_PROFITCENTERHIERARCHYNODET": "CONTROLLINGAREA PROFITCENTERHIERARCHY HIERARCHYNODE VALIDITYENDDATE LANGUAGE HIERARCHYNODENAME",
    "I_PROFITCENTERTEXT": "CONTROLLINGAREA PROFITCENTER VALIDITYENDDATE LANGUAGE PROFITCENTERNAME HIERARCHYNODETEXT",
    "I_SALESORGANIZATION": "SALESORGANIZATION COMPANYCODE SALESORGANIZATIONCURRENCY",
    "I_SALESORGANIZATIONTEXT": "SALESORGANIZATION LANGUAGE SALESORGANIZATIONNAME",
    "I_SEGMENT": "SEGMENT",
    "I_SEGMENTTEXT": "SEGMENT LANGUAGE SEGMENTNAME",
    "I_SHIPPINGPOINT": "SHIPPINGPOINT",
    "I_SHIPPINGPOINTTEXT": "SHIPPINGPOINT LANGUAGE SHIPPINGPOINTNAME",
    "I_SPECIALGLCODE": "SPECIALGLCODE ISNOTEDITMWITHOUTBALUPDT SPECIALGLTRANSACTIONTYPE",
    "I_SPECIALGLCODETEXT": "SPECIALGLCODE LANGUAGE SPECIALGLCODENAME",
    "I_SUPPLIER": "SUPPLIER SUPPLIERNAME SUPPLIERFULLNAME COUNTRY",
    "I_WBSELEMENTDATA_2": "WBSELEMENTINTERNALID",
}

# The native SQL views project these actual attributes, even for unused features.
# They remain SAP initials; there are no invented addresses or industrial nodes.
COST_SQL_ATTRIBUTES = """
ACTLDEPSTATISTICALKEYFIGURES ACTLINDEPSTATISTICALKEYFIGURES ACTYDEPDNTFORMULAPLANNINGTMPL
ACTYDEPENDENTALLOCATIONTMPL ACTYINDEPENDENTALLOCATIONTMPL ACTYINDEPFORMULAPLANNINGTMPL
ADDRESSADDITIONALNAME ADDRESSNAME AVAILABILITYCONTROLISACTIVE AVAILABILITYCONTROLPROFILE
BUDGETCARRYINGCOSTCENTER CITYNAME CONDITIONAPPLICATION CONDITIONUSAGE CONSUMPTIONQTYISRECORDED
COSTCENTERACCOUNTINGOVERHEAD COSTCENTERADDRNAME3 COSTCENTERADDRNAME4 COSTCENTERALLOCATIONMETHOD
COSTCENTERALTERNATIVEFUNCTION COSTCENTERCREATEDBYUSER COSTCENTERCREATIONDATE COSTCENTERFUNCTION
COSTCENTERISCOMPLETE COSTCENTERPRINTERDESTINATION COSTCOLLECTOR COSTCTRRESPONSIBLEPERSONNAME
COSTCTRRESPONSIBLEUSER COSTINGSHEET DATACOMMUNICATIONPHONENUMBER DEPARTMENT DISTRICT FAXNUMBER
FORMOFADDRESS FUNCTIONALAREAISFIXASSIGNED FUND FUNDISFIXASSIGNED GRANTID GRANTIDISFIXASSIGNED
ISBLKDFORPRIMARYCOSTSPOSTING ISBLKDFORSECONDARYCOSTSPOSTING ISBLOCKEDFORCOMMITMENTPOSTING
ISBLOCKEDFORPLANPRIMARYCOSTS ISBLOCKEDFORPLANREVENUES ISBLOCKEDFORPLANSECONDARYCOSTS
ISBLOCKEDFORREVENUEPOSTING ISSTATISTICALCOSTCENTER JOINTVENTURE JOINTVENTURECLASS
JOINTVENTUREEQUITYTYPE JOINTVENTUREOBJECTTYPE JOINTVENTURERECOVERYCODE JOINTVENTURESUBCLASS
LOGICALSYSTEM OBJECTINTERNALID PHONENUMBER1 PHONENUMBER2 PLANT POBOX POBOXPOSTALCODE POSTALCODE
REGION STREETADDRESSNAME SUBSEQUENTCOSTCENTER TAXJURISDICTION TELEBOXNUMBER TELETEXNUMBER TELEXNUMBER
"""
PROFIT_SQL_ATTRIBUTES = """
ADDITIONALNAME ADDRESSNAME CITYNAME DATACOMMUNICATIONPHONENUMBER DEPARTMENT DISTRICT
FAXNUMBER FORMOFADDRESS FORMULAPLANNINGTEMPLATE PHONENUMBER1 PHONENUMBER2 POBOX POBOXPOSTALCODE
POSTALCODE PROFITCENTERADDRNAME3 PROFITCENTERADDRNAME4 PROFITCENTERCREATEDBYUSER
PROFITCENTERCREATIONDATE PROFITCENTERISBLOCKED PROFITCENTERPRINTERNAME PROFITCTRRESPONSIBLEPERSONNAME
PROFITCTRRESPONSIBLEUSER REGION STREETADDRESSNAME TAXJURISDICTION TELEBOXNUMBER TELETEXNUMBER TELEXNUMBER
"""
COST_ACTIVITY_SQL_ATTRIBUTES = """
ACTIVITYTYPEISBLOCKED ACTLPOSTGCOSTCENTERACTYTYPECAT ACTUALPRICEALLOCATIONMETHOD
ACTUALQUANTITYISSETMANUALLY ALLOCATIONCOSTELEMENT COSTCTRACTIVITYTYPECATEGORY
COSTCTRACTIVITYTYPEVALIDCAT COSTCTRACTYTYPEISCTRLGRLVTCOMP COSTCTRACTYTYPEISHUMRSCERLVT
COSTORIGINGROUP CREATIONDATE ENTEREDBYUSER FIXEDCOSTISPREDISTRIBUTED OUTPUTQUANTITYFACTOR
PERIODPRICEISAVERAGE PLANQUANTITYISSETMANUALLY PRICEALLOCATIONMETHOD
"""
SOURCE_COLUMNS["I_COSTCENTER"] += " " + COST_SQL_ATTRIBUTES
SOURCE_COLUMNS["I_PROFITCENTER"] += " " + PROFIT_SQL_ATTRIBUTES
SOURCE_COLUMNS["I_COSTCENTERACTIVITYTYPE"] += " " + COST_ACTIVITY_SQL_ATTRIBUTES

JOURNAL_EXTRA = """
ACCOUNTINGDOCUMENTCATEGORY SPECIALGLCODE CONTROLLINGAREA BUSINESSAREA COSTCENTER PROFITCENTER
FUNCTIONALAREA SEGMENT COMPANY PARTNERCOMPANY CUSTOMERGROUP PRODUCT PRODUCTGROUP PLANT
EQUIPMENT FIXEDASSET MASTERFIXEDASSET FUNCTIONALLOCATION COSTCTRACTIVITYTYPE WBSELEMENTINTERNALID
FUNCTIONALCURRENCY AMOUNTINFUNCTIONALCURRENCY ADDITIONALCURRENCY1 AMOUNTINADDITIONALCURRENCY1
GLOBALCURRENCY AMOUNTINGLOBALCURRENCY FISCALYEARPERIOD LEDGERFISCALYEAR
PAYMENTTERMS PAYMENTBLOCKINGREASON DUNNINGAREA DUNNINGKEY ISOPENITEMMANAGED
PARTNERCOMPANYCODE TAXCODE TAXCOUNTRY
"""
BILLING_EXTRA = """
PAYERPARTY BILLTOPARTY SHIPTOPARTY BILLINGPLANRULE BUSINESSAREA CONTROLLINGAREA COSTCENTER
PROFITCENTER CUSTOMERGROUP DISTRIBUTIONCHANNEL DIVISION FISCALYEARVARIANT FISCALPERIOD
OVERALLBILLINGSTATUS SALESEMPLOYEE PLANT PRODUCTGROUP SALESORGANIZATION SHIPPINGPOINT
CURRENCY SALESORGANIZATIONCURRENCY BILLINGQUANTITY BILLINGQUANTITYINBASEUNIT BILLINGQUANTITYUNIT
BASEUNIT BILLINGDOCUMENTITEMTEXT
"""
for _name in FINANCIAL_FACTS:
    SOURCE_COLUMNS[_name] = " ".join(f.name for f in PR1_SCHEMAS[_name].fields)
    SOURCE_COLUMNS[_name] += " " + (BILLING_EXTRA if _name.startswith("C_") else JOURNAL_EXTRA)


@dataclass(frozen=True)
class NativeField(Field):
    initial_key_allowed: bool = False

    def validate(self, value: object) -> None:
        if value == "" and self.initial_key_allowed and self.ddic == "CHAR":
            return
        if value is None and self.nullable and not self.key:
            return
        if self.ddic == "QUAN":
            replace(self, ddic="DEC").validate(value)
        elif self.ddic in ("INT4", "INT8"):
            bits = 32 if self.ddic == "INT4" else 64
            if type(value) is not int or not -(2 ** (bits - 1)) <= value < 2 ** (bits - 1):
                raise ValueError(f"{self.name} requires a signed {bits}-bit integer")
        else:
            super().validate(value)
        if self.ddic == "NUMC" and value is not None and int(value) > 2147483647:
            raise ValueError(f"{self.name}: NUMC would overflow native BPS IntegerType")


def _field_types() -> dict[str, tuple[str, int, int]]:
    types = {}
    for obj in PR1_SCHEMAS.values():
        if obj.name.startswith("ZMSF_") or obj.name == "DD03ND":
            continue
        for f in obj.fields:
            definition = (f.ddic, f.length, f.scale)
            if f.name in types and types[f.name] != definition:
                raise ValueError(f"{obj.name}.{f.name}: conflicting PR1 source types require explicit native adaptation")
            types[f.name] = definition
    groups = {
        ("CHAR", 1, 0): """ACCOUNTINGDOCUMENTCATEGORY SPECIALGLCODE PAYMENTBLOCKINGREASON DUNNINGKEY
            BILLINGPLANRULE NODETYPE COSTCENTERCATEGORY SPECIALGLTRANSACTIONTYPE
            ISPROFITLOSSACCOUNT ISSALESRELATED ISSPECIALGLTRANSACTION ISUSEDINPAYMENTTRANSACTION
            ISNOTEDITMWITHOUTBALUPDT ISOPENITEMMANAGED CHARTOFACCTSISBLOCKED FISCALYEARISCALENDARYEAR
            OVERALLBILLINGSTATUS""",
        ("CHAR", 2, 0): """CUSTOMERGROUP DISTRIBUTIONCHANNEL DIVISION DUNNINGAREA
            CONTROLLINGAREACURRENCYROLE REVERSALPOSTINGKEY ACCOUNTINGDOCUMENTNUMBERRANGE TAXCODE""",
        ("CHAR", 3, 0): "COUNTRY REGION TAXCOUNTRY",
        ("CHAR", 4, 0): """CONTROLLINGAREA BUSINESSAREA SALESORGANIZATION PLANT SHIPPINGPOINT
            FIXEDASSET PAYMENTTERMS CUSTOMERPAYMENTTERMS GLACCOUNTGROUP OPERATINGCONCERN
            CORPORATEGROUPCHARTOFACCOUNTS SDDOCUMENTCATEGORY PARTNERCOMPANYCODE""",
        ("CHAR", 5, 0): "ALLOWEDFINANCIALACCOUNTTYPES",
        ("CHAR", 6, 0): "COMPANY PARTNERCOMPANY COSTCTRACTIVITYTYPE",
        ("CHAR", 8, 0): "SALESEMPLOYEE PERSONWORKAGREEMENT",
        ("CHAR", 9, 0): "PRODUCTGROUP",
        ("CHAR", 10, 0): """COSTCENTER PROFITCENTER SEGMENT PERSON BUDGETCARRYINGCOSTCENTER
            SUBSEQUENTCOSTCENTER PAYERPARTY BILLTOPARTY SHIPTOPARTY ALLOCATIONCOSTELEMENT""",
        ("CHAR", 12, 0): "MASTERFIXEDASSET COSTCENTERCREATEDBYUSER PROFITCENTERCREATEDBYUSER ENTEREDBYUSER",
        ("CHAR", 15, 0): "COSTCENTERHIERARCHY PROFITCENTERHIERARCHY COSTCENTERSTANDARDHIERAREA PROFITCENTERSTANDARDHIERARCHY",
        ("CHAR", 16, 0): "FUNCTIONALAREA",
        ("CHAR", 18, 0): "EQUIPMENT",
        ("CHAR", 40, 0): """FUNCTIONALLOCATION DOMAINVALUE PRODUCTDESCRIPTION"""
            + COST_SQL_ATTRIBUTES + PROFIT_SQL_ATTRIBUTES + COST_ACTIVITY_SQL_ATTRIBUTES,
        ("CHAR", 42, 0): "GLACCOUNTHIERARCHY",
        ("CHAR", 50, 0): "HIERARCHYNODE PARENTNODE BILLINGDOCUMENTITEMTEXT",
        ("CHAR", 60, 0): """ACCOUNTINGDOCUMENTCATEGORYNAME ACCOUNTINGDOCUMENTTYPENAME
            BILLINGDOCUMENTTYPENAME BILLINGPLANRULENAME BUSINESSAREANAME CHARTOFACCOUNTSNAME
            COSTCTRACTIVITYTYPENAME HIERARCHYNODENAME COSTCENTERNAME HIERARCHYNODETEXT
            CUSTOMERGROUPNAME CUSTOMERPAYMENTTERMSNAME DEBITCREDITCODENAME
            DISTRIBUTIONCHANNELNAME DIVISIONNAME DUNNINGAREANAME DUNNINGKEYNAME EQUIPMENTNAME
            FUNCTIONALAREANAME FUNCTIONALLOCATIONNAME GLACCOUNTLONGNAME LANGUAGENAME LEDGERNAME
            OVERALLBILLINGSTATUSNAME PAYMENTBLOCKINGREASONNAME PAYMENTTERMSNAME PERSONFULLNAME
            PLANTNAME POSTINGKEYNAME PRODUCTNAME PRODUCTGROUPNAME PROFITCENTERNAME
            SALESORGANIZATIONNAME SEGMENTNAME SHIPPINGPOINTNAME SPECIALGLCODENAME""",
        ("CHAR", 80, 0): "COMPANYNAME CONTROLLINGAREANAME CUSTOMERFULLNAME SUPPLIERFULLNAME",
        ("NUMC", 1, 0): "MAXIMUMDUNNINGLEVEL NUMBEROFSPECIALPERIODS",
        ("NUMC", 3, 0): "NEXTFISCALPERIOD NUMBEROFPOSTINGPERIODS INVOICEITEMREFERENCE",
        ("NUMC", 4, 0): """NEXTFISCALPERIODFISCALYEAR LEDGERFISCALYEAR HIERARCHYVERSION
            CLEARINGDOCFISCALYEAR INVOICEREFERENCEFISCALYEAR""",
        ("NUMC", 8, 0): "WBSELEMENTINTERNALID",
        ("CUKY", 5, 0): """FUNCTIONALCURRENCY ADDITIONALCURRENCY1 GLOBALCURRENCY
            CONTROLLINGAREACURRENCY COSTCENTERCURRENCY SALESORGANIZATIONCURRENCY""",
        ("CURR", 23, 2): "AMOUNTINFUNCTIONALCURRENCY AMOUNTINADDITIONALCURRENCY1 AMOUNTINGLOBALCURRENCY",
        ("QUAN", 13, 3): "BILLINGQUANTITY BILLINGQUANTITYINBASEUNIT",
        ("DEC", 5, 2): "OUTPUTQUANTITYFACTOR",
        ("UNIT", 3, 0): "BILLINGQUANTITYUNIT BASEUNIT COSTCTRACTIVITYTYPEQTYUNIT COSTCTRACTIVITYTYPEOUTPQTYUNIT",
        ("LANG", 1, 0): "LANGUAGECODE",
        ("DATS", 8, 0): """VALIDITYSTARTDATE VALIDITYENDDATE COSTCENTERCREATIONDATE
            PROFITCENTERCREATIONDATE CREATIONDATE""",
    }
    # Broad SQL text groups are overridden by curated SAP DDIC definitions below.
    for definition, names in groups.items():
        for name in names.split():
            types[name] = definition
    for name in ("PLANT",):
        types[name] = ("CHAR", 4, 0)
    for name in ("REGION",):
        types[name] = ("CHAR", 3, 0)
    for name in ("COSTCENTERCREATEDBYUSER", "PROFITCENTERCREATEDBYUSER", "ENTEREDBYUSER"):
        types[name] = ("CHAR", 12, 0)
    for name in ("BUDGETCARRYINGCOSTCENTER", "SUBSEQUENTCOSTCENTER", "LOGICALSYSTEM", "ALLOCATIONCOSTELEMENT"):
        types[name] = ("CHAR", 10, 0)
    for name in (COST_SQL_ATTRIBUTES + PROFIT_SQL_ATTRIBUTES + COST_ACTIVITY_SQL_ATTRIBUTES).split():
        if name.startswith("IS") or name in {
            "AVAILABILITYCONTROLISACTIVE", "CONSUMPTIONQTYISRECORDED", "COSTCENTERISCOMPLETE",
            "FUNCTIONALAREAISFIXASSIGNED", "FUNDISFIXASSIGNED", "GRANTIDISFIXASSIGNED",
            "PROFITCENTERISBLOCKED",
            "ACTIVITYTYPEISBLOCKED", "ACTUALQUANTITYISSETMANUALLY", "COSTCTRACTYTYPEISCTRLGRLVTCOMP",
            "COSTCTRACTYTYPEISHUMRSCERLVT", "FIXEDCOSTISPREDISTRIBUTED", "PERIODPRICEISAVERAGE",
            "PLANQUANTITYISSETMANUALLY",
        }:
            types[name] = ("CHAR", 1, 0)
    return types


def _definitions(objects: dict) -> dict[str, Object]:
    if set(objects) != set(SOURCE_COLUMNS):
        raise ValueError(f"Uncovered native objects: {set(objects) ^ set(SOURCE_COLUMNS)}")
    types = _field_types()
    result = {}
    for name, (role, keys, _delta, _related) in objects.items():
        columns = SOURCE_COLUMNS[name].split()
        if len(columns) != len(set(columns)):
            raise ValueError(f"{name}: duplicate source whitelist columns")
        if set(keys) - set(columns):
            raise ValueError(f"{name}: uncovered native keys {set(keys) - set(columns)}")
        ordered = list(keys) + sorted(set(columns) - set(keys))
        fields = []
        for column in ordered:
            if column in NOT_SOURCE or column.startswith("_") or column not in types:
                raise ValueError(f"{name}: uncovered or Gold-only source column {column}")
            ddic, length, scale = types[column]
            fields.append(NativeField(
                column, ddic, length, scale, column in keys, column not in keys,
                column in INITIAL_KEYS,
            ))
        result[name] = Object(name, tuple(fields), financial=role == "FACT")
    for name, obj in PR1_SCHEMAS.items():
        if name.startswith("ZMSF_"):
            result[name] = Object(name, tuple(NativeField(**asdict(f)) for f in obj.fields), obj.financial)
    result["DD03ND"] = Object("DD03ND", (
        NativeField("STRUCOBJN", "CHAR", 128, key=True),
        NativeField("FIELDNAME", "CHAR", 128, key=True),
        NativeField("DATATYPE", "CHAR", 4),
        NativeField("LENG", "NUMC", 6),
        NativeField("DECIMALS", "NUMC", 6),
    ))
    return result


def _parse_list(value: object, label: str) -> list:
    try:
        result = ast.literal_eval(value) if isinstance(value, str) else value
    except (ValueError, SyntaxError) as exc:
        raise ValueError(f"Invalid native {label}") from exc
    if not isinstance(result, list):
        raise ValueError(f"Invalid native {label}: expected a list")
    return result


@dataclass
class NativeContract:
    schemas: dict[str, Object]
    objects: dict
    joins: list
    provenance: dict
    excluded_relationships: list

    def validate_schema(self) -> None:
        expected = _definitions(self.objects)
        if set(expected) != set(self.schemas):
            raise ValueError("Uncovered native object schemas")
        for name, obj in self.schemas.items():
            declared = {f.name: f for f in expected[name].fields}
            if len(obj.fields) != len(declared) or {f.name for f in obj.fields} != set(declared):
                raise ValueError(f"{name}: uncovered/unknown native source columns")
            if obj.financial != expected[name].financial:
                raise ValueError(f"{name}: conflicting native financial deletion policy")
            for f in obj.fields:
                definition = declared[f.name]
                if (f.ddic, f.length, f.scale) != (definition.ddic, definition.length, definition.scale):
                    raise ValueError(f"{name}.{f.name}: native schema type conflict")
                arrow_type(f)
        for name, (role, keys, delta, related) in self.objects.items():
            if role not in {"FACT", "DIMENSION", "DIMENSION-TD", "TEXT", "HIERARCHY"}:
                raise ValueError(f"{name}: unsupported native role {role}")
            if not isinstance(delta, bool) or not keys or len(keys) != len(set(keys)):
                raise ValueError(f"{name}: invalid native keys/delta")
            if self.schemas[name].keys != tuple(keys):
                raise ValueError(f"{name}: uncovered native keys")
            if related:
                if role != "TEXT" or related not in self.schemas:
                    raise ValueError(f"{name}: uncovered related CDS view {related}")
                if set(self.schemas[related].keys) - set(keys) - {"PARENTNODE", "HIERARCHYVERSION", "CHARTOFACCOUNTS"}:
                    raise ValueError(f"{name}: incomplete text-to-dimension keys")
        for fact, dimension, conditions, extra, _sk in self.joins:
            if fact not in self.schemas or dimension not in self.schemas:
                raise ValueError(f"Uncovered native relationship: {fact} -> {dimension}")
            if self.objects[fact][0] != "FACT" or not conditions:
                raise ValueError(f"Invalid native fact relationship {fact} -> {dimension}")
            left = {f.name: f for f in self.schemas[fact].fields}
            right = {f.name: f for f in self.schemas[dimension].fields}
            for condition in conditions:
                if len(condition) != 3:
                    raise ValueError("Invalid native join condition")
                a, b, comparison = condition
                if a not in left or b not in right or comparison not in {"==", ">=", "<="}:
                    raise ValueError(f"Uncovered native join columns/operator: {fact}.{a} -> {dimension}.{b}")
                if _bps_type(left[a]) != _bps_type(right[b]):
                    raise ValueError(f"Native join type conflict: {fact}.{a} -> {dimension}.{b}")
            if set(extra) - set(right):
                raise ValueError(f"{dimension}: uncovered native dimension projections {set(extra) - set(right)}")

    def manifest(self) -> dict:
        return {
            "version": SCHEMA_VERSION, "native_bps_ready": False,
            "compatibility": {
                "scope": "LOCAL_ASSERTED_ONLY", "pipeline_qualified": False,
                "native_objects_covered": len(self.objects), "source_schema_validated": True,
                "in_scope_relationships": len(self.joins),
                "excluded_global_relationships": self.excluded_relationships,
            },
            "provenance": self.provenance,
            "currency_projection": CURRENCIES,
            "signed_journal": "S amounts are positive, H amounts negative; native credit aggregate is sum(H, -amount).",
            "initial_value_policy": "Only explicitly whitelisted raw attributes receive SAP initials; unused business dimensions are empty, without placeholder rows.",
            "source_types": "NUMC is a zero-padded source string; BPS casts it to IntegerType on BOTH join partners. CHAR IDs remain full strings.",
            "text_policy": "Raw SAP languages E/F; native B2S normalizes them to en/fr. No Key, ISO language, pivot or calculated Gold column is emitted.",
            "gates": [
                "Qualify actual Datasphere/mirror ingestion and the deployed B2S/S2G pipelines; local checks are not successful cloud runs.",
                "Verify native non-delta generate_table_from_text routing against deployed library/notebook; raw mirrored dimensions do not imply an unsupported template escape.",
                "Qualify typed empty dimension creation/processing in the native pipeline; no fake business placeholders are supplied for unused assets, equipment, plants or employees.",
                "Qualify signed billing credit memo treatment in the native Billing insight; no completed Gold report is claimed.",
                "Register custom ZMSF relationships or use a separately declared curated MSFlixGold path; native datasets do not automatically consume custom objects.",
            ],
            "objects": {
                name: {
                    "keys": list(obj.keys), "financial_deletes_allowed": not obj.financial,
                    "coverage": "custom_simulation" if name.startswith("ZMSF_") else "native_source_projection",
                    "native_metadata": self.objects.get(name),
                    "fields": [asdict(f) for f in obj.fields],
                } for name, obj in self.schemas.items()
            },
            "joins": self.joins,
        }


def _bps_type(f: Field) -> tuple:
    if f.ddic == "NUMC":
        return ("integer",)
    if f.ddic in ("CHAR", "LANG", "CUKY", "UNIT"):
        return ("string", f.length)
    return (f.ddic, f.length, f.scale)


def load_contract(metadata_path: Path | None = None) -> NativeContract:
    bundled = read_json(INPUT_CONTRACT)
    if bundled["version"] != 1:
        raise ValueError("Unsupported native input contract version")
    objects = deepcopy(bundled["objects"])
    joins = deepcopy(bundled["joins"])
    provenance = deepcopy(bundled["provenance"])
    provenance["whitelist_version"] = SCHEMA_VERSION
    provenance["vendored_contract_sha256"] = digest(INPUT_CONTRACT.read_bytes())
    provenance["adapter_sha256"] = digest(Path(__file__).read_bytes())
    provenance["pr1_input_sha256"] = {
        name: digest((Path(__file__).parent / name).read_bytes())
        for name in ("accounting.py", "config.py", "schema.py", "scenario.py")
    }
    excluded = [{
        "reason": "Fact not in the 85 activated native objects",
        "count": provenance["global_join_count"] - len(joins),
        "inventory": "Bundled contract retains the scoped relationships; supply captured native-contract.json for exact global relationship inventory.",
    }]
    if metadata_path is not None:
        raw = read_json(Path(metadata_path))
        observed = {}
        custom = {}
        for row in raw["objects"]:
            name = row["CDSViewName"]
            definition = [row["Type"], _parse_list(row["KeyFields"], "keys"), row["Delta"], row["relatedCDSViewName"]]
            if name.startswith("ZMSF_"):
                schema = PR1_SCHEMAS.get(name)
                expected = ["FACT" if schema and schema.financial else "DIMENSION",
                            list(schema.keys) if schema else [], bool(schema and schema.financial), ""]
                if schema is None or definition != expected:
                    raise ValueError(f"{name}: custom native registration differs from its source contract")
                if name in custom and custom[name] != definition:
                    raise ValueError(f"{name}: conflicting custom registration")
                custom[name] = definition
                continue
            if name in observed and observed[name] != definition:
                raise ValueError(f"{name}: conflicting duplicate native roles/keys")
            observed[name] = definition
        if observed != objects:
            raise ValueError("Uncovered native objects, keys, roles, delta or related CDS views; update the explicit input contract")
        joins, excluded = [], []
        for row in raw["joins"]:
            fact = row["FactTable"]
            if fact not in objects:
                excluded.append({
                    "fact": fact, "dimension": row["DimensionTable"],
                    "relationship": row["RelationshipName"],
                    "reason": "Fact not in activated native object scope",
                })
                continue
            joins.append([
                fact, row["DimensionTable"],
                [list(c) for c in _parse_list(row["JoinCondition"], "conditions")],
                _parse_list(row["DimColumns"], "dimension projections"), row["SKColumn"],
            ])
        for column in raw["columns"]:
            raise ValueError(f"Unexpected native fieldMetadata override: {column}; DD03ND owns this version's source types")
        provenance.update(
            actual_metadata_sha256=digest(Path(metadata_path).read_bytes()),
            native_metadata_rows=len(raw["objects"]), global_join_count=len(raw["joins"]),
            custom_registrations=custom,
        )
        if sorted(json_bytes(j) for j in joins) != sorted(json_bytes(j) for j in bundled["joins"]):
            raise ValueError("Uncovered native relationships/projections; update the explicit input contract")
    contract = NativeContract(_definitions(objects), objects, joins, provenance, excluded)
    contract.validate_schema()
    return contract


def dd03nd_rows(schemas: dict[str, Object]) -> list[dict]:
    return [
        {"STRUCOBJN": name, "FIELDNAME": f.name, "DATATYPE": f.ddic,
         "LENG": f"{f.length:06d}", "DECIMALS": f"{f.scale:06d}"}
        for name, obj in schemas.items() for f in obj.fields
    ]


def _initial(f: Field):
    if f.ddic == "DATS":
        return None
    if f.ddic == "NUMC":
        return "0" * f.length
    if f.ddic in ("CURR", "DEC", "QUAN"):
        return ZERO.quantize(Decimal(1).scaleb(-f.scale))
    if f.ddic in ("INT4", "INT8"):
        return 0
    return ""


def _complete(obj: Object, supplied: dict) -> dict:
    known = {f.name for f in obj.fields}
    if set(supplied) - known:
        raise ValueError(f"{obj.name}: unknown source columns {set(supplied) - known}")
    if set(obj.keys) - set(supplied):
        raise ValueError(f"{obj.name}: missing source keys {set(obj.keys) - set(supplied)}")
    row = {}
    for f in obj.fields:
        value = supplied[f.name] if f.name in supplied else _initial(f)
        # PR1 represents unassigned numeric invoice references as empty strings.
        # Native NUMC must be numeric on ingestion; a null preserves unassignment.
        if f.ddic == "NUMC" and value == "" and f.name in {"INVOICEREFERENCEFISCALYEAR", "INVOICEITEMREFERENCE"}:
            value = None
        row[f.name] = value
    obj.index([row])
    return row


def _master(base: Snapshot, config: dict, contract: NativeContract) -> dict[str, list[dict]]:
    tables = {name: [] for name in contract.schemas}
    start, end = period(config)
    high, low = date(9999, 12, 31), date(start.year, 1, 1)
    company = config["company_code"]
    controlling, cost, profit, business, segment = "MSFX", "MSFSTREAM", "MSFSVOD", "MSFX", "MSFSVOD"

    def add(name, **values):
        tables[name].append(_complete(contract.schemas[name], values))

    def texts(name, keys, english, french=None, **values):
        name_fields = [f.name for f in contract.schemas[name].fields if f.name.endswith("NAME") or f.name in {
            "HIERARCHYNODETEXT", "PRODUCTDESCRIPTION", "GLACCOUNTLONGNAME",
        }]
        for language, label in (("E", english), ("F", french or english)):
            add(name, **{**keys, "LANGUAGE": language, **{field: label for field in name_fields}, **values})

    def simple(dim, text, key, values, **attributes):
        for code, labels in values.items():
            add(dim, **{key: code}, **attributes)
            if text:
                texts(text, {key: code}, *labels)

    for name in tables:
        if name.startswith("ZMSF_"):
            tables[name] = deepcopy(base.tables[name])
    add("I_COMPANYCODE", **base.tables["I_COMPANYCODE"][0], COMPANY=company,
        CONTROLLINGAREA=controlling, LANGUAGE="E")
    add("I_CHARTOFACCOUNTS", **base.tables["I_CHARTOFACCOUNTS"][0])
    texts("I_CHARTOFACCOUNTSTEXT", {"CHARTOFACCOUNTS": CHART},
          "MSFlix operational accounts", "Comptes opérationnels MSFlix")
    add("I_GLOBALCOMPANY", COMPANY=company, COMPANYNAME=config["company_name"], COUNTRY="FR", CURRENCY="EUR", LANGUAGE="E")
    add("I_CONTROLLINGAREA", CONTROLLINGAREA=controlling, CONTROLLINGAREANAME="MSFlix SVOD controlling",
        CONTROLLINGAREACURRENCY="EUR", CONTROLLINGAREACURRENCYROLE="20", CHARTOFACCOUNTS=CHART,
        FISCALYEARVARIANT="K4", OPERATINGCONCERN="")
    simple("I_BUSINESSAREA", "I_BUSINESSAREATEXT", "BUSINESSAREA", {business: ("MSFlix streaming", "Streaming MSFlix")})
    simple("I_FUNCTIONALAREA", "I_FUNCTIONALAREATEXT", "FUNCTIONALAREA", {"SVOD": ("Subscription streaming", "Streaming par abonnement")})
    simple("I_SEGMENT", "I_SEGMENTTEXT", "SEGMENT", {segment: ("MSFlix SVOD", "MSFlix SVOD")})
    add("I_COSTCENTER", CONTROLLINGAREA=controlling, COSTCENTER=cost, VALIDITYENDDATE=high, VALIDITYSTARTDATE=low,
        COMPANYCODE=company, BUSINESSAREA=business, FUNCTIONALAREA="SVOD", PROFITCENTER=profit,
        COSTCENTERCURRENCY="EUR", COSTCENTERCATEGORY="W", COSTCENTERSTANDARDHIERAREA="MSF_COSTS", COUNTRY="FR", LANGUAGE="E")
    texts("I_COSTCENTERTEXT", {"CONTROLLINGAREA": controlling, "COSTCENTER": cost, "VALIDITYENDDATE": high},
          "MSFlix streaming operations", "Opérations streaming MSFlix")
    add("I_PROFITCENTER", CONTROLLINGAREA=controlling, PROFITCENTER=profit, VALIDITYENDDATE=high, VALIDITYSTARTDATE=low,
        COMPANYCODE=company, COUNTRY="FR", SEGMENT=segment, LANGUAGE="E", PROFITCENTERSTANDARDHIERARCHY="MSF_PROFIT")
    texts("I_PROFITCENTERTEXT", {"CONTROLLINGAREA": controlling, "PROFITCENTER": profit, "VALIDITYENDDATE": high},
          "MSFlix subscription portfolio", "Portefeuille abonnements MSFlix")
    for row in base.tables["I_CUSTOMER"]:
        add("I_CUSTOMER", **row, CUSTOMERFULLNAME=row["CUSTOMERNAME"])
    for row in base.tables["I_SUPPLIER"]:
        add("I_SUPPLIER", **row, SUPPLIERFULLNAME=row["SUPPLIERNAME"])
    for number, name, kind in ACCOUNTS.values():
        add("I_GLACCOUNTINCHARTOFACCOUNTS", CHARTOFACCOUNTS=CHART, GLACCOUNT=number, GLACCOUNTTYPE=kind,
            ISBALANCESHEETACCOUNT="X" if kind == "X" else "", ISPROFITLOSSACCOUNT="X" if kind == "P" else "",
            GLACCOUNTGROUP="BS" if kind == "X" else "PL")
        texts("I_GLACCOUNTTEXT", {"CHARTOFACCOUNTS": CHART, "GLACCOUNT": number}, name)
    add("I_LEDGER", LEDGER="0L", ISLEADINGLEDGER="X")
    texts("I_LEDGERTEXT", {"LEDGER": "0L"}, "MSFlix leading ledger", "Grand livre principal MSFlix")
    add("I_PRODUCT", PRODUCT=config["plan_id"], PRODUCTTYPE="SERV", PRODUCTGROUP="SVOD", BASEUNIT="MON")
    texts("I_PRODUCTDESCRIPTION", {"PRODUCT": config["plan_id"]}, config["plan_name"])
    simple("I_PRODUCTGROUP_2", "I_PRODUCTGROUPTEXT_2", "PRODUCTGROUP", {"SVOD": ("Monthly SVOD", "SVOD mensuel")})
    simple("I_CUSTOMERGROUP", "I_CUSTOMERGROUPTEXT", "CUSTOMERGROUP", {"SV": ("SVOD subscribers", "Abonnés SVOD")})
    simple("I_DISTRIBUTIONCHANNEL", "I_DISTRIBUTIONCHANNELTEXT", "DISTRIBUTIONCHANNEL", {"01": ("Online streaming", "Streaming en ligne")})
    simple("I_DIVISION", "I_DIVISIONTEXT", "DIVISION", {"01": ("SVOD service", "Service SVOD")})
    add("I_SALESORGANIZATION", SALESORGANIZATION=company, COMPANYCODE=company, SALESORGANIZATIONCURRENCY="EUR")
    texts("I_SALESORGANIZATIONTEXT", {"SALESORGANIZATION": company}, "MSFlix subscription sales", "Ventes abonnements MSFlix")
    for row in base.tables["I_FISCALPERIODFORVARIANT"]:
        month, year = int(row["FISCALPERIOD"]), int(row["FISCALYEAR"])
        add("I_FISCALPERIODFORVARIANT", **row, NEXTFISCALPERIOD=f"{month % 12 + 1:03d}",
            NEXTFISCALPERIODFISCALYEAR=f"{year + (month == 12):04d}")
    add("I_FISCALYEARVARIANT", FISCALYEARVARIANT="K4", NUMBEROFPOSTINGPERIODS="012",
        NUMBEROFSPECIALPERIODS="0", FISCALYEARISCALENDARYEAR="X")
    add("I_FISCALYEARFORCOMPANYCODE", COMPANYCODE=company, FISCALYEAR=f"{start.year:04d}",
        FISCALYEARSTARTDATE=low, FISCALYEARENDDATE=date(start.year, 12, 31))
    for language in ("E", "F"):
        add("I_LANGUAGE", LANGUAGE=language, LANGUAGECODE=language)
    for described, labels in {"E": ("English", "Anglais"), "F": ("French", "Français")}.items():
        texts("I_LANGUAGETEXT", {"LANGUAGECODE": described}, *labels)
    kinds = {
        "DR": ("Customer invoice", "Facture client"), "DG": ("Customer credit", "Avoir client"),
        "DZ": ("Customer collection", "Encaissement client"), "DA": ("Customer refund", "Remboursement client"),
        "SA": ("Revenue recognition", "Reconnaissance de revenu"), "KR": ("Supplier invoice", "Facture fournisseur"),
        "KZ": ("Supplier payment", "Paiement fournisseur"),
    }
    simple("I_ACCOUNTINGDOCUMENTTYPE", "I_ACCOUNTINGDOCUMENTTYPETEXT", "ACCOUNTINGDOCUMENTTYPE", kinds,
           ACCOUNTINGDOCUMENTNUMBERRANGE="90", ALLOWEDFINANCIALACCOUNTTYPES="DKS")
    for code, labels, category in (
        ("F2", ("SVOD invoice", "Facture SVOD"), "M"), ("G2", ("SVOD credit memo", "Avoir SVOD"), "O"),
    ):
        add("I_BILLINGDOCUMENTTYPE", BILLINGDOCUMENTTYPE=code, BILLINGDOCUMENTCATEGORY=category, SDDOCUMENTCATEGORY=category)
        texts("I_BILLINGDOCUMENTTYPETEXT", {"BILLINGDOCUMENTTYPE": code}, *labels)
    simple("I_DEBITCREDITCODE", "I_DEBITCREDITCODETEXT", "DEBITCREDITCODE",
           {"S": ("Debit", "Débit"), "H": ("Credit", "Crédit")})
    simple("I_ACCOUNTINGDOCUMENTCATEGORY", "I_ACCOUNTINGDOCUMENTCATEGORYT", "ACCOUNTINGDOCUMENTCATEGORY",
           {"": ("Normal accounting document", "Document comptable normal")})
    simple("I_SPECIALGLCODE", "I_SPECIALGLCODETEXT", "SPECIALGLCODE",
           {"": ("Normal AR/AP posting", "Écriture client/fournisseur normale")}, ISNOTEDITMWITHOUTBALUPDT="")
    simple("I_PAYMENTBLOCKINGREASON", "I_PAYMENTBLOCKINGREASONTEXT", "PAYMENTBLOCKINGREASON",
           {"": ("No payment block", "Aucun blocage de paiement")})
    simple("I_BILLINGPLANRULE", "I_BILLINGPLANRULETEXT", "BILLINGPLANRULE",
           {"": ("No SAP billing plan", "Aucun échéancier SAP")})
    simple("I_OVERALLBILLINGSTATUS", "I_OVERALLBILLINGSTATUSTEXT", "OVERALLBILLINGSTATUS",
           {"C": ("Fully billed", "Entièrement facturé")}, DOMAINVALUE="C")
    terms = {
        "": ("Not applicable", "Sans objet"), "0007": ("Net 7 days", "Échéance à 7 jours"),
        "0030": ("Net 30 days", "Échéance à 30 jours"),
    }
    simple("I_PAYMENTTERMS", "I_PAYMENTTERMSTEXT", "PAYMENTTERMS", terms)
    simple("I_CUSTOMERPAYMENTTERMS", "I_CUSTOMERPAYMENTTERMSTEXT", "CUSTOMERPAYMENTTERMS", terms)
    simple("I_DUNNINGKEY", "I_DUNNINGKEYTEXT", "DUNNINGKEY",
           {"": ("No special dunning rule", "Aucune règle de relance spécifique")}, MAXIMUMDUNNINGLEVEL="0")
    add("I_DUNNINGAREA", COMPANYCODE=company, DUNNINGAREA="")
    texts("I_DUNNINGAREATEXT", {"COMPANYCODE": company, "DUNNINGAREA": ""},
          "No separate dunning area", "Aucun domaine de relance distinct", COMPANYCODENAME=config["company_name"])
    for key, account_type, debit, label in (
        ("01", "D", "S", "Customer debit"), ("11", "D", "H", "Customer credit"),
        ("15", "D", "H", "Customer collection"), ("21", "K", "S", "Supplier debit"),
        ("25", "K", "S", "Supplier payment"), ("31", "K", "H", "Supplier invoice"),
        ("40", "S", "S", "GL debit"), ("50", "S", "H", "GL credit"),
    ):
        add("I_POSTINGKEY", POSTINGKEY=key, DEBITCREDITCODE=debit, FINANCIALACCOUNTTYPE=account_type,
            REVERSALPOSTINGKEY={"01": "11", "11": "01", "15": "01", "21": "31", "25": "31", "31": "21", "40": "50", "50": "40"}[key],
            ISSALESRELATED="X" if account_type == "D" else "", ISSPECIALGLTRANSACTION="",
            ISUSEDINPAYMENTTRANSACTION="X" if key in {"15", "25"} else "")
        texts("I_POSTINGKEYTEXT", {"POSTINGKEY": key}, label)

    def hierarchy(kind, hierarchy_name, leaves):
        table, text = f"I_{kind}HIERARCHYNODE", f"I_{kind}HIERARCHYNODET"
        identity = {f"{kind}HIERARCHY": hierarchy_name}
        if kind == "GLACCOUNT":
            identity.update(CHARTOFACCOUNTS=CHART, HIERARCHYVERSION="0001")
        else:
            identity["CONTROLLINGAREA"] = controlling
        for node, parent, node_type, business_key, label in [
            ("MSFLIX", "", "R", "", "MSFlix SVOD business"),
            ("MSF_FINANCE", "MSFLIX", "N", "", "MSFlix subscription finance"),
            *[(f"MSF_{key}", "MSF_FINANCE", "L", key, label) for key, label in leaves],
        ]:
            add(table, **identity, HIERARCHYNODE=node, PARENTNODE=parent, NODETYPE=node_type,
                VALIDITYSTARTDATE=low, VALIDITYENDDATE=high, **{kind: business_key})
            text_keys = {key: value for key, value in {
                **identity, "HIERARCHYNODE": node, "VALIDITYENDDATE": high,
            }.items() if key in contract.schemas[text].keys}
            texts(text, text_keys, label)
    hierarchy("GLACCOUNT", "MSF_FINANCE", [(number, name) for number, name, _kind in ACCOUNTS.values()])
    hierarchy("COSTCENTER", "MSF_COSTS", [(cost, "MSFlix streaming operations")])
    hierarchy("PROFITCENTER", "MSF_PROFIT", [(profit, "MSFlix SVOD portfolio")])
    tables["DD03ND"] = dd03nd_rows(contract.schemas)
    return tables


def _facts(base: Snapshot, config: dict, contract: NativeContract, tables: dict) -> None:
    common = {
        "CONTROLLINGAREA": "MSFX", "BUSINESSAREA": "MSFX", "COSTCENTER": "MSFSTREAM",
        "PROFITCENTER": "MSFSVOD", "PRODUCTGROUP": "SVOD",
    }
    for name in FINANCIAL_FACTS:
        for original in base.tables[name]:
            row = deepcopy(original)
            row.update(common)
            if name.startswith("C_"):
                row.update(
                    PAYERPARTY=row["SOLDTOPARTY"], BILLTOPARTY=row["SOLDTOPARTY"], SHIPTOPARTY=row["SOLDTOPARTY"],
                    BILLINGPLANRULE="", CUSTOMERGROUP="SV", DISTRIBUTIONCHANNEL="01", DIVISION="01",
                    FISCALYEARVARIANT="K4", FISCALPERIOD=f"{row['BILLINGDOCUMENTDATE'].month:03d}",
                    OVERALLBILLINGSTATUS="C", SALESEMPLOYEE="", PLANT="",
                    SALESORGANIZATION=config["company_code"], SHIPPINGPOINT="", CURRENCY="EUR",
                    SALESORGANIZATIONCURRENCY="EUR", BILLINGQUANTITY=Decimal("1.000"),
                    BILLINGQUANTITYINBASEUNIT=Decimal("1.000"), BILLINGQUANTITYUNIT="MON", BASEUNIT="MON",
                    BILLINGDOCUMENTITEMTEXT="Monthly SVOD credit" if row["NETAMOUNT"] < 0 else "Monthly SVOD subscription",
                )
            else:
                row.update(
                    ACCOUNTINGDOCUMENTCATEGORY="", SPECIALGLCODE="", FUNCTIONALAREA="SVOD", SEGMENT="MSFSVOD",
                    COMPANY=config["company_code"], PARTNERCOMPANY="", CUSTOMERGROUP="SV",
                    PRODUCT=config["plan_id"], FISCALYEARPERIOD=row["FISCALYEAR"] + row["FISCALPERIOD"],
                    LEDGERFISCALYEAR=row["FISCALYEAR"], GLOBALCURRENCY="EUR",
                    AMOUNTINGLOBALCURRENCY=row["AMOUNTINTRANSACTIONCURRENCY"],
                    PAYMENTTERMS={"D": "0007", "K": "0030", "S": ""}[row["FINANCIALACCOUNTTYPE"]],
                    PAYMENTBLOCKINGREASON="", DUNNINGAREA="", DUNNINGKEY="",
                    PARTNERCOMPANYCODE="", TAXCODE="", TAXCOUNTRY="FR",
                    ISOPENITEMMANAGED="X" if row["FINANCIALACCOUNTTYPE"] in {"D", "K"} else "",
                )
                for code, amount in CURRENCIES.values():
                    row[code] = "EUR"
                    row[amount] = original["AMOUNTINTRANSACTIONCURRENCY"]
            tables[name].append(_complete(contract.schemas[name], row))


@dataclass
class NativeScenario(Scenario):
    native_contract: NativeContract

    @property
    def schemas(self):
        return self.native_contract.schemas


def build(config: dict, references: dict, *, metadata_path: Path | None = None) -> NativeScenario:
    contract = load_contract(metadata_path)
    original = build_pr1(config, references)
    snapshots = []
    for base in original.snapshots:
        tables = _master(base, config, contract)
        _facts(base, config, contract, tables)
        validate_snapshot(tables, contract, config, references)
        snapshots.append(Snapshot(base.label, base.timestamp, tables, deepcopy(base.summary)))
    return NativeScenario(deepcopy(config), deepcopy(references), snapshots, deepcopy(original.documents), contract)


def _cast(value, f: Field):
    if f.ddic == "NUMC" and value is not None:
        return int(value)
    return value


def _unassigned(value, f: Field) -> bool:
    return value is None or value == "" or (f.ddic == "NUMC" and int(value) == 0)


def resolve_relationships(tables: dict, contract: NativeContract) -> dict:
    comparisons = {"==": operator.eq, ">=": operator.ge, "<=": operator.le}
    statistics = {}
    for fact, dimension, conditions, extra, sk in contract.joins:
        left = {f.name: f for f in contract.schemas[fact].fields}
        right = {f.name: f for f in contract.schemas[dimension].fields}
        relevant = [a for a, _b, _op in conditions if a in UNASSIGNED_RELATIONS.get(dimension, set())]
        matched, unassigned = 0, 0
        for row in tables[fact]:
            if relevant and all(_unassigned(row[name], left[name]) for name in relevant):
                unassigned += 1
                continue
            matches = []
            for target in tables[dimension]:
                valid = True
                for a, b, comparison in conditions:
                    x, y = _cast(row[a], left[a]), _cast(target[b], right[b])
                    if x is None or y is None or not comparisons[comparison](x, y):
                        valid = False
                        break
                if valid:
                    # Native TD joins omit date ranges: one dimension version only
                    # avoids fan-out while still retaining proper source validity.
                    matches.append(target)
            if len(matches) != 1:
                raise ValueError(f"Unresolved or ambiguous native foreign key: {fact} -> {dimension} ({sk}), {len(matches)} matches")
            for column in extra:
                if column in row and row[column] != matches[0][column]:
                    raise ValueError(f"{fact}: conflicting native projected column {column}")
            matched += 1
        statistics[f"{fact}:{sk}"] = {"matched": matched, "unassigned": unassigned}
    return statistics


def validate_snapshot(tables: dict, contract: NativeContract, config: dict, references: dict) -> None:
    contract.validate_schema()
    if set(tables) != set(contract.schemas):
        raise ValueError("Native snapshot must contain exactly all declared source objects")
    for name, obj in contract.schemas.items():
        obj.index(tables[name])
    if tables["DD03ND"] != dd03nd_rows(contract.schemas):
        raise ValueError("DD03ND does not match every exported source field")
    for name in EMPTY_OBJECTS:
        if tables[name]:
            raise ValueError(f"{name}: unrelated business dimension must remain honestly empty")
    resolve_relationships(tables, contract)
    for name, (role, _keys, _delta, related) in contract.objects.items():
        if role != "TEXT":
            continue
        base_keys = [key for key in contract.schemas[related].keys if key in contract.schemas[name].keys]
        parents = {tuple(r[k] for k in base_keys) for r in tables[related]}
        for row in tables[name]:
            if row["LANGUAGE"] not in {"E", "F"} or tuple(row[k] for k in base_keys) not in parents:
                raise ValueError(f"{name}: unresolved native raw text dimension keys/language")
    journal = tables["I_OPERATIONALACCTGDOCITEM"]
    gl = tables["I_GLACCOUNTLINEITEMRAWDATA"]
    shared = set(SOURCE_COLUMNS["I_OPERATIONALACCTGDOCITEM"].split())
    def journal_key(row):
        return tuple(row[key] for key in ("COMPANYCODE", "FISCALYEAR", "ACCOUNTINGDOCUMENT", "ACCOUNTINGDOCUMENTITEM"))
    if len({journal_key(r) for r in gl}) != len(gl) or len(gl) != len(journal):
        raise ValueError("Native GL must be a one-to-one journal projection")
    if any(r["SOURCELEDGER"] != "0L" or r["LEDGERGLLINEITEM"] != r["ACCOUNTINGDOCUMENTITEM"].zfill(6) for r in gl):
        raise ValueError("Native GL ledger/line IDs must preserve the journal projection")
    if {journal_key(r): {k: r[k] for k in shared} for r in journal} != {
        journal_key(r): {k: r[k] for k in shared} for r in gl
    }:
        raise ValueError("Native GL and AR/AP must contain the same signed journal")
    totals = defaultdict(lambda: ZERO)
    documents = {journal_key(r)[:3] for r in journal}
    for row in journal:
        value = row["AMOUNTINTRANSACTIONCURRENCY"]
        if row["DEBITCREDITCODE"] != ("S" if value > ZERO else "H") or value == ZERO:
            raise ValueError("Native journal requires signed S/H nonzero amounts")
        for code, amount in CURRENCIES.values():
            if row[code] != "EUR" or row[amount] != value:
                raise ValueError("Native four-currency EUR projections must preserve signed journal amounts")
        totals[journal_key(row)[:3]] += value
        if row["CLEARINGDATE"] is not None:
            clearing = (row["COMPANYCODE"], row["CLEARINGDOCFISCALYEAR"], row["CLEARINGACCOUNTINGDOCUMENT"])
            if clearing not in documents or row["CLEARINGDATE"] < row["POSTINGDATE"]:
                raise ValueError("Unresolved or invalid native clearing document/date")
    if any(totals.values()):
        raise ValueError("Native accounting documents must balance")
    customers = {r["CUSTOMER"] for r in tables["I_CUSTOMER"]}
    suppliers = {r["SUPPLIER"] for r in tables["I_SUPPLIER"]}
    reference_customers = {r["customer_key"]: r["salesforce_contact_id"] for r in references["customers"]}
    selected = {r["sap_customer"]: r["customer_key"] for r in config["customers"]}
    links = tables["ZMSF_CUSTOMER_LINK"]
    if len(links) != len(selected) or {r["CUSTOMER"] for r in links} != customers:
        raise ValueError("Incomplete native customer crosswalk")
    for row in links:
        if selected.get(row["CUSTOMER"]) != row["CUSTOMER_KEY"] or reference_customers.get(row["CUSTOMER_KEY"]) != row["SALESFORCE_CONTACT_ID"]:
            raise ValueError("Native customer crosswalk must preserve actual Salesforce/source IDs")
    rights = {(r["CONTRACT_ID"], r["VERSION"]): r for r in tables["ZMSF_RIGHTS_CONTRACT"]}
    for row in rights.values():
        if row["SUPPLIER"] not in suppliers or row["SIMULATION_ONLY"] != "X":
            raise ValueError("Unresolved or non-simulation rights supplier")
    if any("fictional" not in row["SUPPLIERNAME"].lower() for row in tables["I_SUPPLIER"]):
        raise ValueError("Native supplier must remain explicitly fictional")
    coverage = tables["ZMSF_RIGHTS_COVERAGE"]
    if {r["CONTENT_KEY"] for r in coverage} != set(config["content_keys"]):
        raise ValueError("Native rights coverage must preserve exact content source keys")
    contents = {r["content_key"]: r for r in references["contents"]}
    distributors = {r["distributor_key"]: r for r in references["distributors"]}
    for row in coverage:
        content = contents[row["CONTENT_KEY"]]
        distributor = distributors[content["distributor_key"]]
        if (row["CONTRACT_ID"], row["VERSION"]) not in rights or row["SIMULATION_ONLY"] != "X" or row["USAGE_TYPE"] != "SVOD":
            raise ValueError("Native content rights require a fictional simulated SVOD contract")
        if row["CATALOG_DISTRIBUTOR_KEY"] != content["distributor_key"] or row["CATALOG_SAP_PARTNER_CODE"] != distributor["sap_partner_code"]:
            raise ValueError("Native content/distributor lineage must not be invented")
    plans = {(r["PLAN_ID"], r["VERSION"]): r for r in tables["ZMSF_PLAN"]}
    subscriptions = {r["SUBSCRIPTION_ID"]: r for r in tables["ZMSF_SUBSCRIPTION"]}
    for row in plans.values():
        if (row["CONTRACT_ID"], row["CONTRACT_VERSION"]) not in rights:
            raise ValueError("Unresolved native plan/rights contract")
    for row in subscriptions.values():
        if row["CUSTOMER"] not in customers or (row["PLAN_ID"], row["PLAN_VERSION"]) not in plans:
            raise ValueError("Unresolved native subscription/customer/plan")
    bills = contract.schemas["C_BILLINGDOCITEMBASICDEX_1"].index(tables["C_BILLINGDOCITEMBASICDEX_1"])
    bill_links = contract.schemas["ZMSF_BILLING_LINK"].index(tables["ZMSF_BILLING_LINK"])
    if set(bills) != set(bill_links):
        raise ValueError("Each native bill requires exactly one subscription link")
    for key, row in bills.items():
        link = bill_links[key]
        subscription = subscriptions.get(link["SUBSCRIPTION_ID"])
        if subscription is None or subscription["CUSTOMER"] != row["SOLDTOPARTY"]:
            raise ValueError("Unresolved native billing/subscription/customer")
        if (row["COMPANYCODE"], row["FISCALYEAR"], row["ACCOUNTINGDOCUMENT"]) not in documents:
            raise ValueError("Unresolved native billing/accounting document")
        original = link["ORIGINAL_BILLINGDOCUMENT"]
        if original is not None and (original, "000010") not in bills:
            raise ValueError("Unresolved native credit/original billing document")
        if row["GROSSAMOUNT"] != row["NETAMOUNT"] + row["TAXAMOUNT"]:
            raise ValueError("Native billing net/tax/gross amounts do not reconcile")
    for row in tables["ZMSF_CONTRACT_CHARGE"]:
        if (row["CONTRACT_ID"], row["VERSION"]) not in rights or (
            row["COMPANYCODE"], row["FISCALYEAR"], row["ACCOUNTINGDOCUMENT"]
        ) not in documents:
            raise ValueError("Unresolved native rights charge/accounting document")
    for kind in ("GLACCOUNT", "COSTCENTER", "PROFITCENTER"):
        rows = tables[f"I_{kind}HIERARCHYNODE"]
        nodes = {r["HIERARCHYNODE"]: r for r in rows}
        if len(nodes) != len(rows) or sum(r["NODETYPE"] == "R" for r in rows) != 1:
            raise ValueError(f"{kind}: native hierarchy requires unique nodes and one root")
        dimension = "I_GLACCOUNTINCHARTOFACCOUNTS" if kind == "GLACCOUNT" else f"I_{kind}"
        business_keys = {r[kind] for r in tables[dimension]}
        for row in rows:
            if row["NODETYPE"] not in {"R", "N", "L"} or (
                row["NODETYPE"] == "L" and row[kind] not in business_keys
            ) or (row["NODETYPE"] != "L" and row[kind] != ""):
                raise ValueError(f"{kind}: unresolved native hierarchy business leaf")
            seen = {row["HIERARCHYNODE"]}
            parent = row["PARENTNODE"]
            while parent:
                if parent not in nodes or parent in seen:
                    raise ValueError(f"{kind}: unresolved/cyclic native hierarchy parent")
                seen.add(parent)
                parent = nodes[parent]["PARENTNODE"]
            if row["NODETYPE"] == "R" and row["PARENTNODE"]:
                raise ValueError(f"{kind}: native root must have no parent")


def balance_projection(rows: list[dict], account_type: str) -> dict:
    """Local oracle for the deployed aggregate's signed S/H math, NOT a Gold run."""
    if account_type not in {"D", "K"}:
        raise ValueError("Balance projection requires customer D or supplier K")
    result = {}
    selected = [r for r in rows if r["FINANCIALACCOUNTTYPE"] == account_type]
    for currency_type, (_code, amount) in CURRENCIES.items():
        debit = sum((r[amount] for r in selected if r["DEBITCREDITCODE"] == "S"), ZERO)
        credit = sum((-r[amount] for r in selected if r["DEBITCREDITCODE"] == "H"), ZERO)
        result[currency_type] = {"debit": debit, "credit": credit, "net": debit - credit}
    return result


def arrow_type(f: Field) -> pa.DataType:
    if f.ddic in {"CURR", "QUAN", "DEC"}:
        return pa.decimal128(f.length, f.scale)
    if f.ddic == "DATS":
        return pa.date32()
    if f.ddic in {"INT4", "INT8"}:
        return pa.int32() if f.ddic == "INT4" else pa.int64()
    if f.ddic in {"CHAR", "NUMC", "LANG", "CUKY", "UNIT"}:
        return pa.string()
    raise ValueError(f"Uncovered native DDIC data type {f.ddic}")


def metadata(obj: Object, source_system: str) -> bytes:
    import json
    result = json.loads(pr1_metadata(obj, source_system))
    result["properties"][1]["value"] = uuid.uuid5(
        uuid.NAMESPACE_URL, f"{SCHEMA_VERSION}:{source_system}:{obj.name}",
    ).hex.upper()
    for f, column in zip(obj.fields, result["columns"][3:], strict=True):
        arrow_type(f)
        if f.ddic in {"CURR", "QUAN", "DEC"}:
            column.pop("length", None)
            column.update(dataType="DECIMAL", precision=f.length, scale=f.scale)
            column["properties"][0]["value"] = "decimal"
        elif f.ddic in {"INT4", "INT8"}:
            column.pop("length", None)
            column["dataType"] = "INTEGER" if f.ddic == "INT4" else "BIGINT"
            column["properties"][0]["value"] = "int32" if f.ddic == "INT4" else "int64"
    return json_bytes(result)


def as_table(obj: Object, operations: list[tuple[str, dict]], stamp) -> pa.Table:
    if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
        raise ValueError("Extraction timestamps must be UTC")
    seen, rows = set(), []
    for op, row in operations:
        if op in {"L", "U"}:
            obj.index([row])
        elif op == "X" and not obj.financial and set(row) == set(obj.keys):
            for f in obj.fields:
                if f.key:
                    f.validate(row[f.name])
        else:
            raise ValueError(f"Unsupported native operation {op} for {obj.name}")
        key = tuple(row[name] for name in obj.keys)
        if key in seen:
            raise ValueError("A source batch cannot contain duplicate native keys")
        seen.add(key)
        rows.append({
            "__operation_type": op, "__sequence_number": None, "__timestamp": stamp,
            **{f.name: row.get(f.name) for f in obj.fields},
        })
    schema = pa.schema([
        pa.field("__operation_type", pa.string()), pa.field("__sequence_number", pa.decimal128(20, 0)),
        pa.field("__timestamp", pa.timestamp("us", tz="UTC")),
        *[pa.field(f.name, arrow_type(f), nullable=not f.key) for f in obj.fields],
    ])
    return pa.Table.from_pylist(rows, schema=schema)


def write_package(root: Path, scenario: NativeScenario) -> dict:
    """Native parameterization of PR1's deterministic local Parquet protocol."""
    root = Path(root)
    if not root.is_dir() or any(root.iterdir()):
        raise ValueError("Package staging directory must exist and be empty")
    if not isinstance(scenario, NativeScenario) or not scenario.snapshots:
        raise ValueError("Native package writer requires a nonempty NativeScenario")
    batches, previous = [], None
    source, schemas = scenario.config["source_system"], scenario.schemas
    for snapshot in scenario.snapshots:
        validate_snapshot(snapshot.tables, scenario.native_contract, scenario.config, scenario.references)
        batch = {"label": snapshot.label, "timestamp": snapshot.timestamp, "objects": {}, "summary": snapshot.summary}
        for name, obj in schemas.items():
            index = obj.index(snapshot.tables[name])
            operations = (
                [("L", index[key]) for key in sorted(index)] if previous is None
                else changes(obj, previous.tables[name], snapshot.tables[name])
            )
            folder = root / "datasphere" / source / name
            if previous is None:
                for target in (folder, folder / "initial", folder / "delta"):
                    target.mkdir(parents=True, exist_ok=True)
                    (target / ".sap.partfile.metadata").write_bytes(metadata(obj, source))
            if not operations and previous is not None:
                continue
            fingerprint = digest(json_bytes({"object": name, "time": snapshot.timestamp, "rows": operations}))
            initial = previous is None
            suffix = fingerprint[:33] if initial else f"{snapshot.timestamp:%Y%m%d%H%M%S}-{fingerprint[:24]}-01"
            path = folder / ("initial" if initial else "delta") / f"part-{suffix}.parquet"
            pq.write_table(as_table(obj, operations, snapshot.timestamp), path, compression="snappy")
            if initial:
                (folder / "initial" / "_SUCCESS").write_bytes(b"")
            batch["objects"][name] = {
                "file": path.relative_to(root).as_posix(),
                "loads": sum(op == "L" for op, _ in operations),
                "upserts": sum(op == "U" for op, _ in operations),
                "deletes": sum(op == "X" for op, _ in operations),
            }
        batches.append(batch)
        previous = snapshot
    payloads = {
        "scenario.json": scenario.config, "references.json": scenario.references,
        "contract.json": scenario.native_contract.manifest(), "batches.json": batches,
        "journal.json": scenario.documents, "final-snapshot.json": scenario.snapshots[-1].tables,
        "summary.json": scenario.snapshots[-1].summary,
        "local-validation.json": {
            "scope": "LOCAL_ASSERTED_ONLY", "pipeline_qualified": False,
            "relationships": resolve_relationships(scenario.snapshots[-1].tables, scenario.native_contract),
            "aggregate_math": {
                kind: balance_projection(scenario.snapshots[-1].tables["I_OPERATIONALACCTGDOCITEM"], kind)
                for kind in ("D", "K")
            },
            "empty_objects": sorted(EMPTY_OBJECTS),
        },
    }
    for name, value in payloads.items():
        (root / name).write_bytes(json_bytes(value))
    files = {
        path.relative_to(root).as_posix(): digest(path.read_bytes())
        for path in sorted(root.rglob("*")) if path.is_file()
    }
    manifest = {
        "format_version": 1, "schema_version": SCHEMA_VERSION, "scenario_id": scenario.config["scenario_id"],
        "source_system": source, "synthetic": True, "native_bps_ready": False, "network_operations": 0,
        "compatibility_scope": "LOCAL_ASSERTED_ONLY", "pipeline_qualified": False,
        "native_object_count": len(scenario.native_contract.objects), "object_count": len(schemas),
        "batch_count": len(batches), "files": files, "pyarrow_version": pa.__version__,
        "reference_observed_at": scenario.references["observed_at_utc"],
        "initial_as_of": scenario.snapshots[0].timestamp, "final_as_of": scenario.snapshots[-1].timestamp,
        "provenance": scenario.native_contract.provenance,
        "replay": "Initial L then timestamp-ordered U full-row upserts/X key deletions. Financial deletes prohibited.",
        "publication_warning": "Local staged history only; publish/run qualification is owned by the parent, not this adapter.",
        "commercial_warning": "All SAP transactions and rights terms are fictional simulations; no real Blender/distributor rights contract is claimed.",
    }
    (root / "manifest.json").write_bytes(json_bytes(manifest))
    return manifest


def generate(output: Path, config_path=DEFAULT_CONFIG, references_path=DEFAULT_REFERENCES, *, metadata_path=None) -> dict:
    output = Path(output).absolute()
    if str(output).startswith(("\\\\", "//")) or any(p.is_symlink() or p.is_junction() for p in (output, *output.parents)):
        raise ValueError("Native output must be local and must not traverse links")
    root = REPOSITORY / ".state" / "sap-native"
    output = output.resolve()
    if not output.is_relative_to(root) or output == root:
        raise ValueError("Native output must be a child of this repository's .state/sap-native")
    scenario = build(read_json(Path(config_path)), read_json(Path(references_path)), metadata_path=metadata_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.parent / f".native-pending-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        manifest = write_package(staging, scenario)
        if output.exists():
            if not output.is_dir() or any(p.is_symlink() or p.is_junction() for p in output.rglob("*")):
                raise FileExistsError("Existing native output is not a safe package directory")
            expected = {p.relative_to(staging) for p in staging.rglob("*") if p.is_file()}
            actual = {p.relative_to(output) for p in output.rglob("*") if p.is_file()}
            if actual != expected or any((output / p).read_bytes() != (staging / p).read_bytes() for p in expected):
                raise FileExistsError("Existing native package differs; choose a new output directory")
            status = "unchanged"
        else:
            staging.rename(output)
            status = "created"
        return {"status": status, "output": str(output), "objects": manifest["object_count"],
                "native_objects": manifest["native_object_count"], "summary": scenario.snapshots[-1].summary}
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--references", type=Path, default=DEFAULT_REFERENCES)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--output", type=Path, default=REPOSITORY / ".state" / "sap-native" / "november-2026-native-v1")
    args = parser.parse_args()
    print(json_bytes(generate(args.output, args.config, args.references, metadata_path=args.metadata)).decode(), end="")


if __name__ == "__main__":
    main()
