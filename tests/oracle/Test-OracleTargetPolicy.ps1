[CmdletBinding()]
param([string]$PrivateLiteralManifest)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$oracleRoot = Join-Path $PSScriptRoot '..\..\sources\oracle'
. (Join-Path $oracleRoot 'Oracle-TargetPolicy.ps1')
$script:checks = 0

function Assert-PolicyRejected {
    param([string]$Path, [string]$Name)

    $failure = $null
    try { Read-OracleTargetPolicy -Path $Path | Out-Null }
    catch { $failure = $_.Exception.Message }
    if ($null -eq $failure -or $failure -notlike 'Oracle target policy*') {
        throw "Policy rejection failed: $Name"
    }
    $script:checks++
}

function Get-IsolatedGuard {
    param([object]$Ast, [string]$Message)

    $matches = @($Ast.FindAll({
        param($node)
        $node -is [Management.Automation.Language.IfStatementAst] -and
            $node.Extent.Text.Contains("throw '$Message'")
    }, $true))
    if ($matches.Count -ne 1 -or
        @($matches[0].FindAll({ param($node) $node -is [Management.Automation.Language.CommandAst] }, $true)).Count -ne 0) {
        throw "Expected one command-free approval guard: $Message"
    }
    return [scriptblock]::Create($matches[0].Extent.Text)
}

function Assert-GuardResult {
    param([object]$Guard, [hashtable]$Values, [bool]$Reject, [string]$Name)

    $failure = $null
    try {
        & {
            foreach ($entry in $Values.GetEnumerator()) { Set-Variable -Name $entry.Key -Value $entry.Value }
            & $Guard.Code
        }
    }
    catch { $failure = $_.Exception.Message }
    if (($Reject -and $failure -cne $Guard.Message) -or (-not $Reject -and $null -ne $failure)) {
        throw "Approval guard failed: $Name"
    }
    $script:checks++
}

$scripts = @{
    deploy = 'Deploy-ReferenceMirror.ps1'
    register = 'Register-Gateway.ps1'
    repair = 'Repair-CatalogEncoding.ps1'
    configure = 'reference\fabric\Configure-DemoFabric.ps1'
}
$asts = @{}
foreach ($entry in $scripts.GetEnumerator()) {
    $parseErrors = $null
    $asts[$entry.Key] = [Management.Automation.Language.Parser]::ParseFile(
        (Join-Path $oracleRoot $entry.Value), [ref]$null, [ref]$parseErrors)
    if ($parseErrors.Count) { throw "Oracle script parse failed: $($entry.Value)" }
    $statements = $asts[$entry.Key].EndBlock.Statements
    $relativeHelper = if ($entry.Key -eq 'configure') { '..\..\Oracle-TargetPolicy.ps1' } else { 'Oracle-TargetPolicy.ps1' }
    if ($statements[0].Extent.Text -cne '$ErrorActionPreference = ''Stop''' -or
        $statements[1].Extent.Text -cne ". (Join-Path `$PSScriptRoot '$relativeHelper')" -or
        $statements[2].Extent.Text -cne '$targetPolicy = Read-OracleTargetPolicy') {
        throw "Policy must load before state access or external commands: $($entry.Value)"
    }
    $script:checks++
}
$guardDefinitions = @{
    deploy = @('deploy', 'Refusing Oracle reference deployment outside the approved MSFlix environment.')
    state = @('register', 'Gateway state is not the approved environment.')
    register = @('register', 'Refusing gateway registration outside the explicitly approved dedicated MSFlix VM.')
    registration = @('register', 'Refusing an unverified or unrelated gateway registration.')
    repair = @('repair', 'Refusing to repair catalog data outside the approved MSFlix subscription.')
    configure = @('configure', 'Refusing Oracle Fabric configuration outside the explicitly approved MSFlix environment.')
    gateway = @('configure', 'Refusing to use or modify an unrelated gateway.')
}
$guards = @{}
foreach ($entry in $guardDefinitions.GetEnumerator()) {
    $guards[$entry.Key] = @{
        Code = Get-IsolatedGuard -Ast $asts[$entry.Value[0]] -Message $entry.Value[1]
        Message = $entry.Value[1]
    }
}

