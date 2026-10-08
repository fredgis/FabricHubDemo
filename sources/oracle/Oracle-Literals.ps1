function ConvertTo-OracleTextLiteral {
    param([AllowEmptyString()][string]$Value)
    $builder = [Text.StringBuilder]::new()
    foreach ($character in [regex]::Replace($Value, '[\r\n]+', ' ').ToCharArray()) {
        $code = [int]$character
        if ($code -gt 127) {
            [void]$builder.Append(('\{0:X4}' -f $code))
        } elseif ($character -eq '\') {
            [void]$builder.Append('\\')
        } elseif ($character -eq "'") {
            [void]$builder.Append("''")
        } else {
            [void]$builder.Append($character)
        }
    }
    return "UNISTR('$builder')"
}
