# Leadership brief: which automation first, and what stands in the way

Status: **built as a document**; the ranking table is generated from the intake scores and checked by `workflows/assurance/briefs.py`, the rest is hand-written and every list item and table row cites a file or a test. Everything numeric is **fixture-based**.

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only.

## What this page is for

Leadership decides which automation to build next, which to refuse and what to measure first. This page gives the order this prototype's own scoring produces, the risk behind each line, and the questions only leadership can answer. The scoring ranks ideas for a conversation. Leadership decides priority; the score approves nothing (`governance/USE_CASE_INTAKE.md`).

## Ranking by return and risk

The table is the output of `uv run --frozen python -m workflows.assurance score`, which reads ten synthetic intakes, the weights in `governance/intake_rubric.json`, the fixture rows in `governance/roi_fixtures.json` and the never-automate list. Priority is assumed hours per month times fixture acceptance, divided by assumed build days times the risk weight; a blocked or unmeasured idea gets no priority and no rank. Hours are assumptions written into the intakes. Acceptance is the share of fixture cases right against author-written gold labels. The priority is a method, not a saving.

<!-- ranking:begin -->
| Rank | Intake | Idea | Risk class | Hours per month (assumed) | Acceptance (fixture) | Priority | Verdict | Source |
|---|---|---|---|---|---|---|---|---|
| 1 | UC-001 | Ticket triage suggestions for the service desk | R0 | 75.00 | 96.7% | 12.08 | candidate | `fixtures/governance/intakes/UC-001.json`, `evals/triage/report.md` |
| 2 | UC-010 | Alert grouping across security sources | R0 | 53.33 | 92.9% | 7.07 | candidate | `fixtures/governance/intakes/UC-010.json`, `evals/alerts/report.md` |
| 3 | UC-003 | Duplicate ticket and outage grouping | R0 | 20.00 | 100.0% | 5.00 | candidate | `fixtures/governance/intakes/UC-003.json`, `evals/duplicates/report.md` |
| 4 | UC-002 | Reply drafts from the client's own knowledge base | R0 | 33.33 | 69.4% | 2.31 | below-acceptance-bar | `fixtures/governance/intakes/UC-002.json`, `evals/replies/report.md` |
| - | UC-004 | Stale ticket backlog report | R0 | 1.33 | - | - | needs-measurement | `fixtures/governance/intakes/UC-004.json` |
| - | UC-005 | Bulk sign-in block for leavers across tenants | R3 | 30.00 | - | - | design-review-required | `fixtures/governance/intakes/UC-005.json` |
| - | UC-006 | Show the local admin password to the technician | R3 | 4.00 | - | - | blocked | `fixtures/governance/intakes/UC-006.json` |
| - | UC-007 | Hosted-model summaries of dental tickets | R0 | 40.00 | 100.0% | - | blocked | `fixtures/governance/intakes/UC-007.json`, `evals/summary/report.md` |
| - | UC-008 | Caller identity check by model | R0 | 25.00 | - | - | blocked | `fixtures/governance/intakes/UC-008.json` |
| - | UC-009 | Something to make clients happier | R0 | 1.67 | - | - | needs-inventory-mapping | `fixtures/governance/intakes/UC-009.json` |
<!-- ranking:end -->

## What the ranking says

