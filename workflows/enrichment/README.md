# workflows/enrichment (B-44)

Status: **built** on synthetic fixtures (change note `docs/changes/B-44.md`). Synthetic data only.

`pack` gives the analyst one pack for one user alert: user, device and recent sign-in facts, each citing the read lever and field it came from, with gaps listed instead of guessed. `review` lists risky users and the levers a lead could approve. Only read levers are called.

## Command

```
uv run --frozen python -m workflows.enrichment pack <client> <upn> [--as tech-ana] [--prompt]
uv run --frozen python -m workflows.enrichment review <client> [--as tech-ana]
```

## Inputs

The mock tenant through R0 read levers (audited as who asked about whom).

## Outputs

JSON on stdout (the technician view holds times and places), or with `--prompt` only the model-safe text. Exit 0 ran, 2 refused or bad input.

## What is mock

The tenant and sign-in data are the Graph mock; no write lever runs.

## Spec and tests

Spec: `specs/B-44.md`. Tests: `tests/py/enrichment/test_b44_enrichment.py`.
