# B-58 eval: KB drafts and stale/conflict detection

Fixture-based. Synthetic tickets, recorded resolutions and a planted KB, gold answers by one author, no model called, word-overlap retrieval stand-in. It describes these fixtures only.

## Step coverage

Gold step fragments found in drafts: 21 of 21 (100%).

| Client | Drafts | Withheld | Skipped | Rejected | Steps found |
| --- | --- | --- | --- | --- | --- |
| contoso-dental | 3 | 1 | 2 | 2 | 11 of 11 |
| fabrikam-capital | 3 | 1 | 0 | 1 | 10 of 10 |

Missed steps: none.

Outcome errors (withheld, skipped, rejected, drafted set): none.

## Stale and conflict detection (planted KB)

Age limit 365 days.

| Client | Stale | Conflicting pairs | Flagged articles |
| --- | --- | --- | --- |
| contoso-dental | 1 | 2 | 1 |
| fabrikam-capital | 1 | 1 | 0 |

Missed: none. Spurious: none.

## Leak sweep

Planted canaries, other clients' text, requester names and PHI found in any written file: 0.
