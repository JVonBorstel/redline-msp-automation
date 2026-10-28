# workflows/reporting (B-71)

Status: **built** on synthetic fixtures (change note `docs/changes/B-71.md`). Synthetic data only.

Read-only exports of fixture-based figures, one sub-package each: `health` (B-71, monthly client health report, every figure recomputed by a second code path), `digest` and `qbr` (B-72, weekly digest and quarterly business review drafts), `roadmap` (B-73, technology roadmap recommendations and the client AI-use policy draft) and `ops` (B-74, operations metrics and Power BI exports, never per technician). Every report is a draft a person reviews; nothing is sent.

## Command

```
uv run --frozen python -m workflows.reporting.health build contoso-dental --period 2026-10 --generated-on 2026-10-31
uv run --frozen python -m workflows.reporting.digest build contoso-dental --week 2026-W42 --generated-on 2026-10-26
uv run --frozen python -m workflows.reporting.qbr build contoso-dental --quarter 2026-Q4 --generated-on 2026-10-31
uv run --frozen python -m workflows.reporting.roadmap build contoso-dental --period 2026-10 --generated-on 2026-10-31
uv run --frozen python -m workflows.reporting.ops export contoso-dental --as-of 2026-10-31
# each has a matching verify command, e.g. uv run --frozen python -m workflows.reporting.health verify build/client-health/2026-10/contoso-dental.draft.html
```

## Inputs

Synthetic fixtures (`fixtures/tickets/`, `fixtures/psa/`, and the `data/` folders inside each sub-package), `governance/AI_POLICY.md`, `governance/ai-vendor-register.json` and `config/models.json`.

## Outputs

Draft files with hashes under `build/client-health/`, `build/digest/`, `build/qbr/`, `build/client-roadmap/` and `build/ops-metrics/`. A report that does not reconcile is not written.

## What is mock

Every source is a synthetic fixture; patching, awareness and baseline shapes are this repo's own and UNVERIFIED; the Outlook draft of the digest belongs to B-88, which is not complete in this checkout.

## Spec and tests

Specs: `specs/B-71.md`, `specs/B-72.md`, `specs/B-73.md`, `specs/B-74.md`. Tests: `tests/py/reporting/test_b71_health.py`, `tests/py/reporting/test_b72_qbr.py`, `tests/py/reporting/test_b73_vcio.py`, `tests/py/reporting/test_b74_ops.py`.
