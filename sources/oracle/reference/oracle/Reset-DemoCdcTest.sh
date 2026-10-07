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

delete from DEMO_DW.FACT_SALES
where sales_key > 25000;

merge into DEMO_DW.FACT_SALES target
using (
  select
    level sales_key,
    to_number(to_char(date '2025-01-01' + mod(level - 1, 731), 'YYYYMMDD')) date_key,
    mod(level * 7, 500) + 1 customer_key,
    mod(level * 11, 100) + 1 product_key,
    mod(level * 13, 20) + 1 store_key,
    mod(level, 8) + 1 quantity,
    round(10 + mod(level * 31, 900) / 10, 2) unit_price
  from dual
  connect by level <= 25000
) source
on (target.sales_key = source.sales_key)
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
  round(source.quantity * source.unit_price, 2),
  sysdate
);

update DEMO_DW.DIM_CUSTOMER
set segment_name = 'Consumer'
where customer_key = 2;

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
