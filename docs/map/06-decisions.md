# 06 Decisions on the open questions

Status: **document-only** (decision pass, 2026-10-21). No code. This file closes every open question in the maps (`Q-` in 01, `IQ-` in 02, `OQ-` in 03, `RO-` in 04, `GQ-` in 05, `RQ-` in ROADMAP, `MQ-` in the index) with a decision a builder can act on, so no wave waits on an answer. The owner delegated the call ("do research and decide for the MSP or bridge gaps"). The few questions that are the owner's personal choices are not decided; they are in section 3 with a recommendation.

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only. The MSP assumptions come from a reference profile (`07-msp-profile.md`), not from any real company. An **assumed** fact is never treated as confirmed: every decision that rests on one says what would change it.

Ids in this file: decisions `D6-nn` and the owner's calls `J-nn`. They are stable, and other documents may cite them. The repo-wide summary is `D-025` in `docs/DECISIONS.md`.

**How a decision is built.** Each one has a basis, either an assumption about the reference MSP (labelled ASSUMED or UNKNOWN in `07-msp-profile.md`) or an industry default with its source. Each says what would make us revisit it, and which build items (`B-`) and controls (`C-`) it touches. "Hedged" means the source was read second-hand or from memory and must be checked before anyone quotes it.

**Default rule.** Where the MSP's practice is unknown, the prototype takes the stricter safe default and makes the value configurable per client, so the MSP can loosen it on evidence without code changes. Loosening needs a recorded the MSP decision; tightening never does.

---

## 1. Decisions at a glance

