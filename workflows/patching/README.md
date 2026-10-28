# workflows/patching

Status: **mocked** (fixtures only). Independently built prototype. Synthetic data only. Spec: `specs/B-67.md`.

## What it does

For one client and one monthly patch cycle it writes a pack a lead can read and a human can approve from: the released updates by ring with their known issues; compliance counts per device; failed patches grouped by error code with a suggested remediation lever; a server maintenance window with a client notice draft; and a version report for network firmware. It proposes and reports. It approves, deploys, schedules, sends and upgrades nothing.

## Run it

```
uv run --frozen python -m workflows.patching clients
uv run --frozen python -m workflows.patching build contoso-dental
uv run --frozen python -m workflows.patching verify build/patching/2026-10/contoso-dental.json
```

`build` writes `build/patching/<cycle>/<client>.json` and `<client>.md`, each with a `.sha256` sidecar in `sha256sum` format, so `sha256sum -c` or `Get-FileHash` re-checks them without this code. The Markdown ends with the SHA-256 of the JSON it was rendered from. Exit 0 = done (`verify`: matches), 1 = mismatch, 2 = bad input (unknown client, changed fixture shape).

## Inputs, outputs, permissions

- Inputs: `fixtures/patches/` (`releases.json`, `<client>.json`; sources and seeded cases in `SOURCES.md`), the client's own device list through the RMM mock adapter (`fixtures/rmm/`, B-61), and `config.json` (thresholds and the error-code table). Nothing else is read; no network.
- Output: the two files above, under `build/` (not committed). The JSON also lists the SHA-256 of every source file it read.
- Permissions: none needed. It calls no lever, runs no script and sends nothing. Every proposal carries `deployed: false`, every approval field is empty, and the notice says `draft - not sent`.

## How to read the pack

- **Review pack.** Each update has a proposed action per ring: `approve-first-ring`, `promote-after-soak`, `hold` (a known issue is open, or its fix is not in the release list) or `defer` (optional update). `decision` and `approver` stay empty for the engineer.
- **Compliance.** Every RMM device of the client has exactly one status (`compliant`, `non-compliant`, `stale`, `no-patch-data`) and the counts add up to the RMM device list. An update released less than `grace_days` ago is not required yet. A patch record for a device that is not in this client's RMM site is dropped and counted.
- **Failed patches.** Grouped by error code. `suggested_lever` is a name; `lever_status` says whether the lever exists in the registry or is only proposed.
- **Server windows.** The client's declared weekday and time, the first date at least `notice_lead_days` after the cycle date. The notice names only this client's servers.
- **Firmware.** `advisory-open`, `behind`, `current` or `unknown`. A person plans and performs any upgrade.

## Eval result

None: there is no model and no accuracy claim. Counts are computed from the fixtures and a test recomputes them from the raw files. Fixture-based.

## Known limits

See `specs/B-67.md`: the patch-state shape is this repo's own and unverified against any real RMM or Intune, the error-code meanings are UNVERIFIED, no remediation lever is registered yet (B-62), the window uses a fixed UTC offset, and untrusted fixture text is passed through the injection guard.
