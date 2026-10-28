# workflows/restore_tests (B-69)

Status: **built** on synthetic fixtures (change note `docs/changes/B-69.md`). Synthetic data only.

`run` restores one synthetic item to a mock alternate location, compares its hash with the one recorded at backup time, writes the evidence and pins its hash in the client's audit chain. It never touches an original location. Restore requests to an alternate location are proposals for the normal queue.

## Command

```
uv run --frozen python -m workflows.restore_tests run contoso-dental --as-of 2026-10-21 [--seed s] [--item RI-1001]
uv run --frozen python -m workflows.restore_tests verify build/restore-tests/contoso-dental/2026-10-21.json
```

## Inputs

The restorable-item catalog mock `catalog/<client>.json` here (on the B-68 backup adapter) and `config.json`.

## Outputs

`build/restore-tests/<client>/<date>.json` with a `.sha256`, and an audit record under `.tmp/demo/audit`. Exit 0 passed (verify: intact), 1 failed (evidence still written), 2 bad input, refused or not run.

## What is mock

The backup product, its catalog and the alternate location are mocks; nothing is written to disk as a restore.

## Spec and tests

Spec: `specs/B-69.md`. Tests: `tests/py/backup/test_b69_restore.py`.
