# workflows/licensing (B-75)

Status: **built** on synthetic fixtures (change note `docs/changes/B-75.md`). Synthetic data only.

For one client: bought, assigned, orphaned, duplicate, unused and active seats per SKU, billed versus counted users and devices, renewals coming due, and hardware past its lifecycle, as a review report of proposals. It buys, cancels, assigns and removes nothing.

## Command

```
uv run --frozen python -m workflows.licensing report contoso-dental --as-of 2026-10-22 --within-days 90
```

## Inputs

Synthetic fixtures under `fixtures/tenant/`, `fixtures/rmm/`, `fixtures/licensing/` and the PSA assets in `workflows/device_reconcile/psa_assets/`. Without `--as-of` the fixture's pinned date is used, never the clock.

## Outputs

`build/licensing/<as_of>/<client>.json`, `.md` and `.json.sha256`. Exit 0 written, 2 bad input (nothing written).

## What is mock

Tenant, RMM, PSA and licensing data are synthetic fixtures.

## Spec and tests

Spec: `specs/B-75.md`. Tests: `tests/py/licensing/test_b75_licensing.py`.
