param(
    [Parameter(Mandatory)][string]$ApplicationId,
    [Parameter(Mandatory)][string]$TenantId,
    [Parameter(Mandatory)][string]$ClientSecret,
    [string]$RegionKey = 'default',
    [string]$GatewayName = 'MSFlix Oracle Gateway Fabric'
)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) {
    & 'C:\Program Files\PowerShell\7\pwsh.exe' -NoProfile -File $PSCommandPath `
        -ApplicationId $ApplicationId -TenantId $TenantId -ClientSecret $ClientSecret -RegionKey $RegionKey -GatewayName $GatewayName
    exit $LASTEXITCODE
}
Import-Module DataGateway
Import-Module DataGateway.Profile
Connect-DataGatewayServiceAccount -ApplicationId $ApplicationId `
    -ClientSecret (ConvertTo-SecureString $ClientSecret -AsPlainText -Force) -Tenant $TenantId | Out-Null
try {
    $regions = @(Get-DataGatewayRegion)
    if ($RegionKey -eq 'default') {
        $defaults = @($regions | Where-Object IsDefaultPowerBIRegion -eq $true)
        if ($defaults.Count -ne 1) { throw 'Cannot resolve a unique tenant gateway registration region.' }
        $RegionKey = $defaults[0].RegionKey
    }
    $clusters = @(Get-DataGatewayCluster -RegionKey $RegionKey | Where-Object Name -eq $GatewayName)
    [pscustomobject]@{
        regionKey = $RegionKey
        clusters = @($clusters | ForEach-Object {
            @{
                id = $_.Id
                name = $_.Name
                propertyNames = @($_.PSObject.Properties.Name)
                members = @($_.MemberGateways | Select-Object Id,Name,GatewayId,Status,Version,MachineName)
                permissions = @($_.Permissions | Select-Object Id,PrincipalType,PrincipalObjectId,Role)
            }
        })
    } | ConvertTo-Json -Depth 5 -Compress
    [pscustomobject]@{
        regionProperties = @($regions[0].PSObject.Properties.Name)
        selectedRegion = @($regions | Where-Object RegionKey -eq $RegionKey)
    } | ConvertTo-Json -Depth 3 -Compress
    Get-Service PBIEgwService | Select-Object Name,Status | ConvertTo-Json
} finally {
    Disconnect-DataGatewayServiceAccount
}
