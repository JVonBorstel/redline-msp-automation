# Device reports (B-64)

Status: **mocked**. One client's device compliance, encryption and LAPS coverage, and Autopilot readiness for incoming hires, as hashed JSON and Markdown. Status only: no recovery key or local-admin password is read or shown. Synthetic data only. Spec: `specs/B-64.md`.

```
uv run --frozen python -m workflows.device_reports report contoso-dental --out build/device-reports
uv run --frozen python -m workflows.device_reports verify build/device-reports/contoso-dental/2026-10-22.json
```

Devices come from the B-61 reconciliation (`workflows/device_reconcile`); LAPS metadata, Autopilot identities and hires from `fixtures/<client>.json` here (field status in `fixtures/SOURCES.md`). `config.json` holds the LAPS backup age (35 days) and the urgency window (7 days).
