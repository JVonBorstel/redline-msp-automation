# Engineering standards

Status: **document-only** (written 2026-10-20, mapping stage). These are the rules every new piece of this repo follows. They are taken from what the Phase 1 code and Slices A, B and C already do well (lever runner, audit chain, gateway, guard, queue, TenantBaseline), so following them does not mean rewriting anything that exists. Where today's code departs from a rule, the gap and the smallest fix are listed in `docs/map/03-architecture-target.md`, section 8 (drift table, ids `DR-nn`).

> Independently built prototype. Synthetic data only. Nothing here describes a production system.

**Precedence.** docs/BLUEPRINT.md hard rules first, then this file, then local habits. An exception to a rule here needs a `docs/DECISIONS.md` entry (`D-nnn`) that names the rule id.

**Rule ids.** Every rule has a stable id, `STD-<area>-<n>`. Ids are never reused or renumbered; a retired rule stays in place, struck through, with the decision that retired it. Words: **must** = enforced or will be enforced by a test or CI check; **should** = expected, reviewers ask why if not; **proposed** = agreed direction, not built yet.

| Area | Prefix | Section |
|------|--------|---------|
| Lever contract | STD-LV | 1 |
| Proposal contract | STD-PR | 2 |
| Identity and client scoping | STD-ID | 3 |
| Audit record | STD-AU | 4 |
| Config files | STD-CF | 5 |
| Error model | STD-ER | 6 |
| Python | STD-PY | 7 |
| PowerShell | STD-PS | 8 |
| Cross-language contract | STD-XL | 9 |
| Testing | STD-TS | 10 |
| Fixtures | STD-FX | 11 |
| Docs | STD-DC | 12 |
| Security defaults | STD-SC | 13 |
| Versioning and changelog | STD-VR | 14 |
| Definition of done | STD-DD | 15 |

---

## 1. Lever contract (STD-LV)

A **lever** is one deterministic, tested action. A model may pick a lever and fill its parameters; the lever runner (`core/levers/runner.py`) decides whether it runs. Permissions live on the lever definition in `levers/registry.json`, never in a prompt or a workflow.

### 1.1 Registry fields

Today's fields (enforced by `LeverDef` in `core/levers/models.py`, `extra="forbid"`, frozen):

| Field | Type | Rule |
|-------|------|------|
| `name` | string | STD-LV-1 naming below. Unique in the registry (load fails on a duplicate). |
| `description` | string, non-empty | One sentence a technician understands, and the word "Mock" while it is mock-backed. |
| `client_scope` | `"any"` or non-empty list of client ids | Where the lever may run at all. Identity scope is checked separately (STD-ID-3). |
| `required_role` | `agent` \| `technician` \| `lead` | Role needed to **execute**. |
| `dry_run_role` | role, optional | Role needed to **dry-run** (propose). Defaults to `required_role`. Set to `agent` so an agent can propose a write it can never execute. |
| `class` | `read` \| `write` | STD-LV-3. |
| `approval` | `none` \| `lead` | STD-LV-4. |
| `idempotency_keys` | list of param names | STD-LV-6. Each must name a declared param (load fails otherwise). |
| `params` | map name to ParamSpec | Types `string` \| `integer` \| `boolean`; `required`, `enum`, `max_length`, `pattern` (strings), `minimum`/`maximum` (integers), `description`. Every string param must have `max_length`; free-text params also need a `pattern` or an `enum` unless they only go to the audit trail (like `reason`). |
| `dry_run` | bool | Must be `true` for every write lever (load fails otherwise). |
| `timeout_s` | number, 0 < t <= 60 | STD-LV-7. |

Proposed additive fields (STD-LV-10). Each is optional with a default that reproduces today's behaviour, so the existing four levers load unchanged and the registry file stays `version: 1`. The one exception is `risk_class` and `impact`, which become required on write levers in `B-01`; that item adds them to the two existing write levers in the same change, so no registry file in the repo stops loading (recorded as a DECISIONS entry at the W1 fold):

| Field | Default | Purpose |
|-------|---------|---------|
| `runtime` | `"python"` | `"python"` (handler in `HANDLERS`) or `"powershell"` (STD-LV-11). |
| `entry` | the lever name | For PowerShell: `"<Module>\\<Function>"`. For Python: the `HANDLERS` key. |
| `lever_version` | `1` | Bumped when behaviour changes; written into every audit record (STD-AU-2). |
| `reversibility` | `"reversible"` for write, `"n/a"` for read | `"irreversible"` (for example a mailbox purge) adds the rule in STD-LV-4. |
| `undo` | none | Name of the lever that reverses this one (for example `user.disable` to `user.enable`). Shown on the approval page. |
| `graph_scopes` | `[]` | Least-privilege Microsoft Graph application permissions the real adapter needs (STD-SC-4). |
| `adapter` | none | Which adapter interface the handler uses (`graph`, `psa`, `rmm`, `kb`), so a client's adapter binding can be checked before the lever runs. |
| `owner` | none | Who maintains it (a role or person id, synthetic in this repo). |
| `risk_class` | **required on write levers** (from `B-01`); `"R0"` for read | `R0`-`R3` as defined in `docs/map/05-governance.md` section 6.1 (control `C-29`). Must agree with `class`: a `read` lever is `R0`, a `write` lever is `R1`-`R3` (load fails otherwise). |
| `impact` | **required on write levers** (from `B-01`) | Four one-line strings `L1`-`L4`: who the lever affects at one person, the client business, the MSP and the community (STD-DD-10). Shown on the approval page. |
| `verification` | none | `"requester"` (write levers only): execute needs an approval that records how the requester was verified out of band (`C-30`, governance HO-4). |

