# Runbook: AI incident response (wrong automated action)

Status: **document-only** (a procedure for humans; every command in the code blocks below is run against a synthetic state folder by `tests/py/governance/test_b94_incident_response.py`). The MSP's real incident procedure is UNKNOWN; this is the prototype's proposal, to be merged into theirs. Synthetic data only. Not legal advice.

> Independently built prototype. Not affiliated with any vendor's or real company's systems.

Inventory `W-GOV-04`. Controls `C-34` (this runbook), `C-35` (notification templates), `C-31` (pause switch), `C-33` (rollback). The steps are `IR-1` to `IR-9` of `docs/map/05-governance.md` section 7, in that order, with the same names. Rehearsed once on synthetic tenants: `docs/TABLETOP_2026.md`.

## When this runbook starts

A wrong action is any lever execution that hit the wrong target, did the wrong thing, ran when it should not have, or ran in the wrong client, whether or not a model was involved. Treat it as a security incident until shown otherwise: at a dental or financial client a wrong action can also be a breach.

The rule of the whole runbook: **the person is restored first, and the client hears from a human.** No message about the incident is sent by an automation (HO-9).

## Roles (roles, never people; D6-17)

| Role | Does | Steps |
| --- | --- | --- |
| On-call lead | declares the incident, pauses the lever, approves the restore | IR-2, IR-3, IR-9 |
| Technician on call | proposes the restore, talks to the affected person | IR-3, IR-6 |
| Engineer | verifies the audit chains, scopes, fixes | IR-4, IR-7 |
| Compliance owner | decides whether regulated data was exposed or made unavailable, talks to counsel | IR-5, IR-6 |
| Account manager | client contact and privacy officer notices | IR-6 |
| AI and Automation Engineer | runs the blameless review | IR-8 |

Who holds these roles at the MSP is GQ-01 (unknown).

## Before you start

- Run every command from the repo root in PowerShell 7. The demo state folder is `.tmp/demo` (the default of every command below). Lever ids and client ids are listed by `uv run --frozen python -m core.levers list` and `config/identities.json`.
- Fill the placeholders in angle brackets before pasting. They are:

| Placeholder | Means | Example (synthetic) |
| --- | --- | --- |
| `<lever>` | the lever that did the wrong thing | `user.disable` |
| `<client>` | the client where it happened | `contoso-dental` |
| `<other-client>` | each other client that uses the lever (IR-9 rings) | `fabrikam-capital` |
| `<lead>` | the on-call lead's identity id | `lead-lee` |
| `<tech>` | the technician on call | `tech-ana` |
| `<seq>` | the audit `seq` of the wrong execute in that client's chain (IR-4 prints it) | `2` |
| `<proposal-id>` | the rollback proposal id that IR-3 prints | `P-d77916af21d5` |
| `<upn>` | the person a corrected call is for (IR-9) | `jamie.chen@contosodental.example` |
| `<reason>` | one line, 1 to 200 characters, for the audit | `IR wrong user disabled` |

- Never paste a phone number, a password, a token or ticket text into a command. Reasons are short and factual.

## IR-1 Detect

Any of: the affected person reports it (the EU-2 fast path line in `fixtures/notify/contacts.json`); a technician spots it; the audit verifier fails; a second review of a pre-authorized containment is overdue (B-42, D6-08). Monitoring alerts on volume, denials or after-hours executes are planned (C-40), not built.

```powershell
uv run --frozen python -m core.levers verify
uv run --frozen python -m core.levers reviews
```

`verify` checks every audit chain on its own (`core/audit/router.py`, `AuditRouter.verify_all`: one `audit/<client>.jsonl` per client plus `audit/_msp.jsonl`, B-42) and exits 1 if any is broken. `reviews` exits 1 when a second review is overdue. A broken chain is itself an incident: stop, do not trust its before-state (the rollback workflow refuses a broken chain), and tell the engineer.

