# workflows/bec (B-46)

Status: **mocked** on synthetic fixtures (change note `docs/changes/B-46.md`). Synthetic data only.

`plan` builds the containment plan for one user: block sign-in, revoke sessions, reset MFA and disable each flagged inbox rule, each dry-run through the runner and queued as one proposal for a lead. `audit` lists every flagged inbox rule of one client. Nothing is executed here.

## Command

```
uv run --frozen python -m workflows.bec plan <client> <upn> [--as tech-ana] [--incident ID] [--prompt]
uv run --frozen python -m workflows.bec audit <client> [--as tech-ana]
```

## Inputs

The mock tenant's users and inbox rules (read through `inboxrule.list`), `config.json` here, and the approval queue state.

## Outputs

The plan as JSON (or, with `--prompt`, only the text that may go to a model), queued proposals, and the incident timeline at `<state>/bec/timelines/<client>/<incident>.jsonl`. Exit 0 done, 2 refused or bad input.

## What is mock

The tenant is the Graph mock; no mailbox or sign-in is touched.

## Spec and tests

Spec: `specs/B-46.md`. Tests: `tests/py/bec/test_b46_bec.py`.
