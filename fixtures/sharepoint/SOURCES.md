# SharePoint and OneDrive sharing fixture sources

These fixtures are **synthetic**: invented clients, people and tenants, `.example` domains, ids with the `c0000000-` (contoso-dental) and `f0000000-` (fabrikam-capital) prefixes. Nothing was captured from a real tenant or read from Microsoft Graph, SharePoint admin or Purview. Pinned to `as_of` 2026-10-22. Results are fixture-based. Tests make no network call.

- `fixtures/sharepoint/<client>.json`: the client's tenant label and DLP coverage and its sites (SharePoint sites and OneDrive drives) with their sharing links and shares. The `client` field matches the file name.
- Envelope fields: `client`, `as_of`, `_note`. Section names: `tenant`, `sites`.
- Seeded problems (contoso-dental): `Patient Records` holds health content with no label (unlabelled-sensitive-site) and has an `everyone-except-external` link (everyone-link); `Front Desk OneDrive` is shared with an outside guest (external-share). `Billing` is labelled and has only an organization link (not flagged). No label and no DLP policy covers health content (a label-gap and a dlp-gap recommendation). fabrikam-capital is the clean twin and triggers nothing.

## Field shapes

Every vendor-shaped name below was written from memory, with no Microsoft page opened in this session. They are UNVERIFIED against Microsoft Graph, SharePoint and Purview documentation, and the fixture is flatter than the real shapes.

| Fixture field | Meaning | Status |
| --- | --- | --- |
| `tenant` | the tenant's label and DLP coverage | invented, not a vendor shape |
| `labels` | published sensitivity labels | UNVERIFIED against Purview; shape invented |
| `dlpPolicies` | DLP policies | UNVERIFIED against Purview; shape invented |
| `name` | label, policy or site display name | UNVERIFIED |
| `covers` | which content categories (`health`, `finance`, `legal`, `general`) a label or policy applies to | invented |
| `sites` | SharePoint sites and OneDrive drives | invented envelope |
| `id` | site id, or link/share id within a site | UNVERIFIED; real ids are Graph ids, these are synthetic |
| `kind` | `site` or `onedrive` | invented |
| `sensitivity` | the site's content category as judged by the MSP | invented |
| `label` | the sensitivity label applied to the site, or null | UNVERIFIED against Purview |
| `owner` | who in the MSP owns the item | invented |
| `links` | sharing links on the site | UNVERIFIED against Graph permission links |
| `scope` | `anyone`, `everyone-except-external`, `organization`, `specific` | UNVERIFIED against Graph link scopes |
| `target` | file or folder the link or share points at | invented |
| `shares` | direct shares to named people | UNVERIFIED against Graph permissions |
| `recipient` | who the share goes to | invented, `.example` addresses |
| `recipientType` | `guest` or `internal` | invented |
