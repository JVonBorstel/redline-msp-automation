# redline-msp-automation

> Independently built prototype. Not affiliated with any vendor's or real company's systems. All tenants, people and tickets are synthetic.

Redline is a governed AI automation program for a managed service provider (MSP), built as runnable, tested software. The design rule is one sentence: **agents are button-pushers.** Deterministic, tested scripts ("levers") do the work; a model only chooses which lever to press and fills validated parameters. Permissions, approval and audit live on the lever, not on the model.

**At a glance.** Run the packaged demo (one command, below) and the test suites. Proven by tests on synthetic fixtures: lever permissions, approvals, dry-run and pause; a tamper-evident audit log; client scoping; a loopback-only model gateway; a prompt-injection tripwire; a local approval page. Not proven: anything against a real tenant, real tickets or real users. Nothing here has been used in production, and no result in this repo is real-world: every number comes from this repo's fixtures and is labeled fixture-based.

## What this is
A prototype of how an MSP service desk and its security and compliance work could be automated without handing a model the keys. One story runs through it: a locked-out person (Priya Nair, synthetic, at Contoso Dental, ticket `T-3101`) is helped by a chain that protects her at every step, from the first triage to the audit record and the notice she receives. Around that story sit about forty read-only or proposal-only workflows, a lever registry, a hash-chained audit log, an approval page, mock adapters for the systems an MSP touches, evals, a governance pack and infrastructure source files. All of it runs offline on the mock model unless a local model is configured.

## Architecture in ten lines (the lever model)
1. Ticket text, email and documents are **untrusted data**. They are scanned for injection, wrapped as labelled data blocks, and can never change permissions or tool choice (`core/guard`).
2. A workflow (`workflows/*`) is a thin sequence. A small model classifies or summarizes through one gateway interface (`core/gateway`); rules, not the model, pick at most one registered lever.
3. A **lever** is a typed, tested action in `levers/` declared in `levers/registry.json` and `levers/registry.d/`. It states its client scope, required role, read or write class, risk class (R0 to R3), approval rule, idempotency key, dry-run support, timeout, undo and who it affects.
4. The runner (`core/levers`) enforces all of that in code, for every call: schema, role, client scope, pause switch, requester verification for identity changes, lead approval, two approvers for R3.
5. Every lever starts as a **dry-run**: a diff of what would change. Nothing changes without a recorded approval bound to that exact lever, client and parameters.
6. Humans approve in a local page (`ui`, 127.0.0.1 only) or by CLI; the approver, not the model, carries the authority. Any lead can pause a lever at once.
7. Levers act through adapters (`adapters/`) that are mocks of a PSA, Microsoft Graph, backup, alerts and device tools. No adapter talks to a real system.
8. Every call, allowed or denied, writes one hash-chained audit record (`core/audit`); a verifier command proves the chain is intact and names the first broken record.
9. Drafts for people (replies, notices, reports) are written from templates or by the mock model; a person reads and sends every one.
10. Everything runs offline. Hosted model providers are stubs and off by default; the default backend is a deterministic mock, with an optional loopback-only local model. A fooled model can only press buttons it was allowed to press.

Diagrams and the one-lever-call sequence: `docs/ARCHITECTURE.md`. Decisions with reasons and alternatives: `docs/DECISIONS.md`.

## What is real and what is mock
"Real" means real code with a passing test in this repo. It does not mean connected to a real system.

| Area | Status | What is there |
|---|---|---|
| Lever registry, runner, approval, dry-run, pause (`core/levers`) | Real | Enforced in code and tested; the levers act on a mock tenant folder. |
| Audit log and verifier (`core/audit`) | Real | Hash chain, head pin, per-client chains, secret redaction, `python -m core.audit.verify`; a port of the verifier runs in the browser on the showcase site. |
| Identities, roles, client scope (`core/identity`) | Real | A file of synthetic technicians, leads and agents. |
| Approval page and queue (`ui`, `core/queue`) | Real | Standard-library server on 127.0.0.1, no scripts, CSRF-protected; runs against the mock tenant. |
| Approver sign-in (`core/auth`) | Mock | Entra-ID-shaped token validated offline against a mock issuer. No Microsoft-issued token has ever been validated. |
| Model gateway (`core/gateway`) | Mock | One interface; the default model is a deterministic mock. A loopback Ollama adapter exists but was not exercised against a real model here; hosted providers are off stubs. |
| Injection tripwire and evals (`core/guard`, `evals/injection`) | Real code, mock data | The 100 percent figures are fixture-based, on a corpus written alongside the rules. |
| Adapters (PSA, Graph, backup, alerts, RMM, Intune) | Mock | Shapes are assumptions; every vendor field name is UNVERIFIED (`docs/UNVERIFIED.md`). |
| PowerShell levers and the TenantBaseline module | Mock | Run on mock Graph-shaped data; cmdlet and field names UNVERIFIED. |
| Workflows (`workflows/*`: triage, summaries, SLA, backup review, alerts, lockout, expiry, fact packs, rollback, reporting and more) | Mock | Read-only or proposal-only over synthetic fixtures; nothing is sent, renewed or changed by software. |
| Retrieval (`rag`) and MCP server (`mcp`) | Mock | In-memory stores and a stdio server; protocol details UNVERIFIED, never connected to a real client. |
| Governance pack (`governance/`, `docs/`) | Document-only | Policies, mappings and runbooks, with checkers for their format. Not reviewed by a lawyer, an auditor or an MSP. |
| Infrastructure (`infra/`) | Document-only | Bicep and pipeline source; never compiled, validated or deployed. |
| Docker files (`Dockerfile`, `docker-compose.yml`) | Document-only | Written, never built or run (no Docker on the build machine). |
| Real tenants, tickets, users, PSA or RMM | Not built | None connected. No result here is real-world. |

