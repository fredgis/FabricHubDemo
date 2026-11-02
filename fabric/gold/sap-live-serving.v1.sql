-- SAP live serving v1: query-time native state, not historical snapshots.
-- Review schema, mapping cardinality and native marker semantics before use.
-- Nonblank/NULL _Delete markers are unverified, not assumed deleted.
-- Monthly/payment retain SOURCELEDGER; filter 0L for legacy-ledger comparisons.
-- Account roles are the explicit MSFX simulation, not universal SAP classifications.
-- Examples invoice_customer/gl_account_balance preserve measures with cardinality-safe mappings.
IF SCHEMA_ID('sap_live') IS NULL EXEC('CREATE SCHEMA [sap_live]');
-- @batch
CREATE OR ALTER VIEW [sap_live].[gl_line] AS
SELECT s.[ACCOUNTINGDOCUMENT],
       s.[ACCOUNTINGDOCUMENTCATEGORY],
       s.[ACCOUNTINGDOCUMENTITEM],
       s.[ACCOUNTINGDOCUMENTTYPE],
       s.[ADDITIONALCURRENCY1],
       s.[AMOUNTINADDITIONALCURRENCY1],
       s.[AMOUNTINCOMPANYCODECURRENCY],
       s.[AMOUNTINFUNCTIONALCURRENCY],
       s.[AMOUNTINGLOBALCURRENCY],
       s.[AMOUNTINTRANSACTIONCURRENCY],
       s.[BILLINGDOCUMENT],
       s.[BUSINESSAREA],
       s.[CHARTOFACCOUNTS],
       s.[CLEARINGACCOUNTINGDOCUMENT],
       s.[CLEARINGDATE],
       s.[CLEARINGDOCFISCALYEAR],
       s.[COMPANY],
       s.[COMPANYCODE],
       s.[COMPANYCODECURRENCY],
       s.[CONTROLLINGAREA],
       s.[COSTCENTER],
       s.[COSTCTRACTIVITYTYPE],
       s.[CUSTOMER],
       s.[CUSTOMERGROUP],
       s.[DEBITCREDITCODE],
       s.[DOCUMENTDATE],
       s.[DOCUMENTITEMTEXT],
       s.[DUNNINGAREA],
       s.[DUNNINGKEY],
       s.[EQUIPMENT],
       s.[FINANCIALACCOUNTTYPE],
       s.[FISCALPERIOD],
       s.[FISCALYEAR],
       s.[FISCALYEARPERIOD],
       s.[FISCALYEARVARIANT],
       s.[FIXEDASSET],
       s.[FUNCTIONALAREA],
       s.[FUNCTIONALCURRENCY],
       s.[FUNCTIONALLOCATION],
       s.[GLACCOUNT],
       s.[GLOBALCURRENCY],
       s.[INVOICEITEMREFERENCE],
       s.[INVOICEREFERENCE],
       s.[INVOICEREFERENCEFISCALYEAR],
       s.[ISOPENITEMMANAGED],
       s.[LEDGERFISCALYEAR],
       s.[LEDGERGLLINEITEM],
       s.[MASTERFIXEDASSET],
       s.[NETDUEDATE],
       s.[PARTNERCOMPANY],
       s.[PARTNERCOMPANYCODE],
       s.[PAYMENTBLOCKINGREASON],
       s.[PAYMENTTERMS],
       s.[PLANT],
       s.[POSTINGDATE],
       s.[POSTINGKEY],
       s.[PRODUCT],
       s.[PRODUCTGROUP],
       s.[PROFITCENTER],
       s.[SEGMENT],
       s.[SOURCELEDGER],
       s.[SPECIALGLCODE],
       s.[SUPPLIER],
       s.[TAXCODE],
       s.[TAXCOUNTRY],
       s.[TRANSACTIONCURRENCY],
       s.[WBSELEMENTINTERNALID],
       s.[_Delete],
       s.[_Reprocess],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP],
       s.[_key_IACCOUNTINGDOCUMENTTYPE],
       s.[_key_IBUSINESSAREA],
       s.[_key_ICHARTOFACCOUNTS],
       s.[_key_ICOMPANYCODE],
       s.[_key_ICONTROLLINGAREA],
       s.[_key_ICOSTCENTER],
       s.[_key_ICOSTCTRACTIVITYTYPE],
       s.[_key_ICUSTOMER],
       s.[_key_ICUSTOMERGROUP],
       s.[_key_IDEBITCREDITCODE],
       s.[_key_IEQUIPMENT],
       s.[_key_IFISCALPERIODFORVARIANT],
       s.[_key_IFISCALYEARFORCOMPANYCODE],
       s.[_key_IFISCALYEARVARIANT],
       s.[_key_IFIXEDASSET],
       s.[_key_IFUNCTIONALAREA],
       s.[_key_IFUNCTIONALLOCATION],
       s.[_key_IGLACCOUNTINCHARTOFACCOUNTS],
       s.[_key_IGLOBALCOMPANYCompany],
       s.[_key_IGLOBALCOMPANYPartnerCompany],
       s.[_key_ILEDGER],
       s.[_key_IPLANT],
       s.[_key_IPRODUCT],
       s.[_key_IPRODUCTGROUP2],
       s.[_key_IPROFITCENTER],
       s.[_key_ISEGMENT],
       s.[_key_ISUPPLIER],
       s.[_key_IWBSELEMENTDATA_2]
FROM [bps_gold_<system_suffix>].[dbo].[I_GLACCOUNTLINEITEMRAWDATA] AS s
WHERE s.[_SystemName] = 'S4M' AND s.[COMPANYCODE] IN ('1710', '1720', '1730');
-- @batch
CREATE OR ALTER VIEW [sap_live].[operational_item] AS
SELECT s.[ACCOUNTINGDOCUMENT],
       s.[ACCOUNTINGDOCUMENTCATEGORY],
       s.[ACCOUNTINGDOCUMENTITEM],
       s.[ACCOUNTINGDOCUMENTTYPE],
       s.[ADDITIONALCURRENCY1],
       s.[AMOUNTINADDITIONALCURRENCY1],
       s.[AMOUNTINCOMPANYCODECURRENCY],
       s.[AMOUNTINFUNCTIONALCURRENCY],
       s.[AMOUNTINGLOBALCURRENCY],
       s.[AMOUNTINTRANSACTIONCURRENCY],
       s.[BILLINGDOCUMENT],
       s.[BUSINESSAREA],
       s.[CHARTOFACCOUNTS],
       s.[CLEARINGACCOUNTINGDOCUMENT],
       s.[CLEARINGDATE],
       s.[CLEARINGDOCFISCALYEAR],
       s.[COMPANY],
       s.[COMPANYCODE],
       s.[COMPANYCODECURRENCY],
       s.[CONTROLLINGAREA],
       s.[COSTCENTER],
       s.[COSTCTRACTIVITYTYPE],
       s.[CUSTOMER],
       s.[CUSTOMERGROUP],
       s.[DEBITCREDITCODE],
       s.[DOCUMENTDATE],
       s.[DOCUMENTITEMTEXT],
       s.[DUNNINGAREA],
       s.[DUNNINGKEY],
       s.[EQUIPMENT],
       s.[FINANCIALACCOUNTTYPE],
       s.[FISCALPERIOD],
       s.[FISCALYEAR],
       s.[FISCALYEARPERIOD],
       s.[FISCALYEARVARIANT],
       s.[FIXEDASSET],
       s.[FUNCTIONALAREA],
       s.[FUNCTIONALCURRENCY],
       s.[FUNCTIONALLOCATION],
       s.[GLACCOUNT],
       s.[GLOBALCURRENCY],
       s.[INVOICEITEMREFERENCE],
       s.[INVOICEREFERENCE],
       s.[INVOICEREFERENCEFISCALYEAR],
       s.[ISOPENITEMMANAGED],
       s.[LEDGERFISCALYEAR],
       s.[MASTERFIXEDASSET],
       s.[NETDUEDATE],
       s.[PARTNERCOMPANY],
       s.[PARTNERCOMPANYCODE],
       s.[PAYMENTBLOCKINGREASON],
       s.[PAYMENTTERMS],
       s.[PLANT],
       s.[POSTINGDATE],
       s.[POSTINGKEY],
       s.[PRODUCT],
       s.[PRODUCTGROUP],
       s.[PROFITCENTER],
       s.[SEGMENT],
       s.[SPECIALGLCODE],
       s.[SUPPLIER],
       s.[TAXCODE],
       s.[TAXCOUNTRY],
       s.[TRANSACTIONCURRENCY],
       s.[WBSELEMENTINTERNALID],
       s.[_Delete],
       s.[_Reprocess],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP],
       s.[_key_IACCOUNTINGDOCUMENTCATEGORY],
       s.[_key_IACCOUNTINGDOCUMENTTYPE],
       s.[_key_IBUSINESSAREA],
       s.[_key_ICHARTOFACCOUNTS],
       s.[_key_ICOMPANYCODE],
       s.[_key_ICONTROLLINGAREA],
       s.[_key_ICOSTCENTER],
       s.[_key_ICUSTOMER],
       s.[_key_ICUSTOMERPAYMENTTERMS],
       s.[_key_IDEBITCREDITCODE],
       s.[_key_IDUNNINGAREA],
       s.[_key_IDUNNINGKEY],
       s.[_key_IFISCALPERIODFORVARIANT],
       s.[_key_IFISCALYEARFORCOMPANYCODE],
       s.[_key_IGLACCOUNTINCHARTOFACCOUNTS],
       s.[_key_IPAYMENTBLOCKINGREASON],
       s.[_key_IPAYMENTTERMS],
       s.[_key_IPOSTINGKEY],
       s.[_key_IPROFITCENTER],
       s.[_key_ISPECIALGLCODE],
       s.[_key_ISUPPLIER]
FROM [bps_gold_<system_suffix>].[dbo].[I_OPERATIONALACCTGDOCITEM] AS s
WHERE s.[_SystemName] = 'S4M' AND s.[COMPANYCODE] IN ('1710', '1720', '1730');
-- @batch
CREATE OR ALTER VIEW [sap_live].[invoice_line] AS
SELECT s.[ACCOUNTINGDOCUMENT],
       s.[BASEUNIT],
       s.[BILLINGDOCUMENT],
       s.[BILLINGDOCUMENTCATEGORY],
       s.[BILLINGDOCUMENTDATE],
       s.[BILLINGDOCUMENTITEM],
       s.[BILLINGDOCUMENTITEMTEXT],
       s.[BILLINGDOCUMENTTYPE],
       s.[BILLINGPLANRULE],
       s.[BILLINGQUANTITY],
       s.[BILLINGQUANTITYINBASEUNIT],
       s.[BILLINGQUANTITYUNIT],
       s.[BILLTOPARTY],
       s.[BUSINESSAREA],
       s.[COMPANYCODE],
       s.[CONTROLLINGAREA],
       s.[COSTCENTER],
       s.[CURRENCY],
       s.[CUSTOMERGROUP],
       s.[DISTRIBUTIONCHANNEL],
       s.[DIVISION],
       s.[FISCALPERIOD],
       s.[FISCALYEAR],
       s.[FISCALYEARVARIANT],
       s.[GROSSAMOUNT],
       s.[NETAMOUNT],
       s.[OVERALLBILLINGSTATUS],
       s.[PAYERPARTY],
       s.[PLANT],
       s.[PRODUCT],
       s.[PRODUCTGROUP],
       s.[PROFITCENTER],
       s.[SALESEMPLOYEE],
       s.[SALESORGANIZATION],
       s.[SALESORGANIZATIONCURRENCY],
       s.[SHIPPINGPOINT],
       s.[SHIPTOPARTY],
       s.[SOLDTOPARTY],
       s.[TAXAMOUNT],
       s.[TRANSACTIONCURRENCY],
       s.[_Delete],
       s.[_Reprocess],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP],
       s.[_key_IBILLINGDOCUMENTTYPE],
       s.[_key_IBILLINGPLANRULE],
       s.[_key_IBUSINESSAREA],
       s.[_key_ICOMPANYCODE],
       s.[_key_ICONTROLLINGAREA],
       s.[_key_ICOSTCENTER],
       s.[_key_ICUSTOMERBillToParty],
       s.[_key_ICUSTOMERGROUP],
       s.[_key_ICUSTOMERPayerParty],
       s.[_key_ICUSTOMERShipToParty],
       s.[_key_ICUSTOMERSoldToParty],
       s.[_key_IDISTRIBUTIONCHANNEL],
       s.[_key_IDIVISION],
       s.[_key_IFISCALPERIODFORVARIANT],
       s.[_key_IOVERALLBILLINGSTATUS],
       s.[_key_IPERSONWORKAGREEMENT1],
       s.[_key_IPLANT],
       s.[_key_IPRODUCT],
       s.[_key_IPRODUCTGROUP2],
       s.[_key_IPROFITCENTER],
       s.[_key_ISALESORGANIZATION],
       s.[_key_ISHIPPINGPOINT]
FROM [bps_gold_<system_suffix>].[dbo].[C_BILLINGDOCITEMBASICDEX_1] AS s
WHERE s.[_SystemName] = 'S4M' AND s.[COMPANYCODE] IN ('1710', '1720', '1730');
-- @batch
CREATE OR ALTER VIEW [sap_live].[company] AS
SELECT s.[CHARTOFACCOUNTS],
       s.[COMPANY],
       s.[COMPANYCODE],
       s.[COMPANYCODENAME],
       s.[CONTROLLINGAREA],
       s.[COUNTRY],
       s.[CURRENCY],
       s.[FISCALYEARVARIANT],
       s.[Key],
       s.[LANGUAGE],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[I_COMPANYCODE] AS s
WHERE (s.[_SystemName] = 'S4M' AND s.[COMPANYCODE] IN ('1710', '1720', '1730')) OR (s.[Key] = -1 AND s.[_SystemName] IS NULL);
-- @batch
CREATE OR ALTER VIEW [sap_live].[gl_account] AS
SELECT s.[CHARTOFACCOUNTS],
       s.[GLACCOUNT],
       s.[GLACCOUNTGROUP],
       s.[GLACCOUNTTYPE],
       s.[ISBALANCESHEETACCOUNT],
       s.[ISPROFITLOSSACCOUNT],
       s.[Key],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[I_GLACCOUNTINCHARTOFACCOUNTS] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL);
-- @batch
CREATE OR ALTER VIEW [sap_live].[fiscal_period] AS
SELECT s.[FISCALPERIOD],
       s.[FISCALPERIODENDDATE],
       s.[FISCALPERIODSTARTDATE],
       s.[FISCALYEAR],
       s.[FISCALYEARENDDATE],
       s.[FISCALYEARPERIOD],
       s.[FISCALYEARSTARTDATE],
       s.[FISCALYEARVARIANT],
       s.[ISSPECIALPERIOD],
       s.[Key],
       s.[NEXTFISCALPERIOD],
       s.[NEXTFISCALPERIODFISCALYEAR],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[I_FISCALPERIODFORVARIANT] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL);
-- @batch
CREATE OR ALTER VIEW [sap_live].[customer] AS
SELECT s.[COUNTRY],
       s.[CUSTOMER],
       s.[CUSTOMERFULLNAME],
       s.[CUSTOMERNAME],
       s.[Key],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[I_CUSTOMER] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL);
-- @batch
CREATE OR ALTER VIEW [sap_live].[supplier] AS
SELECT s.[COUNTRY],
       s.[Key],
       s.[SUPPLIER],
       s.[SUPPLIERFULLNAME],
       s.[SUPPLIERNAME],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[I_SUPPLIER] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL);
-- @batch
CREATE OR ALTER VIEW [sap_live].[customer_link] AS
SELECT s.[CUSTOMER],
       s.[CUSTOMER_KEY],
       s.[Key],
       s.[SALESFORCE_CONTACT_ID],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[ZMSF_CUSTOMER_LINK] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL);
-- @batch
CREATE OR ALTER VIEW [sap_live].[fiscal_year] AS
SELECT s.[COMPANYCODE],
       s.[FISCALYEAR],
       s.[FISCALYEARENDDATE],
       s.[FISCALYEARSTARTDATE],
       s.[Key],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[I_FISCALYEARFORCOMPANYCODE] AS s
WHERE (s.[_SystemName] = 'S4M' AND s.[COMPANYCODE] IN ('1710', '1720', '1730')) OR (s.[Key] = -1 AND s.[_SystemName] IS NULL);
-- @batch
CREATE OR ALTER VIEW [sap_live].[fiscal_variant] AS
SELECT s.[FISCALYEARISCALENDARYEAR],
       s.[FISCALYEARVARIANT],
       s.[Key],
       s.[NUMBEROFPOSTINGPERIODS],
       s.[NUMBEROFSPECIALPERIODS],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[I_FISCALYEARVARIANT] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL);
-- @batch
CREATE OR ALTER VIEW [sap_live].[product] AS
SELECT s.[BASEUNIT],
       s.[Key],
       s.[PRODUCT],
       s.[PRODUCTGROUP],
       s.[PRODUCTTYPE],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[I_PRODUCT] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL);
-- @batch
CREATE OR ALTER VIEW [sap_live].[cost_center] AS
SELECT s.[ACTLDEPSTATISTICALKEYFIGURES],
       s.[ACTLINDEPSTATISTICALKEYFIGURES],
       s.[ACTYDEPDNTFORMULAPLANNINGTMPL],
       s.[ACTYDEPENDENTALLOCATIONTMPL],
       s.[ACTYINDEPENDENTALLOCATIONTMPL],
       s.[ACTYINDEPFORMULAPLANNINGTMPL],
       s.[ADDRESSADDITIONALNAME],
       s.[ADDRESSNAME],
       s.[AVAILABILITYCONTROLISACTIVE],
       s.[AVAILABILITYCONTROLPROFILE],
       s.[BUDGETCARRYINGCOSTCENTER],
       s.[BUSINESSAREA],
       s.[CITYNAME],
       s.[COMPANYCODE],
       s.[CONDITIONAPPLICATION],
       s.[CONDITIONUSAGE],
       s.[CONSUMPTIONQTYISRECORDED],
       s.[CONTROLLINGAREA],
       s.[COSTCENTER],
       s.[COSTCENTERACCOUNTINGOVERHEAD],
       s.[COSTCENTERADDRNAME3],
       s.[COSTCENTERADDRNAME4],
       s.[COSTCENTERALLOCATIONMETHOD],
       s.[COSTCENTERALTERNATIVEFUNCTION],
       s.[COSTCENTERCATEGORY],
       s.[COSTCENTERCREATEDBYUSER],
       s.[COSTCENTERCREATIONDATE],
       s.[COSTCENTERCURRENCY],
       s.[COSTCENTERFUNCTION],
       s.[COSTCENTERISCOMPLETE],
       s.[COSTCENTERPRINTERDESTINATION],
       s.[COSTCENTERSTANDARDHIERAREA],
       s.[COSTCOLLECTOR],
       s.[COSTCTRRESPONSIBLEPERSONNAME],
       s.[COSTCTRRESPONSIBLEUSER],
       s.[COSTINGSHEET],
       s.[COUNTRY],
       s.[DATACOMMUNICATIONPHONENUMBER],
       s.[DEPARTMENT],
       s.[DISTRICT],
       s.[FAXNUMBER],
       s.[FORMOFADDRESS],
       s.[FUNCTIONALAREA],
       s.[FUNCTIONALAREAISFIXASSIGNED],
       s.[FUND],
       s.[FUNDISFIXASSIGNED],
       s.[GRANTID],
       s.[GRANTIDISFIXASSIGNED],
       s.[ISBLKDFORPRIMARYCOSTSPOSTING],
       s.[ISBLKDFORSECONDARYCOSTSPOSTING],
       s.[ISBLOCKEDFORCOMMITMENTPOSTING],
       s.[ISBLOCKEDFORPLANPRIMARYCOSTS],
       s.[ISBLOCKEDFORPLANREVENUES],
       s.[ISBLOCKEDFORPLANSECONDARYCOSTS],
       s.[ISBLOCKEDFORREVENUEPOSTING],
       s.[ISSTATISTICALCOSTCENTER],
       s.[JOINTVENTURE],
       s.[JOINTVENTURECLASS],
       s.[JOINTVENTUREEQUITYTYPE],
       s.[JOINTVENTUREOBJECTTYPE],
       s.[JOINTVENTURERECOVERYCODE],
       s.[JOINTVENTURESUBCLASS],
       s.[Key],
       s.[LANGUAGE],
       s.[LOGICALSYSTEM],
       s.[OBJECTINTERNALID],
       s.[PHONENUMBER1],
       s.[PHONENUMBER2],
       s.[PLANT],
       s.[POBOX],
       s.[POBOXPOSTALCODE],
       s.[POSTALCODE],
       s.[PROFITCENTER],
       s.[REGION],
       s.[STREETADDRESSNAME],
       s.[SUBSEQUENTCOSTCENTER],
       s.[TAXJURISDICTION],
       s.[TELEBOXNUMBER],
       s.[TELETEXNUMBER],
       s.[TELEXNUMBER],
       s.[VALIDITYENDDATE],
       s.[VALIDITYSTARTDATE],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[I_COSTCENTER] AS s
