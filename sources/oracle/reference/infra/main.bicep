targetScope = 'resourceGroup'

@description('Azure region for all Demo resources.')
param location string = 'southeastasia'

@description('Short prefix used for resource names.')
param prefix string = 'demo'

@description('Linux administrator name.')
param linuxAdminUsername string = 'demoadmin'

@description('Windows administrator name.')
param windowsAdminUsername string = 'demoadmin'

@secure()
@description('Windows local administrator password.')
param windowsAdminPassword string

@description('SSH public key for the Oracle Linux VM.')
param linuxSshPublicKey string

@description('GZip-compressed Base64 gateway preparation script.')
param gatewayPreparationScriptGzipBase64 string

@description('Stable non-secret value used to name role assignments.')
param roleAssignmentSalt string

@description('Oracle VM size.')
param oracleVmSize string = 'Standard_D2s_v5'

@description('Gateway VM size.')
param gatewayVmSize string = 'Standard_D4s_v5'

var vnetName = '${prefix}-oracle-vnet'
var oracleSubnetName = 'snet-${prefix}-oracle'
var gatewaySubnetName = 'snet-${prefix}-gateway'
var privateEndpointSubnetName = 'snet-${prefix}-private-endpoints'
var oracleNsgName = '${prefix}-oracle-nsg'
var gatewayNsgName = '${prefix}-gateway-nsg'
var natName = '${prefix}-egress-nat'
var natPublicIpName = '${prefix}-egress-pip'
var oracleNicName = '${prefix}-oracle-nic'
var gatewayNicName = '${prefix}-fabric-gateway-nic'
var oracleVmName = '${prefix}-oracle-vm'
var gatewayVmName = '${prefix}-fabric-gateway-vm'
var logAnalyticsName = '${prefix}-oracle-logs'
var keyVaultName = take('${replace(prefix, '-', '')}oraclekv${uniqueString(subscription().id, resourceGroup().id)}', 24)
var privateDnsZoneName = 'privatelink.vaultcore.azure.net'
var oraclePrivateIp = '10.60.1.4'
var gatewayPrivateIp = '10.60.2.4'
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
var gatewayPreparationCommand = format('powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$bytes=[Convert]::FromBase64String(\'{0}\'); $input=[IO.MemoryStream]::new($bytes); $gzip=[IO.Compression.GzipStream]::new($input,[IO.Compression.CompressionMode]::Decompress); $reader=[IO.StreamReader]::new($gzip); $script=$reader.ReadToEnd(); $reader.Dispose(); $path=\'C:\\Windows\\Temp\\Prepare-DemoGateway.ps1\'; [IO.File]::WriteAllText($path,$script); & $path"', gatewayPreparationScriptGzipBase64)

resource oracleNsg 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: oracleNsgName
  location: location
  properties: {
    securityRules: [
      {
        name: 'AllowSshFromDemoVnet'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '22'
          sourceAddressPrefix: 'VirtualNetwork'
          destinationAddressPrefix: oraclePrivateIp
        }
      }
      {
        name: 'AllowOracleFromGatewaySubnet'
        properties: {
          priority: 110
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '1521'
          sourceAddressPrefix: '10.60.2.0/24'
          destinationAddressPrefix: oraclePrivateIp
        }
      }
      {
        name: 'DenyOtherDemoVnetInbound'
        properties: {
          priority: 4096
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: 'VirtualNetwork'
          destinationAddressPrefix: '*'
        }
      }
    ]
  }
}

resource gatewayNsg 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: gatewayNsgName
  location: location
  properties: {
    securityRules: [
      {
        name: 'AllowRdpFromDemoVnet'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '3389'
          sourceAddressPrefix: 'VirtualNetwork'
          destinationAddressPrefix: gatewayPrivateIp
        }
      }
      {
        name: 'DenyOtherDemoVnetInbound'
        properties: {
          priority: 4096
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: 'VirtualNetwork'
          destinationAddressPrefix: '*'
        }
      }
    ]
  }
}

resource natPublicIp 'Microsoft.Network/publicIPAddresses@2023-11-01' = {
  name: natPublicIpName
  location: location
  sku: {
    name: 'Standard'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }
}

resource natGateway 'Microsoft.Network/natGateways@2023-11-01' = {
  name: natName
  location: location
  sku: {
    name: 'Standard'
  }
  properties: {
    idleTimeoutInMinutes: 10
    publicIpAddresses: [
      {
        id: natPublicIp.id
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: vnetName
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.60.0.0/16'
      ]
    }
  }
}

resource oracleSubnet 'Microsoft.Network/virtualNetworks/subnets@2023-11-01' = {
  parent: vnet
  name: oracleSubnetName
  properties: {
    addressPrefix: '10.60.1.0/24'
    defaultOutboundAccess: false
    networkSecurityGroup: {
      id: oracleNsg.id
    }
    natGateway: {
      id: natGateway.id
    }
  }
}

resource gatewaySubnet 'Microsoft.Network/virtualNetworks/subnets@2023-11-01' = {
  parent: vnet
  name: gatewaySubnetName
  properties: {
    addressPrefix: '10.60.2.0/24'
    defaultOutboundAccess: false
    networkSecurityGroup: {
      id: gatewayNsg.id
    }
    natGateway: {
      id: natGateway.id
    }
  }
  dependsOn: [
    oracleSubnet
  ]
}

resource privateEndpointSubnet 'Microsoft.Network/virtualNetworks/subnets@2023-11-01' = {
  parent: vnet
  name: privateEndpointSubnetName
  properties: {
    addressPrefix: '10.60.3.0/24'
    defaultOutboundAccess: false
    privateEndpointNetworkPolicies: 'Disabled'
  }
  dependsOn: [
    gatewaySubnet
  ]
}

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    retentionInDays: 30
    sku: {
      name: 'PerGB2018'
    }
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
      ipRules: []
    }
    sku: {
      family: 'A'
      name: 'standard'
    }
  }
}