| Id | Decision (short) | Closes | Basis | Changes |
|---|---|---|---|---|
|  D6-01 | Build mock adapters shaped after Autotask (PSA), Datto RMM, IT Glue and Datto backup, behind vendor-neutral interfaces; CloudRadial is the client portal intake | Q-01, RQ-05 (products), OQ-01, GQ-07, IQ-05 (tools) | Assumption: a PSA, RMM, documentation tool, backup product and client portal of the common kinds; vendor names are generic examples (map 07 MP-10 to MP-16) | B-18, B-61, B-68, B-91  |
|  D6-02 | GitHub stays the prototype's home; Azure Boards and Pipelines are export targets; a monorepo is fine | RQ-05 (tracker), RO-05 | Assumption: GitHub first, with Azure DevOps a common alternative (map 07 MP-31) | B-09, B-86 (no change)  |
|  D6-03 | Plan for 200 tenants and 5,000 users; design to 500 tenants; every volume stays labelled an estimate; phases for gap items accepted | Q-02, Q-11, IQ-01 | industry default; the reference MSP is small (map 07 MP-04), hedged | none  |
|  D6-04 | Model tiers 1 to 3 plus an external 24/7 SOC/MDR; the program groups and enriches alerts, the SOC stays the responder | Q-03 | Assumption: 24/7 SOC/MDR is bought from third parties (map 07 MP-17, MP-18) | B-43  |
| D6-05 | R2: one human approver, not the requester. R3: two distinct human leads scoped to the client, never the requester, never an agent. Minimums can be raised per client, never lowered. Approvers must be authenticated; `B-89` moves to W2 | Q-04, RQ-06, OQ-08, RQ-12 | industry default (Intune Multi Admin Approval, SOC 2 CC8.1, ITIL change authority); D-024 | B-28, B-89, B-65; HO-3 |
| D6-06 | Callback to the number on file is the minimum recorded verification; MFA reset, TAP and contact-detail changes also need the client's authorized contact; privileged accounts are never reset on a phone call | Q-05, RQ-07 | industry default (CISA AA23-320A, Microsoft Verified ID help-desk guidance) | B-28, B-30, B-34 |
| D6-07 | Identity changes are R3 (confirms D-024); containment levers get the pre-authorized path of D6-08 | RQ-01, IQ-06, MQ-02 | D-024; industry default treats help-desk MFA reset as the main attack path | B-01, B-06; governance 6.1 |
| D6-08 | Time windows live in the runner (`B-42`), held on the client record; no window means refuse. Reversible containment (disable, revoke sessions, isolate) may run on one on-call approval when the client pre-authorized it, with a next-business-day second review. Wipe never | IQ-08, Q-10, RQ-13 | industry default (NIST SP 800-61r3, MDR pre-authorized runbooks, RMM and Intune maintenance windows) | B-42, B-62, B-65 |
|  D6-09 | GDAP with least-privileged roles and the Secure Application Model; no Global Admin; per-client app registrations only by documented exception | OQ-04, Q-08, GQ-08 | Assumption: the MSP is a Microsoft cloud partner, so GDAP applies (map 07 MP-02); Microsoft guidance | B-19, B-54, B-91  |
| D6-10 | One Key Vault per environment, client-named secrets; a per-client vault only where a contract requires it | OQ-09 | Microsoft Key Vault guidance (vault per app, environment, region) | B-85 |
|  D6-11 | Target hosting is the MSP's own Azure tenant; hosted models stay off; Azure OpenAI and Anthropic are registered as `pending`; every client defaults to `model_processing: none` | Q-06, RQ-10, OQ-06, GQ-03, GQ-04, GQ-05 | Assumption: the MSP's own Azure tenant, with hosted-model providers as generic examples (map 07 MP-31) | B-90, B-55  |
|  D6-12 | Each client record carries a `regimes` list set by the MSP's compliance owner, never by code; the financial floor (DC-5) also covers legal and accounting; add a Regulation S-P pack for investment advisers | OQ-05, GQ-06 | Assumption: financial-services clients bring GLBA, SEC, Reg S-P, FDIC, OCC, NCUA and FINRA duties; HIPAA applies to the dental demo client (map 07 MP-41) | B-52, B-55  |
|  D6-13 | Personas lean to the MSP's real verticals (financial, RIA, legal, accounting); Contoso Dental stays as the W1 demo client; "Woodgrove Legal" personas renamed Litware Legal | IQ-07, RO-04 | Assumption: financial, adviser, legal and accounting verticals (map 07 MP-40); D-024 | B-21  |
| D6-14 | Technician-to-client access is an explicit list per technician now, read from Entra security groups (one per client or pod) later | OQ-03 | industry default (GDAP role assignment to security groups) | B-03, B-18 |
| D6-15 | The PSA company record is the source of truth for client ids; a new client record is approved by a human service manager | OQ-02 | industry default | B-18, B-77 |
| D6-16 | Keep audit evidence 7 years by default, configurable per client; target store is immutable storage in the MSP's Azure tenant | OQ-07 | industry default; covers SEC 6-year books-and-records periods (hedged) | B-42, B-82, B-85 |
|  D6-17 | "Compliance owner" and "AI change approver" are roles on configuration, not names; the AI policy pack extends any process the MSP already has | GQ-01, GQ-02 | Assumption: the MSP may already run an AI change process (UNKNOWN) | B-92, B-93  |
|  D6-18 | Assume SOC 2 scope is security, availability and confidentiality; processing integrity and privacy are not claimed | GQ-11 | industry default for MSPs; no real MSP's SOC 2 status is claimed (U-01) | B-51, B-95  |
| D6-19 | MSP operations automation is treated as outside the Colorado AI Act's "consequential decisions"; any decision about a consumer's access to lending, housing, insurance, employment, healthcare, legal or education services stays on the never-automate list | GQ-12 | statute scope (hedged; post-June 2026 status unverified) | B-14, B-92 |
|  D6-20 | Restore target for a person locked out by an automation: one business hour during support hours (EU-2 as proposed) | IQ-04, GQ-09 | industry default; real SLA numbers UNKNOWN | B-04, B-41  |
|  D6-21 | Individual metric: time until the person can work again, from PSA timestamps plus a proposed `user confirmed working` field; CSAT from the CSAT tool | IQ-02 | Assumption: a CSAT tool and a PSA exist (map 07 MP-29, MP-10) | B-74  |
| D6-22 | Program position: hours saved move technicians up, not out; metrics never rank technicians. Written as a proposal for the MSP leadership | IQ-03 | industry practice (correction loops need trust); existing guard B74-3 | B-96, B-97 |
| D6-23 | Leverage scores (B x N x S) and the enabler exclusion are accepted as the planning basis until real PSA volumes exist | IQ-09 | judgment; re-score on data | none |
|  D6-24 | Backup is in scope; the read-only backup review `B-68` moves from W6 to W3 | RQ-08, Q-09, IQ-05 (scope), MQ-01 | Assumption: the MSP sells backup and DR (map 07 MP-15, MP-16) | B-68  |
| D6-25 | Staged rollout starts with one small financial-services pilot tenant and R0 levers only for 30 days | GQ-10 | industry default (ring rollout, CM-5) | none (C-37 rule) |
| D6-26 | Existing RMM scripts are listed read-only and never run by the program until vetted into the registry | Q-07 | industry default (CISA AA22-131A on MSP tooling) | B-61, B-62 |
| D6-27 | Approve moves M-04 and M-07 and kept-in-place K-01 to K-08 | RO-01 | repo hygiene | none (W3-X5, B-96) |
| D6-28 | Create labels and milestones in W1 (metadata only, no demo impact); the owner runs the `gh` commands | RO-03 | they do not touch demoed code | B-08 |
| D6-29 | CODEOWNERS uses roles: automation lead (`levers/`), compliance owner (`governance/`), security lead (`core/audit/`); the owner holds all three until the MSP names people | RO-06 | industry default | B-08 |
| D6-30 | No PowerShell function prefix; module-qualified Verb-Noun names | OQ-10 | STD-PS-2; avoids implying any affiliation | B-15 |
| D6-31 | Drift fixes DR-01 to DR-22 ship through their roadmap items (B-02, B-03, B-12, B-26 and the rest), never as separate work items; nothing visible changes after the demo freeze | OQ-12 | the build automation is paused; one owner per path per wave | none |
| D6-32 | W1 scope and cut line approved as written, including the visible demo changes; the W1 calendar follows the demo date (J-05) | RQ-02 | the W1 items are the demo story | B-01 to B-11 (no change) |