WHERE (s.[_SystemName] = 'S4M' AND s.[COMPANYCODE] IN ('1710', '1720', '1730')) OR (s.[Key] = -1 AND s.[_SystemName] IS NULL);
-- @batch
CREATE OR ALTER VIEW [sap_live].[profit_center] AS
SELECT s.[ADDITIONALNAME],
       s.[ADDRESSNAME],
       s.[CITYNAME],
       s.[COMPANYCODE],
       s.[CONTROLLINGAREA],
       s.[COUNTRY],
       s.[DATACOMMUNICATIONPHONENUMBER],
       s.[DEPARTMENT],
       s.[DISTRICT],
       s.[FAXNUMBER],
       s.[FORMOFADDRESS],
       s.[FORMULAPLANNINGTEMPLATE],
       s.[Key],
       s.[LANGUAGE],
       s.[PHONENUMBER1],
       s.[PHONENUMBER2],
       s.[POBOX],
       s.[POBOXPOSTALCODE],
       s.[POSTALCODE],
       s.[PROFITCENTER],
       s.[PROFITCENTERADDRNAME3],
       s.[PROFITCENTERADDRNAME4],
       s.[PROFITCENTERCREATEDBYUSER],
       s.[PROFITCENTERCREATIONDATE],
       s.[PROFITCENTERISBLOCKED],
       s.[PROFITCENTERPRINTERNAME],
       s.[PROFITCENTERSTANDARDHIERARCHY],
       s.[PROFITCTRRESPONSIBLEPERSONNAME],
       s.[PROFITCTRRESPONSIBLEUSER],
       s.[REGION],
       s.[SEGMENT],
       s.[STREETADDRESSNAME],
       s.[TAXJURISDICTION],
       s.[TELEBOXNUMBER],
       s.[TELETEXNUMBER],
       s.[TELEXNUMBER],
       s.[VALIDITYENDDATE],
       s.[VALIDITYSTARTDATE],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[I_PROFITCENTER] AS s
WHERE (s.[_SystemName] = 'S4M' AND s.[COMPANYCODE] IN ('1710', '1720', '1730')) OR (s.[Key] = -1 AND s.[_SystemName] IS NULL);
-- @batch
CREATE OR ALTER VIEW [sap_live].[gl_hierarchy] AS
SELECT s.[CHARTOFACCOUNTS],
       s.[GLACCOUNT],
       s.[GLACCOUNTHIERARCHY],
       s.[HIERARCHYNODE],
       s.[HIERARCHYVERSION],
       s.[Key],
       s.[NODETYPE],
       s.[PARENTNODE],
       s.[VALIDITYENDDATE],
       s.[VALIDITYSTARTDATE],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[I_GLACCOUNTHIERARCHYNODE] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL);
-- @batch
CREATE OR ALTER VIEW [sap_live].[cost_hierarchy] AS
SELECT s.[CONTROLLINGAREA],
       s.[COSTCENTER],
       s.[COSTCENTERHIERARCHY],
       s.[HIERARCHYNODE],
       s.[Key],
       s.[NODETYPE],
       s.[PARENTNODE],
       s.[VALIDITYENDDATE],
       s.[VALIDITYSTARTDATE],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[I_COSTCENTERHIERARCHYNODE] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL);
-- @batch
CREATE OR ALTER VIEW [sap_live].[profit_hierarchy] AS
SELECT s.[CONTROLLINGAREA],
       s.[HIERARCHYNODE],
       s.[Key],
       s.[NODETYPE],
       s.[PARENTNODE],
       s.[PROFITCENTER],
       s.[PROFITCENTERHIERARCHY],
       s.[VALIDITYENDDATE],
       s.[VALIDITYSTARTDATE],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[I_PROFITCENTERHIERARCHYNODE] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL);
-- @batch
CREATE OR ALTER VIEW [sap_live].[plan] AS
SELECT s.[CONTRACT_ID],
       s.[CONTRACT_VERSION],
       s.[CURRENCY],
       s.[Key],
       s.[MONTHLY_NET],
       s.[NAME],
       s.[PLAN_ID],
       s.[PRODUCT],
       s.[TERRITORY],
       s.[VALID_FROM],
       s.[VALID_TO_EXCLUSIVE],
       s.[VAT_RATE],
       s.[VERSION],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[ZMSF_PLAN] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL);
-- @batch
CREATE OR ALTER VIEW [sap_live].[subscription] AS
SELECT s.[CUSTOMER],
       s.[Key],
       s.[PLAN_ID],
       s.[PLAN_VERSION],
       s.[RENEWAL_POLICY],
       s.[SERVICE_FROM],
       s.[SERVICE_TO_EXCLUSIVE],
       s.[STATUS],
       s.[SUBSCRIPTION_ID],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[ZMSF_SUBSCRIPTION] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL);
-- @batch
CREATE OR ALTER VIEW [sap_live].[rights_contract] AS
SELECT s.[CONTRACT_ID],
       s.[CURRENCY],
       s.[FIXED_NET],
       s.[Key],
       s.[REVENUE_BASIS],
       s.[REVENUE_SHARE],
       s.[SIMULATION_ONLY],
       s.[SUPPLIER],
       s.[VALID_FROM],
       s.[VALID_TO_EXCLUSIVE],
       s.[VERSION],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[ZMSF_RIGHTS_CONTRACT] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL);
-- @batch
CREATE OR ALTER VIEW [sap_live].[rights_coverage] AS
SELECT s.[CATALOG_DISTRIBUTOR_KEY],
       s.[CATALOG_SAP_PARTNER_CODE],
       s.[CONTENT_KEY],
       s.[CONTRACT_ID],
       s.[Key],
       s.[SIMULATION_ONLY],
       s.[TERRITORY],
       s.[USAGE_TYPE],
       s.[VALID_FROM],
       s.[VALID_TO_EXCLUSIVE],
       s.[VERSION],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[ZMSF_RIGHTS_COVERAGE] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL);
-- @batch
CREATE OR ALTER VIEW [sap_live].[billing_link] AS
SELECT s.[BILLINGDOCUMENT],
       s.[BILLINGDOCUMENTITEM],
       s.[ORDER_ID],
       s.[ORIGINAL_BILLINGDOCUMENT],
       s.[SERVICE_FROM],
       s.[SERVICE_TO_EXCLUSIVE],
       s.[SUBSCRIPTION_ID],
       s.[_Delete],
       s.[_Reprocess],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP],
       s.[_key_ZMSFSUBSCRIPTION]
FROM [bps_gold_<system_suffix>].[dbo].[ZMSF_BILLING_LINK] AS s
WHERE s.[_SystemName] = 'S4M';
-- @batch
CREATE OR ALTER VIEW [sap_live].[contract_charge] AS
SELECT s.[ACCOUNTINGDOCUMENT],
       s.[BASIS_NET],
       s.[CHARGE_NET],
       s.[CHARGE_TYPE],
       s.[COMPANYCODE],
       s.[CONTRACT_ID],
       s.[FISCALYEAR],
       s.[PERIOD_START],
       s.[RATE],
       s.[VERSION],
       s.[_Delete],
       s.[_Reprocess],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP],
       s.[_key_ZMSFRIGHTSCONTRACT]
FROM [bps_gold_<system_suffix>].[dbo].[ZMSF_CONTRACT_CHARGE] AS s
WHERE s.[_SystemName] = 'S4M' AND s.[COMPANYCODE] IN ('1710', '1720', '1730');
-- @batch
CREATE OR ALTER VIEW [sap_live].[order_link] AS
SELECT s.[BILLINGDOCUMENT],
       s.[BILLINGDOCUMENTITEM],
       s.[CUSTOMER],
       s.[ORDER_ID],
       s.[ORDER_LINE_NUMBER],
       s.[ORIGINAL_BILLINGDOCUMENT],
       s.[ORIGINAL_BILLINGDOCUMENTITEM],
       s.[SIMULATION_ONLY],
       s.[_Delete],
       s.[_Reprocess],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP],
       s.[_key_ICUSTOMER]
FROM [bps_gold_<system_suffix>].[dbo].[ZMSF_ORDER_LINK] AS s
WHERE s.[_SystemName] = 'S4M';
-- @batch
CREATE OR ALTER VIEW [sap_live].[invoice_customer] AS
WITH [invoice_line] AS (
SELECT s.[ACCOUNTINGDOCUMENT],
       s.[BASEUNIT],
       s.[BILLINGDOCUMENT],
       s.[BILLINGDOCUMENTCATEGORY],
       s.[BILLINGDOCUMENTDATE],
       s.[BILLINGDOCUMENTITEM],
       s.[BILLINGDOCUMENTITEMTEXT],
       s.[BILLINGDOCUMENTTYPE],
       s.[BILLINGPLANRULE],
       s.[BILLINGQUANTITY],
       s.[BILLINGQUANTITYINBASEUNIT],
       s.[BILLINGQUANTITYUNIT],
       s.[BILLTOPARTY],
       s.[BUSINESSAREA],
       s.[COMPANYCODE],
       s.[CONTROLLINGAREA],
       s.[COSTCENTER],
       s.[CURRENCY],
       s.[CUSTOMERGROUP],
       s.[DISTRIBUTIONCHANNEL],
       s.[DIVISION],
       s.[FISCALPERIOD],
       s.[FISCALYEAR],
       s.[FISCALYEARVARIANT],
       s.[GROSSAMOUNT],
       s.[NETAMOUNT],
       s.[OVERALLBILLINGSTATUS],
       s.[PAYERPARTY],
       s.[PLANT],
       s.[PRODUCT],
       s.[PRODUCTGROUP],
       s.[PROFITCENTER],
       s.[SALESEMPLOYEE],
       s.[SALESORGANIZATION],
       s.[SALESORGANIZATIONCURRENCY],
       s.[SHIPPINGPOINT],
       s.[SHIPTOPARTY],
       s.[SOLDTOPARTY],
       s.[TAXAMOUNT],
       s.[TRANSACTIONCURRENCY],
       s.[_Delete],
       s.[_Reprocess],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP],
       s.[_key_IBILLINGDOCUMENTTYPE],
       s.[_key_IBILLINGPLANRULE],
       s.[_key_IBUSINESSAREA],
       s.[_key_ICOMPANYCODE],
       s.[_key_ICONTROLLINGAREA],
       s.[_key_ICOSTCENTER],
       s.[_key_ICUSTOMERBillToParty],
       s.[_key_ICUSTOMERGROUP],
       s.[_key_ICUSTOMERPayerParty],
       s.[_key_ICUSTOMERShipToParty],
       s.[_key_ICUSTOMERSoldToParty],
       s.[_key_IDISTRIBUTIONCHANNEL],
       s.[_key_IDIVISION],
       s.[_key_IFISCALPERIODFORVARIANT],
       s.[_key_IOVERALLBILLINGSTATUS],
       s.[_key_IPERSONWORKAGREEMENT1],
       s.[_key_IPLANT],
       s.[_key_IPRODUCT],
       s.[_key_IPRODUCTGROUP2],
       s.[_key_IPROFITCENTER],
       s.[_key_ISALESORGANIZATION],
       s.[_key_ISHIPPINGPOINT]
FROM [bps_gold_<system_suffix>].[dbo].[C_BILLINGDOCITEMBASICDEX_1] AS s
WHERE s.[_SystemName] = 'S4M' AND s.[COMPANYCODE] IN ('1710', '1720', '1730')
),
[customer] AS (
SELECT s.[COUNTRY],
       s.[CUSTOMER],
       s.[CUSTOMERFULLNAME],
       s.[CUSTOMERNAME],
       s.[Key],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[I_CUSTOMER] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL)
),
[customer_distinct] AS (
SELECT DISTINCT [COUNTRY], [CUSTOMER], [CUSTOMERFULLNAME], [CUSTOMERNAME], [Key], [_Delete], [_SystemName], [_UpdateTimeStamp], [__SEQUENCE_NUMBER], [__TIMESTAMP]
FROM [customer]
),
[customer_counts] AS (
SELECT [_SystemName], [Key], COUNT_BIG(*) AS source_rows
FROM [customer]
GROUP BY [_SystemName], [Key]
),
[customer_variants] AS (
SELECT [_SystemName], [Key], COUNT_BIG(*) AS distinct_rows
FROM [customer_distinct]
GROUP BY [_SystemName], [Key]
),
[customer_safe] AS (
SELECT d.[COUNTRY], d.[CUSTOMER], d.[CUSTOMERFULLNAME], d.[CUSTOMERNAME], n.[Key], d.[_Delete], n.[_SystemName], d.[_UpdateTimeStamp], d.[__SEQUENCE_NUMBER], d.[__TIMESTAMP], n.source_rows, v.distinct_rows
FROM [customer_counts] n
JOIN [customer_variants] v ON (n.[_SystemName] = v.[_SystemName] OR (n.[_SystemName] IS NULL AND v.[_SystemName] IS NULL)) AND (n.[Key] = v.[Key] OR (n.[Key] IS NULL AND v.[Key] IS NULL))
LEFT JOIN [customer_distinct] d ON v.distinct_rows = 1 AND (n.[_SystemName] = d.[_SystemName] OR (n.[_SystemName] IS NULL AND d.[_SystemName] IS NULL)) AND (n.[Key] = d.[Key] OR (n.[Key] IS NULL AND d.[Key] IS NULL))
),
[customer_link] AS (
SELECT s.[CUSTOMER],
       s.[CUSTOMER_KEY],
       s.[Key],
       s.[SALESFORCE_CONTACT_ID],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[ZMSF_CUSTOMER_LINK] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL)
),
[customer_link_distinct] AS (
SELECT DISTINCT [CUSTOMER], [CUSTOMER_KEY], [Key], [SALESFORCE_CONTACT_ID], [_Delete], [_SystemName], [_UpdateTimeStamp], [__SEQUENCE_NUMBER], [__TIMESTAMP]
FROM [customer_link]
),
[customer_link_counts] AS (
SELECT [_SystemName], [CUSTOMER], COUNT_BIG(*) AS source_rows
FROM [customer_link]
GROUP BY [_SystemName], [CUSTOMER]
),
[customer_link_variants] AS (
SELECT [_SystemName], [CUSTOMER], COUNT_BIG(*) AS distinct_rows
FROM [customer_link_distinct]
GROUP BY [_SystemName], [CUSTOMER]
),
[customer_link_safe] AS (
SELECT n.[CUSTOMER], d.[CUSTOMER_KEY], d.[Key], d.[SALESFORCE_CONTACT_ID], d.[_Delete], n.[_SystemName], d.[_UpdateTimeStamp], d.[__SEQUENCE_NUMBER], d.[__TIMESTAMP], n.source_rows, v.distinct_rows
FROM [customer_link_counts] n
JOIN [customer_link_variants] v ON (n.[_SystemName] = v.[_SystemName] OR (n.[_SystemName] IS NULL AND v.[_SystemName] IS NULL)) AND (n.[CUSTOMER] = v.[CUSTOMER] OR (n.[CUSTOMER] IS NULL AND v.[CUSTOMER] IS NULL))
LEFT JOIN [customer_link_distinct] d ON v.distinct_rows = 1 AND (n.[_SystemName] = d.[_SystemName] OR (n.[_SystemName] IS NULL AND d.[_SystemName] IS NULL)) AND (n.[CUSTOMER] = d.[CUSTOMER] OR (n.[CUSTOMER] IS NULL AND d.[CUSTOMER] IS NULL))
),
[shared_customer] AS (
SELECT customer_key, source_customer_id, name FROM gold.dim_customer
),
[shared_customer_distinct] AS (
SELECT DISTINCT [customer_key], [source_customer_id], [name]
FROM [shared_customer]
),
[shared_customer_counts] AS (
SELECT [customer_key], COUNT_BIG(*) AS source_rows
FROM [shared_customer]
GROUP BY [customer_key]
),
[shared_customer_variants] AS (
SELECT [customer_key], COUNT_BIG(*) AS distinct_rows
FROM [shared_customer_distinct]
GROUP BY [customer_key]
),
[shared_customer_safe] AS (
SELECT n.[customer_key], d.[source_customer_id], d.[name], n.source_rows, v.distinct_rows
FROM [shared_customer_counts] n
JOIN [shared_customer_variants] v ON (n.[customer_key] = v.[customer_key] OR (n.[customer_key] IS NULL AND v.[customer_key] IS NULL))
LEFT JOIN [shared_customer_distinct] d ON v.distinct_rows = 1 AND (n.[customer_key] = d.[customer_key] OR (n.[customer_key] IS NULL AND d.[customer_key] IS NULL))
)
SELECT
    b._SystemName, b.COMPANYCODE, b.BILLINGDOCUMENT, b.BILLINGDOCUMENTITEM,
    b.ACCOUNTINGDOCUMENT, b.BILLINGDOCUMENTDATE, b.BILLINGDOCUMENTCATEGORY,
    b.SOLDTOPARTY, b.PRODUCT, b.TRANSACTIONCURRENCY,
    b.NETAMOUNT, b.TAXAMOUNT, b.GROSSAMOUNT,
    b.[_key_ICUSTOMERSoldToParty], c.[Key] AS native_customer_key,
    c.CUSTOMERNAME AS sap_customer_name, l.CUSTOMER_KEY AS mapped_customer_key,
    l.SALESFORCE_CONTACT_ID, CASE WHEN m.distinct_rows = 1 THEN m.customer_key END AS shared_customer_key,
    m.name AS shared_customer_name,
    CASE
      WHEN c.distinct_rows > 1 THEN 'ambiguous_native_customer'
      WHEN l.distinct_rows > 1 THEN 'ambiguous_crosswalk'
      WHEN m.distinct_rows > 1 THEN 'ambiguous_shared_customer'
      WHEN c.[Key] IS NULL OR c.[Key] = -1 THEN 'missing_native_customer'
      WHEN c.CUSTOMER <> b.SOLDTOPARTY OR c.CUSTOMER IS NULL
        OR b.SOLDTOPARTY IS NULL THEN 'native_key_mismatch'
      WHEN l.CUSTOMER_KEY IS NULL THEN 'missing_crosswalk'
      WHEN m.customer_key IS NULL THEN 'missing_shared_customer'
      WHEN m.source_customer_id IS NULL OR l.SALESFORCE_CONTACT_ID IS NULL
        OR m.source_customer_id <> l.SALESFORCE_CONTACT_ID THEN 'crm_id_mismatch'
      ELSE 'matched' END AS customer_mapping_status,
    b._UpdateTimeStamp AS native_update_timestamp,
    b._Delete AS native_fact_delete_marker,
    c._Delete AS native_customer_delete_marker,
    l._Delete AS native_crosswalk_delete_marker
