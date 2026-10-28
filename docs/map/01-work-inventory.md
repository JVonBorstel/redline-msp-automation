# 01 Work inventory (granular)

Status: **document-only** (mapping stage, 2026-10-20). No code. Every unit of work the AI & Automation Engineer role and the MSP teams it serves actually do, one row per unit, with a stable id. Machine-readable twin: `map/inventory.json` (same ids, same fields). Synthetic planning data: nothing here describes the MSP's real staffing, tools, volumes or clients.

Derived from: `docs/BLUEPRINT.md` (scope, section 2), `docs/COVERAGE.md`, the code that exists in this repo on 2026-10-20, and general knowledge of how an MSP runs. The MSP's actual PSA, RMM, backup and documentation products are **unknown** (see open questions); this inventory names system *types*, not brands.

## How to read this

**Ids.** `W-<area>-<nn>`, for example `W-IDM-02`. Ids never get reused; a retired item keeps its id with a note. Other map documents reference these ids.

**Reference scale (estimate, used for every volume column).** A mid-size MSP inside the target range: 200 client tenants, about 5,000 end users, about 6,000 managed endpoints, 25-35 technicians. Volumes are rough planning estimates from general MSP practice, not measurements and not the MSP figures; they scale roughly linearly with users and tenants (50 tenants: divide by about 4; 500 tenants: multiply by about 2.5). A small MSP sits at the lower end of the range today (UNVERIFIED; Q-02 replaces the estimate with measured volumes).

**Granular to macro.** Each row is written at the level of one person at one client with one ticket (the granular end). The `who_today`, `data_sensitivity` and `pain_today` fields carry who is hurt when it goes wrong; later map documents roll these up to the client business, the MSP and the community.

### Risk classes

| Class | Meaning | Default control |
|---|---|---|
| R0 | Read-only. Changes nothing anywhere. | Scoped read lever, audited. No approval. |
| R1 | Low-impact, reversible write inside MSP systems (ticket fields, notes, drafts, internal records). | Suggestion accepted by a technician, or a named standard change after evals. |
| R2 | Reversible write to a client system (license, group, mailbox permission, reboot, patch, restore to alternate location). | Dry-run diff, technician approval, audit record. |
| R3 | Identity, security-control, destructive or irreversible change (credentials, MFA, disable, wipe, admin roles, Conditional Access, overwrite restore, spending). | Dry-run diff, lead approval (approver is never the requester), extra confirmation where stated, or human-only. |

### Automation patterns

| Pattern | Meaning |
|---|---|
| read-lever | A deterministic, scoped, audited read (Graph, PSA, RMM query). |
| write-lever-approval | A deterministic lever that changes state, dry-run first, executed only after the approval in the row. |
| agent-triage | A model classifies, groups or summarizes untrusted input and proposes; rules, not the model, pick any lever. |
| report | A generated report, draft or checklist that a human reads, edits and sends. |
| eval | A test, golden set or validator that measures or gates the work. |
| none-keep-human | Stays human. Tools may fetch facts for the human; they do not decide or act. |

### Data sensitivity

`public`, `internal` (MSP business data), `confidential` (client business data, personal data, credentials), `regulated` (likely to contain PHI under HIPAA or customer NPI under the GLBA / FTC Safeguards Rule). Ticket free text is treated as possibly regulated everywhere, because users paste anything into tickets.

### Repo status

`exists` (code in this repo, mocked against synthetic fixtures), `partial` (some of it exists), `planned` (a blueprint phase covers it), `gap (proposed)` (no blueprint phase covers it; a phase is proposed), `not planned` (deliberately left human or out of scope).

## Summary

152 work items across 17 areas.

| Area | Code | Items | R3 items | Exists or partial |
|---|---|---|---|---|
| Service desk (tiers 1-3) | SD | 14 | 0 | 3 |
| User onboarding and offboarding | ONB | 17 | 6 | 2 |
| Identity and MFA | IDM | 13 | 7 | 6 |
| Microsoft 365 administration (Entra, Exchange, SharePoint, Teams, Purview) | M365 | 12 | 2 | 1 |
| Endpoint management | EP | 11 | 3 | 0 |
| Patching | PAT | 7 | 1 | 0 |
| Backup and disaster recovery | BDR | 8 | 1 | 0 |
| Security monitoring and alerting | SEC | 10 | 4 | 2 |
| Compliance evidence | CMP | 9 | 1 | 3 |
| Vendor and license management | VND | 6 | 2 | 0 |
| Client reporting and QBRs | RPT | 6 | 0 | 0 |
| Documentation and knowledge base | KB | 7 | 1 | 2 |
| Billing inputs | BIL | 4 | 1 | 0 |
| Project work | PRJ | 6 | 3 | 1 |
| Internal tooling and the AI/automation platform | TOOL | 14 | 1 | 6 |
| AI governance | GOV | 4 | 2 | 1 |
| Staff training on AI | TRN | 4 | 1 | 1 |

| Risk | Items |  | Pattern (items using it) | Items |  | Repo status | Items |
|---|---|---|---|---|---|---|---|
| R0 | 67 | | report | 78 | | planned | 84 |
| R1 | 23 | | write-lever-approval | 40 | | gap (proposed) | 29 |
| R2 | 26 | | eval | 23 | | partial | 18 |
| R3 | 36 | | none-keep-human | 22 | | not planned | 11 |
| | | | read-lever | 17 | | exists | 10 |
| | | | agent-triage | 15 | | | |

What already exists in the repo (all mocked, synthetic data): triage (`W-SD-02`), the MFA reset and disable levers (`W-IDM-02`, `W-ONB-08`), the tenant baseline check (`W-M365-11` and the identity checks it feeds), the approval queue (`W-TOOL-06`), the hash-chained audit log and verifier (`W-CMP-05`), the gateway, lever registry, injection guard and triage evals (`W-TOOL-01`..`05`).

