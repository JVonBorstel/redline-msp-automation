# workflows/billing (B-76)

Status: **built** on synthetic fixtures (change note `docs/changes/B-76.md`). Synthetic data only.

For one client: classifies each time entry against the contract clauses (rules, no model; an unmatched entry goes to a person) and scores each note for what was done, why and the outcome. Every correction is a proposal for a lead; nothing is scored or grouped per technician.

## Command

```
uv run --frozen python -m workflows.billing export contoso-dental --as lead-lee --as-of 2026-10-27
uv run --frozen python -m workflows.billing verify build/billing/contoso-dental.json
```

## Inputs

The synthetic billing fixture `fixtures/<client>.json` here (contract scope, tickets, time entries) and `config/identities.json`.

## Outputs

`build/billing/<client>.json` with a `.sha256` and a Markdown rendering, and an audit record. Exit 0 done, 1 verify mismatch, 2 bad input or refused.

## What is mock

The PSA data is a synthetic fixture; nothing is written to a PSA or an invoice.

## Spec and tests

Spec: `specs/B-76.md`. Tests: `tests/py/billing/test_b76_billing.py`.
