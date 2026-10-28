# workflows/backup_review (B-68)

Status: **built** on synthetic fixtures (change note `docs/changes/B-68.md`). Synthetic data only.

For one client: the failed (including a failed boot check), missed and long-running backup jobs, each with the reason from the job record, and one ticket draft per protected asset however many nights it failed. Every job lands in one bucket, so the counts reconcile. It retries nothing; a lead approves any retry through the queue (`backup.retry-job`, R2).

## Command

```
uv run --frozen python -m workflows.backup_review contoso-dental [--as-of 2026-10-21T07:00:00Z]
```

## Inputs

The client's backup jobs through the backup adapter mock (B-68) and `config.json` here.

## Outputs

JSON on stdout: counts, the jobs a person must look at, and ticket drafts. Nothing is written. Exit 0 ran, 2 bad input.

## What is mock

The backup adapter is a mock over synthetic job records.

## Spec and tests

Spec: `specs/B-68.md`. Tests: `tests/py/backup/test_b68_backup.py`.
