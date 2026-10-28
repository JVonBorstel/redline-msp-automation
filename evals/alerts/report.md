# Alert grouping: fixture-based eval (B-43)

> Fixture-based and synthetic. The alerts, the gold groups and the grouping rule were all written by one author, with the alerts in view. This shows the pipeline working and where it errs, not alert-grouping quality on real feeds (D-022). Regenerate with `uv run --frozen python -m evals.alerts.report`.

Settings (from the workflow config): window 60 minutes; groups are keyed by client, group type (incident or health) and entity. All clients' alerts are mixed in one list before grouping.

## Alert pairs

| Client | Alerts | Groups | Gold groups | True pairs | Predicted pairs | Correct pairs | Pair precision | Pair recall |
|---|---|---|---|---|---|---|---|---|
| contoso-dental | 18 | 11 | 6 | 11 | 10 | 10 | 100.0% | 90.9% |
| fabrikam-capital | 7 | 4 | 3 | 3 | 3 | 3 | 100.0% | 100.0% |
| **all** | 25 | 15 | 9 | 14 | 13 | 13 | 100.0% | 92.9% |

**Missed pairs:** A-1017+A-1018

**False pairs:** none

## Health group type (RMM agent and endpoint sensor health)

| Client | Gold health groups | Found as one health group | False health groups |
|---|---|---|---|
| contoso-dental | 1 | 1 | 0 |
| fabrikam-capital | 1 | 1 | 0 |
| **all** | 2 | 2 | 0 |

## Isolation

Alerts of another client found inside any group: 0 (must be 0).

## Limits

- Grouping needs a shared entity id. An alert about a device and one about the person who used it do not group until an enrichment step links them (B-44); that is the missed pair above.
- One window for every source. Slow-burn activity across hours is not grouped, by design for this item.
- Gold singletons are not scored beyond the pairs: a group that wrongly absorbs one shows as false pairs.