### 1.2 Rules

- **STD-LV-1 Naming.** `<object>.<action>`, all lowercase, matching `^[a-z][a-z0-9]*(\.[a-z][a-z0-9-]*)+$`, at most 64 characters (the `LeverName` type). The object is a noun for the thing acted on: `user`, `ticket`, `kb`, `mailbox`, `device`, `group`, `license`, `role`, `ca` (Conditional Access), `tenant`. The action starts with a verb, then optional kebab-case words: `get`, `search`, `disable`, `reset-mfa`, `remove-member`, `block-legacy-auth`. Verbs come from a short list so names stay predictable:
  - read: `get` (one item by id), `list` (many), `search` (query), `check` (a computed finding);
  - write: `add`, `remove`, `set`, `enable`, `disable`, `reset`, `revoke`, `grant`, `block`, `unblock`, `new`, `require`.
  A new verb needs a DECISIONS entry. Examples in the repo: `ticket.get`, `kb.search`, `user.reset-mfa`, `user.disable`.
- **STD-LV-2 Registration is the only door.** A name not in the registry is denied and audited. A registry entry without an implementation fails the load. One bad entry fails the whole load (fail closed, `RegistryError`).
- **STD-LV-3 Classes.** `read` returns data and must not change state: the runner diffs the state copy after a read and discards the call as an error if anything changed. `write` changes state only through the runner's diff-and-save path. There is no third class. Risk is a separate field, `risk_class` (`R0`-`R3`, governance section 6.1), together with `approval` and `reversibility`; `class` and `risk_class` must agree (STD-LV-10 table).
- **STD-LV-4 Approval.** Every `write` lever has `approval: lead` and `dry_run: true` (load fails otherwise). An approval is bound to the exact lever, client and canonical-JSON params; it comes from an identity with role `lead` who is scoped to that client and is not the requester (four-eyes). Proposed: an `R3` lever needs two approvals from two different leads, neither the requester, both scoped to the client (governance HO-3, `B-28`; who the second approver is stays open, RQ-06), and an `irreversible` lever also needs the approval to be younger than 24 hours and shows the `undo` gap on the approval page.
- **STD-LV-5 Dry-run is the default and returns a diff.** `mode` defaults to `dry-run`. The diff is a list of `Change` objects, sorted by path:
  ```json
  {"op": "add" | "remove" | "replace", "path": "/users/<id>/accountEnabled", "before": true, "after": false}
  ```
  `path` is slash-separated from the client's state root. Lists of objects that all carry a string `id` are keyed by `id` (removing one item is one `remove`, not a cascade). `before` is omitted on `add`, `after` on `remove`. Nothing is saved in dry-run. Execute writes the audit record first, then saves (a change is never applied without its record).
- **STD-LV-6 Idempotency.** Every write handler must be **convergent**: run it twice on the same state with the same params and the second diff is empty (the runner reports "no change: already in the desired state" and saves nothing). The idempotency key is `"<lever>/<client>/<k>=<v>/..."` over `idempotency_keys` in declared order, and is written into the audit result. Proposed (STD-LV-6a): before an execute, the runner refuses a call whose key already has an `applied: true` record that this approval did not authorise.
- **STD-LV-7 Timeout.** Every lever declares `timeout_s` (at most 60). A Python handler runs on a private deep copy of one client's state in a daemon thread; a late result is discarded and nothing is saved. A PowerShell lever runs in a child process that is killed at the timeout (STD-LV-11). Long work (bulk reports, evidence bundles) is a scheduled job (target architecture), not a long lever.
- **STD-LV-8 Handler shape.** Python: `handler(state: JsonDict, params: Mapping[str, Any]) -> Any`. It receives one client's state copy and validated params only, never the identity, the client list, a path, a credential or another client's data. It raises `LeverFailed` for an expected failure ("no user ... in this client's tenant"). Anything else it raises is reported as `lever crashed: <ExceptionType>` and never reaches the caller.
- **STD-LV-9 Parameters come from trusted fields.** A workflow fills lever params from form fields or validated structured data (a ticket's `affected_user`, a finding's `userId`), never from free text or model output (D-022). If a model must supply a value, it is checked against the schema and against a lookup in the client's own data before the dry-run.
- **STD-LV-10 Schema evolution.** New registry fields are optional with a backward-compatible default. Removing or retyping a field bumps the registry file `version` and ships a migration note in the CHANGELOG (STD-VR-3).
- **STD-LV-11 PowerShell levers (proposed).** A lever with `runtime: "powershell"` is a function in a module under `levers/powershell/<Module>/`. The Python runner keeps every check (registry, schema, role, scope, approval, audit) and calls a single bridge that starts `pwsh -NoProfile -NonInteractive`, passes one JSON request on stdin (`schemas/lever-request.schema.json`) and reads one JSON result from stdout (`schemas/lever-result.schema.json`). Dry-run maps to `-WhatIf`. The PowerShell function never decides permissions; it trusts that the runner already did, and it receives only the one client's adapter context.

