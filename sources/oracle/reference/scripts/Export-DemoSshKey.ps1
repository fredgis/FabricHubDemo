[CmdletBinding()]
param(
    [string]$StatePath = "$env:LOCALAPPDATA\MSFlixOracle\state.json",
    [string]$OutputPath = "$env:TEMP\demo-oracle-ssh.key"
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $StatePath)) {
    throw "Deployment state not found: $StatePath"
}

$state = Get-Content -Raw $StatePath | ConvertFrom-Json
$secureKey = ConvertTo-SecureString $state.protected.linuxSshPrivateKey
$privateKey = [System.Net.NetworkCredential]::new('', $secureKey).Password
$parent = Split-Path -Parent $OutputPath
if ($parent -and -not (Test-Path -LiteralPath $parent)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
}

Set-Content -LiteralPath $OutputPath -Value $privateKey -Encoding utf8NoBOM -NoNewline
if ($env:OS -eq 'Windows_NT') {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls.exe $OutputPath /inheritance:r /grant:r "$($identity):(R,W)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Remove-Item -LiteralPath $OutputPath -Force
        throw 'Unable to restrict access to the exported SSH private key.'
    }
}

Write-Output 'SSH_USERNAME=demoadmin'
Write-Output "SSH_PRIVATE_KEY=$OutputPath"
Write-Output "REMOVE_AFTER_USE=Remove-Item -LiteralPath '$OutputPath'"
