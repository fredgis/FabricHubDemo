[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$SubscriptionId,

    [Parameter(Mandatory)]
    [string]$TenantId,

    [string]$ResourceGroupName = 'MSFlix',
    [string]$Location = 'southeastasia',
    [string]$Prefix = 'demo'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'Demo.Common.ps1')
$templateFile = Join-Path $repoRoot 'infra\main.bicep'
$gatewayPreparationScriptFile = Join-Path $repoRoot 'fabric\Prepare-DemoGateway.ps1'
$stateDirectory = Join-Path $env:LOCALAPPDATA 'MSFlixOracle'
$stateFile = Join-Path $stateDirectory 'state.json'
$workDir = Join-Path $env:TEMP "oracle-fabric-demo-$([guid]::NewGuid().ToString('N'))"
$parametersFile = Join-Path $workDir 'parameters.json'
$protectedSettingsFile = Join-Path $workDir 'protected-settings.json'
$sshPrivateKey = Join-Path $workDir 'demo-oracle-ssh'
$sshPublicKey = "$sshPrivateKey.pub"
$temporaryRoleAssignmentId = $null

function New-DemoPassword {
    param(
        [int]$Length = 32,
        [switch]$IncludeSymbols
    )

    $letters = 'abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    $symbols = '!#%+,-.:=@_'
    $alphabet = if ($IncludeSymbols) { $letters + $symbols } else { $letters }
    $bytes = New-Object byte[] $Length
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    $chars = for ($index = 0; $index -lt $Length; $index++) {
        $alphabet[$bytes[$index] % $alphabet.Length]
    }
    $password = -join $chars
    if ($password -notmatch '[A-Z]') { $password = "A$password" }
    if ($password -notmatch '[a-z]') { $password = "a$password" }
    if ($password -notmatch '[0-9]') { $password = "9$password" }
    if ($IncludeSymbols -and $password -notmatch '[!#%+,\-.=@_]') { $password = "!$password" }
    return $password
}

function Protect-LocalValue {
    param([string]$Value)

    return ConvertFrom-SecureString (ConvertTo-SecureString $Value -AsPlainText -Force)
}

function Unprotect-LocalValue {
    param([string]$Value)

    $secure = ConvertTo-SecureString $Value
    return [System.Net.NetworkCredential]::new('', $secure).Password
}

function ConvertTo-Base64 {
    param([string]$Value)

    return [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Value))
}

function Compress-TextToBase64 {
    param([string]$Value)

    $inputBytes = [Text.Encoding]::UTF8.GetBytes($Value)
    $output = [IO.MemoryStream]::new()
    $gzip = [IO.Compression.GzipStream]::new($output, [IO.Compression.CompressionMode]::Compress)
    try {
        $gzip.Write($inputBytes, 0, $inputBytes.Length)
    }
    finally {
        $gzip.Dispose()
    }
    return [Convert]::ToBase64String($output.ToArray())
}

function New-SecretSeedScript {
    param(
        [string]$VaultName,
        [hashtable]$Secrets
    )

    $commands = foreach ($entry in $Secrets.GetEnumerator()) {
        "put_secret '$($entry.Key)' '$(ConvertTo-Base64 -Value $entry.Value)'"
    }
    $template = @'
#!/usr/bin/env bash
set -euo pipefail

VAULT_NAME='__VAULT_NAME__'

token="$(curl --fail --silent --show-error \
    --header Metadata:true \
    'http://169.254.169.254/metadata/identity/oauth2/token?api-version=2019-08-01&resource=https%3A%2F%2Fvault.azure.net' \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"

put_secret() {
    local name="$1"
    local encoded="$2"
    local body
    body="$(python3 - "$encoded" <<'PY'
import base64
import json
import sys

print(json.dumps({"value": base64.b64decode(sys.argv[1]).decode("utf-8")}))
PY
)"

    for attempt in $(seq 1 18); do
        status="$(curl --silent --show-error \
            --output /tmp/keyvault-response.json \
            --write-out '%{http_code}' \
            --request PUT \
            --header "Authorization: Bearer ${token}" \
            --header 'Content-Type: application/json' \
            --data "${body}" \
            "https://${VAULT_NAME}.vault.azure.net/secrets/${name}?api-version=7.4")"
        if [[ "$status" == "200" ]]; then
            rm -f /tmp/keyvault-response.json
            return
        fi
        sleep 10
    done

    cat /tmp/keyvault-response.json >&2
    exit 1
}

