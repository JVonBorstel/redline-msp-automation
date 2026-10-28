# Device-security fixture sources (B-64)

Status: **mocked**. These fixtures are **synthetic**: invented clients (Contoso Dental, Fabrikam Capital), invented people marked "(synthetic)", invented serials and ids (`c0000000-...` for Contoso, `f0000000-...` for Fabrikam), `.example` domains. Nothing was captured from a real tenant. They are pinned to `asOf` 2026-10-22T12:00:00Z. Results computed from them are fixture-based.

They sit beside the workflow because `fixtures/intune/` and `fixtures/rmm/` are B-61's. Compliance and encryption come from `fixtures/intune/<client>.json` (see its `SOURCES.md`); the LAPS, Autopilot and hire data come from here.

- One file per client, `workflows/device_reports/fixtures/<client>.json`; its `client` matches the file name and `tenantId` equals the client's Intune tenant (the report refuses the file otherwise).
- `localCredentials` holds **metadata only**: no password and no credential list, in the fixture or in the code that reads it (an allow-list, `LAPS_FIELDS`). Each file also holds one LAPS record of the **other** client's device on purpose; the report counts it as a gap and never as coverage.
- No page of Microsoft's documentation was opened for this item and no call was made, so **no field below is marked Verified**. Every shape is written from memory of the Graph v1.0 `deviceLocalCredentialInfo` and `windowsAutopilotDeviceIdentity` resources.

## Field status

Every field in the fixtures is in this table; a test (`test_b64_1_every_overlay_fixture_field_is_marked_verified_or_unverified`) checks it.

| Entity | Field | Status |
| --- | --- | --- |
| file | `_note` | UNVERIFIED (this repo's own key, STD-FX-3) |
| file | `client` | UNVERIFIED (this repo's own key) |
| file | `asOf` | UNVERIFIED (this repo's own key; pins the fixture) |
| file | `tenantId` | UNVERIFIED (this repo's own key; the Intune tenant the data belongs to) |
| file | `localCredentials` | UNVERIFIED (this repo's own key; holds the LAPS metadata response) |
| file | `autopilotDevices` | UNVERIFIED (this repo's own key; holds the Autopilot identities response) |
| file | `incomingHires` | UNVERIFIED (this repo's own key; the source of hires is open) |
| localCredentials | `value` | UNVERIFIED (standard Graph collection shape, not re-read) |
| autopilotDevices | `value` | UNVERIFIED (standard Graph collection shape, not re-read) |
| value | `id` | UNVERIFIED (for LAPS: the Entra device id, joined to Intune's `azureADDeviceId`; for Autopilot: the identity id) |
| value | `deviceName` | UNVERIFIED |
| value | `lastBackupDateTime` | UNVERIFIED (when the password was last backed up; the freshness check uses it) |
| value | `refreshDateTime` | UNVERIFIED (when the next rotation is due) |
| value | `serialNumber` | UNVERIFIED |
| value | `groupTag` | UNVERIFIED |
| value | `enrollmentState` | UNVERIFIED (enum value `notContacted` assumed) |
| value | `deploymentProfileAssignmentStatus` | UNVERIFIED (enum values `assignedInSync`, `notAssigned` assumed; only `assignedInSync` counts as ready) |
| value | `lastContactedDateTime` | UNVERIFIED |
| incomingHires | `hireId` | UNVERIFIED (this repo's own key) |
| incomingHires | `displayName` | UNVERIFIED (this repo's own key) |
| incomingHires | `userPrincipalName` | UNVERIFIED (this repo's own key) |
| incomingHires | `startDate` | UNVERIFIED (this repo's own key) |
| incomingHires | `assignedSerial` | UNVERIFIED (this repo's own key; null means no device assigned yet) |

## Seeded problems (STD-FX-4)

Contoso Dental is seeded; Fabrikam Capital is the clean twin (its only follow-up is the file server, which has no Intune record).

- `LAPTOP-PNAIR`: LAPS password last backed up 2026-08-20, more than 35 days before `asOf` (stale backup).
- `OFFICE-MGR`: no LAPS record at all (not backed up); it is also the device B-61 finds stale in Intune.
- A LAPS record of Fabrikam's `FAB-WS01` in Contoso's file (and Contoso's `FRONTDESK-01` in Fabrikam's): a gap, never coverage.
- Hires: `H-CD-001` ready; `H-CD-002` registered in Autopilot but no profile assigned (starts in 6 days, urgent); `H-CD-003` has no device assigned; `H-CD-004` has a serial that is not in Autopilot. One Autopilot device is not assigned to any hire.
