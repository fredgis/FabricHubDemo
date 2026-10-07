[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$SubscriptionId,

    [Parameter(Mandatory)]
    [string]$TenantId,

    [string]$WorkspaceName = 'MSFlix',
    [string]$ApplicationName = 'demo-oracle-gateway-automation',
    [switch]$SkipTenantAdminRoles,
    [string]$StatePath = "$env:LOCALAPPDATA\MSFlixOracle\state.json"
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Demo.Common.ps1')
$azureCliClientId = '04b07795-8ddb-461a-bbee-02f9e1bf7b46'
$nativeClientRedirectUri = 'https://login.microsoftonline.com/common/oauth2/nativeclient'

function Protect-LocalValue {
    param([string]$Value)

    return ConvertFrom-SecureString (ConvertTo-SecureString $Value -AsPlainText -Force)
}

function Get-JwtClaims {
    param([string]$AccessToken)

    $payload = $AccessToken.Split('.')[1].Replace('-', '+').Replace('_', '/')
    switch ($payload.Length % 4) {
        2 { $payload += '==' }
        3 { $payload += '=' }
    }
    return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload)) | ConvertFrom-Json
}

function Get-GraphTokenWithPkce {
    param(
        [string]$Tenant,
        [string]$LoginHint
    )

    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes

    $random = New-Object byte[] 48
    [Security.Cryptography.RandomNumberGenerator]::Fill($random)
    $verifier = [Convert]::ToBase64String($random).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    $sha = [Security.Cryptography.SHA256]::HashData([Text.Encoding]::ASCII.GetBytes($verifier))
    $challenge = [Convert]::ToBase64String($sha).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    $state = [guid]::NewGuid().ToString('N')
    $parameters = [ordered]@{
        client_id = $azureCliClientId
        response_type = 'code'
        redirect_uri = $nativeClientRedirectUri
        response_mode = 'query'
        scope = 'openid offline_access https://graph.microsoft.com/.default'
        code_challenge = $challenge
        code_challenge_method = 'S256'
        prompt = 'none'
        login_hint = $LoginHint
        state = $state
    }
    $query = ($parameters.GetEnumerator() | ForEach-Object {
        "$([uri]::EscapeDataString($_.Key))=$([uri]::EscapeDataString($_.Value))"
    }) -join '&'

    Start-Process msedge.exe -ArgumentList '--inprivate', "https://login.microsoftonline.com/$Tenant/oauth2/v2.0/authorize?$query"

    $captured = $null
    for ($attempt = 0; $attempt -lt 30 -and -not $captured; $attempt++) {
        Start-Sleep -Seconds 2
        $root = [System.Windows.Automation.AutomationElement]::RootElement
        $editCondition = [System.Windows.Automation.PropertyCondition]::new(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::Edit
        )
        $edits = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $editCondition)
        for ($index = 0; $index -lt $edits.Count; $index++) {
            $element = $edits.Item($index)
            $pattern = $null
            if ($element.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$pattern)) {
                $value = $pattern.Current.Value
                if (
                    $value -match 'login\.microsoftonline\.com/common/oauth2/nativeclient' -and
                    $value -match [regex]::Escape($state) -and
                    ($value -match '[?&]code=' -or $value -match '[?&]error=')
                ) {
                    $captured = $value
                    break
                }
            }
        }
    }
    if (-not $captured) {
        throw 'Silent Graph authentication timed out. The tenant account must have an active Edge InPrivate session.'
    }

    $uri = [uri]$captured
    $responseValues = @{}
    foreach ($part in $uri.Query.TrimStart('?') -split '&') {
        $keyValue = $part -split '=', 2
        if ($keyValue.Count -eq 2) {
            $responseValues[[uri]::UnescapeDataString($keyValue[0])] = [uri]::UnescapeDataString($keyValue[1])
        }
    }
    if ($responseValues.error) {
        throw "Silent Graph authentication failed: $($responseValues.error_description)"
    }
    if ($responseValues.state -ne $state -or -not $responseValues.code) {
        throw 'Silent Graph authentication returned an invalid response.'
    }

    $tokenResponse = Invoke-RestMethod `
        -Method Post `
        -Uri "https://login.microsoftonline.com/$Tenant/oauth2/v2.0/token" `
        -ContentType 'application/x-www-form-urlencoded' `
        -Body @{
            client_id = $azureCliClientId
            grant_type = 'authorization_code'
            code = $responseValues.code
            redirect_uri = $nativeClientRedirectUri
            code_verifier = $verifier
            scope = 'openid offline_access https://graph.microsoft.com/.default'
        }
    return $tokenResponse.access_token
}

