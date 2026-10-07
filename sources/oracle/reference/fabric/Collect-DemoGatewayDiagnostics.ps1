$ErrorActionPreference = 'Stop'

$root = 'C:\Windows\ServiceProfiles\PBIEgwService\AppData\Local\Microsoft\On-premises data gateway'
Write-Output "SERVICE_STATUS=$((Get-Service PBIEgwService).Status)"

$logs = Get-ChildItem $root -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Length -gt 0 -and $_.Extension -In '.log', '.txt' } |
    Sort-Object LastWriteTime -Descending

foreach ($file in $logs) {
    $matches = Select-String `
        -Path $file.FullName `
        -Pattern 'Failed to open the Oracle database connection|OracleException|ORA-|ODP.NET|InputValidationError' `
        -Context 3, 12 `
        -ErrorAction SilentlyContinue
    if ($matches) {
        Write-Output "LOG_FILE=$($file.FullName)"
        foreach ($match in $matches | Select-Object -Last 8) {
            $match.Context.PreContext | ForEach-Object { Write-Output "LOG=$_" }
            Write-Output "LOG=$($match.Line)"
            $match.Context.PostContext | ForEach-Object { Write-Output "LOG=$_" }
        }
    }
}
