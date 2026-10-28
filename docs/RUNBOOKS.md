# Runbooks

Owner: repository owner
Last reviewed: 2026-10-28

## Purpose

For a technician who has never seen this repo: where every runbook is, and the two short procedures for working on the repo itself (the commit hook and the offline checks). Product procedures (incidents, identity decisions, client offboarding) are their own files in `docs/runbooks/`, listed in the index.

## Prerequisites

- A clone of this repo with PowerShell 7 and uv on the path; run every command from the repo root.
- The commit hook installed once after cloning: `pwsh -File scripts/install-hooks.ps1`.

## Index

| Runbook | Phase or item | Status |
|---------|-------|--------|
| The commit hook blocked a commit | 0 | written (below) |
| Run the offline checks before a pull request | 0 | written (below) |
| AI incident response (wrong automated action) | B-94 | written: [ai-incident-response.md](runbooks/ai-incident-response.md) |
| Caller identity verification | B-37 | written: [caller-verification.md](runbooks/caller-verification.md) |
| Urgent or hostile termination | B-37 | written: [urgent-termination.md](runbooks/urgent-termination.md) |
| Offboarding a client from the MSP | B-77 | written: [client-offboarding.md](runbooks/client-offboarding.md) |

## Steps

Each procedure below is a short set of numbered steps of its own.

### The commit hook blocked a commit
1. Read the reason the hook printed; it names the file or the line that looked like a secret.
2. If it is a real secret, remove it, rotate it at the source, and commit again (see `SECURITY.md`).
3. If it is a placeholder, make it look like one (`example`, `changeme`, `your_...`) or move it to `.env.example`. The scan is heuristic and exempts values that look like placeholders.
4. Recursive deletes of build artifacts: `pwsh -File scripts/clean.ps1`.

### Run the offline checks before a pull request
1. `uv sync --frozen`, then `uv run --frozen ruff check .` and `uv run --frozen ruff format --check .`.
2. `uv run --frozen mypy` and `uv run --frozen mypy --strict core workflows evals ui mcp rag`.
3. `uv run --frozen pytest -p no:cacheprovider tests/phase1 tests/py`.
4. On Windows with PowerShell 7: `pwsh -NoProfile -File tests/ps/Test-Modules.ps1`, `tests/sliceb/Test-SliceB.ps1` and `tests/demo/Test-Demo.ps1`.

## Rollback

These procedures change no product state. A commit the hook blocked was never made; a failed check changes nothing. Revert any local edit with git.

## Verification

The commit goes through after the fix, and the same checks pass in CI on the pull request (Linux and Windows jobs).
