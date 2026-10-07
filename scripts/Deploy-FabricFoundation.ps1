[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SubscriptionId,
    [Parameter(Mandatory)][string]$TenantId,
    [string]$ResourceGroupName = 'rg-msflix-demo-sea',
    [string]$Location = 'southeastasia',
    [string]$CapacityName = 'msflixf16sea'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$account = az account show --subscription $SubscriptionId --output json --only-show-errors | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $account.tenantId -ne $TenantId) {
    throw 'Azure account does not match the explicitly approved tenant/subscription.'
}
az group create --subscription $SubscriptionId --name $ResourceGroupName --location $Location `
    --tags application=MSFlix environment=demo owner=fabricroadshow --output none --only-show-errors
if ($LASTEXITCODE -ne 0) { throw 'MSFlix resource group creation failed.' }
az deployment group create --subscription $SubscriptionId --resource-group $ResourceGroupName `
    --name msflix-fabric-foundation --template-file (Join-Path $root 'infra\fabric.bicep') `
    --parameters "administrator=$($account.user.name)" "location=$Location" "capacityName=$CapacityName" --output none --only-show-errors
if ($LASTEXITCODE -ne 0) { throw 'Fabric/Event Hubs foundation deployment failed; inspect the deployment operations.' }
az deployment group show --subscription $SubscriptionId --resource-group $ResourceGroupName `
    --name msflix-fabric-foundation --query properties.outputs --output json --only-show-errors
if ($LASTEXITCODE -ne 0) { throw 'Unable to read the deployed foundation outputs.' }
