#!/usr/bin/env bash
set -euo pipefail

ORACLE_HOME="/opt/oracle/product/26ai/dbhomeFree"
ORACLE_SID="FREE"
export ORACLE_HOME ORACLE_SID
export PATH="$ORACLE_HOME/bin:$PATH"

sudo -u oracle env ORACLE_HOME="$ORACLE_HOME" ORACLE_SID="$ORACLE_SID" PATH="$PATH" \
    "$ORACLE_HOME/bin/sqlplus" -s "/ as sysdba" <<'SQL'
set echo off feedback off heading off pagesize 0 linesize 200 verify off
whenever sqlerror exit sql.sqlcode rollback

alter system archive log current;
alter system switch logfile;
alter system archive log current;

select 'ARCHIVED_LOG_COUNT=' || count(*) from v$archived_log;
select 'MAX_NEXT_CHANGE=' || max(next_change#) from v$archived_log;
select 'CURRENT_SCN=' || current_scn from v$database;

exit success
SQL
