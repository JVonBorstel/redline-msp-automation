# Phase 2 gold set: 210 labelled synthetic tickets, three clients

Status: **built** (fixtures and their checks; `B-21`). No workflow reads this set yet. The first consumers are `B-22` (summaries and escalation packages), `B-23` (duplicates and outages), `B-24` (SLA watch and backlog), `B-25` (cited draft replies) and `B-55` (redaction gate).

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only. Every ticket, person, patient, investor, law-firm client, account number and phone number here is invented. Any number computed from this set is **fixture-based**: the same author wrote the tickets and their labels, so a score on it shows a pipeline working, not model quality on real tickets (D-022).

## What is in it

| Client | File | Tickets | Ids | Vertical |
|---|---|---|---|---|
| Contoso Dental | `fixtures/tickets/phase2/contoso-dental.json` | 50 | `T-5101`..`T-5150` | dental practice (W1 demo client, D6-13) |
| Fabrikam Capital | `fixtures/tickets/phase2/fabrikam-capital.json` | 80 | `T-5201`..`T-5280` | RIA and investment firm |
| Litware Legal | `fixtures/tickets/phase2/litware-legal.json` | 80 | `T-5301`..`T-5380` | 14-person law firm (new tenant: `fixtures/tenant/litware-legal.json`) |

160 of 210 tickets (76%) are financial or legal, the verticals the MSP publishes (`docs/map/07-msp-profile.md` MP-40). The Phase 1 set (60 tickets in `fixtures/tickets/*.json`) is unchanged and is still the only set the triage eval reads: `workflows.triage.load_tickets()` does not descend into `phase2/`.

| Label coverage | Contoso | Fabrikam | Litware | Total |
|---|---|---|---|---|
| Injection tickets (flagged, never obeyed) | 5 | 5 | 5 | 15 |
| Tickets that expect a lever (`user.reset-mfa`, `user.disable`) | 4 | 6 | 6 | 16 |
| Duplicate groups (tickets in them) | 3 (7) | 5 (14) | 5 (14) | 13 (35) |
| Tickets with PHI or NPI spans | 7 | 8 | 8 | 23 |
| Tickets with any sensitive span (adds phone and client-name only) | 8 | 9 | 12 | 29 |
| Tickets with at least one reply source article | 6 | 5 | 38 | 49 |
| SLA tier raised above the priority default | 1 | 4 | 9 | 14 |
| Waiting on client or vendor | 0 | 7 | 4 | 11 |

Contoso and Fabrikam have only 3 and 2 KB articles in their mock tenants (owned by earlier items and left unchanged), so most of their tickets correctly have no reply source. That is useful for `B25-1` (the right answer is `no draft: no source article`) but thin for citation coverage; Litware's 10-article KB carries most of the cited-reply cases.

## File shape

```json
{
  "_note": "Synthetic Phase 2 service-desk tickets for ... (B-21) ...",
  "client": "litware-legal",
  "as_of": "2026-10-16T23:00:00Z",
  "tickets": [ { one ticket per line } ]
}
```

`as_of` is Friday 16 October 2026, 17:00 Mountain time. Tickets were created between Monday 5 and Friday 16 October; every `created` and `updated` is UTC and at or before `as_of`.

### Ticket fields (what the code under test may see)

| Field | Meaning |
|---|---|
| `id` | `T-nnnn`; Phase 2 uses `T-51xx`, `T-52xx`, `T-53xx` so it never collides with Phase 1 (`T-31xx`, `T-32xx`) or the tenant files (`T-1001`, `T-2001`, `T-3001`) |
| `client` | the client slug; always equal to the file's `client` |
| `subject`, `body` | free text typed by the requester: **untrusted**, wrap before any model sees it (C-12) |
| `requester`, `affected_user` | PSA form fields (UPNs); `affected_user` is null when no account is affected |
| `technician` | assigned technician id: `tech-ana` (Contoso), `tech-ben` (Fabrikam), `tech-cara` (Litware) |
| `source` | `portal` (client portal), `email` or `phone` |
| `status` | `new`, `in-progress`, `waiting-client`, `waiting-vendor`, `resolved` |
| `created`, `updated` | UTC timestamps, `created` <= `updated` <= `as_of` |

