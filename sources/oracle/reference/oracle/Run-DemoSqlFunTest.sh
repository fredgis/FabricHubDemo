#!/usr/bin/env bash
set -euo pipefail

ORACLE_HOME="/opt/oracle/product/26ai/dbhomeFree"
ORACLE_SID="FREE"
export ORACLE_HOME ORACLE_SID
export PATH="$ORACLE_HOME/bin:$PATH"

OUTPUT="$(sudo -u oracle env ORACLE_HOME="$ORACLE_HOME" ORACLE_SID="$ORACLE_SID" PATH="$PATH" \
    "$ORACLE_HOME/bin/sqlplus" -s "/ as sysdba" <<'SQL'
set echo off feedback off heading off pagesize 100 linesize 100 verify off
whenever sqlerror exit sql.sqlcode rollback
alter session set container=FREEPDB1;
set heading on
column SALES_BY_STORE format a45
column GALAXY format a70

prompt
prompt SALES BY STORE
select lpad(store_key, 2, '0') || ' | ' || rpad('#', round(sum(sales_amount) / max(sum(sales_amount)) over () * 40), '#') as SALES_BY_STORE from DEMO_DW.FACT_SALES group by store_key order by store_key;

prompt
prompt RANDOM GALAXY
select listagg(case when star < 0.02 then '@' when star < 0.06 then '*' when star < 0.15 then '.' else ' ' end, '') within group (order by col_no) as GALAXY from (select ceil(level / 70) as row_no, mod(level - 1, 70) + 1 as col_no, dbms_random.value as star from dual connect by level <= 1400) group by row_no order by row_no;

set heading off feedback off
select 'SALES_CHART_ROWS=' || count(distinct store_key) from DEMO_DW.FACT_SALES;
select 'GALAXY_ROWS=' || count(distinct ceil(level / 70)) from dual connect by level <= 1400;
exit success
SQL
)"

printf '%s\n' "$OUTPUT"

if ! grep -q 'SALES_CHART_ROWS=20' <<<"$OUTPUT"; then
    echo 'The sales chart did not return 20 stores.' >&2
    exit 1
fi
if ! grep -q 'GALAXY_ROWS=20' <<<"$OUTPUT"; then
    echo 'The galaxy did not return 20 rows.' >&2
    exit 1
fi

echo 'SQL_FUN_VALID=true'
