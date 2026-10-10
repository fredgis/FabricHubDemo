targetScope = 'resourceGroup'

@allowed(['southeastasia'])
param location string = 'southeastasia'

@allowed(['dev', 'test', 'prod'])
param environment string = 'dev'

@minLength(3)
@maxLength(24)
param storageAccountName string

@description('Existing MSFlix workspace; this template does not create or modify Fabric items.')
param workspaceId string

@description('Service principal object ID of the existing workspace identity, not its application ID.')
param workspaceIdentityPrincipalId string

@description('Object ID of the authorized human operator who will publish the synthetic source files.')
param operatorPrincipalId string

var containerName = 'datasphere'
// Fabric resource-instance rules use the documented zero subscription, not the Azure subscription.
var workspaceResourceId = '/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/Fabric/providers/Microsoft.Fabric/workspaces/${workspaceId}'
var readerRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1')
var contributorRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  tags: {
    application: 'MSFlix'
    environment: environment
    owner: 'fabricroadshow'
    component: 'sap-datasphere'
    managedBy: 'FabricHubDemo'
  }
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    isHnsEnabled: true
    accessTier: 'Hot'
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'None'
      ipRules: []
      virtualNetworkRules: []
      resourceAccessRules: [
        {
          tenantId: subscription().tenantId
          resourceId: workspaceResourceId
        }
      ]
    }
    encryption: {
      keySource: 'Microsoft.Storage'
      services: {
        blob: {
          enabled: true
          keyType: 'Account'
        }
        file: {
          enabled: true
          keyType: 'Account'
        }
      }
    }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: false
      allowPermanentDelete: false
    }
  }
}

resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: containerName
  properties: {
    publicAccess: 'None'
    defaultEncryptionScope: '$account-encryption-key'
    denyEncryptionScopeOverride: false
  }
}

resource workspaceReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, workspaceIdentityPrincipalId, readerRole)
  scope: storage
  properties: {
    principalId: workspaceIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: readerRole
  }
}

resource operatorWriter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, operatorPrincipalId, contributorRole)
  scope: storage
  properties: {
    principalId: operatorPrincipalId
    principalType: 'User'
    roleDefinitionId: contributorRole
  }
}

resource workspaceContainerWriter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(container.id, workspaceIdentityPrincipalId, contributorRole)
  scope: container
  properties: {
    principalId: workspaceIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: contributorRole
  }
}

output storageAccountId string = storage.id
output storageAccountName string = storage.name
output dfsEndpoint string = storage.properties.primaryEndpoints.dfs
output blobEndpoint string = storage.properties.primaryEndpoints.blob
output containerName string = container.name
output containerId string = container.id
output workspaceResourceId string = workspaceResourceId
output workspaceReaderAssignmentId string = workspaceReader.id
output operatorWriterAssignmentId string = operatorWriter.id
output workspaceContainerWriterAssignmentId string = workspaceContainerWriter.id
output deploymentEnvironment string = environment