## Run the packaged demo
One command, offline, synthetic data, about ten to fifteen seconds. You need [uv](https://docs.astral.sh/uv/) (Python 3.12 comes from uv; Python is run only through uv).
```bash
git clone https://github.com/JVonBorstel/redline-msp-automation
cd redline-msp-automation
export UV_PYTHON_PREFERENCE=only-managed      # PowerShell: $env:UV_PYTHON_PREFERENCE = 'only-managed'
uv sync --frozen
uv run --frozen python tools/packaged_demo.py
```
It writes into a new temp folder (or `--state DIR` for an empty one) and prints a short transcript of ten steps: the registry; triage of `T-3101` with who it affects and the call-back check; an injection ticket flagged with no lever; the runner refusing the change without approval and without the requester check; a lead approving after a recorded call-back and the change running on the mock tenant; the notice draft for the person; a lever paused, a call denied, resume; the audit chain verified; one changed letter caught in a copy of the log; the injection eval. It exits 0 only if every step passed. It does not run the PowerShell baseline check or the web page; the full five-minute script with those is `docs/DEMO.md`.

With Docker (written but never built or run; the UI is not published to the host because it refuses any address but loopback):
```bash
docker compose run --rm demo
```

Try single pieces (state goes to `.tmp/demo`):
```bash
uv run --frozen python -m core.levers list
uv run --frozen python -m core.levers invoke user.reset-mfa --as tech-ana --client contoso-dental -p upn=ana.lopez@contosodental.example   # dry-run: a diff, nothing changed
uv run --frozen python -m workflows.triage T-3101 --enqueue --state .tmp/demo
uv run --frozen python -m ui --state .tmp/demo --demo     # approval page on 127.0.0.1 (demo picker, not a sign-in)
uv run --frozen python -m evals.injection.report
```

## Run the test suites
From the repo root (the PowerShell suites need PowerShell 7; see `docs/ENVIRONMENT.md`):
```bash
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy
uv run --frozen mypy --strict workflows evals ui mcp rag
uv run --frozen pytest tests/py tests/phase1 tests/demo
pwsh -NoProfile -File tests/ps/Test-Modules.ps1       # PowerShell lever modules and schemas
pwsh -NoProfile -File tests/sliceb/Test-SliceB.ps1    # Microsoft 365 baseline (PowerShell, mock Graph data)
pwsh -NoProfile -File tests/demo/Test-Demo.ps1        # every typed command in docs/DEMO.md, run end to end
```
CI runs the same on Linux and Windows and needs no secrets. Install the commit-time secret scan once: `pwsh -File scripts/install-hooks.ps1`.

## Roadmap status
The roadmap (`map/roadmap.json`) has one item per piece of work. The numbers below are **computed**, not typed: `tools/coverage_audit.py` recomputes every status from the files in the checkout and a test fails when this block is out of date.

<!-- audit:status:start -->
Roadmap: 87 of 98 items built, 7 partial, 4 not demonstrated, 0 planned (89 change notes say built, mocked or document-only). Inventory: 130 of 152 built, 20 partial, 0 planned, 2 not demonstrated, 0 not planned by design. Controls: 26 of 45 built, 2 partial, 0 planned, 17 not demonstrated. Map-versus-code disagreements: 196 (7 error, 126 stale, 15 gap, 48 info).

Computed by `tools/coverage_audit.py` from the map and the files in this checkout (fixture-based; "built" means the files, a spec, a change note and a tied test exist, not that the tests were re-run). The full per-item report with every disagreement is `docs/COVERAGE_AUDIT.md`.
<!-- audit:status:end -->

```bash
uv run --frozen python tools/coverage_audit.py --headline   # the line above
uv run --frozen python tools/coverage_audit.py --write      # regenerate docs/COVERAGE_AUDIT.md, this block and the patch
uv run --frozen python tools/coverage_audit.py --check      # exit 1 when any of them is out of date
```
The audit lists, per roadmap item, inventory row and control, its true status, and every place the map and the code disagree. Gaps are listed, not hidden: `docs/COVERAGE_AUDIT.md`.

## The showcase site
`site/` builds a static site from real runs of this code: triage a ticket, replay the approval queue, tamper with the audit log and verify it in your browser, read the roadmap and the evidence. It makes no third-party requests and stores nothing. Build it with `python site/build.py` (needs uv and PowerShell 7; it builds from this repository and works offline once the uv cache is warm; add `--offline` to forbid network); see `site/README.md`.

When GitHub Pages is enabled for the repository, the `pages` workflow publishes the site from `main` at <https://jvonborstel.github.io/redline-msp-automation/>. Pages: [overview](https://jvonborstel.github.io/redline-msp-automation/index.html), [triage](https://jvonborstel.github.io/redline-msp-automation/triage.html), [approvals and the audit chain](https://jvonborstel.github.io/redline-msp-automation/approvals.html), [injection](https://jvonborstel.github.io/redline-msp-automation/injection.html), [baseline check](https://jvonborstel.github.io/redline-msp-automation/baseline.html), [workflows](https://jvonborstel.github.io/redline-msp-automation/workflows.html), [levers](https://jvonborstel.github.io/redline-msp-automation/levers.html), [roadmap](https://jvonborstel.github.io/redline-msp-automation/roadmap.html), [proof](https://jvonborstel.github.io/redline-msp-automation/proof.html), [about](https://jvonborstel.github.io/redline-msp-automation/about.html). The links work once Pages is enabled.

## Design trade-offs
- **Levers over free-form agents.** A model that can only press registered buttons is less capable and far easier to audit. Adding capability means adding a lever with its tests, not a prompt.
- **Rules pick the lever, the model only classifies.** Cheaper and testable, at the cost of rules to maintain. Routing thresholds come from eval results, not opinion.
- **Approval on every write, even in the mock.** Slower for the demo, but the approval, verification and audit paths are what is being shown.
- **Standard library and few dependencies.** A small web page with no scripts and a stdio MCP server avoid framework sprawl, and mean less is battle-tested than a mature framework would be.
- **Mocks shaped like the real thing.** Adapters follow the public shape of the systems as far as it was checked; where it was not, the field is marked UNVERIFIED instead of guessed.

## Honest limits
- Nothing here has been used in production or run against a real tenant, PSA, RMM, ticket or user. All data is synthetic; every number is fixture-based and says nothing about real-world performance.
- "Built" means real code with a passing test in this repo, never "verified against the vendor". Vendor products, API fields, prices, limits and regulations that were not checked against a source are listed in `docs/UNVERIFIED.md`.
- The call-back check is a lead's recorded attestation, not proof that a call happened. The audit log catches edits, not a lead who lies.
- The injection tripwire is a heuristic; the control that matters is that a fooled model can only press buttons it was allowed to press.
- The coverage audit is static: it checks that the evidence files exist and agree with the map, and it does not re-run tests or judge their quality.
- The repo has had no security review by anyone outside it.

## Adapting this to a real MSP
- Start read-only: connect a PSA and a device tool as read levers (get a ticket, a device's status, a client's contract). Write levers come only after the read side has earned trust, and always with dry-run and approval.
- Use a test tenant and a read-only application registration with the narrowest scopes, trimmed in that tenant; secrets in a vault, reached with a managed identity, never in code or config.
- Replace each mock adapter behind the same interface, one client at a time, and re-check every UNVERIFIED field against the real API before trusting a result.
- Keep the same gates in the MSP's own pipeline: tests, lint, types, secret scan, and approval before anything changes a client.
- Use the MSP's own client list, risk classes and approvers; learn the top ticket types by shadowing the service desk before adding a lever.

## Rules this repo follows
Synthetic data only. No secrets. Dry-run by default. No installs, model downloads, cloud changes or spending without asking. Anything unverified is labeled unverified. Full list: `docs/BLUEPRINT.md`; how to contribute: `CONTRIBUTING.md`; security policy: `SECURITY.md`.

## Layout
`core/` runner, audit, identity, queue, gateway, guard; `levers/` the actions and their registry; `workflows/` thin sequences; `adapters/` mocks; `ui/` the approval page; `rag/`, `mcp/`, `prompts/`, `evals/`; `governance/` and `docs/` documents; `infra/` source files; `map/` the inventory, controls and roadmap; `specs/` one spec per item; `tests/` the suites; `tools/` the audit, the packaged demo and helper scripts; `site/` the showcase site; `scripts/` and `.github/` helper scripts and CI.

## License
Apache License 2.0. See [LICENSE](LICENSE).