## 2. Proposal contract (STD-PR)

A **proposal** is a dry-run that passed and now waits for a lead. The shape is `Proposal` in `core/queue/store.py` (frozen, `extra="forbid"`):

| Field | Rule |
|-------|------|
| `id` | `"P-"` + first 12 hex of SHA-256 over `lever + client + canonical_json(params)`. Same action proposed twice (two tickets, or triage and the baseline) gets the same id and is stored once. |
| `source` | Where it came from: `triage` \| `baseline` today. A new source is added to the `Source` literal in one place (STD-PR-5). |
| `ref` | The ticket id, finding id or job id that caused it (one line, at most 64 characters). |
| `lever`, `client`, `params` | Must be a registered `write` lever with schema-valid params, checked again on `add`. Params are strict scalars. |
| `requested_by` | The human technician who will be recorded as the requester; never an agent (STD-PR-2). |
| `reason` | One line, at most 200 characters: why, in words a lead can check. |
| `created`, `decided_at` | UTC ISO 8601 with `Z`. |
| `status` | `pending` → `approved` → `executed` \| `failed`; or `pending` → `rejected`. |
| `decided_by` | Set exactly when status is not `pending`. |

- **STD-PR-1 Proposals are created only from an allowed dry-run.** A workflow dry-runs the lever through the runner as its agent identity (audited), and only an `ok` dry-run becomes a proposal.
- **STD-PR-2 The requester is a human.** Agents propose; a human technician with the lever's `required_role` and scope for the client is `requested_by`; a different lead decides. Approving executes the lever as `requested_by` with the lead as approver, so the audit names both.
- **STD-PR-3 Approve-then-execute.** The proposal is saved as `approved` before the runner executes, so a crash can never leave it `pending` and run it twice. A `failed` proposal is not retried automatically; a new proposal is made.
- **STD-PR-4 Every decision is audited**, including refused attempts (not a lead, wrong client, own proposal).
- **STD-PR-5 One definition.** The id function, the `Source` literal and the timestamp helper exist once, in `core/queue`. Producers import them (see DR-01).
- **STD-PR-6 Explainable.** A proposal shown to a lead must carry, or link to, the why, the data used and the dry-run diff (docs/BLUEPRINT.md, "explainable").

## 3. Identity and client scoping (STD-ID)

- **STD-ID-1 Every actor has an identity**: technicians, leads and each agent (one identity per agent, for example `triage-bot`). Identities load from `config/identities.json`; an unknown id is a denial, never a default.
- **STD-ID-2 Roles are ranked** `agent < technician < lead`. A lever that needs `technician` accepts a lead, never an agent. No new role without a DECISIONS entry and a runner test.
- **STD-ID-3 Two scope checks, both in code.** The identity must list the client (`can_act_for`), and the lever's `client_scope` must include it. Both happen in the runner, before any handler or adapter is touched.
- **STD-ID-4 Client is explicit.** Every function that touches client data takes `client` as an explicit argument. There is no ambient "current client" (no global, no environment variable, no thread-local). A client id is a slug, `^[a-z0-9][a-z0-9-]{0,62}$`, and is the only thing that becomes part of a path, through one resolver per store (today `MockTenant.path_for`).
- **STD-ID-5 Client ids are canonical and the same in every language and file**: `contoso-dental`, not `contoso` (see DR-05). Display names live next to the id, never instead of it.
- **STD-ID-6 One client per unit of work.** A lever call, a prompt, a retrieval, a report and a proposal each concern exactly one client. Cross-client views (an MSP dashboard) aggregate results that were each produced under one client.
- **STD-ID-7 Demo sign-in is not authentication.** The UI identity picker is labelled as a demo. Real deployments sign in through Microsoft Entra ID (target architecture); nothing in this repo pretends otherwise.

## 4. Audit record (STD-AU)

The product audit log is `core/audit/chain.py`: append-only JSON lines, SHA-256 chain over canonical JSON (sorted keys, no spaces, UTF-8), plus a head pin file. The verifier (`python -m core.audit.verify <log>`) exits 0 on an intact chain and names the first broken `seq`.

### 4.1 Schema (version 1, today)

