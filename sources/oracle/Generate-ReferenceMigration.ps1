[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$catalog = Get-Content -Raw -LiteralPath (Join-Path $root 'data\catalog.json') | ConvertFrom-Json
$directory = Join-Path $PSScriptRoot 'migrations'
New-Item -ItemType Directory -Path $directory -Force | Out-Null
. (Join-Path $PSScriptRoot 'Oracle-Literals.ps1')
function Sql-Literal([string]$Value) {
    return ConvertTo-OracleTextLiteral $Value
}
$sql = [Collections.Generic.List[string]]::new()
$sql.Add(@'
whenever oserror exit failure rollback
whenever sqlerror exit failure rollback
set define off
set serveroutput on
alter session set container = FREEPDB1;
alter session set current_schema = DEMO_DW;
declare
  procedure create_if_absent(p_name varchar2,p_ddl varchar2) is n number;
  begin
    select count(*) into n from all_tables where owner='DEMO_DW' and table_name=p_name;
    if n=0 then execute immediate p_ddl; end if;
  end;
begin
  create_if_absent('REF_CONTENT',q'[create table DEMO_DW.REF_CONTENT (
    CONTENT_ID number(10) primary key, CONTENT_KEY varchar2(80 char) not null unique,
    TITLE varchar2(200 char) not null, CONTENT_TYPE varchar2(20 char) not null,
    DURATION_SECONDS number(10) not null, RELEASE_DATE date not null,
    GENRE varchar2(80 char) not null, IMAGE_URL varchar2(1000 char) not null,
    SOURCE_URL varchar2(1000 char) not null, LICENSE varchar2(80 char) not null,
    ATTRIBUTION varchar2(1000 char) not null, IS_ACTIVE number(1) default 1 not null,
    UPDATED_AT timestamp default systimestamp not null)]');
  create_if_absent('REF_OFFER',q'[create table DEMO_DW.REF_OFFER (
    OFFER_ID number(10) primary key, OFFER_KEY varchar2(40 char) not null unique,
    OFFER_TYPE varchar2(20 char) not null, START_WINDOW_HOURS number(10),
    PLAY_WINDOW_HOURS number(10), UPDATED_AT timestamp default systimestamp not null)]');
  create_if_absent('REF_DISTRIBUTOR',q'[create table DEMO_DW.REF_DISTRIBUTOR (
    DISTRIBUTOR_ID number(10) primary key, DISTRIBUTOR_KEY varchar2(80 char) not null unique,
    DISTRIBUTOR_NAME varchar2(200 char) not null, SOURCE_URL varchar2(1000 char) not null,
    SAP_PARTNER_CODE varchar2(80 char), UPDATED_AT timestamp default systimestamp not null)]');
  create_if_absent('REF_TERRITORY',q'[create table DEMO_DW.REF_TERRITORY (
    TERRITORY_ID number(10) primary key, TERRITORY_CODE varchar2(2 char) not null unique,
    TERRITORY_NAME varchar2(80 char) not null, CURRENCY_CODE varchar2(3 char) not null)]');
  create_if_absent('REF_PRICE_RULE',q'[create table DEMO_DW.REF_PRICE_RULE (
    PRICE_RULE_ID number(10) primary key, PRICE_RULE_KEY varchar2(150 char) not null unique,
    CONTENT_ID number(10) not null references DEMO_DW.REF_CONTENT(CONTENT_ID),
    OFFER_ID number(10) not null references DEMO_DW.REF_OFFER(OFFER_ID),
    DISTRIBUTOR_ID number(10) references DEMO_DW.REF_DISTRIBUTOR(DISTRIBUTOR_ID),
    TERRITORY_ID number(10) not null references DEMO_DW.REF_TERRITORY(TERRITORY_ID),
    CURRENCY_CODE varchar2(3 char) not null, AMOUNT_MINOR number(18) not null,
    VALID_FROM date not null, VALID_TO date not null,
    constraint CK_MSF_PRICE_PERIOD check (VALID_TO>VALID_FROM),
    UPDATED_AT timestamp default systimestamp not null)]');
