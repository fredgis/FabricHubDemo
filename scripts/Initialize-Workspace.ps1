[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SubscriptionId,
    [Parameter(Mandatory)][string]$TenantId,
    [string]$WorkspaceName = 'MSFlix',
    [string]$CapacityName = 'msflixf16sea'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$account = az account show --subscription $SubscriptionId --output json --only-show-errors | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $account.tenantId -ne $TenantId) { throw 'Incorrect deployment tenant.' }
$token = az account get-access-token --subscription $SubscriptionId `
    --resource https://api.fabric.microsoft.com --query accessToken --output tsv --only-show-errors
if ($LASTEXITCODE -ne 0 -or -not $token) { throw 'Cannot obtain the cached Fabric authorization.' }
$headers = @{ Authorization = "Bearer $token"; 'x-ms-fabric-skill' = 'e2e-medallion-architecture' }
$base = 'https://api.fabric.microsoft.com/v1'
$capacity = $null
for ($attempt = 0; $attempt -lt 18 -and -not $capacity; $attempt++) {
    $capacities = (Invoke-RestMethod -Uri "$base/capacities" -Headers $headers).value
    $capacity = $capacities | Where-Object displayName -eq $CapacityName | Select-Object -First 1
    if (-not $capacity) { Start-Sleep -Seconds 10 }
}
if (-not $capacity -or $capacity.state -ne 'Active') { throw 'The newly provisioned F16 is not yet active/visible in Fabric.' }
$workspaces = (Invoke-RestMethod -Uri "$base/workspaces" -Headers $headers).value
$matches = @($workspaces | Where-Object displayName -eq $WorkspaceName)
if ($matches.Count -gt 1) { throw 'More than one MSFlix workspace found; refusing ambiguous deployment.' }
if ($matches.Count -eq 1) {
    $workspace = $matches[0]
    if ($workspace.capacityId -ne $capacity.id) { throw 'Existing MSFlix workspace belongs to another capacity.' }
} else {
    $body = @{ displayName = $WorkspaceName; capacityId = $capacity.id } | ConvertTo-Json -Compress
    $workspace = Invoke-RestMethod -Method Post -Uri "$base/workspaces" -Headers $headers `
        -ContentType application/json -Body $body
}
$state = @{
    subscriptionId = $SubscriptionId
    tenantId = $TenantId
    location = 'southeastasia'
    resourceGroup = 'rg-msflix-demo-sea'
    capacityId = $capacity.id
    capacityName = $capacity.displayName
    workspaceId = $workspace.id
    workspaceName = $workspace.displayName
    eventHubNamespace = 'fixture'
    eventHubName = 'msflix-events'
}
$directory = Join-Path $root '.state'
New-Item -ItemType Directory -Path $directory -Force | Out-Null
$state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $directory 'deployment.json') -Encoding utf8NoBOM
$state | ConvertTo-Json -Depth 5

