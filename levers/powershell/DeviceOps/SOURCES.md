# DeviceOps sources and field status

Status: **mocked**. Everything under `mock/` is **synthetic**: invented clients (Contoso Dental, Fabrikam Capital), invented machines, accounts, sessions and ids. Nothing was captured from a real RMM or remote-support tool. No vendor page was opened for this item and no call was made to any real service, so **every field below is UNVERIFIED**. Results computed from these files are fixture-based.

## What the files follow

- `mock/<client>/devices.json` is a mock of the RMM's view of one site's devices, extended with the small amount of device state the seven scripts act on. Device identity fields (`uid`, `hostname`, `siteUid`, `deviceType`, `online`) are copied from `fixtures/rmm/<client>.json`, which follows the public Datto RMM API v2 (field status in `fixtures/rmm/SOURCES.md`); a test checks they still agree. The Datto RMM API has no endpoint that reads a device's services, print queue, mapped drives or Outlook profiles, so the rest of the device record is this repo's own invention and carries no claim about what a real RMM reports.
- `mock/<client>/remote-sessions.json` is shaped like a session log exported from a remote-support tool such as Splashtop (MP-13, `docs/map/07-msp-profile.md`, where the tool is cited but not confirmed). The field names were written from memory of what such a log holds (a session id, the computer, the technician, start and end). No Splashtop page was read, so each one is UNVERIFIED.
- `vetted-scripts.json` holds, for each lever, the plain-language steps a person approves and a SHA-256 over `script_id`, `version` and the steps. The steps are descriptions: the mock RMM runs none of them and no real script is stored in this repo. Real components that already exist in an RMM stay read-only in `adapters/rmm` and are never run by the program until someone vets the exact script into this file and the registry (D6-26).

## Field status

| File | Field | Status |
| --- | --- | --- |
| devices | `_meta` | UNVERIFIED (this repo's own key; holds `client`, `siteUid`, `as_of`, `note`) |
| devices | `devices` | UNVERIFIED (this repo's own key; the device list) |
| devices | `uid`, `hostname`, `siteUid`, `deviceType`, `online` | UNVERIFIED (names follow `fixtures/rmm`, whose status is in `fixtures/rmm/SOURCES.md`) |
| devices | `lastBoot`, `pendingReboot` | UNVERIFIED (this repo's own keys) |
| devices | `services` | UNVERIFIED (this repo's own key; service name to `status` and `health`) |
| devices | `printQueue`, `mappedDrives`, `outlookProfiles` | UNVERIFIED (this repo's own keys) |
| devices | `tempBytes`, `tempStaleBytes`, `tempQuarantineBytes` | UNVERIFIED (this repo's own keys; whole bytes) |
| devices | `faults` | UNVERIFIED (this repo's own key; names a script that fails on this mock device so verification can be tested) |
| sessions | `_meta` | UNVERIFIED (this repo's own key; holds `client`, `as_of`, `note`) |
| sessions | `sessions` | UNVERIFIED (this repo's own key; the log rows) |
| sessions | `session_id` | UNVERIFIED (name and format; written from memory of a remote-support session log) |
| sessions | `computer_name` | UNVERIFIED (the log is matched to a device by computer name, case-insensitive, because a session log carries no RMM uid) |
| sessions | `technician` | UNVERIFIED (a synthetic label such as `tech-session-a`, not an identity in `config/identities.json`) |
| sessions | `start_time` | UNVERIFIED (name and UTC ISO 8601 format) |
| sessions | `end_time` | UNVERIFIED (name and UTC ISO 8601 format) |
| sessions | `session_type` | UNVERIFIED (the value `remote-control` is invented) |
| sessions | `status` | UNVERIFIED (the value `ended` is invented) |
| catalog | `script_id`, `version`, `steps`, `sha256` | UNVERIFIED (this repo's own keys) |

## What the mock does not model

- A real RMM job runs asynchronously and reports later; the mock changes the record and reads it back at once.
- Windows service names (`Spooler`, `Dnscache`, `W32Time`, `BITS`, `wuauserv`, `LanmanWorkstation`) are recalled from memory; the `health` value (`Ok`, `Hung`) is invented because Windows reports a state, not a health.
- The Outlook profile reset, mapped-drive reconnect and temp quarantine are described, not implemented, as Windows commands.
- Multiple profiles per user, per-user temp folders, network drives mapped by group policy, and a reboot that interrupts an update are not modelled.
