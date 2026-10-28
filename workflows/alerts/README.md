# workflows/alerts (B-43)

Status: **mocked** on synthetic fixtures (change note `docs/changes/B-43.md`). Synthetic data only.

Groups one client's security alerts by entity inside a time window and prints a summary ordered by severity, so the on-call engineer reads a few grouped events instead of many alerts. It reads and suggests only; it never closes, contains or acknowledges an alert.

## Command

```
uv run --frozen python -m workflows.alerts contoso-dental [--since 2026-10-20T00:00:00Z] [--until ...] [--after-hours] [--text]
```

## Inputs

The client's alerts through the alerts adapter mock (B-43) and `config.json` here (window and business hours).

## Outputs

JSON on stdout (plain text with `--text`); alert text appears only inside untrusted-data blocks. Nothing is written. Exit 0 ran, 2 bad input.

## What is mock

The alert source is an adapter mock over synthetic fixtures; no Defender or SIEM is called.

## Spec and tests

Spec: `specs/B-43.md`. Tests: `tests/py/alerts/test_b43_alerts.py`.
