# Runbooks

For a technician who has never seen this repo. Product runbooks (levers, workflows, incidents) are added with their phases. Index and the Phase 0 runbook are below.

## Index
| Runbook | Phase | Status |
|---------|-------|--------|
| The commit hook blocked a commit | 0 | written |
| Run the offline checks before a pull request | 0 | written |
| Lever operations (dry-run, approve, audit) | 1 | planned |
| Onboarding / offboarding / password reset | 3 | planned |
| Evidence bundle collection | 4 | planned |
| AI incident response | 10 | planned |

## The commit hook blocked a commit
1. Read the reason the hook printed; it names the file or the line that looked like a secret.
2. If it is a real secret, remove it, rotate it at the source, and commit again (see `SECURITY.md`).
3. If it is a placeholder, make it look like one (`example`, `changeme`, `your_...`) or move it to `.env.example`. The scan is heuristic and exempts values that look like placeholders.
4. Install the hook once after cloning: `pwsh -File scripts/install-hooks.ps1`. Recursive deletes of build artifacts: `pwsh -File scripts/clean.ps1`.

## Run the offline checks before a pull request
1. `uv sync --frozen`.
2. `uv run --frozen ruff check . && uv run --frozen ruff format --check . && uv run --frozen mypy`.
3. `uv run --frozen pytest tests/py tests/phase1` and, with PowerShell 7, the suites listed in `docs/ENVIRONMENT.md`.