Every open id in the maps is in this table or in section 3. `OQ-1` and `OQ-13` in the index are old names for `GQ-` questions (SX-01), not open questions.

---

## 2. Decisions in full

### D6-01 First adapters follow the MSP's likely stack
- **Decision.** Keep every adapter interface vendor-neutral (PSA, RMM, documentation, backup, alerts), but shape the first mock of each after the product the MSP most likely runs: Autotask PSA (Companies, Contacts, Tickets, TicketNotes, Resources), Datto RMM (sites, devices, alerts, jobs, components), IT Glue (organizations, configurations, flexible assets, documents; passwords never ingested), Datto continuity and SaaS backup jobs (the Datto RMM and IT Glue entity names are UNVERIFIED: no vendor documentation was read for them). CloudRadial is modelled as a ticket-intake source next to email and phone. The PSA's own ticket history is where lever audit records are joined (by ticket id) for IR-4. Real implementations stay absent and fail closed.
- **Basis.** Generic vendor examples for each tool type (map 07 MP-10 to MP-16): an Autotask-class PSA, a Datto RMM-class RMM, an IT Glue-class documentation tool and appliance backup. A client portal is an intake source. No product is claimed to be in use at any real MSP.
- **Revisit when** the MSP confirms the products, the API editions and whether an automation identity may hold an API user (Autotask API users and Datto RMM API keys are per-account settings; UNVERIFIED, no source recorded).
- **Affects.** B-18 (B18-4), B-61 (B61-4), B-68 (B68-4), B-91; C-27, C-02, C-04.

### D6-02 GitHub now, Azure DevOps as export
- **Decision.** The prototype stays in GitHub (free, CI already wired, D-021). `B-09` already exports the roadmap as an Azure Boards CSV and `B-86` writes an Azure DevOps pipeline, so moving to Azure Repos after hire is a copy, not a rewrite. A monorepo is kept.
- **Basis.** Assumption: GitHub first, with Azure DevOps a common alternative at MSPs (map 07 MP-31).
- **Revisit when** the MSP asks for the work to live in their Azure DevOps organisation.
- **Affects.** B-09, B-86 (no acceptance change); C-24, C-37.

### D6-03 Planning scale
- **Decision.** Plan for 200 client tenants and 5,000 end users; design limits for 500 tenants (map 03). Every volume and minute estimate keeps its "estimate" label. The proposed phases for the gap items (Q-11) are accepted as the roadmap waves.
- **Basis.** Industry default for a small MSP (tens of staff, hedged). Real numbers are UNKNOWN.
- **Revisit when** the MSP shares tenant, user, endpoint and monthly ticket counts; then re-score map 02 Appendix A (D6-23) and the caps in B-42.
- **Affects.** none now; C-32 caps use these numbers.