,
    COALESCE(c.source_rows, 0) AS customer_source_rows,
    COALESCE(c.distinct_rows, 0) AS customer_distinct_rows,
    CASE WHEN c.source_rows IS NULL THEN 'missing'
      WHEN c.distinct_rows > 1 THEN 'conflicting_matches'
      WHEN c.source_rows > 1 THEN 'identical_duplicates'
      ELSE 'unique' END AS customer_cardinality_status,
    COALESCE(l.source_rows, 0) AS customer_link_source_rows,
    COALESCE(l.distinct_rows, 0) AS customer_link_distinct_rows,
    CASE WHEN l.source_rows IS NULL THEN 'missing'
      WHEN l.distinct_rows > 1 THEN 'conflicting_matches'
      WHEN l.source_rows > 1 THEN 'identical_duplicates'
      ELSE 'unique' END AS customer_link_cardinality_status,
    COALESCE(m.source_rows, 0) AS shared_customer_source_rows,
    COALESCE(m.distinct_rows, 0) AS shared_customer_distinct_rows,
    CASE WHEN m.source_rows IS NULL THEN 'missing'
      WHEN m.distinct_rows > 1 THEN 'conflicting_matches'
      WHEN m.source_rows > 1 THEN 'identical_duplicates'
      ELSE 'unique' END AS shared_customer_cardinality_status
FROM invoice_line b
LEFT JOIN customer_safe c ON c.[Key] = b.[_key_ICUSTOMERSoldToParty]
 AND ((c.[Key] <> -1 AND c._SystemName = b._SystemName) OR (c.[Key] = -1 AND c._SystemName IS NULL))
LEFT JOIN customer_link_safe l ON l._SystemName = c._SystemName AND l.CUSTOMER = c.CUSTOMER
LEFT JOIN shared_customer_safe m ON m.customer_key = l.CUSTOMER_KEY;
-- @batch
CREATE OR ALTER VIEW [sap_live].[gl_account_balance] AS
WITH [gl_line] AS (
SELECT s.[ACCOUNTINGDOCUMENT],
       s.[ACCOUNTINGDOCUMENTCATEGORY],
       s.[ACCOUNTINGDOCUMENTITEM],
       s.[ACCOUNTINGDOCUMENTTYPE],
       s.[ADDITIONALCURRENCY1],
       s.[AMOUNTINADDITIONALCURRENCY1],
       s.[AMOUNTINCOMPANYCODECURRENCY],
       s.[AMOUNTINFUNCTIONALCURRENCY],
       s.[AMOUNTINGLOBALCURRENCY],
       s.[AMOUNTINTRANSACTIONCURRENCY],
       s.[BILLINGDOCUMENT],
       s.[BUSINESSAREA],
       s.[CHARTOFACCOUNTS],
       s.[CLEARINGACCOUNTINGDOCUMENT],
       s.[CLEARINGDATE],
       s.[CLEARINGDOCFISCALYEAR],
       s.[COMPANY],
       s.[COMPANYCODE],
       s.[COMPANYCODECURRENCY],
       s.[CONTROLLINGAREA],
       s.[COSTCENTER],
       s.[COSTCTRACTIVITYTYPE],
       s.[CUSTOMER],
       s.[CUSTOMERGROUP],
       s.[DEBITCREDITCODE],
       s.[DOCUMENTDATE],
       s.[DOCUMENTITEMTEXT],
       s.[DUNNINGAREA],
       s.[DUNNINGKEY],
       s.[EQUIPMENT],
       s.[FINANCIALACCOUNTTYPE],
       s.[FISCALPERIOD],
       s.[FISCALYEAR],
       s.[FISCALYEARPERIOD],
       s.[FISCALYEARVARIANT],
       s.[FIXEDASSET],
       s.[FUNCTIONALAREA],
       s.[FUNCTIONALCURRENCY],
       s.[FUNCTIONALLOCATION],
       s.[GLACCOUNT],
       s.[GLOBALCURRENCY],
       s.[INVOICEITEMREFERENCE],
       s.[INVOICEREFERENCE],
       s.[INVOICEREFERENCEFISCALYEAR],
       s.[ISOPENITEMMANAGED],
       s.[LEDGERFISCALYEAR],
       s.[LEDGERGLLINEITEM],
       s.[MASTERFIXEDASSET],
       s.[NETDUEDATE],
       s.[PARTNERCOMPANY],
       s.[PARTNERCOMPANYCODE],
       s.[PAYMENTBLOCKINGREASON],
       s.[PAYMENTTERMS],
       s.[PLANT],
       s.[POSTINGDATE],
       s.[POSTINGKEY],
       s.[PRODUCT],
       s.[PRODUCTGROUP],
       s.[PROFITCENTER],
       s.[SEGMENT],
       s.[SOURCELEDGER],
       s.[SPECIALGLCODE],
       s.[SUPPLIER],
       s.[TAXCODE],
       s.[TAXCOUNTRY],
       s.[TRANSACTIONCURRENCY],
       s.[WBSELEMENTINTERNALID],
       s.[_Delete],
       s.[_Reprocess],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP],
       s.[_key_IACCOUNTINGDOCUMENTTYPE],
       s.[_key_IBUSINESSAREA],
       s.[_key_ICHARTOFACCOUNTS],
       s.[_key_ICOMPANYCODE],
       s.[_key_ICONTROLLINGAREA],
       s.[_key_ICOSTCENTER],
       s.[_key_ICOSTCTRACTIVITYTYPE],
       s.[_key_ICUSTOMER],
       s.[_key_ICUSTOMERGROUP],
       s.[_key_IDEBITCREDITCODE],
       s.[_key_IEQUIPMENT],
       s.[_key_IFISCALPERIODFORVARIANT],
       s.[_key_IFISCALYEARFORCOMPANYCODE],
       s.[_key_IFISCALYEARVARIANT],
       s.[_key_IFIXEDASSET],
       s.[_key_IFUNCTIONALAREA],
       s.[_key_IFUNCTIONALLOCATION],
       s.[_key_IGLACCOUNTINCHARTOFACCOUNTS],
       s.[_key_IGLOBALCOMPANYCompany],
       s.[_key_IGLOBALCOMPANYPartnerCompany],
       s.[_key_ILEDGER],
       s.[_key_IPLANT],
       s.[_key_IPRODUCT],
       s.[_key_IPRODUCTGROUP2],
       s.[_key_IPROFITCENTER],
       s.[_key_ISEGMENT],
       s.[_key_ISUPPLIER],
       s.[_key_IWBSELEMENTDATA_2]
FROM [bps_gold_<system_suffix>].[dbo].[I_GLACCOUNTLINEITEMRAWDATA] AS s
WHERE s.[_SystemName] = 'S4M' AND s.[COMPANYCODE] IN ('1710', '1720', '1730')
),
[gl_account] AS (
SELECT s.[CHARTOFACCOUNTS],
       s.[GLACCOUNT],
       s.[GLACCOUNTGROUP],
       s.[GLACCOUNTTYPE],
       s.[ISBALANCESHEETACCOUNT],
       s.[ISPROFITLOSSACCOUNT],
       s.[Key],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[I_GLACCOUNTINCHARTOFACCOUNTS] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL)
),
[gl_account_distinct] AS (
SELECT DISTINCT [CHARTOFACCOUNTS], [GLACCOUNT], [GLACCOUNTGROUP], [GLACCOUNTTYPE], [ISBALANCESHEETACCOUNT], [ISPROFITLOSSACCOUNT], [Key], [_Delete], [_SystemName], [_UpdateTimeStamp], [__SEQUENCE_NUMBER], [__TIMESTAMP]
FROM [gl_account]
),
[gl_account_counts] AS (
SELECT [_SystemName], [Key], COUNT_BIG(*) AS source_rows
FROM [gl_account]
GROUP BY [_SystemName], [Key]
),
[gl_account_variants] AS (
SELECT [_SystemName], [Key], COUNT_BIG(*) AS distinct_rows
FROM [gl_account_distinct]
GROUP BY [_SystemName], [Key]
),
[gl_account_safe] AS (
SELECT d.[CHARTOFACCOUNTS], d.[GLACCOUNT], d.[GLACCOUNTGROUP], d.[GLACCOUNTTYPE], d.[ISBALANCESHEETACCOUNT], d.[ISPROFITLOSSACCOUNT], n.[Key], d.[_Delete], n.[_SystemName], d.[_UpdateTimeStamp], d.[__SEQUENCE_NUMBER], d.[__TIMESTAMP], n.source_rows, v.distinct_rows
FROM [gl_account_counts] n
JOIN [gl_account_variants] v ON (n.[_SystemName] = v.[_SystemName] OR (n.[_SystemName] IS NULL AND v.[_SystemName] IS NULL)) AND (n.[Key] = v.[Key] OR (n.[Key] IS NULL AND v.[Key] IS NULL))
LEFT JOIN [gl_account_distinct] d ON v.distinct_rows = 1 AND (n.[_SystemName] = d.[_SystemName] OR (n.[_SystemName] IS NULL AND d.[_SystemName] IS NULL)) AND (n.[Key] = d.[Key] OR (n.[Key] IS NULL AND d.[Key] IS NULL))
)
SELECT
    g._SystemName, g.COMPANYCODE, g.SOURCELEDGER,
    g.FISCALYEARVARIANT, g.FISCALYEAR, g.FISCALPERIOD,
    g.CHARTOFACCOUNTS, g.GLACCOUNT, g.TRANSACTIONCURRENCY,
    g.[_key_IGLACCOUNTINCHARTOFACCOUNTS], a.[Key] AS native_account_key,
    a.GLACCOUNTTYPE, g._Delete AS native_fact_delete_marker,
    a._Delete AS native_account_delete_marker,
    COUNT_BIG(*) AS journal_lines,
    SUM(g.AMOUNTINTRANSACTIONCURRENCY) AS signed_movement,
    SUM(ABS(g.AMOUNTINTRANSACTIONCURRENCY)) AS absolute_movement,
    MAX(g._UpdateTimeStamp) AS native_update_timestamp,
    CASE WHEN a.distinct_rows > 1 THEN 'ambiguous_native_account'
      WHEN a.[Key] IS NULL OR a.[Key] = -1 THEN 'missing_native_account'
      WHEN a.GLACCOUNT <> g.GLACCOUNT OR a.CHARTOFACCOUNTS <> g.CHARTOFACCOUNTS
        OR a.GLACCOUNT IS NULL OR a.CHARTOFACCOUNTS IS NULL
        OR g.GLACCOUNT IS NULL OR g.CHARTOFACCOUNTS IS NULL THEN 'native_key_mismatch'
      ELSE 'matched' END AS account_mapping_status
,
    COALESCE(a.source_rows, 0) AS gl_account_source_rows,
    COALESCE(a.distinct_rows, 0) AS gl_account_distinct_rows,
    CASE WHEN a.source_rows IS NULL THEN 'missing'
      WHEN a.distinct_rows > 1 THEN 'conflicting_matches'
      WHEN a.source_rows > 1 THEN 'identical_duplicates'
      ELSE 'unique' END AS gl_account_cardinality_status
FROM gl_line g
LEFT JOIN gl_account_safe a ON a.[Key] = g.[_key_IGLACCOUNTINCHARTOFACCOUNTS]
 AND ((a.[Key] <> -1 AND a._SystemName = g._SystemName) OR (a.[Key] = -1 AND a._SystemName IS NULL))
GROUP BY g._SystemName, g.COMPANYCODE, g.SOURCELEDGER,
    g.FISCALYEARVARIANT, g.FISCALYEAR, g.FISCALPERIOD,
    g.CHARTOFACCOUNTS, g.GLACCOUNT, g.TRANSACTIONCURRENCY,
    g.[_key_IGLACCOUNTINCHARTOFACCOUNTS], a.[Key], a.GLACCOUNTTYPE,
    a.GLACCOUNT, a.CHARTOFACCOUNTS, g._Delete, a._Delete, a.source_rows, a.distinct_rows;
-- @batch
CREATE OR ALTER VIEW [sap_live].[customer_invoice_item] AS
WITH [invoice_line] AS (
SELECT s.[ACCOUNTINGDOCUMENT],
       s.[BASEUNIT],
       s.[BILLINGDOCUMENT],
       s.[BILLINGDOCUMENTCATEGORY],
       s.[BILLINGDOCUMENTDATE],
       s.[BILLINGDOCUMENTITEM],
       s.[BILLINGDOCUMENTITEMTEXT],
       s.[BILLINGDOCUMENTTYPE],
       s.[BILLINGPLANRULE],
       s.[BILLINGQUANTITY],
       s.[BILLINGQUANTITYINBASEUNIT],
       s.[BILLINGQUANTITYUNIT],
       s.[BILLTOPARTY],
       s.[BUSINESSAREA],
       s.[COMPANYCODE],
       s.[CONTROLLINGAREA],
       s.[COSTCENTER],
       s.[CURRENCY],
       s.[CUSTOMERGROUP],
       s.[DISTRIBUTIONCHANNEL],
       s.[DIVISION],
       s.[FISCALPERIOD],
       s.[FISCALYEAR],
       s.[FISCALYEARVARIANT],
       s.[GROSSAMOUNT],
       s.[NETAMOUNT],
       s.[OVERALLBILLINGSTATUS],
       s.[PAYERPARTY],
       s.[PLANT],
       s.[PRODUCT],
       s.[PRODUCTGROUP],
       s.[PROFITCENTER],
       s.[SALESEMPLOYEE],
       s.[SALESORGANIZATION],
       s.[SALESORGANIZATIONCURRENCY],
       s.[SHIPPINGPOINT],
       s.[SHIPTOPARTY],
       s.[SOLDTOPARTY],
       s.[TAXAMOUNT],
       s.[TRANSACTIONCURRENCY],
       s.[_Delete],
       s.[_Reprocess],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP],
       s.[_key_IBILLINGDOCUMENTTYPE],
       s.[_key_IBILLINGPLANRULE],
       s.[_key_IBUSINESSAREA],
       s.[_key_ICOMPANYCODE],
       s.[_key_ICONTROLLINGAREA],
       s.[_key_ICOSTCENTER],
       s.[_key_ICUSTOMERBillToParty],
       s.[_key_ICUSTOMERGROUP],
       s.[_key_ICUSTOMERPayerParty],
       s.[_key_ICUSTOMERShipToParty],
       s.[_key_ICUSTOMERSoldToParty],
       s.[_key_IDISTRIBUTIONCHANNEL],
       s.[_key_IDIVISION],
       s.[_key_IFISCALPERIODFORVARIANT],
       s.[_key_IOVERALLBILLINGSTATUS],
       s.[_key_IPERSONWORKAGREEMENT1],
       s.[_key_IPLANT],
       s.[_key_IPRODUCT],
       s.[_key_IPRODUCTGROUP2],
       s.[_key_IPROFITCENTER],
       s.[_key_ISALESORGANIZATION],
       s.[_key_ISHIPPINGPOINT]
FROM [bps_gold_<system_suffix>].[dbo].[C_BILLINGDOCITEMBASICDEX_1] AS s
WHERE s.[_SystemName] = 'S4M' AND s.[COMPANYCODE] IN ('1710', '1720', '1730')
),
[customer] AS (
SELECT s.[COUNTRY],
       s.[CUSTOMER],
       s.[CUSTOMERFULLNAME],
       s.[CUSTOMERNAME],
       s.[Key],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[I_CUSTOMER] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL)
),
[customer_distinct] AS (
SELECT DISTINCT [COUNTRY], [CUSTOMER], [CUSTOMERFULLNAME], [CUSTOMERNAME], [Key], [_Delete], [_SystemName], [_UpdateTimeStamp], [__SEQUENCE_NUMBER], [__TIMESTAMP]
FROM [customer]
),
[customer_counts] AS (
SELECT [_SystemName], [Key], COUNT_BIG(*) AS source_rows
FROM [customer]
GROUP BY [_SystemName], [Key]
),
[customer_variants] AS (
SELECT [_SystemName], [Key], COUNT_BIG(*) AS distinct_rows
FROM [customer_distinct]
GROUP BY [_SystemName], [Key]
),
[customer_safe] AS (
SELECT d.[COUNTRY], d.[CUSTOMER], d.[CUSTOMERFULLNAME], d.[CUSTOMERNAME], n.[Key], d.[_Delete], n.[_SystemName], d.[_UpdateTimeStamp], d.[__SEQUENCE_NUMBER], d.[__TIMESTAMP], n.source_rows, v.distinct_rows
FROM [customer_counts] n
JOIN [customer_variants] v ON (n.[_SystemName] = v.[_SystemName] OR (n.[_SystemName] IS NULL AND v.[_SystemName] IS NULL)) AND (n.[Key] = v.[Key] OR (n.[Key] IS NULL AND v.[Key] IS NULL))
LEFT JOIN [customer_distinct] d ON v.distinct_rows = 1 AND (n.[_SystemName] = d.[_SystemName] OR (n.[_SystemName] IS NULL AND d.[_SystemName] IS NULL)) AND (n.[Key] = d.[Key] OR (n.[Key] IS NULL AND d.[Key] IS NULL))
),
[customer_link] AS (
SELECT s.[CUSTOMER],
       s.[CUSTOMER_KEY],
       s.[Key],
       s.[SALESFORCE_CONTACT_ID],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[ZMSF_CUSTOMER_LINK] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL)
),
[customer_link_distinct] AS (
SELECT DISTINCT [CUSTOMER], [CUSTOMER_KEY], [Key], [SALESFORCE_CONTACT_ID], [_Delete], [_SystemName], [_UpdateTimeStamp], [__SEQUENCE_NUMBER], [__TIMESTAMP]
FROM [customer_link]
),
[customer_link_counts] AS (
SELECT [_SystemName], [CUSTOMER], COUNT_BIG(*) AS source_rows
FROM [customer_link]
GROUP BY [_SystemName], [CUSTOMER]
),
[customer_link_variants] AS (
SELECT [_SystemName], [CUSTOMER], COUNT_BIG(*) AS distinct_rows
FROM [customer_link_distinct]
GROUP BY [_SystemName], [CUSTOMER]
),
[customer_link_safe] AS (
SELECT n.[CUSTOMER], d.[CUSTOMER_KEY], d.[Key], d.[SALESFORCE_CONTACT_ID], d.[_Delete], n.[_SystemName], d.[_UpdateTimeStamp], d.[__SEQUENCE_NUMBER], d.[__TIMESTAMP], n.source_rows, v.distinct_rows
FROM [customer_link_counts] n
JOIN [customer_link_variants] v ON (n.[_SystemName] = v.[_SystemName] OR (n.[_SystemName] IS NULL AND v.[_SystemName] IS NULL)) AND (n.[CUSTOMER] = v.[CUSTOMER] OR (n.[CUSTOMER] IS NULL AND v.[CUSTOMER] IS NULL))
LEFT JOIN [customer_link_distinct] d ON v.distinct_rows = 1 AND (n.[_SystemName] = d.[_SystemName] OR (n.[_SystemName] IS NULL AND d.[_SystemName] IS NULL)) AND (n.[CUSTOMER] = d.[CUSTOMER] OR (n.[CUSTOMER] IS NULL AND d.[CUSTOMER] IS NULL))
),
[billing_link] AS (
SELECT s.[BILLINGDOCUMENT],
       s.[BILLINGDOCUMENTITEM],
       s.[ORDER_ID],
       s.[ORIGINAL_BILLINGDOCUMENT],
       s.[SERVICE_FROM],
       s.[SERVICE_TO_EXCLUSIVE],
       s.[SUBSCRIPTION_ID],
       s.[_Delete],
       s.[_Reprocess],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP],
       s.[_key_ZMSFSUBSCRIPTION]
