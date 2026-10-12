function Read-OracleTargetPolicy {
    [CmdletBinding()]
    param(
        [string]$Path = (Join-Path $PSScriptRoot 'target-policy.local.json')
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw 'Oracle target policy is missing. Populate sources\oracle\target-policy.local.json with independently approved identifiers.'
    }
    try {
        $json = Get-Content -LiteralPath $Path -Raw -Encoding utf8 -ErrorAction Stop
        $document = [System.Text.Json.JsonDocument]::Parse($json)
    }
    catch {
        throw 'Oracle target policy must contain valid JSON.'
    }
    try {
        if ($document.RootElement.ValueKind -ne [System.Text.Json.JsonValueKind]::Object) {
            throw 'Oracle target policy must be a JSON object.'
        }
        $fields = @('subscriptionId', 'tenantId', 'prohibitedGatewayId')
        $policy = @{}
        foreach ($property in $document.RootElement.EnumerateObject()) {
            if ($property.Name -notin $fields -or $policy.ContainsKey($property.Name)) {
                throw 'Oracle target policy contains unexpected or duplicate fields.'
            }
            $policy[$property.Name] = if ($property.Value.ValueKind -eq [System.Text.Json.JsonValueKind]::String) {
                $property.Value.GetString()
            } else { $null }
        }
        foreach ($name in $fields) {
            $value = $policy[$name]
            $identifier = [guid]::Empty
            if ($value -isnot [string] -or $value -cne $value.Trim() -or
                -not [guid]::TryParseExact($value, 'D', [ref]$identifier) -or
                $identifier -eq [guid]::Empty) {
                throw "Oracle target policy field $name must be a non-empty GUID."
            }
        }
        return [pscustomobject]$policy
    }
    finally {
        $document.Dispose()
    }
}