resource privateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: privateDnsZoneName
  location: 'global'
}

resource privateDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: privateDnsZone
  name: '${prefix}-keyvault-dns-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}

resource keyVaultPrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-11-01' = {
  name: '${prefix}-keyvault-pe'
  location: location
  properties: {
    subnet: {
      id: privateEndpointSubnet.id
    }
    privateLinkServiceConnections: [
      {
        name: '${prefix}-keyvault-connection'
        properties: {
          privateLinkServiceId: keyVault.id
          groupIds: [
            'vault'
          ]
        }
      }
    ]
  }
}

resource keyVaultDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = {
  parent: keyVaultPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'keyvault'
        properties: {
          privateDnsZoneId: privateDnsZone.id
        }
      }
    ]
  }
}

resource oracleNic 'Microsoft.Network/networkInterfaces@2023-11-01' = {
  name: oracleNicName
  location: location
  properties: {
    enableAcceleratedNetworking: false
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          privateIPAllocationMethod: 'Static'
          privateIPAddress: oraclePrivateIp
          subnet: {
            id: oracleSubnet.id
          }
        }
      }
    ]
  }
}

resource gatewayNic 'Microsoft.Network/networkInterfaces@2023-11-01' = {
  name: gatewayNicName
  location: location
  properties: {
    enableAcceleratedNetworking: false
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          privateIPAllocationMethod: 'Static'
          privateIPAddress: gatewayPrivateIp
          subnet: {
            id: gatewaySubnet.id
          }
        }
      }
    ]
  }
}

resource oracleVm 'Microsoft.Compute/virtualMachines@2023-09-01' = {
  name: oracleVmName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    hardwareProfile: {
      vmSize: oracleVmSize
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: oracleNic.id
          properties: {
            deleteOption: 'Delete'
          }
        }
      ]
    }
    osProfile: {
      computerName: 'demooracle'
      adminUsername: linuxAdminUsername
      linuxConfiguration: {
        disablePasswordAuthentication: true
        provisionVMAgent: true
        ssh: {
          publicKeys: [
            {
              path: '/home/${linuxAdminUsername}/.ssh/authorized_keys'
              keyData: linuxSshPublicKey
            }
          ]
        }
      }
    }
    storageProfile: {
      imageReference: {
        publisher: 'Oracle'
        offer: 'Oracle-Linux'
        sku: 'ol98-lvm-gen2'
        version: '9.8.2'
      }
      osDisk: {
        createOption: 'FromImage'
        deleteOption: 'Delete'
        diskSizeGB: 64
        managedDisk: {
          storageAccountType: 'Premium_LRS'
        }
      }
      dataDisks: [
        {
          lun: 0
          createOption: 'Empty'
          deleteOption: 'Delete'
          diskSizeGB: 64
          caching: 'None'
          managedDisk: {
            storageAccountType: 'Premium_LRS'
          }
        }
      ]
    }
    diagnosticsProfile: {
      bootDiagnostics: {
        enabled: true
      }
    }
  }
}

resource gatewayVm 'Microsoft.Compute/virtualMachines@2023-09-01' = {
  name: gatewayVmName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    hardwareProfile: {
      vmSize: gatewayVmSize
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: gatewayNic.id
          properties: {
            deleteOption: 'Delete'
          }
        }
      ]
    }
    osProfile: {
      computerName: 'demogateway'
      adminUsername: windowsAdminUsername
      adminPassword: windowsAdminPassword
      windowsConfiguration: {
        enableAutomaticUpdates: true
        provisionVMAgent: true
        patchSettings: {
          assessmentMode: 'AutomaticByPlatform'
          patchMode: 'AutomaticByPlatform'
        }
      }
    }
    storageProfile: {
      imageReference: {
        publisher: 'MicrosoftWindowsServer'
        offer: 'WindowsServer'
        sku: '2022-datacenter-azure-edition'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        deleteOption: 'Delete'
        diskSizeGB: 128
        managedDisk: {
          storageAccountType: 'StandardSSD_LRS'
        }
      }
    }
    diagnosticsProfile: {
      bootDiagnostics: {
        enabled: true
      }
    }
  }
}

resource gatewayPreparationExtension 'Microsoft.Compute/virtualMachines/extensions@2023-09-01' = {
  parent: gatewayVm
  name: 'PrepareDemoGateway'
  location: location
  properties: {
    publisher: 'Microsoft.Compute'
    type: 'CustomScriptExtension'
    typeHandlerVersion: '1.10'
    autoUpgradeMinorVersion: true
    protectedSettings: {
      commandToExecute: gatewayPreparationCommand
    }
  }
}

resource oracleVmKeyVaultSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, roleAssignmentSalt, 'oracle-vm', keyVaultSecretsUserRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: oracleVm.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource gatewayVmKeyVaultSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, roleAssignmentSalt, 'gateway-vm', keyVaultSecretsUserRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: gatewayVm.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output location string = location
output vnetName string = vnet.name
output oracleVmName string = oracleVm.name
output gatewayVmName string = gatewayVm.name
output keyVaultName string = keyVault.name
output logAnalyticsName string = logAnalytics.name
output oraclePrivateIp string = oraclePrivateIp
output gatewayPrivateIp string = gatewayPrivateIp
output natPublicIpAddress string = natPublicIp.properties.ipAddress
output oracleVmPrincipalId string = oracleVm.identity.principalId
output keyVaultResourceId string = keyVault.id
