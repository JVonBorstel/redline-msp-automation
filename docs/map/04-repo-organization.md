# Map 04: repo organization and GitHub setup

Status: **document-only** (mapping stage, 2026-10-20). No code was written and no folder was created for this map. It fixes where every piece of the job lives in one repo, the few moves from today's layout, naming rules, and how GitHub (labels, milestones, issues, CODEOWNERS, branches and pull requests) is organized. The build order is in `docs/ROADMAP.md` (items `B-nn`, machine twin `map/roadmap.json`).

> Independently built prototype. Synthetic data only. Nothing here describes the MSP's real repositories, teams or tools.

Ids in this file are stable, and other documents may cite them: layout entries `LAY-nn`, moves `M-nn`, kept-in-place decisions `K-nn`, naming rules `NM-nn`, test suites `TS-nn`, GitHub rules `GH-nn`, open questions `RO-nn`.

---

## 1. Principles

1. **Minimal moves.** Phase 1 and Slices A to C are demoed and tested. A path that tests, the demo, CI reference stays where it is unless keeping it blocks the target architecture. Only two moves are planned (section 3).
2. **One owner per path per wave.** The layout is chosen so that each roadmap item owns its own folder or files (one lever family = one PowerShell module + one registry fragment + one fixture file per client + one test file). Shared ledgers are folded once per wave from per-item fragments (`docs/changes/B-nn.md`).
3. **Product code, build tooling and guardrails are separate.** `core/`, `adapters/`, `levers/`, `workflows/`, `rag/`, `mcp/` and `ui/` are the product. `tools/` holds developer scripts (schema generation, roadmap export, ledger folding) that the product never imports. `scripts/` holds the human-only guard scripts and does not change.
4. **Data is separated by client in the path.** Wherever a file holds one client's data, the client id is a path segment (`fixtures/tenant/contoso-dental/...`, `config/clients/contoso-dental.json`, `audit/contoso-dental.jsonl`) and is resolved by one resolver per store (STD-ID-4).

## 2. Target layout

Legend: **exists** = in the repo today; **new (Wn)** = created by the named wave.

```
redline-msp-automation/
  core/                    trusted core; nothing here imports adapters' real implementations
    gateway/               model gateway (exists); budgets (W8), azure_openai adapter (W9)
    levers/                registry, runner, schema, diff, models (exists); pause (W1), bridge (W2), caps (W4), oob (W3)
    audit/                 hash chain and verifier (exists); v2 (W2), router per client (W4), sqlite store (W8)
    identity/              identities and scope (exists)
    guard/                 injection tripwire and wrapper (exists); classify + prompt redaction (W5)
    queue/                 approval queue (exists); sqlite store (W8)
    scheduler/             per-client jobs (new W8)
    obs/                   operational logs, request ids (new W8)
    auth/                  approver sign-in token validation (new W9)
    paths.py               REPO_ROOT (new W2)
  adapters/                one folder per system: interface.py, mock.py, (real.py behind a flag)
    base.py binding.py     result types, per-client binding from config/clients (new W2)
    psa/ graph/            (new W2)
    alerts/                (new W4)
    rmm/ intune/ backup/   (new W6)
    m365/                  Teams, Outlook, SharePoint mocks (new W9)
  levers/
    registry.json          the four Phase 1 levers (exists, stays)
    registry.d/<family>.json  one registry fragment per lever family (new W2)
    python/<family>.py     Python lever handlers for new families (new W2)
    powershell/<Module>/   TenantBaseline (exists); LeverHost, Sample (W2); IdentityOps, CredentialOps,
                           LicenseOps, GroupOps, MailboxOps, Provisioning (W3); MailFlowOps (W4); DeviceOps, DeviceR3 (W6)
    bash/<family>/         macOS and Linux levers (new W6)
  workflows/<name>/        triage (exists); notify (W1); summary, duplicates, sla, replies (W2); ... one folder each
  prompts/                 STANDARDS.md, library/<task>.v<n>.md (new W2)
  rag/                     ingest/, store/, retrieve/ (new W5)
  mcp/                     MCP server over approved levers (new W9)
  ui/                      approval queue and audit viewer (exists)
  evals/<workflow>/        golden sets, report.py, report.md: triage, injection (exist); one per new workflow
  schemas/                 JSON Schema 2020-12 shared by Python and PowerShell (new W2)
  fixtures/<system>/       synthetic data only, client id in the path: graph, tenant, tickets, gateway (exist); psa (W2), ...
  config/                  identities, models, routing (exist); clients/<client-id>.json (new W2, owner-applied)
  infra/
    bicep/core/ compute/   validate and what-if only (new W9)
    azure-pipelines.yml    Azure DevOps twin of .github/workflows/ci.yml (new W9)
  governance/              never-automate.json (W2), ai-vendor-register.json (W9), policies and templates (W10)
  docs/
    map/                   mapping documents 01-05 (this folder)
    runbooks/              one runbook per file (new W3)
    changes/               one change fragment per roadmap item, folded each wave (new W1)
    planned/               outlines (exist); emptied in W10 (move M-07)
  map/                     machine-readable maps: inventory.json, impact.json, controls.json, roadmap.json; check_map.py (exists)
  specs/                   phase-1.md, demo-sprint.md (exist); B-nn.md per roadmap item (new W1)
  tests/
    phase0/                guardrail acceptance tests (exists, human-only)
    phase1/                Phase 1 and Slices A, C pytest suite (exists, stays)
    sliceb/                Slice B PowerShell suite (exists, stays)
    py/<area>/             new pytest suites, one file per item: test_bNN_<slug>.py (new W1)
    ps/                    runner for levers/powershell/*/tests and schema checks (new W2)
    demo/                  demo smoke test (new W1)
  tools/                   developer scripts: roadmap_issues.py, fold_changes.py (W1), gen_schemas.py (W2), ...
  scripts/                 guardrail and hook scripts (exists, human-only, unchanged)
  .github/                 CI, CODEOWNERS, templates (exists, owner-only)
```

