[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$SubscriptionId,

    [Parameter(Mandatory)]
    [string]$TenantId,

    [string]$ResourceGroupName = 'MSFlix',
    [switch]$RunCdcValidation
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$statePath = "$env:LOCALAPPDATA\MSFlixOracle\state.json"
. (Join-Path $PSScriptRoot 'Demo.Common.ps1')

function Unprotect-LocalValue {
    param([string]$Value)

    return [System.Net.NetworkCredential]::new('', (ConvertTo-SecureString $Value)).Password
}

function Get-AutomationFabricHeaders {
    param([pscustomobject]$State)

    if (
        -not $State.gatewayIdentity.appId -or
        -not $State.gatewayIdentity.protectedClientSecret
    ) {
        throw 'The Fabric automation identity is missing from the local encrypted state.'
    }

    $clientSecret = Unprotect-LocalValue -Value $State.gatewayIdentity.protectedClientSecret
    $token = Get-DemoClientCredentialToken `
        -TenantId $State.tenantId `
        -ClientId $State.gatewayIdentity.appId `
        -ClientSecret $clientSecret `
        -Resource 'https://api.fabric.microsoft.com'
    return @{ Authorization = "Bearer $token" }
}

function Find-FabricGateway {
    param(
        [hashtable]$Headers,
        [string]$GatewayName,
        [int]$Attempts = 1,
        [int]$DelaySeconds = 10
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        $response = Invoke-WebRequest `
            -Headers $Headers `
            -Uri 'https://api.fabric.microsoft.com/v1/gateways' `
            -SkipHttpErrorCheck
        if ($response.StatusCode -in 401, 403) {
            throw 'The Fabric automation service principal cannot list gateways. Verify tenant settings, API roles, and gateway Admin access.'
        }
        if ($response.StatusCode -ne 200) {
            throw "Fabric gateway lookup returned HTTP $($response.StatusCode): $($response.Content)"
        }

        $gateway = ($response.Content | ConvertFrom-Json).value |
            Where-Object displayName -eq $GatewayName |
            Select-Object -First 1
        if ($gateway) {
            return $gateway
        }
        if ($attempt -lt $Attempts) {
            Start-Sleep -Seconds $DelaySeconds
        }
    }
    return $null
}

& (Join-Path $PSScriptRoot 'Test-DemoPrerequisites.ps1') `
    -SubscriptionId $SubscriptionId `
    -TenantId $TenantId `
    -WorkspaceName 'MSFlix'

$identityExisted = $false
if (Test-Path -LiteralPath $statePath) {
    $initialState = Get-Content -Raw $statePath | ConvertFrom-Json
    $identityExisted = [bool]$initialState.gatewayIdentity.appId
}

& (Join-Path $PSScriptRoot 'Deploy-DemoFoundation.ps1') `
    -SubscriptionId $SubscriptionId `
    -TenantId $TenantId `
    -ResourceGroupName $ResourceGroupName

& (Join-Path $PSScriptRoot 'Initialize-DemoIdentity.ps1') `
    -SubscriptionId $SubscriptionId `
    -TenantId $TenantId

if (-not $identityExisted) {
    & (Join-Path $PSScriptRoot 'Deploy-DemoFoundation.ps1') `
        -SubscriptionId $SubscriptionId `
        -TenantId $TenantId `
        -ResourceGroupName $ResourceGroupName
}

$state = Get-Content -Raw $statePath | ConvertFrom-Json
$oracleInstallScript = Join-Path $repoRoot 'oracle\Install-OracleDemo.sh'
$oracleRpmUrl = 'https://download.oracle.com/otn-pub/otn_software/db-free/oracle-ai-database-free-26ai-23.26.3-1.el9.x86_64.rpm'
$oracleRpmSha256 = '895fc9df794685b515c4ac83f104dbdfb657eb0e92c41e45c58302fb8fd53e44'

az vm run-command invoke `
    --subscription $SubscriptionId `
    --resource-group $ResourceGroupName `
    --name $state.oracleVmName `
    --command-id RunShellScript `
    --scripts "@$oracleInstallScript" `
    --parameters $state.keyVaultName $oracleRpmUrl $oracleRpmSha256 `
    --output none
if ($LASTEXITCODE -ne 0) {
    throw 'Oracle installation failed.'
}

$connectivity = az vm run-command invoke `
    --subscription $SubscriptionId `
    --resource-group $ResourceGroupName `
    --name $state.gatewayVmName `
    --command-id RunPowerShellScript `
    --scripts "@$(Join-Path $repoRoot 'fabric\Test-DemoOracleConnectivity.ps1')" `
    --parameters "OracleHost=$($state.oraclePrivateIp)" 'OraclePort=1521' `
    --query 'value[0].message' `
    --output tsv
$connectivityText = $connectivity -join "`n"
if ($LASTEXITCODE -ne 0 -or $connectivityText -notmatch 'ORACLE_TCP_VALID=true') {
    throw "Gateway-to-Oracle TCP validation failed: $connectivityText"
}

$fabricHeaders = Get-AutomationFabricHeaders -State $state
$gateway = Find-FabricGateway `
    -Headers $fabricHeaders `
    -GatewayName 'MSFlix Oracle Gateway'

if (-not $gateway) {
    $clientSecret = Unprotect-LocalValue -Value $state.gatewayIdentity.protectedClientSecret
    $recoveryKey = Unprotect-LocalValue -Value $state.protected.gatewayRecoveryKey
    $commandName = 'demo-register-gateway'
    az vm run-command delete `
        --subscription $SubscriptionId `
        --resource-group $ResourceGroupName `
        --vm-name $state.gatewayVmName `
        --run-command-name $commandName `
        --yes `
        --output none 2>$null
    az vm run-command create `
        --subscription $SubscriptionId `
        --resource-group $ResourceGroupName `
        --vm-name $state.gatewayVmName `
        --run-command-name $commandName `
        --location $state.location `
        --script "@$(Join-Path $repoRoot 'fabric\Register-DemoGateway.ps1')" `
        --protected-parameters "ClientSecret=$clientSecret" "RecoveryKey=$recoveryKey" `
        --parameters `
            "ApplicationId=$($state.gatewayIdentity.appId)" `
            "TenantId=$TenantId" `
            'GatewayName=MSFlix Oracle Gateway' `
            'RegionKey=southeastasia' `
        --timeout-in-seconds 300 `
        --async-execution false `
        --output none
    $registrationExitCode = $LASTEXITCODE
    az vm run-command delete `
        --subscription $SubscriptionId `
        --resource-group $ResourceGroupName `
        --vm-name $state.gatewayVmName `
        --run-command-name $commandName `
        --yes `
        --output none
    $cleanupExitCode = $LASTEXITCODE
    if ($registrationExitCode -ne 0) {
        throw 'Gateway registration failed.'
    }
    if ($cleanupExitCode -ne 0) {
        throw 'Gateway registration succeeded, but its temporary Run Command could not be removed.'
    }

    $gateway = Find-FabricGateway `
        -Headers $fabricHeaders `
        -GatewayName 'MSFlix Oracle Gateway' `
        -Attempts 18 `
        -DelaySeconds 10
    if (-not $gateway) {
        throw 'Gateway registration completed, but the automation service principal could not discover it within three minutes.'
    }
}

$gatewayRoles = (Invoke-RestMethod `
    -Headers $fabricHeaders `
    -Uri "https://api.fabric.microsoft.com/v1/gateways/$($gateway.id)/roleAssignments").value
if (-not ($gatewayRoles | Where-Object {
    $_.principal.id -eq $state.gatewayIdentity.servicePrincipalId -and
    $_.role -eq 'Admin'
})) {
    throw 'The Fabric automation service principal is not an Admin of MSFlix Oracle Gateway.'
}
if (-not $state.deploymentUserId) {
    throw 'The deploying user object ID is missing from the local deployment state.'
}
Ensure-DemoFabricRoleAssignment `
    -ResourceUri "https://api.fabric.microsoft.com/v1/gateways/$($gateway.id)" `
    -Headers $fabricHeaders `
    -PrincipalId $state.deploymentUserId `
    -PrincipalType User `
    -Role Admin `
    -ResourceDescription 'MSFlix Oracle Gateway' | Out-Null

& (Join-Path $repoRoot 'fabric\Configure-DemoFabric.ps1') -SubscriptionId $SubscriptionId
& (Join-Path $repoRoot 'tests\Validate-AzureDemo.ps1') -SubscriptionId $SubscriptionId

$state = Get-Content -Raw $statePath | ConvertFrom-Json
$oracleValidation = az vm run-command invoke `
    --subscription $SubscriptionId `
    --resource-group $ResourceGroupName `
    --name $state.oracleVmName `
    --command-id RunShellScript `
    --scripts "@$(Join-Path $repoRoot 'oracle\Validate-OracleDemo.sh')" `
    --query 'value[0].message' `
    --output tsv
$oracleValidationText = $oracleValidation -join "`n"
if ($oracleValidationText -notmatch 'FACT_SALES=25000') {
    throw "Oracle validation failed: $oracleValidationText"
}

$keyVaultValidation = az vm run-command invoke `
    --subscription $SubscriptionId `
    --resource-group $ResourceGroupName `
    --name $state.oracleVmName `
    --command-id RunShellScript `
    --scripts "@$(Join-Path $repoRoot 'oracle\Validate-KeyVaultSecrets.sh')" `
    --parameters $state.keyVaultName `
    --query 'value[0].message' `
    --output tsv
$keyVaultValidationText = $keyVaultValidation -join "`n"
if ($keyVaultValidationText -notmatch 'demo-gateway-app-client-secret\|STATUS=present') {
    throw "Key Vault validation failed: $keyVaultValidationText"
}

if ($RunCdcValidation) {
    & (Join-Path $repoRoot 'tests\Invoke-DemoCdcValidation.ps1')
}

Write-Output 'DEPLOYMENT_USER_GATEWAY_ROLE=Admin'
Write-Output 'DEMO_DEPLOYMENT_VALID=true'
