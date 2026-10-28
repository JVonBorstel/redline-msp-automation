// B-86 compute: storage for the function host, function app, Logic App, Automation account (one set per environment).
// Resource-group scope. Validate and what-if only: see README.md. Never deployed from this repo.
// Everything runs as the user-assigned managed identity that infra/bicep/core creates; this template never creates one.
targetScope = 'resourceGroup'

@allowed([
  'dev'
  'prod'
])
param environment string

@description('Short lowercase name prefix, 2-8 characters. Use the same value as infra/bicep/core.')
@minLength(2)
@maxLength(8)
param namePrefix string

param location string = resourceGroup().location

@description('Resource id of the managed identity from infra/bicep/core (output identityId of that deployment).')
param identityId string

@description('Principal id of that identity (core output identityPrincipalId).')
param identityPrincipalId string

@description('Client id of that identity (core output clientId).')
param identityClientId string

@description('Log Analytics workspace id from core (core output workspaceId). Echoed as an output; diagnostics are not wired yet.')
param workspaceId string

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

module storage 'modules/storageAccount.bicep' = {
  name: 'storageAccount'
  params: {
    name: take('st${namePrefix}${environment}${uniqueString(resourceGroup().id)}', 24)
    location: location
    identityPrincipalId: identityPrincipalId
    tags: tags
  }
}

module functionApp 'modules/functionApp.bicep' = {
  name: 'functionApp'
  params: {
    name: 'func-${namePrefix}-${environment}'
    planName: 'plan-${namePrefix}-${environment}'
    location: location
    identityId: identityId
    identityClientId: identityClientId
    storageAccountName: storage.outputs.accountName
    tags: tags
  }
}

module logicApp 'modules/logicApp.bicep' = {
  name: 'logicApp'
  params: {
    name: 'logic-${namePrefix}-${environment}'
    location: location
    identityId: identityId
    tags: tags
  }
}

module automationAccount 'modules/automationAccount.bicep' = {
  name: 'automationAccount'
  params: {
    name: 'aa-${namePrefix}-${environment}'
    location: location
    identityId: identityId
    tags: tags
  }
}

output functionAppName string = functionApp.outputs.functionAppName
output logicAppName string = logicApp.outputs.workflowName
output automationAccountName string = automationAccount.outputs.accountName
output logWorkspaceId string = workspaceId