if (-not (Test-Path -LiteralPath $StatePath)) {
    throw "Deployment state not found: $StatePath"
}

az account set --subscription $SubscriptionId
$state = Get-Content -Raw $StatePath | ConvertFrom-Json
$managementToken = (az account get-access-token `
    --subscription $SubscriptionId `
    --resource 'https://management.azure.com/' `
    --output json | ConvertFrom-Json).accessToken
$managementClaims = Get-JwtClaims -AccessToken $managementToken
$loginHint = $managementClaims.preferred_username
if (-not $loginHint) { $loginHint = $managementClaims.upn }
if (-not $loginHint) { $loginHint = $managementClaims.unique_name }

$graphToken = (az account get-access-token `
    --subscription $SubscriptionId `
    --resource 'https://graph.microsoft.com/' `
    --output json | ConvertFrom-Json).accessToken
$graphResponse = Invoke-WebRequest `
    -Uri 'https://graph.microsoft.com/v1.0/me?$select=id' `
    -Headers @{ Authorization = "Bearer $graphToken" } `
    -SkipHttpErrorCheck
if ($graphResponse.StatusCode -ne 200) {
    $graphToken = Get-GraphTokenWithPkce -Tenant $TenantId -LoginHint $loginHint
}
$graphHeaders = @{ Authorization = "Bearer $graphToken" }
$currentDeploymentUser = Invoke-RestMethod `
    -Headers $graphHeaders `
    -Uri 'https://graph.microsoft.com/v1.0/me?$select=id'
$deploymentUserId = Resolve-DemoDeploymentUserId `
    -RecordedUserId $state.deploymentUserId `
    -CurrentUserId $currentDeploymentUser.id

$fabricToken = (az account get-access-token `
    --subscription $SubscriptionId `
    --resource 'https://api.fabric.microsoft.com' `
    --output json | ConvertFrom-Json).accessToken
$fabricHeaders = @{ Authorization = "Bearer $fabricToken" }
$fabricHeaders['x-ms-fabric-skill'] = 'e2e-medallion-architecture'
$tenantSettings = (Invoke-RestMethod `
    -Headers $fabricHeaders `
    -Uri 'https://api.fabric.microsoft.com/v1/admin/tenantsettings').value
foreach ($title in @(
    'Service principals can call Fabric public APIs',
    'Service principals can create workspaces, connections, and deployment pipelines'
)) {
    $setting = $tenantSettings | Where-Object title -eq $title | Select-Object -First 1
    if (-not $setting.enabled) {
        throw @"
Required Fabric tenant setting is disabled: $title
Enable it at https://app.fabric.microsoft.com/admin-portal/tenantSettings.
Fabric Administrator or Power BI Administrator is required.
"@
    }
}

$filter = [uri]::EscapeDataString("displayName eq '$ApplicationName'")
$applications = (Invoke-RestMethod `
    -Headers $graphHeaders `
    -Uri "https://graph.microsoft.com/v1.0/applications?`$filter=$filter").value
$requiredResourceAccess = @{
    resourceAppId = '00000009-0000-0000-c000-000000000000'
    resourceAccess = @(
        @{ id = '654b31ae-d941-4e22-8798-7add8fdf049f'; type = 'Role' }
        @{ id = '28379fa9-8596-4fd9-869e-cb60a93b5d84'; type = 'Role' }
    )
}
$configuredResourceAccess = if ($SkipTenantAdminRoles) { @() } else { @($requiredResourceAccess) }

