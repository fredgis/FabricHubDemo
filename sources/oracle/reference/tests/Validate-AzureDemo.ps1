[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$SubscriptionId,

    [string]$ResourceGroupName = 'MSFlix'
)

$ErrorActionPreference = 'Stop'
az account set --subscription $SubscriptionId

$failures = [System.Collections.Generic.List[string]]::new()
$vms = az vm list --subscription $SubscriptionId --resource-group $ResourceGroupName --show-details --output json | ConvertFrom-Json
if (@($vms).Count -ne 2) {
    $failures.Add("Expected two VMs, found $(@($vms).Count).")
}
foreach ($vm in @($vms)) {
    if ($vm.publicIps) {
        $failures.Add("VM $($vm.name) has a public IP.")
    }
    if ($vm.powerState -ne 'VM running') {
        $failures.Add("VM $($vm.name) is not running.")
    }
}

$bastion = az network bastion show `
    --subscription $SubscriptionId `
    --resource-group $ResourceGroupName `
    --name demo-bastion `
    --output json | ConvertFrom-Json
if ($bastion.sku.name -ne 'Developer') {
    $failures.Add("Bastion SKU is $($bastion.sku.name), expected Developer.")
}
if (@($bastion.ipConfigurations).Count -ne 0) {
    $failures.Add('Bastion Developer unexpectedly has a dedicated IP configuration.')
}
$bastionIpRuleCount = @($bastion.networkAcls.ipRules).Count
if ($bastionIpRuleCount -ne 0) {
    $failures.Add("Bastion Developer has $bastionIpRuleCount client IP ACL rule(s), expected none.")
}

$natPublicIps = az network public-ip list `
    --subscription $SubscriptionId `
    --resource-group $ResourceGroupName `
    --query "[?name=='demo-egress-pip']" `
    --output json | ConvertFrom-Json
if (@($natPublicIps).Count -ne 1) {
    $failures.Add('Expected one outbound NAT public IP.')
}

$keyVault = az keyvault list `
    --subscription $SubscriptionId `
    --resource-group $ResourceGroupName `
    --query '[0]' `
    --output json | ConvertFrom-Json
if ($keyVault.properties.publicNetworkAccess -ne 'Disabled') {
    $failures.Add('Key Vault public network access is not disabled.')
}
if ($keyVault.properties.privateEndpointConnections[0].privateLinkServiceConnectionState.status -ne 'Approved') {
    $failures.Add('Key Vault Private Endpoint is not approved.')
}

$vnet = az network vnet show `
    --subscription $SubscriptionId `
    --resource-group $ResourceGroupName `
    --name demo-oracle-vnet `
    --output json | ConvertFrom-Json
$expectedSubnets = @(
    'snet-demo-oracle',
    'snet-demo-gateway',
    'snet-demo-private-endpoints'
)
foreach ($subnet in $expectedSubnets) {
    if ($subnet -notin @($vnet.subnets.name)) {
        $failures.Add("Missing subnet $subnet.")
    }
}

if ($failures.Count -gt 0) {
    $failures | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Output 'AZURE_DEMO_VALID=true'
Write-Output "VM_COUNT=$(@($vms).Count)"
Write-Output 'WORKLOAD_PUBLIC_IP_COUNT=0'
Write-Output 'BASTION_SKU=Developer'
Write-Output "BASTION_CLIENT_IP_RULE_COUNT=$bastionIpRuleCount"
Write-Output 'NAT_PUBLIC_IP_COUNT=1'
Write-Output 'KEY_VAULT_PUBLIC_ACCESS=Disabled'
