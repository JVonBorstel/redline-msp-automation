# Automation framework review: a checklist for existing RMM scripts, and where automation fits

Status: **method only** (a written checklist, a fit table and a blank review record; no script has been reviewed and none is named). It is checked by `workflows/assurance/briefs.py`. Everything numeric elsewhere in the repo is **fixture-based**.

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only.

## What this page is, and what it is not

Someone onboarding to an automation role will find scripts that already run in the monitoring and management tool. Nobody knows what they do, which rights they use or who owns them. This page is the order of questions to ask of each one, and the point at which an answer turns into an intake for the normal lever process. This page makes no claim about any real script, any real tool tenant or any real organisation. Which scripts exist and with what rights is an open question the repo decided to leave open (Q-07, D6-26); it does not guess.

## Rules of the review

- The review is read-only. A reviewer lists and reads scripts; nothing is run, edited or disabled during it (`docs/map/06-decisions.md`, D6-26).
- The program never runs an existing script until it has been vetted into the lever registry as a named, versioned action with no free-form script parameter (`docs/map/06-decisions.md`, `map/roadmap.json`).
- Script text or output that may hold a password, key, certificate or recovery code never goes into a prompt, a ticket or this review's record (`governance/ACCEPTABLE_USE.md`).
- The review record uses roles, never names, and synthetic or redacted examples only (`docs/BLUEPRINT.md`).
- A script that fails a question is not shamed or blamed; it gets a verdict and a next step (`governance/RISK_REGISTER.md`).

## The checklist

Answer each question with one of: **pass** (the evidence is in front of the reviewer), **gap** (the evidence shows it is missing) or **unknown** (nobody can show it yet). Unknown is not pass.

### 1. Rights

Ask which account or identity the script runs as, and which permissions it holds at each client it can reach.

- Good looks like the least privilege the work needs, one client per run, and a role named on the action, the way a lever declares client scope, role required and read or write class (`docs/STANDARDS.md`, `tests/py/levers/test_b01_registry_fields.py::test_b01_1_every_lever_in_the_registry_file_declares_the_new_fields`).
- A gap is a shared admin identity, a tenant-wide scope for one client's job, or rights nobody can list (`docs/map/05-governance.md`).
- A script that can reach every client from one run is a many-clients scope and, if it writes, at least R3 on the intake rubric (`governance/intake_rubric.json`).

### 2. Secrets

Ask where any credential, token or key the script uses is stored, who can read it and how it rotates.

- Good looks like no stored credential at all, then a vault read by a managed identity, with a person doing rotation (`docs/SECRETS.md`).
- A gap is a value written in the script, in a command line, in a log or in a ticket note; the finding is recorded without copying the value, and rotation is a human task (`docs/SECRETS.md`, `tests/phase1/test_levers.py::test_p1_9_secret_params_are_redacted_in_the_audit_log`).
- Anything that reads or shows a stored administrator password is on the never-automate list and is not migrated (`governance/never-automate.json`).

### 3. Idempotency

Ask what happens if the script runs twice, stops half-way or is re-run after a timeout.

- Good looks like a declared idempotency key, a dry run that shows the change without making it, and a timeout that leaves nothing half-applied (`tests/phase1/test_levers.py::test_execute_twice_is_idempotent`, `tests/phase1/test_levers.py::test_p1_3_dry_run_changes_nothing`, `tests/phase1/test_levers.py::test_timeout_is_enforced_and_nothing_is_applied`).
- A gap is a script that appends, sends or creates on every run, or that has no way to preview its effect; the retry tests show the failure to avoid (`tests/py/load/test_b84_load.py::test_b84_3_control_a_non_idempotent_adapter_does_double_apply`).

### 4. Logging

Ask who can see what the script did, for which client, when and with which result, and whether the record can be altered.

- Good looks like one record per run with the actor, client, action, parameters (secrets masked), result and approver, in a tamper-evident chain (`tests/py/audit/test_b17_audit_v2.py::test_b17_1_new_records_carry_the_v2_fields`, `tests/py/audit/test_b17_audit_v2.py::test_b17_2_p1_2_rehashed_edit_breaks_the_next_record`).
- A gap is output that goes only to a console, a log that holds secrets or personal data, or a record a person can edit unseen (`docs/STANDARDS.md`).

