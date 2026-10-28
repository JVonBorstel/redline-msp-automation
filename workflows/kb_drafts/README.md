# workflows/kb_drafts (B-58)

Status: **built** on synthetic fixtures (change note `docs/changes/B-58.md`). Synthetic data only.

`drafts` turns each resolved ticket with a recorded resolution into a DRAFT article (the recorded steps, redacted; the ticket text is never copied). `detect` lists stale articles and pairs of articles that say opposite things about the same topic. Nothing is published or written to a knowledge base.

## Command

```
uv run --frozen python -m workflows.kb_drafts drafts contoso-dental [--out build/kb-drafts]
uv run --frozen python -m workflows.kb_drafts detect contoso-dental [--as-of 2026-10-23] [--max-age-days 365]
```

## Inputs

The dated synthetic ticket set, the recorded resolutions in `data/resolutions/` here, the KB fixtures in `fixtures/kb/`, review dates from the B-59 documentation fixture, and B-57 retrieval.

## Outputs

Draft files under `build/kb-drafts/` and a detection report under `build/kb-detect/`. Exit 0 done, 2 bad input.

## What is mock

The knowledge base and tickets are synthetic fixtures; the contradiction rules are lexical and miss paraphrases.

## Spec and tests

Spec: `specs/B-58.md`. Tests: `tests/py/kb/test_b58_kb_drafts.py`.
