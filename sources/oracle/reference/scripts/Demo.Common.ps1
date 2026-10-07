function Assert-DemoCommand {
    param(
        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [string]$Remediation
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name is required.`nRun:`n$Remediation"
    }
}

function Invoke-DemoNativeCommand {
    param(
        [Parameter(Mandatory)]
        [scriptblock]$Command,

        [Parameter(Mandatory)]
        [string]$Description
    )

    $stderrPath = Join-Path $env:TEMP "oracle-fabric-stderr-$([guid]::NewGuid().ToString('N')).txt"
    try {
        $output = @(& $Command 2> $stderrPath)
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            $stderr = if (Test-Path -LiteralPath $stderrPath) {
                Get-Content -Raw $stderrPath
            }
            else {
                ''
            }
            $details = ((@($output) + @($stderr)) | Out-String).Trim()
            throw "$Description failed with exit code $exitCode.`n$details"
        }
        return $output
    }
    finally {
        if (Test-Path -LiteralPath $stderrPath) {
            Remove-Item -LiteralPath $stderrPath -Force
        }
    }
}

function Get-DemoExactNameCount {
    param(
        [Parameter(Mandatory)]
        [scriptblock]$ListCommand,

        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [string]$Description
    )

    $json = (Invoke-DemoNativeCommand -Command $ListCommand -Description $Description) -join "`n"
    try {
        $resources = $json | ConvertFrom-Json
    }
    catch {
        throw "$Description returned invalid JSON."
    }
    return @($resources | Where-Object name -eq $Name).Count
}

function Get-DemoJwtClaims {
    param(
        [Parameter(Mandatory)]
        [string]$AccessToken
    )

    $payload = $AccessToken.Split('.')[1].Replace('-', '+').Replace('_', '/')
    switch ($payload.Length % 4) {
        2 { $payload += '==' }
        3 { $payload += '=' }
    }
    return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload)) |
        ConvertFrom-Json
}

function Get-DemoClientCredentialToken {
    param(
        [Parameter(Mandatory)]
        [string]$TenantId,

        [Parameter(Mandatory)]
        [string]$ClientId,

        [Parameter(Mandatory)]
        [string]$ClientSecret,

        [Parameter(Mandatory)]
        [string]$Resource
    )

    $scope = "$($Resource.TrimEnd('/'))/.default"
    $response = Invoke-RestMethod `
        -Method Post `
        -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" `
        -ContentType 'application/x-www-form-urlencoded' `
        -Body @{
            client_id = $ClientId
            client_secret = $ClientSecret
            grant_type = 'client_credentials'
            scope = $scope
        }
    return $response.access_token
}

function Resolve-DemoDeploymentUserId {
    param(
        [string]$RecordedUserId,

        [Parameter(Mandatory)]
        [string]$CurrentUserId
    )

    if (-not $RecordedUserId) {
        return $CurrentUserId
    }
    if ($RecordedUserId -ne $CurrentUserId) {
        throw "The local deployment state belongs to Entra user $RecordedUserId, but the current user is $CurrentUserId."
    }
    return $RecordedUserId
}

function Get-DemoRoleAssignmentPlan {
    param(
        [object[]]$Assignments,

        [Parameter(Mandatory)]
        [string]$PrincipalId,

        [Parameter(Mandatory)]
        [string]$Role
    )

    $matches = @($Assignments | Where-Object { $_.principal.id -eq $PrincipalId })
    if ($matches.Count -gt 1) {
        throw "Found multiple role assignments for principal $PrincipalId."
    }
    if ($matches.Count -eq 0) {
        return [pscustomobject]@{ Action = 'Create'; AssignmentId = $null }
    }
    if ($matches[0].role -eq $Role) {
        return [pscustomobject]@{ Action = 'None'; AssignmentId = $matches[0].id }
    }
    return [pscustomobject]@{ Action = 'Update'; AssignmentId = $matches[0].id }
}

function Ensure-DemoFabricRoleAssignment {
    param(
        [Parameter(Mandatory)]
        [string]$ResourceUri,

        [Parameter(Mandatory)]
        [hashtable]$Headers,

        [Parameter(Mandatory)]
        [string]$PrincipalId,

        [ValidateSet('User', 'Group', 'ServicePrincipal')]
        [string]$PrincipalType = 'User',

        [Parameter(Mandatory)]
        [string]$Role,

        [Parameter(Mandatory)]
        [string]$ResourceDescription
    )

    $listResponse = Invoke-WebRequest `
        -Headers $Headers `
        -Uri "$ResourceUri/roleAssignments" `
        -SkipHttpErrorCheck
    if ($listResponse.StatusCode -ne 200) {
        throw "Unable to list role assignments for $ResourceDescription. HTTP $($listResponse.StatusCode): $($listResponse.Content)"
    }

    $assignments = ($listResponse.Content | ConvertFrom-Json).value
    $plan = Get-DemoRoleAssignmentPlan `
        -Assignments $assignments `
        -PrincipalId $PrincipalId `
        -Role $Role
    if ($plan.Action -eq 'None') {
        return $plan
    }

    if ($plan.Action -eq 'Create') {
        $uri = "$ResourceUri/roleAssignments"
        $body = @{
            principal = @{
                id = $PrincipalId
                type = $PrincipalType
            }
            role = $Role
        }
        $method = 'Post'
    }
    else {
        $uri = "$ResourceUri/roleAssignments/$($plan.AssignmentId)"
        $body = @{ role = $Role }
        $method = 'Patch'
    }

    $writeResponse = Invoke-WebRequest `
        -Method $method `
        -Headers $Headers `
        -Uri $uri `
        -ContentType 'application/json' `
        -Body ($body | ConvertTo-Json -Depth 5) `
        -SkipHttpErrorCheck
    if ($writeResponse.StatusCode -lt 200 -or $writeResponse.StatusCode -ge 300) {
        throw "Unable to assign $Role on $ResourceDescription to user $PrincipalId. HTTP $($writeResponse.StatusCode): $($writeResponse.Content)"
    }
    return $plan
}

function Get-DemoSqlCmdInstallCommand {
    return 'winget install --id Microsoft.Sqlcmd --exact --accept-source-agreements --accept-package-agreements --silent'
}
