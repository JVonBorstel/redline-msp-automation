# RMM fixture sources

Status: **mocked**. These fixtures are **synthetic**: invented clients (Contoso Dental, Fabrikam Capital), invented machine names, serials and ids (`c0000000-...` for Contoso, `f0000000-...` for Fabrikam, `a0000000-...` for the MSP account), `.example` URLs. Nothing was captured from a real RMM. They are pinned to `asOf` 2026-10-22T12:00:00Z. Results computed from them are fixture-based.

- One file per client, `fixtures/rmm/<client>.json`; its `client` matches the file name and `site.uid` equals the client's RMM site uid (the `rmm` binding's `external_id`).
- The mock adapter is `adapters/rmm/mock.py` (`RmmMock`). It only reads these files and has no method that runs anything.
- Each file also holds one device (with its audit), one open alert and one job of the **other** client's site. They are there on purpose: the decoy device carries this client's first hostname and serial, and a test shows it is never returned, matched or counted (B61-2, C-27).

## What the shape follows (D6-01, B61-4)

The shape follows the public Datto RMM API v2. The MSP's RMM is INFERRED as Datto RMM (`docs/map/07-msp-profile.md`), not confirmed.

| Fixture part | Request it stands in for |
| --- | --- |
| `site` | `GET /v2/site/{siteUid}` |
| `devices` | `GET /v2/site/{siteUid}/devices` (one page) |
| `deviceAudits[<deviceUid>]` | `GET /v2/audit/device/{deviceUid}` (the serial is in `bios.serialNumber`) |
| `alerts` | `GET /v2/site/{siteUid}/alerts/open` (one page) |
| `jobsBySite[<siteUid>][]` | `GET /v2/job/{uid}` for jobs a technician already ran; never created by the program |
| `components` | `GET /v2/account/components` (one page), listed read-only (D6-26) |

Sources, read 2026-10-23:

- Datto RMM help, "Datto RMM API v2": https://rmm.datto.com/help/en/Content/2SETUP/APIv2.htm (endpoint paths; `uid` and `deviceClass` for audits; `alertUid` and `alertContext` with `@class`; job `uid` and `status` `active`/`completed`; `pageDetails` with `prevPageUrl` and `nextPageUrl`).
- The platform's public OpenAPI document: https://concord-api.centrastage.net/api/v3/api-docs (schema property names for Site, Device, DevicesStatus, DevicesType, DeviceAudit, bios, SystemInfo, Alert, alertSourceInfo, alertMonitorInfo, Component, ComponentVariable, Job, PaginationData).

How it was read: both pages were fetched and read through a summarising tool, not line by line by a person. "Verified" below means the property **name** appeared in that reading. No value, format or enum was verified, and no call was made to a real Datto RMM account.

## Field status

Every field in the fixtures is in this table; a test (`test_b61_4_every_rmm_fixture_field_is_marked_verified_or_unverified`) checks it. The entity column is the key that holds the field (`devices` holds both the page wrapper and each device record).

