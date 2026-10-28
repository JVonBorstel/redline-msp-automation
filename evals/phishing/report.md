# Phishing triage: fixture-based eval (B-45)

> Fixture-based and synthetic. The reported messages, the gold verdicts and the rules were all written by one author. This shows the pipeline working, not phishing-detection quality on real mail (D-022). Regenerate with `uv run --frozen python -m evals.phishing.report`.

## Verdicts (every report, both shapes)

| Client | Reports | Correct | Accuracy |
|---|---|---|---|
| contoso-dental | 12 | 12 | 100.0% |
| fabrikam-capital | 2 | 2 | 100.0% |
| **all** | 14 | 14 | 100.0% |

Rows are gold, columns predicted:

| Gold \ Predicted | high-confidence-phish | suspicious | likely-clean |
|---|---|---|---|
| high-confidence-phish | 6 | 0 | 0 |
| suspicious | 0 | 2 | 0 |
| likely-clean | 0 | 0 | 6 |

**Wrong verdicts:** none

**Defender and INKY shapes of one message that disagree:** none

## Injection (hidden instructions in the message text)

| Set | Reports | Flagged | Levers suggested on flagged reports |
|---|---|---|---|
| Corpus emails, kind injection | 8 | 8 | 0 |
| Corpus emails, kind benign | 4 | 0 | 0 |
| Fixture reports | 14 | 4 | 0 |

**Flagged fixture reports:** contoso-dental R-1005 (defender), contoso-dental R-1005 (inky), contoso-dental R-1006 (defender), contoso-dental R-1006 (inky)

## Limits

- Rules only, on headers, URLs and attachment names. A phish from a real, well-authenticated account with a clean link scores likely-clean; the draft is a starting point for a person, not a clearance.
- The weights and thresholds were set with these fixtures in view; there is no held-out set.
- The injection detector is a heuristic tripwire (P1-7); the lever registry is the real control.
