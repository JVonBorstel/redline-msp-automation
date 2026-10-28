# Intune fixture sources

Status: **mocked**. These fixtures are **synthetic**: invented clients (Contoso Dental, Fabrikam Capital), invented people marked "(synthetic)", invented serials and ids (`c0000000-...` for Contoso, `f0000000-...` for Fabrikam), `.example` domains. Nothing was captured from a real tenant. They are pinned to `asOf` 2026-10-22T12:00:00Z. Results computed from them are fixture-based.

- One file per client, `fixtures/intune/<client>.json`; its `client` matches the file name and `tenantId` equals the client's tenant GUID (the `m365` binding's `external_id`, the same GUIDs `tests/py/adapters/test_b19_graph.py` uses).
- The mock adapter is `adapters/intune/mock.py` (`IntuneMock`). It only reads these files and has no write, retire, wipe, lock or sync method.
- `managedDevices` is the body of one `GET https://graph.microsoft.com/v1.0/deviceManagement/managedDevices` request: a collection response `{"@odata.context": ..., "value": [...]}`. The application permission a real read would need (`DeviceManagementManagedDevices.Read.All`) is UNVERIFIED: it was not re-read for this item.

Source, read 2026-10-23: [managedDevice resource type (v1.0)](https://learn.microsoft.com/en-us/graph/api/resources/intune-devices-manageddevice?view=graph-rest-1.0). It was read through a summarising tool that returned the property table and the JSON representation. "Verified" below means the property name is in that table. Values are invented; the enum values used (`company`, `compliant`, `mdm`, `windowsAzureADJoin`) are in the page's lists of possible values.

## Field status

Every field in the fixtures is in this table; a test (`test_b61_4_every_intune_and_psa_fixture_field_is_marked`) checks it.

| Entity | Field | Status |
| --- | --- | --- |
| file | `_note` | UNVERIFIED (this repo's own key, STD-FX-3) |
| file | `client` | UNVERIFIED (this repo's own key) |
| file | `asOf` | UNVERIFIED (this repo's own key; pins the fixture) |
| file | `tenantId` | UNVERIFIED (this repo's own key; the tenant the response came from) |
| file | `managedDevices` | UNVERIFIED (this repo's own key; holds the response body) |
| managedDevices | `@odata.context` | UNVERIFIED (standard Graph collection shape, not re-read for this item) |
| managedDevices | `value` | UNVERIFIED (standard Graph collection shape, not re-read for this item) |
| value | `id` | Verified 2026-10-23 |
| value | `deviceName` | Verified 2026-10-23 |
| value | `managedDeviceOwnerType` | Verified 2026-10-23 |
| value | `enrolledDateTime` | Verified 2026-10-23 |
| value | `lastSyncDateTime` | Verified 2026-10-23 (the last successful sync with Intune; the stale check uses it) |
| value | `operatingSystem` | Verified 2026-10-23 |
| value | `osVersion` | Verified 2026-10-23 |
| value | `complianceState` | Verified 2026-10-23 |
| value | `managementAgent` | Verified 2026-10-23 |
| value | `isEncrypted` | Verified 2026-10-23 |
| value | `userPrincipalName` | Verified 2026-10-23 |
| value | `userDisplayName` | Verified 2026-10-23 |
| value | `model` | Verified 2026-10-23 |
| value | `manufacturer` | Verified 2026-10-23 |
| value | `serialNumber` | Verified 2026-10-23 |
| value | `azureADDeviceId` | Verified 2026-10-23 |
| value | `deviceEnrollmentType` | Verified 2026-10-23 |

Not imitated: paging (`@odata.nextLink`), `$select` and `$filter`, throttling, and every action on the resource (retire, wipe, remoteLock, syncDevice and the rest). Device R3 actions are B-65's levers.

## Seeded problems (STD-FX-4)

Contoso Dental is seeded; Fabrikam Capital is the clean twin.

- `LAPTOP-PNAIR` (`...e0003`): enrolled in Intune, but no RMM agent and no PSA item (only in one system).
- `OFFICE-MGR` (`...e0004`): last synced 2026-09-01, more than 30 days before `asOf` (stale).
- `operatory-02` (`...e0002`): lower-case name; it still matches by serial.
