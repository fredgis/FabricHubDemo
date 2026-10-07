[CmdletBinding()]
param([Parameter(Mandatory)][string]$SourceRepository)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$destination = Join-Path $root 'sources\oracle\reference'
if (Test-Path -LiteralPath $destination) {
    throw 'Oracle reference already imported; do not overwrite source changes.'
}
if (-not (Test-Path -LiteralPath (Join-Path $SourceRepository 'LICENSE'))) {
    throw 'The Oracle reference must include its upstream license.'
}
New-Item -ItemType Directory -Path $destination -Force | Out-Null
foreach ($name in @('infra','scripts','oracle','fabric','tests','LICENSE','README.md')) {
    Copy-Item -LiteralPath (Join-Path $SourceRepository $name) -Destination $destination -Recurse
}

# The imported environment must never read or mutate the upstream local state.
Get-ChildItem -LiteralPath $destination -Recurse -File |
    Where-Object Extension -in '.ps1','.bicep','.sh' |
    ForEach-Object {
        $content = [IO.File]::ReadAllText($_.FullName)
        $content = $content.Replace('OracleToFabricDemo','MSFlixOracle')
        $content = $content.Replace('FGI-ORACLE','MSFlix')
        $content = $content.Replace('Demo Oracle Gateway','MSFlix Oracle Gateway')
        $content = $content.Replace('Demo Oracle Connection','MSFlix Oracle Connection')
        $content = $content.Replace('DemoOracleMirror','MSFlix_OracleMirror')
        $content = $content.Replace('DemoLakehouse','MSFlix_Raw')
        $content = $content.Replace('centralus','southeastasia')
        $content = $content.Replace('Standard_D2as_v7','Standard_D2s_v7')
        $content = $content.Replace('Standard_D4as_v7','Standard_D4s_v7')
        [IO.File]::WriteAllText($_.FullName,$content,[Text.UTF8Encoding]::new($false))
    }
Write-Output "ORACLE_REFERENCE_IMPORTED=$destination"
