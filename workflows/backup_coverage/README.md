# workflows/backup_coverage (B-70)

Status: **built** on synthetic fixtures (change note `docs/changes/B-70.md`). Synthetic data only.

For one client: which in-scope users, mailboxes and SharePoint sites no active backup policy covers, which policies keep data too briefly or are not immutable when the client requires it, which disaster recovery plan sections are overdue for review, and a draft tabletop outline. Every count reconciles. Read-only.

## Command

```
uv run --frozen python -m workflows.backup_coverage report contoso-dental [--as-of 2026-10-26] [--stale-months 12]
uv run --frozen python -m workflows.backup_coverage verify build/backup-coverage/contoso-dental/contoso-dental.json
```

## Inputs

One synthetic fixture per client in `data/<client>.json` here.

## Outputs

A JSON and a Markdown report under `build/backup-coverage/<client>/`, each with a `.sha256`. Exit 0 done, 1 verify mismatch, 2 bad input.

## What is mock

The backup product and the DR plan are synthetic fixtures; no backup service is called.

## Spec and tests

Spec: `specs/B-70.md`. Tests: `tests/py/backup/test_b70_coverage.py`.