## IR-2 Contain

Pause the lever. No approval is needed; only a `lead` may pause (B-02, `core/levers/pause.py`). When you do not yet know how far it spread, pause it for **every** client:

```powershell
uv run --frozen python -m core.levers pause <lever> --as <lead> --reason "<reason>"
uv run --frozen python -m core.levers paused
```

To pause for one client only, add `--client <client>` (a lead scoped to that client). What the pause does, from `specs/B-02.md` and `core/levers/runner.py`:

- the lever is denied in **dry-run and execute** for everyone, with the reason `lever paused by <lead>: <reason>`;
- a global pause wins over a client pause; it is written to `audit/_msp.jsonl` with client `*`, a client pause to that client's chain;
- the pauses live in `audit/pauses.json`; an unreadable file denies every call (fail closed).

A pause also blocks correct calls of the same lever (the real leaver in the tabletop stayed enabled until IR-9). Say so to the client when it matters.

## IR-3 Restore the person first

Put the person back to work before looking for the root cause. The rollback workflow (B-41, `workflows/rollback/rollback.py`) reads the wrong execute from the client's audit chain, verifies the chain, and builds a normal proposal for the lever's registered undo from the recorded before-state. It executes nothing.

```powershell
uv run --frozen python -m workflows.rollback <seq> --client <client> --as <tech>
uv run --frozen python -m ui --demo
```

- Outcome `proposed`: open the approval page (`ui/app.py`, `http://127.0.0.1:8765`), sign in as the on-call lead, and approve the `rollback` proposal like any other change. Call the person back on the number on file first; the undo lever asks for that verification (`user.enable` is `verification: requester`). The requester can never approve their own proposal (four-eyes).
- Outcome `manual`: the lever has no undo; the workflow prints the manual steps from the lever's README section and the recorded before-state. Follow them by hand with a second technician watching.
- Outcome `nothing-to-undo`: the state is already back. Outcome `drifted` or a refusal (exit 2): someone or something changed the object since; read the current state with the person before changing anything. Masked contact details (B-02, `mask_change` in `core/levers/runner.py`) always come back as `drifted`, never as a guess.
- The pause does not block the undo: it is a different lever (`user.enable` undoes `user.disable`).

Target: the person can work again within one business hour during support hours (EU-2; the target is to agree with the MSP, GQ-09). This repo cannot measure it.

## IR-4 Scope

Verify the chains first, then list every applied execute of the lever across every client chain. There is no audit query command in the repo; the query is this PowerShell filter over the chain files (B-42 layout), or the audit page's chain picker in `ui/app.py`, one chain at a time.

```powershell
uv run --frozen python -m core.levers verify
Get-ChildItem .tmp/demo/audit -Filter *.jsonl | Get-Content | ConvertFrom-Json | Where-Object { $_.lever -eq '<lever>' -and $_.mode -eq 'execute' -and $_.result.applied } | Select-Object client, seq, ts, agent, approver, @{n='target'; e={ $_.params.upn }} | Format-Table -AutoSize | Out-String -Width 400
uv run --frozen python -m core.levers export --client <client> --out .tmp/ir-<client>
```

- Read the `ts` column for the incident window; every row in it is a candidate wrong action and goes back to IR-3.
- `export` copies one client's chain and its head pin and nothing else (`AuditRouter.export_client`), so the client's own evidence can be handed over without any other client's records (B42-2, SL-01 step 1).
- What the audit can and cannot show: it holds the changed fields before and after, the requester, the approver and the verification method, never read data (C-11), and contact details are masked (B02-3).

## IR-5 Assess regulatory impact

The compliance owner decides, not the tool. Inputs:

- **Data class of the client** (B-55, `core/guard/classify.py`): the industry floor is `DC-4` (PHI) for dental clients and `DC-5` (NPI) for financial, RIA, legal and accounting clients; unknown is high.

