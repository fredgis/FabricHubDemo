targetScope = 'resourceGroup'

param tenantId string
param workspaceId string
param location string = 'southeastasia'
param vnetName string = 'msflix-oracle-vnet'
param subnetName string = 'snet-msflix-private-endpoints'

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' existing = {
  name: vnetName
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2023-11-01' existing = {
  parent: vnet
  name: subnetName
}

resource link 'Microsoft.Fabric/privateLinkServicesForFabric@2024-06-01' = {
  name: 'msflix-workspace-link'
  location: 'global'
  tags: {
    application: 'MSFlix'
    environment: 'demo'
  }
  properties: {
    tenantId: tenantId
    workspaceId: workspaceId
  }
}

resource endpoint 'Microsoft.Network/privateEndpoints@2023-11-01' = {
  name: 'msflix-fabric-workspace-pe'
  location: location
  tags: {
    application: 'MSFlix'
    environment: 'demo'
  }
  properties: {
    subnet: {
      id: subnet.id
    }
    privateLinkServiceConnections: [
      {
        name: 'msflix-workspace'
        properties: {
          privateLinkServiceId: link.id
          groupIds: [
            'workspace'
          ]
        }
      }
    ]
  }
}

resource zone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.fabric.microsoft.com'
  location: 'global'
}

resource dnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: zone
  name: 'msflix-fabric-vnet'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}

resource zoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = {
  parent: endpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'fabric'
        properties: {
          privateDnsZoneId: zone.id
        }
      }
    ]
  }
}

output privateEndpointId string = endpoint.id
output privateLinkServiceId string = link.id
output dnsZone string = zone.name