| Id | Folder | Holds | Rule |
|---|---|---|---|
| LAY-01 | `core/` | trusted core | No client data at rest, no real-adapter imports. Every permission check lives in `core/levers/runner.py` (D-016). |
| LAY-02 | `adapters/` | one folder per external system | `interface.py` + `mock.py`; a real implementation is selected only by the client binding and fails closed when not configured. An adapter instance serves one client (TEN-04). |
| LAY-03 | `levers/` | lever definitions and implementations | Registry entry + implementation + tests + README per lever (STD-DD-4). A family = one module (or Python file) + one `registry.d` fragment. |
| LAY-04 | `workflows/` | thin loops | Call only the gateway, the guard and the runner (STD-LV-9); never an adapter directly; one eval folder each. |
| LAY-05 | `prompts/` | versioned prompt library | Loaded by name and version; untrusted text only inside the wrapper. |
| LAY-06 | `rag/` | ingestion, store, retrieval | Namespace per client plus one MSP-internal namespace; the filter comes from the lever call. |
| LAY-07 | `mcp/` | MCP server | A front over the runner, read-only by default. |
| LAY-08 | `ui/` | queue and audit viewer | Loopback, CSRF, no scripts (STD-SC-6). |
| LAY-09 | `evals/` | golden sets and reports | Fixture-based labels on every number; thresholds in `evals/gates.json` (W8). |
| LAY-10 | `schemas/` | shared shapes | Generated from pydantic where Python owns the shape; checked in CI (STD-XL-2). |
| LAY-11 | `fixtures/` | synthetic data | Client id in the path; `SOURCES.md` per vendor-shaped folder (STD-FX-2). |
| LAY-12 | `config/` | program config | Protected: owner-applied. Client records here are change-managed by design. |
| LAY-13 | `infra/` | Bicep and Azure pipeline | Validate and what-if only. GitHub Actions stay in `.github/workflows/` because GitHub only reads them there. |
| LAY-14 | `governance/` | policies, registers, never-automate list | Data files here (`*.json`) are read by tests and the registry loader; prose policies are reviewed by the MSP's compliance owner. |
| LAY-15 | `docs/` | human docs | Status line first (STD-DC-1). `docs/map/` is planning; `docs/runbooks/` is operational. |
| LAY-16 | `map/` | machine-readable maps | Generated together with their `docs/` twins; checked by `map/check_map.py` (stdlib, built in the mapping stage) and enforced in CI through `tests/phase1/test_map.py`; `B-06` extends it. |
| LAY-17 | `specs/` | acceptance ids before code | One file per roadmap item from W1; the phase specs stay. |
| LAY-18 | `tests/` | suites | See section 5. |
| LAY-19 | `tools/` | developer scripts | Never imported by product code; print-first (for example the issue exporter prints `gh` commands and runs nothing). |

