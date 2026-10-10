-- Render SAP_DOMAIN_DDL from warehouse.py's explicit native business field whitelist.
-- This batch executes INSIDE the SAP publication transaction. No shared master/fact
-- or gold.publication is changed. No DROP, TRUNCATE, or schema auto-migration.
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name='gold')
    THROW 51100, 'Existing operational Gold schema required', 1;

IF OBJECT_ID('gold.sap_writer_guard','U') IS NULL
BEGIN
    CREATE TABLE gold.sap_writer_guard (resource_name varchar(128) NOT NULL, generation bigint NOT NULL);
    INSERT INTO gold.sap_writer_guard SELECT 'MSFlixGold.SAP', 0;
END;
IF (SELECT COUNT_BIG(*) FROM gold.sap_writer_guard)<>1
   OR NOT EXISTS (SELECT 1 FROM gold.sap_writer_guard WHERE resource_name='MSFlixGold.SAP')
    THROW 51100, 'SAP writer resource missing/ambiguous', 1;
-- Fabric snapshot isolation detects conflicting writes to this common resource.
-- Concurrent first-time DDL also conflicts. No retry: the losing writer must fail.
UPDATE gold.sap_writer_guard SET generation=generation+1 WHERE resource_name='MSFlixGold.SAP';

IF OBJECT_ID('gold.sap_publication','U') IS NULL
CREATE TABLE gold.sap_publication (
    source_system varchar(16) NOT NULL, company_scope varchar(4) NOT NULL,
    scenario_id varchar(128) NOT NULL, run_id varchar(128) NOT NULL, as_of date NOT NULL,
    source_workspace_id varchar(36) NOT NULL, source_item_id varchar(36) NOT NULL,
    source_endpoint_id varchar(36) NOT NULL, source_database varchar(128) NOT NULL,
    b2s_job_id varchar(36) NOT NULL, s2g_job_id varchar(36) NOT NULL,
    input_sha256 varchar(64) NOT NULL, catalog_sha256 varchar(64) NOT NULL,
    data_sha256 varchar(64) NOT NULL, journal_lines bigint NOT NULL,
    accounting_documents bigint NOT NULL, net_billings decimal(23,2) NOT NULL,
    recognized_revenue decimal(23,2) NOT NULL, content_cost decimal(23,2) NOT NULL,
    receivables decimal(23,2) NOT NULL, payables decimal(23,2) NOT NULL,
    net_bank_movement decimal(23,2) NOT NULL, net_vat_liability decimal(23,2) NOT NULL,
    completed_at datetime2(6) NOT NULL
);
{{SAP_DOMAIN_DDL}}
