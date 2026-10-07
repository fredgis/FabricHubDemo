[CmdletBinding()]
param([string]$Alias='MSFlix',[int]$CustomerCount=120)
$ErrorActionPreference = 'Stop'
$env:SF_DISABLE_TELEMETRY = 'true'
$env:SF_AUTOUPDATE_DISABLE = 'true'
$sf = Join-Path $env:APPDATA 'npm\sf.cmd'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$directory = Join-Path $root '.state\salesforce'
New-Item -ItemType Directory -Path $directory -Force | Out-Null
$displayRaw = & $sf org display --target-org $Alias --json
if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve the authorized Salesforce user.' }
$display = $displayRaw | ConvertFrom-Json
$username = $display.result.username.Replace("'","\'")
$userRaw = & $sf data query --target-org $Alias `
    --query "SELECT Id,UserPermissionsMarketingUser FROM User WHERE Username='$username'" --json
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect campaign-management permission.' }
$users = @(($userRaw | ConvertFrom-Json).result.records)
if ($users.Count -ne 1) { throw 'Expected one authorized Salesforce user.' }
if (-not $users[0].UserPermissionsMarketingUser) {
    $updated = & $sf data update record --sobject User --record-id $users[0].Id `
        --values 'UserPermissionsMarketingUser=true' --target-org $Alias --json
    if ($LASTEXITCODE -ne 0) { throw 'Cannot enable Marketing User for the approved campaign seed.' }
    'SALESFORCE_MARKETING_USER=Enabled'
}

function Upsert-Records {
    param([string]$Object,[object[]]$Records)
    $path = Join-Path $directory "$Object.csv"
    $Records | Export-Csv -LiteralPath $path -NoTypeInformation -Encoding utf8NoBOM
    $raw = & $sf data upsert bulk --sobject $Object --file $path --external-id MSFlix_Key__c --target-org $Alias --wait 10 --json
    $exit = $LASTEXITCODE
    $result = $raw | ConvertFrom-Json
    if ($exit -ne 0 -or $result.status -ne 0) { throw "CRM bulk upsert failed for $Object : $($result.message)" }
    if ($result.result.numberRecordsFailed -gt 0) { throw "CRM bulk job rejected $($result.result.numberRecordsFailed) records for $Object." }
    "CRM_SEEDED=$Object;INPUT_COUNT=$($Records.Count)"
}