FROM [bps_gold_<system_suffix>].[dbo].[ZMSF_BILLING_LINK] AS s
WHERE s.[_SystemName] = 'S4M'
),
[billing_link_distinct] AS (
SELECT DISTINCT [BILLINGDOCUMENT], [BILLINGDOCUMENTITEM], [ORDER_ID], [ORIGINAL_BILLINGDOCUMENT], [SERVICE_FROM], [SERVICE_TO_EXCLUSIVE], [SUBSCRIPTION_ID], [_Delete], [_Reprocess], [_SystemName], [_UpdateTimeStamp], [__SEQUENCE_NUMBER], [__TIMESTAMP], [_key_ZMSFSUBSCRIPTION]
FROM [billing_link]
),
[billing_link_counts] AS (
SELECT [_SystemName], [BILLINGDOCUMENT], [BILLINGDOCUMENTITEM], COUNT_BIG(*) AS source_rows
FROM [billing_link]
GROUP BY [_SystemName], [BILLINGDOCUMENT], [BILLINGDOCUMENTITEM]
),
[billing_link_variants] AS (
SELECT [_SystemName], [BILLINGDOCUMENT], [BILLINGDOCUMENTITEM], COUNT_BIG(*) AS distinct_rows
FROM [billing_link_distinct]
GROUP BY [_SystemName], [BILLINGDOCUMENT], [BILLINGDOCUMENTITEM]
),
[billing_link_safe] AS (
SELECT n.[BILLINGDOCUMENT], n.[BILLINGDOCUMENTITEM], d.[ORDER_ID], d.[ORIGINAL_BILLINGDOCUMENT], d.[SERVICE_FROM], d.[SERVICE_TO_EXCLUSIVE], d.[SUBSCRIPTION_ID], d.[_Delete], d.[_Reprocess], n.[_SystemName], d.[_UpdateTimeStamp], d.[__SEQUENCE_NUMBER], d.[__TIMESTAMP], d.[_key_ZMSFSUBSCRIPTION], n.source_rows, v.distinct_rows
FROM [billing_link_counts] n
JOIN [billing_link_variants] v ON (n.[_SystemName] = v.[_SystemName] OR (n.[_SystemName] IS NULL AND v.[_SystemName] IS NULL)) AND (n.[BILLINGDOCUMENT] = v.[BILLINGDOCUMENT] OR (n.[BILLINGDOCUMENT] IS NULL AND v.[BILLINGDOCUMENT] IS NULL)) AND (n.[BILLINGDOCUMENTITEM] = v.[BILLINGDOCUMENTITEM] OR (n.[BILLINGDOCUMENTITEM] IS NULL AND v.[BILLINGDOCUMENTITEM] IS NULL))
LEFT JOIN [billing_link_distinct] d ON v.distinct_rows = 1 AND (n.[_SystemName] = d.[_SystemName] OR (n.[_SystemName] IS NULL AND d.[_SystemName] IS NULL)) AND (n.[BILLINGDOCUMENT] = d.[BILLINGDOCUMENT] OR (n.[BILLINGDOCUMENT] IS NULL AND d.[BILLINGDOCUMENT] IS NULL)) AND (n.[BILLINGDOCUMENTITEM] = d.[BILLINGDOCUMENTITEM] OR (n.[BILLINGDOCUMENTITEM] IS NULL AND d.[BILLINGDOCUMENTITEM] IS NULL))
),
[order_link] AS (
SELECT s.[BILLINGDOCUMENT],
       s.[BILLINGDOCUMENTITEM],
       s.[CUSTOMER],
       s.[ORDER_ID],
       s.[ORDER_LINE_NUMBER],
       s.[ORIGINAL_BILLINGDOCUMENT],
       s.[ORIGINAL_BILLINGDOCUMENTITEM],
       s.[SIMULATION_ONLY],
       s.[_Delete],
       s.[_Reprocess],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP],
       s.[_key_ICUSTOMER]
FROM [bps_gold_<system_suffix>].[dbo].[ZMSF_ORDER_LINK] AS s
WHERE s.[_SystemName] = 'S4M'
),
[order_link_distinct] AS (
SELECT DISTINCT [BILLINGDOCUMENT], [BILLINGDOCUMENTITEM], [CUSTOMER], [ORDER_ID], [ORDER_LINE_NUMBER], [ORIGINAL_BILLINGDOCUMENT], [ORIGINAL_BILLINGDOCUMENTITEM], [SIMULATION_ONLY], [_Delete], [_Reprocess], [_SystemName], [_UpdateTimeStamp], [__SEQUENCE_NUMBER], [__TIMESTAMP], [_key_ICUSTOMER]
FROM [order_link]
),
[order_link_counts] AS (
SELECT [_SystemName], [BILLINGDOCUMENT], [BILLINGDOCUMENTITEM], COUNT_BIG(*) AS source_rows
FROM [order_link]
GROUP BY [_SystemName], [BILLINGDOCUMENT], [BILLINGDOCUMENTITEM]
),
[order_link_variants] AS (
SELECT [_SystemName], [BILLINGDOCUMENT], [BILLINGDOCUMENTITEM], COUNT_BIG(*) AS distinct_rows
FROM [order_link_distinct]
GROUP BY [_SystemName], [BILLINGDOCUMENT], [BILLINGDOCUMENTITEM]
),
[order_link_safe] AS (
SELECT n.[BILLINGDOCUMENT], n.[BILLINGDOCUMENTITEM], d.[CUSTOMER], d.[ORDER_ID], d.[ORDER_LINE_NUMBER], d.[ORIGINAL_BILLINGDOCUMENT], d.[ORIGINAL_BILLINGDOCUMENTITEM], d.[SIMULATION_ONLY], d.[_Delete], d.[_Reprocess], n.[_SystemName], d.[_UpdateTimeStamp], d.[__SEQUENCE_NUMBER], d.[__TIMESTAMP], d.[_key_ICUSTOMER], n.source_rows, v.distinct_rows
FROM [order_link_counts] n
JOIN [order_link_variants] v ON (n.[_SystemName] = v.[_SystemName] OR (n.[_SystemName] IS NULL AND v.[_SystemName] IS NULL)) AND (n.[BILLINGDOCUMENT] = v.[BILLINGDOCUMENT] OR (n.[BILLINGDOCUMENT] IS NULL AND v.[BILLINGDOCUMENT] IS NULL)) AND (n.[BILLINGDOCUMENTITEM] = v.[BILLINGDOCUMENTITEM] OR (n.[BILLINGDOCUMENTITEM] IS NULL AND v.[BILLINGDOCUMENTITEM] IS NULL))
LEFT JOIN [order_link_distinct] d ON v.distinct_rows = 1 AND (n.[_SystemName] = d.[_SystemName] OR (n.[_SystemName] IS NULL AND d.[_SystemName] IS NULL)) AND (n.[BILLINGDOCUMENT] = d.[BILLINGDOCUMENT] OR (n.[BILLINGDOCUMENT] IS NULL AND d.[BILLINGDOCUMENT] IS NULL)) AND (n.[BILLINGDOCUMENTITEM] = d.[BILLINGDOCUMENTITEM] OR (n.[BILLINGDOCUMENTITEM] IS NULL AND d.[BILLINGDOCUMENTITEM] IS NULL))
)
SELECT b.[ACCOUNTINGDOCUMENT],
    b.[BASEUNIT],
    b.[BILLINGDOCUMENT],
    b.[BILLINGDOCUMENTCATEGORY],
    b.[BILLINGDOCUMENTDATE],
    b.[BILLINGDOCUMENTITEM],
    b.[BILLINGDOCUMENTITEMTEXT],
    b.[BILLINGDOCUMENTTYPE],
    b.[BILLINGPLANRULE],
    b.[BILLINGQUANTITY],
    b.[BILLINGQUANTITYINBASEUNIT],
    b.[BILLINGQUANTITYUNIT],
    b.[BILLTOPARTY],
    b.[BUSINESSAREA],
    b.[COMPANYCODE],
    b.[CONTROLLINGAREA],
    b.[COSTCENTER],
    b.[CURRENCY],
    b.[CUSTOMERGROUP],
    b.[DISTRIBUTIONCHANNEL],
    b.[DIVISION],
    b.[FISCALPERIOD],
    b.[FISCALYEAR],
    b.[FISCALYEARVARIANT],
    b.[GROSSAMOUNT],
    b.[NETAMOUNT],
    b.[OVERALLBILLINGSTATUS],
    b.[PAYERPARTY],
    b.[PLANT],
    b.[PRODUCT],
    b.[PRODUCTGROUP],
    b.[PROFITCENTER],
    b.[SALESEMPLOYEE],
    b.[SALESORGANIZATION],
    b.[SALESORGANIZATIONCURRENCY],
    b.[SHIPPINGPOINT],
    b.[SHIPTOPARTY],
    b.[SOLDTOPARTY],
    b.[TAXAMOUNT],
    b.[TRANSACTIONCURRENCY],
    b.[_Delete],
    b.[_Reprocess],
    b.[_SystemName],
    b.[_UpdateTimeStamp],
    b.[__SEQUENCE_NUMBER],
    b.[__TIMESTAMP],
    b.[_key_IBILLINGDOCUMENTTYPE],
    b.[_key_IBILLINGPLANRULE],
    b.[_key_IBUSINESSAREA],
    b.[_key_ICOMPANYCODE],
    b.[_key_ICONTROLLINGAREA],
    b.[_key_ICOSTCENTER],
    b.[_key_ICUSTOMERBillToParty],
    b.[_key_ICUSTOMERGROUP],
    b.[_key_ICUSTOMERPayerParty],
    b.[_key_ICUSTOMERShipToParty],
    b.[_key_ICUSTOMERSoldToParty],
    b.[_key_IDISTRIBUTIONCHANNEL],
    b.[_key_IDIVISION],
    b.[_key_IFISCALPERIODFORVARIANT],
    b.[_key_IOVERALLBILLINGSTATUS],
    b.[_key_IPERSONWORKAGREEMENT1],
    b.[_key_IPLANT],
    b.[_key_IPRODUCT],
    b.[_key_IPRODUCTGROUP2],
    b.[_key_IPROFITCENTER],
    b.[_key_ISALESORGANIZATION],
    b.[_key_ISHIPPINGPOINT],
    CASE WHEN b._Delete = '' AND c._Delete = '' AND l._Delete = '' AND (k.BILLINGDOCUMENT IS NULL OR k._Delete = '') AND (q.BILLINGDOCUMENT IS NULL OR q._Delete = '') THEN 'observed_blank_markers' ELSE 'unverified_native_markers' END AS native_state_status,
    c.[Key] AS native_customer_key, l.CUSTOMER_KEY,
    l.SALESFORCE_CONTACT_ID AS source_customer_id,
    c._Delete AS native_customer_delete_marker, l._Delete AS native_crosswalk_delete_marker,
    CASE WHEN c.distinct_rows > 1 THEN 'ambiguous_native_customer'
      WHEN l.distinct_rows > 1 THEN 'ambiguous_crosswalk'
      WHEN c.[Key] IS NULL OR c.[Key] = -1 THEN 'missing_native_customer'
      WHEN c.CUSTOMER IS NULL OR b.SOLDTOPARTY IS NULL
        OR c.CUSTOMER <> b.SOLDTOPARTY THEN 'native_key_mismatch'
      WHEN l.CUSTOMER_KEY IS NULL THEN 'missing_crosswalk'
      ELSE 'matched' END AS customer_mapping_status,
    CASE WHEN (k.source_rows IS NULL OR k.distinct_rows = 1) AND (q.source_rows IS NULL OR (q.distinct_rows = 1 AND q.CUSTOMER = b.SOLDTOPARTY AND q._key_ICUSTOMER = b._key_ICUSTOMERSoldToParty AND q._key_ICUSTOMER <> -1)) AND (k.source_rows IS NULL OR q.source_rows IS NULL) THEN k.SUBSCRIPTION_ID END AS [SUBSCRIPTION_ID],
    CASE WHEN (k.source_rows IS NULL OR k.distinct_rows = 1) AND (q.source_rows IS NULL OR (q.distinct_rows = 1 AND q.CUSTOMER = b.SOLDTOPARTY AND q._key_ICUSTOMER = b._key_ICUSTOMERSoldToParty AND q._key_ICUSTOMER <> -1)) AND (k.source_rows IS NULL OR q.source_rows IS NULL) THEN k.SERVICE_FROM END AS [SERVICE_FROM],
    CASE WHEN (k.source_rows IS NULL OR k.distinct_rows = 1) AND (q.source_rows IS NULL OR (q.distinct_rows = 1 AND q.CUSTOMER = b.SOLDTOPARTY AND q._key_ICUSTOMER = b._key_ICUSTOMERSoldToParty AND q._key_ICUSTOMER <> -1)) AND (k.source_rows IS NULL OR q.source_rows IS NULL) THEN k.SERVICE_TO_EXCLUSIVE END AS [SERVICE_TO_EXCLUSIVE],
    CASE WHEN (k.source_rows IS NULL OR k.distinct_rows = 1) AND (q.source_rows IS NULL OR (q.distinct_rows = 1 AND q.CUSTOMER = b.SOLDTOPARTY AND q._key_ICUSTOMER = b._key_ICUSTOMERSoldToParty AND q._key_ICUSTOMER <> -1)) AND (k.source_rows IS NULL OR q.source_rows IS NULL) THEN COALESCE(q.ORIGINAL_BILLINGDOCUMENT, k.ORIGINAL_BILLINGDOCUMENT) END AS [ORIGINAL_BILLINGDOCUMENT],
    CASE WHEN (k.source_rows IS NULL OR k.distinct_rows = 1) AND (q.source_rows IS NULL OR (q.distinct_rows = 1 AND q.CUSTOMER = b.SOLDTOPARTY AND q._key_ICUSTOMER = b._key_ICUSTOMERSoldToParty AND q._key_ICUSTOMER <> -1)) AND (k.source_rows IS NULL OR q.source_rows IS NULL) THEN COALESCE(q.ORDER_ID, k.ORDER_ID) END AS [ORDER_ID],
    CASE WHEN (k.source_rows IS NULL OR k.distinct_rows = 1) AND (q.source_rows IS NULL OR (q.distinct_rows = 1 AND q.CUSTOMER = b.SOLDTOPARTY AND q._key_ICUSTOMER = b._key_ICUSTOMERSoldToParty AND q._key_ICUSTOMER <> -1)) AND (k.source_rows IS NULL OR q.source_rows IS NULL) THEN k._key_ZMSFSUBSCRIPTION END AS [_key_ZMSFSUBSCRIPTION],
    CASE WHEN (k.source_rows IS NULL OR k.distinct_rows = 1) AND (q.source_rows IS NULL OR (q.distinct_rows = 1 AND q.CUSTOMER = b.SOLDTOPARTY AND q._key_ICUSTOMER = b._key_ICUSTOMERSoldToParty AND q._key_ICUSTOMER <> -1)) AND (k.source_rows IS NULL OR q.source_rows IS NULL) THEN q.ORDER_LINE_NUMBER END AS [ORDER_LINE_NUMBER],
    CASE WHEN (k.source_rows IS NULL OR k.distinct_rows = 1) AND (q.source_rows IS NULL OR (q.distinct_rows = 1 AND q.CUSTOMER = b.SOLDTOPARTY AND q._key_ICUSTOMER = b._key_ICUSTOMERSoldToParty AND q._key_ICUSTOMER <> -1)) AND (k.source_rows IS NULL OR q.source_rows IS NULL) THEN q.ORIGINAL_BILLINGDOCUMENTITEM END AS [ORIGINAL_BILLINGDOCUMENTITEM],
    CASE WHEN (k.source_rows IS NULL OR k.distinct_rows = 1) AND (q.source_rows IS NULL OR (q.distinct_rows = 1 AND q.CUSTOMER = b.SOLDTOPARTY AND q._key_ICUSTOMER = b._key_ICUSTOMERSoldToParty AND q._key_ICUSTOMER <> -1)) AND (k.source_rows IS NULL OR q.source_rows IS NULL) THEN q.SIMULATION_ONLY END AS [SIMULATION_ONLY],
    q._key_ICUSTOMER AS native_order_customer_key,
    q._Delete AS native_order_link_delete_marker,
    k._Delete AS native_billing_link_delete_marker,
    CASE WHEN k.distinct_rows > 1 OR q.distinct_rows > 1
        OR (k.BILLINGDOCUMENT IS NOT NULL AND q.BILLINGDOCUMENT IS NOT NULL) THEN 'ambiguous_billing_link'
      WHEN k.BILLINGDOCUMENT IS NULL AND q.BILLINGDOCUMENT IS NULL THEN 'missing_billing_link'
      WHEN q.source_rows IS NOT NULL AND CASE WHEN q.distinct_rows = 1 AND q.CUSTOMER = b.SOLDTOPARTY AND q._key_ICUSTOMER = b._key_ICUSTOMERSoldToParty AND q._key_ICUSTOMER <> -1 THEN 0 ELSE 1 END = 1 THEN 'order_customer_mismatch'
      ELSE 'matched' END AS billing_mapping_status
    , CASE WHEN k.distinct_rows > 1 OR q.distinct_rows > 1
        OR (k.BILLINGDOCUMENT IS NOT NULL AND q.BILLINGDOCUMENT IS NOT NULL) THEN 'ambiguous'
      WHEN q.source_rows IS NOT NULL AND CASE WHEN q.distinct_rows = 1 AND q.CUSTOMER = b.SOLDTOPARTY AND q._key_ICUSTOMER = b._key_ICUSTOMERSoldToParty AND q._key_ICUSTOMER <> -1 THEN 0 ELSE 1 END = 1 THEN 'invalid_order'
      WHEN q.BILLINGDOCUMENT IS NOT NULL THEN 'operational_order'
      WHEN k.BILLINGDOCUMENT IS NOT NULL THEN 'subscription'
      ELSE 'unlinked' END AS billing_linkage_type,
    CASE WHEN q.source_rows IS NULL THEN 'missing_order_link'
      WHEN q.distinct_rows > 1 THEN 'ambiguous_order_link'
      WHEN q.distinct_rows = 1 AND q.CUSTOMER = b.SOLDTOPARTY AND q._key_ICUSTOMER = b._key_ICUSTOMERSoldToParty AND q._key_ICUSTOMER <> -1 THEN 'matched' ELSE 'native_key_mismatch' END AS order_customer_mapping_status,
