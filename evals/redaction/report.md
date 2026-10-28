# Pre-prompt redaction gate: fixture-based eval (B-55)

> Fixture-based and synthetic. The Phase 2 tickets, their `sensitive` labels and the gate's shape rules were written by one author, and the rules were written with this set in view (D-022). This shows the gate working on this set, not redaction quality on real tickets. Regenerate with `uv run --frozen python -m evals.redaction.report`.

A labelled span **leaks** when its exact text is still in the prompt text the gate produces. Each client's floor comes from its record in `evals/redaction/clients/` (industry, D6-12). Hosted route: summarize on an enabled Anthropic stub; local route: classify on the offline mock.

| Client | Floor | Tickets | PHI/NPI spans | PHI/NPI leaked | PHI/NPI leak rate | PII spans | PII leaked | Typed as labelled | Blocked as DC-6 | Hosted route refused | Local route ok |
|---|---|---|---|---|---|---|---|---|---|---|---|
| contoso-dental | DC-4 | 50 | 11 | 0 | 0.0% | 2 | 0 | 12 of 13 | 0 | 50 | 50 |
| fabrikam-capital | DC-5 | 80 | 12 | 0 | 0.0% | 4 | 0 | 16 of 16 | 0 | 80 | 80 |
| litware-legal | DC-5 | 80 | 11 | 0 | 0.0% | 9 | 0 | 17 of 20 | 0 | 80 | 80 |
| **all** | - | 210 | 34 | 0 | 0.0% | 15 | 0 | 45 of 49 | 0 | 210 | 210 |

## Miss list (labelled spans still in the prompt)

- none

## Redacted under another placeholder type than the label

- T-5137 patient-name redacted as person-name
- T-5322 patient-name redacted as client-name
- T-5372 patient-name redacted as client-name
- T-5375 patient-name redacted as client-name

## Redactions that overlap no labelled span (over-redaction)

- T-5307 client-name
- T-5380 client-name

## Limits

- Names are found only after a cue: patient, investor, limited partner, client, named, the name, an honorific, `the <Name> matter`, `<Name> Family Trust`. A bare name with no cue is not found; the industry floor (DC-4 or DC-5) is what keeps such text off hosted models.
- Dates of birth are found only next to `DOB`, `date of birth` or `born`.
- Personal email addresses and street addresses are not redacted (UPNs are identifiers the tickets need).
- The hosted provider is a stub: the refusal happens before any provider is called, so no hosted model was reached.
