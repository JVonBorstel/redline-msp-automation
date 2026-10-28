# workflows/factpack (B-37)

Status: **built** on synthetic fixtures (change note `docs/changes/B-37.md`). Synthetic data only.

Puts what is known about one person or one Conditional Access policy of one client on a single page for the human who decides a termination, a caller verification, a role grant or a policy change. It assembles facts only: no lever, no proposal, no runner, no file written.

## Command

```
uv run --frozen python -m workflows.factpack termination --client contoso-dental --target <upn>
uv run --frozen python -m workflows.factpack policy --client contoso-dental --target "Require MFA for all users"
```

## Inputs

The Graph mock under `fixtures/graph/` and the synthetic device list `fixtures/devices.json` here. Kinds: `termination`, `caller`, `role`, `policy`.

## Outputs

JSON on stdout. Exit 0 ran, 2 bad input or a target not in this client's data.

## What is mock

The tenant and the device list are synthetic; device field names are UNVERIFIED.

## Spec and tests

Runbooks: `docs/runbooks/urgent-termination.md`, `docs/runbooks/caller-verification.md`. Tests: `tests/py/factpack/test_b37_factpack.py`.
