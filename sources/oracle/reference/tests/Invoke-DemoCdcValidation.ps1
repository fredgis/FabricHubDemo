[CmdletBinding()]
param(
    [string]$StatePath = "$env:LOCALAPPDATA\MSFlixOracle\state.json"
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
$fabricToken = (az account get-access-token `
    --subscription $state.subscriptionId `
    --resource 'https://api.fabric.microsoft.com' `
    --output json | ConvertFrom-Json).accessToken
$lakehouse = Invoke-RestMethod `
    -Headers @{ Authorization = "Bearer $fabricToken" } `
    -Uri "https://api.fabric.microsoft.com/v1/workspaces/$($state.fabric.workspaceId)/lakehouses/$($state.fabric.lakehouseId)"

$query = @'
SELECT CONCAT(
    (SELECT COUNT_BIG(*) FROM DEMO_DW.FACT_SALES WHERE SALES_KEY = 900000000000002),
    '|',
    (SELECT SEGMENT_NAME FROM DEMO_DW.DIM_CUSTOMER WHERE CUSTOMER_KEY = 2),
    '|',
    (SELECT COUNT_BIG(*) FROM DEMO_DW.FACT_SALES WHERE SALES_KEY = 24998),
    '|',
    (SELECT COUNT_BIG(*) FROM DEMO_DW.FACT_SALES)
) AS result
'@

function Invoke-OracleCdcScript {
    param([string]$ScriptPath)

    $result = az vm run-command invoke `
        --subscription $state.subscriptionId `
        --resource-group $state.resourceGroupName `
        --name $state.oracleVmName `
        --command-id RunShellScript `
        --scripts "@$ScriptPath" `
        --query 'value[0].message' `
        --output tsv
    $text = $result -join "`n"
    if ($LASTEXITCODE -ne 0 -or $text -notmatch 'FACT_COUNT=25000') {
        throw "Oracle CDC script failed: $text"
    }
}

function Wait-LakehouseResult {
    param([string]$Expected)

    $actual = ''
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $output = & sqlcmd `
            -S $lakehouse.properties.sqlEndpointProperties.connectionString `
            -d $lakehouse.displayName `
            -G `
            -Q $query `
            -h -1 `
            -W 2>&1
        $line = $output | Where-Object { $_ -match '^\d+\|' } | Select-Object -First 1
        if ($line) {
            $actual = $line.Trim()
        }
        if ($actual -eq $Expected) {
            return
        }
        Start-Sleep -Seconds 10
    }
    throw "CDC did not converge. Expected $Expected, actual $actual"
}

Invoke-OracleCdcScript -ScriptPath (Join-Path $repoRoot 'oracle\Reset-DemoCdcTest.sh')
Wait-LakehouseResult -Expected '0|Consumer|1|25000'

Invoke-OracleCdcScript -ScriptPath (Join-Path $repoRoot 'oracle\Run-DemoLiveCdcTest.sh')
Wait-LakehouseResult -Expected '1|CDC_LIVE|0|25000'

Write-Output 'CDC_VALID=true'
Write-Output 'CDC_BASELINE=0|Consumer|1|25000'
Write-Output 'CDC_RESULT=1|CDC_LIVE|0|25000'
