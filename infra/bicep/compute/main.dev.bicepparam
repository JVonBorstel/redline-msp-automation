// Placeholders only. No secret, key, token, connection string or real id belongs in this file.
// The identity and workspace values are outputs of the infra/bicep/core deployment; a human copies them in for a what-if.
using './main.bicep'

param environment = 'dev'
param namePrefix = 'gwai'
param location = 'westus3'
param identityId = '<core-identity-resource-id>'
param identityPrincipalId = '<core-identity-principal-id>'
param identityClientId = '<core-identity-client-id>'
param workspaceId = '<core-workspace-resource-id>'
param owner = '<owner-team-or-person>'
param dataClass = '<data-class>'
param project = 'redline-msp-automation'
