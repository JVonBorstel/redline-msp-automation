# infra/bicep/core: Key Vault, managed identity, Log Analytics

> Independently built prototype. Not affiliated with any vendor's or real company's systems.

Resource-group-scope Bicep for one environment: a Log Analytics workspace, a user-assigned managed identity, a Key Vault (Azure RBAC, soft delete, purge protection, public access disabled) and diagnostic settings that send the vault's audit events to the workspace. Pattern and rules: `docs/SECRETS.md`.

**Nothing here has been compiled, validated or deployed.** The build machine has no Azure CLI or Bicep. This repo only validates and runs what-if; it never deploys (docs/BLUEPRINT.md rule 6). The commands below are for a human, in a subscription they choose, and nothing in this repo runs them.

## Files

- `main.bicep` wires the modules together. `modules/` holds `logAnalytics`, `managedIdentity`, `keyVault`, `diagnosticSettings`.
- `main.dev.bicepparam`, `main.prod.bicepparam`: placeholders and plain names only. Replace `<owner-team-or-person>` and `<data-class>` before a what-if. Never add a secret, key, token or real id.

## Steps a human runs

Install the tools first (see `docs/ENVIRONMENT.md`). From this folder:

```powershell
az bicep build --file main.bicep --stdout > $null     # compiles; errors stop here
az bicep lint --file main.bicep                        # linter warnings
az bicep build-params --file main.dev.bicepparam --stdout > $null
az login
az account set --subscription "<subscription-name-or-id>"
az deployment group validate --resource-group "<existing-resource-group>" --parameters main.dev.bicepparam
az deployment group what-if  --resource-group "<existing-resource-group>" --parameters main.dev.bicepparam
```

Read the what-if output. The expected result for a new environment is create-only: one workspace, one identity, one vault, one role assignment, one diagnostic setting (and a private endpoint if a subnet id was given). Anything marked delete or modify is a stop. Repeat with `main.prod.bicepparam`. Deploying is a separate, human decision outside this repo.

If a compile or lint step fails, fix the template and add the finding to `docs/changes/B-85.md`: the static tests in `tests/py/infra/` do not replace the compiler.