## 3. What moves, and what deliberately stays

### 3.1 Moves (each one PR, imports and references updated in the same PR, no compatibility shim)

| Id | Today | Target | When | Why | Item |
|---|---|---|---|---|---|
| M-04 | `core/levers/tenant.py` (`MockTenant`) | `adapters/graph/mock_state.py` | end of W3 (exit step) | State for real levers lives behind adapters (SL-04, ARC-05). Moving it earlier would break every Phase 1 test mid-wave | W3-X5 |
| M-07 | `docs/planned/ROI_TRACKER.md`, `STAFF_TRAINING.md`, `CLIENT_CONVERSATION_GUIDE.md`, `TECH_RADAR.md` | `docs/ROI_TRACKER.md`, `docs/STAFF_TRAINING.md`, `docs/CLIENT_CONVERSATION_GUIDE.md`, `docs/TECH_RADAR.md` | W10, when each is filled | An outline becomes a real document; COVERAGE rows A10, D2, D4, D5, D7 are updated in the same fold | `B-95`, `B-96`, `B-97` |

(M-01 to M-03, M-05 and M-06 were considered and rejected; they are recorded as K-rows below so nobody proposes them again without a reason.)

### 3.2 Kept in place

| Id | Path | Considered | Decision and reason |
|---|---|---|---|
| K-01 | `levers/registry.json` | split into fragments | Stays as the core file with the four Phase 1 levers; new families go to `levers/registry.d/` and are merged at load (`B-14`). The demo and docs keep working. |
| K-02 | `core/levers/handlers.py` | move to `levers/python/` | Stays for the four existing handlers; new Python levers go to `levers/python/<family>.py` and are resolved by the `entry` field (`B-14`). |
| K-03 | `tests/phase1/`, `tests/sliceb/` | rename to `tests/py/core`, `tests/ps/sliceb` | Stay. `.github/workflows/ci.yml` and `pyproject.toml` (all protected) reference them, and the demo fallback points at their output. New suites are added beside them. |
| K-04 | `fixtures/tenant/<client>.json` | split per family | The existing file stays (users and authentication methods). New families add `fixtures/tenant/<client>/<family>.json` (read by the Graph mock, `B-19`). |
| K-05 | `levers/powershell/TenantBaseline/` incl. `Test-SummaryReconciles.ps1` and its config | move the validator to `tools/` | Stays: the validator is part of the module's contract (SB-2), and the config is module-private (STD-CF-1). |
| K-06 | `evals/triage/`, `evals/injection/` | regroup | Stay; every new workflow gets `evals/<workflow>/` in the same pattern. |
| K-07 | `docs/BLUEPRINT.md` | edit for drift | The owner's source document; drift notes go beside it (DR-13), not into it. |
| K-08 | `.github/workflows/ci.yml` | move under `infra/` | Stays: GitHub reads workflows only from `.github/workflows/`. `infra/azure-pipelines.yml` is its Azure DevOps twin. |

## 4. Naming

