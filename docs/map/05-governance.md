# 05 Governance, risk and compliance map

Status: **document-only** (mapping stage, 2026-10-20). No code was written for this document. Each control has a stable id (`C-nn`) in `map/controls.json`, with an honest `implemented_in` (a repo path that exists today, `partial: <path>`, or `planned`).

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only. Nothing here is legal advice or a compliance attestation; every regulatory statement is a map for the MSP's compliance owner and counsel to confirm.

## 0. How to read this map

The MSP setting this maps to: 50 to 500 client tenants, thousands of end users, many technicians, an MSP assumed to be SOC 2 Type II audited (an assumption, not a fact about any real MSP; see `docs/UNVERIFIED.md` U-01).

Every rule is traced at four levels, because an automation that is safe "on average" can still end one person's working day:

| Level | Id | Who | What a failure costs them |
|---|---|---|---|
| L1 Individual | `L1` | one end user at one client (the dental office manager, the financial advisor) | locked out, data exposed, a day of work lost |
| L2 Client business | `L2` | the client tenant (Contoso Dental, Fabrikam Capital) | regulatory breach, lost patients or customers, fines |
| L3 MSP | `L3` | The MSP, its technicians and leads | audit exceptions, liability as a business associate or service provider, trust |
| L4 Community | `L4` | patients, investors, the Denver-area small business base | harm spread across many tenants at once |

Ids used in this document (other map documents may reference them):

| Prefix | Meaning | Section |
|---|---|---|
| `DC-n` | data class | 1 |
| `ISO-n` | per-client isolation rule | 2 |
| `BA-n` | HIPAA business associate obligation | 3 |
| `GLBA-n` | GLBA / FTC Safeguards obligation | 3 |
| `R0`-`R3` | lever risk class | 6 |
| `HO-n` | human oversight rule | 6 |
| `AIR-n` | AI-specific risk | 5 |
| `IR-n` | wrong-action incident step | 7 |
| `CM-n` | lever change-management rule | 8 |
| `EU-n` | commitment to the end user | 9 |
| `C-nn` | control (`map/controls.json`) | throughout |
| `GQ-nn` | open question for the owner or the MSP (governance; `OQ-nn` ids belong to map 03) | 11 |

Status words follow `docs/COVERAGE.md`: **built** = real code with passing tests on fixtures; **partial** = some of it is built and the rest is named; **planned** = not started. "Built" never means "proven against a real tenant".

---

## 1. Data classification for MSP AI work

An MSP touches four families of data at once: its own operational data, each client's business data, each client's regulated data, and the keys to all of it. The class decides what may enter a prompt, a log, a retrieval index or a hosted model.

