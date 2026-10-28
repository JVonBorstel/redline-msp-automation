# Routing eval (B-78)

> **Fixture-based.** 60 synthetic tickets (Contoso Dental, Fabrikam Capital) scored against their gold labels by three MOCK tiers: keyword deciders in `evals/routing/mock_backends.json` that stand in for a rules-first tier, a small model and a strong model. They were written by the same author as the tickets. These numbers show the method working end to end. They are not a measure of any real model or of real tickets.

## Accuracy and cost per tier (task: classify the ticket category)

| Tier | Accuracy | Cost per call (relative cost units) | Latency |
|---|---|---|---|
| rules | 78.3% | 0 | not measured (mock) |
| small | 95.0% | 1 | not measured (mock) |
| strong | 95.0% | 20 | not measured (mock) |
| local model | skipped: no local model | skipped: no local model | skipped: no local model |
| cascade (derived thresholds) | 98.3% | 4.15 average | not measured (mock) |

Latency: not measured. The mock tiers answer instantly, so a latency number would be meaningless. Relative cost units are an assumption written in the fixture (rules 0, small 1, strong 20), not money and not measured. The local-model row says `skipped: no local model` because this eval never calls a local model; it does not show a number it did not measure.

## Cascade versus always using the strong tier

- Settled by rules: 31, by small: 18, by strong: 11 (of 60).
- Total cost 249 units for the cascade against 1200 for strong on everything. Cascade accuracy 98.3% against 95.0% for strong alone.
- In-sample: the thresholds were derived from these same tickets, so this is the flattering number. The cascade can beat the strong tier here only because the mock strong tier is wrong on a few tickets where a cheaper mock tier happens to be right; that is a property of these hand-written mocks, not a finding about real models.

## Per category (by gold category)

Accuracy columns are each tier's own answers. `Left rules` is the share the rules tier did not settle (escalated to small or beyond). `Reached strong` is the share neither rules nor small settled. Cascade accuracy is the final answer after escalation.

| Category | Tickets | Rules acc | Small acc | Strong acc | Left rules | Reached strong | Cascade acc |
|---|---|---|---|---|---|---|---|
| account-access | 9 | 100.0% | 100.0% | 88.9% | 0.0% | 0.0% | 100.0% |
| email | 7 | 57.1% | 100.0% | 100.0% | 100.0% | 0.0% | 100.0% |
| hardware | 7 | 71.4% | 85.7% | 71.4% | 28.6% | 28.6% | 85.7% |
| mfa | 8 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| network | 6 | 100.0% | 83.3% | 100.0% | 0.0% | 0.0% | 100.0% |
| offboarding | 7 | 85.7% | 100.0% | 100.0% | 14.3% | 0.0% | 100.0% |
| other | 4 | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 100.0% |
| security | 6 | 83.3% | 100.0% | 100.0% | 16.7% | 0.0% | 100.0% |
| software | 6 | 0.0% | 83.3% | 100.0% | 100.0% | 16.7% | 100.0% |

## Derived escalation thresholds

Rule: per tier and predicted category, the lowest confidence whose accepted decisions are at least 95.0% correct, with at least 3 of them. `never` means no confidence qualified: that tier always escalates for that category. Confidence values are declared in the mock fixture, so the thresholds are fixture-based and are a proposal for review, not applied.

| Tier | Predicted category | Accept at confidence >= |
|---|---|---|
| rules | account-access | 0.6 |
| rules | email | never |
| rules | hardware | 0.8 |
| rules | mfa | never |
| rules | network | 0.8 |
| rules | offboarding | 0.9 |
| rules | other | never |
| rules | security | 0.95 |
| small | account-access | never |
| small | email | 0.7 |
| small | hardware | never |
| small | mfa | never |
| small | network | 0.7 |
| small | offboarding | 0.85 |
| small | other | 0.3 |
| small | security | 0.9 |
| small | software | 0.6 |

## Holdout check

Thresholds derived from 30 tickets (even positions in id order) and the cascade scored on the other 30 (holdout): accuracy 100.0% (strong alone on the same tickets 96.7%), cost 321 units against 600 for strong on everything. With this few tickets per category the holdout is a rough check, not a confidence interval.

## Cascade misses

| Ticket | Gold | Answered | Settled by | Confidence |
|---|---|---|---|---|
| T-3127 | hardware | mfa | strong | 0.95 |

0 technician correction(s) applied from `evals/triage/corrections.jsonl`.

Regenerate: `uv run python -m evals.routing`
