# workflows/lockout (B-39)

Status: **built** on synthetic fixtures (change note `docs/changes/B-39.md`). Synthetic data only.

Explains why one person cannot sign in: reads that user's recent sign-ins through the `signins.list` read lever, maps each failure code to a plain cause from the cited table in `codes.json`, and suggests the lever a lead could approve. It never executes anything.

## Command

```
uv run --frozen python -m workflows.lockout <client> <upn> [--as tech-ana] [--prompt]
```

## Inputs

The mock sign-in log through `signins.list` (R0, audited) and `codes.json` here.

## Outputs

The technician view as JSON (with IP addresses and places), or with `--prompt` only the model-safe text. Exit 0 ran, 2 refused or bad input.

## What is mock

The sign-in log is the Graph mock; failure-code meanings are cited and some are UNVERIFIED.

## Spec and tests

Spec: `specs/B-39.md`. Tests: `tests/py/lockout/test_b39_lockout.py`.
