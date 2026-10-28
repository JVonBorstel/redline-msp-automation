// Logic App (consumption workflow) that runs as the user-assigned managed identity from core.
// Ships DISABLED with an empty definition: a person designs the workflow and enables it. Nothing sensitive is stored here.
// Not compiled here (no Bicep CLI on the build machine). API version is from memory (UNVERIFIED).
targetScope = 'resourceGroup'

@description('Workflow name, 1-80 characters.')
param name string

param location string = resourceGroup().location

@description('Resource id of the user-assigned managed identity (created by infra/bicep/core).')
param identityId string

@description('Required tags: environment, owner, dataClass, project.')
param tags object

resource workflow 'Microsoft.Logic/workflows@2019-05-01' = {
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
    state: 'Disabled'
    definition: {
      '$schema': 'https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#'
      contentVersion: '1.0.0.0'
      triggers: {}
      actions: {}
      outputs: {}
    }
  }
}

output workflowName string = workflow.name
