# Graph fixture sources

These fixtures are **synthetic**: they are mock data shaped like Microsoft Graph v1.0 responses. The tenants (Contoso Dental, Fabrikam Capital), people, IDs and domains are invented. IDs follow the pattern `c0000000-...` (Contoso) and `f0000000-...` (Fabrikam), and domains use the reserved `.example` TLD or `*.onmicrosoft.com`. No file was captured from a real tenant. Results computed from them are fixture-based.

- `contoso/` is seeded with known problems. `clean/` (Fabrikam Capital) has none.
- Each file is the body of one `GET` request: a collection response `{"@odata.context": ..., "value": [...]}`.
- The mock adapter is `levers/powershell/TenantBaseline` (`Get-TbFixtureSnapshot`).

**Verification status.**
- **Verified:** field names and enum values were checked against the Microsoft Learn pages linked below on 2026-10-20, by reading the docs.
- **Unverified:** anything marked UNVERIFIED was not checked against a docs page or a live tenant.
- **No live data:** no call was made to a real Graph endpoint.

## Files

| File | Request it stands in for | Docs (v1.0) | Permission (application, least privileged, per the docs page) |
| --- | --- | --- | --- |
| `users.json` | `GET /users?$select=id,displayName,userPrincipalName,userType,accountEnabled,createdDateTime,onPremisesSyncEnabled,signInActivity` | [List users](https://learn.microsoft.com/en-us/graph/api/user-list?view=graph-rest-1.0), [user](https://learn.microsoft.com/en-us/graph/api/resources/user?view=graph-rest-1.0), [signInActivity](https://learn.microsoft.com/en-us/graph/api/resources/signinactivity?view=graph-rest-1.0) | `User.Read.All`. `signInActivity` also needs `AuditLog.Read.All` and a Microsoft Entra ID P1 or P2 license. |
| `userRegistrationDetails.json` | `GET /reports/authenticationMethods/userRegistrationDetails` | [List userRegistrationDetails](https://learn.microsoft.com/en-us/graph/api/authenticationmethodsroot-list-userregistrationdetails?view=graph-rest-1.0), [userRegistrationDetails](https://learn.microsoft.com/en-us/graph/api/resources/userregistrationdetails?view=graph-rest-1.0) | `AuditLog.Read.All` |
| `directoryRoles.json` | `GET /directoryRoles?$expand=members` | [List directoryRoles](https://learn.microsoft.com/en-us/graph/api/directoryrole-list?view=graph-rest-1.0), [List members](https://learn.microsoft.com/en-us/graph/api/directoryrole-list-members?view=graph-rest-1.0) | `RoleManagement.Read.Directory` |
| `conditionalAccessPolicies.json` | `GET /identity/conditionalAccess/policies` | [List policies](https://learn.microsoft.com/en-us/graph/api/conditionalaccessroot-list-policies?view=graph-rest-1.0), [conditionalAccessPolicy](https://learn.microsoft.com/en-us/graph/api/resources/conditionalaccesspolicy?view=graph-rest-1.0), [conditionalAccessConditionSet](https://learn.microsoft.com/en-us/graph/api/resources/conditionalaccessconditionset?view=graph-rest-1.0) | `Policy.Read.All` (UNVERIFIED: not re-read on 2026-10-20) |
| `secureScores.json` | `GET /security/secureScores?$top=1` | [List secureScores](https://learn.microsoft.com/en-us/graph/api/security-list-securescores?view=graph-rest-1.0) | `SecurityEvents.Read.All`. This scope is **not** in the five scopes the spec lists (see below). |

## What was checked, field by field

- **`users.json`**
  - **Verified:** `signInActivity` has `lastSignInDateTime`, `lastNonInteractiveSignInDateTime` and `lastSuccessfulSignInDateTime`. All three are DateTimeOffset in UTC.
  - **What the fields mean:**
    - `lastSignInDateTime` records interactive *attempts*, including failed ones.
    - `lastSuccessfulSignInDateTime` exists from December 2023 and is not backfilled.
    - The stale check uses `lastSuccessfulSignInDateTime` for this reason.
  - **Simplification:** the `...RequestId` fields are omitted to keep the fixture short.
  - **UNVERIFIED:** whether a user who never signed in returns `"signInActivity": null` or omits the property. The module handles both.
  - **Standard properties:** `userType` (`Member` or `Guest`), `accountEnabled`, `createdDateTime` and `onPremisesSyncEnabled` (`true` when synced, `null` when never synced) are standard user properties. Their exact null-vs-false behaviour is UNVERIFIED.
- **`userRegistrationDetails.json`**
  - **Verified:** the property names, including `isMfaRegistered`, `methodsRegistered` and `isAdmin`.
  - **Verified:** `userType` is lowercase here (`member`, `guest`).
  - **Verified:** the docs say this method "doesn't work for disabled users", so the disabled accounts have no record in the fixture.
  - **Synthetic edge case:** one new hire (`nina.shah`) has no record at all. The module treats a missing record as "not registered".
  - **Simplification:** some properties (`isSsprEnabled`, `isSsprCapable`, `isSystemPreferredAuthenticationMethodEnabled` and others) are omitted.
- **`directoryRoles.json`**
  - **Verified:**
    - `roleTemplateId` `62e90394-69f5-4237-9190-012177145e10` is Global Administrator; it appears in the docs example.
    - `$expand` is a supported query parameter on List directoryRoles.
    - The docs now recommend the unified RBAC API (`roleManagement/directory`). This adapter uses the older `directoryRoles` API as the spec asks.
  - **UNVERIFIED:**
    - the exact shape of the `members` array that `$expand=members` returns inline. The documented fallback is one `GET /directoryRoles/{id}/members` per role.
    - the role template IDs for User Administrator (`fe930be7-5e62-47db-91af-98c3a49a38b1`) and Global Reader (`f2ef992c-3afb-46b9-b7cf-a126ee74c451`) were taken from the Entra built-in roles reference and not re-read on 2026-10-20.
- **`conditionalAccessPolicies.json`**
  - **Verified:**
    - `state` is one of `enabled`, `disabled`, `enabledForReportingButNotEnforced`.
    - `conditions.clientAppTypes` values include `all`, `browser`, `mobileAppsAndDesktopClients`, `exchangeActiveSync` and `other`. Legacy authentication is `exchangeActiveSync` plus `other`.
  - **UNVERIFIED:** the full value lists of `grantControls.builtInControls` (`block`, `mfa`, `compliantDevice`) and of the `conditions.users` property names (`includeUsers`, `excludeUsers`, `includeGroups`, `excludeGroups`, `includeRoles`, `excludeRoles`). Both are well known, but their resource pages were not re-read.
- **`secureScores.json`**
  - **Verified:** the field names follow the docs example (`id` = `{tenantId}_{date}`, `azureTenantId`, `currentScore`, `maxScore`, `enabledServices`, `averageComparativeScores`, `controlScores`, `vendorInformation`).
  - **Synthetic:** the `controlScores` entries.

## Scopes: what the spec lists, and what the docs say

- **The five scopes:** `-UseGraph` lists the five read-only scopes from `specs/slices-abc.md`: `User.Read.All`, `AuditLog.Read.All`, `Policy.Read.All`, `RoleManagement.Read.Directory`, `Reports.Read.All`.
- **Two gaps found in the docs pages above:**
  - **`SecurityEvents.Read.All`:** Secure Score needs it, and it is not in that list. The module calls it optional because the score is context only and no check depends on it.
  - **`Reports.Read.All`:** none of the endpoints above require it. `userRegistrationDetails` needs `AuditLog.Read.All`. It may be removable (least privilege). Confirm this against a test tenant before changing the list.

## Break-glass pattern (the "documented pattern")

The pattern lives in `levers/powershell/TenantBaseline/TenantBaseline.config.json`. It is based on Microsoft's [emergency access accounts guidance](https://learn.microsoft.com/en-us/entra/identity/role-based-access-control/security-emergency-access), read on 2026-10-20. That guidance says:
- two or more accounts;
- cloud-only;
- Global Administrator;
- excluded from Conditional Access policies (report-only policies need no exclusion);
- validated at least every 90 days.

The UPN prefix `bg-` is this repo's own naming convention, not Microsoft's.

**Simplification:** CA exclusion is checked by user id in `excludeUsers` on every enabled policy. Microsoft suggests excluding a dedicated group. Resolving group membership would need another read scope (`GroupMember.Read.All`), which is out of scope here.

## Tenant state shapes (B-19)

These are the shapes the Graph mock adapter (`adapters/graph/`) serves from `fixtures/tenant/<client>.json` (the file the lever runner loads and saves) and from the optional per-family files `fixtures/tenant/<client>/<family>.json`. They are synthetic. Docs pages were read on 2026-10-21; nothing was called against a live tenant.

Pages: [user resource](https://learn.microsoft.com/en-us/graph/api/resources/user?view=graph-rest-1.0), [List methods (`GET /users/{id | userPrincipalName}/authentication/methods`)](https://learn.microsoft.com/en-us/graph/api/authentication-list-methods?view=graph-rest-1.0), [phoneAuthenticationMethod](https://learn.microsoft.com/en-us/graph/api/resources/phoneauthenticationmethod?view=graph-rest-1.0).

| Shape and field | Microsoft Learn page | Status |
| --- | --- | --- |
| `users[]` is a plain array, not an `@odata.context` / `value` envelope | user resource | Synthetic simplification (a real list response has the envelope) |
| `users[]` `id` | user resource | Verified 2026-10-21 (name) |
| `users[]` `displayName` | user resource | Verified 2026-10-21 (name) |
| `users[]` `userPrincipalName` | user resource | Verified 2026-10-21 (name) |
| `users[]` `jobTitle` | user resource | Verified 2026-10-21 (name) |
| `users[]` `accountEnabled` | user resource | Verified 2026-10-21 (name, Boolean) |
| `users[]` `authentication` (an object holding `methods`) | List methods | Synthetic: Graph has no inline `authentication` property on user; methods are a separate request, nested here for one-file simplicity |
| `users[].authentication.methods[]` `@odata.type` | List methods | Verified 2026-10-21 that values look like `#microsoft.graph.<type>AuthenticationMethod`; the exact type names used in the fixtures were not re-read: UNVERIFIED |
| `users[].authentication.methods[]` `id` | phoneAuthenticationMethod | name Verified 2026-10-21; the docs say a phone method id is one of three fixed GUIDs by `phoneType`, the fixtures use arbitrary ids (Synthetic) |
| `users[].authentication.methods[]` `phoneNumber` | phoneAuthenticationMethod | Verified 2026-10-21 (format `+{country code} {number}`; fixtures use the 555-01xx range) |
| `users[].authentication.methods[]` `phoneType` | phoneAuthenticationMethod | Verified 2026-10-21 (`mobile`, `alternateMobile`, `office`) |
| `users[].authentication.methods[]` `displayName` | List methods | Verified 2026-10-21 on the fido2 and Windows Hello entries in the page example; on the Authenticator method UNVERIFIED |
| Family file: `_meta.client`, `_meta.note`, then family-defined keys | none (this repo's own envelope) | Synthetic. `_meta.client` must equal the folder's client or the adapter refuses the file (STD-FX-3) |

**Permission the real call needs:** application `UserAuthenticationMethod.Read.All` for another user's methods (List methods page, 2026-10-21). That scope is not in the five listed above. The page also says the Authentication Administrator sees masked phone numbers, which the fixtures do not imitate.

**Not imitated:** paging (`@odata.nextLink`), `$select`, throttling and `smsSignInState`.
