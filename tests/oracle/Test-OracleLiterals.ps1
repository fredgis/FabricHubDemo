$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\..\sources\oracle\Oracle-Literals.ps1')
$sample = [string][char]0xC9 + 't' + [char]0xE9 + " d'hiver \"
if ((ConvertTo-OracleTextLiteral $sample) -cne "UNISTR('\00C9t\00E9 d''hiver \\')") {
    throw 'Oracle Unicode, apostrophe and backslash quoting failed.'
}
if ((ConvertTo-OracleTextLiteral "first`r`nsecond") -cne "UNISTR('first second')") {
    throw 'Oracle SQLPlus line normalization failed.'
}
if ((ConvertTo-OracleTextLiteral '') -cne "UNISTR('')") {
    throw 'Oracle empty literal changed.'
}
'ORACLE_LITERAL_TESTS=3 passed'