COALESCE(c.source_rows, 0) AS customer_source_rows,
    COALESCE(c.distinct_rows, 0) AS customer_distinct_rows,
    CASE WHEN c.source_rows IS NULL THEN 'missing'
      WHEN c.distinct_rows > 1 THEN 'conflicting_matches'
      WHEN c.source_rows > 1 THEN 'identical_duplicates'
      ELSE 'unique' END AS customer_cardinality_status,
COALESCE(l.source_rows, 0) AS customer_link_source_rows,
    COALESCE(l.distinct_rows, 0) AS customer_link_distinct_rows,
    CASE WHEN l.source_rows IS NULL THEN 'missing'
      WHEN l.distinct_rows > 1 THEN 'conflicting_matches'
      WHEN l.source_rows > 1 THEN 'identical_duplicates'
      ELSE 'unique' END AS customer_link_cardinality_status,
COALESCE(k.source_rows, 0) AS billing_link_source_rows,
    COALESCE(k.distinct_rows, 0) AS billing_link_distinct_rows,
    CASE WHEN k.source_rows IS NULL THEN 'missing'
      WHEN k.distinct_rows > 1 THEN 'conflicting_matches'
      WHEN k.source_rows > 1 THEN 'identical_duplicates'
      ELSE 'unique' END AS billing_link_cardinality_status,
COALESCE(q.source_rows, 0) AS order_link_source_rows,
    COALESCE(q.distinct_rows, 0) AS order_link_distinct_rows,
    CASE WHEN q.source_rows IS NULL THEN 'missing'
      WHEN q.distinct_rows > 1 THEN 'conflicting_matches'
      WHEN q.source_rows > 1 THEN 'identical_duplicates'
      ELSE 'unique' END AS order_link_cardinality_status
FROM invoice_line b
LEFT JOIN customer_safe c ON c.[Key] = b.[_key_ICUSTOMERSoldToParty]
 AND ((c.[Key] <> -1 AND c._SystemName = b._SystemName) OR (c.[Key] = -1 AND c._SystemName IS NULL))
LEFT JOIN customer_link_safe l ON l._SystemName = b._SystemName
 AND l.CUSTOMER = b.SOLDTOPARTY AND l.CUSTOMER = c.CUSTOMER AND c.[Key] <> -1
LEFT JOIN billing_link_safe k ON k._SystemName = b._SystemName
 AND k.BILLINGDOCUMENT = b.BILLINGDOCUMENT AND k.BILLINGDOCUMENTITEM = b.BILLINGDOCUMENTITEM
LEFT JOIN order_link_safe q ON q._SystemName = b._SystemName
 AND q.BILLINGDOCUMENT = b.BILLINGDOCUMENT AND q.BILLINGDOCUMENTITEM = b.BILLINGDOCUMENTITEM;
-- @batch
CREATE OR ALTER VIEW [sap_live].[subscription_contract] AS
WITH [subscription] AS (
SELECT s.[CUSTOMER],
       s.[Key],
       s.[PLAN_ID],
       s.[PLAN_VERSION],
       s.[RENEWAL_POLICY],
       s.[SERVICE_FROM],
       s.[SERVICE_TO_EXCLUSIVE],
       s.[STATUS],
       s.[SUBSCRIPTION_ID],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[ZMSF_SUBSCRIPTION] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL)
),
[customer_link] AS (
SELECT s.[CUSTOMER],
       s.[CUSTOMER_KEY],
       s.[Key],
       s.[SALESFORCE_CONTACT_ID],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[ZMSF_CUSTOMER_LINK] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL)
),
[customer_link_distinct] AS (
SELECT DISTINCT [CUSTOMER], [CUSTOMER_KEY], [Key], [SALESFORCE_CONTACT_ID], [_Delete], [_SystemName], [_UpdateTimeStamp], [__SEQUENCE_NUMBER], [__TIMESTAMP]
FROM [customer_link]
),
[customer_link_counts] AS (
SELECT [_SystemName], [CUSTOMER], COUNT_BIG(*) AS source_rows
FROM [customer_link]
GROUP BY [_SystemName], [CUSTOMER]
),
[customer_link_variants] AS (
SELECT [_SystemName], [CUSTOMER], COUNT_BIG(*) AS distinct_rows
FROM [customer_link_distinct]
GROUP BY [_SystemName], [CUSTOMER]
),
[customer_link_safe] AS (
SELECT n.[CUSTOMER], d.[CUSTOMER_KEY], d.[Key], d.[SALESFORCE_CONTACT_ID], d.[_Delete], n.[_SystemName], d.[_UpdateTimeStamp], d.[__SEQUENCE_NUMBER], d.[__TIMESTAMP], n.source_rows, v.distinct_rows
FROM [customer_link_counts] n
JOIN [customer_link_variants] v ON (n.[_SystemName] = v.[_SystemName] OR (n.[_SystemName] IS NULL AND v.[_SystemName] IS NULL)) AND (n.[CUSTOMER] = v.[CUSTOMER] OR (n.[CUSTOMER] IS NULL AND v.[CUSTOMER] IS NULL))
LEFT JOIN [customer_link_distinct] d ON v.distinct_rows = 1 AND (n.[_SystemName] = d.[_SystemName] OR (n.[_SystemName] IS NULL AND d.[_SystemName] IS NULL)) AND (n.[CUSTOMER] = d.[CUSTOMER] OR (n.[CUSTOMER] IS NULL AND d.[CUSTOMER] IS NULL))
),
[plan] AS (
SELECT [CONTRACT_ID], [CONTRACT_VERSION], [CURRENCY], [Key], [MONTHLY_NET], [NAME], [PLAN_ID], [PRODUCT], [TERRITORY], [VALID_FROM], [VALID_TO_EXCLUSIVE], [VAT_RATE], [VERSION], [_Delete], [_SystemName], [_UpdateTimeStamp], [__SEQUENCE_NUMBER], [__TIMESTAMP]
FROM (
SELECT s.[CONTRACT_ID],
       s.[CONTRACT_VERSION],
       s.[CURRENCY],
       s.[Key],
       s.[MONTHLY_NET],
       s.[NAME],
       s.[PLAN_ID],
       s.[PRODUCT],
       s.[TERRITORY],
       s.[VALID_FROM],
       s.[VALID_TO_EXCLUSIVE],
       s.[VAT_RATE],
       s.[VERSION],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[ZMSF_PLAN] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL)
) eligible_plan WHERE [Key] <> -1
),
[plan_distinct] AS (
SELECT DISTINCT [CONTRACT_ID], [CONTRACT_VERSION], [CURRENCY], [Key], [MONTHLY_NET], [NAME], [PLAN_ID], [PRODUCT], [TERRITORY], [VALID_FROM], [VALID_TO_EXCLUSIVE], [VAT_RATE], [VERSION], [_Delete], [_SystemName], [_UpdateTimeStamp], [__SEQUENCE_NUMBER], [__TIMESTAMP]
FROM [plan]
),
[plan_counts] AS (
SELECT [_SystemName], [PLAN_ID], [VERSION], COUNT_BIG(*) AS source_rows
FROM [plan]
GROUP BY [_SystemName], [PLAN_ID], [VERSION]
),
[plan_variants] AS (
SELECT [_SystemName], [PLAN_ID], [VERSION], COUNT_BIG(*) AS distinct_rows
FROM [plan_distinct]
GROUP BY [_SystemName], [PLAN_ID], [VERSION]
),
[plan_safe] AS (
SELECT d.[CONTRACT_ID], d.[CONTRACT_VERSION], d.[CURRENCY], d.[Key], d.[MONTHLY_NET], d.[NAME], n.[PLAN_ID], d.[PRODUCT], d.[TERRITORY], d.[VALID_FROM], d.[VALID_TO_EXCLUSIVE], d.[VAT_RATE], n.[VERSION], d.[_Delete], n.[_SystemName], d.[_UpdateTimeStamp], d.[__SEQUENCE_NUMBER], d.[__TIMESTAMP], n.source_rows, v.distinct_rows
FROM [plan_counts] n
JOIN [plan_variants] v ON (n.[_SystemName] = v.[_SystemName] OR (n.[_SystemName] IS NULL AND v.[_SystemName] IS NULL)) AND (n.[PLAN_ID] = v.[PLAN_ID] OR (n.[PLAN_ID] IS NULL AND v.[PLAN_ID] IS NULL)) AND (n.[VERSION] = v.[VERSION] OR (n.[VERSION] IS NULL AND v.[VERSION] IS NULL))
LEFT JOIN [plan_distinct] d ON v.distinct_rows = 1 AND (n.[_SystemName] = d.[_SystemName] OR (n.[_SystemName] IS NULL AND d.[_SystemName] IS NULL)) AND (n.[PLAN_ID] = d.[PLAN_ID] OR (n.[PLAN_ID] IS NULL AND d.[PLAN_ID] IS NULL)) AND (n.[VERSION] = d.[VERSION] OR (n.[VERSION] IS NULL AND d.[VERSION] IS NULL))
)
SELECT s.[CUSTOMER],
    s.[Key],
    s.[PLAN_ID],
    s.[PLAN_VERSION],
    s.[RENEWAL_POLICY],
    s.[SERVICE_FROM],
    s.[SERVICE_TO_EXCLUSIVE],
    s.[STATUS],
    s.[SUBSCRIPTION_ID],
    s.[_Delete],
    s.[_SystemName],
    s.[_UpdateTimeStamp],
    s.[__SEQUENCE_NUMBER],
    s.[__TIMESTAMP],
    CASE WHEN s._Delete = '' AND l._Delete = '' AND p._Delete = '' THEN 'observed_blank_markers' ELSE 'unverified_native_markers' END AS native_state_status,
    l.CUSTOMER_KEY, l.SALESFORCE_CONTACT_ID AS source_customer_id,
    l._Delete AS native_crosswalk_delete_marker,
    p.[Key] AS native_plan_key, p._Delete AS native_plan_delete_marker,
    p.MONTHLY_NET, p.VAT_RATE, p.CURRENCY, p.CONTRACT_ID, p.CONTRACT_VERSION,
    p.VALID_FROM AS plan_valid_from, p.VALID_TO_EXCLUSIVE AS plan_valid_to_exclusive,
    CASE WHEN l.distinct_rows > 1 THEN 'ambiguous_crosswalk'
      WHEN l.CUSTOMER_KEY IS NULL THEN 'missing_crosswalk' ELSE 'matched' END AS customer_mapping_status,
    CASE WHEN p.distinct_rows > 1 THEN 'ambiguous_plan_version'
      WHEN p.PLAN_ID IS NULL THEN 'missing_plan_version' ELSE 'matched' END AS plan_mapping_status,
    COALESCE(l.source_rows, 0) AS customer_link_source_rows,
    COALESCE(l.distinct_rows, 0) AS customer_link_distinct_rows,
    CASE WHEN l.source_rows IS NULL THEN 'missing'
      WHEN l.distinct_rows > 1 THEN 'conflicting_matches'
      WHEN l.source_rows > 1 THEN 'identical_duplicates'
      ELSE 'unique' END AS customer_link_cardinality_status,
    COALESCE(p.source_rows, 0) AS plan_source_rows,
    COALESCE(p.distinct_rows, 0) AS plan_distinct_rows,
    CASE WHEN p.source_rows IS NULL THEN 'missing'
      WHEN p.distinct_rows > 1 THEN 'conflicting_matches'
      WHEN p.source_rows > 1 THEN 'identical_duplicates'
      ELSE 'unique' END AS plan_cardinality_status
FROM subscription s
LEFT JOIN customer_link_safe l ON l._SystemName = s._SystemName AND l.CUSTOMER = s.CUSTOMER
LEFT JOIN plan_safe p ON p._SystemName = s._SystemName
 AND p.PLAN_ID = s.PLAN_ID AND p.VERSION = s.PLAN_VERSION
WHERE s._SystemName IS NOT NULL AND s.[Key] <> -1;
-- @batch
CREATE OR ALTER VIEW [sap_live].[calendar] AS
WITH [fiscal_period] AS (
SELECT s.[FISCALPERIOD],
       s.[FISCALPERIODENDDATE],
       s.[FISCALPERIODSTARTDATE],
       s.[FISCALYEAR],
       s.[FISCALYEARENDDATE],
       s.[FISCALYEARPERIOD],
       s.[FISCALYEARSTARTDATE],
       s.[FISCALYEARVARIANT],
       s.[ISSPECIALPERIOD],
       s.[Key],
       s.[NEXTFISCALPERIOD],
       s.[NEXTFISCALPERIODFISCALYEAR],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[I_FISCALPERIODFORVARIANT] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL)
)
SELECT p.[FISCALPERIOD],
    p.[FISCALPERIODENDDATE],
    p.[FISCALPERIODSTARTDATE],
    p.[FISCALYEAR],
    p.[FISCALYEARENDDATE],
    p.[FISCALYEARPERIOD],
    p.[FISCALYEARSTARTDATE],
    p.[FISCALYEARVARIANT],
    p.[ISSPECIALPERIOD],
    p.[Key],
    p.[NEXTFISCALPERIOD],
    p.[NEXTFISCALPERIODFISCALYEAR],
    p.[_Delete],
    p.[_SystemName],
    p.[_UpdateTimeStamp],
    p.[__SEQUENCE_NUMBER],
    p.[__TIMESTAMP],
    CASE WHEN p._Delete = '' THEN 'observed_blank_markers' ELSE 'unverified_native_markers' END AS native_state_status
FROM fiscal_period p
WHERE p.[Key] <> -1 AND p._SystemName IS NOT NULL
 AND NULLIF(p.FISCALYEARVARIANT, '') IS NOT NULL AND p.FISCALYEAR > 0
 AND p.FISCALPERIOD > 0 AND p.FISCALYEARPERIOD > 0
 AND p.FISCALPERIODSTARTDATE <= p.FISCALPERIODENDDATE;
-- @batch
CREATE OR ALTER VIEW [sap_live].[account_roles] AS
WITH [gl_account] AS (
SELECT s.[CHARTOFACCOUNTS],
       s.[GLACCOUNT],
       s.[GLACCOUNTGROUP],
       s.[GLACCOUNTTYPE],
       s.[ISBALANCESHEETACCOUNT],
       s.[ISPROFITLOSSACCOUNT],
       s.[Key],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[I_GLACCOUNTINCHARTOFACCOUNTS] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL)
)
SELECT a.[CHARTOFACCOUNTS],
    a.[GLACCOUNT],
    a.[GLACCOUNTGROUP],
    a.[GLACCOUNTTYPE],
    a.[ISBALANCESHEETACCOUNT],
    a.[ISPROFITLOSSACCOUNT],
    a.[Key],
    a.[_Delete],
    a.[_SystemName],
    a.[_UpdateTimeStamp],
    a.[__SEQUENCE_NUMBER],
    a.[__TIMESTAMP],
    CASE WHEN a._Delete = '' THEN 'observed_blank_markers' ELSE 'unverified_native_markers' END AS native_state_status,
    CASE a.GLACCOUNT
      WHEN '0011000000' THEN 'bank'
      WHEN '0012000000' THEN 'receivables'
      WHEN '0013000000' THEN 'input_vat'
      WHEN '0021000000' THEN 'payables'
      WHEN '0022000000' THEN 'output_vat'
      WHEN '0023000000' THEN 'deferred_revenue'
      WHEN '0040000000' THEN 'revenue'
      WHEN '0050000000' THEN 'content_cost'
      WHEN '0041000000' THEN 'revenue_tvod'
      WHEN '0042000000' THEN 'revenue_est'
      WHEN '0023100000' THEN 'deferred_tvod'
      WHEN '0023200000' THEN 'deferred_est'
      WHEN '0051000000' THEN 'operational_content_cost'
    END AS account_role,
    CASE WHEN a.GLACCOUNT IS NULL THEN 'missing_gl_account'
      WHEN a.GLACCOUNT IN ('0011000000', '0012000000', '0013000000', '0021000000', '0022000000', '0023000000', '0040000000', '0050000000', '0041000000', '0042000000', '0023100000', '0023200000', '0051000000') THEN 'matched' ELSE 'unmapped_gl_account' END AS account_mapping_status