Upsert-Records Account @([pscustomobject]@{ Name='MSFlix Consumer Audience'; MSFlix_Key__c='MSFLIX-AUDIENCE'; Type='Customer' })
$raw = & $sf data query --target-org $Alias --query "SELECT Id FROM Account WHERE MSFlix_Key__c='MSFLIX-AUDIENCE'" --json
if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve the MSFlix audience account.' }
$account = ($raw | ConvertFrom-Json).result.records
if (@($account).Count -ne 1) { throw 'Expected exactly one MSFlix audience account.' }
$firstNames = @('Camille','Nora','Gabriel','Elise','Romain','Ines','Mathis','Clara','Hugo','Salome','Yanis','Louise','Theo','Maya','Julien')
$lastNames = @('Delorme','Vernier','Morel','Dumont','Lenoir','Marchand','Perrin','Aubert','Laurent','Roche','Faure','Garnier','Collet','Renard','Mercier')
$territories = @('FR','BE','CA','CH')
$customers = @(for ($index=1; $index -le $CustomerCount; $index++) {
    [pscustomobject]@{
        AccountId=$account[0].Id
        FirstName=$firstNames[($index-1) % $firstNames.Count]
        LastName=$lastNames[[int][Math]::Floor(($index-1)/$firstNames.Count) % $lastNames.Count]
        Email=('client{0:D4}@msflix.invalid' -f $index)
        MSFlix_Key__c=('MSF-C{0:D4}' -f $index)
        MSFlix_Territory__c=$territories[($index-1) % $territories.Count]
    }
})
Upsert-Records Contact $customers
$campaigns = @(
    @{ key='MSF-MKT-FANTASY'; name='La nuit du fantastique'; budget=185000; channel='EMAIL' },
    @{ key='MSF-MKT-FAMILY'; name='Le cinema en famille'; budget=124000; channel='EMAIL' },
    @{ key='MSF-MKT-INDIE'; name='Regards independants'; budget=236000; channel='SOCIAL' },
    @{ key='MSF-MKT-SCIFI'; name='Horizons science-fiction'; budget=198000; channel='SOCIAL' },
    @{ key='MSF-MKT-WEEKEND'; name='Votre prochaine seance'; budget=99000; channel='EMAIL' },
    @{ key='MSF-MKT-CATALOG'; name='Les incontournables MSFlix'; budget=156000; channel='IN_APP' }
)
$records = @($campaigns | ForEach-Object { [pscustomobject]@{
    Name=$_.name; MSFlix_Key__c=$_.key; IsActive='true'; Status='In Progress'
    StartDate='2026-10-01'; EndDate='2026-10-31'; MSFlix_Currency__c='EUR'
    MSFlix_BudgetMinor__c=$_.budget; MSFlix_Channel__c=$_.channel
}})
Upsert-Records Campaign $records
$consents = @(for ($index=1; $index -le $CustomerCount; $index++) {
    [pscustomobject]@{
        MSFlix_Key__c=('MSF-CONSENT-{0:D4}' -f $index)
        CustomerKey__c=('MSF-C{0:D4}' -f $index)
        Channel__c='EMAIL'; Purpose__c='MARKETING'
        Granted__c=if ($index % 7 -eq 0) { 'false' } else { 'true' }
        EffectiveAt__c='2026-10-01T08:00:00Z'
    }
})
Upsert-Records MSFlix_Consent__c $consents
$touches = @(for ($index=1; $index -le $CustomerCount; $index++) {
    if ($index % 7 -ne 0) {
        [pscustomobject]@{
            MSFlix_Key__c=('MSF-TOUCH-{0:D4}' -f $index)
            CustomerKey__c=('MSF-C{0:D4}' -f $index)
            CampaignKey__c=$campaigns[($index-1) % $campaigns.Count].key
            Channel__c=$campaigns[($index-1) % $campaigns.Count].channel
            TouchType__c='CLICK'; OccurredAt__c='2026-10-07T09:30:00Z'
            TrackingToken__c=('MSF-TRACK-{0:D4}' -f $index)
        }
    }
})
Upsert-Records MSFlix_Touch__c $touches

foreach ($query in @(
    @{ key='customers'; soql="SELECT Id,FirstName,LastName,MSFlix_Key__c,MSFlix_Territory__c FROM Contact WHERE MSFlix_Key__c LIKE 'MSF-C%'" },
    @{ key='campaigns'; soql="SELECT Id,Name,MSFlix_Key__c,MSFlix_Currency__c,MSFlix_BudgetMinor__c,MSFlix_Channel__c FROM Campaign WHERE MSFlix_Key__c LIKE 'MSF-MKT-%'" },
    @{ key='consents'; soql='SELECT Id,MSFlix_Key__c,CustomerKey__c,Channel__c,Purpose__c,Granted__c,EffectiveAt__c FROM MSFlix_Consent__c' },
    @{ key='touches'; soql='SELECT Id,MSFlix_Key__c,CustomerKey__c,CampaignKey__c,Channel__c,TouchType__c,OccurredAt__c,TrackingToken__c FROM MSFlix_Touch__c' }
)) {
    $raw = & $sf data query --target-org $Alias --query $query.soql --json
    if ($LASTEXITCODE -ne 0) { throw "CRM export failed: $($query.key)" }
    $records = ($raw | ConvertFrom-Json).result.records
    $records | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $directory "$($query.key).json") -Encoding utf8NoBOM
    "CRM_EXPORTED=$($query.key);COUNT=$(@($records).Count)"
}
