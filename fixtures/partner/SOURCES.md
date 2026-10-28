# Partner and app-registration fixture sources

These fixtures are **synthetic**: invented clients (Contoso Dental, Fabrikam Capital), invented tenants (`c0000000-...`, `f0000000-...` id prefixes), invented people, `.example` domains. Nothing was captured from a real Partner Center or Entra tenant. Pinned to `as_of` 2026-10-21. Results computed from them are fixture-based.

- One file per client, `fixtures/partner/<client>.json`; its `client` matches the file name.
- Read by `workflows/expiry` (B-54), which only reports. Nothing is renewed, rotated or changed.
- No network call was made to Partner Center or Microsoft Graph while writing these files, and the field names below were written **from memory, not checked against the vendor documentation in this session**. Per STD-FX-2 every field is therefore UNVERIFIED. What would verify each: read the vendor page named in the table and compare names, types and enum values.
- No secret value is ever in a fixture: a credential carries only a key id, a label and an end date (metadata).
- Seeded problems (contoso-dental): GDAP `...a1` holds Global Administrator and ends within 60 days; `...a2` ends within 30 days; `...a3` is already expired; app `...b1` has a secret ending within 30 days and a certificate already expired; app `...b3` has a secret ending within 30 days and no owner. fabrikam-capital is the clean twin and triggers nothing.

## GDAP relationship (`gdapRelationships`), imitating Partner Center delegated admin relationships

Vendor page to verify against: Microsoft Learn, Partner Center "GDAP introduction" and the Partner Center API "delegatedAdminRelationship" resource (not opened in this session).

| Fixture field | Meant to imitate | Status |
| --- | --- | --- |
| `id` | relationship id (GUID) | UNVERIFIED |
| `displayName` | relationship name | UNVERIFIED |
| `status` | relationship state (`active`, `expired`, ...) | UNVERIFIED (enum values invented here) |
| `endDateTime` | end of the relationship | UNVERIFIED (real API may name it differently) |
| `roles` | flat list of Entra role template ids | UNVERIFIED (the real shape nests roles under access details) |
| `owner` | who in the MSP owns the relationship | invented, not a vendor field |
| `client`, `as_of`, `_note` | fixture envelope | invented, not a vendor field |

The Global Administrator role template id `62e90394-69f5-4237-9190-012177145e10` is used from memory: UNVERIFIED (verify against the Microsoft Entra built-in roles list).

## App registration (`appRegistrations`), imitating Microsoft Graph application

Vendor page to verify against: Microsoft Graph v1.0 `application` resource (not opened in this session).

| Fixture field | Meant to imitate | Status |
| --- | --- | --- |
| `appId` | application (client) id | UNVERIFIED |
| `displayName` | application name | UNVERIFIED |
| `passwordCredentials` | client secrets, metadata only | UNVERIFIED |
| `keyCredentials` | certificates, metadata only | UNVERIFIED |
| `keyId` | credential id | UNVERIFIED |
| `endDateTime` | credential expiry | UNVERIFIED |
| `owner` | who in the MSP owns the app | invented, not a vendor field |
