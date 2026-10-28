# workflows/monitoring (B-83)

Status: **built** on synthetic fixtures (change note `docs/changes/B-83.md`). Synthetic data only.

Alert rules as versioned data (`rules.json`: audit-chain failure, breaker open, budget exhaustion, approval backlog age, dead-letter growth) and a deterministic evaluator that turns a snapshot into alerts. Nothing here sends an alert.

## Command

```
uv run --frozen python -m workflows.monitoring evaluate --snapshot workflows/monitoring/fixtures/incident-all.json [--rules FILE]
uv run --frozen python -m workflows.monitoring check-rules [--rules FILE]
```

## Inputs

A snapshot file (synthetic incidents in `fixtures/` here, or one built from the real stores by `sources.py`) and `rules.json`.

## Outputs

Alerts as JSON on stdout, with ids, counts and ages, never content. Exit 0 no alerts (or rules valid), 1 at least one alert, 2 bad input.

## What is mock

Snapshots are synthetic replays; thresholds are prototype defaults, not tuned on real traffic.

## Spec and tests

Spec: `specs/B-83.md`. Tests: `tests/py/obs/test_b83_obs.py`.
