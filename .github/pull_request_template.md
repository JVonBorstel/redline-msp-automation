## What and why
<!-- One or two sentences. Link the spec (specs/) or decision (docs/DECISIONS.md) if there is one. -->

## Roadmap item
<!-- B-nn and the issue it closes, e.g. "B-03, closes #5". One roadmap item per PR. -->

## Individual to macro (STD-DD-10)
<!-- Impact chain id(s) from map/impact.json, then one line each. -->
- L1 one person at one client:
- L2 the client business:
- L3 the MSP:
- L4 the community:

## Checklist
- [ ] This PR touches only the paths the roadmap item owns (map/roadmap.json).
- [ ] Every acceptance id has a test named after it, and `uv run --frozen python map/check_map.py` passes.
- [ ] CI is green.
- [ ] Synthetic data only: no real client or company data, names, tickets or credentials.
- [ ] No secrets in files, logs, commits or this description (`.env.example` only).
- [ ] Anything that changes state is dry-run by default and has an approval record.
- [ ] Any metric or result is from this repo's fixtures and labeled fixture-based; anything I could not verify is labeled unverified.
- [ ] Docs updated (`docs/COVERAGE.md` status words are honest: "built" means real code with passing tests).
- [ ] This PR does not touch `scripts/`, `.github/` or `config/` -- or it does, and the owner has asked for that change.

## Built / mocked / not done
<!-- Use the strict status words from docs/BLUEPRINT.md section 7. -->