Gaps the blueprint does not cover yet (no phase owns them): backup and DR (`W-BDR-*`, there is no backup adapter in the blueprint's adapter list), patch review (`W-PAT-01`, `W-PAT-05`), mail flow and quarantine (`W-M365-03`, `W-M365-04`), DMARC (`W-M365-10`), GDAP (`W-IDM-10`), device reconciliation (`W-EP-01`), time-entry notes and billing classification (`W-BIL-01`, `W-BIL-03`), cyber insurance questionnaires (`W-CMP-08`), and MSP-level client offboarding (`W-PRJ-02`). Each row names the phase it is proposed for.

## Never automate

These stay human by design. Tools may fetch read-only facts for the person deciding; no agent decides, triggers or times them. Each reason is the reason a mistake cannot be undone or a judgment cannot be delegated.

| Id | Work | Why it stays human |
|---|---|---|
| `W-ONB-15` | Urgent or hostile termination | Timing and conduct of a termination carry legal and personal stakes; a minute early or late harms a person or the client. |
| `W-IDM-04` | Caller identity verification | Deciding that a caller is who they claim is the main defense against social engineering; a model can be talked into it, and the result unlocks everything else. |
| `W-IDM-06` | Conditional Access policy change | One wrong Conditional Access policy locks out a whole client or silently removes protection. |
| `W-IDM-07` | Privileged role grants and PIM activation approval | Admin grants define who controls a client tenant; an agent granting admin rights is the exact failure zero trust exists to stop. |
| `W-M365-12` | Retention, litigation hold and eDiscovery requests | Legal holds and eDiscovery require legal authority and handle message content; errors destroy evidence or expose privileged data. |
| `W-BDR-07` | Ransomware or disaster recovery decision | Choosing a recovery point and declaring a disaster decides what data a client keeps; it needs people accountable to the client. |
| `W-SEC-07` | Security incident declaration and breach notification decision | Breach determination and notification (for example under the HIPAA Breach Notification Rule or the FTC Safeguards Rule notification requirement) are legal decisions owned by the client and counsel. |
| `W-CMP-07` | Policy attestations and management assertions | A signature or management assertion is a person's accountable statement to an auditor; automating it makes it false. |
| `W-VND-02` | License purchase or reduction | Spending the client's money needs the client's consent each time. |
| `W-KB-07` | Credential vault entries in the documentation platform | The credential vault is the most sensitive store an MSP holds; letting an AI read it turns one injection into access to every client. |
| `W-BIL-04` | Contract terms, pricing and billing disputes | Contract and pricing disputes are relationships, not tasks. |
| `W-TRN-04` | New technician onboarding and performance coaching | Judging people's performance from AI output or ticket metrics is unfair to the individual and corrodes trust in the whole program. |

Also kept human, though not on the never list because they could later be partly automated with strong evidence: Conditional Access *drift detection* is automated but the change is not; firewall and DNS changes (`W-SEC-09`, `W-VND-06`), firmware upgrades (`W-PAT-07`), LAPS and recovery-key retrieval (`W-EP-11`, `W-EP-06`), secret rotation (`W-TOOL-08`), model and tool approval (`W-GOV-02`), AI incident response (`W-GOV-04`), MSP client offboarding (`W-PRJ-02`), and in-place restores (part of `W-BDR-03`).

Cross-cutting rules that apply to every row:
- Secret values (passwords, TAPs, recovery keys, LAPS passwords, app secrets) never enter a prompt, a ticket body, a log or an agent's context.
- Ticket, email and document text is untrusted input. It may raise a ticket's priority; it never changes which lever may run, for whom, or for which client.
- An approver is never the requester, and a model is never an approver.
- Message and file content from client tenants is not pulled into prompts; metadata only, unless a later governance decision says otherwise for a specific, approved use case.

## ITIL practice crosswalk

The scope includes ITIL-style operations. This table maps common ITIL 4 practice names to the inventory, so a service-desk lead can find their practice in this map. It is a reading aid written from general knowledge of ITIL 4, not a certified mapping, and the MSP's own process names may differ (Q-03).

| ITIL 4 practice | Inventory items |
|---|---|
| Incident management | `W-SD-01`, `W-SD-02`, `W-SD-04`, `W-SD-07`, `W-SD-08`, `W-SD-12`, `W-IDM-03` |
| Service request management | `W-SD-11`, `W-ONB-01` to `W-ONB-07`, `W-IDM-01`, `W-IDM-02`, `W-M365-01`, `W-M365-02`, `W-EP-04`, `W-BDR-03` |
| Problem management | `W-SD-03`, `W-SD-13`, `W-PAT-03`, `W-BDR-02` |
| Change enablement | `W-CMP-04`, `W-PAT-01`, `W-PAT-06`, `W-IDM-06`, `W-TOOL-01`, `W-TOOL-07` |
| Service level management | `W-SD-06`, `W-SD-10`, `W-RPT-06` |
| Monitoring and event management | `W-EP-02`, `W-SEC-01`, `W-BDR-01`, `W-VND-05`, `W-TOOL-09` |
| Information security management | `W-SEC-01` to `W-SEC-10`, `W-IDM-05` to `W-IDM-12`, `W-M365-05`, `W-M365-07`, `W-M365-08` |
| Knowledge management | `W-KB-01` to `W-KB-05`, `W-SD-05` |
| IT asset management and service configuration management | `W-EP-01`, `W-EP-10`, `W-VND-01`, `W-VND-03`, `W-KB-02` |
| Service continuity management | `W-BDR-04` to `W-BDR-08` |
| Supplier management | `W-VND-04`, `W-CMP-06`, `W-GOV-02` |
| Relationship management | `W-RPT-01` to `W-RPT-05`, `W-TRN-02` |
| Release and deployment management | `W-TOOL-07`, `W-EP-04`, `W-PAT-04` |
| Continual improvement | `W-TOOL-13`, `W-TOOL-14`, `W-TRN-03`, `W-SD-14` |

## SD: Service desk (tiers 1-3)

| Id | Work | Who today | Volume (est.) | Systems | Sensitivity | Pattern | Risk | Repo |
|---|---|---|---|---|---|---|---|---|
| `W-SD-01` | Ticket intake and logging | Dispatcher / Tier 1 technician | 3,000-5,000 tickets/month (about 0.6-1.0 per end user per month) | PSA, email, phone | confidential (may contain PHI/NPI in free text) | agent-triage | R1 | partial |
| `W-SD-02` | Ticket triage: category, priority, queue | Dispatcher / service desk lead | same as W-SD-01: every ticket | PSA | confidential | agent-triage + eval | R1 | exists |
| `W-SD-03` | Duplicate and related ticket detection | Dispatcher / Tier 1 technician | 5-10% of tickets are duplicates or follow-ups | PSA | confidential | agent-triage | R1 | planned |
| `W-SD-04` | Ticket summary for handoff and escalation | Tier 1/2 technician | 400-800/month | PSA | confidential | report | R0 | planned |
| `W-SD-05` | Draft reply to the end user from the knowledge base | Tier 1/2 technician | 1,500-3,000 replies/month | PSA, documentation, email | confidential | agent-triage + eval | R1 | partial |
| `W-SD-06` | SLA breach watch | Service desk lead / service delivery manager | continuous; 50-150 at-risk tickets/month | PSA, Teams | internal | report | R0 | planned |
| `W-SD-07` | Escalation tier 1 to 2 to 3 with context package | Tier 1/2 technician | 15-25% of tickets | PSA, RMM, Graph/Entra | confidential | read-lever + report | R0 | planned |
| `W-SD-08` | Outage and widespread-issue detection | Service desk lead | 2-6 events/month | PSA, RMM | internal | agent-triage + report | R1 | planned |
| `W-SD-09` | Closure confirmation and follow-up | Tier 1 technician | 2,000-4,000/month | PSA, email | internal | write-lever-approval | R1 | gap (proposed) |
| `W-SD-10` | Stale ticket and backlog grooming | Service desk lead | weekly; 100-300 tickets waiting on client or vendor | PSA | internal | report | R0 | planned |
| `W-SD-11` | Common tier 1 fixes via scripts (print spooler, mapped drives, Outlook profile, cache clear) | Tier 1 technician | 300-600/month | RMM, PSA | internal | write-lever-approval + eval | R2 | planned |
| `W-SD-12` | After-hours and on-call triage | On-call engineer | 20-60 pages/month | PSA, RMM, phone | confidential | agent-triage + report | R1 | planned |
| `W-SD-13` | Recurring-issue analysis (problem management) | Tier 3 engineer / service delivery manager | monthly per client; 10-30 problems/month across clients | PSA, RMM | internal | report | R0 | gap (proposed) |
| `W-SD-14` | Customer satisfaction feedback review | Service delivery manager | 200-600 responses/month | PSA, email | internal | report | R0 | gap (proposed) |

**`W-SD-01` Ticket intake and logging**
- Trigger: Email, phone call, portal form or RMM alert arrives.
- Steps today: Read the email or take the call; Create or match the ticket in the PSA; Set client, contact and asset; Write a short summary.
- Pain today: Retyping, wrong client or contact picked, PHI pasted into ticket bodies.
- Human in the loop: Agent proposes client, contact and summary; dispatcher confirms before the ticket is saved. Free text is untrusted input.
- Repo: partial: workflows/triage reads synthetic tickets (fixtures/tickets/); intake parsing is Phase 2.

**`W-SD-02` Ticket triage: category, priority, queue**
- Trigger: New ticket saved.
- Steps today: Read the ticket; Pick category and priority against the SLA matrix; Route to a queue or technician.
- Pain today: Inconsistent priority, mis-routed tickets bounce between queues, slow first response.
- Human in the loop: Suggestion only. Technician accepts or corrects; corrections become eval data. Ticket text can raise priority but can never change what may be done.
- Repo: exists (mocked): workflows/triage, evals/triage/report.md, workflows/triage/corrections.py.

**`W-SD-03` Duplicate and related ticket detection**
- Trigger: New ticket saved.
- Steps today: Search open tickets for the same user or symptom; Merge or link by hand.
- Pain today: Two technicians work the same issue; client gets two answers.
- Human in the loop: Agent suggests the match with reasons; a technician merges. Never auto-merge across clients.
- Repo: planned: Phase 2.

**`W-SD-04` Ticket summary for handoff and escalation**
- Trigger: Escalation, shift change, or long ticket thread.
- Steps today: Re-read the whole thread; Write what was tried and what is next; Reassign.
- Pain today: Next tier re-asks the user the same questions; context is lost.
- Human in the loop: Read-only summary shown with the ticket entries it used; the receiving technician reads the source when it matters.
- Repo: planned: Phase 2.

**`W-SD-05` Draft reply to the end user from the knowledge base**
- Trigger: Ticket needs a written answer.
- Steps today: Search the KB; Adapt steps to the user; Write and send the reply.
- Pain today: Slow, uneven writing quality, KB not used.
- Human in the loop: Draft only, with citations to the client's own KB; a technician edits and sends. No reply is sent by an agent.
- Repo: partial: kb.search lever in levers/registry.json (keyword, mocked); drafting is Phase 2, cited RAG is Phase 5.

**`W-SD-06` SLA breach watch**
- Trigger: Timer: response or resolution clock nearing breach.
- Steps today: Watch PSA board views; Chase technicians in chat.
- Pain today: Breaches are found after the fact; leads spend time watching boards.
- Human in the loop: Read-only alert to the lead; reassignment is a human decision.
- Repo: planned: Phase 2.

**`W-SD-07` Escalation tier 1 to 2 to 3 with context package**
- Trigger: Fix fails or exceeds tier authority.
- Steps today: Decide to escalate; Gather logs and screenshots; Reassign and notify.
- Pain today: Escalations missing evidence; tier 3 time wasted.
- Human in the loop: Agent gathers read-only evidence (device health, sign-in history); the technician decides to escalate.
- Repo: planned: Phase 2 (summary), Phase 4 (enrichment levers).

**`W-SD-08` Outage and widespread-issue detection**
- Trigger: Several tickets or alerts with the same symptom at one client or across clients.
- Steps today: Notice the pattern; Open a parent ticket; Link children; Notify clients.
- Pain today: Pattern noticed late; each ticket worked separately.
- Human in the loop: Agent proposes grouping; the lead declares the incident and approves any client notice.
- Repo: planned: Phase 2 (alert grouping).

**`W-SD-09` Closure confirmation and follow-up**
- Trigger: Fix applied, waiting on user.
- Steps today: Email or call the user to confirm; Close after N days of no reply.
- Pain today: Tickets sit open; manual chasing.
- Human in the loop: Template reminders may be pre-approved as a standard change; closing a ticket the user disputes is human.
- Repo: not in blueprint; proposed Phase 2.

**`W-SD-10` Stale ticket and backlog grooming**
- Trigger: Weekly review.
- Steps today: Filter old tickets; Ping owners; Close or escalate.
- Pain today: Backlog grows quietly; aging hides real problems.
- Human in the loop: Read-only weekly list; humans act.
- Repo: planned: Phase 2 (SLA watch); grooming list proposed Phase 6.

**`W-SD-11` Common tier 1 fixes via scripts (print spooler, mapped drives, Outlook profile, cache clear)**
- Trigger: Ticket with a known, scripted fix.
- Steps today: Remote into the device; Run the fix by hand or an RMM script; Confirm with the user.
- Pain today: Repetitive, interrupts the user, inconsistent steps.
- Human in the loop: Technician approves each run until the lever's eval and incident record justify a named standard change; dry-run diff shown first.
- Repo: planned: Phase 3 (levers), Phase 7 (idempotency and retry).

**`W-SD-12` After-hours and on-call triage**
- Trigger: Critical alert or emergency call outside hours.
- Steps today: Answer the page; Judge severity; Fix or defer to morning.
- Pain today: Fatigue, false pages, slow wake-up context.
- Human in the loop: Agent groups and summarizes; on-call human decides to act. Write levers still need approval (on-call lead may self-approve only where the policy names it, and that is audited).
- Repo: planned: Phase 2 (alert grouping).

**`W-SD-13` Recurring-issue analysis (problem management)**
- Trigger: Monthly review or a spike.
- Steps today: Pull ticket exports; Cluster by hand in a spreadsheet; Write a root-cause proposal.
- Pain today: Rarely done; same issue fixed 40 times.
- Human in the loop: Read-only clustering; root cause and fix plan are human.
- Repo: not in blueprint; proposed Phase 6.

**`W-SD-14` Customer satisfaction feedback review**
- Trigger: Survey response, especially negative.
- Steps today: Read responses; Call unhappy clients; Coach technicians.
- Pain today: Negative feedback sits unread.
- Human in the loop: Read-only routing of negative feedback to a manager; no automated reply.
- Repo: not in blueprint; proposed Phase 6.

## ONB: User onboarding and offboarding

| Id | Work | Who today | Volume (est.) | Systems | Sensitivity | Pattern | Risk | Repo |
|---|---|---|---|---|---|---|---|---|
| `W-ONB-01` | New-hire request intake and requester authorization check | Tier 1 technician / dispatcher | 60-150 new hires/month (20-35% yearly SMB turnover, estimate) | PSA, documentation, email | confidential (personal data of the new hire) | agent-triage + read-lever | R0 | planned |
| `W-ONB-02` | Create the user account (cloud or hybrid) | Tier 1/2 technician | 60-150/month | Graph/Entra, PSA | confidential | write-lever-approval | R3 | planned |
| `W-ONB-03` | Assign licenses | Tier 1/2 technician | 60-150/month | Graph/Entra, PSA, vendor portal | internal (cost impact) | write-lever-approval | R2 | planned |
| `W-ONB-04` | Role-based access: groups, shared mailboxes, Teams and SharePoint | Tier 1/2 technician | 60-150/month, 5-20 grants each | Graph/Entra, Exchange Online, SharePoint, Teams | regulated (grants reach PHI/NPI stores) | write-lever-approval | R2 | planned |
| `W-ONB-05` | MFA enrollment and Temporary Access Pass | Tier 1 technician | 60-150/month | Graph/Entra, phone | confidential (credential material) | write-lever-approval | R3 | planned |
| `W-ONB-06` | Device provisioning (Autopilot, Intune enrollment, app set) | Tier 1/2 technician / bench tech | 40-120 devices/month | Intune, RMM, PSA | internal | write-lever-approval | R2 | planned |
| `W-ONB-07` | Day-one welcome and handoff to the manager | Tier 1 technician | 60-150/month | email, PSA | confidential | report | R1 | planned |
| `W-ONB-08` | Offboarding: block sign-in and revoke sessions | Tier 1/2 technician | 60-150/month | Graph/Entra, PSA | confidential | write-lever-approval | R3 | exists |
| `W-ONB-09` | Offboarding: mailbox conversion, forwarding and auto-reply | Tier 1/2 technician | 60-150/month | Exchange Online | regulated (mailbox may hold PHI/NPI) | write-lever-approval | R2 | planned |
| `W-ONB-10` | Offboarding: OneDrive and file ownership transfer | Tier 1/2 technician | 60-150/month | Graph/Entra, SharePoint | regulated | write-lever-approval | R2 | planned |
| `W-ONB-11` | Offboarding: license removal after retention window | Tier 1 technician / billing | 60-150/month | Graph/Entra, PSA | internal (cost) | write-lever-approval + report | R2 | planned |
| `W-ONB-12` | Offboarding: device retire or wipe and hardware recovery | Tier 1/2 technician | 40-120 devices/month | Intune, RMM, PSA | regulated (device may hold PHI/NPI) | write-lever-approval | R3 | planned |
| `W-ONB-13` | Offboarding: line-of-business and third-party apps | Tier 1/2 technician | 60-150/month, 2-6 apps each | vendor portal, documentation | regulated | report | R3 | gap (proposed) |
| `W-ONB-14` | Offboarding completion proof | Tier 2 technician / service delivery manager | 60-150/month | PSA, Graph/Entra, Intune | confidential | read-lever + report | R0 | planned |
| `W-ONB-15` | Urgent or hostile termination | Tier 2/3 technician with service desk lead | 2-8/month | Graph/Entra, Intune, Exchange Online, phone | regulated | none-keep-human | R3 | planned |
| `W-ONB-16` | Role change or transfer (mover) | Tier 1/2 technician | 30-80/month | Graph/Entra, Exchange Online, SharePoint | regulated | write-lever-approval | R2 | planned |
| `W-ONB-17` | Guest and contractor account lifecycle | Tier 1 technician | 50-200 guests added/month across tenants | Graph/Entra, SharePoint, Teams | confidential | report + write-lever-approval | R2 | partial |

**`W-ONB-01` New-hire request intake and requester authorization check**
- Trigger: Client manager or HR submits a new-hire form or email.
- Steps today: Read request; Check the requester is an authorized contact; Chase missing fields (role, start date, license).
- Pain today: Incomplete forms, unverified requester, back-and-forth.
- Human in the loop: Agent checks the request against the documented authorized-contact list and lists missing fields; a technician confirms. An unlisted requester always goes to a human.
- Repo: planned: Phase 3.

**`W-ONB-02` Create the user account (cloud or hybrid)**
- Trigger: Approved new-hire request.
- Steps today: Apply naming standard; Create user in Entra (or AD with sync); Set attributes, manager, usage location.
- Pain today: Typos, naming drift, missing attributes break later automation.
- Human in the loop: Dry-run diff from the approved request; lead approves. Identity creation is never triggered by ticket text alone.
- Repo: planned: Phase 3.

**`W-ONB-03` Assign licenses**
- Trigger: Account created.
- Steps today: Check available seats; Assign license SKU; Buy more if short.
- Pain today: No free seat; wrong SKU; billing surprises.
- Human in the loop: Assigning from existing seats needs technician approval; buying seats is W-VND-02 (human).
- Repo: planned: Phase 3.

**`W-ONB-04` Role-based access: groups, shared mailboxes, Teams and SharePoint**
- Trigger: Account created.
- Steps today: Copy access of a 'same as' user or apply a role template; Add groups and mailbox permissions.
- Pain today: 'Same as Bob' copies Bob's excess access; over-provisioning.
- Human in the loop: Only from a client-approved role template. Becomes R3 (lead + client contact approval) if a group grants admin rights or regulated data stores.
- Repo: planned: Phase 3.

**`W-ONB-05` MFA enrollment and Temporary Access Pass**
- Trigger: First sign-in.
- Steps today: Issue a TAP or walk the user through Authenticator; Confirm registration.
- Pain today: Users stuck on day one; insecure shortcuts (SMS, shared codes).
- Human in the loop: TAP issued only after a human verifies identity (W-IDM-04); the TAP value is delivered by a human over an approved channel, never written into a ticket or a prompt.
- Repo: planned: Phase 3.

**`W-ONB-06` Device provisioning (Autopilot, Intune enrollment, app set)**
- Trigger: New hire needs a device.
- Steps today: Register hardware hash; Assign profile and group; Ship; Confirm apps installed.
- Pain today: Hash uploads by hand; missing apps on day one.
- Human in the loop: Technician approves group and profile assignment; dry-run shows which policies will apply.
- Repo: planned: Phase 3.

**`W-ONB-07` Day-one welcome and handoff to the manager**
- Trigger: Account and device ready.
- Steps today: Write the welcome note; Send sign-in instructions; Close the ticket.
- Pain today: Inconsistent notes; credentials pasted into email.
- Human in the loop: Agent drafts the note without any secret; a technician sends it.
- Repo: planned: Phase 3.

**`W-ONB-08` Offboarding: block sign-in and revoke sessions**
- Trigger: Authorized client contact requests termination with a date and time.
- Steps today: Verify requester; Disable the account at the agreed time; Revoke refresh tokens and sessions.
- Pain today: Late disables leave access open; early disables cut someone off by mistake.
- Human in the loop: Requester verified by a human; lead approves the dry-run; timing comes from the client, never from the agent.
- Repo: exists (mocked): user.disable in levers/registry.json via core/levers, triage rule in workflows/triage/rules.py; session revoke planned Phase 3.

**`W-ONB-09` Offboarding: mailbox conversion, forwarding and auto-reply**
- Trigger: Offboarding approved.
- Steps today: Convert to shared mailbox; Grant manager access; Set auto-reply text.
- Pain today: Manager gets full mailbox access without a business reason.
- Human in the loop: Delegate named by the client contact; technician approves.
- Repo: planned: Phase 3.

**`W-ONB-10` Offboarding: OneDrive and file ownership transfer**
- Trigger: Offboarding approved.
- Steps today: Grant manager access to OneDrive; Note retention deadline.
- Pain today: Data lost when retention expires; access granted too broadly.
- Human in the loop: Delegate named by the client contact; technician approves.
- Repo: planned: Phase 3.

**`W-ONB-11` Offboarding: license removal after retention window**
- Trigger: Retention window ends.
- Steps today: Remember to come back; Remove license; Update billing count.
- Pain today: Forgotten; client pays for departed users for months.
- Human in the loop: Agent lists due removals; technician approves each.
- Repo: planned: Phase 3 (lever), Phase 6 (license alerts).

**`W-ONB-12` Offboarding: device retire or wipe and hardware recovery**
- Trigger: Offboarding approved.
- Steps today: Retire from Intune or wipe; Arrange hardware return; Update asset record.
- Pain today: Wipe before a legal hold or evidence need is known.
- Human in the loop: Retire (company data only) with technician approval; full wipe needs lead approval plus client confirmation that no hold or investigation applies.
- Repo: planned: Phase 3.

**`W-ONB-13` Offboarding: line-of-business and third-party apps**
- Trigger: Offboarding approved.
- Steps today: Log in to each vendor portal (practice management, CRM, banking portals); Remove the user.
- Pain today: Apps without SSO are missed; accounts linger.
- Human in the loop: Agent produces the per-client checklist from documentation; a human does each removal (no stored vendor credentials reach an agent).
- Repo: not in blueprint; proposed Phase 3 (checklist only).

**`W-ONB-14` Offboarding completion proof**
- Trigger: All offboarding steps closed.
- Steps today: Tick a checklist in the ticket by hand.
- Pain today: No proof every step ran; weak SOC 2 and HIPAA evidence.
- Human in the loop: Read-only verification against live state, written to the ticket and the audit log.
- Repo: planned: Phase 3 (verify), Phase 4 (evidence bundle).

**`W-ONB-15` Urgent or hostile termination**
- Trigger: Client calls: someone is being let go now.
- Steps today: Verify caller; Coordinate exact time with HR; Disable, revoke, block devices in one sitting.
- Pain today: High stakes, time pressure, legal exposure.
- Human in the loop: NEVER AUTOMATE the decision or the timing. Humans run it; they may press pre-built levers (W-ONB-08, W-EP-08) with approval.
- Repo: planned: Phase 3 (runbook).

**`W-ONB-16` Role change or transfer (mover)**
- Trigger: Client reports a role change.
- Steps today: Add new access; Usually forget to remove old access.
- Pain today: Access creep: movers keep old rights.
- Human in the loop: Diff of add and remove against role templates; technician approves; R3 if admin or regulated stores.
- Repo: planned: Phase 3.

**`W-ONB-17` Guest and contractor account lifecycle**
- Trigger: Guest invited or contract ends.
- Steps today: Invite guest; Rarely review; Remove when someone remembers.
- Pain today: Guests keep access to client files for years.
- Human in the loop: Read-only expiry report; removal approved by technician after the client contact confirms.
- Repo: partial: guest-admin check in levers/powershell/TenantBaseline; lifecycle planned Phase 4.

## IDM: Identity and MFA

| Id | Work | Who today | Volume (est.) | Systems | Sensitivity | Pattern | Risk | Repo |
|---|---|---|---|---|---|---|---|---|
| `W-IDM-01` | Password reset | Tier 1 technician | 200-500/month (lower where self-service reset is enrolled) | Graph/Entra, PSA, phone | confidential (credential) | write-lever-approval | R3 | planned |
| `W-IDM-02` | MFA reset (lost or new phone) | Tier 1 technician | 80-200/month | Graph/Entra, phone | confidential | write-lever-approval | R3 | exists |
| `W-IDM-03` | Sign-in failure and lockout investigation | Tier 1/2 technician | 100-300/month | Graph/Entra | confidential | read-lever + report | R0 | planned |
| `W-IDM-04` | Caller identity verification | Tier 1 technician | every W-IDM-01/W-IDM-02, W-ONB-05, W-ONB-08 request | phone, documentation, PSA | confidential | none-keep-human | R3 | planned |
| `W-IDM-05` | Risky sign-in and risky user review | Security analyst / Tier 2 technician | 50-200 events/month | Graph/Entra, Defender, PSA | confidential | agent-triage + read-lever | R0 | planned |
| `W-IDM-06` | Conditional Access policy change | Tier 3 engineer | 5-20 changes/month | Graph/Entra | confidential | report + none-keep-human | R3 | partial |
| `W-IDM-07` | Privileged role grants and PIM activation approval | Tier 3 engineer / MSP admin | 10-40/month | Graph/Entra | confidential | none-keep-human | R3 | partial |
| `W-IDM-08` | Break-glass account monitoring | Tier 3 engineer | continuous; tested quarterly | Graph/Entra | confidential | read-lever + report | R0 | partial |
| `W-IDM-09` | Quarterly admin access review across tenants | Service delivery manager / Tier 3 engineer | quarterly x 50-500 tenants | Graph/Entra, PSA | confidential | report | R0 | planned |
| `W-IDM-10` | Partner delegated access (GDAP) relationship management | MSP admin | 5-40/month | Graph/Entra, vendor portal | confidential | report | R3 | gap (proposed) |
| `W-IDM-11` | Stale account cleanup | Tier 1/2 technician | 1-3% of accounts stale per month | Graph/Entra, PSA | confidential | report + write-lever-approval | R3 | partial |
| `W-IDM-12` | App registration and service principal secret expiry | Tier 3 engineer | 5-30/month | Graph/Entra, Azure | confidential (secrets) | report | R0 | planned |
| `W-IDM-13` | Self-service password reset and MFA method coverage | Tier 2 technician | monthly per tenant | Graph/Entra | internal | report | R0 | partial |

**`W-IDM-01` Password reset**
- Trigger: User cannot sign in.
- Steps today: Verify caller identity; Reset password or unlock; Require change at next sign-in.
- Pain today: Social-engineering target; frequent interruptions.
- Human in the loop: Identity verification is human (W-IDM-04). The lever generates no password visible to the agent; technician approves.
- Repo: planned: Phase 3.

**`W-IDM-02` MFA reset (lost or new phone)**
- Trigger: User cannot complete MFA.
- Steps today: Verify caller identity; Remove authentication methods; Issue TAP; Watch re-registration.
- Pain today: Top social-engineering path for account takeover.
- Human in the loop: Human verifies identity; lead approves the dry-run.
- Repo: exists (mocked): user.reset-mfa in levers/registry.json, approval via core/queue and ui.

**`W-IDM-03` Sign-in failure and lockout investigation**
- Trigger: Lockout or repeated failures.
- Steps today: Open Entra sign-in logs; Read error codes; Decide if user error or attack.
- Pain today: Error codes are cryptic; attacks mistaken for user error.
- Human in the loop: Read-only explanation with the log entries cited; any action goes through W-IDM-01/W-IDM-02 or W-SEC-04.
- Repo: planned: Phase 3/4.

**`W-IDM-04` Caller identity verification**
- Trigger: Any request to change credentials or access.
- Steps today: Call back on the number in documentation; Ask verification questions; Record the result.
- Pain today: Pressure from 'urgent executive' callers.
- Human in the loop: NEVER AUTOMATE the decision. Tooling may show the documented callback number and record that verification happened; a model never judges whether a person is who they claim.
- Repo: planned: Phase 3 (recording field only).

**`W-IDM-05` Risky sign-in and risky user review**
- Trigger: Entra ID Protection risk event, impossible travel, MFA fatigue.
- Steps today: Review risk detections; Contact user; Dismiss or remediate.
- Pain today: Alert volume; real compromises lost in noise.
- Human in the loop: Agent groups and explains; remediation goes through W-SEC-04 with approval.
- Repo: planned: Phase 4.

**`W-IDM-06` Conditional Access policy change**
- Trigger: Project, baseline drift, or client request.
- Steps today: Design change; Test in report-only mode; Enable; Watch for lockouts.
- Pain today: One mistake locks out a whole client or opens a gap.
- Human in the loop: NEVER AUTOMATE the change. Drift detection is read-only; a change needs a change record, report-only testing and engineer sign-off.
- Repo: partial: legacy-auth CA check in levers/powershell/TenantBaseline; drift planned Phase 4.

**`W-IDM-07` Privileged role grants and PIM activation approval**
- Trigger: Admin access requested.
- Steps today: Check justification; Grant eligible role; Approve activation.
- Pain today: Standing admin access; approvals rubber-stamped.
- Human in the loop: NEVER AUTOMATE grants or approvals. Agents may only report who holds what.
- Repo: partial: admin-count and guest-admin checks in levers/powershell/TenantBaseline.

**`W-IDM-08` Break-glass account monitoring**
- Trigger: Sign-in by a break-glass account; periodic check.
- Steps today: Check accounts exist, are excluded correctly, and alerts fire on sign-in.
- Pain today: Break-glass accounts drift or alerts silently fail.
- Human in the loop: Read-only. Using a break-glass account is NEVER automated.
- Repo: partial: break-glass pattern check in levers/powershell/TenantBaseline.

**`W-IDM-09` Quarterly admin access review across tenants**
- Trigger: Quarterly calendar.
- Steps today: Export role members per tenant; Ask owners to confirm; Remove extras.
- Pain today: Manual exports across hundreds of tenants; rarely complete.
- Human in the loop: Read-only review pack; removals by humans with approval.
- Repo: planned: Phase 4.

**`W-IDM-10` Partner delegated access (GDAP) relationship management**
- Trigger: Relationship expiry or new client.
- Steps today: Create or renew relationships; Map security groups to roles.
- Pain today: Expired relationships break support; over-broad roles.
- Human in the loop: Agent reports expiring or over-broad relationships; changes are human (they define the MSP's own reach into client tenants).
- Repo: not in blueprint; proposed Phase 4 (report only).

**`W-IDM-11` Stale account cleanup**
- Trigger: Monthly review.
- Steps today: Export last sign-in; Ask client; Disable.
- Pain today: Dormant accounts are attack paths; cleanup rarely happens.
- Human in the loop: Detection is read-only; disable needs client confirmation and lead approval (via W-ONB-08 lever).
- Repo: partial: 90-day stale check in levers/powershell/TenantBaseline; disable lever exists (mocked).

**`W-IDM-12` App registration and service principal secret expiry**
- Trigger: Secret or certificate nearing expiry.
- Steps today: Find expiring credentials; Rotate; Update the dependent app.
- Pain today: Integrations break overnight when a secret expires.
- Human in the loop: Read-only expiry report (metadata only, never secret values). Rotation is human or a Key Vault-managed process.
- Repo: planned: Phase 4 (report), Phase 8 (Key Vault).

**`W-IDM-13` Self-service password reset and MFA method coverage**
- Trigger: Monthly review.
- Steps today: Export registration details; Nudge unregistered users.
- Pain today: Unregistered users drive reset tickets and risk.
- Human in the loop: Read-only report; nudge emails drafted for human send.
- Repo: partial: MFA registration check in levers/powershell/TenantBaseline.

## M365: Microsoft 365 administration (Entra, Exchange, SharePoint, Teams, Purview)

| Id | Work | Who today | Volume (est.) | Systems | Sensitivity | Pattern | Risk | Repo |
|---|---|---|---|---|---|---|---|---|
| `W-M365-01` | Shared mailbox and distribution list changes | Tier 1 technician | 100-300/month | Exchange Online, PSA | confidential | write-lever-approval | R2 | planned |
| `W-M365-02` | Mailbox permission grants (Full Access, Send As) | Tier 1/2 technician | 50-150/month | Exchange Online | regulated | write-lever-approval | R2 | planned |
| `W-M365-03` | Mail delivery troubleshooting (message trace) | Tier 1/2 technician | 100-250/month | Exchange Online | confidential (sender, recipient, subject lines) | read-lever + report | R0 | gap (proposed) |
| `W-M365-04` | Quarantine release requests | Tier 1 technician | 100-300/month | Exchange Online, Defender | confidential | agent-triage + write-lever-approval | R2 | gap (proposed) |
| `W-M365-05` | Suspicious inbox rule and external forwarding audit | Security analyst / Tier 2 technician | scheduled weekly; 5-20 findings/month | Exchange Online, Defender | regulated | read-lever + report | R0 | planned |
| `W-M365-06` | SharePoint and Teams site creation and permissions | Tier 1/2 technician | 30-100/month | SharePoint, Teams, Graph/Entra | confidential | write-lever-approval | R2 | planned |
| `W-M365-07` | Oversharing and external sharing review (Copilot readiness) | Tier 3 engineer / vCIO | 5-20 assessments/month | SharePoint, Graph/Entra, Purview | regulated | report | R0 | planned |
| `W-M365-08` | Sensitivity labels and DLP policy changes | Tier 3 engineer / compliance lead | 2-10 changes/month | Purview | regulated | report + none-keep-human | R3 | planned |
| `W-M365-09` | Mailbox size and archive management | Tier 1 technician | 30-100/month | Exchange Online | internal | write-lever-approval | R2 | planned |
| `W-M365-10` | DMARC, SPF and DKIM monitoring | Tier 2/3 engineer | daily x 50-500 domains | email, documentation | internal | report | R0 | gap (proposed) |
| `W-M365-11` | Tenant security baseline and drift check | Tier 3 engineer | monthly x 50-500 tenants | Graph/Entra, Intune, Defender | confidential | report + eval | R0 | exists |
| `W-M365-12` | Retention, litigation hold and eDiscovery requests | Tier 3 engineer with client legal contact | 0-5/month | Purview, Exchange Online, SharePoint | regulated | none-keep-human | R3 | not planned |

**`W-M365-01` Shared mailbox and distribution list changes**
- Trigger: User or manager request.
- Steps today: Create or edit the mailbox or list; Add members.
- Pain today: Repetitive; request authority not checked.
- Human in the loop: Authorized requester check; technician approves.
- Repo: planned: Phase 3.

**`W-M365-02` Mailbox permission grants (Full Access, Send As)**
- Trigger: Request.
- Steps today: Check approval; Grant permission.
- Pain today: Access to mailboxes that hold PHI/NPI without documented approval.
- Human in the loop: Mailbox owner or authorized contact approves; technician approves. R3 for executive or regulated mailboxes.
- Repo: planned: Phase 3.

**`W-M365-03` Mail delivery troubleshooting (message trace)**
- Trigger: 'I didn't get the email'.
- Steps today: Run message trace; Read headers; Explain to the user.
- Pain today: Slow; header reading is a tier 2 skill.
- Human in the loop: Read-only. Message bodies are never pulled into a prompt; metadata only.
- Repo: not in blueprint; proposed Phase 3 (adapters/m365).

**`W-M365-04` Quarantine release requests**
- Trigger: User asks for a quarantined message.
- Steps today: Look at the message; Decide if safe; Release.
- Pain today: Malicious mail released under user pressure.
- Human in the loop: Agent summarizes verdict and indicators; technician decides; high-confidence phish is never released by request alone.
- Repo: not in blueprint; proposed Phase 4.

**`W-M365-05` Suspicious inbox rule and external forwarding audit**
- Trigger: Alert or scheduled scan.
- Steps today: Export rules; Look for forward-to-external and delete-all rules.
- Pain today: Classic business email compromise sign missed.
- Human in the loop: Read-only detection; removal is part of W-SEC-04 with approval.
- Repo: planned: Phase 4.

**`W-M365-06` SharePoint and Teams site creation and permissions**
- Trigger: Request.
- Steps today: Create site or team; Set owners and members; Set sharing.
- Pain today: Sites created with open sharing; no owner.
- Human in the loop: Standard template only; technician approves.
- Repo: planned: Phase 9 (mocked).

**`W-M365-07` Oversharing and external sharing review (Copilot readiness)**
- Trigger: Copilot request or periodic review.
- Steps today: Export sharing links and permissions; Find 'everyone' and anonymous links; Recommend fixes.
- Pain today: Copilot surfaces data people should not see.
- Human in the loop: Read-only assessment; fixes are human with client sign-off.
- Repo: planned: Phase 4.

**`W-M365-08` Sensitivity labels and DLP policy changes**
- Trigger: Client compliance project.
- Steps today: Design labels and DLP rules; Test in simulation; Enable.
- Pain today: Misconfigured DLP either blocks work or leaks data.
- Human in the loop: Agent may report current state and simulation results; policy changes are human with change approval.
- Repo: planned: Phase 4 (assessment), Phase 10 (governance/DLP_MAPPING.md).

**`W-M365-09` Mailbox size and archive management**
- Trigger: Mailbox nearing quota.
- Steps today: Check size; Enable archive or retention tag.
- Pain today: Users hit quota mid-day.
- Human in the loop: Technician approves; no retention-policy deletion.
- Repo: planned: Phase 3.

**`W-M365-10` DMARC, SPF and DKIM monitoring**
- Trigger: Daily aggregate reports; domain onboarding.
- Steps today: Read aggregate reports; Find unauthorized senders; Plan DNS changes.
- Pain today: Reports are unreadable XML; spoofing undetected.
- Human in the loop: Read-only summaries. DNS changes are human (W-VND-06).
- Repo: not in blueprint; proposed Phase 4.

**`W-M365-11` Tenant security baseline and drift check**
- Trigger: Monthly or after change.
- Steps today: Review Secure Score; Check MFA, admins, legacy auth, CA; Write findings.
- Pain today: Manual, inconsistent across tenants.
- Human in the loop: Read-only; every number in the summary is machine-checked; fix suggestions are dry-run levers only.
- Repo: exists (mocked): levers/powershell/TenantBaseline, levers/powershell/TenantBaseline/Test-SummaryReconciles.ps1; drift over time planned Phase 4.

**`W-M365-12` Retention, litigation hold and eDiscovery requests**
- Trigger: Legal or regulator request.
- Steps today: Confirm legal authority; Place hold or run content search; Export.
- Pain today: Legal exposure if done wrong.
- Human in the loop: NEVER AUTOMATE. Legal authority, scope and content handling are human; content is never placed in a prompt.
- Repo: not planned (by design).

## EP: Endpoint management

| Id | Work | Who today | Volume (est.) | Systems | Sensitivity | Pattern | Risk | Repo |
|---|---|---|---|---|---|---|---|---|
| `W-EP-01` | Device inventory reconciliation (RMM vs Intune vs PSA) | Tier 2 technician / service delivery manager | monthly; 3,000-30,000 endpoints across clients | RMM, Intune, PSA | internal | report | R0 | gap (proposed) |
| `W-EP-02` | RMM agent and Defender sensor health | NOC / Tier 1 technician | 100-400 alerts/month | RMM, Defender | internal | agent-triage + report | R0 | planned |
| `W-EP-03` | Disk space and performance alert remediation | NOC / Tier 1 technician | 200-600/month | RMM | internal | write-lever-approval + eval | R2 | planned |
| `W-EP-04` | Software deployment requests | Tier 1/2 technician | 100-300/month | RMM, Intune, PSA | internal | write-lever-approval | R2 | planned |
| `W-EP-05` | Intune compliance follow-up | Tier 1 technician | 100-300/month | Intune | internal | report | R1 | planned |
| `W-EP-06` | Disk encryption status and recovery key retrieval | Tier 1/2 technician | 20-60 key requests/month | Intune, Graph/Entra, phone | confidential (secret) | read-lever + none-keep-human | R3 | planned |
| `W-EP-07` | Remote reboot and service restart | Tier 1 technician | 200-500/month | RMM | internal | write-lever-approval | R2 | planned |
| `W-EP-08` | Lost or stolen device: lock, retire or wipe | Tier 2 technician | 5-20/month | Intune, RMM, PSA | regulated | write-lever-approval | R3 | planned |
| `W-EP-09` | macOS and Linux endpoint scripts | Tier 2 technician | 20-80/month | RMM | internal | write-lever-approval | R2 | planned |
| `W-EP-10` | Hardware lifecycle and warranty forecast | vCIO / account manager | quarterly per client | RMM, PSA, vendor portal | internal | report | R0 | planned |
| `W-EP-11` | Local admin password (LAPS) retrieval and admin-rights requests | Tier 2 technician | 30-100/month | Intune, Graph/Entra | confidential (secret) | none-keep-human | R3 | not planned |

**`W-EP-01` Device inventory reconciliation (RMM vs Intune vs PSA)**
- Trigger: Monthly or before billing.
- Steps today: Export three lists; Match by serial in a spreadsheet; Fix mismatches.
- Pain today: Unmanaged devices; wrong billing counts.
- Human in the loop: Read-only reconciliation; fixes are human.
- Repo: not in blueprint; proposed Phase 6.

**`W-EP-02` RMM agent and Defender sensor health**
- Trigger: Agent offline or sensor not reporting.
- Steps today: Check device; Reinstall agent; Contact user.
- Pain today: Blind spots: devices that stopped reporting are not patched or protected.
- Human in the loop: Grouping and explanation only; reinstall goes through W-EP-04.
- Repo: planned: Phase 2 (alert grouping).

**`W-EP-03` Disk space and performance alert remediation**
- Trigger: RMM threshold alert.
- Steps today: Remote in; Clear temp files; Check large files.
- Pain today: High-volume, low-skill toil.
- Human in the loop: Technician approves per run; may become a named standard change after eval; never deletes user data folders.
- Repo: planned: Phase 3/4 (remediation levers).

**`W-EP-04` Software deployment requests**
- Trigger: User or client request; new standard app.
- Steps today: Check license and approval; Package or pick from catalog; Deploy via RMM or Intune.
- Pain today: Unlicensed installs; inconsistent packaging.
- Human in the loop: Only catalog apps; client approval for paid software; technician approves.
- Repo: planned: Phase 3 (levers), Phase 8 (deployment automation).

**`W-EP-05` Intune compliance follow-up**
- Trigger: Device marked non-compliant.
- Steps today: Read compliance reason; Contact user; Fix setting.
- Pain today: Users blocked by Conditional Access with no explanation.
- Human in the loop: Agent explains the reason and drafts a user note; technician sends.
- Repo: planned: Phase 4.

**`W-EP-06` Disk encryption status and recovery key retrieval**
- Trigger: Audit or user locked at BitLocker/FileVault screen.
- Steps today: Verify caller; Look up key; Read it to the user.
- Pain today: Keys read to unverified callers.
- Human in the loop: Encryption status report is R0. Key retrieval is human only after identity verification; key values never reach a model, a ticket body or a log.
- Repo: planned: Phase 4 (status report only).

**`W-EP-07` Remote reboot and service restart**
- Trigger: Ticket or alert.
- Steps today: Check user is not working; Reboot or restart service.
- Pain today: Reboots during clinic hours interrupt patient care.
- Human in the loop: Technician approves; lever checks the client's maintenance window; servers need lead approval.
- Repo: planned: Phase 3.

**`W-EP-08` Lost or stolen device: lock, retire or wipe**
- Trigger: User or client reports loss.
- Steps today: Verify reporter; Lock or wipe; Record for breach assessment.
- Pain today: A lost device with PHI is a possible HIPAA breach; wipe vs evidence trade-off.
- Human in the loop: Lead approves; client contact confirms; the incident is recorded for the human breach assessment (W-SEC-07).
- Repo: planned: Phase 3.

**`W-EP-09` macOS and Linux endpoint scripts**
- Trigger: Ticket or project on non-Windows devices.
- Steps today: Write or run ad-hoc shell scripts.
- Pain today: One-off scripts, untested.
- Human in the loop: Same lever rules as Windows; technician approves.
- Repo: planned: Phase 3 (levers/bash).

**`W-EP-10` Hardware lifecycle and warranty forecast**
- Trigger: Quarterly planning.
- Steps today: Export ages and warranties; Build replacement budget.
- Pain today: Surprise failures; unplanned spend.
- Human in the loop: Read-only forecast; recommendations reviewed by the account manager.
- Repo: planned: Phase 6 (renewal alerts).

**`W-EP-11` Local admin password (LAPS) retrieval and admin-rights requests**
- Trigger: User needs elevated install or technician needs local admin.
- Steps today: Check approval; Retrieve LAPS password; Use and let it rotate.
- Pain today: Shared local admin passwords; standing admin rights.
- Human in the loop: Retrieval is human; password values never reach a model or log. Agents may report LAPS coverage only.
- Repo: not planned (report of coverage proposed Phase 4).

## PAT: Patching

| Id | Work | Who today | Volume (est.) | Systems | Sensitivity | Pattern | Risk | Repo |
|---|---|---|---|---|---|---|---|---|
| `W-PAT-01` | Monthly patch review and ring approval | Tier 3 engineer | monthly; 50-150 updates reviewed | RMM, Intune | internal | report | R2 | gap (proposed) |
| `W-PAT-02` | Patch compliance reporting per client | Service delivery manager | monthly x 50-500 clients | RMM, Intune | internal | report + eval | R0 | planned |
| `W-PAT-03` | Failed patch remediation | Tier 1/2 technician | 2-5% of endpoints per cycle (60-1,500 devices/month) | RMM | internal | agent-triage + write-lever-approval | R2 | planned |
| `W-PAT-04` | Third-party application patching | Tier 1/2 technician | weekly | RMM | internal | write-lever-approval | R2 | planned |
| `W-PAT-05` | Emergency patch for actively exploited vulnerabilities | Tier 3 engineer / security analyst | 2-8 relevant advisories/month | RMM, Intune, Defender | internal | read-lever + report | R2 | gap (proposed) |
| `W-PAT-06` | Server patch windows and client notice | Tier 2/3 engineer | monthly; 100-600 servers | RMM, PSA, email | internal | write-lever-approval | R2 | planned |
| `W-PAT-07` | Network device firmware (firewalls, switches, access points) | Tier 3 engineer | monthly; 100-1,000 devices | firewall, documentation | internal | report + none-keep-human | R3 | gap (proposed) |

**`W-PAT-01` Monthly patch review and ring approval**
- Trigger: Patch Tuesday (second Tuesday).
- Steps today: Read release notes and known issues; Approve for pilot ring; Promote to broad ring.
- Pain today: Hours of reading; known-issue regressions missed.
- Human in the loop: Agent summarizes notes and known issues with citations; ring promotion is an engineer decision.
- Repo: not in blueprint; proposed Phase 4.

**`W-PAT-02` Patch compliance reporting per client**
- Trigger: Monthly.
- Steps today: Export RMM patch report; Clean it up; Attach to client report.
- Pain today: Manual cleanup; numbers disagree between tools.
- Human in the loop: Read-only; numbers reconcile to source exports (validator).
- Repo: planned: Phase 6.

**`W-PAT-03` Failed patch remediation**
- Trigger: Install failure alert.
- Steps today: Read error code; Clear update cache; Retry.
- Pain today: Same fix applied by hand hundreds of times.
- Human in the loop: Agent groups by error code; technician approves the retry lever per batch.
- Repo: planned: Phase 3/4.

**`W-PAT-04` Third-party application patching**
- Trigger: Vendor release.
- Steps today: Approve new versions in RMM catalog; Deploy; Handle failures.
- Pain today: Browsers and readers lag behind.
- Human in the loop: Catalog-driven; technician approves new versions.
- Repo: planned: Phase 4.

**`W-PAT-05` Emergency patch for actively exploited vulnerabilities**
- Trigger: CISA Known Exploited Vulnerabilities addition or vendor advisory.
- Steps today: Read advisory; Find affected devices; Patch out of band; Tell clients.
- Pain today: Slow exposure mapping across many clients.
- Human in the loop: Agent matches the public KEV catalog to inventory (read-only); deployment is approved by an engineer.
- Repo: not in blueprint; proposed Phase 4.

**`W-PAT-06` Server patch windows and client notice**
- Trigger: Monthly.
- Steps today: Agree window; Notify client; Patch; Check services after.
- Pain today: Reboots during business; missed post-checks.
- Human in the loop: Lead approves; agent drafts notices for human send; post-patch checks read-only.
- Repo: planned: Phase 4.

**`W-PAT-07` Network device firmware (firewalls, switches, access points)**
- Trigger: Vendor advisory or schedule.
- Steps today: Read advisory; Schedule window; Upgrade by hand.
- Pain today: A failed upgrade takes a whole office offline.
- Human in the loop: Agent may report versions against advisories; upgrades are human.
- Repo: not in blueprint; report proposed Phase 4.

## BDR: Backup and disaster recovery

| Id | Work | Who today | Volume (est.) | Systems | Sensitivity | Pattern | Risk | Repo |
|---|---|---|---|---|---|---|---|---|
| `W-BDR-01` | Daily backup job review | NOC / Tier 1 technician | 1,000-10,000 jobs/day; 1-3% fail | backup, PSA | internal | read-lever + agent-triage | R0 | gap (proposed) |
| `W-BDR-02` | Failed backup remediation | Tier 1/2 technician | 300-3,000/month | backup | internal | write-lever-approval | R2 | gap (proposed) |
| `W-BDR-03` | Restore requests (file, mailbox, VM) | Tier 1/2 technician | 50-200/month | backup, PSA | regulated | write-lever-approval | R2 | gap (proposed) |
| `W-BDR-04` | Scheduled restore tests | Tier 2 technician | quarterly per client | backup, documentation | regulated (test data is real client data in practice) | write-lever-approval + report | R1 | gap (proposed) |
| `W-BDR-05` | Microsoft 365 backup coverage check | Tier 2 technician | weekly x tenants | backup, Graph/Entra | internal | report | R0 | gap (proposed) |
| `W-BDR-06` | Disaster recovery plan upkeep and tabletop exercise | vCIO / Tier 3 engineer | yearly per client | documentation | confidential | report | R0 | gap (proposed) |
| `W-BDR-07` | Ransomware or disaster recovery decision | Tier 3 engineer, leadership and client | rare (0-2/year per 100 clients) | backup, Defender, documentation | regulated | none-keep-human | R3 | not planned |
| `W-BDR-08` | Backup retention and immutability review | Tier 3 engineer | quarterly per client | backup | internal | report | R0 | gap (proposed) |

**`W-BDR-01` Daily backup job review**
- Trigger: Every morning.
- Steps today: Open each backup console; Note failures; Open tickets.
- Pain today: Multiple consoles; failures missed for days.
- Human in the loop: Read-only grouping and ticket draft; technician confirms.
- Repo: not in blueprint: no backup adapter is listed; proposed Phase 4 (adapters/backup).

**`W-BDR-02` Failed backup remediation**
- Trigger: Failed job.
- Steps today: Read error; Fix space or credentials; Rerun.
- Pain today: Repetitive.
- Human in the loop: Rerun lever with technician approval; configuration changes are human.
- Repo: proposed Phase 4.

**`W-BDR-03` Restore requests (file, mailbox, VM)**
- Trigger: User or client request.
- Steps today: Verify requester; Pick restore point; Restore to original or alternate location.
- Pain today: Restoring over newer data; restoring to the wrong person.
- Human in the loop: Restore to an alternate location with technician approval. In-place restore (overwrite) is R3 and human-run.
- Repo: proposed Phase 4.

**`W-BDR-04` Scheduled restore tests**
- Trigger: Monthly or quarterly schedule.
- Steps today: Restore a sample to a sandbox; Check it opens; Record evidence.
- Pain today: Rarely done; backups assumed good.
- Human in the loop: Restore to an isolated sandbox only; evidence written to the audit log; technician approves.
- Repo: proposed Phase 4 (evidence bundle).

**`W-BDR-05` Microsoft 365 backup coverage check**
- Trigger: Weekly.
- Steps today: Compare licensed users to protected users.
- Pain today: New hires not added to backup.
- Human in the loop: Read-only gap report.
- Repo: proposed Phase 4.

**`W-BDR-06` Disaster recovery plan upkeep and tabletop exercise**
- Trigger: Annual or after major change.
- Steps today: Update the plan; Run a tabletop with the client.
- Pain today: Plans go stale; nobody rehearses.
- Human in the loop: Agent drafts from current documentation and flags stale sections; humans own the plan and run the exercise.
- Repo: not in blueprint; proposed Phase 6.

**`W-BDR-07` Ransomware or disaster recovery decision**
- Trigger: Major incident.
- Steps today: Declare disaster; Choose clean restore point; Sequence recovery.
- Pain today: Highest stakes in the business.
- Human in the loop: NEVER AUTOMATE. Agents may only fetch read-only status for the people in charge.
- Repo: not planned (by design).

**`W-BDR-08` Backup retention and immutability review**
- Trigger: Quarterly.
- Steps today: Check retention and immutability settings against contract.
- Pain today: Retention silently shortened; no immutable copy.
- Human in the loop: Read-only report; changes are human.
- Repo: proposed Phase 4.

## SEC: Security monitoring and alerting

| Id | Work | Who today | Volume (est.) | Systems | Sensitivity | Pattern | Risk | Repo |
|---|---|---|---|---|---|---|---|---|
| `W-SEC-01` | Security alert intake and grouping | Security analyst / NOC | hundreds to thousands raw/day; 20-80 needing a look | Defender, PSA, firewall | confidential | agent-triage + eval | R0 | planned |
| `W-SEC-02` | Alert enrichment | Security analyst | 600-2,400/month | Defender, Graph/Entra, RMM, PSA | confidential | read-lever + report | R0 | planned |
| `W-SEC-03` | User-reported phishing triage | Tier 1 technician / security analyst | 200-800/month | Exchange Online, Defender, PSA | confidential | agent-triage + write-lever-approval | R2 | partial |
| `W-SEC-04` | Business email compromise containment | Security analyst / Tier 2 technician | 2-10/month | Graph/Entra, Exchange Online, Defender, PSA | regulated | write-lever-approval | R3 | partial |
| `W-SEC-05` | Endpoint isolation | Security analyst / on-call engineer | 2-10/month | Defender, RMM | regulated | write-lever-approval | R3 | planned |
| `W-SEC-06` | Vulnerability scan review and prioritization | Security analyst / Tier 3 engineer | monthly per client; thousands of findings | Defender, RMM, PSA | confidential | report | R0 | planned |
| `W-SEC-07` | Security incident declaration and breach notification decision | Leadership, client and client's counsel | rare | documentation, email | regulated | none-keep-human | R3 | not planned |
| `W-SEC-08` | Threat advisory relevance check | Security analyst | 10-40/month | documentation, RMM | internal | read-lever + report | R0 | gap (proposed) |
| `W-SEC-09` | Firewall and SASE rule changes | Tier 3 engineer | 20-80/month | firewall | confidential | none-keep-human | R3 | not planned |
| `W-SEC-10` | Security awareness training and phishing simulation results | Account manager / security analyst | monthly per client | vendor portal, PSA | confidential (per-person results) | report | R0 | gap (proposed) |

**`W-SEC-01` Security alert intake and grouping**
- Trigger: Alert from Defender, EDR, SIEM or firewall.
- Steps today: Read each alert; Close noise; Open tickets for real ones.
- Pain today: Alert fatigue; real attacks buried.
- Human in the loop: Grouping and severity suggestion with reasons; analyst decides. Closing an alert as benign stays human until evals justify a rule.
- Repo: planned: Phase 2 (grouping), Phase 4 (security).

**`W-SEC-02` Alert enrichment**
- Trigger: Alert opened.
- Steps today: Look up user, device, recent sign-ins, past tickets by hand.
- Pain today: Ten minutes of lookups per alert.
- Human in the loop: Read-only enrichment shown with sources.
- Repo: planned: Phase 4.

**`W-SEC-03` User-reported phishing triage**
- Trigger: User reports an email.
- Steps today: Look at headers and links; Decide; Purge from other mailboxes if malicious.
- Pain today: Slow answers teach users not to report.
- Human in the loop: Agent gives a verdict with indicators (email treated as untrusted input); purge across mailboxes needs analyst approval.
- Repo: partial: injection tripwire core/guard, evals/injection; phishing triage proposed Phase 4.

**`W-SEC-04` Business email compromise containment**
- Trigger: Confirmed or likely account takeover.
- Steps today: Revoke sessions; Reset password and MFA; Remove malicious rules; Block sender; Notify client.
- Pain today: Minutes matter; steps missed under pressure.
- Human in the loop: Playbook of levers, each dry-run then lead-approved; the client is told by a human.
- Repo: partial: user.disable and user.reset-mfa (mocked); playbook planned Phase 3/4.

**`W-SEC-05` Endpoint isolation**
- Trigger: Malware or ransomware behavior detected.
- Steps today: Isolate the device in Defender; Tell the client; Investigate.
- Pain today: Isolating a clinic's only front-desk PC stops patient check-in.
- Human in the loop: Lead approval (on-call may self-approve under written policy, audited); client told by a human.
- Repo: planned: Phase 4.

**`W-SEC-06` Vulnerability scan review and prioritization**
- Trigger: Scheduled scan result.
- Steps today: Export findings; Rank; Open remediation tickets.
- Pain today: Lists too long to act on.
- Human in the loop: Read-only ranking with exploitability source (for example KEV); humans pick what to fix.
- Repo: planned: Phase 4.

**`W-SEC-07` Security incident declaration and breach notification decision**
- Trigger: Confirmed incident.
- Steps today: Assess scope; Decide if it is a reportable breach (for example HIPAA, FTC Safeguards); Notify.
- Pain today: Legal deadlines and liability.
- Human in the loop: NEVER AUTOMATE. Breach determination and notification are legal decisions owned by the client with counsel. Agents may assemble a factual timeline from the audit log.
- Repo: not planned (by design); timeline export planned Phase 10 (AI incident response).

**`W-SEC-08` Threat advisory relevance check**
- Trigger: New public advisory (CISA, vendor).
- Steps today: Read advisory; Decide which clients are exposed.
- Pain today: Advisories read late or not at all.
- Human in the loop: Read-only match against inventory; humans decide action.
- Repo: proposed Phase 4.

**`W-SEC-09` Firewall and SASE rule changes**
- Trigger: Request or project.
- Steps today: Review request; Change rule; Test.
- Pain today: Mistakes open exposure or cut connectivity.
- Human in the loop: Human change with change record. Agents may diff current rules against documentation (read-only) later.
- Repo: not planned.

**`W-SEC-10` Security awareness training and phishing simulation results**
- Trigger: Monthly campaign.
- Steps today: Export results; Find repeat clickers; Report to client.
- Pain today: Results never reach the client in a usable form.
- Human in the loop: Aggregate report; per-person results shared only with the client's named contact; never used by the MSP to rate individuals.
- Repo: proposed Phase 6.

## CMP: Compliance evidence

| Id | Work | Who today | Volume (est.) | Systems | Sensitivity | Pattern | Risk | Repo |
|---|---|---|---|---|---|---|---|---|
| `W-CMP-01` | SOC 2 evidence collection for the MSP's own audit | Compliance lead / service delivery manager | continuous; 50-200 evidence items per audit | PSA, Graph/Entra, backup, documentation | confidential | report | R0 | partial |
| `W-CMP-02` | Client HIPAA security risk analysis support | vCIO / compliance lead with the client | yearly per healthcare client | Graph/Entra, Intune, backup, documentation | regulated (PHI context) | report | R0 | planned |
| `W-CMP-03` | Client FTC Safeguards Rule evidence (financial clients) | vCIO / compliance lead with the client | yearly per financial client | Graph/Entra, Intune, documentation | regulated (NPI context) | report | R0 | planned |
| `W-CMP-04` | Change records and change advisory review | Tier 3 engineer / service delivery manager | 50-200 changes/month | PSA, documentation | internal | report | R1 | partial |
| `W-CMP-05` | Audit log integrity verification | Compliance lead / AI & Automation Engineer | daily | documentation | confidential | eval | R0 | exists |
| `W-CMP-06` | Business associate agreements and vendor due diligence tracking | Compliance lead / account manager | 5-20/month | documentation | confidential | report | R0 | gap (proposed) |
| `W-CMP-07` | Policy attestations and management assertions | Leadership / compliance lead | quarterly | documentation | confidential | none-keep-human | R3 | not planned |
| `W-CMP-08` | Cyber insurance questionnaires | vCIO / account manager | 10-40/month | documentation, Graph/Entra | confidential | report | R0 | gap (proposed) |
| `W-CMP-09` | Client security questionnaires about the MSP itself | Account manager / compliance lead | 5-20/month | documentation | confidential | report | R0 | planned |

**`W-CMP-01` SOC 2 evidence collection for the MSP's own audit**
- Trigger: Audit period, quarterly sampling.
- Steps today: Screenshot settings; Pull tickets for sampled changes; Export access reviews.
- Pain today: Weeks of screenshots each audit.
- Human in the loop: Read-only dated, hashed evidence bundle; the compliance lead reviews before it goes to the auditor.
- Repo: partial: core/audit (hash chain), core/audit/verify.py; evidence bundle planned Phase 4; control map Phase 10.

**`W-CMP-02` Client HIPAA security risk analysis support**
- Trigger: Annual or after major change.
- Steps today: Gather technical safeguards evidence; Discuss with client; Write findings.
- Pain today: Mostly manual evidence gathering.
- Human in the loop: Agent gathers technical evidence only; the risk analysis and its conclusions belong to the client (the covered entity) and a human assessor.
- Repo: planned: Phase 4 (evidence), Phase 10 (mapping).

**`W-CMP-03` Client FTC Safeguards Rule evidence (financial clients)**
- Trigger: Annual report to the client's board or on request.
- Steps today: Show MFA, encryption, logging, access reviews.
- Pain today: Clients do not know what evidence exists.
- Human in the loop: Read-only evidence; the client's Qualified Individual owns the program and the report.
- Repo: planned: Phase 4, Phase 10.

**`W-CMP-04` Change records and change advisory review**
- Trigger: Any non-standard change.
- Steps today: Write change record; Get approval; Record outcome.
- Pain today: Changes undocumented; weak audit trail.
- Human in the loop: Agent drafts the change record from the lever dry-run diff; approval is human.
- Repo: partial: dry-run diffs in core/levers/diff.py; change process planned Phase 10.

**`W-CMP-05` Audit log integrity verification**
- Trigger: Daily or before evidence export.
- Steps today: Run the verifier; Investigate breaks.
- Pain today: Logs that cannot be proven unaltered are weak evidence.
- Human in the loop: Automatic check; a break is a human-investigated incident.
- Repo: exists: core/audit/chain.py, core/audit/verify.py, Verify button in ui/app.py.

**`W-CMP-06` Business associate agreements and vendor due diligence tracking**
- Trigger: New vendor or renewal.
- Steps today: Track who signed what; Chase renewals.
- Pain today: Agreements expire unnoticed.
- Human in the loop: Read-only tracker; legal review human.
- Repo: not in blueprint; proposed Phase 10.

**`W-CMP-07` Policy attestations and management assertions**
- Trigger: Audit or client request.
- Steps today: Read; Sign.
- Pain today: None to automate.
- Human in the loop: NEVER AUTOMATE. A signature is a person's accountable statement.
- Repo: not planned (by design).

**`W-CMP-08` Cyber insurance questionnaires**
- Trigger: Client renewal.
- Steps today: Answer 50-150 control questions from memory and screenshots.
- Pain today: Wrong answers can void coverage.
- Human in the loop: Agent drafts answers with evidence links; a human checks every answer; unsupported answers are left blank, not guessed.
- Repo: not in blueprint; proposed Phase 6.

**`W-CMP-09` Client security questionnaires about the MSP itself**
- Trigger: Prospect or client vendor-risk review.
- Steps today: Find past answers; Adapt; Send.
- Pain today: Repeated work; inconsistent answers.
- Human in the loop: RAG over approved answers with citations; a human approves and sends.
- Repo: planned: Phase 5 (RAG).

## VND: Vendor and license management

| Id | Work | Who today | Volume (est.) | Systems | Sensitivity | Pattern | Risk | Repo |
|---|---|---|---|---|---|---|---|---|
| `W-VND-01` | License reconciliation | Billing / service delivery manager | monthly x 50-500 tenants | Graph/Entra, vendor portal, PSA | internal | report | R0 | planned |
| `W-VND-02` | License purchase or reduction | Account manager / billing | 50-200/month | vendor portal, PSA | internal (spend) | none-keep-human | R3 | not planned |
| `W-VND-03` | Renewal alerts (subscriptions, warranties, domains) | Account manager | 100-400/month | PSA, vendor portal, documentation | internal | report | R0 | planned |
| `W-VND-04` | Vendor and ISP escalation | Tier 2/3 technician | 20-60/month | PSA, email, phone | confidential | report | R1 | gap (proposed) |
| `W-VND-05` | TLS certificate expiry monitoring | Tier 2 technician | 20-80/month | documentation, firewall | internal | report | R0 | planned |
| `W-VND-06` | Domain and DNS registrar changes | Tier 3 engineer | 10-40/month | vendor portal, documentation | confidential | none-keep-human | R3 | not planned |

**`W-VND-01` License reconciliation**
- Trigger: Monthly.
- Steps today: Compare purchased, assigned and active seats.
- Pain today: Paying for unused seats; under-billing.
- Human in the loop: Read-only; recommendations reviewed by billing.
- Repo: planned: Phase 6.

**`W-VND-02` License purchase or reduction**
- Trigger: Need for seats or reduction.
- Steps today: Get client approval; Order in the cloud distributor portal.
- Pain today: Commitments made without client sign-off.
- Human in the loop: NEVER AUTOMATE spending. Agents may recommend; the client approves and a human orders.
- Repo: not planned (recommendation only, Phase 6).

**`W-VND-03` Renewal alerts (subscriptions, warranties, domains)**
- Trigger: Upcoming expiry.
- Steps today: Track in spreadsheets; Remind client.
- Pain today: Lapsed renewals cause outages.
- Human in the loop: Read-only alerts.
- Repo: planned: Phase 6.

**`W-VND-04` Vendor and ISP escalation**
- Trigger: Third-party outage or bug.
- Steps today: Open vendor case; Repeat details; Chase.
- Pain today: Re-explaining the case; slow vendors.
- Human in the loop: Agent drafts the case summary without client secrets; a human submits.
- Repo: not in blueprint; proposed Phase 2 (summaries).

**`W-VND-05` TLS certificate expiry monitoring**
- Trigger: Upcoming expiry.
- Steps today: Check certificates; Renew; Install.
- Pain today: Sites and VPNs break on expiry.
- Human in the loop: Read-only alerts; renewal human.
- Repo: planned: Phase 6 (renewal alerts).

**`W-VND-06` Domain and DNS registrar changes**
- Trigger: Client request or project.
- Steps today: Log in to registrar; Change records.
- Pain today: One wrong record stops email for a whole client.
- Human in the loop: Human only with change record; agents may validate a proposed record set (read-only).
- Repo: not planned.

## RPT: Client reporting and QBRs

| Id | Work | Who today | Volume (est.) | Systems | Sensitivity | Pattern | Risk | Repo |
|---|---|---|---|---|---|---|---|---|
| `W-RPT-01` | Monthly client health report | Service delivery manager / account manager | 50-500 reports/month | PSA, RMM, backup, Graph/Entra | confidential | report + eval | R0 | planned |
| `W-RPT-02` | Quarterly business review draft | vCIO / account manager | 15-150/month | PSA, RMM, documentation | confidential | report + eval | R0 | planned |
| `W-RPT-03` | Weekly 'what we did for you' digest | Account manager | weekly per client | PSA, email | confidential | report | R1 | planned |
| `W-RPT-04` | Technology roadmap and budget recommendations | vCIO | yearly per client | documentation, PSA, RMM | confidential | report | R0 | planned |
| `W-RPT-05` | Client AI-use policy starter | vCIO / account manager | 5-20/month | documentation | internal | report | R0 | planned |
| `W-RPT-06` | Internal operations metrics (resolution time, first-contact resolution, SLA, backlog) | Service delivery manager / leadership | weekly | PSA | internal | report | R0 | planned |

**`W-RPT-01` Monthly client health report**
- Trigger: Month end.
- Steps today: Export tickets, patching, backups, security; Assemble; Write commentary.
- Pain today: Days of copy-paste each month.
- Human in the loop: Every number reconciles to source data (validator gate); account manager reviews and sends.
- Repo: planned: Phase 6.

**`W-RPT-02` Quarterly business review draft**
- Trigger: Quarter.
- Steps today: Build slides; Pick highlights and risks; Write roadmap.
- Pain today: Prep time limits how many clients get QBRs.
- Human in the loop: Draft only; the account manager owns the story and the recommendations.
- Repo: planned: Phase 6.

**`W-RPT-03` Weekly 'what we did for you' digest**
- Trigger: Weekly.
- Steps today: Rarely done by hand.
- Pain today: Clients do not see the work being done.
- Human in the loop: Draft for human send.
- Repo: planned: Phase 6, Phase 9 (Outlook draft).

**`W-RPT-04` Technology roadmap and budget recommendations**
- Trigger: Annual planning.
- Steps today: Review assets, risks, goals; Write plan.
- Pain today: Time-intensive.
- Human in the loop: Agent assembles facts; recommendations and pricing are human.
- Repo: planned: Phase 6.

**`W-RPT-05` Client AI-use policy starter**
- Trigger: Client asks about AI.
- Steps today: Write from scratch.
- Pain today: Clients adopt AI with no policy.
- Human in the loop: Template draft; client and their counsel own the final policy.
- Repo: planned: Phase 6.

**`W-RPT-06` Internal operations metrics (resolution time, first-contact resolution, SLA, backlog)**
- Trigger: Weekly and monthly.
- Steps today: PSA exports to spreadsheets or Power BI.
- Pain today: Metrics debated instead of acted on.
- Human in the loop: Read-only; metrics describe the queue, not individual performance reviews (see W-TRN-04 note).
- Repo: planned: Phase 6 (Power BI exports).

## KB: Documentation and knowledge base

| Id | Work | Who today | Volume (est.) | Systems | Sensitivity | Pattern | Risk | Repo |
|---|---|---|---|---|---|---|---|---|
| `W-KB-01` | KB article drafting from resolved tickets | Tier 1-3 technician | 20-80 articles/month | PSA, documentation | confidential (must strip client specifics) | report + eval | R1 | planned |
| `W-KB-02` | Client documentation upkeep (network, contacts, configurations) | Tier 2 technician | continuous | documentation, RMM | confidential | report | R1 | planned |
| `W-KB-03` | Runbook and SOP authoring | Tier 3 engineer / AI & Automation Engineer | 5-20/month | documentation | internal | report | R0 | partial |
| `W-KB-04` | Cited question answering for technicians (RAG) | Tier 1-3 technician | 2,000-6,000 questions/month | documentation | confidential | read-lever + eval | R0 | partial |
| `W-KB-05` | Stale and conflicting article detection | Documentation owner | monthly | documentation | internal | eval + report | R0 | planned |
| `W-KB-06` | Authorized contacts and escalation lists per client | Account manager | 20-60 updates/month | documentation, PSA | confidential | read-lever | R0 | planned |
| `W-KB-07` | Credential vault entries in the documentation platform | Tier 1-3 technician | daily | documentation | confidential (secrets) | none-keep-human | R3 | not planned |

**`W-KB-01` KB article drafting from resolved tickets**
- Trigger: Ticket closed with a reusable fix.
- Steps today: Rarely done; written from memory later.
- Pain today: Knowledge stays in heads.
- Human in the loop: Draft only; a technician reviews and publishes; client data stripped and checked.
- Repo: planned: Phase 2.

**`W-KB-02` Client documentation upkeep (network, contacts, configurations)**
- Trigger: Change or periodic review.
- Steps today: Update pages by hand after changes.
- Pain today: Docs drift; technicians work from stale facts.
- Human in the loop: Agent flags stale pages against live data and drafts updates; human approves.
- Repo: planned: Phase 5.

**`W-KB-03` Runbook and SOP authoring**
- Trigger: New process or lever.
- Steps today: Write in the documentation platform.
- Pain today: Inconsistent quality.
- Human in the loop: AI-assisted drafts; author owns the content.
- Repo: partial: docs/RUNBOOKS.md (Phase 0); product runbooks with phases.

**`W-KB-04` Cited question answering for technicians (RAG)**
- Trigger: Technician question during a ticket.
- Steps today: Search docs; Ask a senior technician.
- Pain today: Seniors interrupted; answers not grounded.
- Human in the loop: Answers cite the client's own documents; refuses when there is no source; client A never sees client B.
- Repo: partial: kb.search lever (keyword, mocked); RAG planned Phase 5.

**`W-KB-05` Stale and conflicting article detection**
- Trigger: Monthly.
- Steps today: Rarely done.
- Pain today: Two articles give opposite instructions.
- Human in the loop: Read-only report; owner fixes.
- Repo: planned: Phase 5.

**`W-KB-06` Authorized contacts and escalation lists per client**
- Trigger: Client change.
- Steps today: Edit contact pages.
- Pain today: Stale lists defeat requester verification.
- Human in the loop: Agents read the list to check requesters; only a human edits it, on the client's instruction.
- Repo: planned: Phase 3 (read lever).

**`W-KB-07` Credential vault entries in the documentation platform**
- Trigger: Any credential use.
- Steps today: Open the vault; Copy password.
- Pain today: Most sensitive store the MSP holds.
- Human in the loop: NEVER AUTOMATE access by an AI. Vault contents are excluded from retrieval, prompts and logs; levers use their own managed identities instead.
- Repo: not planned (by design); exclusion rule planned Phase 5 and Phase 10 (DLP mapping).

## BIL: Billing inputs

| Id | Work | Who today | Volume (est.) | Systems | Sensitivity | Pattern | Risk | Repo |
|---|---|---|---|---|---|---|---|---|
| `W-BIL-01` | Time entry and ticket note quality | Tier 1-3 technician | 5,000-15,000 entries/month | PSA | confidential | report | R1 | gap (proposed) |
| `W-BIL-02` | Per-seat and per-device count true-up | Billing | monthly x 50-500 agreements | PSA, RMM, Graph/Entra | internal | report + eval | R0 | planned |
| `W-BIL-03` | Managed versus project or out-of-scope classification | Service desk lead / billing | 5-15% of tickets need a decision | PSA | internal | agent-triage | R1 | gap (proposed) |
| `W-BIL-04` | Contract terms, pricing and billing disputes | Leadership / billing / account manager | 5-20/month | PSA, accounting | confidential | none-keep-human | R3 | not planned |

**`W-BIL-01` Time entry and ticket note quality**
- Trigger: Work done on a ticket.
- Steps today: Type notes and time at end of day from memory.
- Pain today: Lost time; notes too thin to bill or audit.
- Human in the loop: Agent drafts notes from lever and ticket activity; the technician confirms time and wording.
- Repo: not in blueprint; proposed Phase 2.

**`W-BIL-02` Per-seat and per-device count true-up**
- Trigger: Month end.
- Steps today: Pull counts from three systems; Reconcile; Adjust invoices.
- Pain today: Revenue leakage and client disputes.
- Human in the loop: Read-only reconciliation; billing approves every change.
- Repo: planned: Phase 6.

**`W-BIL-03` Managed versus project or out-of-scope classification**
- Trigger: Ticket closed.
- Steps today: Read ticket; Check agreement; Mark billable.
- Pain today: Inconsistent; client friction.
- Human in the loop: Suggestion with the agreement clause; a human decides.
- Repo: not in blueprint; proposed Phase 6.

**`W-BIL-04` Contract terms, pricing and billing disputes**
- Trigger: Dispute or renewal.
- Steps today: Negotiate.
- Pain today: Relationship-critical.
- Human in the loop: NEVER AUTOMATE. Commercial relationships are human; agents may fetch facts.
- Repo: not planned (by design).

## PRJ: Project work

| Id | Work | Who today | Volume (est.) | Systems | Sensitivity | Pattern | Risk | Repo |
|---|---|---|---|---|---|---|---|---|
| `W-PRJ-01` | New client onboarding to the MSP (discovery and baseline) | Project engineer | 1-8 new clients/month | Graph/Entra, RMM, Intune, documentation | confidential | read-lever + report | R0 | partial |
| `W-PRJ-02` | Client offboarding from the MSP | Project engineer / leadership | 0-4/month | Graph/Entra, RMM, documentation | confidential | none-keep-human | R3 | gap (proposed) |
| `W-PRJ-03` | Microsoft 365 migrations (tenant to tenant, mailbox moves) | Project engineer | 1-4/month | Graph/Entra, Exchange Online, SharePoint | regulated | write-lever-approval | R3 | gap (proposed) |
| `W-PRJ-04` | Copilot and AI adoption readiness for clients | vCIO / Tier 3 engineer | 5-20/month | Graph/Entra, SharePoint, Purview | regulated | report | R0 | planned |
| `W-PRJ-05` | Azure infrastructure projects | Project engineer | 1-5/month | Azure | confidential | write-lever-approval | R3 | planned |
| `W-PRJ-06` | Project scoping and estimates | Project engineer / account manager | 10-30/month | PSA, documentation | internal | report | R0 | gap (proposed) |

**`W-PRJ-01` New client onboarding to the MSP (discovery and baseline)**
- Trigger: Signed agreement.
- Steps today: Inventory tenant, devices, network; Document; Fix baseline gaps.
- Pain today: Weeks of discovery; gaps missed.
- Human in the loop: Read-only discovery report; remediation goes through normal approved levers.
- Repo: partial: levers/powershell/TenantBaseline (mocked); full discovery planned Phase 4/6.

**`W-PRJ-02` Client offboarding from the MSP**
- Trigger: Contract ends.
- Steps today: Hand back admin access and documentation; Remove agents and delegated access.
- Pain today: Must be clean and respectful; access must truly end.
- Human in the loop: Human-run; agents may produce the checklist and the read-only proof that MSP access is gone.
- Repo: not in blueprint; checklist proposed Phase 10.

**`W-PRJ-03` Microsoft 365 migrations (tenant to tenant, mailbox moves)**
- Trigger: Project.
- Steps today: Plan; Pre-stage; Cut over; Clean up.
- Pain today: Data loss and downtime risk.
- Human in the loop: Scripted batches with dry-run and engineer approval per batch.
- Repo: not in blueprint; proposed after Phase 3.

**`W-PRJ-04` Copilot and AI adoption readiness for clients**
- Trigger: Client interest.
- Steps today: Assess licensing, oversharing, labels; Recommend.
- Pain today: Clients enable AI over data they have not cleaned.
- Human in the loop: Read-only assessment and score; recommendation reviewed by a human.
- Repo: planned: Phase 4.

**`W-PRJ-05` Azure infrastructure projects**
- Trigger: Project.
- Steps today: Click-ops in the portal or ad-hoc scripts.
- Pain today: Undocumented, unrepeatable builds.
- Human in the loop: Infrastructure as code, validate and what-if first; engineer approves the deployment.
- Repo: planned: Phase 8 (validate only in this repo).

**`W-PRJ-06` Project scoping and estimates**
- Trigger: Client request.
- Steps today: Estimate from experience.
- Pain today: Over- or under-scoped projects.
- Human in the loop: Agent finds similar past projects (RAG); the estimate is human.
- Repo: not in blueprint; proposed Phase 5/6.

## TOOL: Internal tooling and the AI/automation platform

| Id | Work | Who today | Volume (est.) | Systems | Sensitivity | Pattern | Risk | Repo |
|---|---|---|---|---|---|---|---|---|
| `W-TOOL-01` | Lever authoring (new PowerShell or Python lever) | AI & Automation Engineer | 4-12 levers/month | Azure DevOps, documentation | internal | eval | R1 | exists |
| `W-TOOL-02` | Model gateway and routing configuration | AI & Automation Engineer | monthly | model gateway | internal | eval | R1 | exists |
| `W-TOOL-03` | Prompt library and standards | AI & Automation Engineer | continuous | documentation | internal | eval | R0 | planned |
| `W-TOOL-04` | Eval golden sets and accuracy reports | AI & Automation Engineer | weekly | documentation | internal (synthetic data only) | eval | R0 | exists |
| `W-TOOL-05` | Prompt-injection corpus and guard maintenance | AI & Automation Engineer | monthly | documentation | internal | eval | R0 | exists |
| `W-TOOL-06` | Approval queue operation | Service desk lead (approver) | scales with write levers; 500-3,000 approvals/month | PSA, Teams | confidential | write-lever-approval | R1 | exists |
| `W-TOOL-07` | CI/CD pipelines and release process | AI & Automation Engineer | daily | Azure DevOps | internal | eval | R1 | partial |
| `W-TOOL-08` | Secrets and managed identity management | AI & Automation Engineer | monthly | Azure | confidential (secrets) | none-keep-human | R3 | planned |
| `W-TOOL-09` | Production monitoring of AI and automation | AI & Automation Engineer | continuous | Azure, model gateway | internal | report | R0 | planned |
| `W-TOOL-10` | MCP server and Teams technician assistant | AI & Automation Engineer | project | Teams, model gateway | confidential | read-lever + write-lever-approval | R1 | planned |
| `W-TOOL-11` | PSA, RMM and Graph integration maintenance | AI & Automation Engineer | monthly | PSA, RMM, Graph/Entra | internal | eval | R1 | planned |
| `W-TOOL-12` | Review of existing automation scripts | AI & Automation Engineer | quarterly | RMM, Azure DevOps | internal | report | R0 | planned |
| `W-TOOL-13` | Use-case intake and ROI scoring | AI & Automation Engineer with leadership | 5-20 ideas/month | documentation, Azure DevOps | internal | report | R0 | planned |
| `W-TOOL-14` | Emerging technology evaluation | AI & Automation Engineer | monthly | documentation | internal | eval + report | R0 | planned |

**`W-TOOL-01` Lever authoring (new PowerShell or Python lever)**
- Trigger: New use case approved.
- Steps today: Write schema, code, tests, dry-run, docs; Register.
- Pain today: Without the pattern, scripts sprawl untested.
- Human in the loop: Code review and passing tests before registration; registry changes are reviewed like code.
- Repo: exists: core/levers/, levers/registry.json, levers/powershell/TenantBaseline.

**`W-TOOL-02` Model gateway and routing configuration**
- Trigger: New model or eval result.
- Steps today: Change config; Re-run evals.
- Pain today: Locked-in providers; costs unknown.
- Human in the loop: Routing thresholds change only on eval evidence; hosted providers stay off unless approved.
- Repo: exists: core/gateway/ (mock and loopback Ollama; hosted stubs off); routing evals Phase 7.

**`W-TOOL-03` Prompt library and standards**
- Trigger: New workflow.
- Steps today: Version prompts; Test them.
- Pain today: Prompts copied around untested.
- Human in the loop: Prompt changes need passing prompt tests.
- Repo: planned: Phase 2 (prompts/).

**`W-TOOL-04` Eval golden sets and accuracy reports**
- Trigger: Each workflow change.
- Steps today: Label data; Run scorers; Publish report.
- Pain today: No proof that AI helps.
- Human in the loop: Reports labelled fixture-based; humans review labels.
- Repo: exists: evals/triage/report.py, evals/triage/report.md; broader Phase 7.

**`W-TOOL-05` Prompt-injection corpus and guard maintenance**
- Trigger: New attack pattern.
- Steps today: Add cases; Re-run detector.
- Pain today: Untrusted ticket and email text could steer agents.
- Human in the loop: Tripwire only; the lever registry is the control.
- Repo: exists: core/guard/, evals/injection/corpus.jsonl, evals/injection/report.py.

**`W-TOOL-06` Approval queue operation**
- Trigger: Pending proposal.
- Steps today: Review diff; Approve or reject.
- Pain today: Approval fatigue leads to rubber-stamping.
- Human in the loop: Approver cannot be the requester; approval is recorded in the audit chain; rejection reasons become eval data.
- Repo: exists: core/queue/, ui/ (local, CSRF-protected); Teams cards Phase 9.

**`W-TOOL-07` CI/CD pipelines and release process**
- Trigger: Every change.
- Steps today: Branch; Pull request; Review; Merge; Release.
- Pain today: Untested scripts reach client tenants.
- Human in the loop: Pull request review and green CI before merge.
- Repo: partial: .github/ CI skeleton; Azure DevOps pipeline Phase 8.

**`W-TOOL-08` Secrets and managed identity management**
- Trigger: New integration or rotation.
- Steps today: Store in Key Vault; Grant managed identity; Rotate.
- Pain today: Secrets in scripts and RMM variables.
- Human in the loop: Humans create and rotate secrets; code only references them; agents never read secret values.
- Repo: planned: Phase 8 (Bicep validate only); pre-commit secret scan exists (scripts/hooks).

**`W-TOOL-09` Production monitoring of AI and automation**
- Trigger: Continuous.
- Steps today: Watch failures, latency, cost, accuracy drift.
- Pain today: Silent failures.
- Human in the loop: Read-only dashboards and alerts; humans respond.
- Repo: planned: Phase 8.

**`W-TOOL-10` MCP server and Teams technician assistant**
- Trigger: Integration build.
- Steps today: Expose approved levers; Wire approval cards.
- Pain today: Uncontrolled tool access by AI clients.
- Human in the loop: Read-only by default; write levers keep their approval rules.
- Repo: planned: Phase 9.

**`W-TOOL-11` PSA, RMM and Graph integration maintenance**
- Trigger: API change, rate limit, outage.
- Steps today: Fix adapters; Handle throttling and retries.
- Pain today: Integrations break quietly.
- Human in the loop: Contract tests against mocks; changes through CI.
- Repo: planned: Phase 2/3/9 (adapters/).

**`W-TOOL-12` Review of existing automation scripts**
- Trigger: Onboarding to the role, then quarterly.
- Steps today: Inventory existing RMM scripts and flows; Rate risk; Migrate to levers.
- Pain today: Unknown scripts with broad rights.
- Human in the loop: Read-only review; migration through normal lever process.
- Repo: planned: Phase 10 (docs/AUTOMATION_FRAMEWORK_REVIEW.md).

**`W-TOOL-13` Use-case intake and ROI scoring**
- Trigger: Idea from staff.
- Steps today: Collect idea; Score value, risk, effort; Prioritize.
- Pain today: Loudest idea wins.
- Human in the loop: Scores are inputs; leadership decides priority.
- Repo: planned: Phase 10 (governance/USE_CASE_INTAKE.md, docs/planned/ROI_TRACKER.md).

**`W-TOOL-14` Emerging technology evaluation**
- Trigger: New model or tool.
- Steps today: Prototype; Evaluate; Recommend.
- Pain today: Hype-driven adoption.
- Human in the loop: Recommendations backed by repo evals and cited sources.
- Repo: planned: Phase 7/10 (docs/planned/TECH_RADAR.md).

## GOV: AI governance

| Id | Work | Who today | Volume (est.) | Systems | Sensitivity | Pattern | Risk | Repo |
|---|---|---|---|---|---|---|---|---|
| `W-GOV-01` | AI acceptable-use policy and data-in-prompt rules | AI & Automation Engineer with leadership | yearly plus changes | documentation | internal | report | R0 | planned |
| `W-GOV-02` | Model and tool approval | AI & Automation Engineer with leadership | monthly | documentation | internal | none-keep-human | R3 | planned |
| `W-GOV-03` | Agent identity and lever permission review | AI & Automation Engineer / service delivery manager | quarterly | documentation | confidential | report | R0 | partial |
| `W-GOV-04` | AI incident response | AI & Automation Engineer / security analyst | rare | documentation, PSA | regulated | none-keep-human | R3 | planned |

**`W-GOV-01` AI acceptable-use policy and data-in-prompt rules**
- Trigger: Policy cycle.
- Steps today: Write; Approve; Train.
- Pain today: Staff paste client data into public AI tools.
- Human in the loop: Leadership approves the policy.
- Repo: planned: Phase 10 (governance/AI_POLICY.md, governance/DLP_MAPPING.md).

**`W-GOV-02` Model and tool approval**
- Trigger: New model, provider or MCP server.
- Steps today: Review data terms and security; Approve or reject.
- Pain today: Unvetted tools with client data.
- Human in the loop: Approval of a provider or tool is a human decision recorded in DECISIONS.
- Repo: planned: Phase 10.

**`W-GOV-03` Agent identity and lever permission review**
- Trigger: Quarterly.
- Steps today: List which agent can press which lever for which client; Remove extras.
- Pain today: Agent permissions creep like human ones.
- Human in the loop: Read-only review; changes by human pull request.
- Repo: partial: core/identity/store.py, levers/registry.json; review report proposed Phase 4.

**`W-GOV-04` AI incident response**
- Trigger: Wrong action, data leak, injection success.
- Steps today: Stop the workflow; Assess; Fix; Tell affected parties.
- Pain today: No playbook today.
- Human in the loop: Humans lead; agents can be switched off by a single config change and supply the audit timeline.
- Repo: planned: Phase 10.

## TRN: Staff training on AI

| Id | Work | Who today | Volume (est.) | Systems | Sensitivity | Pattern | Risk | Repo |
|---|---|---|---|---|---|---|---|---|
| `W-TRN-01` | Technician training: reading suggestions and approvals | AI & Automation Engineer | monthly sessions | documentation | internal (synthetic examples) | report | R0 | planned |
| `W-TRN-02` | Account manager training: explaining AI to clients | AI & Automation Engineer | quarterly | documentation | internal | report | R0 | planned |
| `W-TRN-03` | Correction feedback loop coaching | Service desk lead | weekly | PSA | internal | eval + report | R0 | partial |
| `W-TRN-04` | New technician onboarding and performance coaching | Service desk lead / manager | 1-4 new technicians/month | documentation, PSA | confidential (personnel) | none-keep-human | R3 | not planned |

**`W-TRN-01` Technician training: reading suggestions and approvals**
- Trigger: New staff or new workflow.
- Steps today: Walk through examples.
- Pain today: Blind trust or blind distrust of AI output.
- Human in the loop: Human-led training with synthetic exercises.
- Repo: planned: Phase 10 (docs/planned/STAFF_TRAINING.md).

**`W-TRN-02` Account manager training: explaining AI to clients**
- Trigger: New offering.
- Steps today: Prepare talking points; Practice.
- Pain today: Over-promising to clients.
- Human in the loop: Human-led; claims limited to measured, labelled results.
- Repo: planned: Phase 10 (docs/planned/CLIENT_CONVERSATION_GUIDE.md).

**`W-TRN-03` Correction feedback loop coaching**
- Trigger: Weekly.
- Steps today: Review corrections; Explain patterns to the team.
- Pain today: Corrections not given, so the system never improves.
- Human in the loop: Corrections are about the system's accuracy, not a score of the technician.
- Repo: partial: workflows/triage/corrections.py (stores corrections as eval data).

**`W-TRN-04` New technician onboarding and performance coaching**
- Trigger: New hire or review cycle.
- Steps today: Shadowing; Reviews.
- Pain today: Slow ramp-up.
- Human in the loop: NEVER AUTOMATE judgments about people. AI may help a new technician learn (cited KB answers); AI output and metrics are never the basis for performance ratings or discipline.
- Repo: not planned (by design); learning support via Phase 5.

## Public sources

Used for the regulatory and Microsoft facts behind the risk and never-automate calls. Links were written from known public pages and were **not re-fetched in this session**; treat each as unverified until opened. No vendor numbers are used in this document.

- HHS, HIPAA Security Rule: https://www.hhs.gov/hipaa/for-professionals/security/index.html
- HHS, HIPAA risk analysis guidance: https://www.hhs.gov/hipaa/for-professionals/security/guidance/guidance-risk-analysis/index.html
- HHS, HIPAA Breach Notification Rule: https://www.hhs.gov/hipaa/for-professionals/breach-notification/index.html
- FTC, Safeguards Rule business guidance: https://www.ftc.gov/business-guidance/resources/ftc-safeguards-rule-what-your-business-needs-know
- eCFR, 16 CFR Part 314 (Safeguards Rule text): https://www.ecfr.gov/current/title-16/chapter-I/subchapter-C/part-314
- CISA, Known Exploited Vulnerabilities catalog: https://www.cisa.gov/known-exploited-vulnerabilities-catalog
- NIST, Cybersecurity Framework 2.0: https://www.nist.gov/cyberframework
- NIST, SP 800-61 Rev. 3 incident response: https://csrc.nist.gov/pubs/sp/800/61/r3/final
- NIST, AI Risk Management Framework: https://www.nist.gov/itl/ai-risk-management-framework
- AICPA, SOC 2 overview: https://www.aicpa-cima.com/topic/audit-assurance/audit-and-assurance-greater-than-soc-2
- Microsoft Learn, emergency access (break-glass) accounts: https://learn.microsoft.com/en-us/entra/identity/role-based-access-control/security-emergency-access
- Microsoft Learn, Temporary Access Pass: https://learn.microsoft.com/en-us/entra/identity/authentication/howto-authentication-temporary-access-pass
- Microsoft Learn, Conditional Access report-only mode: https://learn.microsoft.com/en-us/entra/identity/conditional-access/concept-conditional-access-report-only
- Microsoft Learn, Graph user: revokeSignInSessions: https://learn.microsoft.com/en-us/graph/api/user-revokesigninsessions
- Microsoft Learn, GDAP introduction: https://learn.microsoft.com/en-us/partner-center/customers/gdap-introduction
- Microsoft Learn, Intune retire and wipe: https://learn.microsoft.com/en-us/mem/intune/remote-actions/devices-wipe
- Microsoft Learn, Windows LAPS overview: https://learn.microsoft.com/en-us/windows-server/identity/laps/laps-overview

## Open questions (only the owner or the MSP can answer)

- Q-01 Which PSA, RMM, backup and documentation products does the MSP run? (Changes adapters, not the inventory.) **Decided: see 06-decisions.md D6-01.**
- Q-02 Real scale: number of client tenants, end users, endpoints and technicians, and monthly ticket volume. Replaces every estimate here. **Decided: see 06-decisions.md D6-03.**
- Q-03 Service desk structure: are there formal tiers 1-3, a NOC, a dedicated SOC or a third-party SOC/MDR? **Decided: see 06-decisions.md D6-04.**
- Q-04 Who may approve R2 and R3 levers today (lead, engineer, on-call), and is self-approval ever allowed after hours? **Decided: see 06-decisions.md D6-05, D6-08.**
- Q-05 How is caller identity verified today for password and MFA resets (`W-IDM-04`)? **Decided: see 06-decisions.md D6-06.**
- Q-06 Do client contracts or BAAs allow client ticket text or tenant metadata to be processed by any model, local or hosted? Which clients are healthcare (PHI) or financial (NPI)? **Decided: see 06-decisions.md D6-11, D6-12.**
- Q-07 Which existing RMM scripts or automations already run, and with what rights (`W-TOOL-12`)? **Decided: see 06-decisions.md D6-26.**
- Q-08 Does the MSP use GDAP for all tenants, and who owns those relationships (`W-IDM-10`)? **Decided: see 06-decisions.md D6-09.**
- Q-09 Is backup and DR in scope for the AI role, given the blueprint has no backup adapter (`W-BDR-*`)? **Decided: see 06-decisions.md D6-24.**
- Q-10 Which never-automate items does the MSP draw differently (for example lost-device wipe or endpoint isolation after hours)? **Decided: see 06-decisions.md D6-08.**
- Q-11 the owner: confirm the reference scale (200 tenants, 5,000 users) as the planning default, and approve the proposed phases for the gap items before any spec is written. **Decided: see 06-decisions.md D6-03.**
