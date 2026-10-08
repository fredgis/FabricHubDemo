// Existing compute and Kafka only. No new VM, capacity, storage or paid SKU.
targetScope = 'resourceGroup'

@allowed(['dev', 'test', 'prod'])
param environment string
param namespaceName string
param eventHubName string
param publisherPrincipalId string

resource namespace 'Microsoft.EventHub/namespaces@2024-01-01' existing = {
  name: namespaceName
}
resource hub 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' existing = {
  parent: namespace
  name: eventHubName
}
var senderRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '2b629674-e913-4c01-ae53-ef4638d8f975')
resource sender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(hub.id, publisherPrincipalId, senderRoleId)
  scope: hub
  properties: {
    principalId: publisherPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: senderRoleId
  }
}
output roleAssignmentId string = sender.id
output deploymentEnvironment string = environment
