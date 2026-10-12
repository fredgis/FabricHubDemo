$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$source = Join-Path $root 'scripts\Initialize-Workspace.ps1'
$tokens = $null
$errors = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Workspace initialization script failed to parse.' }

$sandbox = Join-Path ([System.IO.Path]::GetTempPath()) ('msflix-initialization-' + [guid]::NewGuid())
$null = New-Item -ItemType Directory -Path (Join-Path $sandbox 'scripts'), (Join-Path $sandbox 'fabric')
$scriptPath = Join-Path $sandbox 'scripts\Initialize-Workspace.ps1'
$policyPath = Join-Path $sandbox 'fabric\target-policy.json'
Copy-Item -LiteralPath $source -Destination $scriptPath
$probe = @{ calls = 0 }
function az { $probe.calls++; throw 'OFFLINE_AZ_STOP' }
function Invoke-RestMethod { throw 'An unexpected HTTP call was attempted.' }

$cases = @(
    @{ json = $null; calls = 0 },
    @{ json = '{'; calls = 0 },
    @{ json = '{}'; calls = 0 },
    @{ json = '{"event_hub_namespace":null}'; calls = 0 },
    @{ json = '{"event_hub_namespace":42}'; calls = 0 },
    @{ json = '{"event_hub_namespace":"invalid/namespace"}'; calls = 0 },
    @{ json = '{"event_hub_namespace":"-invalid"}'; calls = 0 },
    @{ json = '{"event_hub_namespace":"fixture-namespace"}'; calls = 1 }
)
try {
    foreach ($case in $cases) {
        $probe.calls = 0
        if (Test-Path -LiteralPath $policyPath) { Remove-Item -LiteralPath $policyPath }
        if ($null -ne $case.json) { Set-Content -LiteralPath $policyPath -Value $case.json -Encoding utf8NoBOM }
        $caught = $null
        try {
            & $scriptPath -SubscriptionId '00000000-0000-4000-8000-000000000702' `
                -TenantId '00000000-0000-4000-8000-000000000703'
        } catch { $caught = $_.Exception.Message }
        if (-not $caught) { throw 'Initialization unexpectedly completed.' }
        if ($probe.calls -ne $case.calls) { throw 'Initialization did not reject the private target before Azure access.' }
        if ($case.calls -eq 1 -and $caught -ne 'OFFLINE_AZ_STOP') { throw 'A valid fixture did not reach the mocked Azure boundary.' }
    }
    'Workspace initialization: parser and 8 offline policy cases passed.'
} finally {
    Remove-Item -LiteralPath $sandbox -Recurse -Force
}
