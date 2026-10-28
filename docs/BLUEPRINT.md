# REDLINE: PROGRAM BLUEPRINT

Status: **built as a plan**; the phases below are delivered, see `docs/ROADMAP.md` for the current state.

> Independently built prototype. Synthetic data only.

This is the master design for Redline: an AI and automation program for a managed service provider (MSP), built as real, runnable, tested software on synthetic data. It is the plan the code was built from. Section numbers are cited from other documents (for example "blueprint section 3"), so they stay stable.

Work in PHASES. Finish a phase completely, verify it, report, and stop for the owner's go-ahead. Do not start the next phase on your own. Quality over speed.

---------------------------------------------------------------------
## 1. HARD RULES (override everything else)
1. SYNTHETIC DATA ONLY. No real client, company or person data, names, tickets, credentials or documents. Invent tenants ("Contoso Dental", "Fabrikam Capital") and tickets.
2. HONEST LABELS. README states: "Independently built prototype." Never claim production use or real-world results. Any metric comes from this repo's fixtures and is labeled fixture-based.
3. BLAST RADIUS: work only inside this repository. Do not modify any other folder or repo.
4. NO SECRETS in files, logs, commits or prompts. `.env.example` only. Pre-commit secret scan. Never print env values.
5. DRY-RUN BY DEFAULT. Anything that changes state (even in mocks) needs an approval record and supports a dry-run diff first.
6. No global installs, no network downloads of models, no cloud resource creation, no spending money without asking the owner first with the exact command and reason. Azure/Bicep: validate and what-if only, never deploy.
7. If you can't verify something (API behavior, model quality, a version), say so in the docs. Never guess and present it as fact.
8. Ask the owner only when blocked on an irreversible or costly choice. Otherwise decide, record it in `docs/DECISIONS.md`, and continue.

---------------------------------------------------------------------
## 2. SCOPE (build to this)
Setting: an MSP that offers managed IT, cybersecurity, backup and disaster recovery, and Microsoft cloud services (Microsoft 365 and Azure) to small and mid-sized regulated businesses. The reference MSP is an assumption, not a description of any real company (`docs/map/07-msp-profile.md`). The program is built to work with technicians, account managers, leadership and clients.

Capabilities to implement or document:
AI ENGINEERING
- AI agents on top of a model gateway; prompt engineering standards; reusable prompt libraries; AI workflows
- Internal tools that raise technician productivity and automate repetitive work
- RAG over documentation and knowledge bases; AI-assisted reporting and knowledge management
- Evaluating emerging AI technology and recommending adoption
- AI governance framework: policies, access control, auditability, testing standards, monitoring, security controls across the AI lifecycle, secure by design, protecting internal and client data
AUTOMATION ENGINEERING
- Scripts and integrations across PSA, RMM, Microsoft 365, Azure and security platforms
- Advanced PowerShell and API-driven automation for Windows, macOS, Linux and cloud
- Automating deployment, monitoring, remediation and infrastructure management; improving existing automation frameworks
CLOUD AND DEVOPS
- Azure Functions, Logic Apps, Automation Accounts; CI/CD; Git branching, code review, release process
- Secrets management with Key Vault; monitoring production AI and automation for reliability
COLLABORATION
- Finding automation opportunities with technical teams; prioritizing with leadership by measurable ROI; documenting standards and architecture; prototyping emerging technology
- Explaining AI to non-technical audiences; strong documentation; managing stakeholder expectations
Further skills shown: MCP, agentic workflows, Python plus PowerShell, Power Platform, containers, infrastructure as code, Power BI, Azure OpenAI, Teams/SharePoint/Outlook integration, DLP/Purview, ITIL-style operations.

