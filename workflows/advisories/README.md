# workflows/advisories

Status: **mocked** (fixtures only). Independently built prototype. Synthetic data only. Spec: `specs/B-47.md`.

## What it does

Matches a CISA-KEV-shaped feed to each client's software inventory and joins Nessus-shaped scan rows and vPenTest-shaped findings to the match by CVE. It prints, per CVE, the affected clients and devices; a ranked list that shows every factor (exposure, criticality, ransomware use, KEV due date); and an emergency-patch list with proposed change windows.

## Run it

```
uv run --frozen python -m workflows.advisories contoso-dental
uv run --frozen python -m workflows.advisories              # every client in the fixtures
uv run --frozen python -m workflows.advisories --as-of 2026-10-21T12:00:00Z
```

Exit 0 = ran, 2 = bad input (unknown client, changed fixture shape, a file for another client).

## Inputs, outputs, permissions

- Inputs: files under `fixtures/advisories/` only (`kev-feed.json`, `inventory/`, `scans/nessus/`, `scans/vpentest/`). Sources and per-field status: `fixtures/advisories/SOURCES.md`.
- Output: JSON on stdout. No file is written.
- Permissions: none needed. It calls no lever, adapter, RMM, scanner or network. It is a read-only report (R0); acting on the emergency list is R2 and a lead's decision.

## Dry-run example

Every proposal in `emergency_patch_list` has `"deployed": false` and a `proposed_window` taken from the windows the client's inventory file declares. Nothing is deployed, scheduled or sent.

## Eval result

None: there is no model and no accuracy claim. The counts in `summary` and each client's `counts` are computed from the fixtures and reconcile (a test recomputes them from the raw files). Fixture-based.

## Known limits

See `specs/B-47.md`: product-level match only (the KEV feed has no version range), a neutral inventory shape, UNVERIFIED Nessus columns and vPenTest shape, fixture change windows.
