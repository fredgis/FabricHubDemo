[CmdletBinding()]
param(
    [string]$StatePath = "$env:LOCALAPPDATA\MSFlixOracle\state.json"
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path -LiteralPath $StatePath)) {
    throw "Deployment state not found: $StatePath"
}

$state = Get-Content -Raw $StatePath | ConvertFrom-Json
$result = az vm run-command invoke `
    --subscription $state.subscriptionId `
    --resource-group $state.resourceGroupName `
    --name $state.oracleVmName `
    --command-id RunShellScript `
    --scripts "@$(Join-Path $repoRoot 'oracle\Run-DemoSqlFunTest.sh')" `
    --query 'value[0].message' `
    --output tsv
$exitCode = $LASTEXITCODE
$text = $result -join "`n"

if ($exitCode -ne 0 -or $text -notmatch 'SQL_FUN_VALID=true') {
    throw "Oracle SQL rendering smoke test failed: $text"
}

$stdout = [regex]::Match(
    $text,
    '(?s)\[stdout\]\s*(?<value>.*?)(?:\s*\[stderr\]|\z)'
).Groups['value'].Value.Trim()

Write-Output $stdout