---------------------------------------------------------------------
## 3. DESIGN PHILOSOPHY (apply in every design decision)
- AGENTS ARE BUTTON PUSHERS. Deterministic, tested scripts ("levers") do the work. The model only chooses which lever and fills validated parameters. It never improvises steps, never runs free-form shell or code.
- PERMISSIONS LIVE ON THE LEVER, NOT THE MODEL. Each lever declares: client scope, role required, read/write class, approval requirement, idempotency key, dry-run support, timeout. Enforced in code. A fooled model can only press buttons it was allowed to press.
- MOST INTELLIGENT MODEL ONLY WHERE NEEDED. Route: rules and scripts first, small model for classify/summarize, strong model only for hard reasoning. Routing thresholds are set by eval results, not opinion.
- OPEN SOURCE FIRST, NEVER LOCKED IN. A model gateway presents one internal interface. Default backend: a local open-weight model behind an OpenAI-compatible endpoint (Ollama or vLLM; read model names from config, never hardcode). Hosted providers (Azure OpenAI, Anthropic, others) are adapters, off by default, last-resort escalation. Swapping provider is a config change. Prefer open-source libraries.
- ZERO TRUST. Each agent has its own identity, least privilege, per-client isolation at the tool and retrieval layers. Ticket text, emails and documents are UNTRUSTED input: content can never change permissions or tool selection rules; instructions inside data are flagged, not followed.
- AUDITABLE. Every lever call writes an append-only, hash-chained audit record (agent, client, lever, params, result, approver, timestamp). A verifier CLI proves the chain is intact. This is SOC 2 evidence.
- EXPLAINABLE. Every suggestion shows why, which data it used, and what lever it would pull.

---------------------------------------------------------------------
## 4. STACK
- Python 3.12: uv, Pydantic v2, pytest, ruff, mypy. Agents, gateway, evals, RAG.
- PowerShell 7: the primary language for identity, device and M365 levers. Tests and PSScriptAnalyzer. Use `-WhatIf`/`ShouldProcess` properly, structured output, error handling. Python orchestrates, PowerShell acts. A few Bash levers for Linux/macOS.
- Data: SQLite default, Postgres-ready. Vector store behind an interface.
- Observability: structured JSON logs, request IDs.
- IaC and CI/CD: Bicep for Azure Functions, Logic App, Automation Account, Key Vault, managed identities, Log Analytics; `azure-pipelines.yml` plus a GitHub Actions equivalent. Validate with linters and what-if only.
- Secrets: Key Vault references and managed identity in templates; `.env.example` locally.
- Reporting: Power BI-ready CSV exports plus HTML reports; the semantic model is documented.
- MCP: the lever registry is exposed as an MCP server (read-only by default, scoped), with documented security checks (token audience validation, no token passthrough, vetted servers only).
- UI: a minimal local page for the approval queue and audit viewer only.

---------------------------------------------------------------------
## 5. ARCHITECTURE (see `docs/ARCHITECTURE.md` for the diagrams)
core/gateway   model gateway, router, provider adapters, deterministic mock provider
core/levers    registry, schema validation, scope/approval enforcement, dry-run engine
core/audit     hash-chained log, verifier CLI
core/identity  agent identities, per-client scoping, roles
core/guard     untrusted-input handling, injection corpus and detectors
levers/powershell/  modules + tests      levers/python/  levers + tests
adapters/      psa, rmm, graph_entra, intune, m365 (teams/sharepoint/outlook), security_alerts, docs_kb. INTERFACES first, realistic MOCKS good enough to run everything offline, real adapters stubbed behind flags with documented TODOs
rag/           ingestion, per-client isolation at retrieval, citations, groundedness eval
prompts/       versioned prompt library, standards, prompt tests
mcp/           MCP server for approved levers
workflows/     each = levers + thin agent loop + evals + doc
evals/         golden sets, scorers, routing report
ui/            approval queue, audit viewer
infra/         bicep/, azure-pipelines.yml
governance/    AI policy, acceptable use template, data classification and DLP mapping, approval process for models and tools, risk register, AI incident response, new-use-case intake and scoring, SOC 2 control mapping
docs/          ARCHITECTURE, THREAT_MODEL, RUNBOOKS, DECISIONS, COVERAGE, ROI tracker, tech radar, staff training, client conversation guide

---------------------------------------------------------------------
## 6. BUILD PROCESS
- Specs first: one spec file per phase or roadmap item under `specs/`, written before code, with acceptance criteria.
- Tests first where there is code; every acceptance id has a test named after it.
- Independent review at the end of every phase: a second pair of eyes re-checks the acceptance criteria and tries to break the work, and a security pass looks at injection, scope, secrets and least privilege.
- CI (`.github/workflows/ci.yml`) runs lint, types and every test suite; a pre-commit secret scan (`scripts/hooks/pre-commit`) is optional locally.
- Change notes per roadmap item (`docs/changes/`) and written decisions (`docs/DECISIONS.md`).