### D6-04 Service desk tiers and the external SOC
- **Decision.** Model a tier 1 to 3 service desk and an external 24/7 SOC/MDR. Alert intake (`B-43`) groups and enriches alerts for the MSP's engineers; where the SOC already owns an alert, the group carries the SOC case id and says the SOC is the responder. The program never replaces or contradicts the SOC's containment.
- **Basis.** Assumption: the MSP buys 24/7 SOC monitoring and initial response from third parties (map 07 MP-17, MP-18, MP-19). Tier structure UNKNOWN.
- **Revisit when** the MSP describes its tiers, its NOC, and which alerts reach its own engineers versus the SOC.
- **Affects.** B-43 (B43-4); C-12, C-40.

### D6-05 Who approves, and proving who they are
- **Decision.** R1: a lead or a pre-approved standard change. R2: one human approver who is not the requester and holds the lead role for that client. R3: two distinct human leads scoped to the client, neither the requester, neither an agent (keeps `B28-3`). The minimum can be raised per lever or per client (for example "one approver must be the Technical Services Manager"), never lowered, and a lowered value fails the load (`B28-7`). Self-approval is never allowed. A "lead" is anyone holding the lead role for that client in configuration (service desk lead, senior engineer, Technical Services Manager), not a job title. Approvers must be authenticated: the design and mock-token part of `B-89` moves from W9 to W2, and `B-28` depends on it (`B28-6`), as D-024 already decided.
- **Basis.** Industry default: four-eyes with a different approver is the norm (Microsoft Intune Multi Admin Approval: a second admin must approve and cannot approve their own request); SOC 2 CC8.1 and ITIL change enablement expect a named change authority, usually the service desk lead or manager at an SMB MSP. Separation of duties is only evidence when the approver's identity is authenticated (SOC 2 CC6.1, CC8.1). The MSP's actual approvers UNKNOWN.
- **Revisit when** the MSP names its change authority; if it requires the Technical Services Manager on R3, that is a configuration value, not code.
- **Affects.** B-28 (B28-6, B28-7), B-89 (moved to W2), B-65; C-06, C-07, C-44. Governance HO-3 updated.

### D6-06 Verifying a caller
- **Decision.** Knowledge checks (date of birth, employee id, manager name) are not verification. The minimum recorded method for a standard password reset is a callback to the number already on file in the PSA or the client's records, never a number the caller gives; the record holds the method, the source of the number (never the number), who verified and when. MFA reset, Temporary Access Pass, authentication-method changes and changes to the phone or email on file also need confirmation from the client's authorized contact (`B-34` supplies the evidence; a human records it). Accounts holding a privileged directory role are never reset from a phone request; that stays a human-only procedure. Verified ID with Face Check is a later option where licensed.
- **Basis.** Industry default: CISA AA23-320A (revised 2025-07-29) describes help-desk impersonation to reset passwords and move MFA, including abuse of contracted help desks; Microsoft's help-desk Verified ID guidance says knowledge checks no longer stop these attackers. The MSP's current procedure UNKNOWN.
- **Revisit when** the MSP shares its verification procedure; a stronger one (for example Verified ID) replaces the second record, a weaker one does not lower it.
- **Affects.** B-28 (B28-8), B-30 (B30-4), B-34, B-02 and B-03 (W1 wording unchanged: callback-on-file is already the recorded method); C-30.

### D6-07 Identity changes are R3
- **Decision.** Confirms D-024: MFA reset, TAP, password reset, authentication-method and contact-detail changes, disable and privileged-role changes are R3. Governance section 6.1 now lists `user.reset-mfa` and `user.disable` as R3, so the inventory and governance agree and `B-06`'s mismatch warning has nothing to report for these. The speed cost on containment is handled by D6-08, not by lowering the class.
- **Basis.** D-024; industry default treats help-desk MFA reset as the main attacker entry (CISA AA23-320A). The research default (password reset R2, MFA reset R3) was weighed; the stricter rule wins because the harm is a person locked out or an impostor let in, and it can be lowered later on evidence.
- **Revisit when** six months of approval data show R3 delays that hurt users without catching anything.
- **Affects.** B-01, B-06, B-29, B-30; C-29.

