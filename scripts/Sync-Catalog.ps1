[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$sources = Get-Content -LiteralPath (Join-Path $root 'data\catalog.sources.json') -Raw | ConvertFrom-Json
$catalog = @(foreach ($film in $sources) {
    $page = Invoke-WebRequest -Uri $film.source_url
    $match = [regex]::Match($page.Content,'<meta\s+property="og:image"\s+content="([^"]+)"')
    if (-not $match.Success) { throw "No authoritative film artwork found: $($film.title)" }
    $image = [Net.WebUtility]::HtmlDecode($match.Groups[1].Value)
    $uri = [uri]$image
    if ($uri.Scheme -ne 'https' -or $uri.Host -ne 'studio.blender.org') {
        throw "Unexpected artwork host for $($film.title)"
    }
    $film | Add-Member -NotePropertyName image_url -NotePropertyValue $image -Force
    $film | Add-Member -NotePropertyName content_type -NotePropertyValue 'MOVIE' -Force
    $film | Add-Member -NotePropertyName is_active -NotePropertyValue $true -Force
    $film
})
$catalog | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $root 'data\catalog.json') -Encoding utf8NoBOM
"CATALOG_SOURCE_COUNT=$($catalog.Count)"
"CATALOG_ARTWORK=Authoritative Blender Studio images with per-film attribution"

