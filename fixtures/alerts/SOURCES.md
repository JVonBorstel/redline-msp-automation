# Alert fixture sources

These fixtures are **synthetic**: invented clients (Contoso Dental, Fabrikam Capital), invented people marked "(synthetic)" in text, `.example` domains, invented host and job names, an invented SOC case id. Nothing was captured from a real alert feed. Pinned to `as_of` 2026-10-20T06:30:00Z. Results computed from them are fixture-based.

- One file per client, `fixtures/alerts/<client>.json`; its `client` matches the file name and `account_id` equals the client's `alerts` binding `external_id`.
- The mock is `adapters/alerts/mock.py` (`AlertsMock`). It only reads these files.
- The eval answer key is `evals/alerts/gold.json`, kept out of these files so the code under test cannot see it (STD-FX-5).

## Shape: source TYPES, not products

Alert sources are modelled as six types (B43-4, B43-5, D6-04). No fixture names a product.

| `source_type` | Stands in for | Stack row |
| --- | --- | --- |
| `edr-mdr` | an EDR / MDR service | MP-17 (vendor INFERRED) |
| `m365-itdr` | Microsoft 365 identity threat detection and response | MP-18 |
| `siem` | a SIEM | MP-19 |
| `rmm-monitor` | RMM monitors (agent offline and similar) | MP-12 |
| `backup` | backup job alerts | MP-15, MP-16 |
| `saas-monitoring` | SaaS monitoring (vendor possibly SaaS Alerts, UNVERIFIED) | MP-20 |

## Fields

Every field is this repo's own neutral name. **No vendor documentation was read for this item, so no field is claimed to match any vendor's API: every vendor mapping is UNVERIFIED.** A real adapter must map its vendor's fields onto these and record each mapping as Verified (with date) or UNVERIFIED when it is built.

| Field | Meaning | Status |
| --- | --- | --- |
| `id` | alert id, `A-nnnn` | neutral, invented |
| `client` | client id slug | neutral |
| `source_type` | one of the six types above | neutral |
| `severity` | `critical`, `high`, `medium`, `low`, `info` | neutral; vendor severity scales UNVERIFIED |
| `category` | short kebab-case kind such as `risky-sign-in`, `agent-offline`, `sensor-health` | neutral; vendor categories UNVERIFIED |
| `title`, `description` | free text, untrusted | neutral |
| `created_at` | UTC time | neutral |
| `entity_kind`, `entity_id` | the thing the alert is about: `user`, `device`, `mailbox`, `job`, `tenant` | neutral |
| `soc_case_id` | present when an external SOC already owns the alert (D6-04) | neutral; the SOC's real case id format UNVERIFIED |

## Seeded cases (STD-FX-4)

- Contoso `A-1001`, `A-1002`, `A-1003`, `A-1011`: one user, three source types, inside one window. The SaaS-monitoring alert joins the same group (B43-5).
- `A-1004`, `A-1005`: one device owned by the external SOC (`SOC-20481`).
- `A-1006`, `A-1007`: RMM agent offline plus EDR sensor stopped on one server (health group type).
- `A-1008` (agent offline) and `A-1014` (security) on the same device stay apart: a health alert never merges into an incident group.
- `A-1013`: same user as `A-1001`, nearly three hours later, so a new group, not the old one.
- `A-1015`, `A-1016` (Contoso) and `A-2001`, `A-2002` (Fabrikam): the same host name `SRV-FILE-01` at overlapping times in two different clients; they must never be grouped together.
- `A-1014` carries instruction-like text in its description (an injection test). It is still grouped (grouping reads no text) but its text is withheld from the summary.
- `A-1017`, `A-1018`: related by a person but sharing no entity id; the entity rule misses them on purpose (honest recall below 100%).
- Clean twin: Fabrikam has no SOC case and no injection text.

## Not claimed

No call was made to any alert source. Authentication, paging, vendor-side deduplication and real severity mappings are not imitated.
