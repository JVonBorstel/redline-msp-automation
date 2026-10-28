# Triage eval (Slice A)

> **Fixture-based.** 60 synthetic tickets (Contoso Dental, Fabrikam Capital), classified by the **mock** provider. With the mock, classification is keyword rules in `fixtures/gateway/mock_responses.json`, written by the same author as the tickets, so these numbers show the pipeline working end to end. They are not a measure of model quality or of real tickets.

## Accuracy per field

| Field | Correct | Accuracy |
|---|---|---|
| category | 58/60 | 96.7% |
| priority | 49/60 | 81.7% |
| queue | 59/60 | 98.3% |
| lever | 60/60 | 100.0% |

`lever` compares the lever triage proposed (or none) with the expected one. Priority is a keyword rule over the ticket wording and is the weakest field.

## Prompt injection

- Labelled injection tickets flagged: 8 of 8
- Benign tickets flagged (false positives): 0 of 52
- Flagged tickets that got a lever proposal: 0

## Lever proposals

- Proposals: 13 (user.disable 6, user.reset-mfa 7), each one a dry-run by triage-bot through the lever runner, so it was permission-checked and audited
- Proposals outside the registry or outside the ticket's client: 0
- Audit chain of the eval run verifies: yes

## Misses

| Ticket | Field | Expected | Got |
|---|---|---|---|
| T-3107 | priority | medium | high |
| T-3109 | priority | high | medium |
| T-3114 | priority | critical | high |
| T-3116 | priority | low | high |
| T-3121 | priority | medium | low |
| T-3124 | priority | low | medium |
| T-3127 | category | hardware | mfa |
| T-3206 | priority | medium | high |
| T-3215 | priority | low | medium |
| T-3218 | category | network | account-access |
| T-3218 | priority | low | medium |
| T-3218 | queue | network | identity |
| T-3220 | priority | high | low |
| T-3224 | priority | low | medium |

## Corrections

0 technician correction(s) applied from `evals/triage/corrections.jsonl` (latest per ticket and field wins).

Regenerate: `uv run python -m evals.triage.report`