function Test-TargetGuards {
    param([object]$Policy, [hashtable]$Original)

    $otherId = [guid]::NewGuid().ToString('D')
    $allowedGatewayId = [guid]::NewGuid().ToString('D')
    function New-ApprovedValues {
        return @{
            targetPolicy = $Policy
            SubscriptionId = $Original.subscriptionId
            TenantId = $Original.tenantId
            ResourceGroupName = 'rg-msflix-demo-sea'
            WorkspaceName = 'MSFlix'
            GatewayName = 'MSFlix Oracle Gateway Fabric'
            ConnectionName = 'MSFlix Oracle Connection'
            MirrorName = 'MSFlix_OracleMirror'
            LakehouseName = 'MSFlixRaw'
            OracleServer = '10.60.1.4:1521/FREEPDB1'
            state = [pscustomobject]@{
                subscriptionId = $Original.subscriptionId
                tenantId = $Original.tenantId
                gatewayVmName = 'msflix-fabric-gateway-vm'
                fabric = [pscustomobject]@{ gatewayId = $allowedGatewayId }
            }
            registration = [pscustomobject]@{
                registered = $true
                gatewayName = 'MSFlix Oracle Gateway Fabric'
                gatewayId = $allowedGatewayId
            }
            gateway = [pscustomobject]@{ id = $allowedGatewayId }
        }
    }
    foreach ($entry in $guards.GetEnumerator()) {
        Assert-GuardResult -Guard $entry.Value -Values (New-ApprovedValues) -Reject $false -Name "$($entry.Key) approved"
    }
    $cases = @(
        @('deploy', @{ SubscriptionId = $otherId }),
        @('deploy', @{ TenantId = $otherId }),
        @('deploy', @{ ResourceGroupName = 'unapproved-resource-group' }),
        @('state', @{ 'state.subscriptionId' = $otherId }),
        @('state', @{ 'state.tenantId' = $otherId }),
        @('register', @{ SubscriptionId = $otherId; 'state.subscriptionId' = $otherId }),
        @('register', @{ TenantId = $otherId; 'state.tenantId' = $otherId }),
        @('register', @{ ResourceGroupName = 'unapproved-resource-group' }),
        @('register', @{ 'state.gatewayVmName' = 'unapproved-vm' }),
        @('registration', @{ 'registration.registered' = $false }),
        @('registration', @{ 'registration.gatewayName' = 'unapproved-gateway' }),
        @('registration', @{ 'registration.gatewayId' = $Original.prohibitedGatewayId }),
        @('repair', @{ SubscriptionId = $otherId }),
        @('configure', @{ SubscriptionId = $otherId; 'state.subscriptionId' = $otherId }),
        @('configure', @{ 'state.subscriptionId' = $otherId }),
        @('configure', @{ 'state.tenantId' = $otherId }),
        @('configure', @{ WorkspaceName = 'unapproved-workspace' }),
        @('configure', @{ GatewayName = 'unapproved-gateway' }),
        @('configure', @{ ConnectionName = 'unapproved-connection' }),
        @('configure', @{ MirrorName = 'unapproved-mirror' }),
        @('configure', @{ LakehouseName = 'unapproved-lakehouse' }),
        @('configure', @{ OracleServer = 'unapproved-oracle-server' }),
        @('gateway', @{ 'gateway.id' = $otherId }),
        @('gateway', @{ 'gateway.id' = $Original.prohibitedGatewayId; 'state.fabric.gatewayId' = $Original.prohibitedGatewayId })
    )
    foreach ($case in $cases) {
        $values = New-ApprovedValues
        foreach ($change in $case[1].GetEnumerator()) {
            $parts = $change.Key.Split('.')
            $target = $values
            for ($index = 0; $index -lt $parts.Count - 1; $index++) { $target = $target.($parts[$index]) }
            $target.($parts[-1]) = $change.Value
        }
        Assert-GuardResult -Guard $guards[$case[0]] -Values $values -Reject $true -Name "$($case[0]) mismatch"
    }
}

