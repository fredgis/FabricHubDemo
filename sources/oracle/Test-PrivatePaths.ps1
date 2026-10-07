[CmdletBinding()]
param(
    [Parameter(Mandatory)][guid]$WorkspaceId,
    [Parameter(Mandatory)][string]$OracleAddress,
    [Parameter(Mandatory)][string]$WorkspacePrivateAddress,
    [Parameter(Mandatory)][string]$OneLakePrivateAddress,
    [string]$FabricAccessToken
)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) {
    $arguments = @(
        '-NoLogo', '-NoProfile', '-File', $PSCommandPath,
        '-WorkspaceId', $WorkspaceId.ToString(),
        '-OracleAddress', $OracleAddress,
        '-WorkspacePrivateAddress', $WorkspacePrivateAddress,
        '-OneLakePrivateAddress', $OneLakePrivateAddress
    )
    if ($FabricAccessToken) {
        $arguments += @('-FabricAccessToken', $FabricAccessToken)
    }
    & 'C:\Program Files\PowerShell\7\pwsh.exe' @arguments
    exit $LASTEXITCODE
}
$workspaceKey = $WorkspaceId.ToString('N')
$prefix = $workspaceKey + '.z' + $workspaceKey.Substring(0, 2)
$checks = @(
    @{ Name = 'Oracle'; Host = $OracleAddress; Address = $OracleAddress; Port = 1521 },
    @{ Name = 'FabricWorkspace'; Host = "$prefix.w.api.fabric.microsoft.com"; Address = $WorkspacePrivateAddress; Port = 443 },
    @{ Name = 'OneLake'; Host = "$prefix.onelake.fabric.microsoft.com"; Address = $OneLakePrivateAddress; Port = 443 }
)
foreach ($check in $checks) {
    $addresses = @([Net.Dns]::GetHostAddresses($check.Host) |
        Where-Object AddressFamily -eq ([Net.Sockets.AddressFamily]::InterNetwork) |
        ForEach-Object IPAddressToString)
    if ($addresses.Count -ne 1 -or $addresses[0] -ne $check.Address) {
        throw "$($check.Name) DNS mismatch: expected $($check.Address), resolved $($addresses -join ',')."
    }
    $connection = [Net.Sockets.TcpClient]::new()
    try {
        if (-not $connection.ConnectAsync($check.Host, $check.Port).Wait(10000)) {
            throw "$($check.Name) private TCP connection timed out."
        }
        if (-not $connection.Connected) {
            throw "$($check.Name) private TCP connection failed."
        }
    } finally {
        $connection.Dispose()
    }
    [pscustomobject]@{
        check = $check.Name
        hostname = $check.Host
        privateAddress = $addresses[0]
        port = $check.Port
        connected = $true
    } | ConvertTo-Json -Compress
}
if ($FabricAccessToken) {
    $arguments = @{
        Uri = "https://$prefix.w.api.fabric.microsoft.com/v1/workspaces/$WorkspaceId"
        Headers = @{
            Authorization = "Bearer $FabricAccessToken"
            'x-ms-fabric-skill' = 'spark-cli'
        }
        Method = 'Get'
        TimeoutSec = 60
    }
    $workspace = Invoke-RestMethod @arguments
    if ($workspace.id -ne $WorkspaceId.ToString() -or $workspace.displayName -ne 'MSFlix') {
        throw 'Private API did not return the authorized MSFlix workspace.'
    }
    [pscustomobject]@{
        check = 'AuthenticatedPrivateWorkspace'
        workspaceId = $workspace.id
        displayName = $workspace.displayName
        verified = $true
    } | ConvertTo-Json -Compress
}
$service = Get-Service PBIEgwService
if ($service.Status -ne 'Running') {
    throw 'The installed gateway service is not running.'
}
Import-Module DataGateway.Profile -ErrorAction Stop
[pscustomobject]@{
    check = 'GatewayAuthenticationContract'
    service = $service.Status.ToString()
    authenticationParameterSets = @((Get-Command Connect-DataGatewayServiceAccount).ParameterSets |
        ForEach-Object { @{ name = $_.Name; parameters = @($_.Parameters.Name) } })
} | ConvertTo-Json -Depth 5 -Compress
