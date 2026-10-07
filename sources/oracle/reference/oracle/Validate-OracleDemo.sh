#!/usr/bin/env bash
set -euo pipefail

ORACLE_HOME="/opt/oracle/product/26ai/dbhomeFree"
ORACLE_SID="FREE"
export ORACLE_HOME ORACLE_SID
export PATH="$ORACLE_HOME/bin:$PATH"

if [[ ! -x /usr/local/bin/demo-sqlplus ]]; then
    echo 'The demo-sqlplus helper is not installed.' >&2
    exit 1
fi

DEMO_SQLPLUS_OUTPUT="$(sudo demo-sqlplus <<'SQL'
set heading off feedback off pagesize 0 verify off
select 'DEMO_TABLES=' || count(*)
from all_tables
where owner = 'DEMO_DW';
exit success
SQL
)"
if ! grep -q 'Connected to FREEPDB1' <<<"$DEMO_SQLPLUS_OUTPUT" ||
   ! grep -q 'DEMO_TABLES=5' <<<"$DEMO_SQLPLUS_OUTPUT"; then
    echo 'The demo-sqlplus helper did not open FREEPDB1 with the five demo tables.' >&2
    exit 1
fi

if ! pgrep -f '([do]b|[or]a)_pmon_FREE' >/dev/null 2>&1; then
    echo 'Oracle instance FREE is not running.' >&2
    exit 1
fi

if ! lsnrctl status | grep -qi 'FREEPDB1'; then
    echo 'Oracle listener does not advertise FREEPDB1.' >&2
    exit 1
fi

if ! firewall-cmd --query-port=1521/tcp >/dev/null ||
   ! firewall-cmd --permanent --query-port=1521/tcp >/dev/null; then
    echo 'Oracle firewalld does not allow 1521/tcp in both runtime and permanent configuration.' >&2
    exit 1
fi

sudo -u oracle env ORACLE_HOME="$ORACLE_HOME" ORACLE_SID="$ORACLE_SID" PATH="$PATH" \
    "$ORACLE_HOME/bin/sqlplus" -s "/ as sysdba" <<'SQL'
set echo off feedback off heading off pagesize 0 linesize 200 verify off
whenever sqlerror exit sql.sqlcode rollback

select 'LOG_MODE=' || log_mode from v$database;
select 'SUPPLEMENTAL_MIN=' || supplemental_log_data_min from v$database;
select 'SUPPLEMENTAL_PK=' || supplemental_log_data_pk from v$database;
select 'SUPPLEMENTAL_UI=' || supplemental_log_data_ui from v$database;
select 'PDB_OPEN_MODE=' || open_mode from v$pdbs where name = 'FREEPDB1';
select 'DATAFILES_ON_U02=' || count(*) from v$datafile where name like '/u02/%';

alter session set container=FREEPDB1;

select 'DIM_DATE=' || count(*) from DEMO_DW.DIM_DATE;
select 'DIM_CUSTOMER=' || count(*) from DEMO_DW.DIM_CUSTOMER;
select 'DIM_PRODUCT=' || count(*) from DEMO_DW.DIM_PRODUCT;
select 'DIM_STORE=' || count(*) from DEMO_DW.DIM_STORE;
select 'FACT_SALES=' || count(*) from DEMO_DW.FACT_SALES;
select 'MIRROR_USER=' || count(*) from dba_users where username = 'C##FABRIC_MIRROR';

exit success
SQL

echo 'DEMO_SQLPLUS=ready'
echo 'ORACLE_FIREWALL_1521=ready'
