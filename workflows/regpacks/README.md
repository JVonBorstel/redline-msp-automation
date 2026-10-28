# workflows/regpacks (B-52)

Status: **built** on synthetic fixtures (change note `docs/changes/B-52.md`). Synthetic data only.

One pack per client: a page per regime the client record lists (HIPAA, FTC Safeguards, Regulation S-P), each mapping line tied to the governance-map row it cites, plus a BAA and vendor tracker, all hashed into a manifest. It changes no tenant, role or identity.

## Command

```
uv run --frozen python -m workflows.regpacks build contoso-dental --as lead-lee --as-of 2026-10-27
uv run --frozen python -m workflows.regpacks build fabrikam-capital --as lead-lee --write
uv run --frozen python -m workflows.regpacks verify build/regpacks/2026-10-27/contoso-dental [--audit-dir DIR]
```

## Inputs

`fixtures/regpacks/`, `docs/map/05-governance.md`, `map/controls.json` and `config/identities.json`.

## Outputs

With `--write`, a folder under `build/regpacks/<date>/<client>/` with `manifest.json` and its `.sha256`; without it, the manifest hash only. Exit 0 done, 1 verify mismatch, 2 bad input or refused.

## What is mock

Client records and vendor data are synthetic; Regulation S-P lines stay hedged until checked against the rule text.

## Spec and tests

Spec: `specs/B-52.md`. Tests: `tests/py/regpacks/test_b52_regpacks.py`.
