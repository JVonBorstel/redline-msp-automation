# workflows/phishing (B-45)

Status: **mocked** on synthetic fixtures (change note `docs/changes/B-45.md`). Synthetic data only.

Reads a user-reported message as data only (headers as text, URLs split and never requested, attachments judged by name) and drafts a cited verdict with structured lever hints for a person. No lever runs.

## Command

```
uv run --frozen python -m workflows.phishing --client contoso-dental [--reports PATH]
```

## Inputs

Reports in `fixtures/mailflow/reports/<client>.json`, in Defender-style or INKY-style shapes (both UNVERIFIED stand-ins).

## Outputs

Verdict drafts on stdout. Nothing is written. Exit 0 ran (also with nothing to triage), 2 bad input.

## What is mock

The reported messages and both report shapes are synthetic.

## Spec and tests

Spec: `specs/B-45.md`. Tests: `tests/py/phishing/test_b45_phishing.py`.
