#!/usr/bin/env bash
set -euo pipefail

KEY_VAULT_NAME="${1:?Key Vault name is required}"
RPM_URL="${2:?Oracle RPM URL is required}"
RPM_SHA256="${3:?Oracle RPM SHA-256 is required}"
ORACLE_RPM="/var/tmp/$(basename "$RPM_URL")"
ORACLE_HOME="/opt/oracle/product/26ai/dbhomeFree"
ORACLE_SID="FREE"
DATA_MOUNT="/u02"
DATA_DEVICE=""
STATE_DIRECTORY="/var/lib/oracle-to-fabric-demo"
CONFIGURED_MARKER="$STATE_DIRECTORY/oracle-configured-v1"

log() {
    printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"
}

get_managed_identity_token() {
    curl --fail --silent --show-error \
        --header Metadata:true \
        'http://169.254.169.254/metadata/identity/oauth2/token?api-version=2019-08-01&resource=https%3A%2F%2Fvault.azure.net' \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'
}

get_secret() {
    local name="$1"
    local token
    token="$(get_managed_identity_token)"
    curl --fail --silent --show-error \
        --header "Authorization: Bearer $token" \
        "https://${KEY_VAULT_NAME}.vault.azure.net/secrets/${name}?api-version=7.4" \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["value"])'
}

ensure_oracle_firewall() {
    systemctl enable --now firewalld >/dev/null
    firewall-cmd --add-port=1521/tcp >/dev/null
    firewall-cmd --permanent --add-port=1521/tcp >/dev/null
    firewall-cmd --query-port=1521/tcp >/dev/null
    firewall-cmd --permanent --query-port=1521/tcp >/dev/null
}

find_data_device() {
    local device
    while read -r device; do
        if ! lsblk -nrpo MOUNTPOINT "$device" | grep -Eq '^/$|^/boot($|/)'; then
            printf '%s\n' "$device"
            return
        fi
    done < <(lsblk -dpno NAME,TYPE | awk '$2 == "disk" { print $1 }')
}

wait_for_device() {
    local attempt
    for attempt in $(seq 1 30); do
        DATA_DEVICE="$(find_data_device)"
        if [[ -n "$DATA_DEVICE" && -b "$DATA_DEVICE" ]]; then
            return
        fi
        sleep 5
    done
    log "No unmounted data disk was detected"
    exit 1
}

log "Preparing Oracle data disk"
wait_for_device
if ! blkid "$DATA_DEVICE" >/dev/null 2>&1; then
    mkfs.xfs -f "$DATA_DEVICE"
fi
mkdir -p "$DATA_MOUNT"
DEVICE_UUID="$(blkid -s UUID -o value "$DATA_DEVICE")"
if ! grep -q "UUID=${DEVICE_UUID}" /etc/fstab; then
    printf 'UUID=%s %s xfs defaults,nofail 0 2\n' "$DEVICE_UUID" "$DATA_MOUNT" >> /etc/fstab
fi
if ! mountpoint -q "$DATA_MOUNT"; then
    mount "$DATA_MOUNT" || mount -a
fi

log "Installing Oracle prerequisites"
dnf install -y oracle-ai-database-preinstall-26ai curl python3
mkdir -p "$DATA_MOUNT/oradata" "$DATA_MOUNT/archivelog"
chown -R oracle:oinstall "$DATA_MOUNT"
chmod 750 "$DATA_MOUNT" "$DATA_MOUNT/oradata" "$DATA_MOUNT/archivelog"

if ! rpm -q oracle-ai-database-free-26ai >/dev/null 2>&1; then
    log "Downloading Oracle AI Database Free"
    curl --fail --location --retry 5 --retry-delay 10 --output "$ORACLE_RPM" "$RPM_URL"
    printf '%s  %s\n' "$RPM_SHA256" "$ORACLE_RPM" | sha256sum --check -
    dnf install -y "$ORACLE_RPM"
fi

CONFIG_FILE="/etc/sysconfig/oracle-free-26ai.conf"
if grep -q '^DBFILE_DEST=' "$CONFIG_FILE"; then
    sed -i "s|^DBFILE_DEST=.*|DBFILE_DEST=${DATA_MOUNT}/oradata|" "$CONFIG_FILE"
