# workflows/triage (B-05)

Status: **built** on synthetic fixtures (change note `docs/changes/B-05.md`). Synthetic data only.

Triages one synthetic ticket for a technician. The model (mock by default) only names a category for the wrapped, untrusted ticket text; rules set priority and queue and choose at most one registered lever, which runs as a dry-run and comes back as a pending proposal for a lead, with who it affects (L1-L4) and the verification a lead needs. A ticket flagged for prompt injection gets no lever. Corrections by a technician are kept as eval data.

## Command

```
uv run --frozen python -m workflows.triage T-3101                    # mock model, offline
uv run --frozen python -m workflows.triage T-3101 --provider ollama  # local model on loopback, if one runs
uv run --frozen python -m workflows.triage T-3127 --json
uv run --frozen python -m workflows.triage T-3218 --correct category=network --by tech-ben
uv run --frozen python -m workflows.triage T-3101 --enqueue          # also queue the proposal (.tmp/demo)
```

## Inputs

A ticket from `fixtures/tickets/`, `levers/registry.json`, `config/identities.json` and the mock tenant.

## Outputs

The explanation (text or `--json`), a dry-run audit record under the state folder (default `.tmp/triage`), optionally a queued proposal, and corrections appended to `evals/triage/corrections.jsonl`.

## What is mock

The model is a mock by default (Ollama on loopback is optional) and the tenant is the Graph mock.

## Spec and tests

Specs: `specs/B-05.md` (the owning item; B-26 and B-27 also changed this package) and `specs/slices-abc.md` (Slice A). Tests: `tests/py/triage/test_b05_trace.py`, `tests/phase1/`.