### 5. Owner

Ask which role answers for the script, who approves a change to it and who retires it.

- Good looks like a named role (not a person) with a review date, the way the risk register assigns owner roles (`governance/RISK_REGISTER.md`, `docs/map/06-decisions.md`).
- A gap is a script nobody will claim; it is not run by this program and goes to leadership as a decision: adopt an owner or retire it (`docs/LEADERSHIP_BRIEF.md`).

## From answers to a verdict

- All five pass: the script is a migration candidate. Write it up as an intake so it is scored like any other idea and, if approved, rebuilt as a lever through the normal change process (`governance/USE_CASE_INTAKE.md`, `governance/intake_rubric.json`).
- Any gap in rights, secrets or owner: fix first. Nothing is migrated until the gap is closed by a person (`governance/RISK_REGISTER.md`).
- Gaps only in idempotency or logging: migrate as a rewrite, not a wrapper, because the lever runner supplies those properties and the old script cannot (`tests/py/mcp/test_b87_mcp.py::test_b87_2_fooled_client_unregistered_lever_is_refused_and_audited`).
- Any unknown: ask for the evidence; unknown stays unknown in the record (`docs/UNVERIFIED.md`).
- The work is on the never-automate list: keep it with people (`governance/never-automate.json`).

## Automation fit assessment

Where work of a given kind fits, from the repo's own rules. These rows describe kinds of work, not any real script.

| Kind of work | Fit | Why | Evidence |
|---|---|---|---|
| Read-only reports and lookups | Fits a read lever, model optional for wording | R0 has no state change and was scored first in the intake examples | `governance/ROI_TRACKER.md`, `fixtures/governance/intakes/UC-001.json` |
| Reversible change to one user or device with a named undo | Fits a write lever with lead approval and a dry run first | Risk class R1 or R2; the runner enforces approval and logs the change | `docs/STANDARDS.md`, `tests/phase1/test_levers.py::test_p1_3_execute_applies_exactly_the_dry_run_diff` |
| Change across many clients or hard to undo | Fits only with a written plan and two approvers, and never unattended | R3 rule in the rubric | `fixtures/governance/intakes/UC-005.json`, `governance/intake_rubric.json` |
| Script that takes free-form code or a command as a parameter | Does not fit | Device remediation levers are planned to run only vetted scripts named in the registry | `map/roadmap.json` |
| Anything touching a stored secret | Does not fit | Secrets never enter a prompt, log or model route | `governance/never-automate.json`, `governance/AI_POLICY.md` |
| Caller identity checks and privileged role grants | Does not fit | A person decides; tooling may show evidence only | `governance/never-automate.json`, `docs/map/05-governance.md` |
| Work with no measurement of volume or accuracy | Not yet | No priority is computed without a fixture or measured rate | `fixtures/governance/intakes/UC-004.json`, `governance/ROI_TRACKER.md` |

## Review record (blank)

Copy one block per script. Keep it in the review folder the owner chooses. Fill it from evidence in front of you, not from memory.

```
| Script | Rights | Secrets | Idempotency | Logging | Owner | Verdict |
|---|---|---|---|---|---|---|
| (role-based label, no real name) | pass / gap / unknown | pass / gap / unknown | pass / gap / unknown | pass / gap / unknown | pass / gap / unknown | migrate / fix first / keep human / retire |
Reviewer role:           Date:           Evidence seen (file or screen, never a secret):
```

## Not shown

- Which scripts exist, what rights they hold and who owns them: this method has never been applied, so there is no result (Q-07, `docs/map/06-decisions.md`).
- That the five questions are complete: they are a proposal drawn from the lever standard and the governance map and were not reviewed by anyone who runs such scripts (`docs/STANDARDS.md`).
- That any vendor tool exposes the data the questions need: the product behind the monitoring and management tool is inferred, not confirmed (`docs/UNVERIFIED.md`).
- Time or effort for a review: none is claimed and none was measured (`governance/ROI_TRACKER.md`).

## Unverified

- UNVERIFIED: how rights, secrets and logs are shown in the real tool's console and API; the adapter in this repo is a mock shaped from memory (`docs/UNVERIFIED.md`).
- UNVERIFIED: whether the planned device remediation levers exist in the form the roadmap describes; they are not built in this branch (`map/roadmap.json`).
