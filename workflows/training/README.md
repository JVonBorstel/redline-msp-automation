# workflows/training (B-96)

Status: **built** on synthetic fixtures (change note `docs/changes/B-96.md`). Synthetic data only.

Checks the four hand-written B-96 pages (`governance/STAFF_TRAINING.md`, `governance/CLIENT_CONVERSATION_GUIDE.md`, `docs/AI_EXPLAINER.md`, `docs/CLIENT_DATA_HANDLING.md`): every claim about the system carries a tag naming the test or file that backs it, cited files and tests exist, over-claims and unlabelled numbers fail, and the one-page pages stay short and plain.

## Command

```
uv run --frozen python -m workflows.training check [--root DIR]
```

## Inputs

The four pages and the files and tests they cite.

## Outputs

A list of problems on stdout. Exit 0 every check passed, 1 a check failed.

## What is mock

The pages are document-only: nobody has taken the training and no real client has seen them. The checker proves a cited test is defined, not that it passes.

## Spec and tests

Spec: `specs/B-96.md`. Tests: `tests/py/governance/test_b96_training_docs.py`.
