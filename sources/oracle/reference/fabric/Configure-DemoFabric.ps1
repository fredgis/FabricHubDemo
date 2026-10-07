[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$SubscriptionId,

    [string]$WorkspaceName = 'MSFlix',
    [string]$GatewayName = 'MSFlix Oracle Gateway Fabric',
    [string]$LakehouseName = 'MSFlixRaw',
    [string]$ConnectionName = 'MSFlix Oracle Connection',
    [string]$MirrorName = 'MSFlix_OracleMirror',
    [string]$OracleServer = '10.60.1.4:1521/FREEPDB1',
    [string]$StatePath = "$env:LOCALAPPDATA\MSFlixOracle\state.json"
)

$ErrorActionPreference = 'Stop'
$fabricBaseUri = 'https://api.fabric.microsoft.com/v1'
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $repoRoot 'scripts\Demo.Common.ps1')

function Unprotect-LocalValue {
    param([string]$Value)

    return [System.Net.NetworkCredential]::new('', (ConvertTo-SecureString $Value)).Password
}

function Join-ByteArrays {
    param([byte[][]]$Arrays)

    $length = ($Arrays | Measure-Object -Property Length -Sum).Sum
    $result = New-Object byte[] $length
    $offset = 0
    foreach ($array in $Arrays) {
        [Buffer]::BlockCopy($array, 0, $result, $offset, $array.Length)
        $offset += $array.Length
    }
    return $result
}

