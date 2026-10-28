# workflows/evidence (B-51)

Status: **built** on synthetic fixtures (change note `docs/changes/B-51.md`). Synthetic data only.

Builds one evidence bundle per period and scope (a client, or the MSP): the audit-chain verification, an approvals and denials summary, the registry snapshot with lever versions, the access-review files and, for the MSP, change records from the local git log. Every file is hashed into a manifest. It supports a person's attestation and never asserts one.

## Command

```
uv run --frozen python -m workflows.evidence bundle contoso-dental --period 2026-10 --as lead-lee --as-of 2026-11-02
uv run --frozen python -m workflows.evidence bundle --msp --period 2026-10 --as lead-lee --write
uv run --frozen python -m workflows.evidence verify build/evidence/2026-10/contoso-dental [--audit-dir DIR]
```

## Inputs

The audit chains under `.tmp/demo/audit`, `levers/registry.json`, `config/identities.json`, the B-49 files under `build/access-review`, and the local git log (`--no-git` lists that gap instead).

## Outputs

With `--write`, a folder under `build/evidence/<period>/` with `manifest.json` and its `.sha256`; without it, the manifest only. Exit 0 done, 1 verify mismatch, 2 bad input or refused.

## What is mock

Every source is this repo's synthetic state; no auditor has seen a bundle.

## Spec and tests

Spec: `specs/B-51.md`. Tests: `tests/py/evidence/test_b51_evidence.py`.