| Field | Meaning |
|-------|---------|
| `seq` | 1, 2, 3 ... with no gaps |
| `ts` | UTC, millisecond precision, `Z` |
| `agent` | The acting identity id (agent or human; the name is historic, see STD-AU-3) |
| `client` | Client id, or `null` for an MSP-level event |
| `lever` | Lever name (or the lever a proposal decision concerns) |
| `params` | Redacted params |
| `mode` | `dry-run`, `execute`, or for queue decisions `approve` / `reject` |
| `result` | `{status, reason, applied, changes[], idempotency?, proposal?}`, redacted |
| `approver` | Lead id when an approval was used, else `null` |
| `prev_hash`, `hash` | The chain |

The verifier requires exactly this field set, so adding a field is a schema version change.

### 4.2 Rules

- **STD-AU-1 One record per call, allowed or denied.** Two only when saving fails after the record was written (the second says so). Audit first, then apply.
- **STD-AU-2 Version 2 (proposed), additive.** New records carry `v: 2` and four more fields: `event` (`lever.invoke`, `proposal.add`, `proposal.decide`, `model.complete`, `job.run`), `actor_kind` (`agent` \| `human`), `lever_version`, and `request_id` (the correlation id that also appears in traces and logs). The verifier accepts a v1 prefix followed by v2 records, never the reverse. v1 records are never rewritten.
- **STD-AU-3** `agent` keeps its name in v2 for chain compatibility; documentation calls it "actor".
- **STD-AU-4 Never logged** (redaction is a backstop, not the control):
  1. passwords, secrets, tokens, API keys, client secrets, certificates, cookies, `Authorization` headers, connection strings;
  2. environment variable values;
  3. read-lever results (`data` is returned to the caller, not written to the audit);
  4. free text from tickets, emails, documents and tool output; the audit names the ticket id instead;
  5. full model prompts and completions; a `model.complete` record holds provider, model, task, prompt SHA-256, lengths, latency and `ok`, nothing more;
  6. personal data that is not needed to prove what happened. Identifiers needed as evidence (UPN, directory object ids, ticket ids) are allowed; contact details (phone numbers, personal email addresses, addresses), health or financial details, and authentication method details beyond type and id are not. Diffs of fields like `phoneNumber` must be masked before they reach the record (see DR-02);
  7. file contents and fixture bodies.
- **STD-AU-5 Redaction runs inside `append`** on params and result, by key name (`password|passwd|secret|token|key|credential`) and by value shape (bearer, `sk-`, JWT, long hex or mixed base64; GUIDs kept). Callers must not rely on it for categories 3 to 7 above.
- **STD-AU-6 Field lengths are capped** before writing (identity, client and lever at 128 characters, as the runner does today), so odd input can never stop a denial from being recorded.
- **STD-AU-7 Head pin outside the writer's reach (proposed, production).** In this repo the head file sits next to the log. A deployment pins heads somewhere the writing identity cannot rewrite (target architecture, SL-01).
- **STD-AU-8 Audit is not the application log.** Operational logs (STD-SC-8) are separate and can be deleted on a retention schedule; the audit log follows the evidence retention period that the MSP sets (open question in the target architecture).

## 5. Config files (STD-CF)

- **STD-CF-1 Location.** Program config lives in `config/` (identities, models, routing; proposed: `clients/`). The lever registry lives in `levers/registry.json`. A module-private config may live beside its module (`TenantBaseline.config.json`) when nothing else reads it.
- **STD-CF-2 Every config file is schema-validated at load** by a pydantic model with `extra="forbid"`, and from STD-XL-1 also has a JSON Schema in `schemas/`.
- **STD-CF-3 Fail closed.** A missing, unreadable or invalid file stops the component at start with one clear error that names the file. Nothing loads partially, and there are no silent defaults for permissions, scopes, clients or provider switches.
- **STD-CF-4 Version field.** Each file has an integer top-level `version` (registry and identities do; models and routing should, DR-07). A reader rejects a version it does not know.
- **STD-CF-5 Notes.** A top-level `_note` string is allowed for humans and ignored by readers. No other underscore keys.
- **STD-CF-6 Key style.** snake_case for our own keys. camelCase and `@odata.*` only where a file mirrors a Microsoft Graph (or other vendor) shape, and then exactly as the vendor documents it.
- **STD-CF-7 No secrets and no environment values** in any config. A config may name an environment variable or (later) a Key Vault secret name, never hold the value (pattern already used: `graph.tenantIdEnvVar`).
- **STD-CF-8 Model names live only in `config/models.json`**; routes name a provider and an alias. Swapping a model or provider is a config change (D-018).
- **STD-CF-9 Paths in config are repo-relative**, resolved against the repo root by the loader, never against the current directory.

## 6. Error model (STD-ER)

