#!/usr/bin/env bash
set -euo pipefail

SALE_KEY="${1:?Sales key is required}"
if [[ ! "$SALE_KEY" =~ ^[0-9]{1,18}$ ]]; then
    echo "Sales key must contain 1 to 18 digits." >&2
    exit 1
fi

ORACLE_HOME="/opt/oracle/product/26ai/dbhomeFree"
ORACLE_SID="FREE"
export ORACLE_HOME ORACLE_SID
export PATH="$ORACLE_HOME/bin:$PATH"

sudo -u oracle env ORACLE_HOME="$ORACLE_HOME" ORACLE_SID="$ORACLE_SID" PATH="$PATH" \
    "$ORACLE_HOME/bin/sqlplus" -s "/ as sysdba" <<SQL
set echo off feedback off heading off pagesize 0 linesize 200 verify off
whenever sqlerror exit sql.sqlcode rollback

alter session set container=FREEPDB1;

insert into DEMO_DW.FACT_SALES (
  SALES_KEY,
  DATE_KEY,
  CUSTOMER_KEY,
  PRODUCT_KEY,
  STORE_KEY,
  QUANTITY,
  UNIT_PRICE,
  SALES_AMOUNT,
  UPDATED_AT
) values (
  $SALE_KEY,
  20250102,
  2,
  2,
  2,
  1,
  19.95,
  19.95,
  sysdate
);

commit;

alter session set container=CDB\$ROOT;
alter system archive log current;

alter session set container=FREEPDB1;
select 'ORACLE_INSERTED=' || count(*)
from DEMO_DW.FACT_SALES
where SALES_KEY = $SALE_KEY;
select 'SALES_KEY=$SALE_KEY' from dual;

exit success
SQL