else
    printf '\nDBFILE_DEST=%s/oradata\n' "$DATA_MOUNT" >> "$CONFIG_FILE"
fi
if grep -q '^LISTENER_PORT=' "$CONFIG_FILE"; then
    sed -i 's|^LISTENER_PORT=.*|LISTENER_PORT=1521|' "$CONFIG_FILE"
fi

ORACLE_PASSWORD="$(get_secret demo-oracle-sys-password)"
SCHEMA_PASSWORD="$(get_secret demo-schema-password)"
MIRROR_PASSWORD="$(get_secret demo-mirror-password)"

if [[ ! -f "$DATA_MOUNT/oradata/FREE/system01.dbf" ]]; then
    log "Configuring Oracle AI Database Free"
    (printf '%s\n%s\n' "$ORACLE_PASSWORD" "$ORACLE_PASSWORD") \
        | /etc/init.d/oracle-free-26ai configure
elif ! pgrep -f '([do]b|[or]a)_pmon_FREE' >/dev/null 2>&1; then
    /etc/init.d/oracle-free-26ai start
fi

export ORACLE_HOME ORACLE_SID
export PATH="$ORACLE_HOME/bin:$PATH"

install -d -m 0755 /usr/local/share/oracle-to-fabric-demo
cat > /usr/local/share/oracle-to-fabric-demo/login.sql <<'SQL'
whenever sqlerror continue
alter session set container=FREEPDB1;
set linesize 200
set pagesize 100
prompt
prompt Connected to FREEPDB1. Demo schema: DEMO_DW
show con_name
SQL

cat > /usr/local/bin/demo-sqlplus <<'SH'
#!/usr/bin/env bash
set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then
    echo "Run: sudo demo-sqlplus" >&2
    exit 1
fi

ORACLE_HOME="/opt/oracle/product/26ai/dbhomeFree"
ORACLE_SID="FREE"
export ORACLE_HOME ORACLE_SID
export PATH="$ORACLE_HOME/bin:$PATH"

exec runuser -u oracle -- env \
    ORACLE_HOME="$ORACLE_HOME" \
    ORACLE_SID="$ORACLE_SID" \
    PATH="$PATH" \
    "$ORACLE_HOME/bin/sqlplus" "/ as sysdba" \
    @/usr/local/share/oracle-to-fabric-demo/login.sql
SH
chmod 0755 /usr/local/bin/demo-sqlplus
ln -sfn /usr/local/bin/demo-sqlplus /usr/bin/demo-sqlplus

ensure_oracle_firewall

if [[ -f "$CONFIGURED_MARKER" ]]; then
    chkconfig oracle-free-26ai on
    log "Oracle to Fabric Demo database is already configured"
    exit 0
fi

log "Configuring archive logging and Demo schemas"
sudo -u oracle env ORACLE_HOME="$ORACLE_HOME" ORACLE_SID="$ORACLE_SID" PATH="$PATH" \
    "$ORACLE_HOME/bin/sqlplus" -s "/ as sysdba" <<SQL
set echo off feedback on heading on pagesize 100 linesize 200 verify off
whenever sqlerror exit sql.sqlcode rollback

shutdown immediate;
startup mount;
alter system set log_archive_dest_1='LOCATION=${DATA_MOUNT}/archivelog' scope=spfile;
alter database archivelog;
alter database open;
alter pluggable database all open;
alter pluggable database all save state;
alter database add supplemental log data;
alter database add supplemental log data (primary key, unique) columns;

begin
  execute immediate 'drop user C##FABRIC_MIRROR cascade';
exception
  when others then
    if sqlcode != -1918 then
      raise;
    end if;
end;
/

create user C##FABRIC_MIRROR identified by "${MIRROR_PASSWORD}" container=all;
grant create session to C##FABRIC_MIRROR container=all;
grant select_catalog_role to C##FABRIC_MIRROR container=all;
grant connect, resource to C##FABRIC_MIRROR container=all;
grant execute_catalog_role to C##FABRIC_MIRROR container=all;
grant flashback any table to C##FABRIC_MIRROR container=all;
grant select any dictionary to C##FABRIC_MIRROR container=all;
grant select any table to C##FABRIC_MIRROR container=all;
grant logmining to C##FABRIC_MIRROR container=all;

