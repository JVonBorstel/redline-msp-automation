# workflows/questionnaires (B-60)

Status: **built** on synthetic fixtures (change note `docs/changes/B-60.md`). Synthetic data only.

Drafts answers for a synthetic questionnaire. Every answer is a DRAFT for a named owner, built only from quoted retrieved passages, repo controls that are built or partial with an existing test, or hour ranges from similar past projects; anything else is refused as needing a person. No model is called and nothing is sent.

## Command

```
uv run --frozen python -m workflows.questionnaires draft fixtures/questionnaires/security_questionnaire.json --owner "Dana Whitfield" --out build/questionnaires
```

## Inputs

A questionnaire file under `fixtures/questionnaires/`, B-57 retrieval, `map/controls.json` with the B-95 mapping, and synthetic project history.

## Outputs

`<name>.md` and `<name>.json` in `--out` (Markdown to stdout without it). Exit 0 drafted, 2 bad input.

## What is mock

Questionnaires, passages and projects are synthetic; nothing asserts certification or production operation.

## Spec and tests

Spec: `specs/B-60.md`. Tests: `tests/py/questionnaires/test_b60_questionnaires.py`.
