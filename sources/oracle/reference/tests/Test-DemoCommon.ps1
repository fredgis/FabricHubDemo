$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $repoRoot 'scripts\Demo.Common.ps1')

$pwsh = (Get-Command pwsh -ErrorAction Stop).Source

$missingCommandObserved = $false
try {
    Assert-DemoCommand `
        -Name 'command-that-must-not-exist-oracle-fabric-demo' `
        -Remediation 'install-command'
}
catch {
    if ($_.Exception.Message -notmatch 'install-command') {
        throw
    }
    $missingCommandObserved = $true
}
if (-not $missingCommandObserved) {
    throw 'Missing command did not return its remediation.'
}

$failureCommand = {
    & $pwsh -NoProfile -Command "Write-Output 'ResourceNotFound'; exit 3"
}.GetNewClosure()
$failureObserved = $false
try {
    Get-DemoExactNameCount `
        -ListCommand $failureCommand `
        -Name 'demo-bastion' `
        -Description 'Bastion list test' | Out-Null
}
catch {
    if ($_.Exception.Message -notmatch 'ResourceNotFound') {
        throw
    }
    $failureObserved = $true
}
if (-not $failureObserved) {
    throw 'Native command failure was incorrectly treated as resource output.'
}

$missingCommand = {
    & $pwsh -NoProfile -Command '$data = @(@{ name = "other-bastion" }); $data | ConvertTo-Json -Compress; exit 0'
}.GetNewClosure()
$missingCount = Get-DemoExactNameCount `
    -ListCommand $missingCommand `
    -Name 'demo-bastion' `
    -Description 'Missing Bastion test'
if ($missingCount -ne 0) {
    throw "Expected no exact Bastion match, found $missingCount."
}

$existingCommand = {
    & $pwsh -NoProfile -Command '$data = @(@{ name = "demo-bastion" }); $data | ConvertTo-Json -Compress; exit 0'
}.GetNewClosure()
$existingCount = Get-DemoExactNameCount `
    -ListCommand $existingCommand `
    -Name 'demo-bastion' `
    -Description 'Existing Bastion test'
if ($existingCount -ne 1) {
    throw "Expected one exact Bastion match, found $existingCount."
}

$resolvedUserId = Resolve-DemoDeploymentUserId `
    -RecordedUserId $null `
    -CurrentUserId 'user-a'
if ($resolvedUserId -ne 'user-a') {
    throw 'Current deployment user was not recorded.'
}
$sameUserId = Resolve-DemoDeploymentUserId `
    -RecordedUserId 'user-a' `
    -CurrentUserId 'user-a'
if ($sameUserId -ne 'user-a') {
    throw 'Recorded deployment user was not preserved.'
}
$differentUserRejected = $false
try {
    Resolve-DemoDeploymentUserId `
        -RecordedUserId 'user-a' `
        -CurrentUserId 'user-b' | Out-Null
}
catch {
    $differentUserRejected = $true
}
if (-not $differentUserRejected) {
    throw 'A different deployment user was accepted without an explicit state change.'
}

$createPlan = Get-DemoRoleAssignmentPlan `
    -Assignments @() `
    -PrincipalId 'user-a' `
    -Role 'Admin'
if ($createPlan.Action -ne 'Create') {
    throw "Expected Create role plan, found $($createPlan.Action)."
}
$nonePlan = Get-DemoRoleAssignmentPlan `
    -Assignments @([pscustomobject]@{
        id = 'assignment-a'
        principal = [pscustomobject]@{ id = 'user-a' }
        role = 'Admin'
    }) `
    -PrincipalId 'user-a' `
    -Role 'Admin'
if ($nonePlan.Action -ne 'None') {
    throw "Expected None role plan, found $($nonePlan.Action)."
}
$updatePlan = Get-DemoRoleAssignmentPlan `
    -Assignments @([pscustomobject]@{
        id = 'assignment-a'
        principal = [pscustomobject]@{ id = 'user-a' }
        role = 'User'
    }) `
    -PrincipalId 'user-a' `
    -Role 'Owner'
if ($updatePlan.Action -ne 'Update' -or $updatePlan.AssignmentId -ne 'assignment-a') {
    throw 'Existing role assignment was not planned for update.'
}

Write-Output 'DEMO_COMMON_TESTS_VALID=true'
