# Secrets: managed identity first, Key Vault when a credential cannot be avoided

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only.

Status: **document and Bicep source only** (B-85). Nothing in this repo reads a Key Vault, and nothing has been compiled, validated or deployed (no Azure CLI or Bicep compiler is installed here). Rules: `STD-SC-5`, `STD-CF-7`, `STD-PS-7`, decision `D6-10`, inventory `W-TOOL-08`, controls `C-39`, `C-40`, `C-10`.

## The pattern in one page

1. **Prefer no credential at all.** A workload that runs in Azure signs in with a user-assigned managed identity (`infra/bicep/core/modules/managedIdentity.bicep`). There is nothing to store, leak or rotate.
2. **Where a credential cannot be avoided** (a vendor API that only accepts a client secret or API key), the value lives in Key Vault (RBAC, soft delete and purge protection on), never in the repo, a config file, a log, a prompt or a fixture.
3. **The workload reads it with its managed identity.** The identity holds the built-in role Key Vault Secrets User on the vault (Azure RBAC, not legacy access policies). It can read secret values; it cannot create, change or delete them.
4. **A person sets and rotates the value.** The Bicep never declares a secret, key or certificate, so a deployment can neither create nor overwrite one. Rotation stays a human task (`W-TOOL-08`): the repo may report that a secret is close to expiry, it never changes the value.

## One Key Vault per environment

There is one Key Vault per environment (dev and prod), created by `infra/bicep/core/main.bicep` from `main.dev.bicepparam` or `main.prod.bicepparam`. Secrets are named

    client-<id>-<purpose>

lowercase letters, digits and hyphens, for example `client-contoso-graph-app` or `client-fabrikam-psa-api`. The name says who the credential belongs to and what it is for; it never contains the value. A separate vault per client is created only where a client contract requires it, and that fact is recorded on the client record (`D6-10`). Until a contract says so, do not add one.

The vault, as written in `modules/keyVault.bicep`:

| Property | Value | Why |
|---|---|---|
| `enableRbacAuthorization` | `true` | one permission model, auditable role assignments |
| `enableSoftDelete` / retention | `true` / 90 days | a deleted secret is recoverable |
| `enablePurgeProtection` | `true` | nobody can purge during the retention window; cannot be turned off later |
| `publicNetworkAccess` | `Disabled`, default action `Deny` | reachable only through a private endpoint |
| tags | environment, owner, dataClass, project | cost and ownership |
| diagnostics | `AuditEvent` and metrics to Log Analytics | who read which secret, when |

## How an adapter binding names a secret reference

A client record carries an adapter binding per system (ONB-03: `mock` or a real implementation, plus external ids). A real binding holds a **secret reference**: a name, never a value. Planned shape (a design, not code that exists yet; no loader reads it):

```json
{
  "system": "psa",
  "implementation": "real",
  "credential_ref": { "kind": "key-vault-secret", "secret_name": "client-contoso-psa-api" }
}
```

or, when the target accepts the workload's own identity:

```json
{ "system": "graph", "implementation": "real", "credential_ref": { "kind": "managed-identity" } }
```

Rules for a reference: it matches `client-<id>-<purpose>`; the `<id>` is the same client id as the record, so a Contoso Dental binding can never name a Fabrikam Capital secret (per-client isolation); the vault is chosen by environment, not stored in the record. The value is fetched at call time, held in memory, and never logged (`STD-AU-4`, `STD-AU-5`).

## What goes where

| Thing | Where | Never |
|---|---|---|
| Resource definitions, role assignment, diagnostics | `infra/bicep/core/` | secret values |
| Parameter files | placeholders (`<owner-team-or-person>`) and plain names | keys, tokens, connection strings, real tenant or subscription ids |
| Secret values | typed into Key Vault by a person | the repo, chat, tickets, CI variables in clear |
| Secret names | client records, adapter bindings | the value |

The static tests in `tests/py/infra/test_b85_bicep_core.py` fail if a parameter or template file holds a secret-looking value, if a `@secure()` parameter has a default, if a secret or key resource is declared, or if any script in `infra/`, `scripts/`, `levers/` or CI creates or deploys anything. They check the text of the files only.

## Human steps

- Create the resource group, and later deploy, as a person with the right Azure role, after running validate and what-if (`infra/bicep/core/README.md`). This repo never deploys.
- Give the people who set and rotate secrets a Key Vault Secrets Officer role on the vault, for a limited time (their own task; not in the Bicep).
- Set each secret value in the vault. Rotation is a human task: set a new version, confirm the workload reads it, disable the old one.
- Before a client contract forces a per-client vault, record it on the client record and copy the environment parameter file with a new prefix.

## UNVERIFIED

- Nothing here was compiled, linted, validated, what-if'd or deployed: no `az` or `bicep` exists on the build machine, and no network or cloud call was made.
- Resource API versions (`Microsoft.KeyVault/vaults@2023-07-01` and the others) and the built-in role id for Key Vault Secrets User are written from memory; no Microsoft page was opened.
- Whether `softDeleteRetentionInDays` accepts only the values the template allows, whether `bypass: 'None'` blocks the diagnostic-settings path, and whether the private endpoint alone is enough (a private DNS zone and its link are not in the template) are unchecked.
- The `credential_ref` shape is a proposal. No adapter reads it today.
