// Log Analytics workspace: the one place diagnostic logs land. Not compiled here (no Bicep CLI on the build machine).
targetScope = 'resourceGroup'

@description('Workspace name, 4-63 characters.')
param name string

param location string = resourceGroup().location

@description('Days to keep logs. 30 to 730.')
@minValue(30)
@maxValue(730)
param retentionInDays int = 90

@description('Required tags: environment, owner, dataClass, project.')
param tags object

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: retentionInDays
    features: {
      // No shared-key access: callers use Entra ID identities only.
      disableLocalAuth: true
    }
  }
}

output workspaceId string = workspace.id
output workspaceName string = workspace.name