function Protect-GatewayBasicCredentials {
    param(
        [string]$Username,
        [string]$Password,
        [string]$Modulus,
        [string]$Exponent
    )

    $credentialJson = @{
        credentialData = @(
            @{ name = 'username'; value = $Username }
            @{ name = 'password'; value = $Password }
        )
    } | ConvertTo-Json -Compress
    $plainText = [Text.Encoding]::UTF8.GetBytes($credentialJson)
    $modulusBytes = [Convert]::FromBase64String($Modulus)
    $exponentBytes = [Convert]::FromBase64String($Exponent)

    if ($modulusBytes.Length -eq 128) {
        $encrypted = [System.Collections.Generic.List[byte]]::new()
        for ($offset = 0; $offset -lt $plainText.Length; $offset += 85) {
            $length = [Math]::Min(85, $plainText.Length - $offset)
            $segment = New-Object byte[] $length
            [Buffer]::BlockCopy($plainText, $offset, $segment, 0, $length)
            $rsa = [Security.Cryptography.RSACryptoServiceProvider]::new()
            try {
                $parameters = $rsa.ExportParameters($false)
                $parameters.Modulus = $modulusBytes
                $parameters.Exponent = $exponentBytes
                $rsa.ImportParameters($parameters)
                $encrypted.AddRange($rsa.Encrypt($segment, $true))
            }
            finally {
                $rsa.Dispose()
            }
        }
        return [Convert]::ToBase64String($encrypted.ToArray())
    }

    $keyEnc = [Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
    $keyMac = [Security.Cryptography.RandomNumberGenerator]::GetBytes(64)
    $aes = [Security.Cryptography.Aes]::Create()
    try {
        $aes.KeySize = 256
        $aes.Mode = [Security.Cryptography.CipherMode]::CBC
        $aes.Padding = [Security.Cryptography.PaddingMode]::PKCS7
        $aes.Key = $keyEnc
        $encryptor = $aes.CreateEncryptor()
        try {
            $cipherText = $encryptor.TransformFinalBlock($plainText, 0, $plainText.Length)
        }
        finally {
            $encryptor.Dispose()
        }
        $iv = $aes.IV
    }
    finally {
        $aes.Dispose()
    }

    $algorithmChoices = [byte[]](0, 0)
    $tagData = Join-ByteArrays -Arrays @($algorithmChoices, $iv, $cipherText)
    $hmac = [Security.Cryptography.HMACSHA256]::new($keyMac)
    try {
        $tag = $hmac.ComputeHash($tagData)
    }
    finally {
        $hmac.Dispose()
    }
    $authenticatedCipherText = Join-ByteArrays -Arrays @($algorithmChoices, $tag, $iv, $cipherText)

    $keys = New-Object byte[] 98
    $keys[0] = 0
    $keys[1] = 1
    [Buffer]::BlockCopy($keyEnc, 0, $keys, 2, $keyEnc.Length)
    [Buffer]::BlockCopy($keyMac, 0, $keys, 34, $keyMac.Length)

    $rsa = [Security.Cryptography.RSA]::Create()
    try {
        $parameters = [Security.Cryptography.RSAParameters]::new()
        $parameters.Modulus = $modulusBytes
        $parameters.Exponent = $exponentBytes
        $rsa.ImportParameters($parameters)
        $encryptedKeys = $rsa.Encrypt($keys, [Security.Cryptography.RSAEncryptionPadding]::OaepSHA256)
    }
    finally {
        $rsa.Dispose()
    }

    return [Convert]::ToBase64String($encryptedKeys) + [Convert]::ToBase64String($authenticatedCipherText)
}

function Invoke-FabricRequest {
    param(
        [string]$Method,
        [string]$Uri,
        [hashtable]$Headers,
        [object]$Body
    )

    $arguments = @{
        Method = $Method
        Uri = $Uri
        Headers = $Headers
        SkipHttpErrorCheck = $true
        TimeoutSec = 90
    }
    if ($null -ne $Body) {
        $arguments.ContentType = 'application/json'
        $arguments.Body = $Body | ConvertTo-Json -Depth 20
    }

    $response = Invoke-WebRequest @arguments
    if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) {
        if ($response.StatusCode -in 401, 403) {
            throw "Fabric automation identity is not authorized for $Method $Uri. Verify tenant settings, API roles, workspace Contributor, and gateway Admin access."
        }
        throw "Fabric request failed: $Method $Uri returned $($response.StatusCode): $($response.Content)"
    }
    if ($response.StatusCode -eq 202) {
        $location = @($response.Headers.Location)[0]
        $operationId = @($response.Headers.'x-ms-operation-id')[0]
        if (-not $location) {
            throw "Fabric accepted the request without an operation location. Inspect operation $operationId before retrying $Method $Uri."
        }
        $operationUri = [uri]$location
        if ($operationUri.Scheme -ne 'https' -or $operationUri.Host -ne 'api.fabric.microsoft.com') {
            throw 'Refusing to send Fabric credentials to an unexpected operation host.'
        }
        Write-Host "FABRIC_OPERATION_ID=$operationId"
        $deadline = [DateTime]::UtcNow.AddMinutes(20)
        while ([DateTime]::UtcNow -lt $deadline) {
            $delay = @($response.Headers.'Retry-After')[0]
            Start-Sleep -Seconds $(if ($delay) { [Math]::Max(1, [int]$delay) } else { 5 })
            $response = Invoke-WebRequest -Method Get -Uri $location -Headers $Headers `
                -SkipHttpErrorCheck -TimeoutSec 90
            if ($response.StatusCode -ne 200) {
                throw "Fabric operation $operationId poll returned HTTP $($response.StatusCode)."
            }
            $operation = $response.Content | ConvertFrom-Json
            if ($operation.status -eq 'Succeeded') {
                $result = Invoke-WebRequest -Method Get -Uri "$($location.TrimEnd('/'))/result" `
                    -Headers $Headers -SkipHttpErrorCheck -TimeoutSec 90
                if ($result.StatusCode -ne 200) {
                    throw "Fabric operation $operationId result returned HTTP $($result.StatusCode)."
                }
                if ([string]::IsNullOrWhiteSpace($result.Content)) { return $null }
                return $result.Content | ConvertFrom-Json
            }
            if ($operation.status -in @('Failed', 'Canceled', 'Cancelled')) {
                throw "Fabric operation $operationId $($operation.status): $($operation.error.message)"
            }
        }
        throw "Fabric operation $operationId timed out; inspect it before retrying."
    }
    if ([string]::IsNullOrWhiteSpace($response.Content)) {
        return $null
    }
    return $response.Content | ConvertFrom-Json
}