$fixtureDirectory = Join-Path $PSScriptRoot ".target-policy-tests-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $fixtureDirectory | Out-Null
try {
    $fixturePath = Join-Path $fixtureDirectory 'policy.json'
    $original = @{
        subscriptionId = [guid]::NewGuid().ToString('D')
        tenantId = [guid]::NewGuid().ToString('D')
        prohibitedGatewayId = [guid]::NewGuid().ToString('D')
    }
    $original | ConvertTo-Json | Set-Content -LiteralPath $fixturePath -Encoding utf8NoBOM
    $policy = Read-OracleTargetPolicy -Path $fixturePath
    foreach ($entry in $original.GetEnumerator()) {
        if ($policy.($entry.Key) -cne $entry.Value) { throw 'Approved policy identifiers changed during reading.' }
        $script:checks++
    }
    Test-TargetGuards -Policy $policy -Original $original
    Assert-PolicyRejected -Path (Join-Path $fixtureDirectory 'missing.json') -Name 'missing file'
    Assert-PolicyRejected -Path $fixtureDirectory -Name 'directory instead of file'
    Assert-PolicyRejected -Path (Join-Path $oracleRoot 'target-policy.example.json') -Name 'unconfigured example'
    $validJson = $original | ConvertTo-Json -Compress
    $jsonPrefix = $validJson.Substring(0, $validJson.Length - 1)
    $invalidDocuments = @(
        '', '{invalid', 'null', '[]', '{}', '"not an object"', ('[' + $validJson + ']'),
        ($jsonPrefix + ',}'), ('/* invalid JSON comment */' + $validJson),
        ($jsonPrefix + ',"tenantId":"' + [guid]::NewGuid().ToString('D') + '"}'),
        ($jsonPrefix + ',"TenantId":"' + [guid]::NewGuid().ToString('D') + '"}'),
        ($jsonPrefix + ',"unexpectedField":"not approved"}')
    )
    foreach ($invalidJson in $invalidDocuments) {
        Set-Content -LiteralPath $fixturePath -Value $invalidJson -Encoding utf8NoBOM
        Assert-PolicyRejected -Path $fixturePath -Name 'invalid JSON or root shape'
    }
    foreach ($name in @('subscriptionId', 'tenantId', 'prohibitedGatewayId')) {
        $invalid = $original.Clone()
        $invalid.Remove($name)
        $invalid | ConvertTo-Json | Set-Content -LiteralPath $fixturePath -Encoding utf8NoBOM
        Assert-PolicyRejected -Path $fixturePath -Name "$name missing"
        foreach ($value in @($null, '', 123, @($original[$name]), '<unconfigured>', [guid]::Empty.ToString('D'), (' ' + $original[$name]))) {
            $invalid = $original.Clone()
            $invalid[$name] = $value
            $invalid | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $fixturePath -Encoding utf8NoBOM
            Assert-PolicyRejected -Path $fixturePath -Name "$name invalid"
        }
    }
    if ($PrivateLiteralManifest) {
        $entries = @(Get-Content -LiteralPath $PrivateLiteralManifest -Raw | ConvertFrom-Json)
        $original = @{}
        foreach ($name in @('subscriptionId', 'tenantId', 'prohibitedGatewayId')) {
            $entry = @($entries | Where-Object localPolicyKey -eq $name)
            if ($entry.Count -ne 1) { throw 'Private literal manifest is incomplete or ambiguous.' }
            $original[$name] = $entry[0].literal
        }
        $policy = Read-OracleTargetPolicy
        foreach ($entry in $original.GetEnumerator()) {
            if ($policy.($entry.Key) -cne $entry.Value) { throw 'Local policy differs from the preserved original identifiers.' }
            $script:checks++
        }
        Test-TargetGuards -Policy $policy -Original $original
    }
}
finally {
    Remove-Item -LiteralPath $fixtureDirectory -Recurse -Force
}
"ORACLE_TARGET_POLICY_TESTS=$script:checks passed"
