[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$FabricConfig,
    [Parameter(Mandatory)][string]$VmResourceId,
    [Parameter(Mandatory)][string]$OperationalItemId,
    [Parameter(Mandatory)][string]$OperationalServer,
    [Parameter(Mandatory)][string]$OperationalDatabase,
    [Parameter(Mandatory)][string]$GraphId,
    [string]$StateDirectory = '.state/demo-automation',
    [switch]$InstallPrerequisites,
    [switch]$Start
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
Push-Location $repo
try {
    $live = Get-Content $FabricConfig -Raw | ConvertFrom-Json
    $configPath = Join-Path $StateDirectory 'config.json'
    python -m scripts.demo_prepare --fabric-config $FabricConfig --vm-id $VmResourceId `
        --operational-item $OperationalItemId --server $OperationalServer --database $OperationalDatabase `
        --graph-id $GraphId --output $configPath --grant
    if ($LASTEXITCODE -ne 0) { throw 'Binding/permission preparation failed' }
    $config = Get-Content $configPath -Raw | ConvertFrom-Json
    $resourceGroup = ($VmResourceId -split '/')[4]
    az deployment group create --subscription $live.subscription_id --resource-group $resourceGroup `
        --name "msflix-demo-automation-$($live.environment)" --template-file infra/demo-automation.bicep `
        --parameters "environment=$($live.environment)" "namespaceName=$($config.publisher.namespace)" `
        "eventHubName=$($config.publisher.topic)" "publisherPrincipalId=$($config.managed_identity_principal_id)" `
        --query 'properties.outputs' --output json
    if ($LASTEXITCODE -ne 0) { throw 'Topic-scoped sender grant failed' }
    if ($InstallPrerequisites) {
        python -m scripts.demo_vm --tenant $live.tenant_id --vm-id $VmResourceId `
            --script services/publisher/install-prerequisites.sh `
            --state (Join-Path $StateDirectory 'prerequisites-job.json') --timeout 600
        if ($LASTEXITCODE -ne 0) { throw 'VM prerequisite installation incomplete; resume saved command' }
    }
    $arguments = @('-m', 'scripts.demo_deploy', '--config', $configPath, '--state', $StateDirectory)
    if ($Start) { $arguments += '--start' }
    python @arguments
    if ($LASTEXITCODE -ne 0) { throw 'VM deployment incomplete; inspect saved command, do not resubmit blindly' }
} finally {
    Pop-Location
}
