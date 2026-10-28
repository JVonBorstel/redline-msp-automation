# DeviceOps

Seven PowerShell levers for Tier 1 device fixes (B-62): restart the Print Spooler, reconnect a mapped drive, reset an Outlook profile, move old temp files to quarantine, restart an approved service, reboot a workstation, reboot a server. They work on the **mock RMM** device state (`mock/<client>/devices.json`, or the same file in `$env:REDLINE_MOCK_TENANT_DIR/<client>/` when it exists there, which is how the tests isolate it). Synthetic data only; nothing talks to a real RMM. Every shape is UNVERIFIED: read `SOURCES.md` first.

| Lever (registry.d/device.json) | Function | Script | Risk | Window (runner rule) |
| --- | --- | --- | --- | --- |
| `device.restart-spooler` | `Restart-DevicePrintSpooler` | `dev-spooler-restart` | R1 | none |
| `device.repair-mapped-drive` | `Repair-DeviceMappedDrive` | `dev-drive-repair` | R1 | none |
| `device.reset-outlook-profile` | `Reset-DeviceOutlookProfile` | `dev-outlook-reset` | R2 | none |
| `device.cleanup-temp` | `Clear-DeviceTemp` | `dev-temp-cleanup` | R1 | none |
| `device.restart-service` | `Restart-DeviceService` | `dev-service-restart` | R1 | none |
| `device.reboot` | `Restart-DeviceWorkstation` | `dev-reboot-workstation` | R2 | `business-hours` |
| `device.reboot-server` | `Restart-DeviceServer` | `dev-reboot-server` | R2 | `maintenance` |

- **Vetted scripts only.** `vetted-scripts.json` holds one hash-pinned script per lever. The module refuses to run anything if any entry no longer matches its hash. No lever takes a script, command or path parameter; the registry bounds every parameter (a device uid pattern, a drive letter, an account name, an enum of five service names).
- **Dry-run equals execute.** The change is a list of field edits worked out from the state. `-WhatIf` returns that list and writes nothing; execute applies exactly that list, so the two diffs are the same by construction, and the runner compares them again. The same call twice is an empty diff (the mock is convergent; a real reboot is not, which is why the runner's replay guard also applies).
- **Proposal data.** `data` carries `script` (id, version, digest), `device` (uid, hostname, class), `would_run` (the steps), `verification` (the checks, `planned` or `passed`), `rollback` (a proposal for a person, `automated: false`, no undo lever), `remote_session` (the latest remote-support session on that device before the as-of moment, or `null`) and `plan_digest` (24 hex characters over lever, client, device, script hash and diff).
- **Verification.** After applying, the module re-reads the state and evaluates each check. A failed check returns a refusal that starts `Verification failed`; the runner records an error after the audit record, so the audit shows what was attempted.
- **No time logic.** The module never reads a clock. `reboot` and `reboot-server` carry `window` in the registry and the runner (B-42) enforces it; the module only checks that the device is the right class (workstation or server) and online.
- **Per-client scope.** The client id is a slug before it is a path. A device of another client, of another site, or one that does not exist answers with the same sentence.
- **Tests:** `pwsh -NoProfile -File levers/powershell/DeviceOps/tests/DeviceOps.Tests.ps1` (module behaviour) and `uv run --frozen pytest -p no:cacheprovider tests/py/devices/test_b62_remed.py` (registry, runner gates, windows, caps, approval binding, goldens; needs `pwsh` 7.4+).