alter session set container=FREEPDB1;

begin
  execute immediate 'drop user DEMO_DW cascade';
exception
  when others then
    if sqlcode != -1918 then
      raise;
    end if;
end;
/

create user DEMO_DW identified by "${SCHEMA_PASSWORD}" quota unlimited on users;
grant create session, create table to DEMO_DW;

create table DEMO_DW.DIM_DATE (
  DATE_KEY number(8) not null,
  CALENDAR_DATE date not null,
  DAY_OF_MONTH number(2) not null,
  MONTH_NUMBER number(2) not null,
  MONTH_NAME varchar2(12) not null,
  QUARTER_NUMBER number(1) not null,
  YEAR_NUMBER number(4) not null,
  constraint PK_DIM_DATE primary key (DATE_KEY)
);

create table DEMO_DW.DIM_CUSTOMER (
  CUSTOMER_KEY number(10) not null,
  CUSTOMER_CODE varchar2(20) not null,
  CUSTOMER_NAME varchar2(100) not null,
  SEGMENT_NAME varchar2(30) not null,
  COUNTRY_CODE char(2) not null,
  CREATED_DATE date not null,
  constraint PK_DIM_CUSTOMER primary key (CUSTOMER_KEY),
  constraint UQ_DIM_CUSTOMER_CODE unique (CUSTOMER_CODE)
);

create table DEMO_DW.DIM_PRODUCT (
  PRODUCT_KEY number(10) not null,
  PRODUCT_CODE varchar2(20) not null,
  PRODUCT_NAME varchar2(100) not null,
  CATEGORY_NAME varchar2(30) not null,
  UNIT_COST number(12,2) not null,
  LIST_PRICE number(12,2) not null,
  constraint PK_DIM_PRODUCT primary key (PRODUCT_KEY),
  constraint UQ_DIM_PRODUCT_CODE unique (PRODUCT_CODE)
);

create table DEMO_DW.DIM_STORE (
  STORE_KEY number(10) not null,
  STORE_CODE varchar2(20) not null,
  STORE_NAME varchar2(100) not null,
  REGION_NAME varchar2(30) not null,
  COUNTRY_CODE char(2) not null,
  constraint PK_DIM_STORE primary key (STORE_KEY),
  constraint UQ_DIM_STORE_CODE unique (STORE_CODE)
);

create table DEMO_DW.FACT_SALES (
  SALES_KEY number(18) not null,
  DATE_KEY number(8) not null,
  CUSTOMER_KEY number(10) not null,
  PRODUCT_KEY number(10) not null,
  STORE_KEY number(10) not null,
  QUANTITY number(9) not null,
  UNIT_PRICE number(12,2) not null,
  SALES_AMOUNT number(14,2) not null,
  UPDATED_AT date not null,
  constraint PK_FACT_SALES primary key (SALES_KEY),
  constraint FK_SALES_DATE foreign key (DATE_KEY) references DEMO_DW.DIM_DATE (DATE_KEY),
  constraint FK_SALES_CUSTOMER foreign key (CUSTOMER_KEY) references DEMO_DW.DIM_CUSTOMER (CUSTOMER_KEY),
  constraint FK_SALES_PRODUCT foreign key (PRODUCT_KEY) references DEMO_DW.DIM_PRODUCT (PRODUCT_KEY),
  constraint FK_SALES_STORE foreign key (STORE_KEY) references DEMO_DW.DIM_STORE (STORE_KEY)
);

insert into DEMO_DW.DIM_DATE
select
  to_number(to_char(date '2025-01-01' + level - 1, 'YYYYMMDD')),
  date '2025-01-01' + level - 1,
  to_number(to_char(date '2025-01-01' + level - 1, 'DD')),
  to_number(to_char(date '2025-01-01' + level - 1, 'MM')),
  trim(to_char(date '2025-01-01' + level - 1, 'Month', 'NLS_DATE_LANGUAGE=English')),
  to_number(to_char(date '2025-01-01' + level - 1, 'Q')),
  to_number(to_char(date '2025-01-01' + level - 1, 'YYYY'))
from dual
connect by level <= 731;

