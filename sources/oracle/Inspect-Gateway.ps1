$ErrorActionPreference = 'Stop'
Write-Output ('POWERSHELL_7_EXISTS=' + (Test-Path 'C:\Program Files\PowerShell\7\pwsh.exe'))
$service = Get-Service -Name PBIEgwService -ErrorAction SilentlyContinue
if ($service) { Write-Output ('GATEWAY_SERVICE=' + $service.Status) }
else { Write-Output 'GATEWAY_SERVICE=NotInstalled' }
$modulePath = 'C:\Program Files\PowerShell\Modules\DataGateway'
Write-Output ('GATEWAY_MODULE_EXISTS=' + (Test-Path $modulePath))