- The top three ideas are read-only (R0) and clear the 90 percent fixture bar: ticket triage suggestions, alert grouping and duplicate grouping (`governance/ROI_TRACKER.md`).
- Reply drafts from the client's knowledge base rank fourth and sit below the bar at 34 of 49 labelled tickets; the fix is a better knowledge-base match, not a lower bar (`evals/replies/report.md`).
- The stale-ticket report has no linked measurement, so it has no priority until one exists (`fixtures/governance/intakes/UC-004.json`).
- A bulk sign-in block across tenants is R3 and needs a written change plan, two approvers and never runs unattended; it is held for design review, not ranked (`fixtures/governance/intakes/UC-005.json`).
- Showing the local administrator password to a technician is refused outright because secrets never enter a prompt, a log or a model route (`fixtures/governance/intakes/UC-006.json`, `governance/never-automate.json`).
- A caller identity check by a model is refused because that work is on the never-automate list; a model never judges whether a caller is who they claim (`fixtures/governance/intakes/UC-008.json`, `governance/never-automate.json`).
- Hosted-model summaries of dental tickets, which send patient-class data to a hosted model, are blocked until a provider is approved, and none is (`fixtures/governance/intakes/UC-007.json`, `governance/AI_POLICY.md`).
- An idea with no declared lever or inventory id is sent back for mapping instead of guessed at (`fixtures/governance/intakes/UC-009.json`).

## What this prototype recommends leadership consider

These are proposals, in order, and none is a commitment or a forecast.

- Start with ticket triage suggestions as a draft for a person to accept, because it has the highest priority in the table, is read-only (R0) and reads 58 of 60 on its fixture report (`evals/triage/report.md`).
- Measure before building more: replace the assumed minutes and runs with the MSP's own timings, since every hours figure here is invented (`governance/ROI_TRACKER.md`).
- Keep hosted model providers off until written retention and training terms and an approval record exist; the approval gate is planned, the safe default is built (`map/controls.json`, `core/gateway/hosted.py`).
- Treat the eval gate as a release check once the owner adds it to CI; the gate file and script exist, the CI step is a proposal (`evals/gates.json`, `docs/changes/B-84.ci-eval-gate.yml`).
- Review any existing scripts with the checklist before any is migrated into the lever registry (`docs/AUTOMATION_FRAMEWORK_REVIEW.md`).

## Risks to know about

- The register lists twelve AI risks and four risks of this tooling itself, with owner roles that are proposals (`governance/RISK_REGISTER.md`).
- Help-desk social engineering is the risk that decides which ideas stay with people; identity verification is never delegated to a model (`governance/never-automate.json`, `docs/map/05-governance.md`).
- The controls claimed are listed with the test behind each and a column for what is not demonstrated; this is a document for review, not a certification (`governance/SOC2_CONTROL_MAPPING.md`).
- The technology radar holds the hosted adapters and the unproven candidates back and says why (`governance/TECH_RADAR.md`).

## Decisions only leadership can make

- Who holds each owner role in the register; the roles are proposals and the real holders are unknown (`governance/RISK_REGISTER.md`, `docs/map/05-governance.md`).
- Whether any hosted model provider may ever be enabled, and under what written terms (`map/controls.json`, `governance/AI_POLICY.md`).
- Which risk appetite and ranking policy apply; the weights and the 90 percent bar here are proposals (`governance/intake_rubric.json`).
- Whether to move the planned documents out of `docs/planned/`, which needs the owner to change a protected acceptance test (`docs/changes/B-95.md`).

## Not shown

- No saving, no cost, no headcount effect and no client outcome is claimed anywhere on this page; the hours column is assumed hours times a fixture rate (`governance/ROI_TRACKER.md`).
- No real ticket, client, technician or the MSP figure was used; the tickets, tenants and timings are synthetic (`docs/BLUEPRINT.md`).
- The models behind each acceptance figure are mocks, so none says how a real model would score (`evals/routing/report.md`).
- All six tracked automations are R0, so the risk weight does not separate them (`governance/ROI_TRACKER.md`).

## Unverified

- UNVERIFIED: whether the MSP holds any audit report is not known to this repo, and nothing here asserts it (`docs/UNVERIFIED.md`).
- UNVERIFIED: the control-to-criterion ids in the mapping were copied from the map and not checked against the criteria text (`docs/changes/B-95.md`).
- UNVERIFIED: the tools and ticketing products the MSP actually runs are inferred, not confirmed (`docs/UNVERIFIED.md`).