| Id | Class | Examples in MSP work | Governing rule (verify with counsel) | May enter a local model prompt? | May enter a hosted model prompt? | May enter the audit log? |
|---|---|---|---|---|---|---|
| `DC-0` | Public | published KB articles, vendor docs | none | yes | yes | yes |
| `DC-1` | MSP internal | runbooks, lever code, ticket categories, technician names | MSP policy, SOC 2 confidentiality | yes | yes, with an approved provider (C-28) | yes |
| `DC-2` | Client confidential | client network diagrams, tenant config, device inventory, contract terms | client contract, SOC 2 C1.1 | yes, scoped to that client (ISO-1) | only with an approved provider and the client's data-handling setting (C-28) | identifiers only |
| `DC-3` | End-user PII | name, UPN, phone number, job title, sign-in times, IP addresses | state privacy and breach laws (for example Colorado C.R.S. 6-1-716, unverified here), client contract | minimum necessary, scoped to that client | redacted by default (C-25) | identifiers needed for evidence (UPN, object id); never read results (D-017) |
| `DC-4` | PHI (dental and other healthcare clients) | patient names in tickets ("can't open Mrs. X's x-ray"), appointment exports, screenshots of practice software, email bodies | HIPAA Privacy, Security and Breach Notification Rules (45 CFR Parts 160 and 164) | only if the model host is covered (local machine under the MSP's BA safeguards), minimum necessary | **no**, unless the provider has a signed BAA for that exact service and configuration (BA-3) | **never**; tokenised reference only |
| `DC-5` | NPI / customer information (financial clients: RIAs, accountants, lenders) | account numbers, SSNs, balances, tax documents, loan files | GLBA; FTC Safeguards Rule (16 CFR Part 314) for non-bank financial institutions; SEC Regulation S-P for RIAs/broker-dealers (unverified applicability per client) | minimum necessary, scoped | **no** by default; only with provider due diligence and contract terms (GLBA-3) | **never** |
| `DC-6` | Credentials and secrets | passwords, MFA seeds, API keys, app secrets, certificates, refresh tokens, BitLocker keys, break-glass credentials | every framework; an MSP credential is a key to many tenants (CISA AA22-131A) | **never** | **never** | **never** (redacted, C-10) |

Rules that follow from the table:

1. **Unknown is high.** Text whose class is not known (a ticket body, an attachment, an email) is treated as `DC-4`/`DC-5` until a classifier or a human says otherwise. Ticket text is already treated as untrusted for injection (C-12); it must also be treated as possibly regulated for disclosure.
2. **The class of a ticket is the highest class of anything in it.** One SSN in a printer ticket makes the whole ticket `DC-5`.
3. **The tenant's industry sets the floor.** A dental tenant's free text defaults to `DC-4`; a financial tenant's to `DC-5`. This is a per-tenant setting (C-25, planned), not a model judgement.
4. **Secrets never leave a vault.** A lever that needs a credential gets it from Key Vault through a managed identity at run time; the model never sees it, and no parameter schema may accept one (C-10 redacts by key name and value shape as a backstop, not as the control).
5. **Logs carry identifiers, not content.** The audit log records who, which client, which lever, which target and the diff of state changed. It does not record read results (D-017) or ticket bodies.

Current repo state: classification is implicit. The data are synthetic, read results stay out of the audit log, secrets are redacted (C-10), and hosted providers are off (C-15). There is no class tag on data, no per-tenant industry floor and no pre-prompt redaction yet (C-25, planned).

---

## 2. Per-client isolation for AI

At 50 to 500 tenants, the most likely serious AI failure is not a rogue agent; it is one client's data appearing in another client's answer. Isolation must hold at every layer where data can rest or travel.

| Id | Layer | Rule | Status |
|---|---|---|---|
| `ISO-1` | Tool (levers) | every lever call names exactly one client; the caller's identity must be scoped to it and the lever must be enabled for it | **built**: `core/levers/runner.py`, `core/identity/store.py` (C-04) |
| `ISO-2` | Retrieval | retrieval filters by client id in the query layer (the index or the store), never by an instruction in the prompt; one index or namespace per tenant is preferred over a shared index with a filter | **partial**: `kb.search` only reads the client's own articles (test `test_p1_1_kb_search_only_sees_the_clients_own_articles`); real RAG is Phase 5 (C-26) |
| `ISO-3` | Prompt assembly | one model call carries data from one client only; batch jobs never mix tenants in one context window | **partial**: triage builds one prompt per ticket (`workflows/triage/triage.py`); no test asserts it (C-27) |
| `ISO-4` | Model context and memory | no conversation memory, cache or few-shot examples are shared across tenants; few-shot examples are synthetic or from the same tenant | planned (C-27) |
| `ISO-5` | Logs and traces | model prompts and outputs, if logged at all, are stored per tenant with the tenant's retention; the audit log is MSP evidence and any export to a client is filtered to that client | **partial**: audit records carry a `client` field; one shared file today; per-client export planned (C-27, C-39) |
| `ISO-6` | Error text | an error message never echoes another tenant's data (for example "user X not found in tenant Y") | **partial**: runner reasons name the requested client only; no test sweeps every message (C-27) |
| `ISO-7` | Fine-tuning and evaluation data | no client data trains or tunes a shared model; eval corrections are stored per tenant and only synthetic sets are shared | **partial**: corrections are synthetic (`evals/triage/corrections.jsonl`); planned rule (C-27) |
| `ISO-8` | Hosted providers | a hosted provider is used per tenant only when that tenant's data-handling setting allows it; the provider must not retain or train on the data (C-28) | **built** as "off for everyone" (`config/models.json`, `core/gateway/hosted.py`); per-tenant setting planned |
| `ISO-9` | Approvers | an approver must be scoped to the same client as the action | **built**: `_check_approval` in `core/levers/runner.py` (C-06) |
| `ISO-10` | Delegated access | the MSP's access to each tenant is per-tenant and least privilege (GDAP roles, no standing Global Admin); a lever's client scope can never exceed the delegated access behind it | planned (C-38); documented in `docs/DEMO.md` week-one plan |

Proof standard: each `ISO` rule needs a negative test ("client A must never see client B", Blueprint Phase 5). Today `ISO-1` and `ISO-9` have them (`test_p1_1_cross_client_refused`, `test_p1_5_approver_must_be_scoped_to_the_client`, `test_sa2_a_user_from_the_other_client_is_refused_even_when_nothing_is_flagged`).

---

## 3. Regulatory obligations the MSP inherits

### 3.1 HIPAA: the MSP as a business associate (dental clients)

When a dental practice (a covered entity) has an MSP manage systems that create, receive, maintain or transmit ePHI, the MSP is a **business associate** (45 CFR 160.103). HHS's cloud guidance says a provider holding ePHI is a business associate even when it holds only encrypted data without the key. Any AI provider the MSP sends ePHI to is in turn a **subcontractor business associate** of the MSP.

| Id | Obligation | Source | What it means for AI automation |
|---|---|---|---|
| `BA-1` | Signed BAA between client and MSP | 45 CFR 164.502(e), 164.504(e) | The MSP's existing BAAs (assumed; GQ-03) define what the MSP may do with PHI. AI use must fit inside them, or the BAA must be updated. |
| `BA-2` | Security Rule safeguards apply directly to the BA | 45 CFR 164.302-318 (direct liability since the 2013 Omnibus Rule) | access control (164.312(a)), audit controls (164.312(b)), integrity (164.312(c)), person or entity authentication (164.312(d)), risk analysis (164.308(a)(1)) cover the AI system too. |
| `BA-3` | Subcontractor BAA before any PHI reaches an AI provider | 45 CFR 164.502(e)(1)(ii), 164.308(b)(2) | No PHI to a hosted model without a BAA covering **that service in that configuration**. Examples to verify, not assume: Anthropic offers a BAA for HIPAA-ready API configurations, and for its coding-agent product only with Zero Data Retention enabled; web search is excluded. Azure OpenAI is generally listed under Microsoft's HIPAA BAA, but whether abuse-monitoring storage and human review are covered is not settled in public documentation. |
| `BA-4` | Minimum necessary | 45 CFR 164.502(b) | Prompts include only the fields the task needs; triage needs the category, not the patient's name (C-25). |
| `BA-5` | Report security incidents and breaches to the covered entity | 45 CFR 164.314(a)(2)(i)(C), 164.410 (BA notifies the covered entity without unreasonable delay, no later than 60 days after discovery) | A wrong automated action that exposes PHI is a possible breach; the IR flow (section 7) must reach the client's privacy officer quickly. The 60 days is an outer limit; the BAA may set shorter. |
| `BA-6` | Documentation retention | 45 CFR 164.316(b)(2)(i) (6 years) | Policies, risk analyses and incident records about AI use are retained; the audit chain is part of that evidence (C-39). |
| `BA-7` | PHI also lives outside the prompt | HHS cloud guidance (by analogy; no HHS generative-AI guidance found) | vector stores, caches, logs, model outputs and eval sets that contain PHI are ePHI at rest and need the same safeguards and the same BAA coverage. |

Pending change: HHS proposed a Security Rule overhaul (NPRM published 2025-01-06: encryption and MFA mandatory, asset inventory, annual testing). Trade press reports the final rule moved to the long-term agenda (July 2027); **unverified on reginfo.gov**. Design to the proposed rule anyway: the repo's controls already assume MFA and encryption.

### 3.2 GLBA and the FTC Safeguards Rule (financial clients)

Non-bank financial institutions (tax preparers, mortgage brokers, some advisers; applicability per client is for counsel) must run an information security program under 16 CFR Part 314. The MSP is a **service provider** they must oversee, so the MSP's AI controls become evidence in the client's program.

| Id | Requirement (16 CFR 314.4) | AI automation mapping |
|---|---|---|
| `GLBA-1` | (c)(1) access controls, least privilege; (c)(5) MFA for anyone accessing customer information | lever roles and client scope (C-03, C-04); approver authentication (C-44, planned) |
| `GLBA-2` | (c)(2) data and system inventory | the lever registry is an inventory of automated actions; data classes per tenant (C-25) |
| `GLBA-3` | (f) oversee service providers: select capable ones, require safeguards by contract, assess periodically | the MSP's own AI providers are the client's fourth parties; C-43 vendor register and C-28 approval |
| `GLBA-4` | (c)(7) change management | lever change management (section 8, C-37) |
| `GLBA-5` | (c)(8) monitor and log activity of authorized users | audit chain (C-08), monitoring (C-40) |
| `GLBA-6` | (h) written incident response plan | section 7, C-34 |
| `GLBA-7` | (j) notify the FTC within 30 days of discovering a notification event involving unencrypted information of 500 or more consumers (effective May 2024; sources differ on May 11 vs May 13) | the client files; the MSP must tell the client fast enough that it can (C-35) |

RIAs and broker-dealers fall under SEC Regulation S-P instead (amended 2024 with incident-response and service-provider notice requirements); **unverified here**, ask counsel (GQ-06).

### 3.3 SOC 2: what the audit chain and approvals give evidence for

The AICPA 2017 Trust Services Criteria (points of focus revised 2022). The repo produces evidence for the MSP's own SOC 2 report, not for any client attestation.

| Criterion | What the auditor asks | Evidence this repo produces | Controls | Status |
|---|---|---|---|---|
| CC6.1 logical access | access to systems is restricted to authorised users | every lever call checked for role, client, lever scope; denials recorded | C-01, C-03, C-04 | built (fixtures) |
| CC6.2 / CC6.3 provisioning, least privilege, removal | access is granted, changed and removed by an approved process | `config/identities.json` is the identity list; quarterly agent access review | C-03, C-38 | partial |
| CC6.6 / CC6.7 boundaries and transmission | data leaving the boundary is restricted | gateway loopback-only; hosted adapters off | C-15, C-28 | built (off-by-default) |
| CC7.2 monitoring for anomalies | the entity monitors components for anomalies | audit records of denials; alerting planned | C-08, C-40 | partial |
| CC7.3 / CC7.4 / CC7.5 incident evaluation, response, recovery | incidents are evaluated, responded to, recovered from | wrong-action runbook, diff-based rollback | C-33, C-34 | planned |
| CC8.1 change management | changes are authorised, designed, tested, approved, implemented | PR review, CI green, approver recorded, pilot tenant first | C-24, C-37 | partial |
| CC9.2 vendor risk | vendors are assessed | AI provider register with BAA/ZDR status | C-43 | planned |
| PI1.2-PI1.4 processing integrity (if in scope) | inputs, processing and outputs are complete and accurate | schema validation, dry-run diff equals execute diff, summary reconciliation | C-02, C-05, C-21 | built (fixtures) |
| C1.1 / C1.2 confidentiality | confidential information is protected and disposed of | data classes, redaction, isolation | C-10, C-25, C-27 | partial |

The audit chain (C-08) is the main artefact: one record per lever call (allowed or denied) with agent, client, lever, redacted params, mode, result, approver and time; SHA-256 chained with a head pin; `python -m core.audit.verify` proves it intact. Known limit (THREAT_MODEL limit 4): whoever can rewrite both the log and its head file can forge it, so production needs the head pinned to write-once storage (C-39).

### 3.4 Framework mapping of the automations (NIST CSF 2.0, CIS Controls v8.1)

Subcategory ids are from NIST CSWP 29 (CSF 2.0, February 2024) and CIS Controls v8.1 safeguard numbers as I recall them; **verify each id against the published documents before an auditor sees this table**.

| Automation | Risk class | NIST CSF 2.0 | CIS v8.1 | Main controls |
|---|---|---|---|---|
| `ticket.get` (read a ticket) | R0 | PR.AA-05, PR.PS-04 | 6.8, 8.2 | C-01, C-04, C-08 |
| `kb.search` (client KB) | R0 | PR.AA-05, PR.DS-10 | 3.3, 6.8 | C-04, C-26 |
| Ticket triage (`workflows/triage`) | R0 proposal, R1/R2 lever proposed | DE.AE-02, PR.AA-05, ID.RA-01 | 16.1, 6.8 | C-12, C-13, C-14 |
| Tenant baseline check (`TenantBaseline`) | R0 | ID.RA-01, ID.AM-07, DE.CM-09, GV.OV-02 | 4.1, 5.4, 6.3, 6.5 | C-20, C-21 |
| `user.reset-mfa` | R3 (D-024, D6-07) | PR.AA-01, PR.AA-03, RS.MI-01 | 6.3, 6.5 | C-05, C-06, C-07, C-30 |
| `user.disable` | R3 (D-024, D6-07) | PR.AA-01, PR.AA-05, RS.MI-01 | 6.2 | C-05, C-06, C-07, C-32 |
| Approval queue (`core/queue`, `ui`) | governs R1-R3 | GV.RR-02, PR.AA-05 (separation of duties) | 6.1, 6.8 | C-06, C-07, C-19 |
| Audit chain (`core/audit`) | all | PR.PS-04, DE.CM-03, GV.OV-03 | 8.2, 8.5, 8.9, 8.11 | C-08, C-09, C-39 |
| Model gateway (`core/gateway`) | all | PR.DS-02, GV.SC-05, GV.SC-07 | 3.12, 15.4 | C-15, C-16, C-28 |
| Planned: onboarding/offboarding, license and group changes | R1-R3 | PR.AA-01, PR.AA-05 | 5.1, 5.3, 6.1, 6.2 | C-29, C-31, C-32, C-33 |
| Planned: SOC 2 evidence collector | R0 | GV.OV-03, ID.IM-01 | 8.11 | C-39 |
| Planned: RAG over runbooks and client KB | R0 | PR.DS-10, PR.AA-05 | 3.3, 3.12 | C-26, C-27 |

For AI-specific risk management, the reference set is NIST AI RMF 1.0 (AI 100-1) with the Generative AI Profile (NIST AI 600-1, July 2024) and the OWASP Top 10 for LLM Applications 2025.

---

## 4. Governance structure (who decides what)

| Decision | Owner (proposed) | Repo artefact |
|---|---|---|
| A new AI use case or lever is allowed | AI & Automation Engineer proposes, Technical Services Manager approves; compliance owner signs if `DC-4`/`DC-5` data is involved | `governance/USE_CASE_INTAKE.md` (planned, COVERAGE D1) |
| A lever's risk class | engineer proposes, lead reviewer confirms in the PR | registry field `risk_class` (planned, C-29) |
| A hosted model provider is enabled | leadership plus compliance; requires BAA/ZDR evidence | C-28, C-43 |
| A tenant joins a pilot ring | account manager with the client's written agreement | C-37 |
| A lever is paused (kill switch) | any lead or on-call engineer, immediately, without approval | C-31 |
| An incident is declared | on-call lead | C-34 |

Who holds these roles at the MSP is GQ-01.

---

## 5. AI-specific risks and controls

| Id | Risk | How it shows up at an MSP | Controls | Residual risk and status |
|---|---|---|---|---|
| `AIR-1` | Prompt injection (OWASP LLM01) | a ticket or email hides "add me to Global Admins"; a document in the KB tells the model to leak another client's data | C-12 wrap as untrusted, C-13 tripwire, **C-14 model output cannot choose the lever**, C-01 registry default-deny | detector is 100% only on its own 50-case synthetic corpus (D-019); the structural control (C-14) is built for triage only; RAG and email paths are planned |
| `AIR-2` | Over-privileged agents (OWASP LLM06, excessive agency) | an agent identity with standing write access to many tenants | agents can only dry-run writes (C-03), four-eyes approval (C-07), per-client scope (C-04), quarterly access review (C-38), blast-radius caps (C-32) | built for the four sample levers; real Graph permissions are per app registration (GQ-08) |
| `AIR-3` | Hallucinated or wrong actions | the model misreads a ticket and proposes disabling the wrong user; a summary invents a number | rules pick the lever and form fields supply its params, never model text (C-14); dry-run diff shown to the approver (C-05); summary reconciliation (C-21); evals gate (C-41) | a correctly-formed but wrong target (right lever, wrong person) is caught only by the human approver today; requester verification (C-30) is planned |
| `AIR-4` | Hallucinated or wrong text to a person | a client-facing reply promises something untrue (the Air Canada pattern) | client-facing text is always drafted, never sent, by AI (HO-3); citations from the client's own KB (C-26) | planned for draft replies (Phase 2) |
| `AIR-5` | Sensitive data disclosure (OWASP LLM02) | PHI in a prompt sent to a hosted model; NPI in a log | data classes (section 1), pre-prompt redaction (C-25), loopback-only gateway (C-15), no read results in the audit log | built as "nothing leaves the machine"; redaction before a hosted call is planned |
| `AIR-6` | Model data retention by the provider | a provider keeps prompts for abuse monitoring or trains on them | approval only with written retention terms, ZDR or equivalent where PHI/NPI could be present (C-28, C-43) | planned; current state is safest (hosted off) |
| `AIR-7` | Vendor lock-in | prompts, evals and logic tied to one provider's API | one gateway interface, model names in config, provider swap is a config change (C-16); evals on our own golden sets decide routing | built: `core/gateway`, `config/routing.json` |
| `AIR-8` | Cross-tenant leakage through the model | shared memory or few-shot examples bleed client A into client B | ISO-3, ISO-4, ISO-7 (C-27) | planned beyond the per-ticket prompt |
| `AIR-9` | Runaway loops and cost | an agent retries a failing lever across 300 tenants | timeouts (C-17), idempotency (C-18), kill switch and rate caps (C-31, C-32) | timeouts and idempotency built; caps planned |
| `AIR-10` | Unauthenticated or rubber-stamp approvals | approvers click through a long queue; the demo sign-in is an identity picker | approval bound to exact lever/client/params (C-06), diff shown, Entra sign-in for approvers (C-44), approval-volume monitoring (C-40) | binding built; authentication planned (D-023 known gap) |
| `AIR-11` | Help-desk social engineering | a caller impersonates a user to get an MFA reset (the pattern behind well-known 2023 casino breaches; the CISA and FBI advisory AA23-320A on Scattered Spider describes help-desk MFA-reset social engineering, see Sources) | requester identity verification before an R2 identity lever (C-30) | planned; today only the lead approval stands in the way |
| `AIR-12` | Supply chain of the AI stack | a compromised MCP server, model file or package | default-deny tools in the build workshop (C-22), pinned CI actions (C-24), vetted MCP only (Phase 9) | partial |

---

## 6. Risk classes and human oversight

### 6.1 Risk classes

Every lever gets exactly one class, set in its registry entry and reviewed in the PR that adds it. Classes are about the effect on a person and a business, not about technical difficulty.

| Class | Definition | Examples | Current levers |
|---|---|---|---|
| `R0` Read | reads data; changes nothing; output goes to MSP staff | get a ticket, KB search, baseline check, evidence collection | `ticket.get`, `kb.search`, `TenantBaseline` |
| `R1` Reversible, low impact | changes state for one user or one object; fully reversible by a lever; the person can keep working | add a user to a distribution list, assign a license from free stock, reset a forgotten password with verified identity | none yet |
| `R2` Reversible, high impact | reversible, but it affects a person's access, security or ability to work, or affects several users | remove a license, change group membership that grants data access, revoke sessions | none yet (`user.reset-mfa` and `user.disable` moved to R3 by D-024 and D6-07) |
| `R3` Irreversible, broad, or identity access | cannot be undone by a lever (or only from backup), or affects a whole tenant or many tenants; or, by D-024 and D6-07, changes how a person proves who they are or whether they can sign in (MFA or authentication-method reset, TAP, password reset, contact-detail change, disable, privileged-role change) | delete a mailbox or user past soft-delete, wipe a device, change a tenant-wide Conditional Access policy, bulk operations across tenants, anything touching `DC-6` secrets, reset MFA, disable a user | `user.reset-mfa`, `user.disable` (dual approval is enforced by the runner under a policy, `B-28`, and collected on the approval page, D-067; the offline CLIs still take one approval; reversible containment may use the pre-authorized path of D6-08); any new irreversible lever is out of scope until C-29, C-31, C-32, C-33 exist |

### 6.2 Oversight rules by class

| Rule | R0 | R1 | R2 | R3 |
|---|---|---|---|---|
| `HO-1` Who may run it | agent or technician | technician (agent may dry-run only) | technician (agent may dry-run only) | senior engineer, named per change |
| `HO-2` Dry-run first | n/a | required, diff stored | required, diff shown to approver | required, plus a written change plan |
| `HO-3` Approval | none | lead, or pre-approved standard change for that lever and tenant | lead for the same client, never the requester (four-eyes) | two approvers: two distinct leads scoped to the client, neither the requester nor an agent; a client may require one of them to be the Technical Services Manager (D6-05); plus the client's named contact for tenant-wide changes |
| `HO-4` Requester verification | n/a | ticket from a known contact | verified identity of the affected person or their manager by an out-of-band channel (callback to number on file) | written client request |
| `HO-5` Autonomy | may run unattended | may run unattended **only** after 30 days of shadow mode with no correction on that tenant and an eval gate (C-41) | never unattended | never unattended |
| `HO-6` Blast radius | n/a | max targets per run set per lever | one target per approval | one change window, one tenant at a time unless approved in writing |
| `HO-7` Rollback ready | n/a | undo lever exists and is tested | undo lever or documented manual undo, tested in a test tenant | backup verified before the change |
| `HO-8` Person affected is told | n/a | in the ticket reply | before or at the moment of the change, with how to get back (EU-1, EU-2) | client notified in advance |
| `HO-9` Client-facing text | AI drafts only; a human sends | same | same | same |

Today the registry has `approval: none | lead`; both write levers require a lead and an agent cannot execute either (C-03, C-06, C-07 built). The `risk_class` field, R1 standard-change pre-approval, R3 dual approval, HO-4 verification and HO-6 caps were planned here (C-29, C-30, C-32); since then `risk_class` (B-01), HO-4 verification (B-02, B-03), caps (B-42) and R3 dual approval in the runner, queue and page (B-28, D-067) are built.

---

## 7. Incident response for a wrong automated action

A wrong action is any lever execution that hit the wrong target, did the wrong thing, ran when it should not have, or ran in the wrong tenant, whether or not the model was involved. It is handled as a security incident until shown otherwise, because at a regulated client a wrong action can also be a breach.

| Step | Id | What happens | Who | Evidence and controls |
|---|---|---|---|---|
| Detect | `IR-1` | any of: the affected person reports it (EU-2 fast path); a technician spots it; monitoring alerts on unusual volume, denials or after-hours executes; the audit verifier fails | anyone | C-08, C-36, C-40 |
| Contain | `IR-2` | pause the lever globally or for that tenant (kill switch); no approval needed to pause | on-call lead | C-31 |
| Restore the person first | `IR-3` | put the affected user back to work before root cause: re-enable the account, re-register MFA, restore the license, using the before-state in the audit diff | technician on call | C-33 (audit records the changed fields before and after today; an undo lever is planned) |
| Scope | `IR-4` | query the audit chain for every execute of that lever in the window, across all tenants; verify the chain first | engineer | C-08, C-39 |
| Assess regulatory impact | `IR-5` | was PHI or NPI exposed or made unavailable? if yes, this is a possible HIPAA breach or Safeguards notification event; hand to the compliance owner | compliance owner | BA-5, GLBA-7 |
| Notify | `IR-6` | the affected person (plain words, what happened, what we fixed); the client's primary contact the same business day; the client's privacy or security officer when regulated data may be involved, early enough for their own deadlines (HIPAA 60-day outer limit; FTC 30 days; state laws; contract terms may be shorter) | account manager plus lead | C-35 |
| Fix | `IR-7` | fix the lever, rule or prompt through normal change management (section 8); add the case to the eval set so it can never pass again | engineer | C-37, C-41 |
| Review | `IR-8` | blameless review within five business days; record in the risk register; report trends to leadership | AI & Automation Engineer | C-34 |
| Re-enable | `IR-9` | lever comes back on the pilot tenant first, then rings (CM-5) | lead | C-37 |

Status: the audit evidence for IR-3 and IR-4 is built (the record carries the changes and the approver). The runbook, kill switch, undo levers, notification templates and alerting are planned (`docs/RUNBOOKS.md` lists "AI incident response" as planned).

---

## 8. Change management for levers

A lever is production code that acts on client tenants. It changes like production code.

| Id | Rule | Status |
|---|---|---|
| `CM-1` | Every lever change (code, schema, registry entry, prompt, routing threshold) arrives as a pull request with tests; a reviewer other than the author approves | partial: PRs and CI green before merge (D-021); single-person repo today, so the second reviewer is the owner, not an independent human |
| `CM-2` | CI must pass: unit and acceptance tests, lint, types, secret scan, and the lever's own eval set | partial: `.github/workflows/ci.yml` runs Phase 0, Phase 1 and Slice B suites; no eval threshold gate yet (C-41) |
| `CM-3` | Each lever carries its own semantic version, risk class and owner; the audit record names the version that ran | planned: registry has one file-level `version` (C-29, C-37) |
| `CM-4` | A change that raises the risk class, widens the parameter schema, or adds a tenant scope needs the approvals for the new class | planned |
| `CM-5` | Staged rollout: test tenant, then one pilot client tenant (with that client's agreement), then 10% of tenants, then all; each stage holds for a set time with no wrong-action incidents and acceptable correction rates | planned |
| `CM-6` | Every rollout has a rollback: the previous lever version stays registered and can be pinned per tenant | planned |
| `CM-7` | Emergency changes (fixing an active incident) may skip staging but not review; they are reviewed again within two business days | planned |
| `CM-8` | Guardrail and policy code is human-only to edit | partial: `scripts/` and `.github/` are CODEOWNERS-protected (owner review); there is no integrity manifest in the public repository |

---

## 9. What the end users are owed

The people at the MSP's clients did not choose the MSP's AI. A receptionist locked out on a Monday cannot see patients; an advisor locked out on a trading day cannot serve clients. These commitments are the end-user side of every control above.

| Id | Commitment | How the system keeps it | Status |
|---|---|---|---|
| `EU-1` | **Clear communication.** When an automation changes your account, you hear about it from a human-readable message that says what changed, why, who approved it, and how to undo it. No jargon, no "the system did it". | notification template per lever (C-35); text drafted by AI, sent by a human (HO-9) | planned |
| `EU-2` | **A fast way back.** One phone number and one reply-to address that reach a person, prioritised as urgent for any automation-caused lockout, with a target to restore access within one business hour during support hours (target to agree with the MSP, GQ-09). | priority queue rule for "automation-affected" tickets; undo levers (C-33, C-36) | planned |
| `EU-3` | **Never locked out by a bot alone.** No automation disables, removes MFA from, or removes the license of a person without a named human approving it and a reason recorded. | R2 approval and four-eyes (C-06, C-07); agents cannot execute writes (C-03) | **built** for the two sample write levers (fixtures) |
| `EU-4` | **Verified before changed.** Your account is not changed because someone claimed to be you; the requester's identity is checked out of band for access-affecting changes. | C-30 | planned |
| `EU-5` | **No silent decisions about you.** Every action on your account is in a record your company can ask for, with the reason. | audit chain (C-08); per-client export (C-27) | partial |
| `EU-6` | **Your data stays with your company.** What you write in a ticket is not used to answer another company's tickets and is not sent to an outside AI service without your company's agreement. | ISO rules, C-15, C-28 | partial (hosted off; isolation proven for levers only) |
| `EU-7` | **A human when you ask.** You can always ask for a person instead of an automated reply. | service desk policy; AI drafts only | planned (policy) |
| `EU-8` | **Mistakes are owned.** If an automation gets it wrong, the MSP says so, fixes it for you first, and makes sure it cannot happen the same way again. | IR-3, IR-6, IR-7 | planned |

One trace, granular to macro, using the repo's own synthetic case (ticket T-3101, Priya Nair, Contoso Dental, phone lost; technician `tech-ana`):

| Level | What happens | Which rules |
|---|---|---|
| L1 | Priya cannot approve sign-ins. Triage proposes `user.reset-mfa` in dry-run. Before a lead approves, someone calls Priya back on the number on file (EU-4). After the reset she gets a plain message: "We removed your old phone from your sign-in methods; set up your new one at next sign-in; call this number if anything is wrong." | HO-2, HO-3, HO-4, EU-1, EU-2 |
| L2 | Contoso Dental's tenant sees one change, by a scoped technician, approved by a scoped lead; no PHI left the MSP; the record is available to the practice's HIPAA security officer. | ISO-1, ISO-9, BA-2, BA-4 |
| L3 | The MSP has a hash-chained record for its SOC 2 auditor: requester, approver, diff, time. | C-08, CC6.1, CC8.1 |
| L4 | The same help-desk social-engineering trick cannot be scaled across 300 dental and financial tenants, because every R2 identity change needs verification and a human. | AIR-11, HO-6 |

---

## 10. Implemented vs planned at a glance

From `map/controls.json` (45 controls): **built 22**, **partial 8**, **planned 15**. "Built" means real code with passing tests on synthetic fixtures; none has run against a real tenant. C-11 is in the code but counts as partial until a test proves read data stays out of the audit (planned in `B02-3`), and C-22's hooks are tested by script but not yet confirmed firing in a live session.

| Built (fixture-proven) | Partial | Planned |
|---|---|---|
| C-01 to C-10, C-12 to C-17, C-19 to C-24 | C-11, C-18, C-26, C-27, C-33, C-37, C-41, C-45 | C-25, C-28 to C-32, C-34 to C-36, C-38 to C-40, C-42 to C-44 |

The pattern is honest and expected for this stage: the controls that stop a bad action (registry, scope, approval, audit) are built; the controls that classify data, reach the affected person, and run the organisation around the code (notification, training, vendor register, rollout rings) are planned.

(Exact per-control status is in `map/controls.json`; this summary is derived from it.)

---

## 11. Open questions only the owner or the MSP can answer

| Id | Question | Why it matters |
|---|---|---|
| `GQ-01` | Who at the MSP owns compliance (HIPAA privacy/security officer role for the MSP, GLBA qualified individual support), and who approves new AI use cases today? **Decided: see 06-decisions.md D6-17.** | section 4 owners; IR-5 hand-off |
| `GQ-02` | Is there an existing AI acceptable-use policy or AI change process (their blog mentions "AI Change Management")? **Decided: see 06-decisions.md D6-17.** | adopt and extend rather than duplicate |
| `GQ-03` | Do the MSP's client BAAs and MSAs say anything about AI or subcontractors? Is there a standard subcontractor BAA? **Decided: see 06-decisions.md D6-11.** | BA-1, BA-3 |
| `GQ-04` | Which AI providers, if any, are already approved, and under what terms (Azure OpenAI under the Microsoft BAA, Copilot, Claude)? Is modified abuse monitoring or ZDR in place? **Decided: see 06-decisions.md D6-11.** | C-28, C-43, AIR-6 |
| `GQ-05` | Does the MSP want AI workloads in its own Azure tenant under existing Entra sign-in and logging? **Decided: see 06-decisions.md D6-11.** | C-44, C-39 |
| `GQ-06` | Which financial clients are under the FTC Safeguards Rule vs SEC Regulation S-P vs bank regulators? **Decided: see 06-decisions.md D6-12.** | GLBA-7 and notice timing |
| `GQ-07` | Which PSA and RMM are in use, and where do their own audit logs live? **Decided: see 06-decisions.md D6-01.** | IR-4 must join lever audit with PSA history |
| `GQ-08` | How is delegated access to client tenants set up (GDAP roles, per-tenant app registrations, standing admin)? **Decided: see 06-decisions.md D6-09.** | ISO-10, AIR-2 |
| `GQ-09` | What restore-time target for automation-caused lockouts is realistic for the service desk? **Decided: see 06-decisions.md D6-20.** | EU-2 |
| `GQ-10` | Will any client agree to be a pilot tenant for staged rollout, and in which industry? **Decided: see 06-decisions.md D6-25.** | CM-5 |
| `GQ-11` | Does the SOC 2 scope include processing integrity or privacy criteria, or only security, availability and confidentiality? **Decided: see 06-decisions.md D6-18.** | section 3.3 evidence emphasis |
| `GQ-12` | Is the Colorado AI Act (SB 24-205, delayed to 2026-06-30 and reportedly reshaped since) relevant to any client use, or is MSP operations automation clearly outside "consequential decisions"? Current status unverified. **Decided: see 06-decisions.md D6-19.** | regulatory scope |
| `GQ-13` (the owner) | Repo publishing and license remain the owner's decision (D-008); a public repo should still say "synthetic data only" on every governance page. **the owner's call: see 06-decisions.md J-01** (recommendation there). | honesty labels |

---

## Sources

Regulatory and framework (primary where possible):
- HHS, HIPAA and cloud computing guidance: https://www.hhs.gov/hipaa/for-professionals/special-topics/cloud-computing
- HHS, business associates: https://www.hhs.gov/hipaa/for-professionals/privacy/guidance/business-associates/index.html
- 45 CFR Parts 160 and 164 (eCFR): https://www.ecfr.gov/current/title-45/subtitle-A/subchapter-C
- HIPAA Security Rule NPRM status (secondary, unverified on reginfo.gov): https://www.fiercehealthcare.com/health-tech/feds-push-back-hipaa-security-rule-overhaul-july-2027
- FTC Safeguards Rule, 16 CFR Part 314 (eCFR): https://www.ecfr.gov/current/title-16/chapter-I/subchapter-C/part-314
- FTC Safeguards Rule business guidance: https://www.ftc.gov/business-guidance/resources/ftc-safeguards-rule-what-your-business-needs-know
- FTC notification amendment summary (effective date differs by source): https://www.akingump.com/en/insights/blogs/ag-data-dive/ftc-requires-non-banking-financial-institutions-to-report-data-security-breaches
- AICPA Trust Services Criteria: https://www.aicpa-cima.com/resources/download/2017-trust-services-criteria-with-revised-points-of-focus-2022
- NIST CSF 2.0 (CSWP 29): https://www.nist.gov/cyberframework
- NIST AI RMF and Generative AI Profile (AI 600-1): https://www.nist.gov/itl/ai-risk-management-framework
- CIS Critical Security Controls v8.1: https://www.cisecurity.org/controls/v8-1
- CISA, protecting MSPs and their customers (AA22-131A): https://www.cisa.gov/news-events/cybersecurity-advisories/aa22-131a
- CISA and FBI, Scattered Spider advisory (AA23-320A; help-desk social engineering for password and MFA resets; added by the completeness pass, not re-fetched in this session): https://www.cisa.gov/news-events/cybersecurity-advisories/aa23-320a
- OWASP Top 10 for LLM Applications 2025: https://genai.owasp.org/llm-top-10/
- Colorado AI Act delay (secondary; post-June 2026 status unverified): https://www.gtlaw.com/en/insights/2025/9/colorado-delays-comprehensive-ai-law-with-further-changes-anticipated

AI provider terms (verify current terms in writing before relying on them):
- Anthropic, API and data retention: https://platform.claude.com/docs/en/manage-claude/api-and-data-retention
- Anthropic, BAA and HIPAA-ready services: https://privacy.claude.com/en/articles/8956058-i-need-to-be-hipaa-compliant-can-i-use-claude
- Azure OpenAI abuse-monitoring and BAA coverage question (Microsoft Q&A, not contractual): https://learn.microsoft.com/en-us/answers/questions/5941618/is-default-abuse-monitoring-for-azure-openai-(foun
- Microsoft Graph revokeSignInSessions (lag and guest limits): https://learn.microsoft.com/graph/api/user-revokesigninsessions

Repo sources: `docs/DECISIONS.md` (D-016 to D-023), `docs/THREAT_MODEL.md`, `docs/DEMO.md`, `specs/phase-1.md`, `specs/slices-abc.md`, `levers/registry.json`, `core/`, `tests/phase1/`.
