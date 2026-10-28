# workflows/duplicates (B-23)

Status: **built** on synthetic fixtures (change note `docs/changes/B-23.md`). Synthetic data only.

Groups one client's open tickets into probable duplicates and outage groups (N or more tickets of one category inside a window) and lists the injection-flagged tickets a person must read. It only suggests; a lead approves any real link through the queue (`ticket.link`, R1).

## Command

```
uv run --frozen python -m workflows.duplicates fabrikam-capital [--as-of 2026-10-16T23:00:00Z] [--history]
```

## Inputs

The synthetic tickets in `fixtures/tickets/` and `config.json` here.

## Outputs

JSON on stdout with ticket ids only. Nothing is written. Exit 0 ran, 2 bad input.

## What is mock

The PSA is represented by synthetic ticket fixtures.

## Spec and tests

Spec: `specs/B-23.md`. Tests: `tests/py/duplicates/test_b23_duplicates.py`.
