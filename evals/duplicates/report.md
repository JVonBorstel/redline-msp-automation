# Duplicate and outage grouping: fixture-based eval (B-23)

> Fixture-based and synthetic. The 210 tickets, their gold duplicate groups and the topic words in `workflows/duplicates/config.json` were all written by one author, with the tickets in view. This shows the pipeline working and where it errs, not duplicate-detection quality on real tickets (D-022). Regenerate with `uv run --frozen python -m evals.duplicates.report`.

Settings (from the workflow config): window 4 hours, outage at 3 or more tickets of one category from at least 2 people. History mode: resolved tickets are included. Tickets the injection detector flags (15) are left out of grouping and counted as neither true nor predicted.

## Duplicate pairs

| Client | Tickets | Gold groups | True pairs | Predicted pairs | Correct pairs | Pair precision | Pair recall |
|---|---|---|---|---|---|---|---|
| contoso-dental | 50 | 3 | 5 | 5 | 5 | 100.0% | 100.0% |
| fabrikam-capital | 80 | 5 | 14 | 14 | 14 | 100.0% | 100.0% |
| litware-legal | 80 | 5 | 14 | 14 | 14 | 100.0% | 100.0% |
| **all** | 210 | 13 | 33 | 33 | 33 | 100.0% | 100.0% |

**Missed pairs:** none

**False pairs:** none

## Outage groups

| Client | Gold outages | Found | Outage groups raised | False alarms | Outage recall | Outage precision |
|---|---|---|---|---|---|---|
| contoso-dental | 1 | 1 | 2 | 1 | 100.0% | 50.0% |
| fabrikam-capital | 3 | 3 | 3 | 0 | 100.0% | 100.0% |
| litware-legal | 3 | 3 | 3 | 0 | 100.0% | 100.0% |
| **all** | 7 | 7 | 8 | 1 | 100.0% | 87.5% |

**False alarms:** OUT-contoso-dental-hardware-T-5126 (T-5126, T-5127, T-5125)

## Isolation

Tickets of another client found inside any group: 0 (must be 0).

## Limits

- A ticket with no topic word is never grouped, so wording the config does not know is a missed pair.
- Gold groups are defined as same client, same category and within four hours; the workflow uses topic (duplicates) and category (outages) over the same window, so the two can disagree on borderline tickets.
- The lexicon covers incident-type topics only (printers, VPN, portals and so on). Account, MFA and offboarding tickets are not grouped on purpose: two people losing a phone on one day is not an outage.
