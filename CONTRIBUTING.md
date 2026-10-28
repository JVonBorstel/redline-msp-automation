# Contributing

> Independently built prototype. All tenants, people and tickets are synthetic.

Thanks for looking. This is a one-person portfolio project, so changes are welcome but reviewed slowly. The hard rules in `docs/BLUEPRINT.md` section 1 apply to everyone: synthetic data only, honest labels, no secrets, dry-run by default, and no installs or cloud changes without a stated reason.

## Workflow
1. **Branch.** Never commit to `main`. Branch from `main` (`feat/<topic>`, `fix/<topic>`, `docs/<topic>`).
2. **Change.** Small, boring, well-tested. Tests first where there is code. Docs written for a technician who has never seen the repo.
3. **Run the checks locally** (uv, and PowerShell 7 for the PowerShell suites; see `docs/ENVIRONMENT.md`):
   ```bash
   uv sync --frozen
   uv run --frozen ruff check . && uv run --frozen ruff format --check .
   uv run --frozen mypy && uv run --frozen mypy --strict core workflows evals ui mcp rag
   uv run --frozen pytest tests/py tests/phase1 tests/demo
   ```
   Optional: `pwsh -File scripts/install-hooks.ps1` enables a commit-time secret scan. Python is run through uv (`uv run ...`), never a bare interpreter.
4. **Open a pull request** into `main` and fill in the template.
5. **CI must be green.** The `ci` workflow runs lint, types and the test suites on Linux and Windows. Do not merge on red.
6. **Owner approval.** `.github/CODEOWNERS` makes the owner (@VonBorstel-J) the required reviewer. Nobody merges their own pull request without that approval, and automated agents never approve or merge.
7. **Merge**, then delete the branch.

## Things that need the owner's explicit say-so
- Anything under `scripts/` (guard scripts and hooks), `.github/`, `config/`, `pyproject.toml` or `uv.lock`. A change that weakens a check must be called out in the pull request description.
- Installs, model downloads, cloud resources, spending, new third-party GitHub Actions.

## Rules for GitHub Actions
Pin every action to a released major version and keep `permissions: contents: read` unless a job proves it needs more. Workflows must not need secrets. Dependabot proposes updates weekly.

## Status words
"Built" means real code with passing tests. "Mocked", "planned" and "document-only" are labels, not synonyms. Metrics come from this repo's fixtures and are labeled fixture-based. If you could not verify something, say so in the docs.

## Reporting security issues
See `SECURITY.md`. Do not put secrets or real data in issues or pull requests.
