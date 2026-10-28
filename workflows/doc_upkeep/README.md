# workflows/doc_upkeep (B-59)

Status: **built** on synthetic fixtures (change note `docs/changes/B-59.md`). Synthetic data only.

Compares one client's documentation with observed state and reports stale, missing and contradictory pages, each with a draft fix for a person. Nothing is written to a documentation system and no lever is invoked.

## Command

```
uv run --frozen python -m workflows.doc_upkeep report contoso-dental [--as-of 2026-10-23] [--out build/doc-upkeep]
uv run --frozen python -m workflows.doc_upkeep report contoso-dental --fail-on-findings
```

## Inputs

The client's KB scope `fixtures/kb/<client>/manifest.json`, the documentation fixture `data/<client>.json` here, and observed state through the RMM, PSA and Graph mock adapters.

## Outputs

A report pair under `build/doc-upkeep/`. Exit 0 done, 1 findings exist and `--fail-on-findings` was given, 2 bad input.

## What is mock

The documentation platform and the observed state are synthetic fixtures and mocks.

## Spec and tests

The runbook linter of the same item is `tools/lint_runbook.py`. Tests: `tests/py/kb/test_b59_doc_upkeep.py`.