### D6-08 After hours, windows and pre-authorized containment
- **Decision.** Time rules live in the runner, never in a lever (STD-LV-8). `B-42` reads business hours, time zone and maintenance window from the client record; a write lever flagged `window: business-hours` or `window: maintenance` is refused outside it, and a client with no window is refused, not defaulted (`B42-4`). Pre-authorized containment (`B42-5`): `user.disable`, `user.revoke-sessions` and device isolate may run on one on-call approval when the client record says `containment_preauthorized: true`; the runner opens a second review due the next business day, and an overdue review is audited and alerts. Wipe, retire, delete and retention changes never use this path and wait for two approvals; wipe stays human-executed after approval. Workstation reboots run outside business hours; servers only in the maintenance window.
- **Basis.** Industry default: MDR and SOC providers run pre-authorized containment for reversible actions; NIST SP 800-61r3 (April 2025) asks for authority to be defined before an incident; RMM patch policies and Intune update rings hold windows centrally per client. The MSP's after-hours rules UNKNOWN.
- **Revisit when** the MSP states which actions its on-call engineer may take alone, or which clients have pre-authorized containment in their contracts.
- **Affects.** B-42 (B42-4, B42-5), B-62 (B62-2, now depends on B-42), B-65 (B65-3, now depends on B-42); C-32, C-07, C-34.

### D6-09 Reaching client tenants
- **Decision.** GDAP for every Microsoft 365 tenant, roles assigned to security groups by tier, least-privileged roles from Microsoft's role-by-task table, no Global Admin, privileged roles just in time. Automation uses the Secure Application Model (multitenant app plus delegated, consented access). Per-client single-tenant app registrations with certificate auth only by documented exception (a workload GDAP does not reach, or a non-CSP client). The adapter layer keeps one TenantAccess seam with both modes. `B-54` already watches GDAP relationship expiry.
- **Basis.** Assumption: the MSP is a Microsoft cloud partner (map 07 MP-02), so GDAP is likely. Microsoft: DAP is deprecated; partner app-only access to customer tenants under GDAP is not supported; the Secure Application Model is the supported pattern.
- **Revisit when** the MSP shares its GDAP role templates or uses an access broker (for example a CIPP-style tool).
- **Affects.** B-19, B-54, B-91 (B91-4), B-49; C-38, C-04.

### D6-10 Key Vault layout
- **Decision.** One Key Vault per environment (dev, prod), RBAC, soft delete and purge protection, secrets named `client-<id>-<purpose>`, read by managed identity; a separate per-client vault only where a client contract requires it, recorded on the client record. With GDAP and the Secure Application Model there are few per-client secrets.
- **Basis.** Microsoft Key Vault guidance (one vault per application, environment and region). Assumption: the MSP uses Key Vault (map 07 MP-31).
- **Revisit when** a client contract or the MSP's security lead asks for vault-per-client.
- **Affects.** B-85 (B85-4); C-10.

### D6-11 Where it runs and which models may see client data
- **Decision.** The target is the MSP's own Azure tenant (Functions, Logic Apps, Key Vault, Log Analytics) under their Entra sign-in. In the prototype, hosted models stay off (D-018). `governance/ai-vendor-register.json` starts with Azure OpenAI and the Anthropic API as `status: pending` with no allowed data classes (`B90-4`). Every client record defaults to `model_processing: none`; the MSP sets `local` or `hosted` per client after checking that client's contract (MSA, BAA if any, AI and subcontractor terms). Text classed DC-4 or DC-5 never goes to a hosted route without a register entry allowing it (`B-55`).
- **Basis.** Assumption: the MSP builds with Azure services, PowerShell, Graph, MCP and hosted-model providers (map 07 MP-31). Client contract terms on AI are UNKNOWN.
- **Revisit when** the MSP approves a provider in writing with retention terms (and a BAA where needed), or shares its client contract language on AI.
- **Affects.** B-90 (B90-4), B-55, B-85, B-86; C-15, C-28, C-43, C-25.

