# workflows/assurance (B-95)

Status: **built** on synthetic fixtures (change note `docs/changes/B-95.md`). Synthetic data only.

Plain files and pure functions that keep the governance pages honest. B-95: the use-case intake scorer, the ROI tracker, the SOC 2 control mapping and the risk register, generated from `map/controls.json`, the AIR table of `docs/map/05-governance.md`, the committed eval reports and small data files, so they cannot drift. B-97 (`briefs.py`): the checker for the tech radar, leadership brief, 30/60/90 plan and framework review. B-93 (`approvals.py`): the model and tool approval records and the checker that holds the repo to them. No network, no model, no tenant, no clock.

## Command

```
uv run --frozen python -m workflows.assurance check
uv run --frozen python -m workflows.assurance generate [--write]
uv run --frozen python -m workflows.assurance score [FILE ...] [--json]
uv run --frozen python -m workflows.assurance briefs check
uv run --frozen python -m workflows.assurance briefs ranking [--write]
uv run --frozen python -m workflows.assurance.approvals check [--as-of YYYY-MM-DD]
uv run --frozen python -m workflows.assurance.approvals schema [--write]
```

## Inputs

`map/controls.json`, `docs/map/05-governance.md`, `governance/intake_rubric.json`, `governance/roi_fixtures.json`, `governance/soc2_mapping.json`, `governance/risk_register.json`, `governance/model_tool_approvals.json`, the intakes in `fixtures/governance/intakes/`, and the committed eval reports.

## Outputs

Only the generated governance pages (`governance/USE_CASE_INTAKE.md`, `governance/ROI_TRACKER.md`, `governance/SOC2_CONTROL_MAPPING.md`, `governance/RISK_REGISTER.md`, the ranking table in `docs/LEADERSHIP_BRIEF.md`, the approval JSON Schema), and only with `--write`. Exit 0 fine, 1 a check failed, 2 bad input.

## What is mock

Intakes, ROI minutes and runs are synthetic or assumed and say so; the mapping and register are claims for review, not a certification, an attestation or an audit result.

## Spec and tests

Specs: `specs/B-95.md` (owner of the package), `specs/B-97.md` (briefs), `specs/B-93.md` (approvals). Tests: `tests/py/governance/test_b95_intake_scoring.py`, `tests/py/governance/test_b95_roi_tracker.py`, `tests/py/governance/test_b95_soc2_risk.py`, `tests/py/governance/test_b97_briefs.py`, `tests/py/governance/test_b93_approval.py`.