- **STD-ER-1 Result objects at boundaries.** The gateway returns `Completion` (`ok`, `error`), the lever runner returns `InvokeResult` (`status: ok | denied | error`, `reason`, `audit_seq`). Neither raises to its caller for any provider, permission, lever, timeout or tenant failure. Every future boundary follows the same pattern: the PowerShell bridge, adapters, the MCP server, the scheduler and RAG retrieval each return a typed result with `ok`/`status` and a human-readable `reason`.
- **STD-ER-2 Three outcomes, never more.** `denied` = a rule said no (nothing ran); `error` = it was allowed but could not finish (nothing was saved unless the record says `applied`); `ok`. A denial reason says which rule fired, in words a technician can act on, and never includes another client's data.
- **STD-ER-3 Inside a component, typed exceptions are fine** (`RegistryError`, `TenantError`, `LeverFailed`, `ProviderError`, `QueueError`, `DecisionDenied`), and are converted to a result at the boundary. Never catch `BaseException` except where the runner hands a worker-thread exception back to the caller's thread.
- **STD-ER-4 Startup errors raise.** Bad config, a broken registry or an audit log whose head pin disagrees stops the process (fail closed). That is the one place an exception is the correct output.
- **STD-ER-5 Crash text is not leaked.** An unexpected exception becomes `"<component> crashed: <ExceptionType>"` in the result; the stack trace goes to the operational log, not to the model, the UI or the audit.
- **STD-ER-6 CLI exit codes.** 0 = ok, 1 = denied or failed (a normal outcome), 2 = usage or configuration error. Already used by `core.levers`, `core.audit.verify` and `ui`.
- **STD-ER-7 PowerShell.** Inside a module, `throw` and terminating errors are normal. At the bridge boundary every outcome, including a thrown error, becomes one JSON result object on stdout and exit code 0/1/2 per STD-ER-6.

## 7. Python (STD-PY)

- **STD-PY-1 Version.** Python 3.12 (`requires-python = ">=3.12"`, ruff `target-version = "py312"`, mypy `python_version = "3.12"`). Always run through uv: `uv run python -m ...`, `uv run pytest`. Never bare `python` in docs or scripts.
- **STD-PY-2 Dependencies.** Standard library first. Runtime dependency today: pydantic v2 only. A new runtime dependency needs a DECISIONS entry (why, license, alternative) and the owner's approval for the install (hard rule 6). `uv.lock` is committed and CI runs `--frozen`.
- **STD-PY-3 Types.** `mypy --strict` must pass. Scope target: every Python package (`core`, `workflows`, `evals`, `ui`, future `adapters`, `rag`, `mcp`); today it is `core` only (DR-06). No `Any` in a public signature except JSON payloads (`JsonDict`, `Mapping[str, Any]`).
- **STD-PY-4 Models.** Every value that crosses a boundary (config, registry, proposal, approval, result, request) is a pydantic v2 model with `ConfigDict(frozen=True, extra="forbid")`, strict scalar types (`StrictStr`, `StrictInt`, `StrictBool`) where a string must not become a number, and validators that make an unsafe combination unconstructable (as `LeverDef._safe_by_construction` does). Internal plain records may be `@dataclass(frozen=True, slots=True)`.
- **STD-PY-5 Lint and format.** `ruff check .` and `ruff format --check .` clean. Rule set: `E, F, W, I, B, UP, S` with only `S101` ignored, line length 120. A per-line `noqa` names the rule and says why. Adding rules is welcome; removing one needs a DECISIONS entry.
- **STD-PY-6 Module layout.** One package per component. `__init__.py` re-exports the public API and nothing else; `__main__.py` is the CLI; private helpers start with `_`. A module starts with a docstring that says what it does and what it guarantees (the existing modules are the model). `from __future__ import annotations` in every module.
- **STD-PY-7 CLI.** `python -m <package>` with `argparse`, `--help` that names the synthetic-data scope, exit codes per STD-ER-6, JSON output with `--json` where a machine reads it. State goes in `.tmp/<name>` (gitignored), never into committed fixtures.
- **STD-PY-8 Paths.** Repo-relative locations come from one helper (proposed `core/paths.py` with `REPO_ROOT`), not from the current directory (DR-08). Every file opened by a client id goes through that store's resolver (STD-ID-4).
- **STD-PY-9 Time.** `datetime.now(UTC)`; serialise as ISO 8601 with `Z`; milliseconds in the audit, seconds acceptable elsewhere. Anything that must be reproducible (reports, baseline checks) takes an explicit `as_of`.
- **STD-PY-10 Concurrency.** No shared mutable module state except locks. File writes are atomic (`write tmp` then `os.replace`). A component that assumes one writer says so in its docstring.

## 8. PowerShell (STD-PS)

- **STD-PS-1 Version.** PowerShell 7, minimum 7.4 for new modules (7.4 is the first with `Test-Json -LiteralPath` and the JsonSchema.Net validator, STD-XL-3). `CompatiblePSEditions = @('Core')`. `TenantBaseline` declares 7.2 today (DR-09).
- **STD-PS-2 Module layout.**
  ```
  levers/powershell/<Module>/
    <Module>.psd1            manifest: explicit FunctionsToExport, empty Cmdlets/Variables/AliasesToExport
    <Module>.psm1            Set-StrictMode -Version Latest; private helpers first, public functions last
    <Module>.config.json     optional, module-private config (STD-CF-1)
    tests/<Module>.Tests.ps1 Pester 5 tests (once Pester 5 is installed; plain scripts until then, D-002)
    README.md                what it does, inputs, outputs, scopes, how to run offline
  ```
  Private helpers carry a short module prefix in the noun (`Get-TbConfig`), public functions do not need it.
