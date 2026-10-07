targetScope = 'resourceGroup'

param location string = 'southeastasia'
param namespaceName string = 'msflix-${uniqueString(subscription().id, resourceGroup().id)}'

resource namespace 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: namespaceName
  location: location
  tags: {
    application: 'MSFlix'
    environment: 'demo'
    owner: 'fabricroadshow'
  }
  sku: {
    name: 'Standard'
    tier: 'Standard'
    capacity: 1
  }
  properties: {
    minimumTlsVersion: '1.2'
    isAutoInflateEnabled: false
    maximumThroughputUnits: 0
    disableLocalAuth: false
  }
}

resource events 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: namespace
  name: 'msflix-events'
  properties: {
    partitionCount: 4
    messageRetentionInDays: 1
  }
}

resource consumer 'Microsoft.EventHub/namespaces/eventhubs/consumergroups@2024-01-01' = {
  parent: events
  name: 'fabric-msflix'
}

resource fabricListen 'Microsoft.EventHub/namespaces/eventhubs/authorizationRules@2024-01-01' = {
  parent: events
  name: 'fabric-listen'
  properties: {
    rights: [
      'Listen'
    ]
  }
}

output namespaceName string = namespace.name
output eventHubId string = events.id
output listenPolicyId string = fabricListen.id