insert into DEMO_DW.DIM_CUSTOMER
select
  level,
  'CUST-' || to_char(level, 'FM000000'),
  'Demo Customer ' || to_char(level, 'FM000000'),
  case mod(level, 4) when 0 then 'Enterprise' when 1 then 'Small Business' when 2 then 'Consumer' else 'Public Sector' end,
  case mod(level, 5) when 0 then 'FR' when 1 then 'US' when 2 then 'DE' when 3 then 'GB' else 'SE' end,
  date '2024-01-01' + mod(level, 365)
from dual
connect by level <= 500;

insert into DEMO_DW.DIM_PRODUCT
select
  level,
  'PROD-' || to_char(level, 'FM0000'),
  'Demo Product ' || to_char(level, 'FM0000'),
  case mod(level, 5) when 0 then 'Hardware' when 1 then 'Software' when 2 then 'Services' when 3 then 'Accessories' else 'Subscriptions' end,
  round(5 + mod(level * 17, 500) / 10, 2),
  round(10 + mod(level * 29, 900) / 10, 2)
from dual
connect by level <= 100;

insert into DEMO_DW.DIM_STORE
select
  level,
  'STORE-' || to_char(level, 'FM000'),
  'Demo Store ' || to_char(level, 'FM000'),
  case mod(level, 4) when 0 then 'North' when 1 then 'South' when 2 then 'East' else 'West' end,
  case mod(level, 5) when 0 then 'FR' when 1 then 'US' when 2 then 'DE' when 3 then 'GB' else 'SE' end
from dual
connect by level <= 20;

insert /*+ append */ into DEMO_DW.FACT_SALES
select
  level,
  to_number(to_char(date '2025-01-01' + mod(level - 1, 731), 'YYYYMMDD')),
  mod(level * 7, 500) + 1,
  mod(level * 11, 100) + 1,
  mod(level * 13, 20) + 1,
  mod(level, 8) + 1,
  round(10 + mod(level * 31, 900) / 10, 2),
  round((mod(level, 8) + 1) * (10 + mod(level * 31, 900) / 10), 2),
  sysdate
from dual
connect by level <= 25000;

alter table DEMO_DW.DIM_DATE add supplemental log data (all) columns;
alter table DEMO_DW.DIM_CUSTOMER add supplemental log data (all) columns;
alter table DEMO_DW.DIM_PRODUCT add supplemental log data (all) columns;
alter table DEMO_DW.DIM_STORE add supplemental log data (all) columns;
alter table DEMO_DW.FACT_SALES add supplemental log data (all) columns;

begin
  dbms_stats.gather_schema_stats('DEMO_DW');
end;
/

commit;

alter session set container=CDB\$ROOT;
alter system archive log current;
alter system switch logfile;
alter system archive log current;

select log_mode from v\$database;
alter session set container=FREEPDB1;
select 'DIM_DATE' table_name, count(*) row_count from DEMO_DW.DIM_DATE
union all select 'DIM_CUSTOMER', count(*) from DEMO_DW.DIM_CUSTOMER
union all select 'DIM_PRODUCT', count(*) from DEMO_DW.DIM_PRODUCT
union all select 'DIM_STORE', count(*) from DEMO_DW.DIM_STORE
union all select 'FACT_SALES', count(*) from DEMO_DW.FACT_SALES;

exit success
SQL

chkconfig oracle-free-26ai on

DATAFILE_COUNT="$(sudo -u oracle env ORACLE_HOME="$ORACLE_HOME" ORACLE_SID="$ORACLE_SID" PATH="$PATH" \
    "$ORACLE_HOME/bin/sqlplus" -s "/ as sysdba" <<'SQL'
set heading off feedback off pagesize 0 verify off echo off
select count(*) from v$datafile where name like '/u02/%';
exit
SQL
)"
if [[ "${DATAFILE_COUNT//[[:space:]]/}" == "0" ]]; then
    log "Oracle data files were not created on the managed data disk."
    exit 1
fi

rm -f "$ORACLE_RPM"
unset ORACLE_PASSWORD SCHEMA_PASSWORD MIRROR_PASSWORD
mkdir -p "$STATE_DIRECTORY"
touch "$CONFIGURED_MARKER"
log "Oracle to Fabric Demo database is ready"