- **STD-PS-3 Approved verbs only.** Every function name is `<ApprovedVerb>-<Noun>`; check with `Get-Verb`. Do not use synonyms of approved verbs (`Remove`, never `Delete`). Source: [Approved Verbs for PowerShell Commands](https://learn.microsoft.com/en-us/powershell/scripting/developer/cmdlet/approved-verbs-for-windows-powershell-commands) (read 2026-10-20). Lever action to verb: `get`/`list`/`check` → `Get` or `Test`, `search` → `Find`, `disable` → `Disable`, `enable` → `Enable`, `reset` → `Reset`, `revoke` → `Revoke`, `grant` → `Grant`, `block` → `Block`, `add` → `Add`, `remove` → `Remove`, `set`/`require` → `Set`, `new` → `New`.
- **STD-PS-4 Write functions support `-WhatIf`.** `[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]` and every state change inside `if ($PSCmdlet.ShouldProcess($target, $action))`. Under `-WhatIf` the function returns the same diff shape as STD-LV-5 (it computes the change and does not apply it). Read-only functions use plain `[CmdletBinding()]` (as `Invoke-TenantBaseline` does).
- **STD-PS-5 Output is objects.** Return `[pscustomobject]` (or a class) that matches a schema in `schemas/`; no `Write-Host` for data, no formatted text as the result. Files (HTML, CSV) are written only to an `-OutDir` the caller passes.
- **STD-PS-6 Errors.** `Set-StrictMode -Version Latest` at module scope; `-ErrorAction Stop` on calls whose failure matters; `throw` with a message that names the input and says what was and was not done ("No network call was made."). See STD-ER-7 for the bridge boundary.
- **STD-PS-7 No credentials in parameters or files.** A real adapter gets its token from the bridge (managed identity or Key Vault later), never a `-ClientSecret` parameter. `-UseGraph`-style switches refuse before any connection when the test tenant is not configured (SB-3 pattern).
- **STD-PS-8 PSScriptAnalyzer clean** with default rules once installed (D-002, `docs/ENVIRONMENT.md`); a suppression uses `[Diagnostics.CodeAnalysis.SuppressMessageAttribute()]` with a justification.
- **STD-PS-9 Tests.** Pester 5 style: `Describe '<Function>'`, `Context`, `It '<ACCEPTANCE-ID>: <behaviour>'`, `BeforeAll { Import-Module <manifest> -Force }`, fixtures from `fixtures/`, `$TestDrive` for output. Until Pester 5 is installed, plain scripts that print `PASS`/`FAIL` lines and a summary line, as `tests/sliceb/Test-SliceB.ps1` does.
- **STD-PS-10 Determinism.** Anything time-based takes an explicit as-of date (TenantBaseline's `asOf`), so a run over the same fixtures is byte-identical.

## 9. Cross-language contract (STD-XL)

Python orchestrates, PowerShell acts (blueprint section 4). They share data, not code, so the shapes must be written down once.

- **STD-XL-1 A `schemas/` folder (proposed)** holds JSON Schema (draft 2020-12) files, one per shared shape:

  | File | Shape | Source of truth today |
  |------|-------|-----------------------|
  | `lever-registry.schema.json` | `levers/registry.json` | `LeverDef`, `_RegistryFile` |
  | `identities.schema.json` | `config/identities.json` | `Identity`, `_IdentityFile` |
  | `change.schema.json` | one diff entry | `Change` |
  | `lever-request.schema.json` | bridge request (lever, client, params, mode, request_id, adapter context) | new |
  | `lever-result.schema.json` | bridge and runner result | `InvokeResult` |
  | `proposal.schema.json` | queue proposal | `Proposal` |
  | `audit-record.schema.json` | v1 and v2 audit records | `core/audit/chain.py` |
  | `finding.schema.json` | a baseline or compliance finding | `TenantBaseline` `Finding` class |
  | `client.schema.json` | proposed `config/clients/<id>.json` | new |

- **STD-XL-2 Python generates, CI checks.** The pydantic model is the source of truth; a small script writes the schema files (`model_json_schema()`), and a test fails if a committed schema differs from the generated one. Shapes that start in PowerShell (`finding`) are written by hand and validated from both sides.
- **STD-XL-3 PowerShell validates with `Test-Json -SchemaFile`.** From PowerShell 7.4, `Test-Json` uses System.Text.Json and JsonSchema.Net, does not support draft 4 schemas, and accepts only strictly conformant JSON ([Test-Json](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/test-json?view=powershell-7.6), read 2026-10-20). UNVERIFIED: that the JsonSchema.Net version bundled with PowerShell 7.6 implements every draft 2020-12 keyword we use; the first schema PR must include a PowerShell test that proves a known-bad document fails.
- **STD-XL-4 JSON on the wire.** UTF-8, no BOM, no comments, no trailing commas; canonical JSON (sorted keys, compact) wherever a hash is computed, using `core.audit.canonical_json`. PowerShell writes JSON with `ConvertTo-Json -Depth 20 -Compress` and never relies on its key order for hashing; hashes are computed on the Python side.
- **STD-XL-5 Names.** snake_case keys in our shapes. Graph-shaped data keeps Graph names. Enums are lowercase strings.

## 10. Testing (STD-TS)

- **STD-TS-1 Pyramid.** From most to fewest:
  1. **unit**: pure functions (schema checks, diff, redaction, rules, detectors);
  2. **contract**: registry and config loads, schema round-trips Python to PowerShell, the proposal contract between producers and the queue;
  3. **acceptance**: one test per spec acceptance id, on synthetic fixtures, offline;
  4. **eval**: fixture-based metrics with a threshold that fails CI (triage category accuracy at least 90% on the mock, injection corpus pass/fail, later retrieval leakage = 0);
  5. **demo smoke**: the `docs/DEMO.md` commands run end to end.
- **STD-TS-2 Acceptance ids.** `<SPEC>-<n>`: `P<phase>-<n>` for phases (`P1-2`), `S<slice>-<n>` for slices (`SA-1`, `SB-3`, `SC-2`), `B<nn>-<k>` for roadmap items (`B02-3`, defined in `specs/B-nn.md`; `docs/ROADMAP.md`). Ids are defined once, in the spec file, before code. Python test names start with the lowercased id (`test_p1_2_deleting_the_last_record_is_caught_by_the_head_pin`); Pester `It` names start with the id (`It 'SB-1: ...'`); plain scripts print the id in each `PASS`/`FAIL` line. A test that covers no acceptance id has a plain descriptive name.
- **STD-TS-3 Every denial path has a test that also checks the audit record.** "Denied" without "and audited" is half a test.
- **STD-TS-4 Offline and deterministic.** No network in tests (fake servers on 127.0.0.1 only, as `test_gateway.py` does); no wall-clock dependence (pin `as_of`); temp state under `tmp_path` / `$TestDrive`; committed fixtures are never modified by a test.
- **STD-TS-5 Suites are runnable by one command** each (`tests/phase1/Test-Phase1.ps1`, `tests/sliceb/Test-SliceB.ps1`) and each prints one summary line `"<Suite> tests: N passed, M failed"`. CI runs all of them; a missing tool is reported as `skipped`, never as `passed`.
- **STD-TS-6 Isolation tests are mandatory** for every component that reads client data: client A's identity asking for client B's data is denied and audited (P1-1 pattern); retrieval and reports get the same test.

## 11. Fixtures (STD-FX)

- **STD-FX-1 Synthetic only.** Invented tenants (Contoso Dental, Fabrikam Capital, and further names from Microsoft's fictitious-company set), invented people marked "(synthetic)" where a display name is shown, `.example` domains or `*.onmicrosoft.com`, phone numbers in the 555-01xx fictional range, recognisable fake GUID prefixes per tenant (`c0000000-...`, `f0000000-...`) or generated ids. Never a capture from a real tenant, PSA or RMM, never a real company's data.
- **STD-FX-2 Cited shapes.** Every fixture folder that imitates a vendor API has a `SOURCES.md` that names the request it stands in for, links the vendor doc, and marks each field Verified (with date) or UNVERIFIED, as `fixtures/graph/SOURCES.md` does.
- **STD-FX-3 Self-labelled.** Every fixture file carries a `_note` or `_meta.note` saying it is synthetic and what shape it imitates, and its `client` matches its file name.
- **STD-FX-4 Seeded problems are documented.** A fixture built to trigger findings lists them (in `SOURCES.md` or the test), and a clean twin exists that triggers none (SB-1 pattern).
- **STD-FX-5 Labels are gold, never inputs.** Eval labels (ticket `labels`) are never shown to the code under test. Where the fixture author also wrote the mock's rules, results are labelled as pipeline checks, not model quality (D-022).
- **STD-FX-6 Pinned dates.** Fixtures with timestamps come with the `as_of` they were written for.

## 12. Docs (STD-DC)

- **STD-DC-1 Status line first.** Every doc starts with its status: `built`, `mocked`, `document-only`, `planned`, `skeleton` or `outline`, using the strict status words in `docs/COVERAGE.md`.
- **STD-DC-2 Honest labels.** "Independently built prototype"; numbers labelled fixture-based; anything not checked marked UNVERIFIED with what would verify it; no claim of production use or real-world results.
- **STD-DC-3 Decision log.** `docs/DECISIONS.md`, newest last, `D-nnn <title> (<phase or date>)`, then why, alternatives, and what would change it. A superseding decision names the one it supersedes. Exceptions to this file are decisions.
- **STD-DC-4 Stable ids everywhere.** Coverage rows (`A1`), decisions (`D-016`), standards (`STD-LV-4`), acceptance tests (`P1-2`), architecture components (`ARC-nn`), scaling limits (`SL-nn`), drift items (`DR-nn`), and the map ids indexed in `docs/map/README.md` (work items `W-<AREA>-<nn>`, controls `C-nn`, build items `B-nn`, waves `W1`-`W10`). Ids are never renumbered; `map/check_map.py` checks that every cross-reference resolves.
- **STD-DC-5 Written for a technician who has never seen the repo.** Plain English, commands that can be pasted, what it does and does not do.
- **STD-DC-6 Sources.** Public facts carry a URL and the date read. Vendor marketing is labelled as such.
- **STD-DC-7 Each lever and workflow has a doc** (README beside it): purpose, inputs, outputs, permissions and scopes, dry-run example, eval result, known limits.

## 13. Security defaults (STD-SC)

- **STD-SC-1 Loopback only.** Local servers bind 127.0.0.1 and check the `Host` header; local model endpoints must be 127.0.0.1, localhost or ::1 with no userinfo and no redirects (D-018, D-023).
- **STD-SC-2 Hosted model providers off by default**; turning one on is a config change plus a DECISIONS entry that records the data-handling terms checked.
- **STD-SC-3 Untrusted input.** Ticket, email, document and tool-output text is scanned (`detect_injection`) on the raw text, then wrapped (`wrap_untrusted`) before any model sees it. It can never change permissions, scope or which levers exist. Flagged input gets no lever (D-022).
- **STD-SC-4 Least privilege.** Each lever declares the narrowest Graph application permissions it needs (`graph_scopes`, proposed); the app registration for a client is the union of the enabled levers' scopes, reviewed quarterly. Read-only checks use read-only scopes (Slice B lists them). Agents get the `agent` role and dry-run only.
- **STD-SC-5 Secrets never in the repo**, in logs, in prompts or in fixtures. `.env.example` only; the pre-commit secret scan stays on. Later: Azure Key Vault with managed identities and Azure RBAC (not legacy access policies), soft delete and purge protection, separate vaults per environment ([Secure your Azure Key Vault](https://learn.microsoft.com/en-us/azure/key-vault/general/secure-key-vault), read 2026-10-20). Whether client secrets go in one vault per client or one per environment is an open question (target architecture, OQ list).
- **STD-SC-6 Web UI.** POST-only state changes with a CSRF token, every value HTML-escaped, a Content-Security-Policy with no script, `no-store`, `frame-ancestors 'none'` (Slice C).
- **STD-SC-7 No free-form execution.** No lever or workflow runs model-written code, shell or SQL. The PowerShell bridge runs only functions named in the registry `entry` field.
- **STD-SC-8 Operational logs** (when added) are JSON lines with `request_id`, component, event, outcome and timing, and follow STD-AU-4: no secrets, no ticket or document text, no prompts.
- **STD-SC-9 Supply chain.** GitHub Actions pinned to full commit SHAs, `permissions: contents: read`, Dependabot on (already in `.github/`). Python dependencies locked.

## 14. Versioning and changelog (STD-VR)

- **STD-VR-1 SemVer** for the Python project (`pyproject.toml` `version`) and for each PowerShell module (`ModuleVersion`). Pre-1.0 while this is a prototype: a minor bump may break.
- **STD-VR-2 Data versions are integers**: config and registry files `version`, audit records `v`, lever `lever_version`. Readers reject unknown versions.
- **STD-VR-3 `CHANGELOG.md` (proposed)** at the repo root in Keep a Changelog style, sections Added / Changed / Fixed / Security / Migration, one entry per merged PR that changes behaviour, contracts or schemas. Any contract change (STD-XL) gets a Migration line.
- **STD-VR-4 Branches and PRs** follow `CONTRIBUTING.md`: `feat/`, `fix/`, `docs/` branches from `main`, CI green, owner approval; AI agents never approve or merge.

## 15. Definition of done (STD-DD)

A change is done when every line that applies is true:

1. **STD-DD-1 Spec first.** Acceptance ids exist in `specs/` before the code (STD-TS-2).
2. **STD-DD-2 Tests.** Each acceptance id has a test; every denial path is tested together with its audit record; the suites pass locally and in CI.
3. **STD-DD-3 Checks.** `ruff check`, `ruff format --check`, `mypy --strict` clean on the touched packages; PSScriptAnalyzer clean (when installed).
4. **STD-DD-4 Levers.** A new lever has a registry entry, a typed schema, a dry-run diff test, an idempotency test (second run has an empty diff), a scope-denial test, an audit test and a README.
5. **STD-DD-5 Workflows.** A new workflow has an eval set and a fixture-based result in its report.
6. **STD-DD-6 Contracts.** Any shared shape is in `schemas/` and validated from both languages.
7. **STD-DD-7 Config.** New config is schema-validated, versioned and fails closed.
8. **STD-DD-8 Security.** No secrets; loopback only; untrusted input wrapped; never-log list respected (STD-AU-4); a separate review (an independent review and a security review) has run and its findings are fixed or recorded.
9. **STD-DD-9 Docs.** `docs/COVERAGE.md` status updated with strict words; a DECISIONS entry for every choice and every exception to this file; the CHANGELOG line written; honest labels on any number.
10. **STD-DD-10 Traceability.** The PR says who the change helps at each level (one person at one client, the client business, the MSP, the community), in one line each, so every automation stays traceable from one ticket up.