function Find-FabricNamedValue {
    param(
        [string]$Uri,
        [hashtable]$Headers,
        [string]$DisplayName,
        [int]$Attempts = 18,
        [int]$DelaySeconds = 10
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        $item = (Invoke-FabricRequest `
            -Method Get `
            -Uri $Uri `
            -Headers $Headers).value |
            Where-Object displayName -eq $DisplayName |
            Select-Object -First 1
        if ($item) {
            return $item
        }
        if ($attempt -lt $Attempts) {
            Start-Sleep -Seconds $DelaySeconds
        }
    }
    return $null
}

if (-not (Test-Path -LiteralPath $StatePath)) {
    throw "Deployment state not found: $StatePath"
}

$state = Get-Content -Raw $StatePath | ConvertFrom-Json
if ($SubscriptionId -ne 'ce9dbfdd-c341-4e8d-a1fa-51617c74c3eb' -or
    $state.subscriptionId -ne $SubscriptionId -or
    $state.tenantId -ne '1e45d0cb-b0dd-408c-8806-58b447605e96' -or
    $WorkspaceName -ne 'MSFlix' -or
    $GatewayName -ne 'MSFlix Oracle Gateway Fabric' -or
    $ConnectionName -ne 'MSFlix Oracle Connection' -or
    $MirrorName -ne 'MSFlix_OracleMirror' -or
    $LakehouseName -ne 'MSFlixRaw' -or
    $OracleServer -ne '10.60.1.4:1521/FREEPDB1') {
    throw 'Refusing Oracle Fabric configuration outside the explicitly approved MSFlix environment.'
}
$mirrorPassword = Unprotect-LocalValue -Value $state.protected.mirrorPassword

$gatewayClientSecret = Unprotect-LocalValue `
    -Value $state.gatewayIdentity.protectedClientSecret
$fabricToken = Get-DemoClientCredentialToken `
    -TenantId $state.tenantId `
    -ClientId $state.gatewayIdentity.appId `
    -ClientSecret $gatewayClientSecret `
    -Resource 'https://api.fabric.microsoft.com'
$headers = @{ Authorization = "Bearer $fabricToken" }

$headers['x-ms-fabric-skill'] = 'e2e-medallion-architecture'
$workspace = Find-FabricNamedValue `
    -Uri "$fabricBaseUri/workspaces" `
    -Headers $headers `
    -DisplayName $WorkspaceName
if (-not $workspace) {
    throw "Fabric workspace $WorkspaceName was not visible to the automation service principal within three minutes."
}

$gateway = Find-FabricNamedValue `
    -Uri "$fabricBaseUri/gateways" `
    -Headers $headers `
    -DisplayName $GatewayName
if (-not $gateway) {
    throw "Fabric gateway $GatewayName was not visible to the automation service principal within three minutes."
}
$gateway = Invoke-FabricRequest -Method Get -Uri "$fabricBaseUri/gateways/$($gateway.id)" -Headers $headers
if ($gateway.id -ne $state.fabric.gatewayId -or $gateway.id -eq 'c7d59606-b2ad-4653-98e2-a3e858075e37') {
    throw 'Refusing to use or modify an unrelated gateway.'
}
Ensure-DemoFabricRoleAssignment `
    -ResourceUri "$fabricBaseUri/gateways/$($gateway.id)" `
    -Headers $headers -PrincipalId $state.deploymentUserId -PrincipalType User `
    -Role Admin -ResourceDescription $GatewayName | Out-Null

$connections = (Invoke-FabricRequest -Method Get -Uri "$fabricBaseUri/connections" -Headers $headers).value
$connection = $connections |
    Where-Object displayName -eq $ConnectionName |
    Select-Object -First 1
if ($connection -and ($connection.gatewayId -ne $gateway.id -or
    $connection.connectionDetails.type -ne 'Oracle')) {
    throw 'The existing MSFlix-named connection does not target the dedicated Oracle gateway.'
}
if (-not $connection) {
    $encryptedCredentials = Protect-GatewayBasicCredentials `
        -Username 'C##FABRIC_MIRROR' `
        -Password $mirrorPassword `
        -Modulus $gateway.publicKey.modulus `
        -Exponent $gateway.publicKey.exponent

    $connectionBody = @{
        connectivityType = 'OnPremisesGateway'
        gatewayId = $gateway.id
        displayName = $ConnectionName
        connectionDetails = @{
            type = 'Oracle'
            creationMethod = 'Oracle'
            parameters = @(
                @{
                    dataType = 'Text'
                    name = 'server'
                    value = $OracleServer
                }
            )
        }
        privacyLevel = 'Organizational'
        credentialDetails = @{
            singleSignOnType = 'None'
            connectionEncryption = 'NotEncrypted'
            skipTestConnection = $false
            credentials = @{
                credentialType = 'Basic'
                values = @(
                    @{
                        gatewayId = $gateway.id
                        encryptedCredentials = $encryptedCredentials
                    }
                )
            }
        }
    }
    $connection = Invoke-FabricRequest `
        -Method Post `
        -Uri "$fabricBaseUri/connections" `
        -Headers $headers `
        -Body $connectionBody
}
if (-not $state.deploymentUserId) {
    throw 'The deploying user object ID is missing from the local deployment state.'
}
Ensure-DemoFabricRoleAssignment `
    -ResourceUri "$fabricBaseUri/connections/$($connection.id)" `
    -Headers $headers `
    -PrincipalId $state.deploymentUserId `
    -PrincipalType User `
    -Role Owner `
    -ResourceDescription $ConnectionName | Out-Null

$items = (Invoke-FabricRequest -Method Get -Uri "$fabricBaseUri/workspaces/$($workspace.id)/items" -Headers $headers).value
$lakehouse = $items |
    Where-Object { $_.type -eq 'Lakehouse' -and $_.displayName -eq $LakehouseName } |
    Select-Object -First 1
if (-not $lakehouse) {
    $lakehouse = Invoke-FabricRequest `
        -Method Post `
        -Uri "$fabricBaseUri/workspaces/$($workspace.id)/lakehouses" `
        -Headers $headers `
        -Body @{
            displayName = $LakehouseName
            description = 'Lakehouse for the Oracle to Fabric Demo'
            creationPayload = @{
                enableSchemas = $true
            }
        }
}

$mirrors = (Invoke-FabricRequest -Method Get -Uri "$fabricBaseUri/workspaces/$($workspace.id)/mirroredDatabases" -Headers $headers).value
$mirror = $mirrors |
    Where-Object displayName -eq $MirrorName |
    Select-Object -First 1
if (-not $mirror) {
    $definition = @{
        properties = @{
            source = @{
                type = 'Oracle'
                typeProperties = @{
                    connection = $connection.id
                    database = 'FREEPDB1'
                }
            }
            target = @{
                type = 'MountedRelationalDatabase'
                typeProperties = @{
                    defaultSchema = 'DEMO_DW'
                    format = 'Delta'
                    retentionInDays = 1
                }
            }
            mountedTables = @(
                'REF_CONTENT',
                'REF_OFFER',
                'REF_DISTRIBUTOR',
                'REF_TERRITORY',
                'REF_PRICE_RULE'
            ) | ForEach-Object {
                @{
                    source = @{
                        typeProperties = @{
                            schemaName = 'DEMO_DW'
                            tableName = $_
                        }
                    }
                }
            }
        }
    }
    $payload = [Convert]::ToBase64String(
        [Text.Encoding]::UTF8.GetBytes(($definition | ConvertTo-Json -Depth 20 -Compress))
    )
    $mirror = Invoke-FabricRequest `
        -Method Post `
        -Uri "$fabricBaseUri/workspaces/$($workspace.id)/mirroredDatabases" `
        -Headers $headers `
        -Body @{
            displayName = $MirrorName
            description = 'MSFlix Oracle reference mirror: five private source tables'
            definition = @{
                parts = @(
                    @{
                        path = 'mirroring.json'
                        payload = $payload
                        payloadType = 'InlineBase64'
                    }
                )
            }
        }
}

$status = $null
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    $statusResponse = Invoke-FabricRequest `
        -Method Post `
        -Uri "$fabricBaseUri/workspaces/$($workspace.id)/mirroredDatabases/$($mirror.id)/getMirroringStatus" `
        -Headers $headers
    $status = $statusResponse.status
    if ($status -in 'Initialized', 'Stopped', 'Running') {
        break
    }
    if ($status -notin 'Initializing', 'Starting') {
        throw "Unexpected mirroring status: $status"
    }
    Start-Sleep -Seconds 10
}
if ($status -notin 'Initialized', 'Stopped', 'Running') {
    throw "Mirroring initialization timed out with status: $status"
}

if ($status -in 'Initialized', 'Stopped') {
    Invoke-FabricRequest `
        -Method Post `
        -Uri "$fabricBaseUri/workspaces/$($workspace.id)/mirroredDatabases/$($mirror.id)/startMirroring" `
        -Headers $headers | Out-Null
}

$tableNames = @(
    'REF_CONTENT',
    'REF_OFFER',
    'REF_DISTRIBUTOR',
    'REF_TERRITORY',
    'REF_PRICE_RULE'
)
$tablesStatus = $null
for ($attempt = 0; $attempt -lt 90; $attempt++) {
    $tablesStatus = Invoke-FabricRequest `
        -Method Post `
        -Uri "$fabricBaseUri/workspaces/$($workspace.id)/mirroredDatabases/$($mirror.id)/getTablesMirroringStatus" `
        -Headers $headers
    $replicatingCount = @($tablesStatus.data | Where-Object status -eq 'Replicating').Count
    if ($replicatingCount -eq $tableNames.Count) {
        break
    }
    $failures = @($tablesStatus.data | Where-Object { $_.status -match 'Fail' })
    if ($failures.Count -gt 0) {
        throw "Mirroring failed for table $($failures[0].sourceTableName): $($failures[0].error.message)"
    }
    Start-Sleep -Seconds 10
}
if (@($tablesStatus.data | Where-Object status -eq 'Replicating').Count -ne $tableNames.Count) {
    throw 'The five Demo tables did not reach the Replicating state.'
}
$status = 'Running'

foreach ($tableName in $tableNames) {
    Invoke-FabricRequest `
        -Method Post `
        -Uri "$fabricBaseUri/workspaces/$($workspace.id)/items/$($lakehouse.id)/shortcuts?shortcutConflictPolicy=CreateOrOverwrite" `
        -Headers $headers `
        -Body @{
            path = 'Tables/DEMO_DW'
            name = $tableName
            target = @{
                oneLake = @{
                    workspaceId = $workspace.id
                    itemId = $mirror.id
                    path = "Tables/DEMO_DW/$tableName"
                }
            }
        } | Out-Null
}

$state.fabric = [pscustomobject]@{
    workspaceId = $workspace.id
    gatewayId = $gateway.id
    gatewayName = $GatewayName
    gatewayRegistrationRegion = $state.fabric.gatewayRegistrationRegion
    connectionId = $connection.id
    lakehouseId = $lakehouse.id
    mirrorId = $mirror.id
}
$state | ConvertTo-Json -Depth 12 | Set-Content -Path $StatePath -Encoding utf8NoBOM

Write-Output "FABRIC_CONNECTION=$($connection.displayName)"
Write-Output "FABRIC_LAKEHOUSE=$($lakehouse.displayName)"
Write-Output "FABRIC_MIRROR=$($mirror.displayName)"
Write-Output "MIRRORING_STATUS=$status"
Write-Output "SHORTCUT_COUNT=$($tableNames.Count)"
Write-Output 'DEPLOYMENT_USER_CONNECTION_ROLE=Owner'
