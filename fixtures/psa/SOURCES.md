# PSA fixture sources

These fixtures are **synthetic**: invented clients (Contoso Dental, Fabrikam Capital), invented people, `.example` domains, phone numbers in the 555-01xx range. Nothing was captured from a real PSA. They imitate the public Autotask PSA REST API entity shapes, so a real binding can replace the mock later (D6-01). Pinned to `as_of` 2026-10-20. Results computed from them are fixture-based.

- One file per client, `fixtures/psa/<client>.json`; its `client` matches the file name and `company.id` equals the client's PSA company id (the binding's `external_id`).
- The mock adapter is `adapters/psa/mock.py` (`PsaMock`). It only reads these files.
- Seeded problems: none. The two files exist so a test can show client A's binding cannot see client B's data (STD-TS-6).

## Entities

Docs read on 2026-10-21 (Autotask REST API, entity pages under `https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/`): [Companies](https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/CompaniesEntity.htm), [Contacts](https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/ContactsEntity.htm), [Tickets](https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/TicketsEntity.htm), [TicketNotes](https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/TicketNotesEntity.htm), [Resources](https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/ResourcesEntity.htm).

| Fixture key | Autotask entity | Status |
| --- | --- | --- |
| `company` | Companies | Field names Verified (2026-10-21). Enum values (`companyType`) UNVERIFIED. |
| `contacts` | Contacts | Field names Verified (2026-10-21). `isActive` is an integer in the docs, matched here. |
| `tickets` | Tickets | Field names Verified (2026-10-21). Numeric enum values (`status`, `priority`, `queueID`, `ticketCategory`, `ticketType`) are invented placeholders, UNVERIFIED: real values are picklists per Autotask tenant. |
| `ticketNotes` | TicketNotes | Field names Verified (2026-10-21). Enum values (`noteType`, `publish`) UNVERIFIED. |
| `resources` | Resources | Field names Verified (2026-10-21). |
| `slaSettings` | ServiceLevelAgreements | UNVERIFIED. The entity page was not found on 2026-10-21 (HTTP 404). Names and hour fields are a neutral stand-in for "SLA settings" and are not claimed to match Autotask. |

Per-field status is the table in `specs/B-18.md` (checked by a test: every fixture field appears there).

## Not claimed

- No call was made to a real Autotask endpoint. Authentication, paging, `Query` filters and `UserDefinedFields` are not imitated.
- The ticket numbers (`T-3101`) follow this repo's ticket fixtures, not Autotask's real `T20261020.0001` style.