| Entity | Field | Status |
| --- | --- | --- |
| file | `_note` | UNVERIFIED (this repo's own key, STD-FX-3) |
| file | `client` | UNVERIFIED (this repo's own key) |
| file | `asOf` | UNVERIFIED (this repo's own key; pins the fixture) |
| file | `site` | UNVERIFIED (this repo's own key; holds the site response) |
| file | `devices` | UNVERIFIED (this repo's own key; holds the device page) |
| file | `deviceAudits` | UNVERIFIED (this repo's own key; audits keyed by device uid) |
| file | `alerts` | UNVERIFIED (this repo's own key; holds the alert page) |
| file | `jobsBySite` | UNVERIFIED (this repo's own key; jobs keyed by site uid, because the job response carries no site) |
| file | `components` | UNVERIFIED (this repo's own key; holds the component page) |
| site | `id` | Verified 2026-10-23 (OpenAPI) |
| site | `uid` | Verified 2026-10-23 (help page, OpenAPI) |
| site | `accountUid` | Verified 2026-10-23 (OpenAPI) |
| site | `name` | Verified 2026-10-23 (OpenAPI) |
| site | `description` | Verified 2026-10-23 (OpenAPI) |
| site | `onDemand` | Verified 2026-10-23 (OpenAPI) |
| site | `devicesStatus` | Verified 2026-10-23 (OpenAPI) |
| site | `autotaskCompanyName` | Verified 2026-10-23 (OpenAPI) |
| site | `autotaskCompanyId` | Verified 2026-10-23 (OpenAPI); written as a string here, the real type is UNVERIFIED |
| site | `portalUrl` | Verified 2026-10-23 (OpenAPI) |
| devicesStatus | `numberOfDevices` | Verified 2026-10-23 (OpenAPI) |
| devicesStatus | `numberOfOnlineDevices` | Verified 2026-10-23 (OpenAPI) |
| devicesStatus | `numberOfOfflineDevices` | Verified 2026-10-23 (OpenAPI) |
| devices | `pageDetails` | Verified 2026-10-23 (help page) |
| devices | `devices` | UNVERIFIED (the array's key name in the page response) |
| alerts | `pageDetails` | Verified 2026-10-23 (help page) |
| alerts | `alerts` | UNVERIFIED (the array's key name in the page response) |
| components | `pageDetails` | Verified 2026-10-23 (help page) |
| components | `components` | UNVERIFIED (the array's key name in the page response) |
| pageDetails | `count` | Verified 2026-10-23 (OpenAPI PaginationData) |
| pageDetails | `totalCount` | Verified 2026-10-23 (OpenAPI PaginationData) |
| pageDetails | `prevPageUrl` | Verified 2026-10-23 (help page, OpenAPI) |
| pageDetails | `nextPageUrl` | Verified 2026-10-23 (help page, OpenAPI) |
| devices | `id` | Verified 2026-10-23 (OpenAPI Device) |
| devices | `uid` | Verified 2026-10-23 (help page, OpenAPI) |
| devices | `siteId` | Verified 2026-10-23 (OpenAPI) |
| devices | `siteUid` | Verified 2026-10-23 (OpenAPI) |
| devices | `siteName` | Verified 2026-10-23 (OpenAPI) |
| devices | `deviceType` | Verified 2026-10-23 (OpenAPI) |
| devices | `hostname` | Verified 2026-10-23 (OpenAPI) |
| devices | `intIpAddress` | Verified 2026-10-23 (OpenAPI) |
| devices | `operatingSystem` | Verified 2026-10-23 (OpenAPI) |
| devices | `domain` | Verified 2026-10-23 (OpenAPI) |
| devices | `online` | Verified 2026-10-23 (OpenAPI) |
| devices | `deleted` | Verified 2026-10-23 (OpenAPI) |
| devices | `lastSeen` | Verified 2026-10-23 (OpenAPI); the value format is UNVERIFIED (ISO 8601 here; the reconciler also reads epoch milliseconds) |
| devices | `lastAuditDate` | Verified 2026-10-23 (OpenAPI); value format UNVERIFIED |
| devices | `creationDate` | Verified 2026-10-23 (OpenAPI); value format UNVERIFIED |
| devices | `deviceClass` | Verified 2026-10-23 (help page, OpenAPI); the value `device` is UNVERIFIED |
| deviceType | `category` | Verified 2026-10-23 (OpenAPI DevicesType); values (`Desktop`, `Laptop`, `Server`) UNVERIFIED |
| deviceType | `type` | Verified 2026-10-23 (OpenAPI DevicesType); values UNVERIFIED |
| deviceAudit | `bios` | Verified 2026-10-23 (OpenAPI DeviceAudit) |
| deviceAudit | `systemInfo` | Verified 2026-10-23 (OpenAPI DeviceAudit) |
| bios | `instance` | Verified 2026-10-23 (OpenAPI) |
| bios | `releaseDate` | Verified 2026-10-23 (OpenAPI) |
| bios | `serialNumber` | Verified 2026-10-23 (OpenAPI; the serial is in `bios`, not `systemInfo`) |
| bios | `smBiosVersion` | Verified 2026-10-23 (OpenAPI) |
| systemInfo | `manufacturer` | Verified 2026-10-23 (OpenAPI SystemInfo) |
| systemInfo | `model` | Verified 2026-10-23 (OpenAPI SystemInfo) |
| alerts | `alertUid` | Verified 2026-10-23 (help page, OpenAPI) |
| alerts | `priority` | Verified 2026-10-23 (OpenAPI); values UNVERIFIED |
| alerts | `diagnostics` | Verified 2026-10-23 (OpenAPI) |
| alerts | `resolved` | Verified 2026-10-23 (OpenAPI) |
| alerts | `resolvedBy` | Verified 2026-10-23 (OpenAPI) |
| alerts | `resolvedOn` | Verified 2026-10-23 (OpenAPI) |
| alerts | `muted` | Verified 2026-10-23 (OpenAPI) |
| alerts | `ticketNumber` | Verified 2026-10-23 (OpenAPI) |
| alerts | `timestamp` | Verified 2026-10-23 (OpenAPI); value format UNVERIFIED |
| alerts | `alertMonitorInfo` | Verified 2026-10-23 (OpenAPI) |
| alerts | `alertContext` | Verified 2026-10-23 (help page, OpenAPI) |
| alerts | `alertSourceInfo` | Verified 2026-10-23 (OpenAPI) |
| alerts | `autoresolveMins` | Verified 2026-10-23 (OpenAPI) |
| alertMonitorInfo | `sendsEmails` | Verified 2026-10-23 (OpenAPI) |
| alertMonitorInfo | `createsTicket` | Verified 2026-10-23 (OpenAPI) |
| alertContext | `@class` | Verified 2026-10-23 (help page); the value `online_offline_status_ctx` is UNVERIFIED |
| alertSourceInfo | `deviceUid` | Verified 2026-10-23 (OpenAPI) |
| alertSourceInfo | `deviceName` | Verified 2026-10-23 (OpenAPI) |
| alertSourceInfo | `siteUid` | Verified 2026-10-23 (OpenAPI) |
| alertSourceInfo | `siteName` | Verified 2026-10-23 (OpenAPI) |
| job | `id` | Verified 2026-10-23 (OpenAPI Job) |
| job | `uid` | Verified 2026-10-23 (help page, OpenAPI) |
| job | `name` | Verified 2026-10-23 (OpenAPI) |
| job | `dateCreated` | Verified 2026-10-23 (OpenAPI); value format UNVERIFIED |
| job | `status` | Verified 2026-10-23 (help page: `active` or `completed`) |
| components | `id` | Verified 2026-10-23 (OpenAPI Component) |
| components | `uid` | Verified 2026-10-23 (OpenAPI) |
| components | `name` | Verified 2026-10-23 (OpenAPI) |
| components | `description` | Verified 2026-10-23 (OpenAPI) |
| components | `categoryCode` | Verified 2026-10-23 (OpenAPI); the value `scripts` is UNVERIFIED |
| components | `credentialsRequired` | Verified 2026-10-23 (OpenAPI) |
| components | `variables` | Verified 2026-10-23 (OpenAPI) |
| variables | `name` | Verified 2026-10-23 (OpenAPI ComponentVariable) |
| variables | `defaultVal` | Verified 2026-10-23 (OpenAPI) |
| variables | `type` | Verified 2026-10-23 (OpenAPI); values UNVERIFIED |
| variables | `direction` | Verified 2026-10-23 (OpenAPI); the boolean value is UNVERIFIED |
| variables | `description` | Verified 2026-10-23 (OpenAPI) |
| variables | `variablesIdx` | Verified 2026-10-23 (OpenAPI) |

Not imitated: authentication (API key and secret to a bearer token), the platform host name, rate limits, paging beyond one page, the `/v2/account/devices` account-wide list, and every write endpoint (`PUT /v2/device/{deviceUid}/quickjob` and others). The mock has no write method at all.

## Seeded problems (STD-FX-4)

Contoso Dental is seeded; Fabrikam Capital is the clean twin (every device in RMM and PSA, every workstation also in Intune, nothing stale, nothing duplicated).

- `RECEPTION-OLD` (`...d0005`): last seen 2026-08-01, so stale, and in no other system.
- `HYGIENE-03` twice (`...d0007` last seen 2026-07-15 and `...d0008`): the same serial, so one device held twice by the RMM (duplicate), the old record also stale.
- `XRAY-WS01` (`...d0004`): its BIOS serial is the placeholder `To be filled by O.E.M.`, so it is matched by name to the PSA item `xray-ws01.contosodental.example`.
- `CHAIRSIDE-04` (`...d0009`): the PSA item with the same name carries a different serial, so the two are not merged; each is only in one system.
- `DENTAL-SRV01` (`...d0003`): a server in RMM and PSA and not in Intune. This is not a mismatch type (servers are not enrolled in Intune); the device lists which systems know it.