FROM gl_account a
WHERE a.[Key] <> -1 AND a.CHARTOFACCOUNTS = 'MSFX';
-- @batch
CREATE OR ALTER FUNCTION [sap_live].[monthly_finance](@as_of date)
RETURNS TABLE
AS RETURN (
WITH [gl_line] AS (
SELECT s.[ACCOUNTINGDOCUMENT],
       s.[ACCOUNTINGDOCUMENTCATEGORY],
       s.[ACCOUNTINGDOCUMENTITEM],
       s.[ACCOUNTINGDOCUMENTTYPE],
       s.[ADDITIONALCURRENCY1],
       s.[AMOUNTINADDITIONALCURRENCY1],
       s.[AMOUNTINCOMPANYCODECURRENCY],
       s.[AMOUNTINFUNCTIONALCURRENCY],
       s.[AMOUNTINGLOBALCURRENCY],
       s.[AMOUNTINTRANSACTIONCURRENCY],
       s.[BILLINGDOCUMENT],
       s.[BUSINESSAREA],
       s.[CHARTOFACCOUNTS],
       s.[CLEARINGACCOUNTINGDOCUMENT],
       s.[CLEARINGDATE],
       s.[CLEARINGDOCFISCALYEAR],
       s.[COMPANY],
       s.[COMPANYCODE],
       s.[COMPANYCODECURRENCY],
       s.[CONTROLLINGAREA],
       s.[COSTCENTER],
       s.[COSTCTRACTIVITYTYPE],
       s.[CUSTOMER],
       s.[CUSTOMERGROUP],
       s.[DEBITCREDITCODE],
       s.[DOCUMENTDATE],
       s.[DOCUMENTITEMTEXT],
       s.[DUNNINGAREA],
       s.[DUNNINGKEY],
       s.[EQUIPMENT],
       s.[FINANCIALACCOUNTTYPE],
       s.[FISCALPERIOD],
       s.[FISCALYEAR],
       s.[FISCALYEARPERIOD],
       s.[FISCALYEARVARIANT],
       s.[FIXEDASSET],
       s.[FUNCTIONALAREA],
       s.[FUNCTIONALCURRENCY],
       s.[FUNCTIONALLOCATION],
       s.[GLACCOUNT],
       s.[GLOBALCURRENCY],
       s.[INVOICEITEMREFERENCE],
       s.[INVOICEREFERENCE],
       s.[INVOICEREFERENCEFISCALYEAR],
       s.[ISOPENITEMMANAGED],
       s.[LEDGERFISCALYEAR],
       s.[LEDGERGLLINEITEM],
       s.[MASTERFIXEDASSET],
       s.[NETDUEDATE],
       s.[PARTNERCOMPANY],
       s.[PARTNERCOMPANYCODE],
       s.[PAYMENTBLOCKINGREASON],
       s.[PAYMENTTERMS],
       s.[PLANT],
       s.[POSTINGDATE],
       s.[POSTINGKEY],
       s.[PRODUCT],
       s.[PRODUCTGROUP],
       s.[PROFITCENTER],
       s.[SEGMENT],
       s.[SOURCELEDGER],
       s.[SPECIALGLCODE],
       s.[SUPPLIER],
       s.[TAXCODE],
       s.[TAXCOUNTRY],
       s.[TRANSACTIONCURRENCY],
       s.[WBSELEMENTINTERNALID],
       s.[_Delete],
       s.[_Reprocess],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP],
       s.[_key_IACCOUNTINGDOCUMENTTYPE],
       s.[_key_IBUSINESSAREA],
       s.[_key_ICHARTOFACCOUNTS],
       s.[_key_ICOMPANYCODE],
       s.[_key_ICONTROLLINGAREA],
       s.[_key_ICOSTCENTER],
       s.[_key_ICOSTCTRACTIVITYTYPE],
       s.[_key_ICUSTOMER],
       s.[_key_ICUSTOMERGROUP],
       s.[_key_IDEBITCREDITCODE],
       s.[_key_IEQUIPMENT],
       s.[_key_IFISCALPERIODFORVARIANT],
       s.[_key_IFISCALYEARFORCOMPANYCODE],
       s.[_key_IFISCALYEARVARIANT],
       s.[_key_IFIXEDASSET],
       s.[_key_IFUNCTIONALAREA],
       s.[_key_IFUNCTIONALLOCATION],
       s.[_key_IGLACCOUNTINCHARTOFACCOUNTS],
       s.[_key_IGLOBALCOMPANYCompany],
       s.[_key_IGLOBALCOMPANYPartnerCompany],
       s.[_key_ILEDGER],
       s.[_key_IPLANT],
       s.[_key_IPRODUCT],
       s.[_key_IPRODUCTGROUP2],
       s.[_key_IPROFITCENTER],
       s.[_key_ISEGMENT],
       s.[_key_ISUPPLIER],
       s.[_key_IWBSELEMENTDATA_2]
FROM [bps_gold_<system_suffix>].[dbo].[I_GLACCOUNTLINEITEMRAWDATA] AS s
WHERE s.[_SystemName] = 'S4M' AND s.[COMPANYCODE] IN ('1710', '1720', '1730')
)
SELECT g._SystemName, g.COMPANYCODE, g.SOURCELEDGER, g.CHARTOFACCOUNTS,
    @as_of AS as_of, YEAR(g.POSTINGDATE) AS calendar_year, MONTH(g.POSTINGDATE) AS calendar_month,
    g.FISCALYEARVARIANT, g.FISCALYEAR, g.FISCALPERIOD, g.TRANSACTIONCURRENCY AS currency,
    g._Delete AS native_fact_delete_marker, COUNT_BIG(*) AS journal_lines,
    SUM(CASE WHEN g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) AS missing_amount_rows,
    SUM(CASE WHEN g.GLACCOUNT IS NULL THEN 1 ELSE 0 END) AS missing_gl_account_rows,
    SUM(CASE WHEN g.GLACCOUNT NOT IN ('0011000000', '0012000000', '0013000000', '0021000000', '0022000000', '0023000000', '0040000000', '0050000000', '0041000000', '0042000000', '0023100000', '0023200000', '0051000000') THEN 1 ELSE 0 END) AS unmapped_gl_account_rows,
    SUM(CASE WHEN (g.GLACCOUNT IS NULL OR g.GLACCOUNT NOT IN ('0011000000', '0012000000', '0013000000', '0021000000', '0022000000', '0023000000', '0040000000', '0050000000', '0041000000', '0042000000', '0023100000', '0023200000', '0051000000')) THEN 1 ELSE 0 END) AS excluded_account_rows,
    SUM(CASE WHEN (g.GLACCOUNT IS NULL OR g.GLACCOUNT NOT IN ('0011000000', '0012000000', '0013000000', '0021000000', '0022000000', '0023000000', '0040000000', '0050000000', '0041000000', '0042000000', '0023100000', '0023200000', '0051000000')) AND g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) AS excluded_account_missing_amount_rows,
    CASE WHEN SUM(CASE WHEN (g.GLACCOUNT IS NULL OR g.GLACCOUNT NOT IN ('0011000000', '0012000000', '0013000000', '0021000000', '0022000000', '0023000000', '0040000000', '0050000000', '0041000000', '0042000000', '0023100000', '0023200000', '0051000000')) AND g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) > 0 THEN NULL
      ELSE SUM(CASE WHEN (g.GLACCOUNT IS NULL OR g.GLACCOUNT NOT IN ('0011000000', '0012000000', '0013000000', '0021000000', '0022000000', '0023000000', '0040000000', '0050000000', '0041000000', '0042000000', '0023100000', '0023200000', '0051000000')) THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) END AS excluded_account_signed_amount,
    CASE WHEN SUM(CASE WHEN (g.GLACCOUNT IS NULL OR g.GLACCOUNT NOT IN ('0011000000', '0012000000', '0013000000', '0021000000', '0022000000', '0023000000', '0040000000', '0050000000', '0041000000', '0042000000', '0023100000', '0023200000', '0051000000')) THEN 1 ELSE 0 END) > 0 THEN 'incomplete_account_mapping'
      ELSE 'complete_account_mapping' END AS account_completeness_status,
    CASE WHEN g._Delete = '' THEN 'observed_blank_markers' ELSE 'unverified_native_markers' END AS native_state_status,
    -(CASE WHEN SUM(CASE WHEN g.GLACCOUNT IN ('0040000000') AND g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) > 0 THEN NULL ELSE SUM(CASE WHEN g.GLACCOUNT IN ('0040000000') THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) END) AS recognized_subscription_revenue,
    -(CASE WHEN SUM(CASE WHEN g.GLACCOUNT IN ('0041000000') AND g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) > 0 THEN NULL ELSE SUM(CASE WHEN g.GLACCOUNT IN ('0041000000') THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) END) AS recognized_tvod_revenue,
    -(CASE WHEN SUM(CASE WHEN g.GLACCOUNT IN ('0042000000') AND g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) > 0 THEN NULL ELSE SUM(CASE WHEN g.GLACCOUNT IN ('0042000000') THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) END) AS recognized_est_revenue,
    -(CASE WHEN SUM(CASE WHEN g.GLACCOUNT IN ('0041000000', '0042000000') AND g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) > 0 THEN NULL ELSE SUM(CASE WHEN g.GLACCOUNT IN ('0041000000', '0042000000') THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) END) AS recognized_operational_revenue,
    -(CASE WHEN SUM(CASE WHEN g.GLACCOUNT IN ('0040000000', '0041000000', '0042000000') AND g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) > 0 THEN NULL ELSE SUM(CASE WHEN g.GLACCOUNT IN ('0040000000', '0041000000', '0042000000') THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) END) AS recognized_total_revenue,
    (CASE WHEN SUM(CASE WHEN g.GLACCOUNT IN ('0050000000') AND g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) > 0 THEN NULL ELSE SUM(CASE WHEN g.GLACCOUNT IN ('0050000000') THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) END) AS subscription_content_expense,
    (CASE WHEN SUM(CASE WHEN g.GLACCOUNT IN ('0051000000') AND g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) > 0 THEN NULL ELSE SUM(CASE WHEN g.GLACCOUNT IN ('0051000000') THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) END) AS operational_content_expense,
    (CASE WHEN SUM(CASE WHEN g.GLACCOUNT IN ('0050000000', '0051000000') AND g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) > 0 THEN NULL ELSE SUM(CASE WHEN g.GLACCOUNT IN ('0050000000', '0051000000') THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) END) AS content_expense,
    -(CASE WHEN SUM(CASE WHEN g.GLACCOUNT IN ('0040000000', '0041000000', '0042000000', '0050000000', '0051000000') AND g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) > 0 THEN NULL ELSE SUM(CASE WHEN g.GLACCOUNT IN ('0040000000', '0041000000', '0042000000', '0050000000', '0051000000') THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) END) AS contribution_after_content_cost_only,
    (CASE WHEN SUM(CASE WHEN g.GLACCOUNT IN ('0011000000') AND g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) > 0 THEN NULL ELSE SUM(CASE WHEN g.GLACCOUNT IN ('0011000000') THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) END) AS net_bank_movement,
    -(CASE WHEN SUM(CASE WHEN g.GLACCOUNT IN ('0022000000') AND g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) > 0 THEN NULL ELSE SUM(CASE WHEN g.GLACCOUNT IN ('0022000000') THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) END) AS output_vat_liability,
    (CASE WHEN SUM(CASE WHEN g.GLACCOUNT IN ('0013000000') AND g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) > 0 THEN NULL ELSE SUM(CASE WHEN g.GLACCOUNT IN ('0013000000') THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) END) AS input_vat_recoverable,
    -(CASE WHEN SUM(CASE WHEN g.GLACCOUNT IN ('0022000000', '0013000000') AND g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) > 0 THEN NULL ELSE SUM(CASE WHEN g.GLACCOUNT IN ('0022000000', '0013000000') THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) END) AS net_vat_liability,
    -(CASE WHEN SUM(CASE WHEN g.GLACCOUNT IN ('0023000000') AND g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) > 0 THEN NULL ELSE SUM(CASE WHEN g.GLACCOUNT IN ('0023000000') THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) END) AS deferred_subscription_liability,
    -(CASE WHEN SUM(CASE WHEN g.GLACCOUNT IN ('0023100000') AND g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) > 0 THEN NULL ELSE SUM(CASE WHEN g.GLACCOUNT IN ('0023100000') THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) END) AS deferred_tvod_liability,
    -(CASE WHEN SUM(CASE WHEN g.GLACCOUNT IN ('0023200000') AND g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) > 0 THEN NULL ELSE SUM(CASE WHEN g.GLACCOUNT IN ('0023200000') THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) END) AS deferred_est_liability,
    -(CASE WHEN SUM(CASE WHEN g.GLACCOUNT IN ('0023100000', '0023200000') AND g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) > 0 THEN NULL ELSE SUM(CASE WHEN g.GLACCOUNT IN ('0023100000', '0023200000') THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) END) AS deferred_operational_liability,
    -(CASE WHEN SUM(CASE WHEN g.GLACCOUNT IN ('0023000000', '0023100000', '0023200000') AND g.AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) > 0 THEN NULL ELSE SUM(CASE WHEN g.GLACCOUNT IN ('0023000000', '0023100000', '0023200000') THEN g.AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) END) AS deferred_total_liability
FROM gl_line g
WHERE g.POSTINGDATE <= @as_of AND g.CHARTOFACCOUNTS = 'MSFX'
GROUP BY g._SystemName, g.COMPANYCODE, g.SOURCELEDGER, g.CHARTOFACCOUNTS,
    YEAR(g.POSTINGDATE), MONTH(g.POSTINGDATE), g.FISCALYEARVARIANT,
    g.FISCALYEAR, g.FISCALPERIOD, g.TRANSACTIONCURRENCY, g._Delete
);
-- @batch
CREATE OR ALTER FUNCTION [sap_live].[ar_open_items](@as_of date)
RETURNS TABLE
AS RETURN (
WITH [operational_item] AS (
SELECT s.[ACCOUNTINGDOCUMENT],
       s.[ACCOUNTINGDOCUMENTCATEGORY],
       s.[ACCOUNTINGDOCUMENTITEM],
       s.[ACCOUNTINGDOCUMENTTYPE],
       s.[ADDITIONALCURRENCY1],
       s.[AMOUNTINADDITIONALCURRENCY1],
       s.[AMOUNTINCOMPANYCODECURRENCY],
       s.[AMOUNTINFUNCTIONALCURRENCY],
       s.[AMOUNTINGLOBALCURRENCY],
       s.[AMOUNTINTRANSACTIONCURRENCY],
       s.[BILLINGDOCUMENT],
       s.[BUSINESSAREA],
       s.[CHARTOFACCOUNTS],
       s.[CLEARINGACCOUNTINGDOCUMENT],
       s.[CLEARINGDATE],
       s.[CLEARINGDOCFISCALYEAR],
       s.[COMPANY],
       s.[COMPANYCODE],
       s.[COMPANYCODECURRENCY],
       s.[CONTROLLINGAREA],
       s.[COSTCENTER],
       s.[COSTCTRACTIVITYTYPE],
       s.[CUSTOMER],
       s.[CUSTOMERGROUP],
       s.[DEBITCREDITCODE],
       s.[DOCUMENTDATE],
       s.[DOCUMENTITEMTEXT],
       s.[DUNNINGAREA],
       s.[DUNNINGKEY],
       s.[EQUIPMENT],
       s.[FINANCIALACCOUNTTYPE],
       s.[FISCALPERIOD],
       s.[FISCALYEAR],
       s.[FISCALYEARPERIOD],
       s.[FISCALYEARVARIANT],
       s.[FIXEDASSET],
       s.[FUNCTIONALAREA],
       s.[FUNCTIONALCURRENCY],
       s.[FUNCTIONALLOCATION],
       s.[GLACCOUNT],
       s.[GLOBALCURRENCY],
       s.[INVOICEITEMREFERENCE],
       s.[INVOICEREFERENCE],
       s.[INVOICEREFERENCEFISCALYEAR],
       s.[ISOPENITEMMANAGED],
       s.[LEDGERFISCALYEAR],
       s.[MASTERFIXEDASSET],
       s.[NETDUEDATE],
       s.[PARTNERCOMPANY],
       s.[PARTNERCOMPANYCODE],
       s.[PAYMENTBLOCKINGREASON],
       s.[PAYMENTTERMS],
       s.[PLANT],
       s.[POSTINGDATE],
       s.[POSTINGKEY],
       s.[PRODUCT],
       s.[PRODUCTGROUP],
       s.[PROFITCENTER],
       s.[SEGMENT],
       s.[SPECIALGLCODE],
       s.[SUPPLIER],
       s.[TAXCODE],
       s.[TAXCOUNTRY],
       s.[TRANSACTIONCURRENCY],
       s.[WBSELEMENTINTERNALID],
       s.[_Delete],
       s.[_Reprocess],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP],
       s.[_key_IACCOUNTINGDOCUMENTCATEGORY],
       s.[_key_IACCOUNTINGDOCUMENTTYPE],
       s.[_key_IBUSINESSAREA],
       s.[_key_ICHARTOFACCOUNTS],
       s.[_key_ICOMPANYCODE],
       s.[_key_ICONTROLLINGAREA],
       s.[_key_ICOSTCENTER],
       s.[_key_ICUSTOMER],
       s.[_key_ICUSTOMERPAYMENTTERMS],
       s.[_key_IDEBITCREDITCODE],
       s.[_key_IDUNNINGAREA],
       s.[_key_IDUNNINGKEY],
       s.[_key_IFISCALPERIODFORVARIANT],
       s.[_key_IFISCALYEARFORCOMPANYCODE],
       s.[_key_IGLACCOUNTINCHARTOFACCOUNTS],
       s.[_key_IPAYMENTBLOCKINGREASON],
       s.[_key_IPAYMENTTERMS],
       s.[_key_IPOSTINGKEY],
       s.[_key_IPROFITCENTER],
       s.[_key_ISPECIALGLCODE],
       s.[_key_ISUPPLIER]
FROM [bps_gold_<system_suffix>].[dbo].[I_OPERATIONALACCTGDOCITEM] AS s
WHERE s.[_SystemName] = 'S4M' AND s.[COMPANYCODE] IN ('1710', '1720', '1730')
),
[customer] AS (
SELECT s.[COUNTRY],
       s.[CUSTOMER],
       s.[CUSTOMERFULLNAME],
       s.[CUSTOMERNAME],
       s.[Key],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[I_CUSTOMER] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL)
),
[customer_distinct] AS (
SELECT DISTINCT [COUNTRY], [CUSTOMER], [CUSTOMERFULLNAME], [CUSTOMERNAME], [Key], [_Delete], [_SystemName], [_UpdateTimeStamp], [__SEQUENCE_NUMBER], [__TIMESTAMP]
FROM [customer]
),
[customer_counts] AS (
SELECT [_SystemName], [Key], COUNT_BIG(*) AS source_rows
FROM [customer]
GROUP BY [_SystemName], [Key]
),
[customer_variants] AS (
SELECT [_SystemName], [Key], COUNT_BIG(*) AS distinct_rows
FROM [customer_distinct]
GROUP BY [_SystemName], [Key]
),
[customer_safe] AS (
SELECT d.[COUNTRY], d.[CUSTOMER], d.[CUSTOMERFULLNAME], d.[CUSTOMERNAME], n.[Key], d.[_Delete], n.[_SystemName], d.[_UpdateTimeStamp], d.[__SEQUENCE_NUMBER], d.[__TIMESTAMP], n.source_rows, v.distinct_rows
FROM [customer_counts] n
JOIN [customer_variants] v ON (n.[_SystemName] = v.[_SystemName] OR (n.[_SystemName] IS NULL AND v.[_SystemName] IS NULL)) AND (n.[Key] = v.[Key] OR (n.[Key] IS NULL AND v.[Key] IS NULL))
LEFT JOIN [customer_distinct] d ON v.distinct_rows = 1 AND (n.[_SystemName] = d.[_SystemName] OR (n.[_SystemName] IS NULL AND d.[_SystemName] IS NULL)) AND (n.[Key] = d.[Key] OR (n.[Key] IS NULL AND d.[Key] IS NULL))
),
[customer_link] AS (
SELECT s.[CUSTOMER],
       s.[CUSTOMER_KEY],
       s.[Key],
       s.[SALESFORCE_CONTACT_ID],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[ZMSF_CUSTOMER_LINK] AS s
WHERE (s.[_SystemName] = 'S4M') OR (s.[Key] = -1 AND s.[_SystemName] IS NULL)
),
[customer_link_distinct] AS (
SELECT DISTINCT [CUSTOMER], [CUSTOMER_KEY], [Key], [SALESFORCE_CONTACT_ID], [_Delete], [_SystemName], [_UpdateTimeStamp], [__SEQUENCE_NUMBER], [__TIMESTAMP]
FROM [customer_link]
),
[customer_link_counts] AS (
SELECT [_SystemName], [CUSTOMER], COUNT_BIG(*) AS source_rows
FROM [customer_link]
GROUP BY [_SystemName], [CUSTOMER]
),
[customer_link_variants] AS (
SELECT [_SystemName], [CUSTOMER], COUNT_BIG(*) AS distinct_rows
FROM [customer_link_distinct]
GROUP BY [_SystemName], [CUSTOMER]
),
[customer_link_safe] AS (
SELECT n.[CUSTOMER], d.[CUSTOMER_KEY], d.[Key], d.[SALESFORCE_CONTACT_ID], d.[_Delete], n.[_SystemName], d.[_UpdateTimeStamp], d.[__SEQUENCE_NUMBER], d.[__TIMESTAMP], n.source_rows, v.distinct_rows
FROM [customer_link_counts] n
JOIN [customer_link_variants] v ON (n.[_SystemName] = v.[_SystemName] OR (n.[_SystemName] IS NULL AND v.[_SystemName] IS NULL)) AND (n.[CUSTOMER] = v.[CUSTOMER] OR (n.[CUSTOMER] IS NULL AND v.[CUSTOMER] IS NULL))
LEFT JOIN [customer_link_distinct] d ON v.distinct_rows = 1 AND (n.[_SystemName] = d.[_SystemName] OR (n.[_SystemName] IS NULL AND d.[_SystemName] IS NULL)) AND (n.[CUSTOMER] = d.[CUSTOMER] OR (n.[CUSTOMER] IS NULL AND d.[CUSTOMER] IS NULL))
)
SELECT o.[ACCOUNTINGDOCUMENT],
    o.[ACCOUNTINGDOCUMENTCATEGORY],
    o.[ACCOUNTINGDOCUMENTITEM],
    o.[ACCOUNTINGDOCUMENTTYPE],
    o.[ADDITIONALCURRENCY1],
    o.[AMOUNTINADDITIONALCURRENCY1],
    o.[AMOUNTINCOMPANYCODECURRENCY],
    o.[AMOUNTINFUNCTIONALCURRENCY],
    o.[AMOUNTINGLOBALCURRENCY],
    o.[AMOUNTINTRANSACTIONCURRENCY],
    o.[BILLINGDOCUMENT],
    o.[BUSINESSAREA],
    o.[CHARTOFACCOUNTS],
    o.[CLEARINGACCOUNTINGDOCUMENT],
    o.[CLEARINGDATE],
    o.[CLEARINGDOCFISCALYEAR],
    o.[COMPANY],
    o.[COMPANYCODE],
    o.[COMPANYCODECURRENCY],
    o.[CONTROLLINGAREA],
    o.[COSTCENTER],
    o.[COSTCTRACTIVITYTYPE],
    o.[CUSTOMER],
    o.[CUSTOMERGROUP],
    o.[DEBITCREDITCODE],
    o.[DOCUMENTDATE],
    o.[DOCUMENTITEMTEXT],
    o.[DUNNINGAREA],
    o.[DUNNINGKEY],
    o.[EQUIPMENT],
    o.[FINANCIALACCOUNTTYPE],
    o.[FISCALPERIOD],
    o.[FISCALYEAR],
    o.[FISCALYEARPERIOD],
    o.[FISCALYEARVARIANT],
    o.[FIXEDASSET],
    o.[FUNCTIONALAREA],
    o.[FUNCTIONALCURRENCY],
    o.[FUNCTIONALLOCATION],
    o.[GLACCOUNT],
    o.[GLOBALCURRENCY],
    o.[INVOICEITEMREFERENCE],
    o.[INVOICEREFERENCE],
    o.[INVOICEREFERENCEFISCALYEAR],
    o.[ISOPENITEMMANAGED],
    o.[LEDGERFISCALYEAR],
    o.[MASTERFIXEDASSET],
    o.[NETDUEDATE],
    o.[PARTNERCOMPANY],
    o.[PARTNERCOMPANYCODE],
    o.[PAYMENTBLOCKINGREASON],
    o.[PAYMENTTERMS],
    o.[PLANT],
    o.[POSTINGDATE],
    o.[POSTINGKEY],
    o.[PRODUCT],
    o.[PRODUCTGROUP],
    o.[PROFITCENTER],
    o.[SEGMENT],
    o.[SPECIALGLCODE],
    o.[SUPPLIER],
    o.[TAXCODE],
    o.[TAXCOUNTRY],
    o.[TRANSACTIONCURRENCY],
    o.[WBSELEMENTINTERNALID],
    o.[_Delete],
    o.[_Reprocess],
    o.[_SystemName],
    o.[_UpdateTimeStamp],
    o.[__SEQUENCE_NUMBER],
    o.[__TIMESTAMP],
    o.[_key_IACCOUNTINGDOCUMENTCATEGORY],
    o.[_key_IACCOUNTINGDOCUMENTTYPE],
    o.[_key_IBUSINESSAREA],
    o.[_key_ICHARTOFACCOUNTS],
    o.[_key_ICOMPANYCODE],
    o.[_key_ICONTROLLINGAREA],
    o.[_key_ICOSTCENTER],
    o.[_key_ICUSTOMER],
    o.[_key_ICUSTOMERPAYMENTTERMS],
    o.[_key_IDEBITCREDITCODE],
    o.[_key_IDUNNINGAREA],
    o.[_key_IDUNNINGKEY],
    o.[_key_IFISCALPERIODFORVARIANT],
    o.[_key_IFISCALYEARFORCOMPANYCODE],
    o.[_key_IGLACCOUNTINCHARTOFACCOUNTS],
    o.[_key_IPAYMENTBLOCKINGREASON],
    o.[_key_IPAYMENTTERMS],
    o.[_key_IPOSTINGKEY],
    o.[_key_IPROFITCENTER],
    o.[_key_ISPECIALGLCODE],
    o.[_key_ISUPPLIER],
    CASE WHEN o._Delete = '' AND c._Delete = '' AND l._Delete = '' THEN 'observed_blank_markers' ELSE 'unverified_native_markers' END AS native_state_status,
    @as_of AS as_of, o.AMOUNTINTRANSACTIONCURRENCY AS outstanding_signed,
    c.[Key] AS native_customer_key, l.CUSTOMER_KEY,
    l.SALESFORCE_CONTACT_ID AS source_customer_id,
    c._Delete AS native_customer_delete_marker, l._Delete AS native_crosswalk_delete_marker,
    CASE WHEN c.distinct_rows > 1 THEN 'ambiguous_native_customer'
      WHEN l.distinct_rows > 1 THEN 'ambiguous_crosswalk'
      WHEN c.[Key] IS NULL OR c.[Key] = -1 THEN 'missing_native_customer'
      WHEN c.CUSTOMER IS NULL OR o.CUSTOMER IS NULL
        OR c.CUSTOMER <> o.CUSTOMER THEN 'native_key_mismatch'
      WHEN l.CUSTOMER_KEY IS NULL THEN 'missing_crosswalk'
      ELSE 'matched' END AS customer_mapping_status