| Id | Thing | Rule | Example |
|---|---|---|---|
| NM-01 | Client id | slug `^[a-z0-9][a-z0-9-]{0,62}$`, the same in every language and file (STD-ID-5) | `contoso-dental`, `fabrikam-capital`, `litware-legal` |
| NM-02 | Lever name | `<object>.<verb>[-words]` from the STD-LV-1 verb list | `user.revoke-sessions`, `license.add` |
| NM-03 | Registry fragment | `levers/registry.d/<object>.json`, one per lever family, `version` field required | `levers/registry.d/license.json` |
| NM-04 | PowerShell module | PascalCase noun + `Ops` for lever families; approved verbs for functions (STD-PS-3) | `LicenseOps\Add-UserLicense` |
| NM-05 | Python lever module | `levers/python/<object>.py`, handler `<object>_<verb>` | `levers/python/contact.py: contact_check` |
| NM-06 | Workflow | `workflows/<snake_case>/` with `__main__.py` CLI, README, and an `evals/<same name>/` folder | `workflows/offboarding/` |
| NM-07 | Notice template | `workflows/notify/templates/<lever>.md` (or a family subfolder) | `user.reset-mfa.md` |
| NM-08 | Fixture | `fixtures/<system>/<client-id>/<thing>.json` or `fixtures/<system>/<client-id>.json`, `_note` first key | `fixtures/tenant/contoso-dental/licenses.json` |
| NM-09 | Schema | `schemas/<shape>.schema.json`, kebab-case shape | `schemas/lever-request.schema.json` |
| NM-10 | Spec | `specs/B-nn.md`; acceptance ids `B<nn>-<k>` | `specs/B-02.md` defines `B02-1`..`B02-4` |
| NM-11 | Test file | `tests/py/<area>/test_b<nn>_<slug>.py`; test functions start with the lowercased acceptance id | `test_b02_3_no_phone_number_in_audit` |
| NM-12 | Change fragment | `docs/changes/B-nn.md` with headings Decisions, Coverage, Changelog, Inventory status, Controls status, Runbooks | `docs/changes/B-04.md` |
| NM-13 | Branch | `<kind>/b<nn>-<slug>`, kind in `feat`, `fix`, `docs`, `chore` (CONTRIBUTING prefixes kept) | `feat/b03-approval-verification` |
| NM-14 | PR and issue title | `B-nn: <roadmap title>` | `B-03: Approval page: verification capture, ...` |
| NM-15 | Commit message | imperative summary line under 72 characters, roadmap id in the body | `Add pause switch to the lever runner` + `Roadmap: B-02` |
| NM-16 | Runbook | `docs/runbooks/<kebab-case>.md`, linted by `tools/lint_runbook.py` (W5) | `docs/runbooks/ai-incident-response.md` |
| NM-17 | Audit chain file | `audit/<client-id>.jsonl` and `audit/_msp.jsonl` under the state folder (W4) | `.tmp/demo/audit/contoso-dental.jsonl` |

## 5. Test suites

Each suite runs with one command and prints one summary line `"<Suite> tests: N passed, M failed"` (STD-TS-5). CI run every suite; a missing tool is reported as skipped, never passed.

| Id | Suite | Path | Command | Covers | Wired by |
|---|---|---|---|---|---|
| TS-01 | Lint and types | `pyproject.toml` | `uv run --frozen ruff check . && uv run --frozen mypy` | style and types | exists |
| TS-02 | Phase1 | `tests/phase1/` | `pwsh -NoProfile -File tests/phase1/Test-Phase1.ps1` | P1, SA, SC tests; ruff; mypy | exists |
| TS-03 | SliceB | `tests/sliceb/` | `pwsh -NoProfile -File tests/sliceb/Test-SliceB.ps1` | SB tests | exists |
| TS-04 | Py | `tests/py/` | `pwsh -NoProfile -File tests/py/Test-Py.ps1` (runs `uv run --frozen pytest tests/py`) | every roadmap item's Python tests, the map integrity test | `B-06`, CI by `B-07` |
| TS-05 | PS modules | `tests/ps/` + `levers/powershell/*/tests/` | `pwsh -NoProfile -File tests/ps/Test-Modules.ps1` | PowerShell lever modules, schema checks from both sides | `B-15`, CI at `W2-E1` |
| TS-06 | Demo | `tests/demo/` | `pwsh -NoProfile -File tests/demo/Test-Demo.ps1` | every command in `docs/DEMO.md` | `B-10`, CI by `B-07` |
| TS-07 | Eval gates | `evals/gates.json` | `uv run python tools/eval_gate.py` | every workflow's fixture-based threshold | `B-84`, CI at W8 entry |

## 6. GitHub organization

Repo: `VonBorstel-J/redline-msp-automation` (private, D-021). Everything in this section that lives in `.github/` or is a GitHub setting is applied by the owner: agents are blocked from both (hooks protected paths). Roadmap item `B-08`, with the commands printed by `B-09`.

