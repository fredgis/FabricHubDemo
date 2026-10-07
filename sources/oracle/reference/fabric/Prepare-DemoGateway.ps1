[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$workDir = Join-Path $env:TEMP "demo-gateway-$([guid]::NewGuid().ToString('N'))"
$powerShellMsi = Join-Path $workDir 'PowerShell.msi'
$gatewayInstaller = Join-Path $workDir 'GatewayInstall.exe'
$gatewayInstallLog = Join-Path $env:WINDIR 'Temp\OnPremisesDataGateway-Install.log'
$gatewayInstallerUrl = 'https://go.microsoft.com/fwlink/?LinkId=2116849&clcid=0x409'
$pwsh = 'C:\Program Files\PowerShell\7\pwsh.exe'

function Install-PowerShell {
    if (Test-Path $pwsh) {
        return
    }

    $headers = @{ 'User-Agent' = 'MSFlixOracle' }
    $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/PowerShell/PowerShell/releases/latest' -Headers $headers
    $asset = $release.assets |
        Where-Object name -Match '^PowerShell-[0-9.]+-win-x64\.msi$' |
        Select-Object -First 1
    if (-not $asset) {
        throw 'Unable to find the current PowerShell x64 MSI.'
    }

    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $powerShellMsi -Headers $headers
    $process = Start-Process msiexec.exe `
        -ArgumentList '/i', "`"$powerShellMsi`"", '/qn', '/norestart', 'ADD_EXPLORER_CONTEXT_MENU_OPENPOWERSHELL=0', 'ENABLE_PSREMOTING=0' `
        -Wait `
        -PassThru
    if ($process.ExitCode -notin 0, 3010) {
        throw "PowerShell installation failed with exit code $($process.ExitCode)."
    }
}

function Install-Gateway {
    $gatewayService = Get-Service -Name PBIEgwService -ErrorAction SilentlyContinue
    & $pwsh -NoLogo -NoProfile -NonInteractive -Command @'
$ErrorActionPreference = 'Stop'
Set-PSRepository -Name PSGallery -InstallationPolicy Trusted
Install-Module DataGateway -Scope AllUsers -Force -AllowClobber
'@
    if ($LASTEXITCODE -ne 0) {
        throw 'DataGateway PowerShell module installation failed.'
    }

    if (-not $gatewayService) {
        Invoke-WebRequest -Uri $gatewayInstallerUrl -OutFile $gatewayInstaller
        $process = Start-Process $gatewayInstaller `
            -ArgumentList '/install', '/quiet', '/norestart', '/accept_eula', '/log', "`"$gatewayInstallLog`"" `
            -Wait `
            -PassThru
        if ($process.ExitCode -notin 0, 3010) {
            throw "On-premises data gateway installation failed with exit code $($process.ExitCode). See $gatewayInstallLog."
        }
    }

    if (-not (Get-Service -Name PBIEgwService -ErrorAction SilentlyContinue)) {
        throw 'The on-premises data gateway service was not installed.'
    }
}

function Enable-BundledOracleDriver {
    $gatewayRoot = 'C:\Program Files\On-premises data gateway'
    $driverSource = Join-Path $gatewayRoot 'FabricIntegrationRuntime\5.0\Gateway\msdiDrivers\Oracle\1.1.0.0\Oracle.ManagedDataAccess.dll'
    $workerDirectory = Join-Path $gatewayRoot 'FabricIntegrationRuntime\5.0\Shared'
    $driverTarget = Join-Path $workerDirectory 'Oracle.ManagedDataAccess.dll'
    $workerConfig = Join-Path $workerDirectory 'FabricPipelineWorker.exe.config'

    if (-not (Test-Path $driverSource)) {
        throw "Bundled Oracle driver not found: $driverSource"
    }
    if (-not (Test-Path $workerConfig)) {
        throw "Fabric pipeline worker configuration not found: $workerConfig"
    }

    $service = Get-Service -Name PBIEgwService
    if ($service.Status -ne 'Stopped') {
        Stop-Service -Name PBIEgwService -Force
        $service.WaitForStatus('Stopped', [TimeSpan]::FromMinutes(2))
    }

    try {
        Copy-Item -Path $driverSource -Destination $driverTarget -Force

        [xml]$configuration = Get-Content -Raw $workerConfig
        $factories = $configuration.SelectSingleNode('/configuration/system.data/DbProviderFactories')
        if (-not $factories) {
            throw 'DbProviderFactories section is missing from FabricPipelineWorker.exe.config.'
        }

        $existing = $factories.SelectNodes('add[@invariant="Oracle.ManagedDataAccess.Client"]')
        foreach ($node in @($existing)) {
            $factories.RemoveChild($node) | Out-Null
        }

        $provider = $configuration.CreateElement('add')
        $provider.SetAttribute('name', 'ODP.NET, Managed Driver')
        $provider.SetAttribute('invariant', 'Oracle.ManagedDataAccess.Client')
        $provider.SetAttribute('description', 'Oracle Data Provider for .NET, Managed Driver')
        $provider.SetAttribute(
            'type',
            'Oracle.ManagedDataAccess.Client.OracleClientFactory, Oracle.ManagedDataAccess, Version=4.122.23.1, Culture=neutral, PublicKeyToken=89b483f429c47342'
        )
        $factories.AppendChild($provider) | Out-Null

        $backup = "$workerConfig.demo-backup"
        if (-not (Test-Path $backup)) {
            Copy-Item -Path $workerConfig -Destination $backup
        }
        $configuration.Save($workerConfig)
    }
    finally {
        Start-Service -Name PBIEgwService
        $service.WaitForStatus('Running', [TimeSpan]::FromMinutes(2))
    }
}

New-Item -ItemType Directory -Path $workDir | Out-Null

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Install-PowerShell
    Install-Gateway
    Enable-BundledOracleDriver

    $gatewayService = Get-Service -Name PBIEgwService
    $moduleVersion = & $pwsh -NoLogo -NoProfile -NonInteractive -Command "(Get-Module -ListAvailable DataGateway | Sort-Object Version -Descending | Select-Object -First 1).Version.ToString()"

    Write-Output "POWERSHELL_VERSION=$(& $pwsh -NoLogo -NoProfile -Command '$PSVersionTable.PSVersion.ToString()')"
    Write-Output 'ORACLE_DRIVER=built-in-managed-odpnet'
    Write-Output "GATEWAY_MODULE_VERSION=$moduleVersion"
    Write-Output "GATEWAY_SERVICE_STATUS=$($gatewayService.Status)"
}
finally {
    if (Test-Path -LiteralPath $workDir) {
        Remove-Item -LiteralPath $workDir -Recurse -Force
    }
}