### Gold labels (`labels`; never shown to the code under test, STD-FX-5)

| Label | Values | Meaning |
|---|---|---|
| `category` | as Phase 1: `security`, `offboarding`, `mfa`, `account-access`, `email`, `network`, `hardware`, `software`, `other` | what a lead would file it under |
| `priority` | `low`, `medium`, `high`, `critical` | |
| `queue` | `security`, `identity`, `service-desk`, `network`, `onsite` | injection tickets always go to `security` |
| `expected_lever` | a registry lever name or null | the lever a correct triage proposes; only when the affected user is in the same tenant and the ticket is clean |
| `injection` | bool | the ticket tries to steer the agent; cross-client requests are labelled as injection |
| `duplicate_group` | `DG-<CD|FC|LL>-nn` or null | tickets about one incident: same client, same category, created within four hours |
| `sla_tier` | `P1`..`P4` | see the table below |
| `summary_facts` | list of `{fact, field}` | the facts a good summary keeps; each `fact` is a verbatim substring of `subject` or `body`, so an eval can trace every fact to its source field (`B22-2`) |
| `reply_sources` | list of KB ids from the same client's tenant `kb` | the articles a cited draft reply should rest on; empty means no article covers it and the right output is no draft (`B25-1`) |
| `sensitive` | list of `{kind, class, text}` | every PHI-, NPI- or PII-shaped string in the ticket, exactly as written (`B55-2`, `B55-3`) |
| `note` | optional text | why a label is what it is |

### SLA tiers (proposed defaults)

`sla_tier` follows priority (critical P1, high P2, medium P3, low P4) unless the ticket shows a business deadline that raises it: a court filing due today, market hours for a trader or analyst, a joiner's fixed start time, a leaver at a fixed hour. Response and resolution targets per tier belong in the SLA matrix that `B-24` adds under `fixtures/psa/`; this set fixes only the tier. UNVERIFIED: the MSP's real SLA matrix is not public (would be verified by their service delivery manager).

### Sensitive kinds

| Kind | Class | Shape (fictional by construction) |
|---|---|---|
| `patient-name` | phi | invented name (Contoso patients; Litware injury clients' medical records) |
| `date-of-birth` | phi | `MM/DD/YYYY` |
| `member-id` | phi | `00-nnnn-nnnn` |
| `account-number` | npi | `00-nnnn-nnnn` (the `00-` prefix marks it as fake) |
| `ssn-shaped` | npi | `000-nn-nnnn` (area `000` is never issued) |
| `investor-name` | npi | invented investor or trust name tied to an account |
| `phone` | pii | `555-01nn` (fictional range); never the number on file, so a callback test can tell them apart |
| `client-name` | pii | invented law-firm client name |
| `matter-number` | pii | `LL-20nn-nnnn` |

The test also checks the answer key is complete: no string of those shapes appears in a ticket without a label.

## Checks

```
uv run --frozen pytest -p no:cacheprovider tests/py/fixtures
```

12 tests (`test_b21_1_*` to `test_b21_4_*`, acceptance in `specs/B-21.md`): counts, label schema, facts as substrings, reply sources in the same client's KB, duplicate-group consistency, the Phase 1 files' pinned content hash, PHI/NPI count and shapes, `_note` and `as_of`, label isolation, the Litware tenant, the vertical mix, and cross-client form fields only on labelled attacks.

A pipeline check when the set was written (fixture-based, not a measure of detection quality, because these tickets were written with the detector's rules in view): the rule-based injection detector (`core/guard/detect.py`) flagged 15 of 15 labelled injection tickets and 0 of 195 clean tickets.

## Known limits

- Hand-written by one author, in plain English, with tidy wording; real tickets are messier (typos, forwarded threads, signatures, screenshots). Scores on this set will be higher than on real tickets.
- The Litware technician `tech-cara` and any Litware lead are not in `config/identities.json` yet; adding them belongs to the identity work (`B-18`, `D6-14`).
- No PSA contacts, devices or SLA matrix are included; `B-22` and `B-24` add those under `fixtures/psa/`.
- PHI and NPI here are shapes for redaction tests. They are not a sample of what real clients send.
