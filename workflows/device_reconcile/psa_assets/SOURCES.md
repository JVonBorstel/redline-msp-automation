# PSA asset fixture sources

Status: **mocked**. These fixtures are **synthetic**: invented clients (Contoso Dental, Fabrikam Capital), invented asset names, serials and ids. Nothing was captured from a real PSA. They are pinned to `asOf` 2026-10-22T12:00:00Z. Results computed from them are fixture-based.

- One file per client, `workflows/device_reconcile/psa_assets/<client>.json`; its `client` matches the file name and `companyID` equals the client's PSA company id (the `psa` binding's `external_id`; 30001 and 30002, as in `fixtures/psa/`).
- They live beside the workflow, not in `fixtures/psa/`, because `fixtures/psa/` and `adapters/psa/` belong to B-18 and are not B-61's to change. The reader is `workflows/device_reconcile/psa_assets.py` (`PsaAssetsMock`).
- Each file also holds one configuration item of the **other** client's company, carrying this client's first name and serial. A test shows it is never returned, matched or counted (B61-2, C-27).
- `configurationItems` stands in for the body of one `POST /atservicesrest/v1.0/ConfigurationItems/query` filtered by `companyID` (the query form and its response shape are UNVERIFIED).

Source, read 2026-10-23: [Autotask REST API, ConfigurationItems entity](https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/ConfigurationItemsEntity.htm). It was read through a summarising tool that returned field names and types. "Verified" means the field name was in that reading. Values are invented; `configurationItemType` 1 is a placeholder.

## Field status

Every field in the fixtures is in this table; a test (`test_b61_4_every_intune_and_psa_fixture_field_is_marked`) checks it.

| Entity | Field | Status |
| --- | --- | --- |
| file | `_note` | UNVERIFIED (this repo's own key, STD-FX-3) |
| file | `client` | UNVERIFIED (this repo's own key) |
| file | `asOf` | UNVERIFIED (this repo's own key; pins the fixture) |
| file | `companyID` | UNVERIFIED (this repo's own key; the company the query was for) |
| file | `configurationItems` | UNVERIFIED (this repo's own key; holds the query response) |
| configurationItems | `items` | UNVERIFIED (query response shape, not re-read for this item) |
| configurationItems | `pageDetails` | UNVERIFIED (query response shape, not re-read for this item) |
| pageDetails | `count` | UNVERIFIED |
| pageDetails | `requestCount` | UNVERIFIED |
| pageDetails | `prevPageUrl` | UNVERIFIED |
| pageDetails | `nextPageUrl` | UNVERIFIED |
| items | `id` | Verified 2026-10-23 |
| items | `companyID` | Verified 2026-10-23 |
| items | `configurationItemType` | Verified 2026-10-23 (a legacy field per the page; value is a placeholder) |
| items | `referenceTitle` | Verified 2026-10-23 (the "Reference Name"; matching by name uses it) |
| items | `serialNumber` | Verified 2026-10-23 |
| items | `isActive` | Verified 2026-10-23 |
| items | `installDate` | Verified 2026-10-23 |
| items | `createDate` | Verified 2026-10-23 |
| items | `lastModifiedTime` | Verified 2026-10-23 (not a last-seen time, so PSA items are never called stale) |

Not imitated: authentication, zones, user-defined fields, the Datto RMM link fields (`rmmDeviceUID`, `rmmDeviceID`, both read-only per the page), and every write.

## Seeded problems (STD-FX-4)

Contoso Dental is seeded; Fabrikam Capital is the clean twin.

- `SPARE-LT02` (70007): in the PSA only.
- `xray-ws01.contosodental.example` (70004): no serial, so matched by name to the RMM device `XRAY-WS01`.
- `CHAIRSIDE-04` (70008): serial `CD-0099-XX` differs from the RMM device of the same name, so they are not merged.
- `DENTAL-SRV01` (70003): serial written in lower case (`cd-0003-sv`); it still matches the RMM serial.
