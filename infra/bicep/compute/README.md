# infra/bicep/compute: function app, Logic App, Automation account

> Independently built prototype. Not affiliated with any vendor's or real company's systems.

Resource-group-scope Bicep for one environment: host storage for a function app, a Linux Python function app, a Logic App workflow (ships disabled, empty) and an Automation account. All three compute resources run as the **user-assigned managed identity that `infra/bicep/core` creates**. This template never creates an identity, a key, a connection string or a stored login. Pattern and rules: `docs/SECRETS.md`.

**Nothing here has been compiled, validated or deployed.** The build machine has no Azure CLI or Bicep, and this repo never deploys (docs/BLUEPRINT.md rule 6): it validates and runs what-if only, and a human does everything below. The static tests in `tests/py/infra/test_b86_compute_pipeline.py` read the files as text; they do not prove the template builds.

## What is in it

| File | What it declares | No-key properties written in the source |
|---|---|---|
| `modules/storageAccount.bicep` | host storage, plus Storage Blob Data Owner for the identity | `allowSharedKeyAccess: false`, no public blobs, TLS 1.2, OAuth default |
| `modules/functionApp.bicep` | app service plan and function app | user-assigned identity, `httpsOnly`, FTPS off, TLS 1.2, host storage by identity (`AzureWebJobsStorage__credential`), FTP and SCM publishing credentials off |
| `modules/logicApp.bicep` | consumption workflow | user-assigned identity, `state: 'Disabled'`, empty definition |
| `modules/automationAccount.bicep` | Automation account | user-assigned identity, `disableLocalAuth: true`, public network access off, no credential or connection resources |
| `main.bicep` | wires them; takes the core identity and workspace ids as parameters | tags on every taggable resource |
| `main.dev.bicepparam`, `main.prod.bicepparam` | placeholders (`<core-identity-resource-id>` ...) and plain names | never add a real id, secret, key or token |

## Order

1. Core first (`infra/bicep/core`): it makes the identity, vault and workspace.
2. Copy that deployment's outputs (`identityId`, `identityPrincipalId`, `clientId`, `workspaceId`) into the compute parameter file in a scratch copy, not in the repo.
3. Compute (this folder).

## Steps a human runs

From this folder, with the tools installed (see `docs/ENVIRONMENT.md`):

```powershell
az bicep build --file main.bicep --stdout > $null     # compiles; errors stop here
az bicep lint --file main.bicep                        # linter warnings
az bicep build-params --file main.dev.bicepparam --stdout > $null
az login
az account set --subscription "<subscription-name-or-id>"
az deployment group validate --resource-group "<existing-resource-group>" --parameters main.dev.bicepparam
az deployment group what-if  --resource-group "<existing-resource-group>" --parameters main.dev.bicepparam
```

The pipeline `infra/azure-pipelines.yml` runs the same build, lint, validate and what-if, then stops at a manual approval; its deploy stage is disabled. Read the what-if before approving anything.

## Known gaps

- Diagnostic settings for the function app, Logic App and Automation account are not written yet; `workspaceId` is accepted and echoed only.
- No private endpoints or VNet integration; the function app is reachable on its public hostname (HTTPS only).
- The identity needs whatever roles each workload really uses (Graph, Key Vault Secrets User from core, and so on); only the storage role is declared here.
- API versions, the B1 plan, `PYTHON|3.12` and the Storage Blob Data Owner role id are from memory (UNVERIFIED).
