// Function app (Linux, Python) on an app service plan, running as the user-assigned managed identity from core.
// No keys: host storage is identity-based, publishing credentials are off, and no connection string is set.
// Not compiled here (no Bicep CLI on the build machine). API versions and the SKU are from memory (UNVERIFIED).
targetScope = 'resourceGroup'

@description('Function app name, 2-60 characters.')
param name string

@description('App service plan name.')
param planName string

param location string = resourceGroup().location

@description('Resource id of the user-assigned managed identity (created by infra/bicep/core).')
param identityId string

@description('Client id of that identity, used for the identity-based storage connection.')
param identityClientId string

@description('Name of the storage account for the function host (see storageAccount.bicep).')
param storageAccountName string

@description('Required tags: environment, owner, dataClass, project.')
param tags object

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: planName
  location: location
  tags: tags
  kind: 'linux'
  sku: {
    name: 'B1'
    tier: 'Basic'
  }
  properties: {
    reserved: true
  }
}

resource app 'Microsoft.Web/sites@2023-12-01' = {
  name: name
  location: location
  tags: tags
  kind: 'functionapp,linux'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    // Key Vault references (if a person ever adds one) resolve with this identity, not a system one.
    keyVaultReferenceIdentity: identityId
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appSettings: [
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'AzureWebJobsStorage__accountName', value: storageAccountName }
        { name: 'AzureWebJobsStorage__credential', value: 'managedidentity' }
        { name: 'AzureWebJobsStorage__clientId', value: identityClientId }
      ]
    }
  }
}

// FTP and SCM basic-auth publishing credentials are turned off, so there is no deployment password to leak.
resource ftpPolicy 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2023-12-01' = {
  parent: app
  name: 'ftp'
  properties: {
    allow: false
  }
}

resource scmPolicy 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2023-12-01' = {
  parent: app
  name: 'scm'
  properties: {
    allow: false
  }
}

output functionAppName string = app.name