---------------------------------------------------------------------
## 7. PER-PHASE PROTOCOL
For each phase: (1) write `specs/phase-N.md` with deliverables and acceptance tests; (2) write tests first; (3) build; (4) run lint, types, tests; (5) have an independent review and a security review and fix what they find; (6) update `docs/COVERAGE.md` and the docs; (7) commit with a clear message; (8) report to the owner in this format and STOP:
   BUILT (works, tested) / MOCKED / NOT DONE / RISKS / HOW TO RUN / WHAT TO REVIEW.
Status words are strict: "built" means real code with passing tests. Never mark something built if it's a stub.

---------------------------------------------------------------------
## 8. PHASES
PHASE 0: Environment and scaffold. Repo, CI skeleton, pre-commit secret scan, README with the honest label, docs skeleton, COVERAGE.md mapping every capability in section 2 to a planned file with status "planned".
PHASE 1: Foundation. Gateway (mock + local provider + routing config), lever registry with schema validation and scope/approval enforcement and dry-run, hash-chained audit with verifier CLI, identity and per-client scoping. Proof tests: cross-client access refused; tampered audit log detected; dry-run changes nothing; a model asking for an unregistered or out-of-scope lever is denied and logged.
PHASE 2: Service desk. Triage (category, priority, queue, duplicate detection), summaries, draft replies from KB with citations, KB article drafts from resolved tickets, SLA breach watch, alert grouping. Read-only suggestions; technician accepts or corrects; corrections are stored as eval data. 200+ synthetic tickets with labels.
PHASE 3: Identity operations in PowerShell. Onboarding, offboarding, password reset with verification, license and group changes, as levers with dry-run diffs and approval gates. Graph/Entra mock first with tests. A real Microsoft Graph adapter stays behind a flag and is only ever tested against a test tenant.
PHASE 4: Security and compliance. Tenant baseline drift check (Conditional Access, MFA, admin roles, Defender/Intune baselines as data), quarterly admin access review, scheduled SOC 2 evidence collector producing a dated, hashed bundle, Copilot-readiness assessment (oversharing, labels, permissions, score), alert enrichment and triage summaries.
PHASE 5: RAG. Ingest synthetic runbooks and KB per client; isolation enforced at retrieval; citations; refusal when no source; evals for groundedness, refusal and leakage (client A must never see client B).
PHASE 6: Reports and account-manager outputs. Monthly client health report and QBR draft from fixtures; validator scripts that gate output (every number reconciles to source data); renewal and license alerts; weekly "what we did for you" digest; Power BI-ready exports; client AI-policy starter generator.
PHASE 7: Evals and hardening. Prompt-injection corpus (hidden instructions in tickets, emails, documents, tool output) with pass/fail report; routing evals comparing small vs strong models on the golden sets; cost, latency and accuracy table that sets escalation thresholds; load and failure tests; idempotency and retry behavior on write levers.
PHASE 8: Azure and DevOps as code. Bicep modules (Functions, Logic App, Automation Account, Key Vault, managed identities, Log Analytics), pipeline definitions, branching and release docs, monitoring dashboard spec. Validate only.
PHASE 9: Integrations and MCP. MCP server exposing approved levers with scope enforcement and security checks; Teams technician-assistant flow with approval cards (mocked); Outlook digest drafts; SharePoint KB ingestion (mocked). Document real-adapter steps.
PHASE 10: Governance pack and stakeholder materials. Complete `governance/` including DLP mapping (what may enter a prompt), SOC 2 control mapping table, risk register, AI incident response, new-use-case intake and scoring; ROI tracker (fixture-based); tech radar with adoption recommendations; one-page explainer for non-technical staff; one-page client data-handling summary; leadership brief ranking automations by ROI and risk; 30/60/90 plan.
PHASE 11: Packaging. A demo with seeded synthetic data, a 5-minute demo script, final README with diagrams, design tradeoffs, honest limitations, and "adapting this to a real MSP". Final COVERAGE.md audit.

---------------------------------------------------------------------
## 9. QUALITY BAR
- Boring, small, well-tested code. No framework sprawl. No dead code or fake features.
- Every lever: typed schema, tests, dry-run, audit, docs.
- Every workflow: eval set and a measured (fixture-based) result.
- Everything runs offline by default with the mock provider; local model optional; hosted models only by explicit config.
- Docs written for a technician who has never seen the repo.