end;
/
declare n number;
begin
  select count(*) into n from all_tab_columns where owner='DEMO_DW'
    and table_name='REF_PRICE_RULE' and column_name='DISTRIBUTOR_ID' and nullable='N';
  if n=1 then execute immediate 'alter table DEMO_DW.REF_PRICE_RULE modify (DISTRIBUTOR_ID null)'; end if;
end;
/
declare n number;
begin
  for t in (select table_name from all_tables where owner='DEMO_DW'
    and table_name in ('REF_CONTENT','REF_OFFER','REF_DISTRIBUTOR','REF_TERRITORY','REF_PRICE_RULE')) loop
    select count(*) into n from all_log_groups where owner='DEMO_DW'
      and table_name=t.table_name and log_group_type='ALL COLUMN LOGGING';
    if n=0 then execute immediate 'alter table DEMO_DW.'||t.table_name||' add supplemental log data (all) columns'; end if;
  end loop;
end;
/
merge into DEMO_DW.REF_DISTRIBUTOR t using (select 972001 id from dual) s
on (t.DISTRIBUTOR_ID=s.id) when not matched then insert
(DISTRIBUTOR_ID,DISTRIBUTOR_KEY,DISTRIBUTOR_NAME,SOURCE_URL)
values (972001,'BLENDER-FOUNDATION','Blender Foundation','https://www.blender.org/about/foundation/');
merge into DEMO_DW.REF_OFFER t using (select 971001 id from dual) s
on (t.OFFER_ID=s.id) when not matched then insert
(OFFER_ID,OFFER_KEY,OFFER_TYPE,START_WINDOW_HOURS,PLAY_WINDOW_HOURS)
values (971001,'RENTAL','RENTAL',720,48);
merge into DEMO_DW.REF_OFFER t using (select 971002 id from dual) s
on (t.OFFER_ID=s.id) when not matched then insert
(OFFER_ID,OFFER_KEY,OFFER_TYPE) values (971002,'PURCHASE','PURCHASE');
'@)
$territories = @(
    @{id=973001;code='FR';name='France';currency='EUR'},
    @{id=973002;code='BE';name='Belgium';currency='EUR'},
    @{id=973003;code='CA';name='Canada';currency='CAD'},
    @{id=973004;code='CH';name='Switzerland';currency='CHF'}
)
foreach ($territory in $territories) {
    $sql.Add("merge into DEMO_DW.REF_TERRITORY t using (select $($territory.id) id from dual) s on(t.TERRITORY_ID=s.id) when not matched then insert(TERRITORY_ID,TERRITORY_CODE,TERRITORY_NAME,CURRENCY_CODE) values($($territory.id),'$($territory.code)','$($territory.name)','$($territory.currency)');")
}
$index = 0
$priceIndex = 0
foreach ($film in $catalog) {
    $index++
    $id = 970000 + $index
    $key = Sql-Literal $film.content_key
    $title = Sql-Literal $film.title
    $genre = Sql-Literal $film.genre
    $image = Sql-Literal $film.image_url
    $source = Sql-Literal $film.source_url
    $license = Sql-Literal $film.license
    $attribution = Sql-Literal $film.attribution
    $distributorId = if ($film.distributor_key -eq 'BLENDER-FOUNDATION') { '972001' } else { 'NULL' }
    $sql.Add("merge into DEMO_DW.REF_CONTENT t using(select $id id from dual) s on(t.CONTENT_ID=s.id) when not matched then insert(CONTENT_ID,CONTENT_KEY,TITLE,CONTENT_TYPE,DURATION_SECONDS,RELEASE_DATE,GENRE,IMAGE_URL,SOURCE_URL,LICENSE,ATTRIBUTION) values($id,$key,$title,'MOVIE',$($film.duration_seconds),date '$($film.release_date)',$genre,$image,$source,$license,$attribution);")
    foreach ($territory in $territories) {
        foreach ($offer in @(@{id=971001;kind='RENTAL';price=399},@{id=971002;kind='PURCHASE';price=1299})) {
            $priceIndex++
            $priceId = 974000 + $priceIndex
            $priceKey = Sql-Literal "$($film.content_key):$($territory.code):$($offer.kind)"
            $amount = $offer.price
            if ($territory.currency -eq 'CAD') { $amount = if ($offer.kind -eq 'RENTAL') { 599 } else { 1899 } }
            if ($territory.currency -eq 'CHF') { $amount = if ($offer.kind -eq 'RENTAL') { 449 } else { 1399 } }
            $sql.Add("merge into DEMO_DW.REF_PRICE_RULE t using(select $priceId id from dual) s on(t.PRICE_RULE_ID=s.id) when not matched then insert(PRICE_RULE_ID,PRICE_RULE_KEY,CONTENT_ID,OFFER_ID,DISTRIBUTOR_ID,TERRITORY_ID,CURRENCY_CODE,AMOUNT_MINOR,VALID_FROM,VALID_TO) values($priceId,$priceKey,$id,$($offer.id),$distributorId,$($territory.id),'$($territory.currency)',$amount,date '2026-01-01',date '2028-01-01');")
        }
    }
}
$sql.Add(@'
commit;
select 'MSFLIX_CONTENT_COUNT='||count(*) from DEMO_DW.REF_CONTENT;
select 'MSFLIX_PRICE_RULE_COUNT='||count(*) from DEMO_DW.REF_PRICE_RULE;
alter session set container=CDB$ROOT;
alter system archive log current;
exit success
'@)
$sqlText = ($sql -join "`n").Replace("`r`n","`n")
$sqlPath = Join-Path $directory '001_reference_catalog.sql'
[IO.File]::WriteAllText($sqlPath,$sqlText,[Text.UTF8Encoding]::new($false))
$shell = "#!/usr/bin/env bash`nset -euo pipefail`nsudo demo-sqlplus <<'MSFLIX_SQL'`n$sqlText`nMSFLIX_SQL`n"
[IO.File]::WriteAllText((Join-Path $directory 'install-reference.sh'),$shell,[Text.UTF8Encoding]::new($false))
$batchDirectory = Join-Path $directory 'batches'
New-Item -ItemType Directory -Path $batchDirectory -Force | Out-Null
$batchNumber = 0
$buffer = [Text.StringBuilder]::new()
$prefix = @'
whenever oserror exit failure rollback
whenever sqlerror exit failure rollback
set define off
alter session set container=FREEPDB1;
alter session set current_schema=DEMO_DW;
'@
function Save-Batch {
    param([string]$Body,[int]$Number)
    $script = "#!/usr/bin/env bash`nset -euo pipefail`nsudo demo-sqlplus <<'MSFLIX_BATCH'`n$prefix`n$Body`ncommit;`nexit success`nMSFLIX_BATCH`necho MSFLIX_BATCH_$Number=COMMITTED`n"
    [IO.File]::WriteAllText((Join-Path $batchDirectory ('{0:D3}.sh' -f $Number)),$script,[Text.UTF8Encoding]::new($false))
}
foreach ($statement in $sql) {
    if ($buffer.Length -gt 0 -and ($buffer.Length + $statement.Length) -gt 40000) {
        $batchNumber++
        Save-Batch -Body $buffer.ToString() -Number $batchNumber
        $buffer.Clear() | Out-Null
    }
    $buffer.AppendLine($statement) | Out-Null
}
if ($buffer.Length -gt 0) { $batchNumber++; Save-Batch -Body $buffer.ToString() -Number $batchNumber }
"ORACLE_REFERENCE_BATCHES=$batchNumber"
"ORACLE_REFERENCE_MIGRATION=Generated;CONTENT=$index;PRICE_RULES=$priceIndex"
