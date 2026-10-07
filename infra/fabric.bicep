targetScope = 'resourceGroup'

param location string = 'southeastasia'
param capacityName string = 'msflixf16sea'
param administrator string

var tags = {
  application: 'MSFlix'
  environment: 'demo'
  owner: 'fabricroadshow'
}

resource capacity 'Microsoft.Fabric/capacities@2023-11-01' = {
  name: capacityName
  location: location
  tags: tags
  sku: {
    name: 'F16'
    tier: 'Fabric'
  }
  properties: {
    administration: {
      members: [
        administrator
      ]
    }
  }
}

module streaming './streaming.bicep' = {
  name: 'msflix-streaming'
  params: {
    location: location
  }
}

output capacityId string = capacity.id
output eventHubNamespace string = streaming.outputs.namespaceName
output eventHubId string = streaming.outputs.eventHubId