if (@($applications).Count -eq 0) {
    $application = Invoke-RestMethod `
        -Headers $graphHeaders `
        -Uri 'https://graph.microsoft.com/v1.0/applications' `
        -Method Post `
        -ContentType 'application/json' `
        -Body (@{
            displayName = $ApplicationName
            signInAudience = 'AzureADMyOrg'
            requiredResourceAccess = @($configuredResourceAccess)
        } | ConvertTo-Json -Depth 10)
}
else {
    $application = $applications[0]
    $powerBiAccess = $application.requiredResourceAccess |
        Where-Object resourceAppId -eq '00000009-0000-0000-c000-000000000000' |
        Select-Object -First 1
    $configuredRoleIds = @($powerBiAccess.resourceAccess.id)
    $requiredRoleIds = if ($SkipTenantAdminRoles) { @() } else {
        @('654b31ae-d941-4e22-8798-7add8fdf049f','28379fa9-8596-4fd9-869e-cb60a93b5d84')
    }
    if (@($requiredRoleIds | Where-Object { $_ -notin $configuredRoleIds }).Count -gt 0) {
        Invoke-RestMethod `
            -Headers $graphHeaders `
            -Uri "https://graph.microsoft.com/v1.0/applications/$($application.id)" `
            -Method Patch `
            -ContentType 'application/json' `
            -Body (@{ requiredResourceAccess = @($configuredResourceAccess) } | ConvertTo-Json -Depth 10)
    }
}

$servicePrincipalFilter = [uri]::EscapeDataString("appId eq '$($application.appId)'")
$servicePrincipals = (Invoke-RestMethod `
    -Headers $graphHeaders `
    -Uri "https://graph.microsoft.com/v1.0/servicePrincipals?`$filter=$servicePrincipalFilter").value
if (@($servicePrincipals).Count -eq 0) {
    $servicePrincipal = Invoke-RestMethod `
        -Headers $graphHeaders `
        -Uri 'https://graph.microsoft.com/v1.0/servicePrincipals' `
        -Method Post `
        -ContentType 'application/json' `
        -Body (@{ appId = $application.appId } | ConvertTo-Json)
}
else {
    $servicePrincipal = $servicePrincipals[0]
}

$clientSecret = $null
if (
    $state.gatewayIdentity.protectedClientSecret -and
    [datetime]$state.gatewayIdentity.secretExpires -gt (Get-Date).ToUniversalTime().AddDays(7)
) {
    $clientSecret = [System.Net.NetworkCredential]::new(
        '',
        (ConvertTo-SecureString $state.gatewayIdentity.protectedClientSecret)
    ).Password
    $secretExpiry = $state.gatewayIdentity.secretExpires
    $secretKeyId = $state.gatewayIdentity.secretKeyId
}
else {
    $password = Invoke-RestMethod `
        -Headers $graphHeaders `
        -Uri "https://graph.microsoft.com/v1.0/applications/$($application.id)/addPassword" `
        -Method Post `
        -ContentType 'application/json' `
        -Body (@{
            passwordCredential = @{
                displayName = 'Demo gateway automation'
                endDateTime = (Get-Date).ToUniversalTime().AddDays(30).ToString('o')
            }
        } | ConvertTo-Json -Depth 5)
    $clientSecret = $password.secretText
    $secretExpiry = $password.endDateTime
    $secretKeyId = $password.keyId
}

$applicationDetails = Invoke-RestMethod `
    -Headers $graphHeaders `
    -Uri "https://graph.microsoft.com/v1.0/applications/$($application.id)?`$select=passwordCredentials"
