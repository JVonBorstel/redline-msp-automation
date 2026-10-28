# Summary and escalation package eval (B-22)

**Fixture-based.** 210 synthetic tickets across three synthetic clients, hand-written by one author, with synthetic PSA contacts and 12 synthetic technician notes. No model is called: the rule-based summary and the fact pack are scored. These numbers test the pipeline; they say nothing about a model or about real tickets.

## Gates

| Check | Result | Pass |
|---|---|---|
| Client proposed correctly for every ticket | 210 of 210 | yes |
| Wrong-client matches | 0 | yes |
| Contact proposed correctly for every ticket | 210 of 210 | yes |
| Affected user matched inside the client only | 9 of 9 | yes |
| Summaries over 400 characters | 0 | yes |
| Summary parts not found in the ticket | 0 | yes |
| Fact recall at least 90% | 100.0% (319 of 319) | yes |
| Unsupported facts | 0 of 2921 | yes |
| Facts that resolve in another client's data | 0 | yes |
| Technician-note sentences found under steps tried | 24 of 24 | yes |
| Injection tickets summarised as flagged | 15 of 15 | yes |
| Free text from a flagged ticket in its package | 0 | yes |
| Summariser calls on flagged tickets | 0 | yes |

## By client

| Client | Tickets | Client ok | Contact ok | Facts | Unsupported | Gold found | Flagged | Related | Device |
|---|---|---|---|---|---|---|---|---|---|
| contoso-dental | 50 | 50 | 50 | 692 | 0 | 78 of 78 | 5 of 5 | 46 | 49 |
| fabrikam-capital | 80 | 80 | 80 | 1135 | 0 | 128 of 128 | 5 of 5 | 75 | 79 |
| litware-legal | 80 | 80 | 80 | 1094 | 0 | 113 of 113 | 5 of 5 | 72 | 79 |

Packages built: 210 of 210; average 13.9 facts each. Clean tickets flagged by mistake: 0. Packages with at least one related ticket: 193. Packages with a requester-stated step: 2.

## What these numbers do not show

- Recall is high partly because the package quotes every sentence of the description; it is not a measure of how well a model picks the important facts. Precision is not scored.
- Steps tried are mostly the 12 hand-written technician notes; the tickets themselves rarely say what the requester tried, so most packages say `none recorded` there.
- Related tickets are found by contact and by shared wording; they are not scored against the duplicate groups (that is B-23).
- Device facts are registered sign-in devices from the tenant. There is no RMM adapter, so laptop health, patches and backup are not covered.
- The injection tickets were written with the detector's rules in view (B-21), so 15 of 15 is a consistency check, not a detection rate.
- No model was evaluated, so `summarize.v1` stays `draft` (C-41 gate not met by this report).

Overall: all gates pass.