,
    COALESCE(c.source_rows, 0) AS customer_source_rows,
    COALESCE(c.distinct_rows, 0) AS customer_distinct_rows,
    CASE WHEN c.source_rows IS NULL THEN 'missing'
      WHEN c.distinct_rows > 1 THEN 'conflicting_matches'
      WHEN c.source_rows > 1 THEN 'identical_duplicates'
      ELSE 'unique' END AS customer_cardinality_status,
    COALESCE(l.source_rows, 0) AS customer_link_source_rows,
    COALESCE(l.distinct_rows, 0) AS customer_link_distinct_rows,
    CASE WHEN l.source_rows IS NULL THEN 'missing'
      WHEN l.distinct_rows > 1 THEN 'conflicting_matches'
      WHEN l.source_rows > 1 THEN 'identical_duplicates'
      ELSE 'unique' END AS customer_link_cardinality_status
FROM operational_item o
LEFT JOIN customer_safe c ON c.[Key] = o.[_key_ICUSTOMER]
 AND ((c.[Key] <> -1 AND c._SystemName = o._SystemName) OR (c.[Key] = -1 AND c._SystemName IS NULL))
LEFT JOIN customer_link_safe l ON l._SystemName = o._SystemName
 AND l.CUSTOMER = o.CUSTOMER AND l.CUSTOMER = c.CUSTOMER AND c.[Key] <> -1
WHERE o.FINANCIALACCOUNTTYPE = 'D' AND o.POSTINGDATE <= @as_of
 AND (o.CLEARINGDATE IS NULL OR o.CLEARINGDATE > @as_of)
);
-- @batch
CREATE OR ALTER FUNCTION [sap_live].[ap_open_items](@as_of date)
RETURNS TABLE
AS RETURN (
WITH [operational_item] AS (
SELECT s.[ACCOUNTINGDOCUMENT],
       s.[ACCOUNTINGDOCUMENTCATEGORY],
       s.[ACCOUNTINGDOCUMENTITEM],
       s.[ACCOUNTINGDOCUMENTTYPE],
       s.[ADDITIONALCURRENCY1],
       s.[AMOUNTINADDITIONALCURRENCY1],
       s.[AMOUNTINCOMPANYCODECURRENCY],
       s.[AMOUNTINFUNCTIONALCURRENCY],
       s.[AMOUNTINGLOBALCURRENCY],
       s.[AMOUNTINTRANSACTIONCURRENCY],
       s.[BILLINGDOCUMENT],
       s.[BUSINESSAREA],
       s.[CHARTOFACCOUNTS],
       s.[CLEARINGACCOUNTINGDOCUMENT],
       s.[CLEARINGDATE],
       s.[CLEARINGDOCFISCALYEAR],
       s.[COMPANY],
       s.[COMPANYCODE],
       s.[COMPANYCODECURRENCY],
       s.[CONTROLLINGAREA],
       s.[COSTCENTER],
       s.[COSTCTRACTIVITYTYPE],
       s.[CUSTOMER],
       s.[CUSTOMERGROUP],
       s.[DEBITCREDITCODE],
       s.[DOCUMENTDATE],
       s.[DOCUMENTITEMTEXT],
       s.[DUNNINGAREA],
       s.[DUNNINGKEY],
       s.[EQUIPMENT],
       s.[FINANCIALACCOUNTTYPE],
       s.[FISCALPERIOD],
       s.[FISCALYEAR],
       s.[FISCALYEARPERIOD],
       s.[FISCALYEARVARIANT],
       s.[FIXEDASSET],
       s.[FUNCTIONALAREA],
       s.[FUNCTIONALCURRENCY],
       s.[FUNCTIONALLOCATION],
       s.[GLACCOUNT],
       s.[GLOBALCURRENCY],
       s.[INVOICEITEMREFERENCE],
       s.[INVOICEREFERENCE],
       s.[INVOICEREFERENCEFISCALYEAR],
       s.[ISOPENITEMMANAGED],
       s.[LEDGERFISCALYEAR],
       s.[MASTERFIXEDASSET],
       s.[NETDUEDATE],
       s.[PARTNERCOMPANY],
       s.[PARTNERCOMPANYCODE],
       s.[PAYMENTBLOCKINGREASON],
       s.[PAYMENTTERMS],
       s.[PLANT],
       s.[POSTINGDATE],
       s.[POSTINGKEY],
       s.[PRODUCT],
       s.[PRODUCTGROUP],
       s.[PROFITCENTER],
       s.[SEGMENT],
       s.[SPECIALGLCODE],
       s.[SUPPLIER],
       s.[TAXCODE],
       s.[TAXCOUNTRY],
       s.[TRANSACTIONCURRENCY],
       s.[WBSELEMENTINTERNALID],
       s.[_Delete],
       s.[_Reprocess],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP],
       s.[_key_IACCOUNTINGDOCUMENTCATEGORY],
       s.[_key_IACCOUNTINGDOCUMENTTYPE],
       s.[_key_IBUSINESSAREA],
       s.[_key_ICHARTOFACCOUNTS],
       s.[_key_ICOMPANYCODE],
       s.[_key_ICONTROLLINGAREA],
       s.[_key_ICOSTCENTER],
       s.[_key_ICUSTOMER],
       s.[_key_ICUSTOMERPAYMENTTERMS],
       s.[_key_IDEBITCREDITCODE],
       s.[_key_IDUNNINGAREA],
       s.[_key_IDUNNINGKEY],
       s.[_key_IFISCALPERIODFORVARIANT],
       s.[_key_IFISCALYEARFORCOMPANYCODE],
       s.[_key_IGLACCOUNTINCHARTOFACCOUNTS],
       s.[_key_IPAYMENTBLOCKINGREASON],
       s.[_key_IPAYMENTTERMS],
       s.[_key_IPOSTINGKEY],
       s.[_key_IPROFITCENTER],
       s.[_key_ISPECIALGLCODE],
       s.[_key_ISUPPLIER]
FROM [bps_gold_<system_suffix>].[dbo].[I_OPERATIONALACCTGDOCITEM] AS s
WHERE s.[_SystemName] = 'S4M' AND s.[COMPANYCODE] IN ('1710', '1720', '1730')
)
SELECT o.[ACCOUNTINGDOCUMENT],
    o.[ACCOUNTINGDOCUMENTCATEGORY],
    o.[ACCOUNTINGDOCUMENTITEM],
    o.[ACCOUNTINGDOCUMENTTYPE],
    o.[ADDITIONALCURRENCY1],
    o.[AMOUNTINADDITIONALCURRENCY1],
    o.[AMOUNTINCOMPANYCODECURRENCY],
    o.[AMOUNTINFUNCTIONALCURRENCY],
    o.[AMOUNTINGLOBALCURRENCY],
    o.[AMOUNTINTRANSACTIONCURRENCY],
    o.[BILLINGDOCUMENT],
    o.[BUSINESSAREA],
    o.[CHARTOFACCOUNTS],
    o.[CLEARINGACCOUNTINGDOCUMENT],
    o.[CLEARINGDATE],
    o.[CLEARINGDOCFISCALYEAR],
    o.[COMPANY],
    o.[COMPANYCODE],
    o.[COMPANYCODECURRENCY],
    o.[CONTROLLINGAREA],
    o.[COSTCENTER],
    o.[COSTCTRACTIVITYTYPE],
    o.[CUSTOMER],
    o.[CUSTOMERGROUP],
    o.[DEBITCREDITCODE],
    o.[DOCUMENTDATE],
    o.[DOCUMENTITEMTEXT],
    o.[DUNNINGAREA],
    o.[DUNNINGKEY],
    o.[EQUIPMENT],
    o.[FINANCIALACCOUNTTYPE],
    o.[FISCALPERIOD],
    o.[FISCALYEAR],
    o.[FISCALYEARPERIOD],
    o.[FISCALYEARVARIANT],
    o.[FIXEDASSET],
    o.[FUNCTIONALAREA],
    o.[FUNCTIONALCURRENCY],
    o.[FUNCTIONALLOCATION],
    o.[GLACCOUNT],
    o.[GLOBALCURRENCY],
    o.[INVOICEITEMREFERENCE],
    o.[INVOICEREFERENCE],
    o.[INVOICEREFERENCEFISCALYEAR],
    o.[ISOPENITEMMANAGED],
    o.[LEDGERFISCALYEAR],
    o.[MASTERFIXEDASSET],
    o.[NETDUEDATE],
    o.[PARTNERCOMPANY],
    o.[PARTNERCOMPANYCODE],
    o.[PAYMENTBLOCKINGREASON],
    o.[PAYMENTTERMS],
    o.[PLANT],
    o.[POSTINGDATE],
    o.[POSTINGKEY],
    o.[PRODUCT],
    o.[PRODUCTGROUP],
    o.[PROFITCENTER],
    o.[SEGMENT],
    o.[SPECIALGLCODE],
    o.[SUPPLIER],
    o.[TAXCODE],
    o.[TAXCOUNTRY],
    o.[TRANSACTIONCURRENCY],
    o.[WBSELEMENTINTERNALID],
    o.[_Delete],
    o.[_Reprocess],
    o.[_SystemName],
    o.[_UpdateTimeStamp],
    o.[__SEQUENCE_NUMBER],
    o.[__TIMESTAMP],
    o.[_key_IACCOUNTINGDOCUMENTCATEGORY],
    o.[_key_IACCOUNTINGDOCUMENTTYPE],
    o.[_key_IBUSINESSAREA],
    o.[_key_ICHARTOFACCOUNTS],
    o.[_key_ICOMPANYCODE],
    o.[_key_ICONTROLLINGAREA],
    o.[_key_ICOSTCENTER],
    o.[_key_ICUSTOMER],
    o.[_key_ICUSTOMERPAYMENTTERMS],
    o.[_key_IDEBITCREDITCODE],
    o.[_key_IDUNNINGAREA],
    o.[_key_IDUNNINGKEY],
    o.[_key_IFISCALPERIODFORVARIANT],
    o.[_key_IFISCALYEARFORCOMPANYCODE],
    o.[_key_IGLACCOUNTINCHARTOFACCOUNTS],
    o.[_key_IPAYMENTBLOCKINGREASON],
    o.[_key_IPAYMENTTERMS],
    o.[_key_IPOSTINGKEY],
    o.[_key_IPROFITCENTER],
    o.[_key_ISPECIALGLCODE],
    o.[_key_ISUPPLIER],
    CASE WHEN o._Delete = '' THEN 'observed_blank_markers' ELSE 'unverified_native_markers' END AS native_state_status,
    @as_of AS as_of, -o.AMOUNTINTRANSACTIONCURRENCY AS outstanding_payable_signed
FROM operational_item o
WHERE o.FINANCIALACCOUNTTYPE = 'K' AND o.POSTINGDATE <= @as_of
 AND (o.CLEARINGDATE IS NULL OR o.CLEARINGDATE > @as_of)
);
-- @batch
CREATE OR ALTER FUNCTION [sap_live].[balances](@as_of date)
RETURNS TABLE
AS RETURN (
WITH [company] AS (
SELECT s.[CHARTOFACCOUNTS],
       s.[COMPANY],
       s.[COMPANYCODE],
       s.[COMPANYCODENAME],
       s.[CONTROLLINGAREA],
       s.[COUNTRY],
       s.[CURRENCY],
       s.[FISCALYEARVARIANT],
       s.[Key],
       s.[LANGUAGE],
       s.[_Delete],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP]
FROM [bps_gold_<system_suffix>].[dbo].[I_COMPANYCODE] AS s
WHERE (s.[_SystemName] = 'S4M' AND s.[COMPANYCODE] IN ('1710', '1720', '1730')) OR (s.[Key] = -1 AND s.[_SystemName] IS NULL)
),
[operational_item] AS (
SELECT s.[ACCOUNTINGDOCUMENT],
       s.[ACCOUNTINGDOCUMENTCATEGORY],
       s.[ACCOUNTINGDOCUMENTITEM],
       s.[ACCOUNTINGDOCUMENTTYPE],
       s.[ADDITIONALCURRENCY1],
       s.[AMOUNTINADDITIONALCURRENCY1],
       s.[AMOUNTINCOMPANYCODECURRENCY],
       s.[AMOUNTINFUNCTIONALCURRENCY],
       s.[AMOUNTINGLOBALCURRENCY],
       s.[AMOUNTINTRANSACTIONCURRENCY],
       s.[BILLINGDOCUMENT],
       s.[BUSINESSAREA],
       s.[CHARTOFACCOUNTS],
       s.[CLEARINGACCOUNTINGDOCUMENT],
       s.[CLEARINGDATE],
       s.[CLEARINGDOCFISCALYEAR],
       s.[COMPANY],
       s.[COMPANYCODE],
       s.[COMPANYCODECURRENCY],
       s.[CONTROLLINGAREA],
       s.[COSTCENTER],
       s.[COSTCTRACTIVITYTYPE],
       s.[CUSTOMER],
       s.[CUSTOMERGROUP],
       s.[DEBITCREDITCODE],
       s.[DOCUMENTDATE],
       s.[DOCUMENTITEMTEXT],
       s.[DUNNINGAREA],
       s.[DUNNINGKEY],
       s.[EQUIPMENT],
       s.[FINANCIALACCOUNTTYPE],
       s.[FISCALPERIOD],
       s.[FISCALYEAR],
       s.[FISCALYEARPERIOD],
       s.[FISCALYEARVARIANT],
       s.[FIXEDASSET],
       s.[FUNCTIONALAREA],
       s.[FUNCTIONALCURRENCY],
       s.[FUNCTIONALLOCATION],
       s.[GLACCOUNT],
       s.[GLOBALCURRENCY],
       s.[INVOICEITEMREFERENCE],
       s.[INVOICEREFERENCE],
       s.[INVOICEREFERENCEFISCALYEAR],
       s.[ISOPENITEMMANAGED],
       s.[LEDGERFISCALYEAR],
       s.[MASTERFIXEDASSET],
       s.[NETDUEDATE],
       s.[PARTNERCOMPANY],
       s.[PARTNERCOMPANYCODE],
       s.[PAYMENTBLOCKINGREASON],
       s.[PAYMENTTERMS],
       s.[PLANT],
       s.[POSTINGDATE],
       s.[POSTINGKEY],
       s.[PRODUCT],
       s.[PRODUCTGROUP],
       s.[PROFITCENTER],
       s.[SEGMENT],
       s.[SPECIALGLCODE],
       s.[SUPPLIER],
       s.[TAXCODE],
       s.[TAXCOUNTRY],
       s.[TRANSACTIONCURRENCY],
       s.[WBSELEMENTINTERNALID],
       s.[_Delete],
       s.[_Reprocess],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP],
       s.[_key_IACCOUNTINGDOCUMENTCATEGORY],
       s.[_key_IACCOUNTINGDOCUMENTTYPE],
       s.[_key_IBUSINESSAREA],
       s.[_key_ICHARTOFACCOUNTS],
       s.[_key_ICOMPANYCODE],
       s.[_key_ICONTROLLINGAREA],
       s.[_key_ICOSTCENTER],
       s.[_key_ICUSTOMER],
       s.[_key_ICUSTOMERPAYMENTTERMS],
       s.[_key_IDEBITCREDITCODE],
       s.[_key_IDUNNINGAREA],
       s.[_key_IDUNNINGKEY],
       s.[_key_IFISCALPERIODFORVARIANT],
       s.[_key_IFISCALYEARFORCOMPANYCODE],
       s.[_key_IGLACCOUNTINCHARTOFACCOUNTS],
       s.[_key_IPAYMENTBLOCKINGREASON],
       s.[_key_IPAYMENTTERMS],
       s.[_key_IPOSTINGKEY],
       s.[_key_IPROFITCENTER],
       s.[_key_ISPECIALGLCODE],
       s.[_key_ISUPPLIER]
