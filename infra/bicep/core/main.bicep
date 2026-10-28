// B-85 core: Log Analytics workspace, managed identity, Key Vault, diagnostic settings (one set per environment).
// Resource-group scope. Validate and what-if only: see README.md. Never deployed from this repo.
targetScope = 'resourceGroup'

@allowed([
  'dev'
  'prod'
])
param environment string

@description('Short lowercase name prefix, 2-8 characters.')
@minLength(2)
@maxLength(8)
param namePrefix string

param location string = resourceGroup().location

@description('Days to keep logs.')
param logRetentionDays int = 90

@description('Optional subnet resource id for the Key Vault private endpoint. Empty means none.')
param privateEndpointSubnetId string = ''

@description('Team or person accountable for these resources (tag owner).')
param owner string

@description('Data classification (tag dataClass), for example DC-2.')
param dataClass string

@description('Project (tag project).')
param project string

var tags = {
  environment: environment
  owner: owner
  dataClass: dataClass
  project: project
}

module logs 'modules/logAnalytics.bicep' = {
  name: 'logAnalytics'
  params: {
    name: 'log-${namePrefix}-${environment}'
    location: location
    retentionInDays: logRetentionDays
    tags: tags
  }
}

module identity 'modules/managedIdentity.bicep' = {
  name: 'managedIdentity'
  params: {
    name: 'id-${namePrefix}-${environment}'
    location: location
    tags: tags
  }
}

module vault 'modules/keyVault.bicep' = {
  name: 'keyVault'
  params: {
    environment: environment
    namePrefix: namePrefix
    location: location
    secretsReaderPrincipalId: identity.outputs.principalId
    privateEndpointSubnetId: privateEndpointSubnetId
    tags: tags
  }
}

module diagnostics 'modules/diagnosticSettings.bicep' = {
  name: 'diagnosticSettings'
  params: {
    vaultName: vault.outputs.vaultName
    workspaceId: logs.outputs.workspaceId
  }
}

output vaultName string = vault.outputs.vaultName
output identityPrincipalId string = identity.outputs.principalId
output workspaceId string = logs.outputs.workspaceId