### D6-12 Client regimes and data floors
- **Decision.** The code never decides which law applies. Each client record carries `regimes` (for example `glba-ftc-safeguards`, `sec-reg-s-p`, `bank-ffiec`, `ncua`, `hipaa`) set by the MSP's compliance owner; the never-log list, retention and prompt rules read it. The unknown-text floor is DC-5 for financial, legal and accounting clients and DC-4 for dental (`B55-1`). `B-52` adds a Regulation S-P mapping for investment advisers (`B52-4`), marked hedged until checked against the rule text; the HIPAA pack stays for any healthcare client.
- **Basis.** Assumption: the clients live under GLBA, SEC, Regulation S-P, FDIC, OCC, NCUA, FINRA, CIS, NIST and CMMC (map 07 MP-41); HIPAA applies to the dental demo client. Regulation S-P as amended in 2024 adds an incident response program, service-provider oversight and customer notice (hedged, from memory and secondary sources; compliance dates reportedly Dec 2025 for larger and Jun 2026 for smaller entities).
- **Revisit when** the MSP's compliance owner sets the regime per client, or counsel reads the Reg S-P text against the pack.
- **Affects.** B-52 (B52-4), B-55 (B55-1); C-25, C-45.

### D6-13 Personas match the MSP's verticals
- **Decision.** the MSP's public focus is financial institutions, RIAs and wealth managers, legal, and accounting and tax. Contoso Dental stays as the W1 demo client (already built and rehearsed), presented as a generic regulated small business. From W2 the new tickets lean to Fabrikam Capital (financial, RIA) and Litware Legal (`B21-4`). The map 02 personas at "Woodgrove Legal" are renamed Litware Legal so one name is used everywhere (STD-ID-5, SX-08); Northwind Bookkeeping stays as the accounting example.
- **Basis.** Assumption: financial, adviser, legal and accounting verticals (map 07 MP-40); D-024 (third client is `litware-legal`).
- **Revisit when** the MSP says which client types matter most by revenue or ticket volume.
- **Affects.** B-21 (B21-4); C-45.

### D6-14 Technician-to-client mapping
- **Decision.** Explicit client lists per technician in configuration now (as today); the target reads Entra security groups (one per client or pod) that also carry the GDAP role assignments, so one membership change grants both.
- **Basis.** Industry default; Microsoft GDAP role assignment to security groups. The MSP's model UNKNOWN.
- **Revisit when** the MSP says whether it works in pods or named accounts.
- **Affects.** B-03, B-18; C-04, C-38.

### D6-15 Client source of truth
- **Decision.** The PSA company record is the source of truth for client ids; `config/clients/<id>.json` carries the PSA id. A new client record is approved by a human service manager (owner entry step, ONB-01).
- **Basis.** Industry default (the PSA drives billing and contracts).
- **Revisit when** the MSP names a different master (for example its documentation platform).
- **Affects.** B-18, B-77; C-04.

### D6-16 Audit retention and where evidence lives
- **Decision.** Default retention 7 years, configurable upward per client; target store is immutable (write-once) storage in the MSP's Azure tenant with the head pin anchored there (STD-AU-8). The prototype keeps local files.
- **Basis.** Industry default; seven years covers the six-year books-and-records periods common for financial clients and a 12-month SOC 2 audit window (hedged).
- **Revisit when** the MSP's compliance owner sets a period or a client contract requires another.
- **Affects.** B-42, B-82, B-85; C-39, C-08.

### D6-17 Compliance owner and AI change approver are roles
- **Decision.** The governance pack names roles (compliance owner, AI change approver, security lead), never people. `B-92` and `B-93` are written to extend an existing the MSP AI change process rather than replace it.
- **Basis.** Assumption: the MSP may already run an AI change process; UNKNOWN.
- **Revisit when** the MSP names the owners or shares its process.
- **Affects.** B-92, B-93, B-94; C-42, C-37.

### D6-18 SOC 2 scope
- **Decision.** Evidence packs emphasise security, availability and confidentiality; processing integrity and privacy are not claimed.
- **Basis.** Industry default for MSP SOC 2 reports. No real MSP's SOC 2 status is claimed (U-01).
- **Revisit when** the MSP shares its report's scope.
- **Affects.** B-51, B-95; C-39.

