[CmdletBinding()]
param([Parameter(Mandatory)][string]$SubscriptionId,[string]$ResourceGroupName='rg-msflix-demo-sea')
$ErrorActionPreference='Stop'
& "$PSScriptRoot\Generate-ReferenceMigration.ps1"
foreach ($file in Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'migrations\batches') -Filter '*.sh' | Sort-Object Name) {
    $output = az vm run-command invoke --subscription $SubscriptionId --resource-group $ResourceGroupName `
        --name msflix-oracle-vm --command-id RunShellScript --scripts "@$($file.FullName)" `
        --query 'value[0].message' --output tsv --only-show-errors
    if($LASTEXITCODE-ne0-or ($output -join "`n") -notmatch 'MSFLIX_BATCH_[0-9]+=COMMITTED') {
        throw "Oracle batch $($file.Name) was not explicitly confirmed: $output"
    }
    "ORACLE_CATALOG_BATCH=$($file.Name);COMMITTED=true"
}
az vm run-command invoke --subscription $SubscriptionId --resource-group $ResourceGroupName `
    --name msflix-oracle-vm --command-id RunShellScript `
    --scripts "@$PSScriptRoot\Validate-ExistingDatabase.sh" --query 'value[0].message' --output tsv --only-show-errors
if($LASTEXITCODE-ne0){throw 'Oracle final count validation failed.'}
