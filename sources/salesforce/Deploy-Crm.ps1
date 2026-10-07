[CmdletBinding()]
param([string]$Alias='MSFlix')
$ErrorActionPreference = 'Stop'
$env:SF_DISABLE_TELEMETRY = 'true'
$env:SF_AUTOUPDATE_DISABLE = 'true'
$sf = Join-Path $env:APPDATA 'npm\sf.cmd'
if (-not (Test-Path -LiteralPath $sf)) { throw 'Salesforce CLI is missing.' }
Set-Location -LiteralPath $PSScriptRoot
& "$PSScriptRoot\Generate-Schema.ps1"
$raw = & $sf project deploy start --source-dir force-app --target-org $Alias --wait 15 --json
$exit = $LASTEXITCODE
if (-not $raw) { throw "Salesforce metadata deployment returned no result (exit $exit)." }
$result = $raw | ConvertFrom-Json
if ($exit -ne 0 -or $result.status -ne 0 -or $result.result.status -ne 'Succeeded') {
    $details = $result.result.details.componentFailures | ConvertTo-Json -Depth 5 -Compress
    throw "Salesforce metadata deployment failed: $($result.message) $details"
}
$assigned = & $sf org assign permset --name MSFlix_Integration --target-org $Alias --json
if ($LASTEXITCODE -ne 0) { throw "Salesforce permission assignment failed: $assigned" }
"SALESFORCE_METADATA_STATUS=$($result.result.status)"