### D6-19 Colorado AI Act
- **Decision.** MSP operations automation (tickets, identity, devices, backup) is treated as outside "consequential decisions". Any use that would decide a consumer's access to lending, housing, insurance, employment, healthcare, legal services or education goes on the never-automate list (`B-14` gate) and `B-92` says so.
- **Basis.** Statute scope as reported (SB 24-205; effective date delayed to 2026-06-30; later changes reported). Hedged: current status unverified.
- **Revisit when** a client asks to use the program in one of those decisions, or the law changes.
- **Affects.** B-14, B-92; C-42.

### D6-20 Restore target after an automation lockout
- **Decision.** One business hour during support hours to restore a person locked out by an automation (EU-2 as proposed); outside support hours, the on-call response time in the client's agreement.
- **Basis.** Industry default; the MSP's SLA numbers UNKNOWN.
- **Revisit when** the MSP commits a different target.
- **Affects.** B-04, B-41; C-36, C-34.

### D6-21 The individual metric
- **Decision.** Measure time until the person can work again: PSA completed minus created, plus a proposed `user confirmed working` field; CSAT comes from the CSAT tool's export, grouped by client, never by technician (`B74-4`).
- **Basis.** Assumption: the MSP runs a CSAT tool that usually integrates with the PSA (map 07 MP-29).
- **Revisit when** the MSP shares the metrics it already reports.
- **Affects.** B-74 (B74-4); C-21.

### D6-22 Where saved hours go
- **Decision.** The program's stated position is "moved up, not out": saved hours go to project, security and client work, and automation metrics never rank technicians (`B74-3`). `B-96` and `B-97` present it as a proposal for the MSP leadership to adopt or change.
- **Basis.** Technicians only correct a system they trust; the correction loop is a safety control.
- **Revisit when** the MSP leadership states its own position.
- **Affects.** B-96, B-97; C-42.

### D6-23 Leverage scores
- **Decision.** Map 02 Appendix A scores and the enabler exclusion are the planning basis.
- **Basis.** Judgment on estimates, labelled as such.
- **Revisit when** real volumes arrive (D6-03).
- **Affects.** none.

### D6-24 Backup is in scope; backup review comes earlier
- **Decision.** Backup and disaster recovery are in scope. `B-68` (read-only daily backup review plus one R2 retry lever) moves from W6 to W3; its dependencies (`B-14`, `B-18`) are in W2, and `B-69`, `B-70`, `B-91` still follow it. `B-47` (exploited-flaw relevance) stays in W4.
- **Basis.** Assumption: the MSP offers backup and disaster recovery and managed Microsoft 365 backup (map 07 MP-15, MP-16). Rank 1 in map 02.
- **Revisit when** the MSP says backup operations sit with another team.
- **Affects.** B-68 (moved, B68-4); C-27, C-21, C-05.

### D6-25 Pilot tenant
- **Decision.** Staged rollout starts on one small financial-services client that volunteers, R0 levers only for 30 days, then R1 and R2 by ring (CM-5).
- **Basis.** Industry default (ring rollout).
- **Revisit when** the MSP picks a pilot client.
- **Affects.** none in the roadmap; C-37.

### D6-26 Existing RMM scripts
- **Decision.** The RMM adapter lists existing components read-only; the program never runs one until it is vetted into the registry as a named script (`B62-1` already forbids free-form scripts).
- **Basis.** Industry default; CISA AA22-131A on MSP tooling as an attack path.
- **Revisit when** the MSP shares its component library and the rights it runs under.
- **Affects.** B-61 (B61-4), B-62; C-01, C-37.

### D6-27 Repo moves
- **Decision.** Approve M-04 (W3-X5) and M-07 (in `B-96`) and keep K-01 to K-08 in place.
- **Basis.** Each move has one owner step; the kept items avoid churn.
- **Revisit when** a later wave needs another move.
- **Affects.** none.

### D6-28 Labels and milestones now
- **Decision.** Create the labels and milestones in W1; they are metadata and touch no demoed code. The owner runs the `gh` commands, since agents cannot change GitHub settings (`B-08` is owner-only).
- **Basis.** No demo impact.
- **Affects.** B-08; C-37.

### D6-29 CODEOWNERS roles
- **Decision.** Automation lead owns `levers/`, compliance owner owns `governance/`, security lead owns `core/audit/`; the owner holds all three until the MSP names people.
- **Basis.** Industry default.
- **Affects.** B-08; C-37.

