#!/usr/bin/env bash
set -euo pipefail
sudo demo-sqlplus <<'SQL'
whenever oserror exit failure rollback
whenever sqlerror exit failure rollback
set heading off
set feedback off
alter session set container = FREEPDB1;
select 'MSFLIX_CONTENT_COUNT='||count(*) from DEMO_DW.REF_CONTENT;
select 'MSFLIX_PRICE_RULE_COUNT='||count(*) from DEMO_DW.REF_PRICE_RULE;
select 'BASE_TABLE_COUNT='||count(*) from all_tables where owner='DEMO_DW'
  and table_name in ('DIM_DATE','DIM_CUSTOMER','DIM_PRODUCT','DIM_STORE','FACT_SALES');
select 'REF_LOGGING_COUNT='||count(distinct table_name) from all_log_groups
  where owner='DEMO_DW' and log_group_type='ALL COLUMN LOGGING'
    and table_name in ('REF_CONTENT','REF_OFFER','REF_DISTRIBUTOR','REF_TERRITORY','REF_PRICE_RULE');
exit success
SQL

