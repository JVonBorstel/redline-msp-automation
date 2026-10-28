// Sends Key Vault audit events and metrics to the Log Analytics workspace.
targetScope = 'resourceGroup'

@description('Name of the existing Key Vault.')
param vaultName string

@description('Resource id of the Log Analytics workspace.')
param workspaceId string

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: vaultName
}

resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'send-to-log-analytics'
  scope: vault
  properties: {
    workspaceId: workspaceId
    logs: [
      {
        category: 'AuditEvent'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}