```powershell
uv run --frozen python -c "from core.guard.classify import INDUSTRY_FLOOR; print({k: v.label for k, v in INDUSTRY_FLOOR.items()})"
```

- **Was data exposed to a model?** Every gateway text passes the redaction gate first (`core/guard/redact_prompt.py` inside `core/gateway/gateway.py`): DC-6 is blocked, PHI- and NPI-shaped spans become typed placeholders, and hosted routes refuse DC-4 and DC-5 text. The gate is rules on regular expressions proven on the synthetic Phase 2 set only (`evals/redaction/report.md`, fixture-based); a name without a cue word is not found. So "no PHI reached a model" is a claim to check, not to assume.
- **Was data made unavailable?** A disabled dental hygienist cannot open patient records. Loss of availability of PHI can matter under HIPAA as well as exposure. That is for the compliance owner and counsel.
- If PHI or NPI may be involved, this is a possible HIPAA breach or Safeguards Rule notification event (BA-5, GLBA-7). Hand it to the compliance owner the same day.

## IR-6 Notify

A human sends every message. Use the templates in `governance/templates/notifications/`:

| Who | Template | When |
| --- | --- | --- |
| The affected person | `affected-person.md` | as soon as they are back to work (or before, by phone) |
| The client's primary contact | `client-contact.md` | the same business day (confirm with counsel) |
| The client's privacy or security officer | `privacy-officer.md` | when regulated data may be involved, early enough for their own deadlines (confirm with counsel) |

Every legal timeline in the templates says "confirm with counsel". The per-lever drafts of `workflows/notify` are routine change notices, not incident notices; after a rollback their "Why" line is wrong (see the review in `governance/templates/notifications/README.md`). You may read one for the facts:

```powershell
uv run --frozen python -m workflows.notify <proposal-id>
```

## IR-7 Fix

Fix the lever, rule or prompt through normal change management (`docs/map/05-governance.md` section 8): a pull request with tests, CI green, a reviewer other than the author. Emergency fixes may skip staging, never review (CM-7). Add the case so it can never pass again: a test beside the lever's own (for example `tests/py/rollback/test_b41_rollback.py`) and, where the model chose something, a case in the workflow's eval set under `evals/`.

```powershell
uv run --frozen pytest -p no:cacheprovider tests/py/rollback
uv run --frozen ruff check .
```

## IR-8 Review

A blameless review within five business days: timeline from the audit (IR-4 output), what detected it, what slowed the restore, and the fix. The risk register it should go into (`B-95`) is not built yet; until then the review is a dated section in the incident ticket and a line in `docs/DECISIONS.md` when a rule changes. Trends go to leadership.

## IR-9 Re-enable

The lever comes back on the pilot client first, then in rings (CM-5). Because a global pause wins over a client pause, hold every non-pilot client with its own pause **before** lifting the global one, then check the pilot with a dry-run:

```powershell
uv run --frozen python -m core.levers pause <lever> --client <other-client> --as <lead> --reason "ring hold"
uv run --frozen python -m core.levers resume <lever> --as <lead> --reason "<reason>"
uv run --frozen python -m core.levers invoke <lever> --as <tech> --client <client> -p upn=<upn> -p "reason=<reason>"
uv run --frozen python -m core.levers resume <lever> --client <other-client> --as <lead> --reason "ring 2"
uv run --frozen python -m core.levers paused
```

Repeat the first line for each other client (one command per client; a ring-aware resume is not built) and the fourth line ring by ring. `paused` ends with `no levers are paused`. Every pause and resume is one audit record.

## What this runbook does not do

- It does not decide whether an event is a reportable breach, and it does not give legal deadlines; those are for the compliance owner and counsel.
- It does not send anything. There is no paging, chat or e-mail integration.
- Undo levers exist only where the registry names one (`undo` in `levers/registry.d/`); others are manual.
- Nothing here has run against a real tenant.
