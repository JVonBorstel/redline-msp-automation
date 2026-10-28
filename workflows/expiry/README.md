# workflows/expiry (B-54)

Status: **built** on synthetic fixtures (change note `docs/changes/B-54.md`). Synthetic data only.

For one client: SPF, DKIM and DMARC policy per domain, DMARC aggregate reports, app-registration secrets and certificates, TLS certificates, and GDAP relationships that expire soon, have expired or hold Global Administrator. Each finding is a reminder row with a due date and an owner. It only reports; a person renews.

## Command

```
uv run --frozen python -m workflows.expiry contoso-dental [--as-of 2026-10-21] [--within-days 30] [--markdown]
```

## Inputs

Synthetic fixtures under `fixtures/dns/` and `fixtures/partner/` (never the network).

## Outputs

JSON (or Markdown) on stdout. Nothing is written. Exit 0 ran, 2 bad input.

## What is mock

DNS, app registrations, certificates and GDAP relationships are synthetic fixtures.

## Spec and tests

Spec: `specs/B-54.md`. Tests: `tests/py/expiry/test_b54_expiry.py`.
