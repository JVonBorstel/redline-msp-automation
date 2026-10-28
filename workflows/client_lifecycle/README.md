# Client lifecycle: discovery pack and migration pre-flight (B-77)

Status: mocked. Read-only over synthetic fixtures. Spec: `specs/B-77.md`. Offboarding a client from the MSP is a human runbook: `docs/runbooks/client-offboarding.md`.

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only.

```
uv run --frozen python -m workflows.client_lifecycle discover  --client contoso-dental [--as-of 2026-10-01] [--out .tmp/discovery]
uv run --frozen python -m workflows.client_lifecycle preflight --client contoso-dental [--plan FILE]
```

Each command prints JSON. Exit 0 means it ran (gaps and failed checks are results and are listed); exit 2 means bad input and nothing ran. There is no execute command.

## discover

Runs three read-only steps for one new client and writes `<out>/<client>/discovery.json`:

| Step | What it reads | Gaps it lists |
| --- | --- | --- |
| `baseline` | `Invoke-TenantBaseline` (TenantBaseline module, Slice B) over `fixtures/graph/`, run in a child `pwsh` with a fixed command | every finding (MFA, stale sign-in, global admins, legacy auth, break-glass, guest admins); the fix lever is shown as "proposal only" |
| `devices` | B-61 device reconciliation (`workflows/device_reconcile`) over the client's RMM, Intune and PSA mocks | only in one system, duplicate, stale. `not-run` if B-61 is absent. Stale ages are measured against the RMM snapshot's `as_of`, not `--as-of`, so the device `counts.as_of` can differ from the pack-level `as_of` |
| `licences` | `fixtures/tenant/<client>/licenses.json` and `fixtures/tenant/<client>.json` | over-assigned SKU, unused seats, licence holder not in the directory (with its retention window), disabled holder, enabled user with no licence, unknown SKU; plus, never guessed: seat count unknown (`LIC-SEATS`), unreadable retention date (`LIC-BADDATE`), account state unknown (`LIC-ACCOUNTSTATE`), no user name (`LIC-NOUPN`) |

A step that cannot run (no `pwsh`, no data for the client, a file that names another client) is `not-run` or `failed` with the reason and is itself a High gap (`DISC-<STEP>`): missing data is never an all clear. The pack holds `read_only: true`, every step with its counts, every gap with a stable id and next step, the B-55 data class of its own text, and a `sha256` over its body. The date is `--as-of` or the baseline config's `asOf`, never the clock.

## preflight

Reads `data/migrations/<client>.json` (the mailboxes to move and a synthetic, read-only snapshot of the destination tenant) and the client's `fixtures/tenant/<client>/mailboxes.json`. Three checks, each `pass` or `fail` with every problem:

- `mailbox-sizes`: each planned mailbox exists for this client and fits the destination quota. A missing size is a problem; a non-numeric or negative size is bad input (exit 2).
- `licence-availability`: free seats in the target SKU (enabled minus assigned) cover the user mailboxes. Shared mailboxes are counted apart; whether they need a licence is UNVERIFIED and left to a person. A mailbox with no recipient type is flagged and counted as needing a seat; a destination with more assigned than enabled seats is reported as an over-assignment of its own.
- `conflicting-addresses`: each mailbox's address at the destination domain is not already in use and no two mailboxes map to one address.

`ready` is true only when all three pass. `contoso-dental` is seeded with one problem per check; `fabrikam-capital` is the clean twin that passes.

## Permissions and isolation

No lever, no queue, no audit writer, no model. Each step reads one client's files only and refuses a file whose `client` is another client (C-27). Error text never copies child process output or a planned address that is not the client's (ISO-6).

## Known limits

- Fixture-based only; no Graph, RMM or Exchange connection. Every vendor field name in the fixtures is UNVERIFIED (see each fixture's note).
- The migration plan and destination snapshot are this repo's own shape; no migration tool is named (NN-04).
- The device step depends on B-61 (on main); if it is absent the pack reports devices as not known.
- In Python, `from workflows.client_lifecycle import run_preflight` (or import `preflight` from the `preflight` submodule); the package attribute `preflight` is the submodule.
