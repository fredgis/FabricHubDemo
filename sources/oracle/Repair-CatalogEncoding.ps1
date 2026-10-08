[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SubscriptionId,
    [string[]]$ReplayContentKeys = @()
)
$ErrorActionPreference = 'Stop'
if ($SubscriptionId -ne '00000000-0000-4000-8000-000000100086') {
    throw 'Refusing to repair catalog data outside the approved MSFlix subscription.'
}
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $PSScriptRoot 'Oracle-Literals.ps1')
$catalog = Get-Content -Raw -Encoding utf8 (Join-Path $root 'data\catalog.json') | ConvertFrom-Json
$directory = Join-Path $root '.state\oracle-encoding'
[void](New-Item -ItemType Directory -Path $directory -Force)
$batches = [Collections.Generic.List[string]]::new()
$buffer = [Text.StringBuilder]::new()
foreach ($film in $catalog) {
    if ($ReplayContentKeys.Count -and $film.content_key -notin $ReplayContentKeys) { continue }
    $key = ConvertTo-OracleTextLiteral $film.content_key
    $title = ConvertTo-OracleTextLiteral $film.title
    $genre = ConvertTo-OracleTextLiteral $film.genre
    $attribution = ConvertTo-OracleTextLiteral $film.attribution
    $filter = if ($ReplayContentKeys.Count) { '' } else {
        " AND (INSTR(TITLE,UNISTR('\FFFD'))>0 OR INSTR(GENRE,UNISTR('\FFFD'))>0 OR INSTR(ATTRIBUTION,UNISTR('\FFFD'))>0)"
    }
    $statement = "UPDATE DEMO_DW.REF_CONTENT SET TITLE=$title,GENRE=$genre,ATTRIBUTION=$attribution,UPDATED_AT=SYSTIMESTAMP WHERE CONTENT_KEY=$key$filter;"
    if ($buffer.Length + $statement.Length -gt 30000) {
        $batches.Add($buffer.ToString())
        [void]$buffer.Clear()
    }
    [void]$buffer.AppendLine($statement)
}
if ($buffer.Length) { $batches.Add($buffer.ToString()) }
for ($index = 0; $index -lt $batches.Count; $index++) {
    $script = @"
#!/usr/bin/env bash
set -euo pipefail
sudo demo-sqlplus <<'MSFLIX_ENCODING'
whenever oserror exit failure rollback
whenever sqlerror exit failure rollback
set define off
alter session set container=FREEPDB1;
$($batches[$index])
commit;
alter session set container=CDB`$ROOT;
alter system archive log current;
exit success
MSFLIX_ENCODING
echo MSFLIX_ENCODING_BATCH_$index=COMMITTED
"@
    $path = Join-Path $directory "batch-$index.sh"
    [IO.File]::WriteAllText($path, $script.Replace("`r`n", "`n"), [Text.UTF8Encoding]::new($false))
    try {
        $output = az vm run-command invoke --subscription $SubscriptionId --resource-group rg-msflix-demo-sea `
            --name msflix-oracle-vm --command-id RunShellScript --scripts "@$path" `
            --query 'value[0].message' --output tsv --only-show-errors
        if ($LASTEXITCODE -ne 0 -or ($output -join "`n") -notmatch "MSFLIX_ENCODING_BATCH_$index=COMMITTED") {
            throw "Catalog Unicode repair batch $index failed: $output"
        }
        "MSFLIX_ENCODING_BATCH_$index=COMMITTED"
    } finally {
        Remove-Item -LiteralPath $path
    }
}