FROM [bps_gold_<system_suffix>].[dbo].[I_OPERATIONALACCTGDOCITEM] AS s
WHERE s.[_SystemName] = 'S4M' AND s.[COMPANYCODE] IN ('1710', '1720', '1730')
),
[gl_line] AS (
SELECT s.[ACCOUNTINGDOCUMENT],
       s.[ACCOUNTINGDOCUMENTCATEGORY],
       s.[ACCOUNTINGDOCUMENTITEM],
       s.[ACCOUNTINGDOCUMENTTYPE],
       s.[ADDITIONALCURRENCY1],
       s.[AMOUNTINADDITIONALCURRENCY1],
       s.[AMOUNTINCOMPANYCODECURRENCY],
       s.[AMOUNTINFUNCTIONALCURRENCY],
       s.[AMOUNTINGLOBALCURRENCY],
       s.[AMOUNTINTRANSACTIONCURRENCY],
       s.[BILLINGDOCUMENT],
       s.[BUSINESSAREA],
       s.[CHARTOFACCOUNTS],
       s.[CLEARINGACCOUNTINGDOCUMENT],
       s.[CLEARINGDATE],
       s.[CLEARINGDOCFISCALYEAR],
       s.[COMPANY],
       s.[COMPANYCODE],
       s.[COMPANYCODECURRENCY],
       s.[CONTROLLINGAREA],
       s.[COSTCENTER],
       s.[COSTCTRACTIVITYTYPE],
       s.[CUSTOMER],
       s.[CUSTOMERGROUP],
       s.[DEBITCREDITCODE],
       s.[DOCUMENTDATE],
       s.[DOCUMENTITEMTEXT],
       s.[DUNNINGAREA],
       s.[DUNNINGKEY],
       s.[EQUIPMENT],
       s.[FINANCIALACCOUNTTYPE],
       s.[FISCALPERIOD],
       s.[FISCALYEAR],
       s.[FISCALYEARPERIOD],
       s.[FISCALYEARVARIANT],
       s.[FIXEDASSET],
       s.[FUNCTIONALAREA],
       s.[FUNCTIONALCURRENCY],
       s.[FUNCTIONALLOCATION],
       s.[GLACCOUNT],
       s.[GLOBALCURRENCY],
       s.[INVOICEITEMREFERENCE],
       s.[INVOICEREFERENCE],
       s.[INVOICEREFERENCEFISCALYEAR],
       s.[ISOPENITEMMANAGED],
       s.[LEDGERFISCALYEAR],
       s.[LEDGERGLLINEITEM],
       s.[MASTERFIXEDASSET],
       s.[NETDUEDATE],
       s.[PARTNERCOMPANY],
       s.[PARTNERCOMPANYCODE],
       s.[PAYMENTBLOCKINGREASON],
       s.[PAYMENTTERMS],
       s.[PLANT],
       s.[POSTINGDATE],
       s.[POSTINGKEY],
       s.[PRODUCT],
       s.[PRODUCTGROUP],
       s.[PROFITCENTER],
       s.[SEGMENT],
       s.[SOURCELEDGER],
       s.[SPECIALGLCODE],
       s.[SUPPLIER],
       s.[TAXCODE],
       s.[TAXCOUNTRY],
       s.[TRANSACTIONCURRENCY],
       s.[WBSELEMENTINTERNALID],
       s.[_Delete],
       s.[_Reprocess],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP],
       s.[_key_IACCOUNTINGDOCUMENTTYPE],
       s.[_key_IBUSINESSAREA],
       s.[_key_ICHARTOFACCOUNTS],
       s.[_key_ICOMPANYCODE],
       s.[_key_ICONTROLLINGAREA],
       s.[_key_ICOSTCENTER],
       s.[_key_ICOSTCTRACTIVITYTYPE],
       s.[_key_ICUSTOMER],
       s.[_key_ICUSTOMERGROUP],
       s.[_key_IDEBITCREDITCODE],
       s.[_key_IEQUIPMENT],
       s.[_key_IFISCALPERIODFORVARIANT],
       s.[_key_IFISCALYEARFORCOMPANYCODE],
       s.[_key_IFISCALYEARVARIANT],
       s.[_key_IFIXEDASSET],
       s.[_key_IFUNCTIONALAREA],
       s.[_key_IFUNCTIONALLOCATION],
       s.[_key_IGLACCOUNTINCHARTOFACCOUNTS],
       s.[_key_IGLOBALCOMPANYCompany],
       s.[_key_IGLOBALCOMPANYPartnerCompany],
       s.[_key_ILEDGER],
       s.[_key_IPLANT],
       s.[_key_IPRODUCT],
       s.[_key_IPRODUCTGROUP2],
       s.[_key_IPROFITCENTER],
       s.[_key_ISEGMENT],
       s.[_key_ISUPPLIER],
       s.[_key_IWBSELEMENTDATA_2]
FROM [bps_gold_<system_suffix>].[dbo].[I_GLACCOUNTLINEITEMRAWDATA] AS s
WHERE s.[_SystemName] = 'S4M' AND s.[COMPANYCODE] IN ('1710', '1720', '1730')
),
[company_markers] AS (
SELECT _SystemName, COMPANYCODE,
    SUM(CASE WHEN _Delete IS NULL OR _Delete <> '' THEN 1 ELSE 0 END) AS unverified_marker_rows
FROM company GROUP BY _SystemName, COMPANYCODE
),
[scopes] AS (
SELECT _SystemName, COMPANYCODE, CURRENCY AS currency FROM company
WHERE _SystemName IS NOT NULL AND COMPANYCODE IS NOT NULL AND @as_of IS NOT NULL
UNION
SELECT _SystemName, COMPANYCODE, TRANSACTIONCURRENCY FROM operational_item WHERE POSTINGDATE <= @as_of
UNION
SELECT _SystemName, COMPANYCODE, TRANSACTIONCURRENCY FROM gl_line WHERE POSTINGDATE <= @as_of
),
[open_totals] AS (
SELECT _SystemName, COMPANYCODE, TRANSACTIONCURRENCY AS currency,
    SUM(CASE WHEN FINANCIALACCOUNTTYPE = 'D' THEN AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) AS ar_amount,
    -SUM(CASE WHEN FINANCIALACCOUNTTYPE = 'K' THEN AMOUNTINTRANSACTIONCURRENCY ELSE 0 END) AS ap_amount,
    SUM(CASE WHEN FINANCIALACCOUNTTYPE = 'D' AND AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) AS ar_missing,
    SUM(CASE WHEN FINANCIALACCOUNTTYPE = 'K' AND AMOUNTINTRANSACTIONCURRENCY IS NULL THEN 1 ELSE 0 END) AS ap_missing,
    SUM(CASE WHEN _Delete IS NULL OR _Delete <> '' THEN 1 ELSE 0 END) AS unverified_marker_rows,
    COUNT_BIG(*) AS open_item_rows
FROM operational_item
WHERE POSTINGDATE <= @as_of AND (CLEARINGDATE IS NULL OR CLEARINGDATE > @as_of)
 AND FINANCIALACCOUNTTYPE IN ('D', 'K')
GROUP BY _SystemName, COMPANYCODE, TRANSACTIONCURRENCY
)
SELECT s._SystemName, s.COMPANYCODE, s.currency, @as_of AS as_of,
    CASE WHEN t.ar_missing > 0 THEN NULL ELSE COALESCE(t.ar_amount, 0) END AS receivables_outstanding,
    CASE WHEN t.ap_missing > 0 THEN NULL ELSE COALESCE(t.ap_amount, 0) END AS payables_outstanding,
    COALESCE(t.ar_missing, 0) AS ar_missing_amount_rows,
    COALESCE(t.ap_missing, 0) AS ap_missing_amount_rows,
    COALESCE(t.unverified_marker_rows, 0) AS unverified_marker_rows,
    COALESCE(c.unverified_marker_rows, 0) AS scope_unverified_marker_rows,
    CASE WHEN c.COMPANYCODE IS NULL OR c.unverified_marker_rows > 0 OR t.unverified_marker_rows > 0
      THEN 'unverified_native_markers' ELSE 'observed_blank_markers' END AS native_state_status,
    COALESCE(t.open_item_rows, 0) AS open_item_rows
FROM scopes s
LEFT JOIN company_markers c ON c._SystemName = s._SystemName AND c.COMPANYCODE = s.COMPANYCODE
LEFT JOIN open_totals t ON t._SystemName = s._SystemName AND t.COMPANYCODE = s.COMPANYCODE
 AND (t.currency = s.currency OR (t.currency IS NULL AND s.currency IS NULL))
);
-- @batch
CREATE OR ALTER FUNCTION [sap_live].[payment_journal](@as_of date)
RETURNS TABLE
AS RETURN (
WITH [gl_line] AS (
SELECT s.[ACCOUNTINGDOCUMENT],
       s.[ACCOUNTINGDOCUMENTCATEGORY],
       s.[ACCOUNTINGDOCUMENTITEM],
       s.[ACCOUNTINGDOCUMENTTYPE],
       s.[ADDITIONALCURRENCY1],
       s.[AMOUNTINADDITIONALCURRENCY1],
       s.[AMOUNTINCOMPANYCODECURRENCY],
       s.[AMOUNTINFUNCTIONALCURRENCY],
       s.[AMOUNTINGLOBALCURRENCY],
       s.[AMOUNTINTRANSACTIONCURRENCY],
       s.[BILLINGDOCUMENT],
       s.[BUSINESSAREA],
       s.[CHARTOFACCOUNTS],
       s.[CLEARINGACCOUNTINGDOCUMENT],
       s.[CLEARINGDATE],
       s.[CLEARINGDOCFISCALYEAR],
       s.[COMPANY],
       s.[COMPANYCODE],
       s.[COMPANYCODECURRENCY],
       s.[CONTROLLINGAREA],
       s.[COSTCENTER],
       s.[COSTCTRACTIVITYTYPE],
       s.[CUSTOMER],
       s.[CUSTOMERGROUP],
       s.[DEBITCREDITCODE],
       s.[DOCUMENTDATE],
       s.[DOCUMENTITEMTEXT],
       s.[DUNNINGAREA],
       s.[DUNNINGKEY],
       s.[EQUIPMENT],
       s.[FINANCIALACCOUNTTYPE],
       s.[FISCALPERIOD],
       s.[FISCALYEAR],
       s.[FISCALYEARPERIOD],
       s.[FISCALYEARVARIANT],
       s.[FIXEDASSET],
       s.[FUNCTIONALAREA],
       s.[FUNCTIONALCURRENCY],
       s.[FUNCTIONALLOCATION],
       s.[GLACCOUNT],
       s.[GLOBALCURRENCY],
       s.[INVOICEITEMREFERENCE],
       s.[INVOICEREFERENCE],
       s.[INVOICEREFERENCEFISCALYEAR],
       s.[ISOPENITEMMANAGED],
       s.[LEDGERFISCALYEAR],
       s.[LEDGERGLLINEITEM],
       s.[MASTERFIXEDASSET],
       s.[NETDUEDATE],
       s.[PARTNERCOMPANY],
       s.[PARTNERCOMPANYCODE],
       s.[PAYMENTBLOCKINGREASON],
       s.[PAYMENTTERMS],
       s.[PLANT],
       s.[POSTINGDATE],
       s.[POSTINGKEY],
       s.[PRODUCT],
       s.[PRODUCTGROUP],
       s.[PROFITCENTER],
       s.[SEGMENT],
       s.[SOURCELEDGER],
       s.[SPECIALGLCODE],
       s.[SUPPLIER],
       s.[TAXCODE],
       s.[TAXCOUNTRY],
       s.[TRANSACTIONCURRENCY],
       s.[WBSELEMENTINTERNALID],
       s.[_Delete],
       s.[_Reprocess],
       s.[_SystemName],
       s.[_UpdateTimeStamp],
       s.[__SEQUENCE_NUMBER],
       s.[__TIMESTAMP],
       s.[_key_IACCOUNTINGDOCUMENTTYPE],
       s.[_key_IBUSINESSAREA],
       s.[_key_ICHARTOFACCOUNTS],
       s.[_key_ICOMPANYCODE],
       s.[_key_ICONTROLLINGAREA],
       s.[_key_ICOSTCENTER],
       s.[_key_ICOSTCTRACTIVITYTYPE],
       s.[_key_ICUSTOMER],
       s.[_key_ICUSTOMERGROUP],
       s.[_key_IDEBITCREDITCODE],
       s.[_key_IEQUIPMENT],
       s.[_key_IFISCALPERIODFORVARIANT],
       s.[_key_IFISCALYEARFORCOMPANYCODE],
       s.[_key_IFISCALYEARVARIANT],
       s.[_key_IFIXEDASSET],
       s.[_key_IFUNCTIONALAREA],
       s.[_key_IFUNCTIONALLOCATION],
       s.[_key_IGLACCOUNTINCHARTOFACCOUNTS],
       s.[_key_IGLOBALCOMPANYCompany],
       s.[_key_IGLOBALCOMPANYPartnerCompany],
       s.[_key_ILEDGER],
       s.[_key_IPLANT],
       s.[_key_IPRODUCT],
       s.[_key_IPRODUCTGROUP2],
       s.[_key_IPROFITCENTER],
       s.[_key_ISEGMENT],
       s.[_key_ISUPPLIER],
       s.[_key_IWBSELEMENTDATA_2]
FROM [bps_gold_<system_suffix>].[dbo].[I_GLACCOUNTLINEITEMRAWDATA] AS s
WHERE s.[_SystemName] = 'S4M' AND s.[COMPANYCODE] IN ('1710', '1720', '1730')
)
SELECT g.[ACCOUNTINGDOCUMENT],
    g.[ACCOUNTINGDOCUMENTCATEGORY],
    g.[ACCOUNTINGDOCUMENTITEM],
    g.[ACCOUNTINGDOCUMENTTYPE],
    g.[ADDITIONALCURRENCY1],
    g.[AMOUNTINADDITIONALCURRENCY1],
    g.[AMOUNTINCOMPANYCODECURRENCY],
    g.[AMOUNTINFUNCTIONALCURRENCY],
    g.[AMOUNTINGLOBALCURRENCY],
    g.[AMOUNTINTRANSACTIONCURRENCY],
    g.[BILLINGDOCUMENT],
    g.[BUSINESSAREA],
    g.[CHARTOFACCOUNTS],
    g.[CLEARINGACCOUNTINGDOCUMENT],
    g.[CLEARINGDATE],
    g.[CLEARINGDOCFISCALYEAR],
    g.[COMPANY],
    g.[COMPANYCODE],
    g.[COMPANYCODECURRENCY],
    g.[CONTROLLINGAREA],
    g.[COSTCENTER],
    g.[COSTCTRACTIVITYTYPE],
    g.[CUSTOMER],
    g.[CUSTOMERGROUP],
    g.[DEBITCREDITCODE],
    g.[DOCUMENTDATE],
    g.[DOCUMENTITEMTEXT],
    g.[DUNNINGAREA],
    g.[DUNNINGKEY],
    g.[EQUIPMENT],
    g.[FINANCIALACCOUNTTYPE],
    g.[FISCALPERIOD],
    g.[FISCALYEAR],
    g.[FISCALYEARPERIOD],
    g.[FISCALYEARVARIANT],
    g.[FIXEDASSET],
    g.[FUNCTIONALAREA],
    g.[FUNCTIONALCURRENCY],
    g.[FUNCTIONALLOCATION],
    g.[GLACCOUNT],
    g.[GLOBALCURRENCY],
    g.[INVOICEITEMREFERENCE],
    g.[INVOICEREFERENCE],
    g.[INVOICEREFERENCEFISCALYEAR],
    g.[ISOPENITEMMANAGED],
    g.[LEDGERFISCALYEAR],
    g.[LEDGERGLLINEITEM],
    g.[MASTERFIXEDASSET],
    g.[NETDUEDATE],
    g.[PARTNERCOMPANY],
    g.[PARTNERCOMPANYCODE],
    g.[PAYMENTBLOCKINGREASON],
    g.[PAYMENTTERMS],
    g.[PLANT],
    g.[POSTINGDATE],
    g.[POSTINGKEY],
    g.[PRODUCT],
    g.[PRODUCTGROUP],
    g.[PROFITCENTER],
    g.[SEGMENT],
    g.[SOURCELEDGER],
    g.[SPECIALGLCODE],
    g.[SUPPLIER],
    g.[TAXCODE],
    g.[TAXCOUNTRY],
    g.[TRANSACTIONCURRENCY],
    g.[WBSELEMENTINTERNALID],
    g.[_Delete],
    g.[_Reprocess],
    g.[_SystemName],
    g.[_UpdateTimeStamp],
    g.[__SEQUENCE_NUMBER],
    g.[__TIMESTAMP],
    g.[_key_IACCOUNTINGDOCUMENTTYPE],
    g.[_key_IBUSINESSAREA],
    g.[_key_ICHARTOFACCOUNTS],
    g.[_key_ICOMPANYCODE],
    g.[_key_ICONTROLLINGAREA],
    g.[_key_ICOSTCENTER],
    g.[_key_ICOSTCTRACTIVITYTYPE],
    g.[_key_ICUSTOMER],
    g.[_key_ICUSTOMERGROUP],
    g.[_key_IDEBITCREDITCODE],
    g.[_key_IEQUIPMENT],
    g.[_key_IFISCALPERIODFORVARIANT],
    g.[_key_IFISCALYEARFORCOMPANYCODE],
    g.[_key_IFISCALYEARVARIANT],
    g.[_key_IFIXEDASSET],
    g.[_key_IFUNCTIONALAREA],
    g.[_key_IFUNCTIONALLOCATION],
    g.[_key_IGLACCOUNTINCHARTOFACCOUNTS],
    g.[_key_IGLOBALCOMPANYCompany],
    g.[_key_IGLOBALCOMPANYPartnerCompany],
    g.[_key_ILEDGER],
    g.[_key_IPLANT],
    g.[_key_IPRODUCT],
    g.[_key_IPRODUCTGROUP2],
    g.[_key_IPROFITCENTER],
    g.[_key_ISEGMENT],
    g.[_key_ISUPPLIER],
    g.[_key_IWBSELEMENTDATA_2],
    CASE WHEN g._Delete = '' THEN 'observed_blank_markers' ELSE 'unverified_native_markers' END AS native_state_status,
    @as_of AS as_of
FROM gl_line g
WHERE g.ACCOUNTINGDOCUMENTTYPE IN ('DZ', 'DA', 'KZ') AND g.POSTINGDATE <= @as_of
);