### D6-30 No PowerShell prefix
- **Decision.** Public lever functions use module-qualified Verb-Noun names with no prefix (STD-PS-2); any later prefix must not imply affiliation.
- **Affects.** B-15.

### D6-31 Drift fixes ride their roadmap items
- **Decision.** DR-01 to DR-22 are fixed by the roadmap items that already own them (for example DR-02 in `B-02`, DR-12 in `B-03`, DR-01 and DR-05 in `B-26`), not as separate work items. Nothing that changes demoed output lands after the demo freeze.
- **Basis.** One owner per path per wave keeps parallel work safe.
- **Affects.** B-02, B-03, B-12, B-26.

### D6-32 W1 scope
- **Decision.** W1 scope and cut line are approved as written, including the visible demo changes (verification field, masked phone numbers, scoped queue listing). The calendar and the demo tag follow the demo date (J-05).
- **Affects.** B-01 to B-11 (no change).

---

## 3. The owner's calls (not decided here)

These are about the owner's own repo, machine, time or demo. Each has a recommendation; nothing changes until he says yes.

| Id | Question | Recommendation |
|---|---|---|
| J-01 | Publish the repo, choose a license, and how branch protection is enforced (RQ-03, RO-02, GQ-13, D-008) | Done: published under Apache-2.0 (D-008, D-021) with synthetic data only. Enforce required checks by CI plus convention until branch protection is enabled. |
| J-02 | Run the `gh` label and milestone commands yourself (RQ-03, second part) | Yes, in W1 (D6-28). They are printed by `B-09`; about five minutes. |
| J-03 | Apply each wave's protected-file changes yourself as entry steps (RQ-04) | Yes. It keeps the guardrails intact (D-012, D-013); the agents prepare exact diffs so each step is a paste and a review. |
| J-04 | Which installs to approve (RQ-09, OQ-11) | Approve Pester 5 and PSScriptAnalyzer now (Microsoft-maintained, CurrentUser scope, needed for STD-PS-8 and STD-PS-9). Bicep CLI at W9 only (`az bicep install`). No vector store install: start with SQLite and standard-library search in W5. Skip OpenTelemetry until W8 (JSON logs first). No Docker. |
| J-05 | Confirm the demo date (RQ-11) | Confirm the rebooked date, then shift the W1 calendar, set the freeze to the day before at 18:00 MT, and rename the tag from `demo-2026-10-27` to `demo-<date>`. |


---

## 4. Sources

- The MSP public evidence: see `07-msp-profile.md` (each row has its URL or DNS record and a confidence label).
- CISA AA23-320A, Scattered Spider (revised 2025-07-29): https://www.cisa.gov/news-events/cybersecurity-advisories/aa23-320a
- CISA AA22-131A, protecting MSPs and their customers: https://www.cisa.gov/news-events/cybersecurity-advisories/aa22-131a
- Microsoft, help desk with Verified ID: https://learn.microsoft.com/en-us/entra/verified-id/helpdesk-with-verified-id
- Microsoft, Intune Multi Admin Approval: https://learn.microsoft.com/en-us/intune/intune-service/fundamentals/multi-admin-approval
- Microsoft, GDAP and the Secure Application Model: https://learn.microsoft.com/en-us/partner-center/developer/gdap-and-secure-application-model
- Microsoft, GDAP least-privileged roles by task: https://learn.microsoft.com/partner-center/gdap-least-privileged-roles-by-task
- Microsoft, Key Vault best practices: https://learn.microsoft.com/azure/key-vault/general/best-practices (hedged: guidance summarised, page not re-read this session)
- NIST SP 800-61r3 (April 2025): https://csrc.nist.gov/pubs/sp/800/61/r3/final
- AICPA Trust Services Criteria (CC6.1, CC8.1): https://www.aicpa-cima.com/resources/download/2017-trust-services-criteria-with-revised-points-of-focus-2022
- SEC Regulation S-P amendments (2024): https://www.sec.gov/rules-regulations/2024/05/s7-05-23 (hedged: dates and duties from secondary sources)
- Colorado SB 24-205: https://leg.colorado.gov/bills/sb24-205 (hedged: post-June 2026 status unverified)
