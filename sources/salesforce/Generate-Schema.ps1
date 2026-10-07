[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$objectsPath = Join-Path $PSScriptRoot 'force-app\main\default\objects'
$permissionsPath = Join-Path $PSScriptRoot 'force-app\main\default\permissionsets'
New-Item -ItemType Directory -Path $permissionsPath -Force | Out-Null
$permissions = [Collections.Generic.List[string]]::new()
$objectPermissions = [Collections.Generic.List[string]]::new()

function Add-Field {
    param([string]$Object,[string]$Name,[string]$Type='Text',[int]$Length=100,[switch]$External,[switch]$Required)
    $directory = Join-Path $objectsPath "$Object\fields"
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $extra = switch ($Type) {
        'Text' { "<length>$Length</length>" }
        'Number' { '<precision>18</precision><scale>0</scale>' }
        'Checkbox' { '<defaultValue>false</defaultValue>' }
        'DateTime' { '' }
        default { throw "Unsupported source field type: $Type" }
    }
    if ($External) { $extra += '<externalId>true</externalId><unique>true</unique>' }
    if ($Required) { $extra += '<required>true</required>' }
    $xml = "<?xml version=`"1.0`" encoding=`"UTF-8`"?><CustomField xmlns=`"http://soap.sforce.com/2006/04/metadata`"><fullName>$Name</fullName><label>$($Name.Replace('__c','').Replace('_',' '))</label><type>$Type</type>$extra</CustomField>"
    [IO.File]::WriteAllText((Join-Path $directory "$Name.field-meta.xml"),$xml,[Text.UTF8Encoding]::new($false))
    $permissions.Add("<fieldPermissions><editable>true</editable><field>$Object.$Name</field><readable>true</readable></fieldPermissions>")
}

foreach ($object in @('Account','Contact','Campaign')) {
    Add-Field -Object $object -Name MSFlix_Key__c -Length 80 -External
}
Add-Field Contact MSFlix_Territory__c -Length 2
Add-Field Campaign MSFlix_Currency__c -Length 3
Add-Field Campaign MSFlix_BudgetMinor__c -Type Number
Add-Field Campaign MSFlix_Channel__c -Length 30

foreach ($definition in @(
    @{ Name='MSFlix_Touch__c'; Label='MSFlix Marketing Touch'; Plural='MSFlix Marketing Touches' },
    @{ Name='MSFlix_Consent__c'; Label='MSFlix Consent'; Plural='MSFlix Consents' }
)) {
    $object = $definition.Name
    $directory = Join-Path $objectsPath $object
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $xml = "<?xml version=`"1.0`" encoding=`"UTF-8`"?><CustomObject xmlns=`"http://soap.sforce.com/2006/04/metadata`"><deploymentStatus>Deployed</deploymentStatus><label>$($definition.Label)</label><pluralLabel>$($definition.Plural)</pluralLabel><nameField><displayFormat>MSF-{000000}</displayFormat><label>Record Number</label><type>AutoNumber</type></nameField><sharingModel>ReadWrite</sharingModel></CustomObject>"
    [IO.File]::WriteAllText((Join-Path $directory "$object.object-meta.xml"),$xml,[Text.UTF8Encoding]::new($false))
    Add-Field $object MSFlix_Key__c -Length 100 -External
    Add-Field $object CustomerKey__c -Length 80
    Add-Field $object Channel__c -Length 30
    $objectPermissions.Add("<objectPermissions><allowCreate>true</allowCreate><allowDelete>false</allowDelete><allowEdit>true</allowEdit><allowRead>true</allowRead><modifyAllRecords>false</modifyAllRecords><object>$object</object><viewAllRecords>false</viewAllRecords></objectPermissions>")
}
Add-Field MSFlix_Touch__c CampaignKey__c -Length 80
Add-Field MSFlix_Touch__c TouchType__c -Length 30
Add-Field MSFlix_Touch__c OccurredAt__c -Type DateTime
Add-Field MSFlix_Touch__c TrackingToken__c -Length 100
Add-Field MSFlix_Consent__c Purpose__c -Length 30
Add-Field MSFlix_Consent__c Granted__c -Type Checkbox
Add-Field MSFlix_Consent__c EffectiveAt__c -Type DateTime
$xml = "<?xml version=`"1.0`" encoding=`"UTF-8`"?><PermissionSet xmlns=`"http://soap.sforce.com/2006/04/metadata`">$($permissions -join '')<label>MSFlix Integration</label>$($objectPermissions -join '')</PermissionSet>"
[IO.File]::WriteAllText((Join-Path $permissionsPath 'MSFlix_Integration.permissionset-meta.xml'),$xml,[Text.UTF8Encoding]::new($false))
'SALESFORCE_SCHEMA_GENERATED=true'
