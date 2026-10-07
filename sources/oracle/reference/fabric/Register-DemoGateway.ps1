param(
    [Parameter(Mandatory)]
    [string]$ApplicationId,

    [Parameter(Mandatory)]
    [string]$TenantId,

    [Parameter(Mandatory)]
    [string]$ClientSecret,

    [Parameter(Mandatory)]
    [string]$RecoveryKey,

    [string]$GatewayName = 'MSFlix Oracle Gateway Fabric',
    [string]$RegionKey = 'default',
    [ValidateSet('true', 'false')]
    [string]$OverwriteExistingGateway = 'false',
    [Parameter(Mandatory)]
    [string]$ExpectedSubscriptionId,
    [string]$ExpectedResourceGroupName = 'rg-msflix-demo-sea',
    [string]$ExpectedVmName = 'msflix-fabric-gateway-vm'
)

$ErrorActionPreference = 'Stop'

if ($PSVersionTable.PSVersion.Major -lt 7) {
    & 'C:\Program Files\PowerShell\7\pwsh.exe' `
        -NoLogo `
        -NoProfile `
        -File $PSCommandPath `
        -ApplicationId $ApplicationId `
        -TenantId $TenantId `
        -ClientSecret $ClientSecret `
        -RecoveryKey $RecoveryKey `
        -GatewayName $GatewayName `
        -RegionKey $RegionKey `
        -OverwriteExistingGateway $OverwriteExistingGateway `
        -ExpectedSubscriptionId $ExpectedSubscriptionId `
        -ExpectedResourceGroupName $ExpectedResourceGroupName `
        -ExpectedVmName $ExpectedVmName
    exit $LASTEXITCODE
}

Import-Module DataGateway
Import-Module DataGateway.Profile

$machine = Invoke-RestMethod `
    -Uri 'http://169.254.169.254/metadata/instance/compute?api-version=2021-02-01' `
    -Headers @{ Metadata = 'true' } -TimeoutSec 10
if ($machine.subscriptionId -ne $ExpectedSubscriptionId -or
    $machine.resourceGroupName -ne $ExpectedResourceGroupName -or
    $machine.name -ne $ExpectedVmName -or
    $ExpectedVmName -ne 'msflix-fabric-gateway-vm' -or
    $GatewayName -ne 'MSFlix Oracle Gateway Fabric') {
    throw 'Refusing to change gateway configuration outside the dedicated MSFlix VM and gateway.'
}

$secureClientSecret = ConvertTo-SecureString $ClientSecret -AsPlainText -Force
$secureRecoveryKey = ConvertTo-SecureString $RecoveryKey -AsPlainText -Force

Connect-DataGatewayServiceAccount `
    -ApplicationId $ApplicationId `
    -ClientSecret $secureClientSecret `
    -Tenant $TenantId | Out-Null

try {
    if ($RegionKey -eq 'default') {
        $defaultRegion = @(Get-DataGatewayRegion | Where-Object IsDefaultPowerBIRegion -eq $true)
        if ($defaultRegion.Count -ne 1 -or -not $defaultRegion[0].RegionKey) {
            throw 'The tenant default gateway registration region could not be resolved uniquely.'
        }
        $RegionKey = $defaultRegion[0].RegionKey
    }
    $existing = @(Get-DataGatewayCluster -RegionKey $RegionKey) |
        Where-Object {
            $_.GatewayName -eq $GatewayName -or
            $_.Name -eq $GatewayName -or
            $_.DisplayName -eq $GatewayName
        } |
        Select-Object -First 1

    if (-not $existing) {
        $registration = @{
            GatewayName = $GatewayName
            RecoveryKey = $secureRecoveryKey
            RegionKey = $RegionKey
        }
        if ($OverwriteExistingGateway -eq 'true') {
            $registration.OverwriteExistingGateway = $true
        }
        Add-DataGatewayCluster @registration | Out-Null
    }

    $verified = @(Get-DataGatewayCluster -RegionKey $RegionKey |
        Where-Object {
            $_.GatewayName -eq $GatewayName -or
            $_.Name -eq $GatewayName -or
            $_.DisplayName -eq $GatewayName
        })
    if ($verified.Count -ne 1 -or -not $verified[0].Id) {
        throw 'Gateway registration was not confirmed in the requested region; no registration success claimed.'
    }
    $evidence = [pscustomobject]@{
        gatewayName = $GatewayName
        gatewayId = $verified[0].Id
        regionKey = $RegionKey
        registered = $true
    }
    Write-Output ('MSFLIX_GATEWAY_JSON=' + ($evidence | ConvertTo-Json -Compress))
}
finally {
    Disconnect-DataGatewayServiceAccount
}
