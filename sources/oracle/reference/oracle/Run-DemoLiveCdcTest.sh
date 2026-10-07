#!/usr/bin/env bash
set -euo pipefail

ORACLE_HOME="/opt/oracle/product/26ai/dbhomeFree"
ORACLE_SID="FREE"
export ORACLE_HOME ORACLE_SID
export PATH="$ORACLE_HOME/bin:$PATH"

sudo -u oracle env ORACLE_HOME="$ORACLE_HOME" ORACLE_SID="$ORACLE_SID" PATH="$PATH" \
    "$ORACLE_HOME/bin/sqlplus" -s "/ as sysdba" <<'SQL'
set echo off feedback on heading on pagesize 100 linesize 200 verify off
whenever sqlerror exit sql.sqlcode rollback

alter session set container=FREEPDB1;

merge into DEMO_DW.FACT_SALES target
using (
  select
    900000000000002 sales_key,
    20250102 date_key,
    2 customer_key,
    2 product_key,
    2 store_key,
    4 quantity,
    222.25 unit_price,
    889.00 sales_amount
  from dual
) source
on (target.sales_key = source.sales_key)
when matched then update set
  target.quantity = source.quantity,
  target.unit_price = source.unit_price,
  target.sales_amount = source.sales_amount,
  target.updated_at = sysdate
when not matched then insert (
  sales_key,
  date_key,
  customer_key,
  product_key,
  store_key,
  quantity,
  unit_price,
  sales_amount,
  updated_at
) values (
  source.sales_key,
  source.date_key,
  source.customer_key,
  source.product_key,
  source.store_key,
  source.quantity,
  source.unit_price,
  source.sales_amount,
  sysdate
);

update DEMO_DW.DIM_CUSTOMER
set segment_name = 'CDC_LIVE'
where customer_key = 2;

delete from DEMO_DW.FACT_SALES
where sales_key = 24998;

commit;

alter session set container=CDB$ROOT;
alter system archive log current;

alter session set container=FREEPDB1;
select 'INSERTED=' || count(*) from DEMO_DW.FACT_SALES where sales_key = 900000000000002;
select 'UPDATED=' || segment_name from DEMO_DW.DIM_CUSTOMER where customer_key = 2;
select 'DELETED=' || count(*) from DEMO_DW.FACT_SALES where sales_key = 24998;
select 'FACT_COUNT=' || count(*) from DEMO_DW.FACT_SALES;

exit success
SQL
