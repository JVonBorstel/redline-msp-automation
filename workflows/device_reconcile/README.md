# Device reconciliation (B-61)

Status: **mocked**. One client's devices, matched across the RMM, Intune and the PSA's assets, with every mismatch listed. Read-only: nothing is written, run or changed. Synthetic data only. Spec: `specs/B-61.md`.

```
uv run --frozen python -m workflows.device_reconcile contoso-dental
uv run --frozen python -m workflows.device_reconcile fabrikam-capital --as-of 2026-10-22T12:00:00Z
uv run --frozen python -m workflows.device_reconcile contoso-dental --clients config/clients   # select by binding
```

## Inputs

- RMM devices and their hardware audit (serial in `bios.serialNumber`): `adapters/rmm/` over `fixtures/rmm/<client>.json`.
- Intune managed devices: `adapters/intune/` over `fixtures/intune/<client>.json`.
- PSA configuration items: `psa_assets.py` over `psa_assets/<client>.json` (beside this workflow because `adapters/psa/` and `fixtures/psa/` are B-18's).
- `config.json`: `stale_days` (30) and `placeholder_serials`. Unknown keys fail the load.

Without `--clients` the three mocks are built from their fixtures. With `--clients <dir>` they are selected from `<dir>/<client>.json` bindings (`rmm`, `m365`, `psa`). Any implementation other than `mock` stops with `real adapter not configured` and exit 2. `config/clients/` does not exist yet (an owner step, W2-E1), so today that command stops with `error: rmm: contoso-dental.json: unreadable (FileNotFoundError)` and exit 2.

## How it matches

1. Serial first: case and spaces ignored. A placeholder serial (`To be filled by O.E.M.`, empty, ...) counts as none.
2. Then name, for a record without a usable serial: case ignored, DNS suffix dropped (`xray-ws01.contosodental.example` is `XRAY-WS01`), and only when exactly one device carries the name. Two records with different serials are never merged because their names agree.

## Outputs

JSON with `counts` (records per system, records placed, devices, devices in all three systems, findings per type, `reconciles`), `devices` (each with the systems that know it and its records), `findings` and `rmm_components`.

| Finding | Meaning |
| --- | --- |
| `only-in-one-system` | one system knows the device and the other two do not |
| `stale` | an RMM `lastSeen` or Intune `lastSyncDateTime` older than `stale_days`, or unreadable |
| `duplicate` | one system holds the device more than once |

`rmm_components` lists the RMM account's existing components with `vetted: false` and `run_by_program: false`. The program never runs a component; a script is run only after it is rewritten and registered as a lever (D6-26, B-62).

Fixture-based result: Contoso Dental 11 devices, 4 in all three systems, 5 only in one system, 3 stale, 1 duplicate; Fabrikam Capital (the clean twin) 4 devices and no findings.

## Permissions and scope

One client per run (STD-ID-6). The three adapters must be of the same client, and the RMM site's `autotaskCompanyId` must be the PSA company, or nothing is compared. A real Intune read would need a read-only Graph device scope (UNVERIFIED which one; not checked for this item). No lever is called, so there is no approval, audit record or dry-run diff: this workflow only reads.

## Known limits

- Mocks only; no RMM, Graph or PSA call is made. Field names are Verified or UNVERIFIED per `fixtures/rmm/SOURCES.md`, `fixtures/intune/SOURCES.md` and `psa_assets/SOURCES.md`.
- A server not in Intune is not a mismatch; the device lists which systems know it. Whether the MSP expects every workstation in Intune is not known.
- PSA items have no last-seen time, so they are never stale. Inactive PSA items (`isActive: false`) are compared like active ones.
- The 30-day threshold and the placeholder list are starting values, not tuned on real devices.
