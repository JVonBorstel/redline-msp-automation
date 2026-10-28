// Automation account that runs as the user-assigned managed identity from core.
// Local authentication is off and no stored-login, connection or certificate resource is declared.
// Not compiled here (no Bicep CLI on the build machine). API version is from memory (UNVERIFIED).
targetScope = 'resourceGroup'

@description('Automation account name, 6-50 characters.')
param name string

param location string = resourceGroup().location

@description('Resource id of the user-assigned managed identity (created by infra/bicep/core).')
param identityId string

@description('Required tags: environment, owner, dataClass, project.')
param tags object

resource account 'Microsoft.Automation/automationAccounts@2023-11-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: {
    sku: {
      name: 'Basic'
    }
    disableLocalAuth: true
    publicNetworkAccess: false
  }
}

output accountName string = account.name