### 6.1 Labels

Four families. Each issue and PR carries exactly one `type:`, at least one `area:`, exactly one `risk:` and at least one `phase:`. Waves are milestones, not labels.

| Label | Description |
|---|---|
| `area:sd` | Service desk (tiers 1-3) |
| `area:onb` | User onboarding and offboarding |
| `area:idm` | Identity and MFA |
| `area:m365` | Microsoft 365 administration |
| `area:ep` | Endpoint management |
| `area:pat` | Patching |
| `area:bdr` | Backup and disaster recovery |
| `area:sec` | Security monitoring and alerting |
| `area:cmp` | Compliance evidence |
| `area:vnd` | Vendor and license management |
| `area:rpt` | Client reporting and QBRs |
| `area:kb` | Documentation and knowledge base |
| `area:bil` | Billing inputs |
| `area:prj` | Project work |
| `area:tool` | Internal tooling and the AI/automation platform |
| `area:gov` | AI governance |
| `area:trn` | Staff training on AI |
| `type:lever` | adds or changes a lever (registry entry plus implementation) |
| `type:workflow` | adds or changes a workflow and its evals |
| `type:adapter` | adds or changes an adapter interface or mock |
| `type:platform` | core runner, audit, gateway, queue, schemas, scheduler |
| `type:eval` | golden sets, scorers, gates |
| `type:drift` | closes a `DR-nn` row from map 03 |
| `type:fix` | a defect |
| `type:docs` | documentation only |
| `type:governance` | policy, register, never-automate list |
| `type:infra` | Bicep, pipelines, containers |
| `type:owner` | touches protected files; the owner applies |
| `risk:R0` | read-only: changes nothing (governance 6.1) |
| `risk:R1` | reversible, low impact |
| `risk:R2` | reversible, high impact (a person's access or work) |
| `risk:R3` | irreversible or broad; dual approval |
| `phase:0` .. `phase:11` | the blueprint phase whose deliverable this advances (keeps `docs/COVERAGE.md` traceable) |
| `status:needs-owner` | waiting on the owner for a protected-file change or an install |
| `status:blocked-external` | waiting on an answer only the MSP can give (cite the question id) |
| `status:cut` | dropped at a freeze; returns in a later wave |

`risk:` is the highest risk class of any lever the change adds or alters (platform changes that affect all levers take `risk:R3`).

### 6.2 Milestones

One per wave, `W1` to `W10`, titled `W<n>: <wave name>`, with the wave goal from `docs/ROADMAP.md` as its description and the wave's estimated end as its due date. Closing a milestone requires the wave's exit steps (`Wn-X1`..). The W1 milestone is due 2026-10-25 (the demo freeze).

### 6.3 Issue form fields (`.github/ISSUE_TEMPLATE/work-item.yml`)

One issue per roadmap item. Blank issues are disabled (`config.yml`), so every issue uses the form.

| Field | Required | Content |
|---|---|---|
| Roadmap id | yes | `B-nn` (the issue title is `B-nn: <title>`) |
| Inventory ids | yes | `W-<AREA>-<nn>` list, from `map/inventory.json` |
| Impact chain id | yes | the inventory id of each chain the item touches (a chain in `map/impact.json` is keyed by its `inventory_id`; ROADMAP RF-02), plus four lines: L1 one person, L2 client business, L3 MSP, L4 community (STD-DD-10) |
| Controls | yes | `C-nn` list from `map/controls.json` |
| Standards | yes | STD sections the item follows (for example `STD-LV`, `STD-TS`) |
| Acceptance tests | yes | checkboxes, one per `B<nn>-<k>` |
| Owned paths | yes | copied from the roadmap; the PR may touch nothing else |
| Depends on | no | `B-nn` list |
| Risk class | yes | dropdown R0 to R3 (governance definitions) |
| Size | yes | dropdown S, M (L is not allowed: split first) |
| Blocking questions | no | question ids from any map: `Q-` (01), `IQ-` (02), `OQ-` (03), `RO-` (04), `GQ-` (05), `RQ-` (ROADMAP); index in `docs/map/README.md` |
| Synthetic data only | yes | checkbox: "This work uses only synthetic data and invented names." |

A sketch of the form (owner to commit in `B-08`):

```yaml
name: Work item
description: One roadmap item (docs/ROADMAP.md)
title: "B-nn: "
body:
  - type: input
    id: roadmap
    attributes: {label: Roadmap id, placeholder: B-03}
    validations: {required: true}
  - type: input
    id: inventory
    attributes: {label: Inventory ids, placeholder: "W-IDM-02, W-IDM-04"}
    validations: {required: true}
  - type: textarea
    id: impact
    attributes: {label: "Impact chain ids (inventory ids) and L1-L4 lines"}
    validations: {required: true}
  - type: input
    id: controls
    attributes: {label: Controls, placeholder: "C-30, C-06"}
    validations: {required: true}
  - type: textarea
    id: acceptance
    attributes: {label: Acceptance tests, description: "One '- [ ] B03-1: ...' line per test"}
    validations: {required: true}
  - type: textarea
    id: owns
    attributes: {label: Owned paths}
    validations: {required: true}
  - type: dropdown
    id: risk
    attributes: {label: Risk class, options: [R0, R1, R2, R3]}
    validations: {required: true}
  - type: dropdown
    id: size
    attributes: {label: Size, options: [S, M]}
    validations: {required: true}
  - type: checkboxes
    id: synthetic
    attributes:
      label: Data
      options:
        - label: This work uses only synthetic data and invented names.
          required: true
```

### 6.4 CODEOWNERS (target)

Today every path is owned by `@VonBorstel-J`, with explicit lines for the guardrails. The target keeps that, and adds explicit lines for the paths whose review carries the most risk, so a later second reviewer (at the MSP, a named role) can be added per path without restructuring:

```
*                               @VonBorstel-J
# Guardrails and CI (existing)
/docs/BLUEPRINT.md  /scripts/  /.github/   @VonBorstel-J
# Permissions and evidence: every change here changes what automation may do
/core/levers/                   @VonBorstel-J
/core/audit/                    @VonBorstel-J
/core/identity/                 @VonBorstel-J
/levers/registry.json           @VonBorstel-J
/levers/registry.d/             @VonBorstel-J
/config/                        @VonBorstel-J
/governance/                    @VonBorstel-J
/schemas/                       @VonBorstel-J
/infra/                         @VonBorstel-J
```

(Real CODEOWNERS syntax takes one path per line; the guardrail line above is shortened for reading and is written out in full in `B-08`.) At the MSP the same paths would map to roles (for example an automation lead for `levers/`, the security or compliance owner for `governance/` and `core/audit/`), named only once the MSP says who holds them (GQ-01 in map 05).

### 6.5 Branches and pull requests

| Id | Rule |
|---|---|
| GH-01 | `main` changes only through pull requests; never commit to `main` (CONTRIBUTING). |
| GH-02 | One roadmap item per PR; branch `<kind>/b<nn>-<slug>` (NM-13); PR title `B-nn: <title>`; body links the issue (`Closes #n`). |
| GH-03 | A PR touches only the item's owned paths; the map integrity test enforces ownership across the roadmap; reviewers reject any other path. |
| GH-04 | Each commit fits the commit budget (12 files, 800 lines). A bigger change is split into items, not squeezed. |
| GH-05 | Required before merge: CI green (all suites in section 5 that exist), the owner's review (CODEOWNERS), the PR checklist complete including the L1 to L4 lines. AI agents never approve or merge. |
| GH-06 | Merge commit, then delete the branch. Squash and rebase merges are turned off in the repo settings, so the commit CI tested is exactly what lands (the build automation sets aside a squash or rebase merge). No force-push to `main`, no history rewrite. |
| GH-07 | Protected paths (`.github/**`, `config/**`, `pyproject.toml`, `uv.lock`, guardrails) carry `type:owner` and `status:needs-owner`; the agent puts the exact diff in its change fragment and the owner applies it. |
| GH-08 | Freeze: the W1 freeze commit is tagged `demo-2026-10-27`; nothing merges to `main` between the freeze and the demo. |
| GH-09 | Release tags follow SemVer for the Python project (`v0.<wave>.0` at each wave exit while pre-1.0, STD-VR-1), with the CHANGELOG folded first. |
| GH-10 | A wave's milestone closes only after its exit steps; the next wave's issues are created only after the owner's yes on the wave report. |

**Enforcement caveat (verify).** GitHub's documentation describes branch protection and rulesets per plan, and on the page read on 2026-10-20 branch restrictions are listed for public repositories on GitHub Free and for all repositories on GitHub Team or Enterprise Cloud. Whether a **private** repository on a free personal plan can enforce required checks and reviews is **UNVERIFIED** here ([about protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)). If it cannot, GH-01 to GH-06 hold by convention, its own gates and CI status, and the repo says so; making the repo public (D-008) would enable enforcement for free (RO-02).

### 6.6 PR template additions

Keep today's checklist and add three lines: the roadmap id and issue link; "this PR touches only the paths the roadmap item owns"; and the four traceability lines (L1 one person at one client, L2 the client business, L3 the MSP, L4 the community), with the impact chain id if one exists.

### 6.7 The same organization in Azure DevOps

If the MSP uses Azure DevOps, the work can move there and the mapping is one to one, and `tools/roadmap_issues.py --format ado-csv` (`B-09`) produces the import:

| GitHub | Azure DevOps |
|---|---|
| issue from the form | work item (User Story), roadmap fields as custom fields or description sections |
| labels `area:` `type:` `risk:` `phase:` | tags with the same text |
| milestone per wave | iteration per wave |
| CODEOWNERS | branch policy: automatically included reviewers per path |
| required checks | branch policy: build validation with `infra/azure-pipelines.yml` |
| Actions `ci.yml` | Pipelines `azure-pipelines.yml` (`B-86`) |

## 7. Protected paths (who may edit)

From the repository's protected-path list. Agents never edit these. When a roadmap item needs a change here, it is an owner-only item or a wave entry step.

`docs/BLUEPRINT.md`, `scripts/hooks/**`, `scripts/install-hooks.ps1`, `scripts/clean.ps1`, `.github/**`, `LICENSE`, `SECURITY.md`, `.gitignore`, `.gitattributes`, `.env.example`, `pyproject.toml`, `uv.lock`, `config/**`.

Two consequences built into the roadmap: client records (`config/clients/`) and identities are owner-applied, which matches their role as change-managed access data, and widening `pytest`/`mypy` coverage in `pyproject.toml` happens at wave entry, after the code passes.

## 8. Open questions only the owner or the MSP can answer

| Id | Question | Who | Why it matters |
|---|---|---|---|
| RO-01 | Approve the two moves (M-04, M-07) and the kept-in-place decisions (K-01 to K-08)? **Decided: see 06-decisions.md D6-27.** | The owner | Avoids moves being re-litigated per PR |
| RO-02 | Private repo without enforced branch protection, a paid plan, or a public repo (D-008)? **the owner's call: see 06-decisions.md J-01** (recommendation there). | The owner | GH-05 enforcement |
| RO-03 | Should the labels and milestones be created now (W1) or after the demo? They are metadata only and do not touch the demo. **Decided: see 06-decisions.md D6-28; the owner runs J-02.** | The owner | `B-08` timing |
| RO-04 | Confirm `litware-legal` (a professional-services firm, Microsoft fictitious name) as the third synthetic client for W2. Note: the impact-chain personas in map 02 use "Woodgrove Legal" and "Northwind Bookkeeping" for the same kinds of client; either rename the personas or make the fixture `woodgrove-legal`, so one name is used everywhere (STD-ID-5). **Decided: see 06-decisions.md D6-13.** | The owner | fixtures, isolation tests with three clients |
| RO-05 | Would the MSP want this program in GitHub or in Azure DevOps Repos and Boards, and is a monorepo acceptable to them? **Decided: see 06-decisions.md D6-02.** | The MSP | section 6.7; adoption after hire |
| RO-06 | Who at the MSP would own review of `levers/`, `governance/` and `core/audit/` (the CODEOWNERS roles)? **Decided: see 06-decisions.md D6-29.** | The MSP | section 6.4 |
