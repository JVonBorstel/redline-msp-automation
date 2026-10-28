// One Key Vault per environment (dev, prod). Azure RBAC only, soft delete, purge protection, no public access.
// The template never creates a secret, key or certificate: values are set by a person, outside this repo.
targetScope = 'resourceGroup'

@allowed([
  'dev'
  'prod'
])
param environment string

@description('Short lowercase prefix used in the vault name.')
@minLength(2)
@maxLength(8)
param namePrefix string

param location string = resourceGroup().location

@description('Days a deleted vault or secret stays recoverable (90 is the maximum). Fixed once the vault exists.')
@minValue(90)
@maxValue(90)
param softDeleteRetentionInDays int = 90

@description('Principal (object) id of the user-assigned managed identity that reads secrets.')
param secretsReaderPrincipalId string

@description('Optional subnet resource id for a private endpoint. Empty means no endpoint is created.')
param privateEndpointSubnetId string = ''

@description('Required tags: environment, owner, dataClass, project.')
param tags object

var vaultName = take('kv-${namePrefix}-${environment}-${uniqueString(resourceGroup().id)}', 24)
// Built-in role "Key Vault Secrets User" (read secret contents). UNVERIFIED: id written from memory.
var secretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: vaultName
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: softDeleteRetentionInDays
    enablePurgeProtection: true
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'None'
    }
  }
}

resource secretsReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, secretsReaderPrincipalId, secretsUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsUserRoleId)
    principalId: secretsReaderPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource endpoint 'Microsoft.Network/privateEndpoints@2023-09-01' = if (!empty(privateEndpointSubnetId)) {
  name: 'pe-${vaultName}'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'vault'
        properties: {
          privateLinkServiceId: vault.id
          groupIds: [
            'vault'
          ]
        }
      }
    ]
  }
}

output vaultId string = vault.id
output vaultName string = vault.name
