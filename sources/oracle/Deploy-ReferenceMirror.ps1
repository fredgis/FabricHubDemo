[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SubscriptionId,
    [Parameter(Mandatory)][string]$TenantId,
    [string]$ResourceGroupName='rg-msflix-demo-sea'
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Oracle-TargetPolicy.ps1')
$targetPolicy = Read-OracleTargetPolicy
if ($SubscriptionId -ne $targetPolicy.subscriptionId -or
    $TenantId -ne $targetPolicy.tenantId -or
    $ResourceGroupName -ne 'rg-msflix-demo-sea') {
    throw 'Refusing Oracle reference deployment outside the approved MSFlix environment.'
}
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$expectedCount = @(Get-Content -Raw -LiteralPath (Join-Path $root 'data\catalog.json') | ConvertFrom-Json).Count
$output = & "$PSScriptRoot\Load-CatalogBatches.ps1" `
    -SubscriptionId $SubscriptionId -ResourceGroupName $ResourceGroupName
if (-not $? -or ($output -join "`n") -notmatch "MSFLIX_CONTENT_COUNT=$expectedCount\b" -or
    ($output -join "`n") -notmatch "MSFLIX_PRICE_RULE_COUNT=$($expectedCount * 8)\b") {
    throw "Oracle reference migration did not produce the expected source catalog: $output"
}
$output
& "$PSScriptRoot\Register-Gateway.ps1" -SubscriptionId $SubscriptionId -TenantId $TenantId -ResourceGroupName $ResourceGroupName
& "$PSScriptRoot\reference\fabric\Configure-DemoFabric.ps1" -SubscriptionId $SubscriptionId `
    -WorkspaceName MSFlix -LakehouseName MSFlixRaw -MirrorName MSFlix_OracleMirror
