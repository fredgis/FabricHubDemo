[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SubscriptionId,
    [Parameter(Mandatory)][string]$TenantId,
    [string]$ResourceGroupName='rg-msflix-demo-sea',
    [ValidateSet('true', 'false')][string]$ReplaceDedicatedVmRegistration='false'
)
$ErrorActionPreference = 'Stop'
$statePath = Join-Path $env:LOCALAPPDATA 'MSFlixOracle\state.json'
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if ($state.tenantId -ne $TenantId -or $state.subscriptionId -ne $SubscriptionId) { throw 'Gateway state is not the approved environment.' }
if ($state.gatewayVmName -ne 'msflix-fabric-gateway-vm' -or
    $ResourceGroupName -ne 'rg-msflix-demo-sea' -or
    $SubscriptionId -ne 'ce9dbfdd-c341-4e8d-a1fa-51617c74c3eb' -or
    $TenantId -ne '1e45d0cb-b0dd-408c-8806-58b447605e96') {
    throw 'Refusing gateway registration outside the explicitly approved dedicated MSFlix VM.'
}
if (-not $state.gatewayIdentity.appId) { throw 'Dedicated gateway identity not initialized.' }
function Unprotect([string]$Value) { [Net.NetworkCredential]::new('',(ConvertTo-SecureString $Value)).Password }
$secret = Unprotect $state.gatewayIdentity.protectedClientSecret
$recovery = Unprotect $state.protected.gatewayRecoveryKey
$commandName = 'msflix-register-gateway-' + [guid]::NewGuid().ToString('N').Substring(0,12)
$script = Join-Path $PSScriptRoot 'reference\fabric\Register-DemoGateway.ps1'
try {
    az vm run-command create --subscription $SubscriptionId --resource-group $ResourceGroupName `
        --vm-name $state.gatewayVmName --run-command-name $commandName --location southeastasia `
        --script "@$script" --protected-parameters "ClientSecret=$secret" "RecoveryKey=$recovery" `
        --parameters "ApplicationId=$($state.gatewayIdentity.appId)" "TenantId=$TenantId" `
            'GatewayName=MSFlix Oracle Gateway Fabric' 'RegionKey=default' `
            "OverwriteExistingGateway=$ReplaceDedicatedVmRegistration" `
            "ExpectedSubscriptionId=$SubscriptionId" "ExpectedResourceGroupName=$ResourceGroupName" `
            "ExpectedVmName=$($state.gatewayVmName)" `
        --timeout-in-seconds 600 --async-execution false --output none --only-show-errors
    if ($LASTEXITCODE -ne 0) { throw 'Private gateway registration command failed.' }
    $result = az vm run-command show --subscription $SubscriptionId --resource-group $ResourceGroupName `
        --vm-name $state.gatewayVmName --run-command-name $commandName --expand instanceView `
        --query instanceView --output json --only-show-errors | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $result.exitCode -ne 0) {
        throw "Gateway guest registration failed: $($result.error) $($result.output)"
    }
    $records = @($result.output -split '\r?\n' | Where-Object { $_.StartsWith('MSFLIX_GATEWAY_JSON=') })
    if ($records.Count -ne 1) { throw 'Gateway guest did not return exactly one verified registration record.' }
    $registration = $records[0].Substring('MSFLIX_GATEWAY_JSON='.Length) | ConvertFrom-Json
    if (-not $registration.registered -or
        $registration.gatewayName -ne 'MSFlix Oracle Gateway Fabric' -or
        $registration.gatewayId -eq 'c7d59606-b2ad-4653-98e2-a3e858075e37') {
        throw 'Refusing an unverified or unrelated gateway registration.'
    }
    [guid]::Parse($registration.gatewayId) | Out-Null
    if (-not $state.fabric) { $state | Add-Member -NotePropertyName fabric -NotePropertyValue ([pscustomobject]@{}) }
    $state.fabric | Add-Member -NotePropertyName gatewayId -NotePropertyValue $registration.gatewayId -Force
    $state.fabric | Add-Member -NotePropertyName gatewayName -NotePropertyValue $registration.gatewayName -Force
    $state.fabric | Add-Member -NotePropertyName gatewayRegistrationRegion -NotePropertyValue $registration.regionKey -Force
    $state | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $statePath -Encoding utf8NoBOM
    $registration | ConvertTo-Json -Compress
} finally {
    $secret = $null
    $recovery = $null
    az vm run-command delete --subscription $SubscriptionId --resource-group $ResourceGroupName `
        --vm-name $state.gatewayVmName --run-command-name $commandName --yes --output none --only-show-errors
    if ($LASTEXITCODE -ne 0) { throw 'Could not remove the protected gateway command.' }
}