if (-not $secretKeyId) {
    $expectedExpiry = [datetime]$secretExpiry
    $currentCredential = @($applicationDetails.passwordCredentials) |
        Sort-Object startDateTime -Descending |
        Where-Object {
            [Math]::Abs((([datetime]$_.endDateTime) - $expectedExpiry).TotalSeconds) -lt 5
        } |
        Select-Object -First 1
    if (-not $currentCredential) {
        $currentCredential = @($applicationDetails.passwordCredentials) |
            Sort-Object startDateTime -Descending |
            Select-Object -First 1
    }
    $secretKeyId = $currentCredential.keyId
}
foreach ($credential in @($applicationDetails.passwordCredentials | Where-Object keyId -ne $secretKeyId)) {
    try {
        Invoke-RestMethod `
            -Headers $graphHeaders `
            -Uri "https://graph.microsoft.com/v1.0/applications/$($application.id)/removePassword" `
            -Method Post `
            -ContentType 'application/json' `
            -Body (@{ keyId = $credential.keyId } | ConvertTo-Json) | Out-Null
    }
    catch {
        if ([int]$_.Exception.Response.StatusCode -ne 403) {
            throw
        }
        Write-Warning 'Stale application credentials could not be removed because the elevated directory role is no longer active.'
        break
    }
}

$powerBiServicePrincipalFilter = [uri]::EscapeDataString("appId eq '00000009-0000-0000-c000-000000000000'")
$powerBiServicePrincipal = (Invoke-RestMethod `
    -Headers $graphHeaders `
    -Uri "https://graph.microsoft.com/v1.0/servicePrincipals?`$filter=$powerBiServicePrincipalFilter").value |
    Select-Object -First 1
$existingAssignments = (Invoke-RestMethod `
    -Headers $graphHeaders `
    -Uri "https://graph.microsoft.com/v1.0/servicePrincipals/$($servicePrincipal.id)/appRoleAssignments").value
$assignmentRoleIds = if ($SkipTenantAdminRoles) { @() } else {
    @('654b31ae-d941-4e22-8798-7add8fdf049f','28379fa9-8596-4fd9-869e-cb60a93b5d84')
}
if ($SkipTenantAdminRoles) {
    Write-Output 'ORACLE_GATEWAY_AUTH=Workspace-scoped service principal; no tenant-admin application roles'
}
foreach ($roleId in $assignmentRoleIds) {
    if (-not ($existingAssignments | Where-Object appRoleId -eq $roleId)) {
        try {
            Invoke-RestMethod `
                -Headers $graphHeaders `
                -Uri "https://graph.microsoft.com/v1.0/servicePrincipals/$($servicePrincipal.id)/appRoleAssignments" `
                -Method Post `
                -ContentType 'application/json' `
                -Body (@{
                    principalId = $servicePrincipal.id
                    resourceId = $powerBiServicePrincipal.id
                    appRoleId = $roleId
                } | ConvertTo-Json) | Out-Null
        }
        catch {
            if ([int]$_.Exception.Response.StatusCode -eq 403) {
                throw @"
Microsoft Graph denied the app-role assignment.
Activate Cloud Application Administrator or Application Administrator in PIM, then refresh Azure CLI:
az logout
az login --tenant `$env:AZURE_TENANT_ID --use-device-code
az account set --subscription `$env:AZURE_SUBSCRIPTION_ID
"@
            }
            throw
        }
    }
}

$workspace = (Invoke-RestMethod -Headers $fabricHeaders -Uri 'https://api.fabric.microsoft.com/v1/workspaces').value |
    Where-Object displayName -eq $WorkspaceName |
    Select-Object -First 1
if (-not $workspace) {
    throw "Fabric workspace not found: $WorkspaceName"
}
$workspaceRoles = (Invoke-RestMethod `
    -Headers $fabricHeaders `
    -Uri "https://api.fabric.microsoft.com/v1/workspaces/$($workspace.id)/roleAssignments").value
if (-not ($workspaceRoles | Where-Object { $_.principal.id -eq $servicePrincipal.id })) {
    Invoke-RestMethod `
        -Headers $fabricHeaders `
        -Uri "https://api.fabric.microsoft.com/v1/workspaces/$($workspace.id)/roleAssignments" `
        -Method Post `
        -ContentType 'application/json' `
        -Body (@{
            principal = @{
                id = $servicePrincipal.id
                type = 'ServicePrincipal'
            }
            role = 'Contributor'
        } | ConvertTo-Json -Depth 5) | Out-Null
}

$state | Add-Member -NotePropertyName gatewayIdentity -NotePropertyValue ([pscustomobject]@{
    appId = $application.appId
    servicePrincipalId = $servicePrincipal.id
    protectedClientSecret = Protect-LocalValue -Value $clientSecret
    secretExpires = $secretExpiry
    secretKeyId = $secretKeyId
}) -Force
$state | Add-Member `
    -NotePropertyName deploymentUserId `
    -NotePropertyValue $deploymentUserId `
    -Force
$state | Add-Member -NotePropertyName fabric -NotePropertyValue ([pscustomobject]@{
    workspaceId = $workspace.id
    gatewayId = $state.fabric.gatewayId
    connectionId = $state.fabric.connectionId
    lakehouseId = $state.fabric.lakehouseId
    mirrorId = $state.fabric.mirrorId
}) -Force
$state | ConvertTo-Json -Depth 12 | Set-Content -Path $StatePath -Encoding utf8NoBOM

Write-Output "GATEWAY_APPLICATION=$ApplicationName"
Write-Output "SECRET_EXPIRES=$secretExpiry"
