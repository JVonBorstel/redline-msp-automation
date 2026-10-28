# workflows/access_review (B-49)

Status: **built** on synthetic fixtures (change note `docs/changes/B-49.md`). Synthetic data only.

Lists every directory-role member of one client's tenant and every repo identity (agent or technician) that may act for it, with its role, as a dated and hashed export a lead decides row by row (keep, remove, investigate). An MSP export lists every repo identity with its full client list. It changes no role, identity or tenant.

## Command

```
uv run --frozen python -m workflows.access_review export contoso-dental --as lead-lee --as-of 2026-10-23
uv run --frozen python -m workflows.access_review export --msp --as lead-lee --as-of 2026-10-23
uv run --frozen python -m workflows.access_review decide build/access-review/2026-Q4/contoso-dental.json --as lead-lee --on 2026-10-24 --decisions decisions.json
uv run --frozen python -m workflows.access_review verify build/access-review/2026-Q4/contoso-dental.json
```

## Inputs

The Graph-shaped mock `fixtures/graph/<folder>/directoryRoles.json`, `config/identities.json`, `levers/registry.json` and `needs.json` here (which clients each agent's workflow needs); `--decisions` is a JSON object `{row_id: keep|remove|investigate}`.

## Outputs

`build/access-review/<quarter>/<client>.json` (or `_msp.json`) with a `.sha256` sidecar, the decided file, and one audit record per export or decision in the chain under `.tmp/demo/audit`. Exit 0 done, 1 verify mismatch, 2 bad input or refused.

## What is mock

The tenant is the Graph mock and the identities are a static synthetic file; no real directory is read.

## Spec and tests

Spec: `specs/B-49.md`. Tests: `tests/py/access_review/test_b49_access_review.py`.
