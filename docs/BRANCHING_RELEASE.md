# Branching and release

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only.

Status: **document only** (B-86). Nothing here is a running process. Rules cited: `CONTRIBUTING.md`, `GH-01` to `GH-10` (`docs/map/04-repo-organization.md`), `STD-VR-1` to `STD-VR-4` (`docs/STANDARDS.md`), `CM-1` to `CM-8` (`docs/map/05-governance.md`). What is enforced by a tool and what holds by convention is stated in each section. Anything not checked against a source is in the UNVERIFIED list at the end.

## 1. Branches

| Branch | Purpose | Rule |
|---|---|---|
| `main` | the released line | changes arrive only through a pull request (`GH-01`); never commit to it; no force-push, no history rewrite (`GH-06`) |
| `enterprise` | the integration line the enterprise roadmap items land on before they are folded into `main` | same pull request and CI rules as `main`; folded into `main` only after the owner's yes on the wave report (`GH-10`) |
| `<kind>/b<nn>-<slug>` | one roadmap item, kind in `feat`, `fix`, `docs`, `chore` (`NM-13`) | cut from the line it will merge into; one item per branch; deleted after merge |

Local worktree branches that agents use (`ent-b86` and the like) are working copies of the same rule: one item, one branch, merged by a human.

## 2. Pull request rules

1. One roadmap item per pull request; title `B-nn: <title>`; the body links the issue and fills the checklist including the four L1 to L4 lines (`GH-02`, `GH-05`).
2. The pull request touches only the paths the item owns (`GH-03`). Protected paths (`.github/**`, `config/**`, `pyproject.toml`, `uv.lock`, guardrails) carry the exact proposed diff in the change note and the owner applies it (`GH-07`).
3. Each commit stays inside the commit budget (12 files, 800 lines); a bigger change is split into items (`GH-04`).
4. CI is green before merge: the `ci` workflow (Python on Linux, PowerShell on Windows) on every pull request, plus the Azure DevOps pipeline `infra/azure-pipelines.yml` if it is adopted (section 6).
5. The owner reviews (`.github/CODEOWNERS`). Agents never approve or merge. Nobody approves their own change (`CM-1`).
6. Merge commit, then delete the branch. Squash and rebase merges are off so the tested commit is the merged commit (`GH-06`).

Enforcement: the review and CI rules are **convention plus its own gates** until branch protection is confirmed to work for this repository. Whether branch protection and required checks are enforceable on a private repository on the current GitHub plan is UNVERIFIED (see the caveat under `GH-06` in `docs/map/04-repo-organization.md`). Do not state it as enforced.

## 3. Versioning (STD-VR)

- **SemVer** for the Python project and each PowerShell module (`STD-VR-1`). Pre-1.0 while this is a prototype: a minor bump may break.
- **Release tags** `v0.<wave>.0` at each wave exit (`GH-09`), made on `main` by the owner after the CHANGELOG is folded.
- **Data versions are integers** (`STD-VR-2`): registry and config `version`, audit record `v`, `lever_version`. A reader rejects an unknown version.
- **CHANGELOG** (`STD-VR-3`): one entry per merged pull request that changes behaviour, contracts or schemas, sections Added, Changed, Fixed, Security, Migration. The file does not exist yet (`DR-11`); change notes in `docs/changes/` carry the proposed line until it does.
- Infrastructure templates (`infra/bicep/`) are versioned by the tag of the commit they are in. There is no separate infrastructure version.

## 4. Staged rollout rings (CM-5)

A change that acts on client tenants (a lever, a schema, a routing threshold, a prompt, a workflow) rolls out in rings. Each ring holds for a set time with no wrong-action incident and an acceptable correction rate before the next one opens. A human decides each promotion; no pipeline promotes a ring.

| Ring | Who gets it | Gate to open the next ring |
|---|---|---|
| R0 | the test tenant (synthetic) | all suites and the eval gate green; dry-run diffs reviewed |
| R1 | one pilot client tenant, only with that client's written agreement (`D6-25`: a small financial-services volunteer, R0-class levers only for the first 30 days) | hold period with no wrong-action incident; corrections reviewed by the lead |
| R2 | about 10% of tenants | hold period; audit chain verified; no open incident |
| R3 | all tenants | owner's decision, recorded in the release note |

Status: `CM-5` is **planned**. The ring membership list, the hold times and the per-tenant switch do not exist in code yet; the numbers above are the governance map's, not measured values. Hold durations are to be set with the first pilot client (open question `GQ-10`, `D6-25`).

## 5. Rollback (CM-6) and emergency changes

- Every rollout has a rollback path **before** it starts. The previous lever version stays registered, and a tenant can be pinned per tenant to it. Rolling back means pinning affected tenants to the previous version, then reverting on `main` through a normal pull request.
- Status: `CM-6` is **planned**. Today the registry has one file-level `version` (`C-29`, `C-37`); per-tenant pinning is not built.
- Rolling back a person's changed account is a separate path: restore the person first, using the before-state in the audit diff (`IR-3`).
- Infrastructure: rollback is a reviewed revert of the template change followed by the same validate, what-if and approval path. There is no "undo" button and none is simulated.
- Emergency changes (`CM-7`, planned) may skip the rings but never review; they are reviewed again within two business days.

## 6. Infrastructure pipeline: what-if first, a person approves, no deploy

`infra/azure-pipelines.yml` is a **proposal** for a human to register in Azure DevOps. Its stages, in order:

1. **Test** runs the same suites as `.github/workflows/ci.yml`, plus the eval gate (`tools/eval_gate.py`).
2. **Lint** builds and lints `infra/bicep/core` and `infra/bicep/compute`, with no cloud sign-in.
3. **WhatIf** runs validate and what-if against an existing resource group and keeps the output as an artifact. It is skipped on pull requests.
4. **Approval** waits for a person in Azure DevOps (manual validation). A timeout rejects.
5. **Deploy** is disabled (`condition: false`) and only echoes.

No agent deploys, and no pipeline stage in this repository deploys. Turning the deploy stage on is a reviewed change by the owner, with an Azure DevOps environment that has its own approval check, and the deploy step is written then, not now. Validate and what-if are the only cloud-touching steps in the repo, and they are read-only. Never put a secret, key or token in the pipeline file; the service connection is a name, created and held by a human.

## 7. Freeze and release checklist

1. Freeze: tag the freeze commit (`GH-08`: the W1 freeze is tagged `demo-2026-10-27`); nothing merges to `main` between a freeze and its event.
2. Fold the CHANGELOG entries from `docs/changes/`; confirm the release note names the rings the change will use.
3. All suites and the eval gate green on the commit to be tagged.
4. Owner tags `v0.<wave>.0` and closes the milestone only after the wave exit steps (`GH-10`).
5. For infrastructure: the what-if artifact was read, the approval was given by someone who did not write the change, and the deploy was run by a human.

## UNVERIFIED

- Whether branch protection and required checks can be enforced on this repository's plan (`GH-06` caveat).
- The Azure DevOps task names and versions used in the pipeline (`ManualValidation@1`, `AzureCLI@2`, `UsePythonVersion@0`, `PublishPipelineArtifact@1`), the hosted-agent image contents (Azure CLI, PowerShell, Python present), and whether the repository will be hosted on GitHub or Azure Repos (this decides how pull request triggers apply).
- Ring hold times, thresholds and the pilot client: none are set or measured.
- The CHANGELOG, per-tenant version pinning and the ring switch are not built.
