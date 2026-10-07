[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$SubscriptionId,

    [Parameter(Mandatory)]
    [string]$TenantId,

    [string]$WorkspaceName = 'MSFlix',
    [string]$StatePath = "$env:LOCALAPPDATA\MSFlixOracle\state.json"
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Demo.Common.ps1')

Assert-DemoCommand `
    -Name az `
    -Remediation 'winget install --id Microsoft.AzureCLI --exact --accept-source-agreements --accept-package-agreements'
Assert-DemoCommand `
    -Name ssh-keygen `
    -Remediation 'Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0'
Assert-DemoCommand `
    -Name sqlcmd `
    -Remediation (Get-DemoSqlCmdInstallCommand)

$null = Invoke-DemoNativeCommand `
    -Description 'Azure CLI' `
    -Command { az version --output json }
$null = Invoke-DemoNativeCommand `
    -Description 'sqlcmd' `
    -Command { sqlcmd --version }

try {
    $null = Invoke-DemoNativeCommand `
        -Description 'Azure Bicep' `
        -Command { az bicep version }
}
catch {
    throw "Azure Bicep is required.`nRun:`naz bicep install`naz bicep version"
}

$accountJson = (Invoke-DemoNativeCommand `
    -Description 'Azure account lookup' `
    -Command { az account show --subscription $SubscriptionId --output json }) -join "`n"
$account = $accountJson | ConvertFrom-Json
if ($account.tenantId -ne $TenantId) {
    throw "Subscription $SubscriptionId belongs to tenant $($account.tenantId), not $TenantId."
}

$featureState = ((Invoke-DemoNativeCommand `
    -Description 'Azure subscription feature lookup' `
    -Command {
        az feature show `
            --namespace Microsoft.Network `
            --name AllowBringYourOwnPublicIpAddress `
            --subscription $SubscriptionId `
            --query properties.state `
            --output tsv
    }) -join "`n").Trim()
if ($featureState -ne 'Registered') {
    throw @"
Azure feature Microsoft.Network/AllowBringYourOwnPublicIpAddress is $featureState.
Run:
az feature register --namespace Microsoft.Network --name AllowBringYourOwnPublicIpAddress --subscription `$env:AZURE_SUBSCRIPTION_ID
az feature show --namespace Microsoft.Network --name AllowBringYourOwnPublicIpAddress --subscription `$env:AZURE_SUBSCRIPTION_ID --query properties.state --output tsv
az provider register --namespace Microsoft.Network --subscription `$env:AZURE_SUBSCRIPTION_ID
"@
}

$networkProviderState = ((Invoke-DemoNativeCommand `
    -Description 'Microsoft.Network provider lookup' `
    -Command {
        az provider show `
            --namespace Microsoft.Network `
            --subscription $SubscriptionId `
            --query registrationState `
            --output tsv
    }) -join "`n").Trim()
if ($networkProviderState -ne 'Registered') {
    throw @"
Azure provider Microsoft.Network is $networkProviderState.
Run:
az provider register --namespace Microsoft.Network --subscription `$env:AZURE_SUBSCRIPTION_ID
"@
}

$reauthentication = @"
Refresh Azure CLI after PIM activation:
az logout
az login --tenant `$env:AZURE_TENANT_ID --use-device-code
az account set --subscription `$env:AZURE_SUBSCRIPTION_ID
"@

try {
    $graphTokenJson = (Invoke-DemoNativeCommand `
        -Description 'Microsoft Graph token acquisition' `
        -Command {
            az account get-access-token `
                --subscription $SubscriptionId `
                --resource 'https://graph.microsoft.com/' `
                --output json
        }) -join "`n"
}
catch {
    throw "Microsoft Graph authentication failed.`n$reauthentication"
}
$graphToken = ($graphTokenJson | ConvertFrom-Json).accessToken
$graphClaims = Get-DemoJwtClaims -AccessToken $graphToken
if ($graphClaims.idtyp -and $graphClaims.idtyp -ne 'user') {
    throw "Deployment requires an interactive user identity for Microsoft Graph.`n$reauthentication"
}
$currentDeploymentUser = Invoke-RestMethod `
    -Headers @{ Authorization = "Bearer $graphToken" } `
    -Uri 'https://graph.microsoft.com/v1.0/me?$select=id'
$state = if (Test-Path -LiteralPath $StatePath) {
    Get-Content -Raw $StatePath | ConvertFrom-Json
}
else {
    $null
}
if ($state.deploymentUserId) {
    Resolve-DemoDeploymentUserId `
        -RecordedUserId $state.deploymentUserId `
        -CurrentUserId $currentDeploymentUser.id | Out-Null
}

$requiredPowerBiRoleIds = @(
    '654b31ae-d941-4e22-8798-7add8fdf049f',
    '28379fa9-8596-4fd9-869e-cb60a93b5d84'
)
$directoryWriteRequired = $true
if ($state) {
    $identity = $state.gatewayIdentity
    if (
        $identity.servicePrincipalId -and
        $identity.protectedClientSecret -and
        [datetime]$identity.secretExpires -gt (Get-Date).ToUniversalTime().AddDays(7)
    ) {
        $assignmentResponse = Invoke-WebRequest `
            -Headers @{ Authorization = "Bearer $graphToken" } `
            -Uri "https://graph.microsoft.com/v1.0/servicePrincipals/$($identity.servicePrincipalId)/appRoleAssignments" `
            -SkipHttpErrorCheck
        if ($assignmentResponse.StatusCode -eq 200) {
            $assignments = ($assignmentResponse.Content | ConvertFrom-Json).value
            $missingAssignments = @(
                $requiredPowerBiRoleIds |
                    Where-Object { $_ -notin @($assignments.appRoleId) }
            )
            $directoryWriteRequired = $missingAssignments.Count -gt 0
        }
    }
}

$directoryRoleIds = @{
    '62e90394-69f5-4237-9190-012177145e10' = 'Global Administrator'
    '9b895d92-2cd3-44c7-9d02-a6ac2d5ea5c3' = 'Application Administrator'
    '158c047a-c907-4556-b7ef-446551a6b5f7' = 'Cloud Application Administrator'
}
$activeDirectoryRoles = @(
    @($graphClaims.wids) |
        Where-Object { $directoryRoleIds.ContainsKey($_) } |
        ForEach-Object { $directoryRoleIds[$_] }
)
if ($directoryWriteRequired -and $activeDirectoryRoles.Count -eq 0) {
    throw @"
Microsoft Entra directory write access is required.
Activate Cloud Application Administrator or Application Administrator in PIM.
$reauthentication
"@
}

try {
    $fabricTokenJson = (Invoke-DemoNativeCommand `
        -Description 'Fabric token acquisition' `
        -Command {
            az account get-access-token `
                --subscription $SubscriptionId `
                --resource 'https://api.fabric.microsoft.com' `
                --output json
        }) -join "`n"
}
catch {
    throw "Fabric authentication failed.`n$reauthentication"
}
$fabricToken = ($fabricTokenJson | ConvertFrom-Json).accessToken
$fabricHeaders = @{ Authorization = "Bearer $fabricToken" }
$tenantSettingsResponse = Invoke-WebRequest `
    -Headers $fabricHeaders `
    -Uri 'https://api.fabric.microsoft.com/v1/admin/tenantsettings' `
    -SkipHttpErrorCheck
if ($tenantSettingsResponse.StatusCode -ne 200) {
    throw @"
Fabric tenant settings could not be read. Fabric Administrator or Power BI Administrator is required.
Open: https://app.fabric.microsoft.com/admin-portal/tenantSettings
$reauthentication
"@
}
$tenantSettings = ($tenantSettingsResponse.Content | ConvertFrom-Json).value
$requiredSettings = @(
    'Service principals can call Fabric public APIs',
    'Service principals can create workspaces, connections, and deployment pipelines'
)
foreach ($title in $requiredSettings) {
    $setting = $tenantSettings | Where-Object title -eq $title | Select-Object -First 1
    if (-not $setting -or -not $setting.enabled) {
        throw @"
Required Fabric tenant setting is disabled: $title
Enable it at https://app.fabric.microsoft.com/admin-portal/tenantSettings.
For initial bootstrap, enable it for the organization or a group that already contains the automation service principal.
"@
    }
}

$workspaceResponse = Invoke-RestMethod `
    -Headers $fabricHeaders `
    -Uri 'https://api.fabric.microsoft.com/v1/workspaces'
$workspaces = @($workspaceResponse.value | Where-Object displayName -eq $WorkspaceName)
if ($workspaces.Count -ne 1) {
    throw "Expected one Fabric workspace named $WorkspaceName, found $($workspaces.Count)."
}
$workspace = Invoke-RestMethod `
    -Headers $fabricHeaders `
    -Uri "https://api.fabric.microsoft.com/v1/workspaces/$($workspaces[0].id)"
$capacities = (Invoke-RestMethod `
    -Headers $fabricHeaders `
    -Uri 'https://api.fabric.microsoft.com/v1/capacities').value
$capacity = $capacities | Where-Object id -eq $workspace.capacityId | Select-Object -First 1
if (-not $capacity -or $capacity.state -ne 'Active') {
    throw "Workspace $WorkspaceName is not assigned to an active Fabric capacity."
}

Write-Output 'DEMO_PREFLIGHT_VALID=true'
Write-Output "AZURE_FEATURE_STATE=$featureState"
Write-Output "AZURE_NETWORK_PROVIDER_STATE=$networkProviderState"
Write-Output 'FABRIC_TENANT_SETTINGS=enabled'
Write-Output "FABRIC_CAPACITY=$($capacity.sku)|$($capacity.state)"
Write-Output "ENTRA_DIRECTORY_WRITE_REQUIRED=$directoryWriteRequired"
