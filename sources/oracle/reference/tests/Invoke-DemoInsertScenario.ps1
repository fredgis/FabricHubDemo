[CmdletBinding()]
param(
    [string]$StatePath = "$env:LOCALAPPDATA\MSFlixOracle\state.json",
    [int]$TimeoutSeconds = 900
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $repoRoot 'scripts\Demo.Common.ps1')

if (-not (Test-Path -LiteralPath $StatePath)) {
    throw "Deployment state not found: $StatePath"
}
Assert-DemoCommand `
    -Name az `
    -Remediation 'winget install --id Microsoft.AzureCLI --exact --accept-source-agreements --accept-package-agreements'
Assert-DemoCommand `
    -Name sqlcmd `
    -Remediation "$(Get-DemoSqlCmdInstallCommand)`nOpen a new PowerShell session, then run: sqlcmd --version"

$state = Get-Content -Raw $StatePath | ConvertFrom-Json
$salesKey = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$insertScript = Join-Path $repoRoot 'oracle\Insert-DemoSale.sh'

$oracleResult = az vm run-command invoke `
    --subscription $state.subscriptionId `
    --resource-group $state.resourceGroupName `
    --name $state.oracleVmName `
    --command-id RunShellScript `
    --scripts "@$insertScript" `
    --parameters "$salesKey" `
    --query 'value[0].message' `
    --output tsv
$oracleExitCode = $LASTEXITCODE
$oracleText = $oracleResult -join "`n"
if ($oracleExitCode -ne 0 -or $oracleText -notmatch 'ORACLE_INSERTED=1') {
    throw "Oracle insert failed: $oracleText"
}

Write-Output 'ORACLE_INSERTED=true'
Write-Output "SALES_KEY=$salesKey"
Write-Output 'WAITING_FOR_FABRIC=true'

$fabricToken = (az account get-access-token `
    --subscription $state.subscriptionId `
    --resource 'https://api.fabric.microsoft.com' `
    --output json | ConvertFrom-Json).accessToken
$lakehouse = Invoke-RestMethod `
    -Headers @{ Authorization = "Bearer $fabricToken" } `
    -Uri "https://api.fabric.microsoft.com/v1/workspaces/$($state.fabric.workspaceId)/lakehouses/$($state.fabric.lakehouseId)"

$query = @"
SET NOCOUNT ON;
SELECT COUNT_BIG(*)
FROM DEMO_DW.FACT_SALES
WHERE SALES_KEY = $salesKey;
"@

$deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
do {
    $output = & sqlcmd `
        -S $lakehouse.properties.sqlEndpointProperties.connectionString `
        -d $lakehouse.displayName `
        -G `
        -Q $query `
        -h -1 `
        -W 2>$null
    if ($LASTEXITCODE -eq 0) {
        $count = $output |
            Where-Object { $_ -match '^\s*\d+\s*$' } |
            Select-Object -First 1
        if ($count -and [int64]$count.Trim() -eq 1) {
            Write-Output 'FABRIC_REPLICATED=true'
            Write-Output 'FABRIC_TABLE=DEMO_DW.FACT_SALES'
            exit 0
        }
    }
    Start-Sleep -Seconds 10
} while ([DateTimeOffset]::UtcNow -lt $deadline)

throw "The row $salesKey was inserted in Oracle but did not reach Fabric within $TimeoutSeconds seconds."
