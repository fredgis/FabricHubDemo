[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$OracleHost,

    [int]$OraclePort = 1521,
    [int]$Attempts = 12,
    [int]$DelaySeconds = 10
)

$ErrorActionPreference = 'Stop'

$sourceIp = (
    Get-NetIPConfiguration |
        Where-Object IPv4DefaultGateway |
        Select-Object -First 1 -ExpandProperty IPv4Address
).IPAddress

for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
    $reachable = Test-NetConnection `
        -ComputerName $OracleHost `
        -Port $OraclePort `
        -InformationLevel Quiet `
        -WarningAction SilentlyContinue
    if ($reachable) {
        Write-Output 'ORACLE_TCP_VALID=true'
        Write-Output "ORACLE_TCP_SOURCE=$sourceIp"
        Write-Output "ORACLE_TCP_DESTINATION=$OracleHost`:$OraclePort"
        exit 0
    }
    if ($attempt -lt $Attempts) {
        Start-Sleep -Seconds $DelaySeconds
    }
}

throw @"
Gateway source $sourceIp cannot reach Oracle at $OracleHost`:$OraclePort.
Verify the Azure NSG allows the gateway subnet to the Oracle private IP on TCP $OraclePort.
On Oracle Linux, run:
sudo firewall-cmd --add-port=$OraclePort/tcp
sudo firewall-cmd --permanent --add-port=$OraclePort/tcp
sudo firewall-cmd --query-port=$OraclePort/tcp
"@
