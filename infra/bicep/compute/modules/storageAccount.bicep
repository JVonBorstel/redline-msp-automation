// Storage account for the function app's host (AzureWebJobsStorage). Identity-based only: shared keys are off.
// Not compiled here (no Bicep CLI on the build machine). API versions are from memory (UNVERIFIED).
targetScope = 'resourceGroup'

@description('Storage account name, 3-24 lowercase letters and digits.')
@minLength(3)
@maxLength(24)
param name string

param location string = resourceGroup().location

@description('Principal id of the user-assigned managed identity (from core) that the function app runs as.')
param identityPrincipalId string

@description('Required tags: environment, owner, dataClass, project.')
param tags object

// Built-in role "Storage Blob Data Owner": the documented role for identity-based function host storage.
// It is data-plane only; it does not allow changing the account itself.
var storageBlobDataOwnerRoleId = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'

resource account 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: name
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    // No account keys or SAS: callers use Entra ID identities only.
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
  }
}

resource blobOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(account.id, identityPrincipalId, storageBlobDataOwnerRoleId)
  scope: account
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataOwnerRoleId)
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output accountName string = account.name