__SECRET_COMMANDS__
'@
    return $template.Replace('__VAULT_NAME__', $VaultName).Replace('__SECRET_COMMANDS__', ($commands -join "`n"))
}

New-Item -ItemType Directory -Path $workDir | Out-Null
New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null

try {
    az account set --subscription $SubscriptionId
    $account = az account show --subscription $SubscriptionId --output json | ConvertFrom-Json
    if ($account.tenantId -ne $TenantId) {
        throw 'The selected subscription does not belong to the expected tenant.'
    }

    if (-not (Get-Command ssh-keygen -ErrorAction SilentlyContinue)) {
        throw 'ssh-keygen is required to manage the Demo key.'
    }

    $vmJson = (Invoke-DemoNativeCommand `
        -Description 'Azure VM list' `
        -Command {
            az vm list `
                --subscription $SubscriptionId `
                --resource-group $ResourceGroupName `
                --output json
        }) -join "`n"
    $existingVms = $vmJson | ConvertFrom-Json
    $expectedVmNames = @("$Prefix-oracle-vm", "$Prefix-fabric-gateway-vm")
    $existingVmCount = @(
        $existingVms | Where-Object name -in $expectedVmNames
    ).Count

    $storedState = $null
    if (Test-Path -LiteralPath $stateFile) {
        $storedState = Get-Content -Raw $stateFile | ConvertFrom-Json
        if ($storedState.subscriptionId -ne $SubscriptionId -or $storedState.tenantId -ne $TenantId) {
            throw 'The local encrypted state belongs to a different Azure environment.'
        }
        $windowsAdminPassword = Unprotect-LocalValue -Value $storedState.protected.windowsAdminPassword
        $oracleSysPassword = Unprotect-LocalValue -Value $storedState.protected.oracleSysPassword
        $schemaPassword = Unprotect-LocalValue -Value $storedState.protected.schemaPassword
        $mirrorPassword = Unprotect-LocalValue -Value $storedState.protected.mirrorPassword
        $gatewayRecoveryKey = Unprotect-LocalValue -Value $storedState.protected.gatewayRecoveryKey
        $privateKeyValue = Unprotect-LocalValue -Value $storedState.protected.linuxSshPrivateKey
        $roleAssignmentSalt = $storedState.roleAssignmentSalt
        Set-Content -Path $sshPrivateKey -Value $privateKeyValue -Encoding utf8NoBOM -NoNewline
        & ssh-keygen -y -f $sshPrivateKey | Set-Content -Path $sshPublicKey -Encoding ascii -NoNewline
        if ($LASTEXITCODE -ne 0) {
            throw 'Unable to derive the stored SSH public key.'
        }
    }
    else {
        if ($existingVmCount -gt 0) {
            throw 'Demo VMs exist but the local encrypted credential state is missing.'
        }
        & ssh-keygen -q -t ed25519 -N '' -C 'oracle-to-fabric-demo' -f $sshPrivateKey
        if ($LASTEXITCODE -ne 0) {
            throw 'ssh-keygen failed.'
        }
        $windowsAdminPassword = New-DemoPassword -Length 30 -IncludeSymbols
        $oracleSysPassword = New-DemoPassword -Length 30
        $schemaPassword = New-DemoPassword -Length 30
        $mirrorPassword = New-DemoPassword -Length 30
        $gatewayRecoveryKey = New-DemoPassword -Length 40 -IncludeSymbols
        $roleAssignmentSalt = [guid]::NewGuid().ToString()
    }

    $bootstrapState = @{
        version = 1
        subscriptionId = $SubscriptionId
        tenantId = $TenantId
        resourceGroupName = $ResourceGroupName
        location = $Location
        workspaceName = 'MSFlix'
        roleAssignmentSalt = $roleAssignmentSalt
        protected = @{
            windowsAdminPassword = Protect-LocalValue -Value $windowsAdminPassword
            oracleSysPassword = Protect-LocalValue -Value $oracleSysPassword
            schemaPassword = Protect-LocalValue -Value $schemaPassword
            mirrorPassword = Protect-LocalValue -Value $mirrorPassword
            gatewayRecoveryKey = Protect-LocalValue -Value $gatewayRecoveryKey
            linuxSshPrivateKey = Protect-LocalValue -Value (Get-Content -Raw $sshPrivateKey)
        }
    }
    if ($storedState.gatewayIdentity) {
        $bootstrapState.gatewayIdentity = $storedState.gatewayIdentity
    }
    if ($storedState.fabric) {
        $bootstrapState.fabric = $storedState.fabric
    }
    if ($storedState.deploymentUserId) {
        $bootstrapState.deploymentUserId = $storedState.deploymentUserId
    }
    $bootstrapState | ConvertTo-Json -Depth 8 | Set-Content -Path $stateFile -Encoding utf8NoBOM

    $parameters = @{
        '$schema' = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
        contentVersion = '1.0.0.0'
        parameters = @{
            location = @{ value = $Location }
            prefix = @{ value = $Prefix }
            windowsAdminPassword = @{ value = $windowsAdminPassword }
            linuxSshPublicKey = @{ value = (Get-Content -Raw $sshPublicKey).Trim() }
            gatewayPreparationScriptGzipBase64 = @{
                value = Compress-TextToBase64 -Value (Get-Content -Raw $gatewayPreparationScriptFile)
            }
            roleAssignmentSalt = @{ value = $roleAssignmentSalt }
        }
    }
    $parameters | ConvertTo-Json -Depth 10 | Set-Content -Path $parametersFile -Encoding utf8NoBOM

    $deploymentName = "demo-foundation-$((Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss'))"
    $deployment = az deployment group create `
        --subscription $SubscriptionId `
        --resource-group $ResourceGroupName `
        --name $deploymentName `
        --template-file $templateFile `
        --parameters "@$parametersFile" `
        --output json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $deployment.properties.provisioningState -ne 'Succeeded') {
        throw 'Azure foundation deployment failed.'
    }

    $outputs = $deployment.properties.outputs
    $keyVaultName = $outputs.keyVaultName.value
    $oracleVmName = $outputs.oracleVmName.value
    $oracleVmPrincipalId = $outputs.oracleVmPrincipalId.value
    $keyVaultResourceId = $outputs.keyVaultResourceId.value

    $secretsOfficerRoleId = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
    $roleAssignment = az role assignment create `
        --subscription $SubscriptionId `
        --assignee-object-id $oracleVmPrincipalId `
        --assignee-principal-type ServicePrincipal `
        --role $secretsOfficerRoleId `
        --scope $keyVaultResourceId `
        --output json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to grant temporary Key Vault secret write access.'
    }
    $temporaryRoleAssignmentId = $roleAssignment.id

    $secretValues = @{
        'demo-windows-admin-password' = $windowsAdminPassword
        'demo-oracle-sys-password' = $oracleSysPassword
        'demo-schema-password' = $schemaPassword
        'demo-mirror-password' = $mirrorPassword
        'demo-gateway-recovery-key' = $gatewayRecoveryKey
        'demo-linux-ssh-private-key' = (Get-Content -Raw $sshPrivateKey)
    }
    if ($bootstrapState.gatewayIdentity.protectedClientSecret) {
        $secretValues['demo-gateway-app-id'] = $bootstrapState.gatewayIdentity.appId
        $secretValues['demo-gateway-app-client-secret'] = Unprotect-LocalValue -Value $bootstrapState.gatewayIdentity.protectedClientSecret
    }
    $secretSeedScript = New-SecretSeedScript -VaultName $keyVaultName -Secrets $secretValues
    $protectedSettings = @{
        script = ConvertTo-Base64 -Value $secretSeedScript
    }
    $protectedSettings | ConvertTo-Json -Depth 5 | Set-Content -Path $protectedSettingsFile -Encoding utf8NoBOM

    az vm extension set `
        --subscription $SubscriptionId `
        --resource-group $ResourceGroupName `
        --vm-name $oracleVmName `
        --publisher Microsoft.Azure.Extensions `
        --name CustomScript `
        --version 2.1 `
        --protected-settings "@$protectedSettingsFile" `
        --output none
    if ($LASTEXITCODE -ne 0) {
        throw 'The private Key Vault secret seed operation failed.'
    }

    az vm extension delete `
        --subscription $SubscriptionId `
        --resource-group $ResourceGroupName `
        --vm-name $oracleVmName `
        --name CustomScript `
        --output none
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to remove the temporary secret seed extension.'
    }

    $bastionName = "$Prefix-bastion"
    $bastionCount = Get-DemoExactNameCount `
        -Name $bastionName `
        -Description 'Azure Bastion list' `
        -ListCommand {
            az network bastion list `
                --subscription $SubscriptionId `
                --resource-group $ResourceGroupName `
                --output json
        }
    if ($bastionCount -eq 0) {
        az network bastion create `
            --subscription $SubscriptionId `
            --resource-group $ResourceGroupName `
            --name $bastionName `
            --location $Location `
            --sku Developer `
            --vnet-name $outputs.vnetName.value `
            --output none
        if ($LASTEXITCODE -ne 0) {
            throw 'Bastion Developer deployment failed.'
        }
    }
    elseif ($bastionCount -eq 1) {
        az network bastion update `
            --subscription $SubscriptionId `
            --resource-group $ResourceGroupName `
            --name $bastionName `
            --location $Location `
            --network-acls '{ip-rules:[]}' `
            --output none
        if ($LASTEXITCODE -ne 0) {
            throw 'Unable to reconcile Bastion Developer network ACLs.'
        }
    }
    else {
        throw "Expected at most one Bastion named $bastionName, found $bastionCount."
    }

    $state = @{
        version = 1
        subscriptionId = $SubscriptionId
        tenantId = $TenantId
        resourceGroupName = $ResourceGroupName
        location = $Location
        workspaceName = 'MSFlix'
        roleAssignmentSalt = $roleAssignmentSalt
        vnetName = $outputs.vnetName.value
        oracleVmName = $oracleVmName
        gatewayVmName = $outputs.gatewayVmName.value
        keyVaultName = $keyVaultName
        oraclePrivateIp = $outputs.oraclePrivateIp.value
        gatewayPrivateIp = $outputs.gatewayPrivateIp.value
        natPublicIpAddress = $outputs.natPublicIpAddress.value
        protected = @{
            windowsAdminPassword = Protect-LocalValue -Value $windowsAdminPassword
            oracleSysPassword = Protect-LocalValue -Value $oracleSysPassword
            schemaPassword = Protect-LocalValue -Value $schemaPassword
            mirrorPassword = Protect-LocalValue -Value $mirrorPassword
            gatewayRecoveryKey = Protect-LocalValue -Value $gatewayRecoveryKey
            linuxSshPrivateKey = Protect-LocalValue -Value (Get-Content -Raw $sshPrivateKey)
        }
    }
    if ($bootstrapState.gatewayIdentity) {
        $state.gatewayIdentity = $bootstrapState.gatewayIdentity
    }
    if ($bootstrapState.fabric) {
        $state.fabric = $bootstrapState.fabric
    }
    if ($bootstrapState.deploymentUserId) {
        $state.deploymentUserId = $bootstrapState.deploymentUserId
    }
    $state | ConvertTo-Json -Depth 8 | Set-Content -Path $stateFile -Encoding utf8NoBOM

    Write-Output "STATE_FILE=$stateFile"
    Write-Output "KEY_VAULT=$keyVaultName"
    Write-Output "ORACLE_VM=$oracleVmName"
    Write-Output "GATEWAY_VM=$($outputs.gatewayVmName.value)"
}
finally {
    if ($temporaryRoleAssignmentId) {
        az role assignment delete --subscription $SubscriptionId --ids $temporaryRoleAssignmentId --output none 2>$null
    }
    if (Test-Path -LiteralPath $workDir) {
        Remove-Item -LiteralPath $workDir -Recurse -Force
    }
}
