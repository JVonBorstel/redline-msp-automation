# 02 Impact chains: from one person to the community

Status: **document-only** (mapping stage, 2026-10-20). No code. Machine-readable twin: `map/impact.json` (one object per chain, same ids). Both files are generated from one source, so they hold the same content.

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only: every person, practice and firm named here is invented. Nothing here is a measurement; volumes come from `01-work-inventory.md` (estimates) and every minute or hour figure in this document is a labeled assumption.

The owner's rule for this program: if we cannot save the individual we will not change the tides. So every automation in the inventory is traced from one named (synthetic) person at one client, up through the client business and the MSP, to the community. A chain answers five questions: who is helped and how, what happens when it acts when it should not, what happens when it misses, how far the harm can reach, and what proves the person is better off.

## Contents

- 1. How to read a chain
- 2. Synthetic personas
- 3. One chain end to end
- 4. Totals across all chains
- 5. Chains by area
- 6. Macro: how the chains add up
- 7. The 10 highest-leverage automations
- 8. Cross-document notes
- 9. Open questions only the owner or the MSP can answer
- 10. Sources
- Appendix A. Leverage scores for every chain

## 1. How to read a chain

**Scope.** 134 chains: every inventory item (152 in `map/inventory.json`) whose automation pattern is anything other than `none-keep-human`. The 18 human-only items (`W-ONB-15`, `W-IDM-04`, `W-IDM-07`, `W-M365-12`, `W-EP-11`, `W-BDR-07`, `W-SEC-07`, `W-SEC-09`, `W-CMP-07`, `W-VND-02`, `W-VND-06`, `W-KB-07`, `W-BIL-04`, `W-PRJ-02`, `W-TOOL-08`, `W-GOV-02`, `W-GOV-04`, `W-TRN-04`) have no chain because nothing automated acts in them. The 4 mixed items (`W-IDM-06`, `W-M365-08`, `W-EP-06`, `W-PAT-07`) are traced for their automated part only (a report or a read); the decision itself stays human.

**Levels.** The same four levels as `05-governance.md` section 0, so the two documents line up:

| Level | Id | Who | Field in `impact.json` |
|---|---|---|---|
| Individual | `L1` | one named person at one client (or one technician), with one problem | `individual` |
| Client business | `L2` | the practice or firm: revenue, compliance exposure, harm to its patients or customers | `business` |
| MSP | `L3` | The MSP in this model: SLA, technician hours, margin, reputation, liability | `msp` |
| Community | `L4` | local small-business resilience, jobs, trust in AI, the people who never chose the MSP | `macro` |

**Two directions of failure.** *False positive (FP)*: the automation acts, flags or asserts when it should not (wrong person disabled, legitimate mail purged, a report says 'complete' when it is not). *False negative (FN)*: it misses something it should have caught or done (a failing backup, a forgotten account, a lockout under-prioritized). Each chain names both, and which one is worse for that item.

**Blast radius scale** (field `blast_radius`, the worst credible reach of one failure):

| Id | Reach |
|---|---|
| `BR-0` | MSP-internal draft or record only; no person outside the MSP affected |
| `BR-1` | one person or one device at one client |
| `BR-2` | several people, or one person's data that exposes many others (for example a mailbox full of patient mail), inside one client |
| `BR-3` | a whole client tenant or site, or the client's own customers or patients |
| `BR-4` | many tenants at once (a shared lever, rule, model, release or delegation pattern) |
| `BR-5` | the MSP itself: its audit opinion, reputation, operating model or the trust every client places in it |

**Individual metrics** (field `individual_metric`). The test of benefit is the person, not the ticket count. Every chain names one of these, made specific to that item. Ids are stable for later documents (ROI tracker, dashboards):

| Id | Metric | Definition |
|---|---|---|
| `IM-01` | Time back to work | minutes from the person first being unable to work (first message, call or failed sign-in) to the person working again, confirmed by them or by a successful sign-in |
| `IM-02` | Time to a human | minutes from the person reporting to a named person owning the problem or telling them what is happening |
| `IM-03` | Repeat contacts | times the person had to re-contact or re-explain the same issue |
| `IM-04` | People wrongly acted on | count of individuals affected by a wrong automated action (target 0), with minutes to restore each |
| `IM-05` | Day-one readiness | share of new hires who can sign in, read mail and use their device and apps at their start time |
| `IM-06` | Exposure window | minutes from the event that should end access or contain a threat to access ended or threat contained |
| `IM-07` | Recoverability | whether the person's data could be restored to the point they needed, and minutes to restore |
| `IM-08` | Disruption minutes | minutes of the person's working time lost to planned or unplanned changes (reboots, patches, isolations) |
| `IM-09` | Fraud caught before loss | hours between a detectable fraud signal and human review; payments or harm after a detectable signal (target 0) |
| `IM-10` | Wrong blocks | legitimate messages, sign-ins or files blocked per person per week |
| `IM-11` | Understood and accountable | share of affected people who got a plain notice (EU-1) and can get a true answer to 'what was done to my account and why' (EU-5) |
| `IM-12` | Technician toil and growth | minutes of repetitive work removed per technician per week, and share of their time on skilled work |
| `IM-13` | Right answer with a source | share of technician questions answered correctly with a cited source, and minutes to answer |
| `IM-14` | Owner and manager time | hours a client owner, manager or compliance contact spends on IT administration or evidence per month |
| `IM-15` | Silent-failure lead time | hours between a failure starting (backup, sensor, certificate, patch exposure) and a human knowing, ideally before any person is affected |

**Safeguards** (field `safeguards`). The first entry is always the item's own human-in-the-loop rule from `01-work-inventory.md`. The rest are control ids from `map/controls.json` with their honest status (**built** = code with passing tests on synthetic fixtures, never proven on a real tenant; **partial**; **planned**), rule ids from `05-governance.md` (`HO-n`, `EU-n`, `IR-n`, `CM-n`, `AIR-n`, `ISO-n`), or another inventory item that stays human.

**Leverage rank** (field `leverage_rank`): 1-10 for the ten highest-leverage chains (section 7), otherwise `null`.

## 2. Synthetic personas

Invented people at invented organizations. Contoso Dental and Fabrikam Capital, and their staff, come from the repo's own fixtures (`fixtures/tenant/`, `fixtures/tickets/`); Northwind Bookkeeping and Litware Legal are added here to cover the bookkeeping and professional-services clients an MSP like the MSP serves. `tech-ana`, `lead-lee` are the repo's synthetic identities (`config/identities.json`). Any resemblance to real people is unintended.

| Id | Name | Role | Organization | Their situation |
|---|---|---|---|---|
| `P-01` | Priya Nair | dental hygienist | Contoso Dental | locked out at 7:45 am with her first patient at 8:00 |
| `P-02` | Ana Lopez | office manager and HIPAA privacy contact | Contoso Dental | runs the front office, authorizes hires and access, answers to the owner |
| `P-03` | Dr. Sam Patel | dentist and practice owner | Contoso Dental | pays the bills, signs the insurance forms, accountable as the covered entity |
| `P-04` | Lena Fischer | billing coordinator | Contoso Dental | insurance claims and payer remittances; cash flow depends on her day |
| `P-05` | Jamie Chen | former front desk | Contoso Dental | left the practice; access must end respectfully and completely |
| `P-06` | Tom Baker | dental assistant | Contoso Dental | works chairside on a shared imaging PC; on parental leave part of the year |
| `P-07` | Morgan Reyes | portfolio analyst | Fabrikam Capital | needs Outlook and the research portal before the market opens |
| `P-08` | Dana Kim | compliance officer (Safeguards Rule Qualified Individual) | Fabrikam Capital | owns the written security program and its evidence |
| `P-09` | Chris Osei | trader | Fabrikam Capital | minutes matter during market hours |
| `P-10` | Riley Brooks | operations | Fabrikam Capital | sends and confirms wires; the person BEC attackers target |
| `P-11` | Grace Okafor | bookkeeper | Northwind Bookkeeping (9 staff) | month-end close for twenty small-business clients |
| `P-12` | Hannah Ortiz | paralegal | Litware Legal (14 staff) | court filing deadlines at 5:00 pm |
| `P-13` | Leo Martins | new front-desk hire | Contoso Dental | starts Monday at 8:00 |
| `P-20` | tech-ana | Tier 1 technician (repo identity) | the MSP | scoped to Contoso Dental |
| `P-22` | lead-lee | service desk lead and approver (repo identity) | the MSP | approves writes for both sample tenants |
| `P-23` | Marcus Hale | on-call engineer | the MSP | carries the after-hours phone one week in four |
| `P-24` | Nia Watts | security analyst | the MSP | watches alerts for every tenant |
| `P-25` | Owen Price | account manager and vCIO | the MSP | explains technology and risk to client owners |
| `P-26` | Rosa Diaz | billing specialist | the MSP | monthly true-ups and invoices |
| `P-27` | the AI & Automation Engineer | builds and runs the platform | the MSP | one person today, so a bus-factor risk |
| `P-28` | Kai Turner | Tier 3 and project engineer | the MSP | changes, migrations and Azure work |
| `P-29` | Elena Park | service delivery manager | the MSP | SLA, metrics and SOC 2 evidence |
| `P-30` | Theo Grant | new Tier 1 technician, first month | the MSP | still learning each client's quirks |

Chains per persona: `P-01` 6, `P-02` 16, `P-03` 17, `P-04` 9, `P-05` 3, `P-06` 7, `P-07` 8, `P-08` 6, `P-09` 4, `P-10` 6, `P-11` 7, `P-12` 6, `P-13` 7, `P-20` 6, `P-22` 1, `P-23` 1, `P-24` 3, `P-25` 2, `P-26` 1, `P-27` 9, `P-28` 1, `P-29` 2, `P-30` 6. Client-side people anchor most chains on purpose; where the person most affected is a technician (internal tooling, notes, training), the chain says who downstream benefits.

## 3. One chain end to end

`W-IDM-01` Password reset, read top to bottom. This is the shape of every chain in section 5.

| Step | What happens |
|---|---|
| L1 Priya | Priya calls at 7:45 locked out with an 8:00 patient; she is verified by callback to the number on file and working by 7:55. |
| L2 Contoso Dental | The morning schedule holds; each rescheduled appointment is lost chair time for a small practice. |
| L3 MSP | The highest-volume identity task becomes faster and safer at once. |
| L4 Community | Help-desk social engineering is a known mass attack path; a consistent verify-then-reset pattern at every tenant blunts it. |
| Works | Verified reset, password never seen by any model, log or ticket; Priya signs in. |
| FP | Resets for a caller who is not Priya; an attacker is in a mailbox full of PHI. |
| FN | Priya waits an hour; patients are rescheduled. |
| Bound | Caller identity verification stays human (`W-IDM-04`); requester verification `C-30` and the fast way back `EU-2` are planned; four-eyes approval `C-06`/`C-07` and secret redaction `C-10` are built. |
| Proof | IM-01 Time back to work: minutes from Priya's first call to her first successful sign-in |

Note the asymmetry that recurs across the map: the FN here costs Priya an hour; the FP can cost every patient whose records sit in her mailbox. That is why this item is R3 with human verification even though it is the most common identity ticket, and why it is *not* in the top 10 despite the largest benefit per person (section 7.3).

## 4. Totals across all chains

| Blast radius | Chains |
|---|---|
| `BR-0` | 0 |
| `BR-1` | 40 |
| `BR-2` | 38 |
| `BR-3` | 30 |
| `BR-4` | 16 |
| `BR-5` | 10 |

Which failure direction is worse, by risk class:

| Risk class | Chains | FP worse (acting wrongly) | FN worse (missing it) |
|---|---|---|---|
| R0 | 67 | 28 | 39 |
| R1 | 23 | 14 | 9 |
| R2 | 26 | 18 | 8 |
| R3 | 18 | 11 | 7 |

The pattern is the point: for read-only and reporting work the danger is *missing* things (silent backup failures, forgotten accounts), so those automations should be tuned to over-report and let a human dismiss. For writes the danger is *acting wrongly* on a person, so those are tuned to under-act and wait for a human. Where an R0 chain's FP is worse, the FP is false assurance (a report that says 'complete' or 'compliant' when it is not); `C-21` reconciliation is the control for that.

Individual metrics in use: `IM-01` 21, `IM-02` 9, `IM-03` 4, `IM-04` 14, `IM-05` 7, `IM-06` 12, `IM-07` 5, `IM-08` 7, `IM-09` 2, `IM-10` 1, `IM-11` 7, `IM-12` 6, `IM-13` 6, `IM-14` 17, `IM-15` 16.

Controls that bound the most chains (a failure in one of these widens many blast radii at once):

| Control | Chains | Status |
|---|---|---|
| `C-06` Lead approval bound to lever, client and params | 41 | built |
| `C-05` Dry-run by default with a diff | 37 | built |
| `C-21` Output reconciliation (no invented numbers) | 24 | built |
| `C-20` Read levers cannot write | 22 | built |
| `C-07` Four-eyes rule (no self-approval) | 19 | built |
| `C-41` Evaluation gate before promotion | 17 | partial |
| `C-12` Untrusted input wrapping | 14 | built |
| `C-27` Tenant isolation of prompts, context, logs and error text | 12 | partial |
| `C-04` Per-client scope at the tool layer | 13 | built |
| `C-33` Rollback from recorded before-state | 10 | partial |
| `C-13` Prompt-injection tripwire | 9 | built |
| `C-32` Blast-radius and rate limits | 8 | partial |

Controls that were planned when this map was written and that the most chains depend on (the build order this map argued for): `C-32` Blast-radius and rate limits (8), `C-30` Requester identity verification for access-affecting levers (8), `C-40` Monitoring and alerting on automation behaviour (5), `C-38` Agent and technician access review; least-privilege delegated access (5), `C-42` Staff training and acceptable use (4), `C-25` Data classification and pre-prompt redaction gate (3). Status on 2026-10-27 (map/controls.json): C-30 and C-25 built; C-32, C-40, C-38 and C-42 partial.

## 5. Chains by area

### SD: Service desk (tiers 1-3)

| Id | Item | Risk | Persona | Worse | Blast | Metric | Rank |
|---|---|---|---|---|---|---|---|
| `W-SD-01` | Ticket intake and logging | R1 | P-01 Priya Nair | FP | BR-1 | IM-02 |  |
| `W-SD-02` | Ticket triage: category, priority, queue | R1 | P-01 Priya Nair | FN | BR-1 | IM-01 | 3 |
| `W-SD-03` | Duplicate and related ticket detection | R1 | P-04 Lena Fischer | FP | BR-1 | IM-03 |  |
| `W-SD-04` | Ticket summary for handoff and escalation | R0 | P-07 Morgan Reyes | FP | BR-1 | IM-03 |  |
| `W-SD-05` | Draft reply to the end user from the knowledge base | R1 | P-12 Hannah Ortiz | FP | BR-1 | IM-01 |  |
| `W-SD-06` | SLA breach watch | R0 | P-09 Chris Osei | FN | BR-1 | IM-02 |  |
| `W-SD-07` | Escalation tier 1 to 2 to 3 with context package | R0 | P-07 Morgan Reyes | FP | BR-1 | IM-01 |  |
| `W-SD-08` | Outage and widespread-issue detection | R1 | P-02 Ana Lopez | FN | BR-3 | IM-02 | 5 |
| `W-SD-09` | Closure confirmation and follow-up | R1 | P-06 Tom Baker | FP | BR-1 | IM-03 |  |
| `W-SD-10` | Stale ticket and backlog grooming | R0 | P-11 Grace Okafor | FN | BR-1 | IM-02 |  |
| `W-SD-11` | Common tier 1 fixes via scripts (print spooler, mapped drives, Outlook profile, cache clear) | R2 | P-04 Lena Fischer | FP | BR-1 | IM-01 |  |
| `W-SD-12` | After-hours and on-call triage | R1 | P-23 Marcus Hale | FN | BR-3 | IM-02 |  |
| `W-SD-13` | Recurring-issue analysis (problem management) | R0 | P-02 Ana Lopez | FN | BR-2 | IM-03 |  |
| `W-SD-14` | Customer satisfaction feedback review | R0 | P-10 Riley Brooks | FN | BR-1 | IM-02 |  |

#### `W-SD-01` Ticket intake and logging

R1 · agent-triage · repo: partial · persona: P-01 Priya Nair, dental hygienist, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Priya emails 'can't sign in' at 7:46 from her personal phone; a correct client and contact match means the identity technician sees it in minutes, not after it sits in a general inbox. |
| L2 Client business | Contoso Dental's 8:00 patient is seen on time; patient details Priya pasted into the email are flagged instead of being copied into the ticket record. |
| L3 MSP | Dispatcher minutes per ticket drop; fewer wrong-client tickets, each of which is a confidentiality incident between two tenants. |
| L4 Community | Across thousands of users the first minutes of every problem are the minutes automation can give back; done carelessly, it is also where cross-client exposure starts. |
| When it works | Ticket created, matched to Contoso Dental and Priya, short summary written, possible PHI flagged, dispatcher confirms in one click. |
| FP: acts when it should not | Matches the message to the wrong client or a same-named contact at another tenant; that tenant's technician reads Priya's details, or her ticket merges into someone else's. |
| FN: misses it | Parsing fails or confidence is low and the ticket waits unassigned; Priya waits with patients in the lobby. |
| Worse direction | FP |
| Blast radius | `BR-1` one person; a wrong-client match is BR-2 (a confidentiality event between two tenants) |
| Safeguards | Inventory rule: Agent proposes client, contact and summary; dispatcher confirms before the ticket is saved. Free text is untrusted input; C-12 Untrusted input wrapping (built); C-13 Prompt-injection tripwire (built); C-27 Tenant isolation of prompts, context, logs and error text (partial); C-25 Data classification and pre-prompt redaction gate (built) |
| Proof for the individual | IM-02 Time to a human: minutes from Priya's first message to a technician owning her ticket; wrong-client matches per 1,000 tickets (target 0) |

#### `W-SD-02` Ticket triage: category, priority, queue

R1 · agent-triage, eval · repo: exists · persona: P-01 Priya Nair, dental hygienist, Contoso Dental (synthetic) · **leverage rank 3**

| | |
|---|---|
| L1 Individual | Priya's MFA ticket lands in the identity queue at high priority instead of normal, so her phone rings back before the first patient. |
| L2 Client business | The clinical schedule is protected; a misclassified urgent ticket at a dental office is a patient-care delay, not just an IT delay. |
| L3 MSP | SLA is met without a lead sorting every ticket by hand; lead time moves to the edge cases and approvals. |
| L4 Community | Triage touches every ticket, so its accuracy is the floor under every other automation; a systematic error ships to every tenant at once. |
| When it works | Category, priority and queue right first time (fixture-based: 96.7% category on the mock gateway); at most one lever proposed by rules, in dry-run. |
| FP: acts when it should not | Over-prioritizes, or proposes a lever for a ticket that should not have one (for example injected text asking for an MFA reset); rules and approval stop it at a wasted approval or a social-engineering attempt reaching a lead. |
| FN: misses it | Under-prioritizes a lockout as low; Priya waits behind password-expiry reminders and printer toner. |
| Worse direction | FN |
| Blast radius | `BR-1` one ticket per error; BR-4 if a systematic misclassification ships to all tenants in one release |
| Safeguards | Inventory rule: Suggestion only. Technician accepts or corrects; corrections become eval data. Ticket text can raise priority but can never change what may be done; C-14 Model output cannot choose the lever or its parameters (built); C-12 Untrusted input wrapping (built); C-13 Prompt-injection tripwire (built); C-41 Evaluation gate before promotion (partial); C-03 Role-based authorization; agents may only dry-run writes (built); C-06 Lead approval bound to lever, client and params (built); C-07 Four-eyes rule (no self-approval) (built) |
| Proof for the individual | IM-01 Time back to work: minutes until the person can work again for high-priority tickets, split by triage correct vs corrected; urgent tickets under-prioritized per 1,000 (trend to 0) |

#### `W-SD-03` Duplicate and related ticket detection

R1 · agent-triage · repo: planned · persona: P-04 Lena Fischer, billing coordinator, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Lena emails, then calls, then uses the portal about the insurance portal failing; follow-ups attach to her one ticket and she explains once. |
| L2 Client business | Two technicians do not apply conflicting fixes to the billing PC during claims day. |
| L3 MSP | Less duplicate work; cleaner ticket counts for reporting and billing. |
| L4 Community | Small per person, but repeat explaining is one of the most common complaints about help desks; removing it is a trust gain. |
| When it works | Duplicate proposed and linked; dispatcher confirms; Lena gets one reply. |
| FP: acts when it should not | Merges two different problems (Lena's portal and Tom's scanner) so Tom's issue vanishes into Lena's ticket. |
| FN: misses it | Duplicates remain; two technicians call Lena about the same thing. |
| Worse direction | FP |
| Blast radius | `BR-1` one or two people in one client |
| Safeguards | Inventory rule: Agent suggests the match with reasons; a technician merges. Never auto-merge across clients; C-27 Tenant isolation of prompts, context, logs and error text (partial) |
| Proof for the individual | IM-03 Repeat contacts: times a person had to re-contact or re-explain the same issue; wrongly merged tickets (target 0) |

#### `W-SD-04` Ticket summary for handoff and escalation

R0 · report · repo: planned · persona: P-07 Morgan Reyes, portfolio analyst, Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | Morgan's research-portal issue is escalated with an accurate summary, so Tier 2 does not make him tell the story again on a trading morning. |
| L2 Client business | Less disruption to Fabrikam's analysts during market hours. |
| L3 MSP | Escalations start faster; Tier 2 time goes to the fix, not to re-reading the thread. |
| L4 Community | Good handoffs are what make a multi-tier desk feel like one team to a small business. |
| When it works | Summary of what happened, what was tried and what the user said, citing the ticket entries. |
| FP: acts when it should not | Summary asserts something false (for example 'user already rebooted'), so Tier 2 skips a step and the outage lasts longer. |
| FN: misses it | Summary omits the key fact (it started right after a password change), so Tier 2 starts from zero. |
| Worse direction | FP |
| Blast radius | `BR-1` one person |
| Safeguards | Inventory rule: Read-only summary shown with the ticket entries it used; the receiving technician reads the source when it matters; C-12 Untrusted input wrapping (built); C-27 Tenant isolation of prompts, context, logs and error text (partial); C-11 Data minimisation in the audit log (partial) |
| Proof for the individual | IM-03 Repeat contacts: times Morgan was asked to repeat information after escalation; minutes from escalation to Tier 2 first action |

#### `W-SD-05` Draft reply to the end user from the knowledge base

R1 · agent-triage, eval · repo: partial · persona: P-12 Hannah Ortiz, paralegal, Litware Legal (14 staff) (synthetic)

| | |
|---|---|
| L1 Individual | Hannah cannot print a court filing at 3:40 pm; a technician sends her correct, cited steps in minutes and she files before the 5:00 deadline. |
| L2 Client business | Litware Legal meets its filing deadline; a missed deadline is a client-matter risk for the firm. |
| L3 MSP | Reply time falls on the 1,500-3,000 monthly replies; technicians edit instead of writing from scratch. |
| L4 Community | Trust in AI at small businesses depends on replies being right, from the client's own knowledge base, and sent by a person who stands behind them. |
| When it works | Draft reply grounded in Litware's own KB article, reviewed and sent by a technician (HO-9). |
| FP: acts when it should not | Confident wrong instructions (for example clearing a cache that deletes offline files), or a reply drawing on another client's article. |
| FN: misses it | No draft; the technician writes it by hand and Hannah waits longer. |
| Worse direction | FP |
| Blast radius | `BR-1` one person; BR-2 if another tenant's KB content leaks into the reply |
| Safeguards | Inventory rule: Draft only, with citations to the client's own KB; a technician edits and sends. No reply is sent by an agent; HO-9 AI drafts, a human sends (05-governance.md section 6); C-26 Per-tenant retrieval isolation (partial); C-27 Tenant isolation of prompts, context, logs and error text (partial); C-41 Evaluation gate before promotion (partial); EU-7 a human when you ask (05-governance.md section 9) |
| Proof for the individual | IM-01 Time back to work: minutes until the person can work again on tickets resolved by a reply; share of drafts sent without a factual edit; reopen rate within 7 days |

#### `W-SD-06` SLA breach watch

R0 · report · repo: planned · persona: P-09 Chris Osei, trader, Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | Chris's ticket about his trading terminal has aged 50 minutes; the lead is warned before the SLA breaches and before the market opens. |
| L2 Client business | Fabrikam gets the response time it pays for on the hours that matter to it. |
| L3 MSP | Fewer SLA breaches and service credits; leads intervene earlier. |
| L4 Community | Clients judge an MSP by the worst wait, not the average one. |
| When it works | Lead warned before breach with the ticket, the person and why it is stuck. |
| FP: acts when it should not | Too many warnings; leads learn to ignore them (alert fatigue). |
| FN: misses it | Misses an at-risk ticket; the breach happens and Chris waits. |
| Worse direction | FN |
| Blast radius | `BR-1` one person per missed ticket |
| Safeguards | Inventory rule: Read-only alert to the lead; reassignment is a human decision; C-40 Monitoring and alerting on automation behaviour (partial) |
| Proof for the individual | IM-02 Time to a human: minutes to first human response for warned vs unwarned tickets; SLA breaches per month |

#### `W-SD-07` Escalation tier 1 to 2 to 3 with context package

R0 · read-lever, report · repo: planned · persona: P-07 Morgan Reyes, portfolio analyst, Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | When Morgan's ticket goes to Tier 2, his sign-in logs and device status are already attached, so the fix starts at minute one. |
| L2 Client business | Shorter outages for Fabrikam staff. |
| L3 MSP | Tier 2 minutes saved per escalation; fewer back-and-forth questions. |
| L4 Community | Faster escalations lower the cost of good service for small clients. |
| When it works | Scoped read levers pull the facts for this client and this person only. |
| FP: acts when it should not | Pulls more personal data than the escalation needs, or data from the wrong tenant into the package. |
| FN: misses it | Package is missing the decisive log; Tier 2 repeats the collection. |
| Worse direction | FP |
| Blast radius | `BR-1` one person; BR-2 if the wrong tenant's data is pulled |
| Safeguards | Inventory rule: Agent gathers read-only evidence (device health, sign-in history); the technician decides to escalate; C-04 Per-client scope at the tool layer (built); C-20 Read levers cannot write (built); C-11 Data minimisation in the audit log (partial); C-27 Tenant isolation of prompts, context, logs and error text (partial) |
| Proof for the individual | IM-01 Time back to work: minutes from escalation to the person working again |

#### `W-SD-08` Outage and widespread-issue detection

R1 · agent-triage, report · repo: planned · persona: P-02 Ana Lopez, office manager and HIPAA privacy contact, Contoso Dental (synthetic) · **leverage rank 5**

| | |
|---|---|
| L1 Individual | Five Contoso staff report email down within ten minutes; Ana gets one honest message ('we know, here is what we know, next update at 9:15') instead of each person calling. |
| L2 Client business | The front desk switches to the paper schedule early; patients are told calmly; no one wastes the morning rebooting. |
| L3 MSP | One incident instead of 40 tickets; phone queue protected; detects a Microsoft 365 or ISP incident across many tenants. |
| L4 Community | At 500 tenants a regional ISP or Microsoft 365 outage hits hundreds of small businesses at once; fast, honest status is community resilience. |
| When it works | Widespread issue proposed after related tickets cluster; lead declares it; status text drafted by AI and sent by a person. |
| FP: acts when it should not | Declares a false outage: alarming messages go to clients, and unrelated tickets get linked and closed with the parent. |
| FN: misses it | Misses the pattern; technicians troubleshoot each user separately for an hour. |
| Worse direction | FN |
| Blast radius | `BR-3` a whole client; BR-4 when the same outage spans many tenants |
| Safeguards | Inventory rule: Agent proposes grouping; the lead declares the incident and approves any client notice; HO-9 AI drafts, a human sends (05-governance.md section 6); C-27 Tenant isolation of prompts, context, logs and error text (partial) |
| Proof for the individual | IM-02 Time to a human: minutes from the first affected person reporting to every affected person receiving a status message; IM-01 per affected person |

#### `W-SD-09` Closure confirmation and follow-up

R1 · write-lever-approval · repo: not in blueprint · persona: P-06 Tom Baker, dental assistant, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Tom's ticket is not closed until he confirms it works; if he is chairside and does not answer, he gets one polite follow-up and a one-click reopen link. |
| L2 Client business | Fewer silent unresolved problems in the operatories. |
| L3 MSP | Clean backlog; better first-contact data. |
| L4 Community | Closing tickets is not the same as helping people; this item measures the difference. |
| When it works | Confirmation and follow-up sent after technician approval; reopen is one click. |
| FP: acts when it should not | Closes a ticket while the problem persists; Tom assumes no one is coming. |
| FN: misses it | Ticket stays open for weeks and clutters the queue. |
| Worse direction | FP |
| Blast radius | `BR-1` one person |
| Safeguards | Inventory rule: Template reminders may be pre-approved as a standard change; closing a ticket the user disputes is human; C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); EU-7 a human when you ask (05-governance.md section 9) |
| Proof for the individual | IM-03 Repeat contacts: tickets reopened within 7 days; share of closures confirmed by the person |

#### `W-SD-10` Stale ticket and backlog grooming

R0 · report · repo: planned · persona: P-11 Grace Okafor, bookkeeper, Northwind Bookkeeping (9 staff) (synthetic)

| | |
|---|---|
| L1 Individual | Grace's ticket waiting on the accounting-software vendor is nudged every few days instead of being forgotten during month-end close. |
| L2 Client business | Northwind's blocked work is visible and chased. |
| L3 MSP | Weekly grooming takes minutes; aging tickets are found early. |
| L4 Community | Forgotten tickets are where small-business trust in an MSP erodes quietly. |
| When it works | Weekly list of stale tickets with the next action for each; humans act. |
| FP: acts when it should not | Flags legitimately waiting tickets as closable and a technician closes them. |
| FN: misses it | A waiting ticket is forgotten for weeks. |
| Worse direction | FN |
| Blast radius | `BR-1` one person |
| Safeguards | Inventory rule: Read-only weekly list; humans act |
| Proof for the individual | IM-02 Time to a human: age of the oldest untouched ticket per person; tickets older than 14 days without a touch |

#### `W-SD-11` Common tier 1 fixes via scripts (print spooler, mapped drives, Outlook profile, cache clear)

R2 · write-lever-approval, eval · repo: planned · persona: P-04 Lena Fischer, billing coordinator, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Lena's print spooler jams during claims; an approved script fixes it in three minutes without a remote session. |
| L2 Client business | Claims go out the same day; the practice's cash flow is not delayed. |
| L3 MSP | Tier 1 toil on 300-600 repeat fixes a month drops; technicians spend time on problems that need thought. |
| L4 Community | Repetitive fixes are the toil automation should remove first; that frees people, it does not replace them. |
| When it works | Scripted fix proposed, diff shown, technician approves, result verified with Lena. |
| FP: acts when it should not | Runs on the wrong device (a chairside PC mid-procedure), restarts a service on the server for the whole office, or resets an Outlook profile and loses local data. |
| FN: misses it | Script fails silently and the ticket is closed anyway. |
| Worse direction | FP |
| Blast radius | `BR-1` one device; BR-3 if it hits a shared server |
| Safeguards | Inventory rule: Technician approves each run until the lever's eval and incident record justify a named standard change; dry-run diff shown first; C-01 Lever registry, default deny (built); C-02 Parameter schema validation (built); C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-07 Four-eyes rule (no self-approval) (built); C-17 Timeouts and failure containment (built); C-18 Idempotency on write levers (partial); C-32 Blast-radius and rate limits (partial); C-33 Rollback from recorded before-state (partial); C-41 Evaluation gate before promotion (partial) |
| Proof for the individual | IM-01 Time back to work: minutes from ticket to the person working again; fixes confirmed by the person vs closed unconfirmed |

#### `W-SD-12` After-hours and on-call triage

R1 · agent-triage, report · repo: planned · persona: P-23 Marcus Hale, on-call engineer, the MSP (synthetic)

| | |
|---|---|
| L1 Individual | Marcus, on call, is woken at 2 am only for real emergencies; the rest wait for morning with a summary ready. |
| L2 Client business | A real after-hours emergency (a server down before a 7 am clinic, a ransomware note) still reaches a human at once. |
| L3 MSP | Less on-call burnout and turnover; better decisions from rested engineers. |
| L4 Community | Humane on-call is part of job design; burned-out technicians make the mistakes that hurt clients. |
| When it works | Correct page or hold; security-flagged or multi-user tickets always page. |
| FP: acts when it should not | Pages for a non-urgent ticket; Marcus loses sleep. |
| FN: misses it | Holds a real emergency until morning; six hours of ransomware spread or a clinic that cannot open. |
| Worse direction | FN |
| Blast radius | `BR-3` a missed emergency can cost a whole client |
| Safeguards | Inventory rule: Agent groups and summarizes; on-call human decides to act. Write levers still need approval (on-call lead may self-approve only where the policy names it, and that is audited); C-13 Prompt-injection tripwire (built); C-40 Monitoring and alerting on automation behaviour (partial) |
| Proof for the individual | IM-02 Time to a human: minutes from an after-hours P1 to human acknowledgement; share of pages that were actionable |

#### `W-SD-13` Recurring-issue analysis (problem management)

R0 · report · repo: not in blueprint · persona: P-02 Ana Lopez, office manager and HIPAA privacy contact, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | The scanner at Contoso's front desk fails every week; problem analysis finds the cause and Ana stops logging the same ticket. |
| L2 Client business | Recurring friction is removed; spend goes to the right fix. |
| L3 MSP | Fewer repeat tickets; root causes fixed once. |
| L4 Community | Recurring problems are a hidden tax on small businesses; finding them is cheap with data. |
| When it works | Monthly recurring-issue report per client; engineer decides the fix. |
| FP: acts when it should not | Blames the wrong cause; the client buys hardware it did not need. |
| FN: misses it | Misses the pattern; the weekly ticket continues. |
| Worse direction | FN |
| Blast radius | `BR-2` a team in one client |
| Safeguards | Inventory rule: Read-only clustering; root cause and fix plan are human |
| Proof for the individual | IM-03 Repeat contacts: recurring tickets per person per quarter |

#### `W-SD-14` Customer satisfaction feedback review

R0 · report · repo: not in blueprint · persona: P-10 Riley Brooks, operations, Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | Riley leaves a frustrated comment about a slow fix; a manager calls her the same day. |
| L2 Client business | Fabrikam feels heard; small complaints do not become a cancellation. |
| L3 MSP | Churn signals found early. |
| L4 Community | Feedback is about service, never a score to rank individual technicians (W-TRN-04 stays human). |
| When it works | Comments grouped and summarized; the manager reads and follows up. |
| FP: acts when it should not | Summary misreads sarcasm, or the scores get used to judge one technician. |
| FN: misses it | An angry comment that predicts churn is missed. |
| Worse direction | FN |
| Blast radius | `BR-1` one person |
| Safeguards | Inventory rule: Read-only routing of negative feedback to a manager; no automated reply; HO-9 AI drafts, a human sends (05-governance.md section 6) |
| Proof for the individual | IM-02 Time to a human: hours from negative feedback to a human follow-up call |

### ONB: User onboarding and offboarding

| Id | Item | Risk | Persona | Worse | Blast | Metric | Rank |
|---|---|---|---|---|---|---|---|
| `W-ONB-01` | New-hire request intake and requester authorization check | R0 | P-13 Leo Martins | FP | BR-2 | IM-05 |  |
| `W-ONB-02` | Create the user account (cloud or hybrid) | R3 | P-13 Leo Martins | FN | BR-1 | IM-05 |  |
| `W-ONB-03` | Assign licenses | R2 | P-13 Leo Martins | FN | BR-1 | IM-05 |  |
| `W-ONB-04` | Role-based access: groups, shared mailboxes, Teams and SharePoint | R2 | P-13 Leo Martins | FP | BR-2 | IM-05 |  |
| `W-ONB-05` | MFA enrollment and Temporary Access Pass | R3 | P-13 Leo Martins | FP | BR-2 | IM-05 |  |
| `W-ONB-06` | Device provisioning (Autopilot, Intune enrollment, app set) | R2 | P-13 Leo Martins | FN | BR-1 | IM-05 |  |
| `W-ONB-07` | Day-one welcome and handoff to the manager | R1 | P-13 Leo Martins | FN | BR-1 | IM-05 |  |
| `W-ONB-08` | Offboarding: block sign-in and revoke sessions | R3 | P-05 Jamie Chen | FP | BR-1 | IM-06 |  |
| `W-ONB-09` | Offboarding: mailbox conversion, forwarding and auto-reply | R2 | P-02 Ana Lopez | FP | BR-2 | IM-02 |  |
| `W-ONB-10` | Offboarding: OneDrive and file ownership transfer | R2 | P-02 Ana Lopez | FN | BR-2 | IM-07 |  |
| `W-ONB-11` | Offboarding: license removal after retention window | R2 | P-03 Dr. Sam Patel | FP | BR-1 | IM-14 |  |
| `W-ONB-12` | Offboarding: device retire or wipe and hardware recovery | R3 | P-05 Jamie Chen | FP | BR-1 | IM-04 |  |
| `W-ONB-13` | Offboarding: line-of-business and third-party apps | R3 | P-05 Jamie Chen | FN | BR-2 | IM-06 |  |
| `W-ONB-14` | Offboarding completion proof | R0 | P-02 Ana Lopez | FP | BR-2 | IM-06 |  |
| `W-ONB-16` | Role change or transfer (mover) | R2 | P-04 Lena Fischer | FP | BR-1 | IM-01 |  |
| `W-ONB-17` | Guest and contractor account lifecycle | R2 | P-08 Dana Kim | FN | BR-2 | IM-06 |  |

#### `W-ONB-01` New-hire request intake and requester authorization check

R0 · agent-triage, read-lever · repo: planned · persona: P-13 Leo Martins, new front-desk hire, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Ana requests Leo's account for Monday; the request is checked against Contoso's authorized contacts, so Leo is ready and no one can invent a fake hire. |
| L2 Client business | No account is created for an impostor inside a tenant full of PHI. |
| L3 MSP | Fewer last-minute onboarding fire drills; fewer social-engineering openings. |
| L4 Community | Fake new-hire requests are a cheap attack; a consistent check across all tenants closes it everywhere. |
| When it works | Request parsed, requester checked against the authorized-contacts list, missing fields asked for early. |
| FP: acts when it should not | Accepts a forged request and an account is made for an attacker. |
| FN: misses it | Rejects a legitimate request (Ana sent it from her phone), delaying Leo's first day. |
| Worse direction | FP |
| Blast radius | `BR-2` one tenant's data exposed to an impostor account |
| Safeguards | Inventory rule: Agent checks the request against the documented authorized-contact list and lists missing fields; a technician confirms. An unlisted requester always goes to a human; C-30 Requester identity verification for access-affecting levers (built); C-12 Untrusted input wrapping (built); C-13 Prompt-injection tripwire (built); EU-4 verified before changed (05-governance.md section 9) |
| Proof for the individual | IM-05 Day-one readiness: share of new hires whose request was verified and complete at least 3 business days before start |

#### `W-ONB-02` Create the user account (cloud or hybrid)

R3 · write-lever-approval · repo: planned · persona: P-13 Leo Martins, new front-desk hire, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Leo signs in at 8:00 on his first Monday instead of watching others work. |
| L2 Client business | Contoso does not pay a new employee to wait; check-in runs at full speed. |
| L3 MSP | Onboarding becomes a reviewed template instead of a hand-typed checklist. |
| L4 Community | A good first day is a small, real part of whether people stay in jobs at small businesses. |
| When it works | Account created from the approved template after dry-run diff and lead approval. |
| FP: acts when it should not | Wrong or duplicate account, an account in the wrong tenant, or an account created weeks early that sits as an attack surface. |
| FN: misses it | No account on day one. |
| Worse direction | FN |
| Blast radius | `BR-1` one person |
| Safeguards | Inventory rule: Dry-run diff from the approved request; lead approves. Identity creation is never triggered by ticket text alone; C-02 Parameter schema validation (built); C-04 Per-client scope at the tool layer (built); C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-07 Four-eyes rule (no self-approval) (built); C-33 Rollback from recorded before-state (partial) |
| Proof for the individual | IM-05 Day-one readiness: share of new hires who sign in successfully within 15 minutes of their start time |

#### `W-ONB-03` Assign licenses

R2 · write-lever-approval · repo: planned · persona: P-13 Leo Martins, new front-desk hire, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Leo has Outlook and Teams when he first signs in. |
| L2 Client business | The practice pays only for the license it chose. |
| L3 MSP | Fewer day-one 'no mailbox' tickets. |
| L4 Community | Small, but it removes the most common first-day failure. |
| When it works | License from free stock assigned after approval. |
| FP: acts when it should not | Assigns the wrong or a premium license, or buys one without consent (purchase stays human, W-VND-02). |
| FN: misses it | No license, so no mailbox on day one. |
| Worse direction | FN |
| Blast radius | `BR-1` one person |
| Safeguards | Inventory rule: Assigning from existing seats needs technician approval; buying seats is W-VND-02 (human); C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built) |
| Proof for the individual | IM-05 Day-one readiness: share of new hires with working mail at start time |

#### `W-ONB-04` Role-based access: groups, shared mailboxes, Teams and SharePoint

R2 · write-lever-approval · repo: planned · persona: P-13 Leo Martins, new front-desk hire, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Leo sees the front-desk shared mailbox and schedule and nothing more. |
| L2 Client business | Minimum-necessary access protects Contoso under HIPAA. |
| L3 MSP | Fewer access tickets; reviewable role templates. |
| L4 Community | Over-granted access is how one compromised account becomes a large breach. |
| When it works | Role template per client, reviewed by Ana, diff shown before approval. |
| FP: acts when it should not | Over-grants ('same as Jamie', who had billing access), giving Leo PHI he does not need. |
| FN: misses it | Missing access; Leo borrows a colleague's login, which is a HIPAA problem in itself. |
| Worse direction | FP |
| Blast radius | `BR-2` PHI of many patients reachable by one person |
| Safeguards | Inventory rule: Only from a client-approved role template. Becomes R3 (lead + client contact approval) if a group grants admin rights or regulated data stores; C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-07 Four-eyes rule (no self-approval) (built); C-38 Agent and technician access review; least-privilege delegated access (partial) |
| Proof for the individual | IM-05 Day-one readiness: access tickets in a new hire's first two weeks; over-grants found at the next review (target 0) |

#### `W-ONB-05` MFA enrollment and Temporary Access Pass

R3 · write-lever-approval · repo: planned · persona: P-13 Leo Martins, new front-desk hire, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Leo enrolls MFA in five minutes with a Temporary Access Pass handed to him in person by Ana. |
| L2 Client business | Contoso's newest account is protected from the first minute. |
| L3 MSP | Fewer day-one lockouts; secrets never pass through chat or tickets. |
| L4 Community | New accounts are a favored target; consistent protected enrollment closes that door at every tenant. |
| When it works | TAP created after approval and delivered out of band; the value never enters a prompt or log. |
| FP: acts when it should not | TAP issued to the wrong person or an attacker, who owns the account from day one. |
| FN: misses it | Leo cannot enroll and is locked out on his first morning. |
| Worse direction | FP |
| Blast radius | `BR-2` one account with tenant data behind it |
| Safeguards | Inventory rule: TAP issued only after a human verifies identity (W-IDM-04); the TAP value is delivered by a human over an approved channel, never written into a ticket or a prompt; C-10 Secret redaction before logging (built); C-06 Lead approval bound to lever, client and params (built); C-07 Four-eyes rule (no self-approval) (built); C-30 Requester identity verification for access-affecting levers (built); W-IDM-04 Caller identity verification (kept human) |
| Proof for the individual | IM-05 Day-one readiness: minutes from start time to MFA registered |

#### `W-ONB-06` Device provisioning (Autopilot, Intune enrollment, app set)

R2 · write-lever-approval · repo: planned · persona: P-13 Leo Martins, new front-desk hire, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Leo's laptop is enrolled, encrypted and has the practice-management client on it before he arrives. |
| L2 Client business | No device without encryption ever touches patient data. |
| L3 MSP | Bench time per device falls. |
| L4 Community | Standard, compliant devices are a baseline that small businesses rarely get on their own. |
| When it works | Autopilot/Intune assignment proposed and approved. |
| FP: acts when it should not | Device enrolled into the wrong tenant or group, or a profile without encryption. |
| FN: misses it | Device not ready on day one. |
| Worse direction | FN |
| Blast radius | `BR-1` one device |
| Safeguards | Inventory rule: Technician approves group and profile assignment; dry-run shows which policies will apply; C-04 Per-client scope at the tool layer (built); C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built) |
| Proof for the individual | IM-05 Day-one readiness: share of new hires with a compliant device at start time |

#### `W-ONB-07` Day-one welcome and handoff to the manager

R1 · report · repo: planned · persona: P-13 Leo Martins, new front-desk hire, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Leo gets a plain one-page welcome: how to sign in, who to call; Ana gets a checklist. |
| L2 Client business | New staff are productive sooner. |
| L3 MSP | Fewer 'how do I' calls in week one. |
| L4 Community | Clear, kind instructions are part of treating people well. |
| When it works | Welcome drafted, never containing secrets, sent by a technician. |
| FP: acts when it should not | Sent to the wrong person or to a personal address. |
| FN: misses it | No welcome; Leo calls the help desk confused. |
| Worse direction | FN |
| Blast radius | `BR-1` one person |
| Safeguards | Inventory rule: Agent drafts the note without any secret; a technician sends it; HO-9 AI drafts, a human sends (05-governance.md section 6); C-10 Secret redaction before logging (built) |
| Proof for the individual | IM-05 Day-one readiness: 'how do I' tickets per new hire in the first week |

#### `W-ONB-08` Offboarding: block sign-in and revoke sessions

R3 · write-lever-approval · repo: exists · persona: P-05 Jamie Chen, former front desk, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Jamie's access ends at the agreed minute, respectfully, and the patients whose records she could open are protected from that minute on. |
| L2 Client business | Contoso closes the most common insider path to PHI; no reportable incident from a former employee. |
| L3 MSP | Clear evidence for the client's HIPAA file and the MSP's SOC 2 audit; lower liability as a business associate. |
| L4 Community | Former-employee access is a common breach path; doing this the same way at every tenant protects many patients. |
| When it works | Sign-in blocked and sessions revoked after dry-run diff, lead approval and requester verification. |
| FP: acts when it should not | Disables the wrong person (Priya instead of Jamie), locking out a hygienist with patients waiting, or acts before the termination meeting. |
| FN: misses it | Jamie keeps access to patient records for days. |
| Worse direction | FP |
| Blast radius | `BR-1` one person wrongly locked out; BR-2 when the miss exposes many patients' records |
| Safeguards | Inventory rule: Requester verified by a human; lead approves the dry-run; timing comes from the client, never from the agent; C-03 Role-based authorization; agents may only dry-run writes (built); C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-07 Four-eyes rule (no self-approval) (built); C-08 Hash-chained audit log with head pin and verifier (built); C-30 Requester identity verification for access-affecting levers (built); C-33 Rollback from recorded before-state (partial); EU-2 a fast way back (05-governance.md section 9); EU-3 never locked out by a bot alone (05-governance.md section 9) |
| Proof for the individual | IM-06 Exposure window: minutes from the agreed end time to all sign-in and sessions revoked; IM-04 wrongly disabled people (target 0) and minutes to restore them |

#### `W-ONB-09` Offboarding: mailbox conversion, forwarding and auto-reply

R2 · write-lever-approval · repo: planned · persona: P-02 Ana Lopez, office manager and HIPAA privacy contact, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Patients who email Jamie get an auto-reply pointing to the front desk; Ana can read the mailbox. |
| L2 Client business | Appointment changes and referrals are not lost in a dead mailbox. |
| L3 MSP | Standard offboarding with fewer missed steps. |
| L4 Community | Missed messages to departed staff are a quiet source of patient and customer harm. |
| When it works | Shared-mailbox conversion and auto-reply after approval; no external forwarding. |
| FP: acts when it should not | Forwards to an external personal address (data leaving the practice) or converts the wrong mailbox. |
| FN: misses it | Messages from patients pile up unread. |
| Worse direction | FP |
| Blast radius | `BR-2` patients writing to the departed person |
| Safeguards | Inventory rule: Delegate named by the client contact; technician approves; C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); W-M365-05 Suspicious inbox rule and external forwarding audit (related item) |
| Proof for the individual | IM-02 Time to a human: unanswered inbound messages to departed mailboxes after 7 days |

#### `W-ONB-10` Offboarding: OneDrive and file ownership transfer

R2 · write-lever-approval · repo: planned · persona: P-02 Ana Lopez, office manager and HIPAA privacy contact, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Ana receives Jamie's working files before retention deletes them. |
| L2 Client business | Business records are kept; nothing needed is destroyed. |
| L3 MSP | Fewer 'we need that file back' restores later. |
| L4 Community | Small businesses often lose institutional memory when one person leaves. |
| When it works | Ownership transfer to the named manager after approval. |
| FP: acts when it should not | Transfers to the wrong person, exposing HR or patient files. |
| FN: misses it | Files deleted at retention end. |
| Worse direction | FN |
| Blast radius | `BR-2` one person's files; whoever receives them |
| Safeguards | Inventory rule: Delegate named by the client contact; technician approves; C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-07 Four-eyes rule (no self-approval) (built) |
| Proof for the individual | IM-07 Recoverability: share of leavers whose files were transferred before retention expiry |

#### `W-ONB-11` Offboarding: license removal after retention window

R2 · write-lever-approval, report · repo: planned · persona: P-03 Dr. Sam Patel, dentist and practice owner, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Dr. Patel stops paying for Jamie's license once her data is preserved. |
| L2 Client business | Money back to a small practice every month. |
| L3 MSP | Accurate billing; fewer disputes. |
| L4 Community | Small savings across many clients are real money for local businesses. |
| When it works | Removal proposed only after the retention check passes; approved. |
| FP: acts when it should not | Removes a license before data is preserved, or from an active user who then loses email. |
| FN: misses it | The practice pays for unused licenses for months. |
| Worse direction | FP |
| Blast radius | `BR-1` one person |
| Safeguards | Inventory rule: Agent lists due removals; technician approves each; C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-33 Rollback from recorded before-state (partial); EU-3 never locked out by a bot alone (05-governance.md section 9) |
| Proof for the individual | IM-14 Owner and manager time: days a leaver's license stays billed after retention ends; wrong removals (target 0) |

#### `W-ONB-12` Offboarding: device retire or wipe and hardware recovery

R3 · write-lever-approval · repo: planned · persona: P-05 Jamie Chen, former front desk, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Jamie's practice laptop is wiped after her files are kept; her personal phone gets a selective retire, so her own photos are untouched. |
| L2 Client business | No cached PHI walks out on an unmanaged device. |
| L3 MSP | Hardware recovered and tracked. |
| L4 Community | Respecting a departing person's personal data is part of trust in workplace technology. |
| When it works | Retire vs wipe chosen explicitly, one device per approval, lead approval. |
| FP: acts when it should not | Full wipe of a personal phone, or the wrong device wiped while someone is using it. |
| FN: misses it | Device keeps cached PHI and is never recovered. |
| Worse direction | FP |
| Blast radius | `BR-1` one device |
| Safeguards | Inventory rule: Retire (company data only) with technician approval; full wipe needs lead approval plus client confirmation that no hold or investigation applies; C-02 Parameter schema validation (built); C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-07 Four-eyes rule (no self-approval) (built); C-32 Blast-radius and rate limits (partial) |
| Proof for the individual | IM-04 People wrongly acted on: wrong wipes (target 0); devices with cached data not recovered after 30 days |

#### `W-ONB-13` Offboarding: line-of-business and third-party apps

R3 · report · repo: not in blueprint · persona: P-05 Jamie Chen, former front desk, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Jamie is also removed from the claims clearinghouse and the imaging portal, which Microsoft 365 does not control. |
| L2 Client business | No back door into patient billing from home. |
| L3 MSP | Complete offboarding, not just the Microsoft part. |
| L4 Community | Third-party apps are where offboarding most often fails at small businesses. |
| When it works | Checklist of the client's line-of-business apps per role; a human removes each. |
| FP: acts when it should not | Lists apps Jamie never used; a technician spends time confirming removals that were not needed. |
| FN: misses it | Misses an app; Jamie, who has left, can still sign in to the claims clearinghouse and see patients' insurance details (a possible HIPAA breach for Contoso Dental). |
| Worse direction | FN |
| Blast radius | `BR-2` patient billing data |
| Safeguards | Inventory rule: Agent produces the per-client checklist from documentation; a human does each removal (no stored vendor credentials reach an agent); C-21 Output reconciliation (no invented numbers) (built) |
| Proof for the individual | IM-06 Exposure window: leavers with any active line-of-business account 7 days after leaving (target 0) |

#### `W-ONB-14` Offboarding completion proof

R0 · read-lever, report · repo: planned · persona: P-02 Ana Lopez, office manager and HIPAA privacy contact, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Ana gets proof that Jamie's access is gone for her HIPAA file. |
| L2 Client business | Evidence the practice can show its auditor or OCR. |
| L3 MSP | SOC 2 evidence of access removal, ready without searching. |
| L4 Community | Proof, not promises, is what lets small businesses trust automation. |
| When it works | Read-only checks confirm each step and reconcile with the record. |
| FP: acts when it should not | Reports complete when a step is missing (false assurance, the worst outcome here). |
| FN: misses it | Reports incomplete when it is complete; rework. |
| Worse direction | FP |
| Blast radius | `BR-2` the whole offboarding |
| Safeguards | Inventory rule: Read-only verification against live state, written to the ticket and the audit log; C-20 Read levers cannot write (built); C-21 Output reconciliation (no invented numbers) (built); C-08 Hash-chained audit log with head pin and verifier (built) |
| Proof for the individual | IM-06 Exposure window: hours from end time to verified-complete offboarding; false 'complete' found at audit (target 0) |

#### `W-ONB-16` Role change or transfer (mover)

R2 · write-lever-approval · repo: planned · persona: P-04 Lena Fischer, billing coordinator, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Lena moves from front desk to billing; she gets billing access the same day and loses front-desk access once the handover is done. |
| L2 Client business | No privilege creep across years of role changes. |
| L3 MSP | Fewer access tickets; cleaner reviews. |
| L4 Community | People change roles often at small businesses; access should follow the person, not pile up. |
| When it works | Diff of adds and removes, approved by the manager and a lead. |
| FP: acts when it should not | Removes old access before the new access works, so Lena cannot work; or keeps both sets. |
| FN: misses it | Old access stays for years. |
| Worse direction | FP |
| Blast radius | `BR-1` one person |
| Safeguards | Inventory rule: Diff of add and remove against role templates; technician approves; R3 if admin or regulated stores; C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-07 Four-eyes rule (no self-approval) (built); C-33 Rollback from recorded before-state (partial) |
| Proof for the individual | IM-01 Time back to work: minutes Lena could not work during the move; days with both old and new access |

#### `W-ONB-17` Guest and contractor account lifecycle

R2 · report, write-lever-approval · repo: partial · persona: P-08 Dana Kim, compliance officer (Safeguards Rule Qualified Individual), Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | Dana sponsors an outside auditor as a guest; the guest sees one site and loses access when the engagement ends. |
| L2 Client business | Customer NPI is not reachable by stale guests. |
| L3 MSP | Guest sprawl measured and reduced. |
| L4 Community | Stale guest access is a common, invisible exposure across many small tenants. |
| When it works | Guest report with sponsors; removals approved. |
| FP: acts when it should not | Removes an active guest mid-engagement. |
| FN: misses it | Guest access lingers for years. |
| Worse direction | FN |
| Blast radius | `BR-2` files shared with the guest |
| Safeguards | Inventory rule: Read-only expiry report; removal approved by technician after the client contact confirms; C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built) |
| Proof for the individual | IM-06 Exposure window: guests with access past their end date |

### IDM: Identity and MFA

| Id | Item | Risk | Persona | Worse | Blast | Metric | Rank |
|---|---|---|---|---|---|---|---|
| `W-IDM-01` | Password reset | R3 | P-01 Priya Nair | FP | BR-1 | IM-01 |  |
| `W-IDM-02` | MFA reset (lost or new phone) | R3 | P-07 Morgan Reyes | FP | BR-1 | IM-01 |  |
| `W-IDM-03` | Sign-in failure and lockout investigation | R0 | P-11 Grace Okafor | FN | BR-1 | IM-01 |  |
| `W-IDM-05` | Risky sign-in and risky user review | R0 | P-10 Riley Brooks | FN | BR-2 | IM-06 |  |
| `W-IDM-06` | Conditional Access policy change | R3 | P-09 Chris Osei | FP | BR-3 | IM-04 |  |
| `W-IDM-08` | Break-glass account monitoring | R0 | P-03 Dr. Sam Patel | FN | BR-3 | IM-15 |  |
| `W-IDM-09` | Quarterly admin access review across tenants | R0 | P-08 Dana Kim | FN | BR-3 | IM-14 |  |
| `W-IDM-10` | Partner delegated access (GDAP) relationship management | R3 | P-03 Dr. Sam Patel | FN | BR-4 | IM-02 |  |
| `W-IDM-11` | Stale account cleanup | R3 | P-06 Tom Baker | FP | BR-2 | IM-04 |  |
| `W-IDM-12` | App registration and service principal secret expiry | R0 | P-04 Lena Fischer | FN | BR-2 | IM-15 |  |
| `W-IDM-13` | Self-service password reset and MFA method coverage | R0 | P-01 Priya Nair | FN | BR-3 | IM-01 | 8 |

#### `W-IDM-01` Password reset

R3 · write-lever-approval · repo: planned · persona: P-01 Priya Nair, dental hygienist, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Priya calls at 7:45 locked out with an 8:00 patient; she is verified by callback to the number on file and working by 7:55. |
| L2 Client business | The morning schedule holds; each rescheduled appointment is lost chair time for a small practice. |
| L3 MSP | The highest-volume identity task becomes faster and safer at once. |
| L4 Community | Help-desk social engineering is a known mass attack path; a consistent verify-then-reset pattern at every tenant blunts it. |
| When it works | Verified reset, password never seen by any model, log or ticket; Priya signs in. |
| FP: acts when it should not | Resets for a caller who is not Priya; an attacker is in a mailbox full of PHI. |
| FN: misses it | Priya waits an hour; patients are rescheduled. |
| Worse direction | FP |
| Blast radius | `BR-1` one person; BR-2 if an impostor gets in |
| Safeguards | Inventory rule: Identity verification is human (W-IDM-04). The lever generates no password visible to the agent; technician approves; W-IDM-04 Caller identity verification (kept human); C-30 Requester identity verification for access-affecting levers (built); C-10 Secret redaction before logging (built); C-06 Lead approval bound to lever, client and params (built); C-07 Four-eyes rule (no self-approval) (built); EU-2 a fast way back (05-governance.md section 9); EU-4 verified before changed (05-governance.md section 9) |
| Proof for the individual | IM-01 Time back to work: minutes from Priya's first call to her first successful sign-in |

#### `W-IDM-02` MFA reset (lost or new phone)

R3 · write-lever-approval · repo: exists · persona: P-07 Morgan Reyes, portfolio analyst, Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | Morgan's new Galaxy has an empty Authenticator; his MFA is reset after verification and he registers before the market opens. |
| L2 Client business | Fabrikam's analyst is working; customer NPI is protected. |
| L3 MSP | A built, tested lever (user.reset-mfa) with dry-run diff, approval and audit. |
| L4 Community | MFA resets are the step attackers try to talk their way through; doing it right everywhere matters. |
| When it works | Old method removed, new one registered, Morgan told what changed and how to get help. |
| FP: acts when it should not | Removes MFA for an attacker posing as the owner of a stolen phone (see ticket T-3202). |
| FN: misses it | Morgan is locked out of Outlook and the research portal all morning. |
| Worse direction | FP |
| Blast radius | `BR-1` one person; BR-2 if an impostor gets in |
| Safeguards | Inventory rule: Human verifies identity; lead approves the dry-run; C-03 Role-based authorization; agents may only dry-run writes (built); C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-07 Four-eyes rule (no self-approval) (built); C-08 Hash-chained audit log with head pin and verifier (built); C-30 Requester identity verification for access-affecting levers (built); C-33 Rollback from recorded before-state (partial); EU-1 clear communication to the person (05-governance.md section 9); EU-4 verified before changed (05-governance.md section 9) |
| Proof for the individual | IM-01 Time back to work: minutes from Morgan's ticket to MFA re-registered and signed in |

#### `W-IDM-03` Sign-in failure and lockout investigation

R0 · read-lever, report · repo: planned · persona: P-11 Grace Okafor, bookkeeper, Northwind Bookkeeping (9 staff) (synthetic)

| | |
|---|---|
| L1 Individual | Grace is locked out on the last day of close; the technician sees 'blocked by Conditional Access: unfamiliar location (VPN)' in one minute instead of guessing. |
| L2 Client business | Northwind's close finishes on time. |
| L3 MSP | Fewer unnecessary password resets; faster first-contact resolution. |
| L4 Community | Explaining why someone is locked out is the difference between a guess and a fix. |
| When it works | Scoped read of sign-in logs with a plain cause. |
| FP: acts when it should not | Shows the wrong cause; the technician resets a password that was not the problem. |
| FN: misses it | Misses that the lockout is a password-spray attack, and the technician just unlocks. |
| Worse direction | FN |
| Blast radius | `BR-1` one person |
| Safeguards | Inventory rule: Read-only explanation with the log entries cited; any action goes through W-IDM-01/W-IDM-02 or W-SEC-04; C-04 Per-client scope at the tool layer (built); C-20 Read levers cannot write (built); C-11 Data minimisation in the audit log (partial) |
| Proof for the individual | IM-01 Time back to work: minutes until the person can work again; share of lockouts where the first cause found was right |

#### `W-IDM-05` Risky sign-in and risky user review

R0 · agent-triage, read-lever · repo: planned · persona: P-10 Riley Brooks, operations, Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | An impossible-travel sign-in on Riley's account is confirmed with her by phone within the hour; it was her VPN, and she keeps working. |
| L2 Client business | If it had been real, the pending wire would have been stopped before money left. |
| L3 MSP | Analysts see a short, enriched list instead of raw events. |
| L4 Community | Business email compromise caused about $2.77B in reported US losses in 2024 (FBI IC3); early detection protects small firms' money. |
| When it works | Risky event enriched and proposed to an analyst; any containment goes through W-SEC-04 with approval. |
| FP: acts when it should not | Flags real travel and a technician blocks Riley on payroll day. |
| FN: misses it | A real compromise is dismissed; fraudulent wire instructions go out. |
| Worse direction | FN |
| Blast radius | `BR-2` one account and the customers it can email |
| Safeguards | Inventory rule: Agent groups and explains; remediation goes through W-SEC-04 with approval; C-12 Untrusted input wrapping (built); C-13 Prompt-injection tripwire (built); C-03 Role-based authorization; agents may only dry-run writes (built); W-SEC-04 Business email compromise containment (related item) |
| Proof for the individual | IM-06 Exposure window: minutes from a risky sign-in to a human verdict; compromises first noticed by the user or a customer (target 0) |

#### `W-IDM-06` Conditional Access policy change

R3 · report, none-keep-human · repo: partial · persona: P-09 Chris Osei, trader, Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | A planned Conditional Access change is shown in report-only mode first, and the report shows Chris's trading terminal would be blocked; it is fixed before enforcement. |
| L2 Client business | Fabrikam is not locked out of trading by its own security policy. |
| L3 MSP | Fewer self-inflicted outages; change records ready. |
| L4 Community | One bad policy can lock out a whole client; preview before enforce is the safe pattern. |
| When it works | Impact report from report-only results; the change stays human and dual-approved. |
| FP: acts when it should not | Report says safe when it is not; a whole tenant is locked out. |
| FN: misses it | Report flags harmless changes; a needed protection is delayed. |
| Worse direction | FP |
| Blast radius | `BR-3` a whole tenant |
| Safeguards | Inventory rule: NEVER AUTOMATE the change. Drift detection is read-only; a change needs a change record, report-only testing and engineer sign-off; HO-3 approval by class (05-governance.md section 6); HO-6 blast-radius limit by class (05-governance.md section 6); W-IDM-06 Conditional Access policy change (change human-only) |
| Proof for the individual | IM-04 People wrongly acted on: people wrongly blocked by a CA change (target 0); days in report-only before enforcement |

#### `W-IDM-08` Break-glass account monitoring

R0 · read-lever, report · repo: partial · persona: P-03 Dr. Sam Patel, dentist and practice owner, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | If Contoso's admin access is ever lost, the break-glass account works; if anyone uses it, a human knows within minutes. |
| L2 Client business | The practice can always get back into its own tenant. |
| L3 MSP | Quarterly test evidence for audits. |
| L4 Community | Emergency access is rarely tested at small businesses; testing it everywhere is cheap insurance. |
| When it works | Alert on any break-glass sign-in; quarterly test result recorded. |
| FP: acts when it should not | Alert on a planned test pages someone (minor). |
| FN: misses it | Misses an attacker using break-glass, or the account fails when needed. |
| Worse direction | FN |
| Blast radius | `BR-3` a whole tenant |
| Safeguards | Inventory rule: Read-only. Using a break-glass account is NEVER automated; C-20 Read levers cannot write (built); C-40 Monitoring and alerting on automation behaviour (partial) |
| Proof for the individual | IM-15 Silent-failure lead time: minutes from a break-glass sign-in to human acknowledgement; days since the last successful test |

#### `W-IDM-09` Quarterly admin access review across tenants

R0 · report · repo: planned · persona: P-08 Dana Kim, compliance officer (Safeguards Rule Qualified Individual), Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | Dana gets a clear list of who holds admin in Fabrikam and signs off in an hour. |
| L2 Client business | Fewer standing admins; Safeguards Rule evidence for access control. |
| L3 MSP | MSP technician access across tenants is reviewed, not assumed. |
| L4 Community | Forgotten admin accounts across many tenants are a supply-chain risk to every client. |
| When it works | Report per tenant; the client and MSP decide removals. |
| FP: acts when it should not | Lists someone as admin who is not; time wasted. |
| FN: misses it | Misses a forgotten admin (an ex-technician) with standing access. |
| Worse direction | FN |
| Blast radius | `BR-3` a tenant; BR-4 for MSP-wide access |
| Safeguards | Inventory rule: Read-only review pack; removals by humans with approval; C-21 Output reconciliation (no invented numbers) (built); C-38 Agent and technician access review; least-privilege delegated access (partial) |
| Proof for the individual | IM-14 Owner and manager time: Dana's minutes per review; admin accounts with no owner after review (target 0) |

#### `W-IDM-10` Partner delegated access (GDAP) relationship management

R3 · report · repo: not in blueprint · persona: P-03 Dr. Sam Patel, dentist and practice owner, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Contoso's admin delegation to the MSP is least privilege and time-bound, and Dr. Patel can see who at the MSP can do what. |
| L2 Client business | The practice is not exposed by standing Global Admin rights held by a provider. |
| L3 MSP | Lower liability; cleaner GDAP hygiene. |
| L4 Community | MSPs are targeted because one foothold reaches many clients (CISA AA22-131A); least privilege limits that. |
| When it works | Report of relationships, roles and expiry; changes stay human. |
| FP: acts when it should not | Recommends removing a relationship still needed; technicians cannot help Priya at 7:45. |
| FN: misses it | Misses an over-privileged or expired relationship. |
| Worse direction | FN |
| Blast radius | `BR-4` many tenants share the same delegation pattern |
| Safeguards | Inventory rule: Agent reports expiring or over-broad relationships; changes are human (they define the MSP's own reach into client tenants); C-38 Agent and technician access review; least-privilege delegated access (partial); ISO-10 least-privilege delegated access (05-governance.md section 2) |
| Proof for the individual | IM-02 Time to a human: support minutes lost to expired relationships; tenants with standing Global Admin (target 0) |

#### `W-IDM-11` Stale account cleanup

R3 · report, write-lever-approval · repo: partial · persona: P-06 Tom Baker, dental assistant, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Jamie's forgotten account is disabled; Tom, on parental leave, is left alone because Ana confirmed the list. |
| L2 Client business | Fewer dormant accounts to be taken over. |
| L3 MSP | Monthly hygiene across tenants with evidence. |
| L4 Community | Dormant accounts are a common attack path across small tenants. |
| When it works | Stale report, client confirms names, approved disables within caps. |
| FP: acts when it should not | Disables a person on leave or a seasonal worker, who returns to a dead account. |
| FN: misses it | Stale accounts remain enabled. |
| Worse direction | FP |
| Blast radius | `BR-2` many accounts in one bulk run |
| Safeguards | Inventory rule: Detection is read-only; disable needs client confirmation and lead approval (via W-ONB-08 lever); C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-07 Four-eyes rule (no self-approval) (built); C-32 Blast-radius and rate limits (partial); C-33 Rollback from recorded before-state (partial); EU-3 never locked out by a bot alone (05-governance.md section 9) |
| Proof for the individual | IM-04 People wrongly acted on: people wrongly disabled (target 0) and minutes to restore; stale enabled accounts per tenant |

#### `W-IDM-12` App registration and service principal secret expiry

R0 · report · repo: planned · persona: P-04 Lena Fischer, billing coordinator, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | The claims integration's app secret is renewed before it expires, so Lena's claims keep flowing. |
| L2 Client business | No Friday-afternoon integration outage. |
| L3 MSP | Expiry found weeks ahead, not on the day. |
| L4 Community | Silent expiries are a common, avoidable outage. |
| When it works | Expiry report; the rotation itself stays human (W-TOOL-08). |
| FP: acts when it should not | Alerts on an unused app; noise. |
| FN: misses it | Integration breaks without warning. |
| Worse direction | FN |
| Blast radius | `BR-2` everyone who relies on the integration |
| Safeguards | Inventory rule: Read-only expiry report (metadata only, never secret values). Rotation is human or a Key Vault-managed process; C-20 Read levers cannot write (built) |
| Proof for the individual | IM-15 Silent-failure lead time: days of warning before expiry; outages caused by expired secrets (target 0) |

#### `W-IDM-13` Self-service password reset and MFA method coverage

R0 · report · repo: partial · persona: P-01 Priya Nair, dental hygienist, Contoso Dental (synthetic) · **leverage rank 8**

| | |
|---|---|
| L1 Individual | Priya is enrolled in self-service reset, so next time she fixes it herself in three minutes at 7:45. |
| L2 Client business | Fewer lockouts that stop clinical work. |
| L3 MSP | Fewer resets on the desk; the risky manual path is used less. |
| L4 Community | Self-service puts people in control of their own access; at scale it is the cheapest time-back-to-work there is. |
| When it works | Coverage report per tenant; technicians enroll the gaps. |
| FP: acts when it should not | Counts Priya as covered when her methods are stale. |
| FN: misses it | Low coverage goes unnoticed. |
| Worse direction | FN |
| Blast radius | `BR-3` coverage across a tenant |
| Safeguards | Inventory rule: Read-only report; nudge emails drafted for human send; C-20 Read levers cannot write (built); C-21 Output reconciliation (no invented numbers) (built) |
| Proof for the individual | IM-01 Time back to work: share of users able to self-recover; median minutes to work again for self-service vs help desk |

### M365: Microsoft 365 administration (Entra, Exchange, SharePoint, Teams, Purview)

| Id | Item | Risk | Persona | Worse | Blast | Metric | Rank |
|---|---|---|---|---|---|---|---|
| `W-M365-01` | Shared mailbox and distribution list changes | R2 | P-04 Lena Fischer | FP | BR-2 | IM-01 |  |
| `W-M365-02` | Mailbox permission grants (Full Access, Send As) | R2 | P-10 Riley Brooks | FP | BR-2 | IM-01 |  |
| `W-M365-03` | Mail delivery troubleshooting (message trace) | R0 | P-11 Grace Okafor | FN | BR-1 | IM-01 | 10 |
| `W-M365-04` | Quarantine release requests | R2 | P-04 Lena Fischer | FP | BR-1 | IM-01 |  |
| `W-M365-05` | Suspicious inbox rule and external forwarding audit | R0 | P-10 Riley Brooks | FN | BR-2 | IM-09 |  |
| `W-M365-06` | SharePoint and Teams site creation and permissions | R2 | P-12 Hannah Ortiz | FP | BR-2 | IM-01 |  |
| `W-M365-07` | Oversharing and external sharing review (Copilot readiness) | R0 | P-02 Ana Lopez | FN | BR-3 | IM-06 |  |
| `W-M365-08` | Sensitivity labels and DLP policy changes | R3 | P-08 Dana Kim | FP | BR-3 | IM-10 |  |
| `W-M365-09` | Mailbox size and archive management | R2 | P-03 Dr. Sam Patel | FN | BR-1 | IM-15 |  |
| `W-M365-10` | DMARC, SPF and DKIM monitoring | R0 | P-10 Riley Brooks | FN | BR-3 | IM-09 |  |
| `W-M365-11` | Tenant security baseline and drift check | R0 | P-03 Dr. Sam Patel | FN | BR-3 | IM-15 | 4 |

#### `W-M365-01` Shared mailbox and distribution list changes

R2 · write-lever-approval · repo: planned · persona: P-04 Lena Fischer, billing coordinator, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Lena is added to the insurance@ shared mailbox the morning she asks, so payer emails reach her. |
| L2 Client business | Remittances are handled on time. |
| L3 MSP | A frequent, simple change becomes a reviewed one-click proposal. |
| L4 Community | Small, frequent changes are where consistency pays most. |
| When it works | Membership change from a form, diff shown, approved. |
| FP: acts when it should not | Adds her to the wrong list (an external partners list), so PHI emails go to the wrong people. |
| FN: misses it | Lena misses payer emails for days. |
| Worse direction | FP |
| Blast radius | `BR-2` everyone on the list |
| Safeguards | Inventory rule: Authorized requester check; technician approves; C-02 Parameter schema validation (built); C-04 Per-client scope at the tool layer (built); C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built) |
| Proof for the individual | IM-01 Time back to work: minutes from request to working; wrong-membership incidents (target 0) |

#### `W-M365-02` Mailbox permission grants (Full Access, Send As)

R2 · write-lever-approval · repo: planned · persona: P-10 Riley Brooks, operations, Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | Riley gets Send As on ops@ after the mailbox owner approves. |
| L2 Client business | No one gets the CEO's mailbox by mistake. |
| L3 MSP | Delegation is consistent and recorded. |
| L4 Community | Mailbox delegation is a classic quiet over-grant. |
| When it works | Grant proposed, owner confirms, lead approves. |
| FP: acts when it should not | Grants Full Access to the wrong mailbox, exposing NPI or privileged mail. |
| FN: misses it | Riley cannot send as ops@; wire confirmations wait or go from a personal mailbox. |
| Worse direction | FP |
| Blast radius | `BR-2` one mailbox's contents |
| Safeguards | Inventory rule: Mailbox owner or authorized contact approves; technician approves. R3 for executive or regulated mailboxes; C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-07 Four-eyes rule (no self-approval) (built); HO-4 requester verification (05-governance.md section 6) |
| Proof for the individual | IM-01 Time back to work: minutes from request to working; grants confirmed by the mailbox owner (target 100%) |

#### `W-M365-03` Mail delivery troubleshooting (message trace)

R0 · read-lever, report · repo: not in blueprint · persona: P-11 Grace Okafor, bookkeeper, Northwind Bookkeeping (9 staff) (synthetic) · **leverage rank 10**

| | |
|---|---|
| L1 Individual | Grace is waiting for a client's bank statement during close; a message trace shows in one minute that it is in quarantine. |
| L2 Client business | Close is not held up by a missing email. |
| L3 MSP | Mail tickets resolved at first contact. |
| L4 Community | Knowing where a message went is basic and saves hours across thousands of users. |
| When it works | Scoped trace with a plain answer. |
| FP: acts when it should not | Wrong conclusion ('never sent'), and the client resends by an insecure channel. |
| FN: misses it | Trace misses the message; the search continues by hand. |
| Worse direction | FN |
| Blast radius | `BR-1` one person |
| Safeguards | Inventory rule: Read-only. Message bodies are never pulled into a prompt; metadata only; C-04 Per-client scope at the tool layer (built); C-20 Read levers cannot write (built); C-11 Data minimisation in the audit log (partial) |
| Proof for the individual | IM-01 Time back to work: minutes from 'I did not get it' to an answer |

#### `W-M365-04` Quarantine release requests

R2 · agent-triage, write-lever-approval · repo: not in blueprint · persona: P-04 Lena Fischer, billing coordinator, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | A payer remittance is stuck in quarantine; it is released to Lena within minutes after a technician checks it. |
| L2 Client business | Claims are paid on time. |
| L3 MSP | Release requests are triaged, not blindly approved. |
| L4 Community | Releasing phishing on request is how many compromises start; doing it carefully protects people who trust the 'release' button. |
| When it works | Agent groups and assesses; release needs approval; high-confidence phishing or malware is never released. |
| FP: acts when it should not | Releases a phishing email to Lena, who enters her password. |
| FN: misses it | The legitimate remittance stays stuck. |
| Worse direction | FP |
| Blast radius | `BR-1` one person; BR-2 if the phish leads to account compromise |
| Safeguards | Inventory rule: Agent summarizes verdict and indicators; technician decides; high-confidence phish is never released by request alone; C-12 Untrusted input wrapping (built); C-13 Prompt-injection tripwire (built); C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built) |
| Proof for the individual | IM-01 Time back to work: minutes until wanted mail is delivered; phishing released (target 0) |

#### `W-M365-05` Suspicious inbox rule and external forwarding audit

R0 · read-lever, report · repo: planned · persona: P-10 Riley Brooks, operations, Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | An attacker's rule moving 'wire' emails out of Riley's inbox is found the next morning, before anyone acts on a fake payment instruction. |
| L2 Client business | Fabrikam and its customers do not lose money to a changed bank account. |
| L3 MSP | BEC caught early is an hour of work instead of a crisis and a liability claim. |
| L4 Community | BEC caused about $2.77B in reported US losses in 2024 (FBI IC3); weekly rule audits across all tenants cut that risk for local firms. |
| When it works | Weekly scan; suspicious rules reported to an analyst; containment via W-SEC-04. |
| FP: acts when it should not | Flags Riley's own rule forwarding to her assistant; one question to her. |
| FN: misses it | Misses the rule; a fraudulent wire goes out. |
| Worse direction | FN |
| Blast radius | `BR-2` one mailbox and the customers it emails |
| Safeguards | Inventory rule: Read-only detection; removal is part of W-SEC-04 with approval; C-20 Read levers cannot write (built); C-04 Per-client scope at the tool layer (built); W-SEC-04 Business email compromise containment (related item) |
| Proof for the individual | IM-09 Fraud caught before loss: hours from rule creation to human review; payments made after a detectable rule (target 0) |

#### `W-M365-06` SharePoint and Teams site creation and permissions

R2 · write-lever-approval · repo: planned · persona: P-12 Hannah Ortiz, paralegal, Litware Legal (14 staff) (synthetic)

| | |
|---|---|
| L1 Individual | Hannah gets a matter site for a new case, shared only with the case team and co-counsel. |
| L2 Client business | Client-privileged files stay inside the matter. |
| L3 MSP | Sites follow a reviewed template. |
| L4 Community | Law and financial firms depend on confidentiality; small permission mistakes are big harms. |
| When it works | Template-based site with permissions diff, approved. |
| FP: acts when it should not | Site shared to everyone in the firm or to 'anyone with the link'. |
| FN: misses it | Site delayed; files go to email attachments instead. |
| Worse direction | FP |
| Blast radius | `BR-2` the matter's files |
| Safeguards | Inventory rule: Standard template only; technician approves; C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-02 Parameter schema validation (built) |
| Proof for the individual | IM-01 Time back to work: minutes from request to working site; sites with Everyone or anonymous access (target 0) |

#### `W-M365-07` Oversharing and external sharing review (Copilot readiness)

R0 · report · repo: planned · persona: P-02 Ana Lopez, office manager and HIPAA privacy contact, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Ana finds that a staff payroll sheet and a patient list are shared 'anyone with the link' and fixes it before Copilot or a stranger finds them. |
| L2 Client business | PHI and salaries are not exposed. |
| L3 MSP | A repeatable Copilot-readiness assessment the vCIO can sell honestly. |
| L4 Community | AI assistants surface whatever a user can reach; oversharing becomes everyone's problem when AI arrives. |
| When it works | Report of risky shares; the client owner decides. |
| FP: acts when it should not | Flags legitimate shares; noise. |
| FN: misses it | Misses an anonymous link to regulated data. |
| Worse direction | FN |
| Blast radius | `BR-3` a tenant's shared files |
| Safeguards | Inventory rule: Read-only assessment; fixes are human with client sign-off; C-20 Read levers cannot write (built); C-11 Data minimisation in the audit log (partial) |
| Proof for the individual | IM-06 Exposure window: anonymous links to regulated data (target 0); days from finding to fix |

#### `W-M365-08` Sensitivity labels and DLP policy changes

R3 · report, none-keep-human · repo: planned · persona: P-08 Dana Kim, compliance officer (Safeguards Rule Qualified Individual), Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | Dana sees a DLP policy simulated before enforcement, and it would have blocked Fabrikam's monthly statements to customers; it is tuned first. |
| L2 Client business | NPI is protected without stopping normal business. |
| L3 MSP | Fewer self-inflicted blocks; change evidence. |
| L4 Community | Good DLP protects customers; bad DLP teaches staff to work around security. |
| When it works | Simulation report; policy change stays human. |
| FP: acts when it should not | Report says safe; statements are blocked on the 1st of the month. |
| FN: misses it | Report flags harmless rules; protection delayed. |
| Worse direction | FP |
| Blast radius | `BR-3` a tenant's mail flow |
| Safeguards | Inventory rule: Agent may report current state and simulation results; policy changes are human with change approval; HO-3 approval by class (05-governance.md section 6); W-M365-08 Sensitivity labels and DLP policy changes (change human-only) |
| Proof for the individual | IM-10 Wrong blocks: legitimate messages blocked per person per week; NPI leaks caught |

#### `W-M365-09` Mailbox size and archive management

R2 · write-lever-approval · repo: planned · persona: P-03 Dr. Sam Patel, dentist and practice owner, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Dr. Patel's mailbox is full and referral letters bounce; archiving is turned on before more are lost. |
| L2 Client business | Referrals and patient emails arrive. |
| L3 MSP | Quota alerts handled before the bounce. |
| L4 Community | Lost referrals are a direct patient-care harm. |
| When it works | Archive proposal with the policy shown, approved. |
| FP: acts when it should not | Archive policy moves recent mail away or deletes it. |
| FN: misses it | Mailbox stays full; emails bounce. |
| Worse direction | FN |
| Blast radius | `BR-1` one person and their correspondents |
| Safeguards | Inventory rule: Technician approves; no retention-policy deletion; C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built) |
| Proof for the individual | IM-15 Silent-failure lead time: messages bounced due to quota (target 0) |

#### `W-M365-10` DMARC, SPF and DKIM monitoring

R0 · report · repo: not in blueprint · persona: P-10 Riley Brooks, operations, Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | Fabrikam's customers stop receiving spoofed invoices from its domain, and Riley's real mail still lands. |
| L2 Client business | Fabrikam's name is not used to defraud its customers. |
| L3 MSP | Daily monitoring across 50-500 domains without a person reading XML. |
| L4 Community | Spoofed domains harm the client's customers, people who never chose the MSP. |
| When it works | Daily report from DMARC data; DNS changes stay human (W-VND-06). |
| FP: acts when it should not | Recommends p=reject too early; legitimate vendor mail bounces. |
| FN: misses it | Spoofing continues. |
| Worse direction | FN |
| Blast radius | `BR-3` the domain and everyone who receives its mail |
| Safeguards | Inventory rule: Read-only summaries. DNS changes are human (W-VND-06); W-VND-06 Domain and DNS registrar changes (kept human) |
| Proof for the individual | IM-09 Fraud caught before loss: spoofed messages reaching customers (from aggregate reports); legitimate mail failing authentication |

#### `W-M365-11` Tenant security baseline and drift check

R0 · report, eval · repo: exists · persona: P-03 Dr. Sam Patel, dentist and practice owner, Contoso Dental (synthetic) · **leverage rank 4**

| | |
|---|---|
| L1 Individual | The monthly baseline finds Tom without MFA and an old legacy-auth setting; both are fixed before an attacker finds them. |
| L2 Client business | Contoso closes the gaps insurers and auditors ask about. |
| L3 MSP | One built check (TenantBaseline) runs across every tenant with machine-checked numbers. |
| L4 Community | Baseline gaps are the same at many small tenants; finding them everywhere is protection at scale. |
| When it works | Findings report, reconciled summary, Power BI-ready CSV. |
| FP: acts when it should not | A false finding, or a summary with an invented number (blocked by C-21). |
| FN: misses it | Misses a gap such as legacy auth. |
| Worse direction | FN |
| Blast radius | `BR-3` a tenant's security posture |
| Safeguards | Inventory rule: Read-only; every number in the summary is machine-checked; fix suggestions are dry-run levers only; C-21 Output reconciliation (no invented numbers) (built); C-20 Read levers cannot write (built); C-41 Evaluation gate before promotion (partial) |
| Proof for the individual | IM-15 Silent-failure lead time: days a baseline gap stays open; users without MFA per tenant |

### EP: Endpoint management

| Id | Item | Risk | Persona | Worse | Blast | Metric | Rank |
|---|---|---|---|---|---|---|---|
| `W-EP-01` | Device inventory reconciliation (RMM vs Intune vs PSA) | R0 | P-06 Tom Baker | FN | BR-2 | IM-15 |  |
| `W-EP-02` | RMM agent and Defender sensor health | R0 | P-06 Tom Baker | FN | BR-1 | IM-15 |  |
| `W-EP-03` | Disk space and performance alert remediation | R2 | P-06 Tom Baker | FP | BR-1 | IM-08 |  |
| `W-EP-04` | Software deployment requests | R2 | P-12 Hannah Ortiz | FP | BR-2 | IM-01 |  |
| `W-EP-05` | Intune compliance follow-up | R1 | P-09 Chris Osei | FN | BR-1 | IM-04 |  |
| `W-EP-06` | Disk encryption status and recovery key retrieval | R3 | P-07 Morgan Reyes | FP | BR-1 | IM-01 |  |
| `W-EP-07` | Remote reboot and service restart | R2 | P-11 Grace Okafor | FP | BR-1 | IM-08 |  |
| `W-EP-08` | Lost or stolen device: lock, retire or wipe | R3 | P-09 Chris Osei | FN | BR-1 | IM-06 |  |
| `W-EP-09` | macOS and Linux endpoint scripts | R2 | P-03 Dr. Sam Patel | FP | BR-1 | IM-01 |  |
| `W-EP-10` | Hardware lifecycle and warranty forecast | R0 | P-03 Dr. Sam Patel | FN | BR-2 | IM-14 |  |

#### `W-EP-01` Device inventory reconciliation (RMM vs Intune vs PSA)

R0 · report · repo: not in blueprint · persona: P-06 Tom Baker, dental assistant, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Tom's operatory PC is found missing from the RMM and enrolled, so it gets patches. |
| L2 Client business | No unmanaged PC touching PHI. |
| L3 MSP | Billing and coverage match reality. |
| L4 Community | Unmanaged devices are where small-business breaches start. |
| When it works | Monthly reconciliation across RMM, Intune and PSA. |
| FP: acts when it should not | Flags a retired device as missing; wasted visit. |
| FN: misses it | An unmanaged, unpatched PC with PHI stays unknown. |
| Worse direction | FN |
| Blast radius | `BR-2` devices across a tenant |
| Safeguards | Inventory rule: Read-only reconciliation; fixes are human; C-20 Read levers cannot write (built); C-21 Output reconciliation (no invented numbers) (built) |
| Proof for the individual | IM-15 Silent-failure lead time: unmanaged devices touching tenant data; days to enroll |

#### `W-EP-02` RMM agent and Defender sensor health

R0 · agent-triage, report · repo: planned · persona: P-06 Tom Baker, dental assistant, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Tom's PC's Defender sensor went offline yesterday; a technician fixes it before anything gets through. |
| L2 Client business | No silent gaps in protection. |
| L3 MSP | Alerts grouped so NOC time goes to real gaps. |
| L4 Community | Silent protection failures are invisible until they matter. |
| When it works | Agent groups health alerts; technician acts. |
| FP: acts when it should not | Flags healthy sensors; technicians learn to ignore the group and miss the real one. |
| FN: misses it | An unprotected device stays unprotected. |
| Worse direction | FN |
| Blast radius | `BR-1` one device; BR-2 if many sensors fail together |
| Safeguards | Inventory rule: Grouping and explanation only; reinstall goes through W-EP-04; C-12 Untrusted input wrapping (built); C-20 Read levers cannot write (built) |
| Proof for the individual | IM-15 Silent-failure lead time: hours a sensor is offline before a human knows |

#### `W-EP-03` Disk space and performance alert remediation

R2 · write-lever-approval, eval · repo: planned · persona: P-06 Tom Baker, dental assistant, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | The imaging PC by Tom's chair is nearly full; temp files are cleared before an x-ray capture fails mid-appointment. |
| L2 Client business | No patient waiting in the chair for IT. |
| L3 MSP | 200-600 alerts a month handled with a safe, standard fix. |
| L4 Community | Clearing disk space is pure toil; removing it moves technicians to better work. |
| When it works | Allow-listed cleanup paths only, diff lists files, run outside procedures. |
| FP: acts when it should not | Deletes needed data (an imaging cache not yet synced) or runs during a procedure. |
| FN: misses it | Disk fills; imaging fails with a patient in the chair. |
| Worse direction | FP |
| Blast radius | `BR-1` one device |
| Safeguards | Inventory rule: Technician approves per run; may become a named standard change after eval; never deletes user data folders; C-02 Parameter schema validation (built); C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-17 Timeouts and failure containment (built); C-41 Evaluation gate before promotion (partial) |
| Proof for the individual | IM-08 Disruption minutes: disk-full incidents that interrupted work; minutes of downtime |

#### `W-EP-04` Software deployment requests

R2 · write-lever-approval · repo: planned · persona: P-12 Hannah Ortiz, paralegal, Litware Legal (14 staff) (synthetic)

| | |
|---|---|
| L1 Individual | Hannah needs a PDF editor for a filing; it installs within the hour. |
| L2 Client business | Work is not blocked by software requests. |
| L3 MSP | Requests handled as approved packages. |
| L4 Community | Standard software is a quiet productivity gain. |
| When it works | Packaged deployment to one device or group, approved, rolled out in rings. |
| FP: acts when it should not | Deploys to the wrong group or a version that breaks a line-of-business app. |
| FN: misses it | Hannah waits days for the PDF editor she needs for a filing. |
| Worse direction | FP |
| Blast radius | `BR-2` a group of devices |
| Safeguards | Inventory rule: Only catalog apps; client approval for paid software; technician approves; C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-32 Blast-radius and rate limits (partial); CM-5 staged rollout rings (05-governance.md section 8) |
| Proof for the individual | IM-01 Time back to work: minutes from request to installed; failed installs |

#### `W-EP-05` Intune compliance follow-up

R1 · report · repo: planned · persona: P-09 Chris Osei, trader, Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | Chris is told in plain words that his laptop needs an update before Conditional Access would block it, not after. |
| L2 Client business | No trader blocked at market open. |
| L3 MSP | Fewer surprise compliance lockouts. |
| L4 Community | Warning people first is respect; blocking without notice is a broken promise. |
| When it works | Notice drafted; technician sends and follows up. |
| FP: acts when it should not | Nags compliant users with stale data; they learn to ignore notices. |
| FN: misses it | Chris is blocked without warning. |
| Worse direction | FN |
| Blast radius | `BR-1` one person |
| Safeguards | Inventory rule: Agent explains the reason and drafts a user note; technician sends; HO-9 AI drafts, a human sends (05-governance.md section 6); EU-1 clear communication to the person (05-governance.md section 9) |
| Proof for the individual | IM-04 People wrongly acted on: people blocked by compliance without prior notice (target 0) |

#### `W-EP-06` Disk encryption status and recovery key retrieval

R3 · read-lever, none-keep-human · repo: planned · persona: P-07 Morgan Reyes, portfolio analyst, Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | Morgan's laptop shows the BitLocker recovery screen at 7 am; after verification a technician reads him the key and he is working by 7:15. |
| L2 Client business | No lost morning; the key is not exposed. |
| L3 MSP | Key retrieval is fast and audited. |
| L4 Community | Recovery keys unlock everything on a device; handling them carefully protects the person and the firm. |
| When it works | Read lever fetches the key for a human; release stays human; key never enters a prompt or log. |
| FP: acts when it should not | Key given to someone who stole the laptop and called in. |
| FN: misses it | Morgan sits at the BitLocker recovery screen while the market opens. |
| Worse direction | FP |
| Blast radius | `BR-1` one device; BR-2 if given to a thief |
| Safeguards | Inventory rule: Encryption status report is R0. Key retrieval is human only after identity verification; key values never reach a model, a ticket body or a log; W-IDM-04 Caller identity verification (kept human); C-10 Secret redaction before logging (built); C-04 Per-client scope at the tool layer (built); C-11 Data minimisation in the audit log (partial) |
| Proof for the individual | IM-01 Time back to work: minutes from call to working |

#### `W-EP-07` Remote reboot and service restart

R2 · write-lever-approval · repo: planned · persona: P-11 Grace Okafor, bookkeeper, Northwind Bookkeeping (9 staff) (synthetic)

| | |
|---|---|
| L1 Individual | Grace's accounting service hangs; an approved restart fixes it in two minutes. |
| L2 Client business | Close continues. |
| L3 MSP | Restarts are fast, logged and bounded. |
| L4 Community | Turning it off and on again should not need a human dialing in, but it should need a human saying yes. |
| When it works | Restart proposed; user warned; servers in business hours need a second approval. |
| FP: acts when it should not | Reboots the wrong machine (the server hosting the practice database during clinic hours) or kills unsaved work. |
| FN: misses it | The hung service is not restarted; Grace cannot work in her accounting app until someone remotes in. |
| Worse direction | FP |
| Blast radius | `BR-1` one device; BR-3 for a shared server |
| Safeguards | Inventory rule: Technician approves; lever checks the client's maintenance window; servers need lead approval; C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-32 Blast-radius and rate limits (partial) |
| Proof for the individual | IM-08 Disruption minutes: unplanned disruption minutes caused by restarts (target 0); IM-01 for the requester |

#### `W-EP-08` Lost or stolen device: lock, retire or wipe

R3 · write-lever-approval · repo: planned · persona: P-09 Chris Osei, trader, Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | Chris's laptop is stolen from his car; it is locked within the hour and he works on a loaner. |
| L2 Client business | Customer NPI on the device is protected; encryption plus a fast lock can keep this from being a notification event. |
| L3 MSP | A clean, fast, evidenced response. |
| L4 Community | Lost devices are routine; good handling keeps them from becoming breaches. |
| When it works | Lock first, wipe when confirmed, approved by a lead. |
| FP: acts when it should not | Wipes a device that was only left at home, losing unsynced work, or wipes the wrong one. |
| FN: misses it | The device stays live; a thief has access. |
| Worse direction | FN |
| Blast radius | `BR-1` one device |
| Safeguards | Inventory rule: Lead approves; client contact confirms; the incident is recorded for the human breach assessment (W-SEC-07); C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-07 Four-eyes rule (no self-approval) (built); C-30 Requester identity verification for access-affecting levers (built); C-32 Blast-radius and rate limits (partial) |
| Proof for the individual | IM-06 Exposure window: minutes from report to lock; IM-01 minutes to working on a loaner |

#### `W-EP-09` macOS and Linux endpoint scripts

R2 · write-lever-approval · repo: planned · persona: P-03 Dr. Sam Patel, dentist and practice owner, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Dr. Patel's MacBook gets the same managed fixes as the Windows PCs. |
| L2 Client business | Mac users are not second-class in security. |
| L3 MSP | Fewer one-off manual fixes. |
| L4 Community | Mixed fleets are normal in small offices. |
| When it works | Approved scripts tested per platform. |
| FP: acts when it should not | A script written for Windows assumptions misbehaves on macOS. |
| FN: misses it | Mac issues handled late or not at all. |
| Worse direction | FP |
| Blast radius | `BR-1` one device |
| Safeguards | Inventory rule: Same lever rules as Windows; technician approves; C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-41 Evaluation gate before promotion (partial) |
| Proof for the individual | IM-01 Time back to work: minutes to fixed |

#### `W-EP-10` Hardware lifecycle and warranty forecast

R0 · report · repo: planned · persona: P-03 Dr. Sam Patel, dentist and practice owner, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Dr. Patel budgets four operatory PC replacements for Q1 instead of losing one on a Tuesday. |
| L2 Client business | Planned spend, no surprise downtime. |
| L3 MSP | Honest vCIO advice backed by data. |
| L4 Community | Planning instead of panic is resilience for small businesses. |
| When it works | Forecast report from warranty and age data. |
| FP: acts when it should not | Recommends replacing healthy hardware; spend wasted and trust hurt. |
| FN: misses it | Misses failing hardware. |
| Worse direction | FN |
| Blast radius | `BR-2` a client's fleet |
| Safeguards | Inventory rule: Read-only forecast; recommendations reviewed by the account manager; C-21 Output reconciliation (no invented numbers) (built) |
| Proof for the individual | IM-14 Owner and manager time: unplanned hardware failures per year; owner budget surprises |

### PAT: Patching

| Id | Item | Risk | Persona | Worse | Blast | Metric | Rank |
|---|---|---|---|---|---|---|---|
| `W-PAT-01` | Monthly patch review and ring approval | R2 | P-06 Tom Baker | FP | BR-4 | IM-08 |  |
| `W-PAT-02` | Patch compliance reporting per client | R0 | P-08 Dana Kim | FP | BR-2 | IM-14 |  |
| `W-PAT-03` | Failed patch remediation | R2 | P-07 Morgan Reyes | FN | BR-1 | IM-08 |  |
| `W-PAT-04` | Third-party application patching | R2 | P-12 Hannah Ortiz | FP | BR-2 | IM-08 |  |
| `W-PAT-05` | Emergency patch for actively exploited vulnerabilities | R2 | P-03 Dr. Sam Patel | FN | BR-4 | IM-15 | 2 |
| `W-PAT-06` | Server patch windows and client notice | R2 | P-02 Ana Lopez | FP | BR-3 | IM-08 |  |
| `W-PAT-07` | Network device firmware (firewalls, switches, access points) | R3 | P-02 Ana Lopez | FN | BR-3 | IM-15 |  |

#### `W-PAT-01` Monthly patch review and ring approval

R2 · report · repo: not in blueprint · persona: P-06 Tom Baker, dental assistant, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | A patch that breaks the x-ray sensor driver is caught on pilot devices before Tom's chairside PC gets it. |
| L2 Client business | No clinic day lost to a bad update. |
| L3 MSP | Ring approvals backed by a review, not habit. |
| L4 Community | A bad patch reaches every client at once; ring review is a community safeguard. |
| When it works | Review report with known issues; engineer approves rings. |
| FP: acts when it should not | Recommends approving a known-bad patch; breakage across tenants. |
| FN: misses it | Holds a security patch too long; exposure. |
| Worse direction | FP |
| Blast radius | `BR-4` every tenant in the ring |
| Safeguards | Inventory rule: Agent summarizes notes and known issues with citations; ring promotion is an engineer decision; CM-5 staged rollout rings (05-governance.md section 8) |
| Proof for the individual | IM-08 Disruption minutes: devices broken by patches per cycle; days to deploy critical patches |

#### `W-PAT-02` Patch compliance reporting per client

R0 · report, eval · repo: planned · persona: P-08 Dana Kim, compliance officer (Safeguards Rule Qualified Individual), Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | Dana gets accurate patch numbers for her Safeguards evidence in minutes. |
| L2 Client business | Honest evidence for regulators and insurers. |
| L3 MSP | Monthly reports without manual spreadsheet work. |
| L4 Community | False assurance is worse than no report. |
| When it works | Reconciled compliance report. |
| FP: acts when it should not | Overstates compliance; Dana signs her Safeguards evidence on a number that is wrong. |
| FN: misses it | Understates compliance; Dana spends days chasing devices that were already patched. |
| Worse direction | FP |
| Blast radius | `BR-2` one client's evidence |
| Safeguards | Inventory rule: Read-only; numbers reconcile to source exports (validator); C-21 Output reconciliation (no invented numbers) (built) |
| Proof for the individual | IM-14 Owner and manager time: Dana's minutes to evidence; share of devices patched within policy (reconciled) |

#### `W-PAT-03` Failed patch remediation

R2 · agent-triage, write-lever-approval · repo: planned · persona: P-07 Morgan Reyes, portfolio analyst, Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | Morgan's laptop has failed the same update three times and restarts daily; it is fixed and he stops losing his morning. |
| L2 Client business | Patched and stable. |
| L3 MSP | 60-1,500 failures a month triaged by cause. |
| L4 Community | Removes a large, dull queue from technicians. |
| When it works | Agent groups failures by cause; standard fix approved. |
| FP: acts when it should not | Remediation runs on the wrong device or reboots mid-day. |
| FN: misses it | Device stays vulnerable. |
| Worse direction | FN |
| Blast radius | `BR-1` one device |
| Safeguards | Inventory rule: Agent groups by error code; technician approves the retry lever per batch; C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-12 Untrusted input wrapping (built) |
| Proof for the individual | IM-08 Disruption minutes: days a device stays unpatched after a failure; restart interruptions |

#### `W-PAT-04` Third-party application patching

R2 · write-lever-approval · repo: planned · persona: P-12 Hannah Ortiz, paralegal, Litware Legal (14 staff) (synthetic)

| | |
|---|---|
| L1 Individual | Hannah's browser and PDF tools are kept current without breaking the court e-filing plugin. |
| L2 Client business | Fewer exploitable apps. |
| L3 MSP | Third-party patching without hand-holding. |
| L4 Community | Third-party apps are a top exploited surface. |
| When it works | Approved catalog, rings, deferral during filing deadlines. |
| FP: acts when it should not | Forces an update during a filing; plugin breaks. |
| FN: misses it | Vulnerable versions stay. |
| Worse direction | FP |
| Blast radius | `BR-2` a group of devices |
| Safeguards | Inventory rule: Catalog-driven; technician approves new versions; C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); CM-5 staged rollout rings (05-governance.md section 8) |
| Proof for the individual | IM-08 Disruption minutes: minutes of work interrupted by third-party updates; days vulnerable versions remain |

#### `W-PAT-05` Emergency patch for actively exploited vulnerabilities

R2 · read-lever, report · repo: not in blueprint · persona: P-03 Dr. Sam Patel, dentist and practice owner, Contoso Dental (synthetic) · **leverage rank 2**

| | |
|---|---|
| L1 Individual | CISA adds a firewall VPN flaw to its exploited list; within hours the MSP knows Contoso is exposed and patches that night. |
| L2 Client business | The practice does not become a ransomware victim through a known hole. |
| L3 MSP | Exposure answered across all tenants in hours, not days. |
| L4 Community | Known exploited flaws hit many small businesses at once; MSP speed is community protection. |
| When it works | Read across inventories, matched to CISA KEV, human decides and schedules. |
| FP: acts when it should not | Says exposed when not; an unneeded emergency window disrupts the client. |
| FN: misses it | Says not exposed when exposed; the door stays open. |
| Worse direction | FN |
| Blast radius | `BR-4` every exposed tenant |
| Safeguards | Inventory rule: Agent matches the public KEV catalog to inventory (read-only); deployment is approved by an engineer; C-20 Read levers cannot write (built); C-21 Output reconciliation (no invented numbers) (built) |
| Proof for the individual | IM-15 Silent-failure lead time: hours from KEV publication to every exposed client identified and patched |

#### `W-PAT-06` Server patch windows and client notice

R2 · write-lever-approval · repo: planned · persona: P-02 Ana Lopez, office manager and HIPAA privacy contact, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Ana gets notice that the server reboots Saturday at 10 pm, not Monday at 8 am. |
| L2 Client business | No surprise downtime. |
| L3 MSP | Server patching on schedule with notices sent. |
| L4 Community | Predictability is a form of respect. |
| When it works | Window and notice drafted, approved, sent by a person. |
| FP: acts when it should not | Patches during hours or without notice. |
| FN: misses it | Servers go unpatched. |
| Worse direction | FP |
| Blast radius | `BR-3` everyone using the server |
| Safeguards | Inventory rule: Lead approves; agent drafts notices for human send; post-patch checks read-only; C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); HO-9 AI drafts, a human sends (05-governance.md section 6) |
| Proof for the individual | IM-08 Disruption minutes: minutes of business-hours disruption from server patching (target 0) |

#### `W-PAT-07` Network device firmware (firewalls, switches, access points)

R3 · report, none-keep-human · repo: not in blueprint · persona: P-02 Ana Lopez, office manager and HIPAA privacy contact, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Contoso's firewall firmware plan is laid out with risk and rollback. |
| L2 Client business | Network protection current. |
| L3 MSP | Firmware risk visible. |
| L4 Community | Edge devices are prime targets. |
| When it works | Report; upgrades stay human. |
| FP: acts when it should not | Understates upgrade risk; outage. |
| FN: misses it | Misses outdated firmware. |
| Worse direction | FN |
| Blast radius | `BR-3` a site's network |
| Safeguards | Inventory rule: Agent may report versions against advisories; upgrades are human; W-PAT-07 Network device firmware (firewalls, switches, access points) (upgrade human-only) |
| Proof for the individual | IM-15 Silent-failure lead time: devices on firmware with known exploited flaws |

### BDR: Backup and disaster recovery

| Id | Item | Risk | Persona | Worse | Blast | Metric | Rank |
|---|---|---|---|---|---|---|---|
| `W-BDR-01` | Daily backup job review | R0 | P-11 Grace Okafor | FN | BR-3 | IM-15 | 1 |
| `W-BDR-02` | Failed backup remediation | R2 | P-11 Grace Okafor | FP | BR-3 | IM-15 |  |
| `W-BDR-03` | Restore requests (file, mailbox, VM) | R2 | P-04 Lena Fischer | FP | BR-1 | IM-07 |  |
| `W-BDR-04` | Scheduled restore tests | R1 | P-03 Dr. Sam Patel | FN | BR-3 | IM-07 |  |
| `W-BDR-05` | Microsoft 365 backup coverage check | R0 | P-07 Morgan Reyes | FN | BR-2 | IM-15 |  |
| `W-BDR-06` | Disaster recovery plan upkeep and tabletop exercise | R0 | P-02 Ana Lopez | FN | BR-3 | IM-07 |  |
| `W-BDR-08` | Backup retention and immutability review | R0 | P-03 Dr. Sam Patel | FN | BR-3 | IM-07 |  |

#### `W-BDR-01` Daily backup job review

R0 · read-lever, agent-triage · repo: not in blueprint · persona: P-11 Grace Okafor, bookkeeper, Northwind Bookkeeping (9 staff) (synthetic) · **leverage rank 1**

| | |
|---|---|
| L1 Individual | A silently failing backup of Northwind's file server is caught on day one, not on day forty when Grace needs last year's ledgers. |
| L2 Client business | The firm can recover from ransomware or a mistake. |
| L3 MSP | 1,000-10,000 jobs a day reviewed without a person scrolling. |
| L4 Community | Ransomware recovery at small businesses depends on backups that were checked. |
| When it works | Agent groups failures; technician fixes. |
| FP: acts when it should not | Flags a transient failure; noise. |
| FN: misses it | Misses a failing job; data is unrecoverable when needed. |
| Worse direction | FN |
| Blast radius | `BR-3` a client's data |
| Safeguards | Inventory rule: Read-only grouping and ticket draft; technician confirms; C-20 Read levers cannot write (built); C-12 Untrusted input wrapping (built) |
| Proof for the individual | IM-15 Silent-failure lead time: hours from the first failed job to a human acting; days any protected system had no good backup |

#### `W-BDR-02` Failed backup remediation

R2 · write-lever-approval · repo: proposed · persona: P-11 Grace Okafor, bookkeeper, Northwind Bookkeeping (9 staff) (synthetic)

| | |
|---|---|
| L1 Individual | The failing job is fixed the same day. |
| L2 Client business | Protection restored. |
| L3 MSP | 300-3,000 failures a month handled faster. |
| L4 Community | Same macro effect as W-BDR-01; see that chain. |
| When it works | Standard fix proposed and approved. |
| FP: acts when it should not | Changes job scope (excludes a folder) or deletes restore points to free space. |
| FN: misses it | Job stays failed. |
| Worse direction | FP |
| Blast radius | `BR-3` a client's backups |
| Safeguards | Inventory rule: Rerun lever with technician approval; configuration changes are human; C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-33 Rollback from recorded before-state (partial) |
| Proof for the individual | IM-15 Silent-failure lead time: days a system stays without a good backup |

#### `W-BDR-03` Restore requests (file, mailbox, VM)

R2 · write-lever-approval · repo: proposed · persona: P-04 Lena Fischer, billing coordinator, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Lena deletes the claims spreadsheet; it is restored to a safe location in twenty minutes. |
| L2 Client business | Work continues. |
| L3 MSP | Restores faster and recorded. |
| L4 Community | Getting your work back is one of the moments people remember their IT team for. |
| When it works | Restore to an alternate location after approval; in-place restore stays human. |
| FP: acts when it should not | Restores over the current file, or into the wrong person's folder. |
| FN: misses it | The spreadsheet is not restored; Lena rebuilds it by hand and claims go out late. |
| Worse direction | FP |
| Blast radius | `BR-1` one person's files |
| Safeguards | Inventory rule: Restore to an alternate location with technician approval. In-place restore (overwrite) is R3 and human-run; C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-04 Per-client scope at the tool layer (built) |
| Proof for the individual | IM-07 Recoverability: minutes to restore; share of restores to the requested point |

#### `W-BDR-04` Scheduled restore tests

R1 · write-lever-approval, report · repo: proposed · persona: P-03 Dr. Sam Patel, dentist and practice owner, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Dr. Patel sees proof every quarter that the practice could recover. |
| L2 Client business | Real recovery confidence. |
| L3 MSP | Restore tests done and evidenced. |
| L4 Community | Tested backups are rare at small businesses. |
| When it works | Test restore to an isolated location; report. |
| FP: acts when it should not | Test restores into production, or reports false success. |
| FN: misses it | Restore tests are skipped; nobody learns the practice's backup cannot be restored until Dr. Patel needs it. |
| Worse direction | FN |
| Blast radius | `BR-3` a client's recovery |
| Safeguards | Inventory rule: Restore to an isolated sandbox only; evidence written to the audit log; technician approves; C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-21 Output reconciliation (no invented numbers) (built) |
| Proof for the individual | IM-07 Recoverability: days since the last successful restore test per client; measured restore time |

#### `W-BDR-05` Microsoft 365 backup coverage check

R0 · report · repo: proposed · persona: P-07 Morgan Reyes, portfolio analyst, Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | Morgan's new colleagues' mailboxes are found missing from the backup policy and added. |
| L2 Client business | No unprotected users. |
| L3 MSP | Coverage drift caught weekly. |
| L4 Community | Coverage gaps grow silently with every new hire. |
| When it works | Coverage report. |
| FP: acts when it should not | Flags covered users; time goes to re-checking and real gaps get lost in the list. |
| FN: misses it | A new colleague's mailbox stays outside the backup; a deleted folder of client correspondence cannot be recovered. |
| Worse direction | FN |
| Blast radius | `BR-2` unprotected users |
| Safeguards | Inventory rule: Read-only gap report; C-20 Read levers cannot write (built) |
| Proof for the individual | IM-15 Silent-failure lead time: users, mailboxes and sites without backup |

#### `W-BDR-06` Disaster recovery plan upkeep and tabletop exercise

R0 · report · repo: not in blueprint · persona: P-02 Ana Lopez, office manager and HIPAA privacy contact, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Ana knows the first three steps if ransomware hits, and the contacts on the plan are right. |
| L2 Client business | Faster, calmer recovery. |
| L3 MSP | Plans and tabletops kept current. |
| L4 Community | Prepared small businesses recover; unprepared ones sometimes close. |
| When it works | Plan draft and tabletop script; humans review. |
| FP: acts when it should not | Plan lists wrong contacts. |
| FN: misses it | Plan stale. |
| Worse direction | FN |
| Blast radius | `BR-3` a client's recovery |
| Safeguards | Inventory rule: Agent drafts from current documentation and flags stale sections; humans own the plan and run the exercise; HO-9 AI drafts, a human sends (05-governance.md section 6) |
| Proof for the individual | IM-07 Recoverability: staff who know the first step; plan contact accuracy |

#### `W-BDR-08` Backup retention and immutability review

R0 · report · repo: proposed · persona: P-03 Dr. Sam Patel, dentist and practice owner, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Contoso's backups have an immutable copy an attacker cannot delete. |
| L2 Client business | Recovery survives ransomware. |
| L3 MSP | Retention reviewed quarterly. |
| L4 Community | Attackers target backups first. |
| When it works | Review report. |
| FP: acts when it should not | Flags compliant policies; review time is wasted. |
| FN: misses it | Backups stay deletable; ransomware that reaches the backup console deletes Contoso's restore points along with the server. |
| Worse direction | FN |
| Blast radius | `BR-3` a client's backups |
| Safeguards | Inventory rule: Read-only report; changes are human; C-20 Read levers cannot write (built) |
| Proof for the individual | IM-07 Recoverability: clients with an immutable copy |

### SEC: Security monitoring and alerting

| Id | Item | Risk | Persona | Worse | Blast | Metric | Rank |
|---|---|---|---|---|---|---|---|
| `W-SEC-01` | Security alert intake and grouping | R0 | P-24 Nia Watts | FN | BR-3 | IM-06 | 7 |
| `W-SEC-02` | Alert enrichment | R0 | P-24 Nia Watts | FN | BR-1 | IM-06 |  |
| `W-SEC-03` | User-reported phishing triage | R2 | P-04 Lena Fischer | FN | BR-2 | IM-02 |  |
| `W-SEC-04` | Business email compromise containment | R3 | P-10 Riley Brooks | FN | BR-2 | IM-06 |  |
| `W-SEC-05` | Endpoint isolation | R3 | P-06 Tom Baker | FN | BR-1 | IM-06 |  |
| `W-SEC-06` | Vulnerability scan review and prioritization | R0 | P-03 Dr. Sam Patel | FN | BR-3 | IM-15 |  |
| `W-SEC-08` | Threat advisory relevance check | R0 | P-24 Nia Watts | FN | BR-4 | IM-15 |  |
| `W-SEC-10` | Security awareness training and phishing simulation results | R0 | P-04 Lena Fischer | FP | BR-1 | IM-11 |  |

#### `W-SEC-01` Security alert intake and grouping

R0 · agent-triage, eval · repo: planned · persona: P-24 Nia Watts, security analyst, the MSP (synthetic) · **leverage rank 7**

| | |
|---|---|
| L1 Individual | Nia sees 30 grouped incidents instead of 3,000 alerts, and the real attack on Riley's account is at the top. |
| L2 Client business | Real attacks on clients are seen in minutes. |
| L3 MSP | Analyst time goes to judgment, not sorting. |
| L4 Community | Alert fatigue is how real attacks are missed; better grouping protects every tenant. |
| When it works | Agent groups and ranks; it never closes or suppresses alerts on its own. |
| FP: acts when it should not | Escalates benign clusters; analyst time wasted. |
| FN: misses it | Groups a real alert into a benign cluster; the attack is buried. |
| Worse direction | FN |
| Blast radius | `BR-3` a client; BR-4 for a campaign across tenants |
| Safeguards | Inventory rule: Grouping and severity suggestion with reasons; analyst decides. Closing an alert as benign stays human until evals justify a rule; C-12 Untrusted input wrapping (built); C-13 Prompt-injection tripwire (built); C-41 Evaluation gate before promotion (partial); C-27 Tenant isolation of prompts, context, logs and error text (partial) |
| Proof for the individual | IM-06 Exposure window: minutes from the first alert of a true incident to an analyst looking at it; alerts per analyst per shift |

#### `W-SEC-02` Alert enrichment

R0 · read-lever, report · repo: planned · persona: P-24 Nia Watts, security analyst, the MSP (synthetic)

| | |
|---|---|
| L1 Individual | Each alert arrives with the user, device and recent sign-ins attached. |
| L2 Client business | Faster verdicts on client incidents. |
| L3 MSP | Enrichment minutes saved per alert. |
| L4 Community | Same macro effect as W-SEC-01; see that chain. |
| When it works | Read-only enrichment. |
| FP: acts when it should not | Pulls more personal data than needed. |
| FN: misses it | Missing context; slower verdict. |
| Worse direction | FN |
| Blast radius | `BR-1` one alert |
| Safeguards | Inventory rule: Read-only enrichment shown with sources; C-04 Per-client scope at the tool layer (built); C-20 Read levers cannot write (built); C-11 Data minimisation in the audit log (partial) |
| Proof for the individual | IM-06 Exposure window: minutes from alert to verdict |

#### `W-SEC-03` User-reported phishing triage

R2 · agent-triage, write-lever-approval · repo: partial · persona: P-04 Lena Fischer, billing coordinator, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Lena reports a suspicious email and gets an answer within ten minutes, with thanks; the same email is pulled from six other mailboxes. |
| L2 Client business | Staff keep reporting, which is the cheapest defense a practice has. |
| L3 MSP | 200-800 reports a month triaged fast. |
| L4 Community | People report when they are thanked and answered; that habit protects whole communities of small offices. |
| When it works | Agent verdict proposed; purge across mailboxes needs approval. |
| FP: acts when it should not | Purges a legitimate payer email from every mailbox. |
| FN: misses it | Says safe; Lena clicks. |
| Worse direction | FN |
| Blast radius | `BR-2` every mailbox in a tenant |
| Safeguards | Inventory rule: Agent gives a verdict with indicators (email treated as untrusted input); purge across mailboxes needs analyst approval; C-12 Untrusted input wrapping (built); C-13 Prompt-injection tripwire (built); C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-32 Blast-radius and rate limits (partial) |
| Proof for the individual | IM-02 Time to a human: minutes from report to verdict back to the reporter; reporters who got a reply (target 100%) |

#### `W-SEC-04` Business email compromise containment

R3 · write-lever-approval · repo: partial · persona: P-10 Riley Brooks, operations, Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | Riley's account is compromised; sessions are revoked, the rule removed and she is back with new credentials within the hour, and the pending wire is stopped. |
| L2 Client business | Fabrikam's customers are not defrauded. |
| L3 MSP | A fast, evidenced containment. |
| L4 Community | Fast reporting helps recovery: IC3 reports freezing funds in about 66% of BEC cases its Recovery Asset Team handled in 2024. |
| When it works | Containment steps proposed, diff shown, lead approval, notification decision stays human (W-SEC-07). |
| FP: acts when it should not | Contains the wrong user or a false positive; Riley locked out on payroll day. |
| FN: misses it | Attacker keeps access; fraudulent invoices go to customers. |
| Worse direction | FN |
| Blast radius | `BR-2` one account; BR-3 with the client's customers |
| Safeguards | Inventory rule: Playbook of levers, each dry-run then lead-approved; the client is told by a human; C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-07 Four-eyes rule (no self-approval) (built); C-30 Requester identity verification for access-affecting levers (built); C-33 Rollback from recorded before-state (partial); EU-1 clear communication to the person (05-governance.md section 9); EU-2 a fast way back (05-governance.md section 9); IR-3 restore the person first (05-governance.md section 7) |
| Proof for the individual | IM-06 Exposure window: minutes from confirmed compromise to attacker access removed; IM-01 minutes until Riley can work again |

#### `W-SEC-05` Endpoint isolation

R3 · write-lever-approval · repo: planned · persona: P-06 Tom Baker, dental assistant, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Tom's PC shows ransomware behavior at 2 pm; it is isolated before it spreads and Tom moves to another workstation. |
| L2 Client business | The practice stays open. |
| L3 MSP | Containment in minutes. |
| L4 Community | Stopping one device saves the business. |
| When it works | Isolation proposed with approval; after-hours rules agreed with the MSP (inventory Q-10). |
| FP: acts when it should not | Isolates the front-desk PC on a false positive; check-in stops. |
| FN: misses it | Ransomware spreads across the practice. |
| Worse direction | FN |
| Blast radius | `BR-1` one device; BR-3 if missed |
| Safeguards | Inventory rule: Lead approval (on-call may self-approve under written policy, audited); client told by a human; C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-07 Four-eyes rule (no self-approval) (built); C-33 Rollback from recorded before-state (partial) |
| Proof for the individual | IM-06 Exposure window: minutes from detection to isolation; IM-08 minutes lost to false isolations |

#### `W-SEC-06` Vulnerability scan review and prioritization

R0 · report · repo: planned · persona: P-03 Dr. Sam Patel, dentist and practice owner, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | The ten findings that matter (exploited, internet-facing) are fixed first instead of drowning in thousands. |
| L2 Client business | Real risk reduced. |
| L3 MSP | Prioritization done in minutes. |
| L4 Community | Focus is how small teams protect many clients. |
| When it works | Ranked report. |
| FP: acts when it should not | Over-prioritizes noise. |
| FN: misses it | Buries a known exploited flaw. |
| Worse direction | FN |
| Blast radius | `BR-3` a client |
| Safeguards | Inventory rule: Read-only ranking with exploitability source (for example KEV); humans pick what to fix; C-21 Output reconciliation (no invented numbers) (built) |
| Proof for the individual | IM-15 Silent-failure lead time: days KEV-listed findings stay open |

#### `W-SEC-08` Threat advisory relevance check

R0 · read-lever, report · repo: proposed · persona: P-24 Nia Watts, security analyst, the MSP (synthetic)

| | |
|---|---|
| L1 Individual | Nia knows within hours which clients a new advisory affects. |
| L2 Client business | Exposed clients warned first. |
| L3 MSP | Advisory triage fast and consistent. |
| L4 Community | Same macro effect as W-PAT-05; see that chain. |
| When it works | Relevance report. |
| FP: acts when it should not | Says relevant when not; wasted effort. |
| FN: misses it | Misses that an advisory applies; an exploited product at a client stays unpatched. |
| Worse direction | FN |
| Blast radius | `BR-4` exposed tenants |
| Safeguards | Inventory rule: Read-only match against inventory; humans decide action; C-20 Read levers cannot write (built); C-21 Output reconciliation (no invented numbers) (built) |
| Proof for the individual | IM-15 Silent-failure lead time: hours from advisory to exposed clients identified |

#### `W-SEC-10` Security awareness training and phishing simulation results

R0 · report · repo: proposed · persona: P-04 Lena Fischer, billing coordinator, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Lena clicked a simulated phish; she gets two minutes of kind training, not a public shaming. |
| L2 Client business | Better habits across the practice. |
| L3 MSP | Clear training reports per client. |
| L4 Community | Shaming kills reporting; kindness builds it. |
| When it works | Results report; no punitive use of individual names without the client's agreed policy. |
| FP: acts when it should not | Report names people punitively to their own company. |
| FN: misses it | Repeat clickers unhelped. |
| Worse direction | FP |
| Blast radius | `BR-1` one person |
| Safeguards | Inventory rule: Aggregate report; per-person results shared only with the client's named contact; never used by the MSP to rate individuals; HO-9 AI drafts, a human sends (05-governance.md section 6) |
| Proof for the individual | IM-11 Understood and accountable: repeat-click rate and report rate per client |

### CMP: Compliance evidence

| Id | Item | Risk | Persona | Worse | Blast | Metric | Rank |
|---|---|---|---|---|---|---|---|
| `W-CMP-01` | SOC 2 evidence collection for the MSP's own audit | R0 | P-29 Elena Park | FP | BR-5 | IM-14 |  |
| `W-CMP-02` | Client HIPAA security risk analysis support | R0 | P-02 Ana Lopez | FP | BR-3 | IM-14 |  |
| `W-CMP-03` | Client FTC Safeguards Rule evidence (financial clients) | R0 | P-08 Dana Kim | FP | BR-3 | IM-14 |  |
| `W-CMP-04` | Change records and change advisory review | R1 | P-28 Kai Turner | FP | BR-2 | IM-11 |  |
| `W-CMP-05` | Audit log integrity verification | R0 | P-01 Priya Nair | FN | BR-5 | IM-11 |  |
| `W-CMP-06` | Business associate agreements and vendor due diligence tracking | R0 | P-03 Dr. Sam Patel | FP | BR-3 | IM-14 |  |
| `W-CMP-08` | Cyber insurance questionnaires | R0 | P-03 Dr. Sam Patel | FP | BR-3 | IM-14 |  |
| `W-CMP-09` | Client security questionnaires about the MSP itself | R0 | P-25 Owen Price | FP | BR-5 | IM-14 |  |

#### `W-CMP-01` SOC 2 evidence collection for the MSP's own audit

R0 · report · repo: partial · persona: P-29 Elena Park, service delivery manager, the MSP (synthetic)

| | |
|---|---|
| L1 Individual | Elena gathers SOC 2 evidence in hours instead of weeks, from records the system already keeps. |
| L2 Client business | Clients rely on the MSP's SOC 2 report to vet it; a clean report protects their own vendor reviews. |
| L3 MSP | Fewer audit exceptions; audit cost down. |
| L4 Community | Honest evidence is how an MSP earns trust from regulated small businesses. |
| When it works | Evidence pack drafted from the audit chain and change records; management assertions stay human (W-CMP-07). |
| FP: acts when it should not | Evidence claims a control operated when it did not. |
| FN: misses it | Missing evidence produces an exception. |
| Worse direction | FP |
| Blast radius | `BR-5` the MSP's audit opinion, relied on by every client |
| Safeguards | Inventory rule: Read-only dated, hashed evidence bundle; the compliance lead reviews before it goes to the auditor; C-08 Hash-chained audit log with head pin and verifier (built); C-21 Output reconciliation (no invented numbers) (built); C-45 Synthetic data only and honest labels (partial); W-CMP-07 Policy attestations and management assertions (kept human) |
| Proof for the individual | IM-14 Owner and manager time: Elena's hours per audit cycle; audit exceptions |

#### `W-CMP-02` Client HIPAA security risk analysis support

R0 · report · repo: planned · persona: P-02 Ana Lopez, office manager and HIPAA privacy contact, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Ana, Contoso's privacy contact, gets a risk-analysis draft built from the tenant's real configuration and spends two hours on it instead of two days. |
| L2 Client business | The practice meets its HIPAA Security Rule risk-analysis duty with an accurate picture. |
| L3 MSP | A repeatable vCIO service for healthcare clients. |
| L4 Community | Accurate risk analyses at small practices protect patients' records across the community. |
| When it works | Draft from facts; the client reviews and owns it. |
| FP: acts when it should not | Draft claims safeguards that do not exist, giving false assurance before an OCR inquiry. |
| FN: misses it | Draft misses risks. |
| Worse direction | FP |
| Blast radius | `BR-3` the client's compliance position |
| Safeguards | Inventory rule: Agent gathers technical evidence only; the risk analysis and its conclusions belong to the client (the covered entity) and a human assessor; HO-9 AI drafts, a human sends (05-governance.md section 6); C-21 Output reconciliation (no invented numbers) (built); W-CMP-07 Policy attestations and management assertions (kept human) |
| Proof for the individual | IM-14 Owner and manager time: Ana's hours on the risk analysis; findings closed by the next review |

#### `W-CMP-03` Client FTC Safeguards Rule evidence (financial clients)

R0 · report · repo: planned · persona: P-08 Dana Kim, compliance officer (Safeguards Rule Qualified Individual), Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | Dana, Fabrikam's Qualified Individual under the Safeguards Rule, gets evidence for MFA, encryption and logging in one pack. |
| L2 Client business | Fabrikam can show its program works. |
| L3 MSP | Repeatable financial-client service. |
| L4 Community | Customers of small financial firms are protected by programs that are real, not paper. |
| When it works | Evidence pack; Dana reviews and owns it. |
| FP: acts when it should not | Overstates controls. |
| FN: misses it | Misses gaps. |
| Worse direction | FP |
| Blast radius | `BR-3` the client's compliance position |
| Safeguards | Inventory rule: Read-only evidence; the client's Qualified Individual owns the program and the report; HO-9 AI drafts, a human sends (05-governance.md section 6); C-21 Output reconciliation (no invented numbers) (built) |
| Proof for the individual | IM-14 Owner and manager time: Dana's hours on yearly evidence; gaps found and closed |

#### `W-CMP-04` Change records and change advisory review

R1 · report · repo: partial · persona: P-28 Kai Turner, Tier 3 and project engineer, the MSP (synthetic)

| | |
|---|---|
| L1 Individual | Kai's change records write themselves from the dry-run diffs, so Ana can see exactly what changed in her tenant. |
| L2 Client business | Clients see every change made for them. |
| L3 MSP | Change evidence complete without extra typing. |
| L4 Community | Transparency about change is part of trustworthy automation. |
| When it works | Draft change record from the diff; engineer confirms. |
| FP: acts when it should not | Record misdescribes the change. |
| FN: misses it | A change goes unrecorded. |
| Worse direction | FP |
| Blast radius | `BR-2` one tenant's change history |
| Safeguards | Inventory rule: Agent drafts the change record from the lever dry-run diff; approval is human; C-05 Dry-run by default with a diff (built); C-08 Hash-chained audit log with head pin and verifier (built); C-37 Lever change management with staged rollout (partial) |
| Proof for the individual | IM-11 Understood and accountable: share of changes with a complete record (target 100%) |

#### `W-CMP-05` Audit log integrity verification

R0 · eval · repo: exists · persona: P-01 Priya Nair, dental hygienist, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | If Priya asks who reset her MFA and why, the answer is provable from a tamper-evident record. |
| L2 Client business | The practice can answer its patients and auditors. |
| L3 MSP | Daily verification that the audit log was not altered. |
| L4 Community | Provable records are what make automated decisions accountable to the people they affect. |
| When it works | Daily verifier run; failures alert. |
| FP: acts when it should not | Verifier flags tampering falsely; an incident drill for nothing. |
| FN: misses it | Tampering goes unnoticed. |
| Worse direction | FN |
| Blast radius | `BR-5` all audit evidence |
| Safeguards | Inventory rule: Automatic check; a break is a human-investigated incident; C-08 Hash-chained audit log with head pin and verifier (built); C-39 Write-once audit head pinning and retention (partial); EU-5 no silent decisions (05-governance.md section 9) |
| Proof for the individual | IM-11 Understood and accountable: days the verifier passed; minutes to answer 'who changed my account and why' |

#### `W-CMP-06` Business associate agreements and vendor due diligence tracking

R0 · report · repo: not in blueprint · persona: P-03 Dr. Sam Patel, dentist and practice owner, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Dr. Patel knows which vendors touching patient data have a BAA on file. |
| L2 Client business | No unknown processors of PHI. |
| L3 MSP | Tracking without spreadsheets. |
| L4 Community | Fourth-party risk is where small practices lose sight of their data. |
| When it works | Tracker report. |
| FP: acts when it should not | Says a BAA exists when it does not. |
| FN: misses it | Expired agreements missed. |
| Worse direction | FP |
| Blast radius | `BR-3` the client's vendor chain |
| Safeguards | Inventory rule: Read-only tracker; legal review human; C-21 Output reconciliation (no invented numbers) (built); C-43 AI vendor and subprocessor register (built) |
| Proof for the individual | IM-14 Owner and manager time: vendors handling PHI or NPI without a current agreement (target 0) |

#### `W-CMP-08` Cyber insurance questionnaires

R0 · report · repo: not in blueprint · persona: P-03 Dr. Sam Patel, dentist and practice owner, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Dr. Patel's cyber-insurance answers are backed by evidence, so a claim after ransomware is not denied over a false 'yes, MFA everywhere'. |
| L2 Client business | The practice's insurance actually pays when needed; that can decide whether it survives an incident. |
| L3 MSP | Questionnaires done in an hour with evidence links. |
| L4 Community | Insurance that pays out keeps local businesses open after attacks. |
| When it works | Draft answers with evidence; the owner signs. |
| FP: acts when it should not | Answers 'yes' when the truth is 'partly'; the claim may be denied. |
| FN: misses it | Answers 'no' when 'yes'; higher premium. |
| Worse direction | FP |
| Blast radius | `BR-3` the client's financial survival after an incident |
| Safeguards | Inventory rule: Agent drafts answers with evidence links; a human checks every answer; unsupported answers are left blank, not guessed; C-21 Output reconciliation (no invented numbers) (built); HO-9 AI drafts, a human sends (05-governance.md section 6); W-CMP-07 Policy attestations and management assertions (kept human) |
| Proof for the individual | IM-14 Owner and manager time: share of answers backed by evidence (target 100%); owner hours per questionnaire |

#### `W-CMP-09` Client security questionnaires about the MSP itself

R0 · report · repo: planned · persona: P-25 Owen Price, account manager and vCIO, the MSP (synthetic)

| | |
|---|---|
| L1 Individual | Owen answers a prospect's security questionnaire about the MSP in an hour with accurate answers. |
| L2 Client business | Clients get honest answers about their provider. |
| L3 MSP | Faster sales cycle without overclaiming. |
| L4 Community | Honest vendor answers keep the whole supply chain truthful. |
| When it works | Draft from approved answers; human sends. |
| FP: acts when it should not | Overclaims a control. |
| FN: misses it | Slow or incomplete answers. |
| Worse direction | FP |
| Blast radius | `BR-5` the MSP's reputation |
| Safeguards | Inventory rule: RAG over approved answers with citations; a human approves and sends; HO-9 AI drafts, a human sends (05-governance.md section 6); C-21 Output reconciliation (no invented numbers) (built); C-45 Synthetic data only and honest labels (partial) |
| Proof for the individual | IM-14 Owner and manager time: hours per questionnaire; answers corrected after review |

### VND: Vendor and license management

| Id | Item | Risk | Persona | Worse | Blast | Metric | Rank |
|---|---|---|---|---|---|---|---|
| `W-VND-01` | License reconciliation | R0 | P-03 Dr. Sam Patel | FP | BR-1 | IM-14 |  |
| `W-VND-03` | Renewal alerts (subscriptions, warranties, domains) | R0 | P-12 Hannah Ortiz | FN | BR-3 | IM-15 |  |
| `W-VND-04` | Vendor and ISP escalation | R1 | P-02 Ana Lopez | FN | BR-3 | IM-01 |  |
| `W-VND-05` | TLS certificate expiry monitoring | R0 | P-07 Morgan Reyes | FN | BR-3 | IM-15 |  |

#### `W-VND-01` License reconciliation

R0 · report · repo: planned · persona: P-03 Dr. Sam Patel, dentist and practice owner, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Dr. Patel stops paying for three licenses no one uses. |
| L2 Client business | Money back to the practice. |
| L3 MSP | Accurate license data. |
| L4 Community | Small savings across many small clients add up. |
| When it works | Reconciliation report; purchase or reduction stays human (W-VND-02). |
| FP: acts when it should not | Calls a license unused when it is used; acting on it would cut someone off. |
| FN: misses it | Overpaying continues. |
| Worse direction | FP |
| Blast radius | `BR-1` a person if acted on wrongly |
| Safeguards | Inventory rule: Read-only; recommendations reviewed by billing; C-21 Output reconciliation (no invented numbers) (built); W-VND-02 License purchase or reduction (kept human) |
| Proof for the individual | IM-14 Owner and manager time: unused license spend per client per month; wrong 'unused' calls |

#### `W-VND-03` Renewal alerts (subscriptions, warranties, domains)

R0 · report · repo: planned · persona: P-12 Hannah Ortiz, paralegal, Litware Legal (14 staff) (synthetic)

| | |
|---|---|
| L1 Individual | Litware's domain renewal is flagged 60 days early, so the firm's email never goes dark. |
| L2 Client business | No lapsed domains, warranties or subscriptions. |
| L3 MSP | Renewals planned. |
| L4 Community | A lapsed domain can take a small firm offline for days. |
| When it works | Renewal report. |
| FP: acts when it should not | Noise. |
| FN: misses it | The domain lapses; Litware's email stops, possibly on a filing day for Hannah. |
| Worse direction | FN |
| Blast radius | `BR-3` a client's email or website |
| Safeguards | Inventory rule: Read-only alerts; C-20 Read levers cannot write (built) |
| Proof for the individual | IM-15 Silent-failure lead time: lapses (target 0); days of warning |

#### `W-VND-04` Vendor and ISP escalation

R1 · report · repo: not in blueprint · persona: P-02 Ana Lopez, office manager and HIPAA privacy contact, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Contoso's internet is down; a ticket with the circuit ID is opened with the ISP within five minutes. |
| L2 Client business | Faster restoration. |
| L3 MSP | Vendor escalations packaged. |
| L4 Community | Fast ISP escalation matters most for small offices with one line. |
| When it works | Escalation drafted; technician sends. |
| FP: acts when it should not | Escalates to the wrong vendor. |
| FN: misses it | Slow escalation. |
| Worse direction | FN |
| Blast radius | `BR-3` a site |
| Safeguards | Inventory rule: Agent drafts the case summary without client secrets; a human submits; HO-9 AI drafts, a human sends (05-governance.md section 6) |
| Proof for the individual | IM-01 Time back to work: minutes from outage to vendor ticket; outage minutes |

#### `W-VND-05` TLS certificate expiry monitoring

R0 · report · repo: planned · persona: P-07 Morgan Reyes, portfolio analyst, Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | Fabrikam's client portal certificate is renewed before customers see a warning. |
| L2 Client business | No 'not secure' warnings to customers. |
| L3 MSP | Expiry tracked. |
| L4 Community | Warnings teach customers to click through warnings. |
| When it works | Expiry report. |
| FP: acts when it should not | Noise. |
| FN: misses it | The certificate expires; Fabrikam's customers see a security warning on the client portal and some stop using it. |
| Worse direction | FN |
| Blast radius | `BR-3` the client's customers |
| Safeguards | Inventory rule: Read-only alerts; renewal human; C-20 Read levers cannot write (built) |
| Proof for the individual | IM-15 Silent-failure lead time: expired-certificate incidents (target 0) |

### RPT: Client reporting and QBRs

| Id | Item | Risk | Persona | Worse | Blast | Metric | Rank |
|---|---|---|---|---|---|---|---|
| `W-RPT-01` | Monthly client health report | R0 | P-03 Dr. Sam Patel | FP | BR-2 | IM-14 |  |
| `W-RPT-02` | Quarterly business review draft | R0 | P-08 Dana Kim | FP | BR-2 | IM-14 |  |
| `W-RPT-03` | Weekly 'what we did for you' digest | R1 | P-02 Ana Lopez | FP | BR-2 | IM-11 |  |
| `W-RPT-04` | Technology roadmap and budget recommendations | R0 | P-03 Dr. Sam Patel | FP | BR-2 | IM-14 |  |
| `W-RPT-05` | Client AI-use policy starter | R0 | P-02 Ana Lopez | FN | BR-2 | IM-11 |  |
| `W-RPT-06` | Internal operations metrics (resolution time, first-contact resolution, SLA, backlog) | R0 | P-29 Elena Park | FP | BR-5 | IM-01 |  |

#### `W-RPT-01` Monthly client health report

R0 · report, eval · repo: planned · persona: P-03 Dr. Sam Patel, dentist and practice owner, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Dr. Patel reads one page in plain words with true numbers, in five minutes. |
| L2 Client business | An owner who understands IT risk makes better decisions. |
| L3 MSP | 50-500 reports a month without hand assembly. |
| L4 Community | Honest reporting builds trust in the MSP and in AI. |
| When it works | Reconciled report draft; account manager reviews and sends. |
| FP: acts when it should not | Invents or overstates a number (blocked by C-21). |
| FN: misses it | The report hides a real problem; Dr. Patel thinks the practice is fine until it fails. |
| Worse direction | FP |
| Blast radius | `BR-2` one client's understanding |
| Safeguards | Inventory rule: Every number reconciles to source data (validator gate); account manager reviews and sends; C-21 Output reconciliation (no invented numbers) (built); HO-9 AI drafts, a human sends (05-governance.md section 6); C-27 Tenant isolation of prompts, context, logs and error text (partial) |
| Proof for the individual | IM-14 Owner and manager time: owner minutes to understand the report; numbers that reconcile (target 100%) |

#### `W-RPT-02` Quarterly business review draft

R0 · report, eval · repo: planned · persona: P-08 Dana Kim, compliance officer (Safeguards Rule Qualified Individual), Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | Dana's quarterly review shows what changed and what to do next. |
| L2 Client business | Planned improvements. |
| L3 MSP | QBR prep in an hour. |
| L4 Community | Same macro effect as W-RPT-01; see that chain. |
| When it works | Draft; human presents. |
| FP: acts when it should not | Overclaims progress. |
| FN: misses it | Omits a risk. |
| Worse direction | FP |
| Blast radius | `BR-2` one client |
| Safeguards | Inventory rule: Draft only; the account manager owns the story and the recommendations; C-21 Output reconciliation (no invented numbers) (built); HO-9 AI drafts, a human sends (05-governance.md section 6); C-27 Tenant isolation of prompts, context, logs and error text (partial) |
| Proof for the individual | IM-14 Owner and manager time: preparation hours; actions agreed and done by next QBR |

#### `W-RPT-03` Weekly 'what we did for you' digest

R1 · report · repo: planned · persona: P-02 Ana Lopez, office manager and HIPAA privacy contact, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Ana gets a short weekly note of what was done for Contoso. |
| L2 Client business | Visible value. |
| L3 MSP | Client retention. |
| L4 Community | Showing the work builds trust. |
| When it works | Digest drafted; account manager sends. |
| FP: acts when it should not | Includes another client's data. |
| FN: misses it | No digest goes out; Ana cannot see what the MSP did for Contoso, and the value of the service is invisible at renewal. |
| Worse direction | FP |
| Blast radius | `BR-2` cross-tenant exposure if wrong |
| Safeguards | Inventory rule: Draft for human send; C-27 Tenant isolation of prompts, context, logs and error text (partial); HO-9 AI drafts, a human sends (05-governance.md section 6) |
| Proof for the individual | IM-11 Understood and accountable: cross-tenant items in digests (target 0); client read rate |

#### `W-RPT-04` Technology roadmap and budget recommendations

R0 · report · repo: planned · persona: P-03 Dr. Sam Patel, dentist and practice owner, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Dr. Patel gets a three-year plan with costs that fit the practice. |
| L2 Client business | Predictable spend. |
| L3 MSP | vCIO time on advice, not formatting. |
| L4 Community | Planning is resilience. |
| When it works | Draft; vCIO owns it. |
| FP: acts when it should not | Recommends spend the client does not need. |
| FN: misses it | Misses a needed upgrade. |
| Worse direction | FP |
| Blast radius | `BR-2` one client |
| Safeguards | Inventory rule: Agent assembles facts; recommendations and pricing are human; HO-9 AI drafts, a human sends (05-governance.md section 6); C-21 Output reconciliation (no invented numbers) (built) |
| Proof for the individual | IM-14 Owner and manager time: budget surprises per year |

#### `W-RPT-05` Client AI-use policy starter

R0 · report · repo: planned · persona: P-02 Ana Lopez, office manager and HIPAA privacy contact, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Ana gets a starter AI-use policy for Contoso that says, plainly, no patient details in public chatbots. |
| L2 Client business | PHI stays out of consumer AI tools. |
| L3 MSP | A useful, honest service for clients asking about AI. |
| L4 Community | Small businesses need simple AI rules; giving them good ones raises trust in AI locally. |
| When it works | Starter template labeled not legal advice; client adopts. |
| FP: acts when it should not | Template is taken as legal advice and is wrong for the client. |
| FN: misses it | No policy; staff paste PHI into public tools. |
| Worse direction | FN |
| Blast radius | `BR-2` one client's staff |
| Safeguards | Inventory rule: Template draft; client and their counsel own the final policy; HO-9 AI drafts, a human sends (05-governance.md section 6); C-42 Staff training and acceptable use (partial) |
| Proof for the individual | IM-11 Understood and accountable: staff who can state the rule; observed PHI-in-prompt events |

#### `W-RPT-06` Internal operations metrics (resolution time, first-contact resolution, SLA, backlog)

R0 · report · repo: planned · persona: P-29 Elena Park, service delivery manager, the MSP (synthetic)

| | |
|---|---|
| L1 Individual | Elena's weekly metrics include minutes until people can work again, not only tickets closed. |
| L2 Client business | Clients get service measured by their experience. |
| L3 MSP | Leaders steer by outcomes for people. |
| L4 Community | What an MSP measures shapes how its technicians treat people. |
| When it works | Metrics report. |
| FP: acts when it should not | Metrics used to rank individual technicians (stays human, W-TRN-04). |
| FN: misses it | Metrics miss what matters. |
| Worse direction | FP |
| Blast radius | `BR-5` how the MSP is run |
| Safeguards | Inventory rule: Read-only; metrics describe the queue, not individual performance reviews (see W-TRN-04 note); C-21 Output reconciliation (no invented numbers) (built); W-TRN-04 New technician onboarding and performance coaching (kept human) |
| Proof for the individual | IM-01 Time back to work: median minutes until people can work again, per client and per month |

### KB: Documentation and knowledge base

| Id | Item | Risk | Persona | Worse | Blast | Metric | Rank |
|---|---|---|---|---|---|---|---|
| `W-KB-01` | KB article drafting from resolved tickets | R1 | P-20 tech-ana | FP | BR-2 | IM-13 |  |
| `W-KB-02` | Client documentation upkeep (network, contacts, configurations) | R1 | P-30 Theo Grant | FP | BR-2 | IM-13 |  |
| `W-KB-03` | Runbook and SOP authoring | R0 | P-30 Theo Grant | FP | BR-2 | IM-13 |  |
| `W-KB-04` | Cited question answering for technicians (RAG) | R0 | P-30 Theo Grant | FP | BR-1 | IM-13 | 6 |
| `W-KB-05` | Stale and conflicting article detection | R0 | P-30 Theo Grant | FN | BR-2 | IM-13 |  |
| `W-KB-06` | Authorized contacts and escalation lists per client | R0 | P-02 Ana Lopez | FN | BR-2 | IM-04 | 9 |

#### `W-KB-01` KB article drafting from resolved tickets

R1 · report, eval · repo: planned · persona: P-20 tech-ana, Tier 1 technician (repo identity), the MSP (synthetic)

| | |
|---|---|
| L1 Individual | tech-ana turns a solved ticket into a KB draft in two minutes. |
| L2 Client business | Fixes are reused. |
| L3 MSP | Knowledge kept as people move on. |
| L4 Community | Shared knowledge lifts every technician. |
| When it works | Draft from the resolved ticket; technician edits and publishes. |
| FP: acts when it should not | Draft contains PHI or a wrong fix. |
| FN: misses it | Knowledge lost. |
| Worse direction | FP |
| Blast radius | `BR-2` everyone who uses the article |
| Safeguards | Inventory rule: Draft only; a technician reviews and publishes; client data stripped and checked; C-25 Data classification and pre-prompt redaction gate (built); C-41 Evaluation gate before promotion (partial); C-26 Per-tenant retrieval isolation (partial) |
| Proof for the individual | IM-13 Right answer with a source: articles accepted without factual edit; PHI in articles (target 0) |

#### `W-KB-02` Client documentation upkeep (network, contacts, configurations)

R1 · report · repo: planned · persona: P-30 Theo Grant, new Tier 1 technician, first month, the MSP (synthetic)

| | |
|---|---|
| L1 Individual | Theo, a new technician, finds Contoso's correct network notes at 7:45 when Priya calls. |
| L2 Client business | Faster fixes. |
| L3 MSP | Current documentation. |
| L4 Community | Documentation is the memory of a small MSP. |
| When it works | Change suggestions; technician confirms. |
| FP: acts when it should not | Writes a wrong value (an old IP), leading to a bad change. |
| FN: misses it | Docs stay stale. |
| Worse direction | FP |
| Blast radius | `BR-2` one client |
| Safeguards | Inventory rule: Agent flags stale pages against live data and drafts updates; human approves; C-26 Per-tenant retrieval isolation (partial); C-27 Tenant isolation of prompts, context, logs and error text (partial) |
| Proof for the individual | IM-13 Right answer with a source: docs found wrong during tickets |

#### `W-KB-03` Runbook and SOP authoring

R0 · report · repo: partial · persona: P-30 Theo Grant, new Tier 1 technician, first month, the MSP (synthetic)

| | |
|---|---|
| L1 Individual | Theo follows a clear runbook instead of guessing. |
| L2 Client business | Consistent service. |
| L3 MSP | Runbooks exist. |
| L4 Community | Good runbooks let newer people do skilled work safely. |
| When it works | Draft; engineer reviews. |
| FP: acts when it should not | A drafted runbook has a wrong step that a new technician follows on a client system. |
| FN: misses it | No runbook; Theo improvises on a task he has never done. |
| Worse direction | FP |
| Blast radius | `BR-2` everyone who follows it |
| Safeguards | Inventory rule: AI-assisted drafts; author owns the content; C-41 Evaluation gate before promotion (partial) |
| Proof for the individual | IM-13 Right answer with a source: runbook steps corrected after use |

#### `W-KB-04` Cited question answering for technicians (RAG)

R0 · read-lever, eval · repo: partial · persona: P-30 Theo Grant, new Tier 1 technician, first month, the MSP (synthetic) · **leverage rank 6**

| | |
|---|---|
| L1 Individual | Theo asks how Contoso's imaging bridge reconnects and gets a cited answer in one minute; Priya is back to work sooner. |
| L2 Client business | Faster fixes at the first call. |
| L3 MSP | 2,000-6,000 questions a month answered from the MSP's own knowledge. |
| L4 Community | New technicians become effective fast: automation moves people up. |
| When it works | Retrieval from the client's own sources only; refuses when there is no source. |
| FP: acts when it should not | Confident wrong answer, or another client's procedure in the answer. |
| FN: misses it | 'No source' refusal; Theo escalates (acceptable). |
| Worse direction | FP |
| Blast radius | `BR-1` one ticket; BR-2 on cross-tenant leakage |
| Safeguards | Inventory rule: Answers cite the client's own documents; refuses when there is no source; client A never sees client B; C-26 Per-tenant retrieval isolation (partial); C-27 Tenant isolation of prompts, context, logs and error text (partial); C-12 Untrusted input wrapping (built); C-41 Evaluation gate before promotion (partial) |
| Proof for the individual | IM-13 Right answer with a source: share of answers correct with a cited source; minutes to answer; IM-01 for tickets where it was used |

#### `W-KB-05` Stale and conflicting article detection

R0 · eval, report · repo: planned · persona: P-30 Theo Grant, new Tier 1 technician, first month, the MSP (synthetic)

| | |
|---|---|
| L1 Individual | Conflicting articles are found before Theo follows the wrong one. |
| L2 Client business | Fewer wrong fixes. |
| L3 MSP | KB stays trustworthy. |
| L4 Community | Same macro effect as W-KB-04; see that chain. |
| When it works | Report. |
| FP: acts when it should not | Flags fine articles. |
| FN: misses it | Conflicting articles remain; Theo follows the outdated one. |
| Worse direction | FN |
| Blast radius | `BR-2` users of the article |
| Safeguards | Inventory rule: Read-only report; owner fixes; C-41 Evaluation gate before promotion (partial) |
| Proof for the individual | IM-13 Right answer with a source: conflicting article pairs open |

#### `W-KB-06` Authorized contacts and escalation lists per client

R0 · read-lever · repo: planned · persona: P-02 Ana Lopez, office manager and HIPAA privacy contact, Contoso Dental (synthetic) · **leverage rank 9**

| | |
|---|---|
| L1 Individual | Only Ana and Dr. Patel may authorize new hires and access at Contoso, and the list is current, so a request from anyone else is caught. |
| L2 Client business | No access granted on a stranger's say-so. |
| L3 MSP | Verification is consistent. |
| L4 Community | Authorized-contact lists are the root of trust for every access change. |
| When it works | Read lever returns the current list to a human. |
| FP: acts when it should not | List wrong; a legitimate requester is rejected. |
| FN: misses it | Outdated list lets a departed manager authorize. |
| Worse direction | FN |
| Blast radius | `BR-2` one tenant's access decisions |
| Safeguards | Inventory rule: Agents read the list to check requesters; only a human edits it, on the client's instruction; C-04 Per-client scope at the tool layer (built); C-20 Read levers cannot write (built); C-30 Requester identity verification for access-affecting levers (built) |
| Proof for the individual | IM-04 People wrongly acted on: access changes authorized by a non-authorized contact (target 0); list age |

### BIL: Billing inputs

| Id | Item | Risk | Persona | Worse | Blast | Metric | Rank |
|---|---|---|---|---|---|---|---|
| `W-BIL-01` | Time entry and ticket note quality | R1 | P-20 tech-ana | FP | BR-1 | IM-12 |  |
| `W-BIL-02` | Per-seat and per-device count true-up | R0 | P-26 Rosa Diaz | FP | BR-2 | IM-14 |  |
| `W-BIL-03` | Managed versus project or out-of-scope classification | R1 | P-02 Ana Lopez | FP | BR-2 | IM-14 |  |

#### `W-BIL-01` Time entry and ticket note quality

R1 · report · repo: not in blueprint · persona: P-20 tech-ana, Tier 1 technician (repo identity), the MSP (synthetic)

| | |
|---|---|
| L1 Individual | tech-ana spends two minutes on notes at day's end instead of ten. |
| L2 Client business | Clients see accurate notes. |
| L3 MSP | Better billing data. |
| L4 Community | Less admin is more time for people. |
| When it works | Note draft from ticket activity; technician confirms. |
| FP: acts when it should not | The draft claims work tech-ana did not do; if she confirms it unread, the client is billed for it under her name. |
| FN: misses it | Notes stay thin; when the client disputes the invoice weeks later, tech-ana has no record and rebuilds it from memory. |
| Worse direction | FP |
| Blast radius | `BR-1` one ticket |
| Safeguards | Inventory rule: Agent drafts notes from lever and ticket activity; the technician confirms time and wording; HO-9 AI drafts, a human sends (05-governance.md section 6) |
| Proof for the individual | IM-12 Technician toil and growth: technician minutes per day on notes; notes disputed by clients |

#### `W-BIL-02` Per-seat and per-device count true-up

R0 · report, eval · repo: planned · persona: P-26 Rosa Diaz, billing specialist, the MSP (synthetic)

| | |
|---|---|
| L1 Individual | Rosa's monthly true-up is right, so Dr. Patel is billed for the seats he has. |
| L2 Client business | Fair bills. |
| L3 MSP | Margin protected. |
| L4 Community | Fair billing is trust. |
| When it works | Reconciled count. |
| FP: acts when it should not | Overbills for seats or devices the client no longer has; Rosa issues a credit and trust drops. |
| FN: misses it | Underbills; the MSP absorbs the cost without anyone noticing. |
| Worse direction | FP |
| Blast radius | `BR-2` one invoice |
| Safeguards | Inventory rule: Read-only reconciliation; billing approves every change; C-21 Output reconciliation (no invented numbers) (built) |
| Proof for the individual | IM-14 Owner and manager time: billing corrections per month |

#### `W-BIL-03` Managed versus project or out-of-scope classification

R1 · agent-triage · repo: not in blueprint · persona: P-02 Ana Lopez, office manager and HIPAA privacy contact, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Ana is not surprised by a bill for work her contract covers. |
| L2 Client business | Fair invoices. |
| L3 MSP | Fewer disputes. |
| L4 Community | Same macro effect as W-BIL-02; see that chain. |
| When it works | Suggestion; a human decides. |
| FP: acts when it should not | Covered work classified as billable. |
| FN: misses it | MSP absorbs project cost. |
| Worse direction | FP |
| Blast radius | `BR-2` one invoice |
| Safeguards | Inventory rule: Suggestion with the agreement clause; a human decides; C-12 Untrusted input wrapping (built) |
| Proof for the individual | IM-14 Owner and manager time: disputed charges per client |

### PRJ: Project work

| Id | Item | Risk | Persona | Worse | Blast | Metric | Rank |
|---|---|---|---|---|---|---|---|
| `W-PRJ-01` | New client onboarding to the MSP (discovery and baseline) | R0 | P-12 Hannah Ortiz | FN | BR-3 | IM-15 |  |
| `W-PRJ-03` | Microsoft 365 migrations (tenant to tenant, mailbox moves) | R3 | P-11 Grace Okafor | FP | BR-3 | IM-01 |  |
| `W-PRJ-04` | Copilot and AI adoption readiness for clients | R0 | P-02 Ana Lopez | FP | BR-3 | IM-06 |  |
| `W-PRJ-05` | Azure infrastructure projects | R3 | P-07 Morgan Reyes | FP | BR-3 | IM-08 |  |
| `W-PRJ-06` | Project scoping and estimates | R0 | P-03 Dr. Sam Patel | FP | BR-2 | IM-14 |  |

#### `W-PRJ-01` New client onboarding to the MSP (discovery and baseline)

R0 · read-lever, report · repo: partial · persona: P-12 Hannah Ortiz, paralegal, Litware Legal (14 staff) (synthetic)

| | |
|---|---|
| L1 Individual | Litware joins the MSP and Hannah's account has MFA within the first two weeks. |
| L2 Client business | Risks fixed early. |
| L3 MSP | Onboarding discovery is fast and consistent. |
| L4 Community | Every new client raises the community baseline. |
| When it works | Read-only discovery, findings report. |
| FP: acts when it should not | Discovery uses broader rights than needed. |
| FN: misses it | Misses a risk. |
| Worse direction | FN |
| Blast radius | `BR-3` the new client |
| Safeguards | Inventory rule: Read-only discovery report; remediation goes through normal approved levers; C-04 Per-client scope at the tool layer (built); C-20 Read levers cannot write (built); C-38 Agent and technician access review; least-privilege delegated access (partial) |
| Proof for the individual | IM-15 Silent-failure lead time: days from start to baseline MFA coverage |

#### `W-PRJ-03` Microsoft 365 migrations (tenant to tenant, mailbox moves)

R3 · write-lever-approval · repo: not in blueprint · persona: P-11 Grace Okafor, bookkeeper, Northwind Bookkeeping (9 staff) (synthetic)

| | |
|---|---|
| L1 Individual | Grace's mailbox moves over a weekend and works Monday morning. |
| L2 Client business | No lost email. |
| L3 MSP | Migrations predictable. |
| L4 Community | Clean migrations keep small firms running. |
| When it works | Dry-run plan and staged cutover with approvals. |
| FP: acts when it should not | Wrong mailbox cut over; data loss. |
| FN: misses it | A conflict the pre-flight should have caught (an oversized mailbox, a missing licence) surfaces mid-cutover; Grace loses mail during month-end close. |
| Worse direction | FP |
| Blast radius | `BR-3` a tenant |
| Safeguards | Inventory rule: Scripted batches with dry-run and engineer approval per batch; C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-07 Four-eyes rule (no self-approval) (built); C-32 Blast-radius and rate limits (partial) |
| Proof for the individual | IM-01 Time back to work: share of users signing in successfully Monday morning; items lost (target 0) |

#### `W-PRJ-04` Copilot and AI adoption readiness for clients

R0 · report · repo: planned · persona: P-02 Ana Lopez, office manager and HIPAA privacy contact, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Ana learns what must be fixed before Contoso turns on Copilot. |
| L2 Client business | AI adopted safely. |
| L3 MSP | A credible service. |
| L4 Community | Safe AI adoption at small businesses is how trust in AI is earned. |
| When it works | Readiness report. |
| FP: acts when it should not | Says ready when not. |
| FN: misses it | Overcautious. |
| Worse direction | FP |
| Blast radius | `BR-3` a tenant |
| Safeguards | Inventory rule: Read-only assessment and score; recommendation reviewed by a human; W-M365-07 Oversharing and external sharing review (Copilot readiness) (related item) |
| Proof for the individual | IM-06 Exposure window: overshared items found and fixed before rollout |

#### `W-PRJ-05` Azure infrastructure projects

R3 · write-lever-approval · repo: planned · persona: P-07 Morgan Reyes, portfolio analyst, Fabrikam Capital (synthetic)

| | |
|---|---|
| L1 Individual | Fabrikam's file server moves to Azure with a weekend cutover. |
| L2 Client business | Modern infrastructure. |
| L3 MSP | Repeatable projects. |
| L4 Community | Same macro effect as W-PRJ-03; see that chain. |
| When it works | Validated templates; approvals. |
| FP: acts when it should not | Wrong resource changed. |
| FN: misses it | Validation misses a template error; the weekend cutover fails and Morgan starts Monday without the file share. |
| Worse direction | FP |
| Blast radius | `BR-3` a tenant |
| Safeguards | Inventory rule: Infrastructure as code, validate and what-if first; engineer approves the deployment; C-05 Dry-run by default with a diff (built); C-06 Lead approval bound to lever, client and params (built); C-07 Four-eyes rule (no self-approval) (built); C-24 CI with least-privilege token and pinned actions (built) |
| Proof for the individual | IM-08 Disruption minutes: minutes of unplanned downtime |

#### `W-PRJ-06` Project scoping and estimates

R0 · report · repo: not in blueprint · persona: P-03 Dr. Sam Patel, dentist and practice owner, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | Dr. Patel gets an estimate that matches the final bill. |
| L2 Client business | No surprise costs. |
| L3 MSP | Better margins. |
| L4 Community | Honest estimates are trust. |
| When it works | Draft from past projects. |
| FP: acts when it should not | Underestimates; Dr. Patel gets a bill far above the quote, or the MSP absorbs the overrun. |
| FN: misses it | No similar project is found; the quote takes days and Dr. Patel delays a needed upgrade. |
| Worse direction | FP |
| Blast radius | `BR-2` one client |
| Safeguards | Inventory rule: Agent finds similar past projects (RAG); the estimate is human; HO-9 AI drafts, a human sends (05-governance.md section 6) |
| Proof for the individual | IM-14 Owner and manager time: final cost vs estimate |

### TOOL: Internal tooling and the AI/automation platform

| Id | Item | Risk | Persona | Worse | Blast | Metric | Rank |
|---|---|---|---|---|---|---|---|
| `W-TOOL-01` | Lever authoring (new PowerShell or Python lever) | R1 | P-27 the AI & Automation Engineer | FP | BR-4 | IM-04 |  |
| `W-TOOL-02` | Model gateway and routing configuration | R1 | P-27 the AI & Automation Engineer | FP | BR-4 | IM-04 |  |
| `W-TOOL-03` | Prompt library and standards | R0 | P-20 tech-ana | FP | BR-4 | IM-13 |  |
| `W-TOOL-04` | Eval golden sets and accuracy reports | R0 | P-27 the AI & Automation Engineer | FP | BR-4 | IM-04 |  |
| `W-TOOL-05` | Prompt-injection corpus and guard maintenance | R0 | P-01 Priya Nair | FN | BR-4 | IM-04 |  |
| `W-TOOL-06` | Approval queue operation | R1 | P-22 lead-lee | FP | BR-4 | IM-01 |  |
| `W-TOOL-07` | CI/CD pipelines and release process | R1 | P-27 the AI & Automation Engineer | FN | BR-4 | IM-04 |  |
| `W-TOOL-09` | Production monitoring of AI and automation | R0 | P-27 the AI & Automation Engineer | FN | BR-4 | IM-04 |  |
| `W-TOOL-10` | MCP server and Teams technician assistant | R1 | P-20 tech-ana | FP | BR-4 | IM-12 |  |
| `W-TOOL-11` | PSA, RMM and Graph integration maintenance | R1 | P-27 the AI & Automation Engineer | FN | BR-4 | IM-04 |  |
| `W-TOOL-12` | Review of existing automation scripts | R0 | P-27 the AI & Automation Engineer | FN | BR-4 | IM-04 |  |
| `W-TOOL-13` | Use-case intake and ROI scoring | R0 | P-30 Theo Grant | FP | BR-5 | IM-12 |  |
| `W-TOOL-14` | Emerging technology evaluation | R0 | P-27 the AI & Automation Engineer | FP | BR-5 | IM-12 |  |

#### `W-TOOL-01` Lever authoring (new PowerShell or Python lever)

R1 · eval · repo: exists · persona: P-27 the AI & Automation Engineer, builds and runs the platform, the MSP (synthetic)

| | |
|---|---|
| L1 Individual | Each new lever is tested on fixtures, so when Priya's MFA is reset the change is exactly the diff the lead saw. |
| L2 Client business | Every client gets the same tested action. |
| L3 MSP | 4-12 levers a month without new risk. |
| L4 Community | Each lever is a multiplier for good or harm across all tenants. |
| When it works | PR with tests, eval and review. |
| FP: acts when it should not | A buggy lever passes tests and acts wrongly at scale. |
| FN: misses it | The lever is never built; toil stays. |
| Worse direction | FP |
| Blast radius | `BR-4` all tenants with the lever enabled |
| Safeguards | Inventory rule: Code review and passing tests before registration; registry changes are reviewed like code; C-01 Lever registry, default deny (built); C-02 Parameter schema validation (built); C-29 Risk class and version on every lever, enforced by class (partial); C-37 Lever change management with staged rollout (partial); C-41 Evaluation gate before promotion (partial); CM-1 PR with tests and reviewer (05-governance.md section 8) |
| Proof for the individual | IM-04 People wrongly acted on: wrong-action incidents per 1,000 executes; IM-12 toil minutes removed |

#### `W-TOOL-02` Model gateway and routing configuration

R1 · eval · repo: exists · persona: P-27 the AI & Automation Engineer, builds and runs the platform, the MSP (synthetic)

| | |
|---|---|
| L1 Individual | Routing sends each task to an approved model; regulated data never goes to a hosted provider without approval. |
| L2 Client business | PHI and NPI stay inside agreed boundaries. |
| L3 MSP | Provider changes are config, not code. |
| L4 Community | Routing discipline keeps AI benefits without data leakage. |
| When it works | Config change with eval. |
| FP: acts when it should not | Routes regulated data to an unapproved provider. |
| FN: misses it | Task routed to a weak model; worse suggestions. |
| Worse direction | FP |
| Blast radius | `BR-4` all tenants |
| Safeguards | Inventory rule: Routing thresholds change only on eval evidence; hosted providers stay off unless approved; C-15 Loopback-only model gateway, hosted providers off (built); C-16 Provider abstraction against lock-in (built); C-28 Hosted AI provider approval gate (built); C-41 Evaluation gate before promotion (partial) |
| Proof for the individual | IM-04 People wrongly acted on: regulated items sent off-machine without approval (target 0) |

#### `W-TOOL-03` Prompt library and standards

R0 · eval · repo: planned · persona: P-20 tech-ana, Tier 1 technician (repo identity), the MSP (synthetic)

| | |
|---|---|
| L1 Individual | tech-ana uses a tested prompt for replies instead of writing her own. |
| L2 Client business | Consistent quality. |
| L3 MSP | Prompt standards. |
| L4 Community | Shared standards lift everyone. |
| When it works | Library with evals. |
| FP: acts when it should not | Bad prompt spreads. |
| FN: misses it | Ad-hoc prompts. |
| Worse direction | FP |
| Blast radius | `BR-4` all users of the prompt |
| Safeguards | Inventory rule: Prompt changes need passing prompt tests; C-41 Evaluation gate before promotion (partial) |
| Proof for the individual | IM-13 Right answer with a source: prompt changes passing evals |

#### `W-TOOL-04` Eval golden sets and accuracy reports

R0 · eval · repo: exists · persona: P-27 the AI & Automation Engineer, builds and runs the platform, the MSP (synthetic)

| | |
|---|---|
| L1 Individual | Every change is measured on golden sets before it reaches Priya's ticket. |
| L2 Client business | Fewer AI mistakes on clients. |
| L3 MSP | Evidence of accuracy. |
| L4 Community | Measured AI is trustworthy AI. |
| When it works | Weekly eval reports. |
| FP: acts when it should not | Overfit evals give false confidence. |
| FN: misses it | No measurement. |
| Worse direction | FP |
| Blast radius | `BR-4` all tenants |
| Safeguards | Inventory rule: Reports labelled fixture-based; humans review labels; C-41 Evaluation gate before promotion (partial) |
| Proof for the individual | IM-04 People wrongly acted on: regressions caught before release |

#### `W-TOOL-05` Prompt-injection corpus and guard maintenance

R0 · eval · repo: exists · persona: P-01 Priya Nair, dental hygienist, Contoso Dental (synthetic)

| | |
|---|---|
| L1 Individual | A malicious email pasted into Priya's ticket cannot make the agent reset her MFA. |
| L2 Client business | Clients are protected from prompt injection. |
| L3 MSP | Guard measured monthly. |
| L4 Community | Injection is the new social engineering; guarding it protects everyone. |
| When it works | Corpus and guard updated with new cases. |
| FP: acts when it should not | Flags harmless tickets; they go to the security queue (safe direction). |
| FN: misses it | A new injection pattern gets through to a proposal. |
| Worse direction | FN |
| Blast radius | `BR-4` all tenants |
| Safeguards | Inventory rule: Tripwire only; the lever registry is the control; C-12 Untrusted input wrapping (built); C-13 Prompt-injection tripwire (built); C-14 Model output cannot choose the lever or its parameters (built); AIR-1 prompt injection (05-governance.md section 5) |
| Proof for the individual | IM-04 People wrongly acted on: injection cases that reached a lever proposal (target 0) |

#### `W-TOOL-06` Approval queue operation

R1 · write-lever-approval · repo: exists · persona: P-22 lead-lee, service desk lead and approver (repo identity), the MSP (synthetic)

| | |
|---|---|
| L1 Individual | lead-lee reviews a clear diff in 30 seconds; Priya's reset is approved quickly and correctly. |
| L2 Client business | Every write has a human owner. |
| L3 MSP | Approvals are fast and meaningful. |
| L4 Community | Real human review is the backbone of safe automation. |
| When it works | Queue with diffs, bound approvals, four-eyes. |
| FP: acts when it should not | Rubber-stamp approvals. |
| FN: misses it | Backlog; people wait. |
| Worse direction | FP |
| Blast radius | `BR-4` all write levers |
| Safeguards | Inventory rule: Approver cannot be the requester; approval is recorded in the audit chain; rejection reasons become eval data; C-06 Lead approval bound to lever, client and params (built); C-07 Four-eyes rule (no self-approval) (built); C-19 Approval queue and viewer hardening (built); C-40 Monitoring and alerting on automation behaviour (partial); C-44 Authenticated approvers (built); AIR-10 rubber-stamp approvals (05-governance.md section 5) |
| Proof for the individual | IM-01 Time back to work: minutes from proposal to decision; approvals faster than a diff can be read (flagged) |

#### `W-TOOL-07` CI/CD pipelines and release process

R1 · eval · repo: partial · persona: P-27 the AI & Automation Engineer, builds and runs the platform, the MSP (synthetic)

| | |
|---|---|
| L1 Individual | A broken change cannot merge, so Monday's release does not break Priya's reset. |
| L2 Client business | Stable service. |
| L3 MSP | Release discipline. |
| L4 Community | Same macro effect as W-TOOL-04; see that chain. |
| When it works | CI gates. |
| FP: acts when it should not | Flaky gates block good changes. |
| FN: misses it | Bad changes merge. |
| Worse direction | FN |
| Blast radius | `BR-4` all tenants |
| Safeguards | Inventory rule: Pull request review and green CI before merge; C-24 CI with least-privilege token and pinned actions (built); C-23 Commit-time secret scan (built); C-37 Lever change management with staged rollout (partial) |
| Proof for the individual | IM-04 People wrongly acted on: incidents traced to releases |

#### `W-TOOL-09` Production monitoring of AI and automation

R0 · report · repo: planned · persona: P-27 the AI & Automation Engineer, builds and runs the platform, the MSP (synthetic)

| | |
|---|---|
| L1 Individual | A spike in wrong suggestions or after-hours executes is seen within minutes. |
| L2 Client business | Problems stopped early. |
| L3 MSP | Operational visibility. |
| L4 Community | Monitoring makes automation's harm small and short. |
| When it works | Monitoring and alerts. |
| FP: acts when it should not | Noise. |
| FN: misses it | Silent failure across tenants. |
| Worse direction | FN |
| Blast radius | `BR-4` all tenants |
| Safeguards | Inventory rule: Read-only dashboards and alerts; humans respond; C-40 Monitoring and alerting on automation behaviour (partial); C-31 Kill switch per lever and per tenant (built) |
| Proof for the individual | IM-04 People wrongly acted on: minutes from anomaly to human; people affected before detection |

#### `W-TOOL-10` MCP server and Teams technician assistant

R1 · read-lever, write-lever-approval · repo: planned · persona: P-20 tech-ana, Tier 1 technician (repo identity), the MSP (synthetic)

| | |
|---|---|
| L1 Individual | tech-ana asks in Teams for a sign-in check and gets it without leaving the ticket. |
| L2 Client business | Faster help. |
| L3 MSP | Tools where technicians work. |
| L4 Community | Same macro effect as W-KB-04; see that chain. |
| When it works | MCP tools with the same lever rules. |
| FP: acts when it should not | A tool exposes a write without approval. |
| FN: misses it | No assistant. |
| Worse direction | FP |
| Blast radius | `BR-4` all tenants |
| Safeguards | Inventory rule: Read-only by default; write levers keep their approval rules; C-01 Lever registry, default deny (built); C-03 Role-based authorization; agents may only dry-run writes (built); C-06 Lead approval bound to lever, client and params (built); AIR-12 AI supply chain (05-governance.md section 5) |
| Proof for the individual | IM-12 Technician toil and growth: technician minutes saved per day |

#### `W-TOOL-11` PSA, RMM and Graph integration maintenance

R1 · eval · repo: planned · persona: P-27 the AI & Automation Engineer, builds and runs the platform, the MSP (synthetic)

| | |
|---|---|
| L1 Individual | A Graph API change is caught before levers start failing silently. |
| L2 Client business | No broken automations. |
| L3 MSP | Integrations maintained. |
| L4 Community | Same macro effect as W-TOOL-09; see that chain. |
| When it works | Contract tests. |
| FP: acts when it should not | False alarms. |
| FN: misses it | Silent breakage. |
| Worse direction | FN |
| Blast radius | `BR-4` all tenants |
| Safeguards | Inventory rule: Contract tests against mocks; changes through CI; C-17 Timeouts and failure containment (built); C-41 Evaluation gate before promotion (partial) |
| Proof for the individual | IM-04 People wrongly acted on: integration failures reaching users |

#### `W-TOOL-12` Review of existing automation scripts

R0 · report · repo: planned · persona: P-27 the AI & Automation Engineer, builds and runs the platform, the MSP (synthetic)

| | |
|---|---|
| L1 Individual | An old RMM script with a hard-coded password running across all clients is found and fixed. |
| L2 Client business | Hidden risk removed. |
| L3 MSP | Script inventory. |
| L4 Community | Old scripts are a supply-chain risk to every client. |
| When it works | Review report. |
| FP: acts when it should not | Flags harmless scripts. |
| FN: misses it | Misses a risky one. |
| Worse direction | FN |
| Blast radius | `BR-4` all tenants |
| Safeguards | Inventory rule: Read-only review; migration through normal lever process; C-22 Protected paths need owner review (built); C-23 Commit-time secret scan (built) |
| Proof for the individual | IM-04 People wrongly acted on: risky scripts found and fixed |

#### `W-TOOL-13` Use-case intake and ROI scoring

R0 · report · repo: planned · persona: P-30 Theo Grant, new Tier 1 technician, first month, the MSP (synthetic)

| | |
|---|---|
| L1 Individual | Theo's idea for removing his worst toil is scored and credited. |
| L2 Client business | Automation picked for real benefit. |
| L3 MSP | Pipeline of good ideas. |
| L4 Community | People who do the work shape the automation. |
| When it works | Scoring report. |
| FP: acts when it should not | Prioritizes cost cutting over people. |
| FN: misses it | Good ideas lost. |
| Worse direction | FP |
| Blast radius | `BR-5` the program's direction |
| Safeguards | Inventory rule: Scores are inputs; leadership decides priority; W-TRN-04 New technician onboarding and performance coaching (kept human) |
| Proof for the individual | IM-12 Technician toil and growth: ideas from technicians shipped; time-to-work gains per shipped idea |

#### `W-TOOL-14` Emerging technology evaluation

R0 · eval, report · repo: planned · persona: P-27 the AI & Automation Engineer, builds and runs the platform, the MSP (synthetic)

| | |
|---|---|
| L1 Individual | New tools are tried on fixtures before anyone's data touches them. |
| L2 Client business | Safe adoption. |
| L3 MSP | Informed choices. |
| L4 Community | Measured adoption. |
| When it works | Evaluation report. |
| FP: acts when it should not | Adopts hype. |
| FN: misses it | Misses a real gain. |
| Worse direction | FP |
| Blast radius | `BR-5` the program's direction |
| Safeguards | Inventory rule: Recommendations backed by repo evals and cited sources; C-28 Hosted AI provider approval gate (built); C-43 AI vendor and subprocessor register (built) |
| Proof for the individual | IM-12 Technician toil and growth: evaluations completed with a decision |

### GOV: AI governance

| Id | Item | Risk | Persona | Worse | Blast | Metric | Rank |
|---|---|---|---|---|---|---|---|
| `W-GOV-01` | AI acceptable-use policy and data-in-prompt rules | R0 | P-20 tech-ana | FN | BR-5 | IM-11 |  |
| `W-GOV-03` | Agent identity and lever permission review | R0 | P-27 the AI & Automation Engineer | FN | BR-4 | IM-04 |  |

#### `W-GOV-01` AI acceptable-use policy and data-in-prompt rules

R0 · report · repo: planned · persona: P-20 tech-ana, Tier 1 technician (repo identity), the MSP (synthetic)

| | |
|---|---|
| L1 Individual | tech-ana knows exactly what may go into a prompt. |
| L2 Client business | Client data protected by habit. |
| L3 MSP | Policy in place. |
| L4 Community | Clear rules make AI trustworthy. |
| When it works | Policy draft; leadership adopts. |
| FP: acts when it should not | Too strict; useful work blocked. |
| FN: misses it | Too loose; PHI in prompts. |
| Worse direction | FN |
| Blast radius | `BR-5` the program |
| Safeguards | Inventory rule: Leadership approves the policy; C-42 Staff training and acceptable use (partial); C-25 Data classification and pre-prompt redaction gate (built) |
| Proof for the individual | IM-11 Understood and accountable: staff who can state the rule; PHI-in-prompt events |

#### `W-GOV-03` Agent identity and lever permission review

R0 · report · repo: partial · persona: P-27 the AI & Automation Engineer, builds and runs the platform, the MSP (synthetic)

| | |
|---|---|
| L1 Individual | The triage agent can still only dry-run, and no technician holds tenants they do not serve. |
| L2 Client business | Least privilege kept. |
| L3 MSP | Access reviewed quarterly. |
| L4 Community | Over-privileged agents are the scaled version of an over-privileged admin. |
| When it works | Review report. |
| FP: acts when it should not | Removes needed access. |
| FN: misses it | Excess access stays. |
| Worse direction | FN |
| Blast radius | `BR-4` all tenants |
| Safeguards | Inventory rule: Read-only review; changes by human pull request; C-38 Agent and technician access review; least-privilege delegated access (partial); C-03 Role-based authorization; agents may only dry-run writes (built); AIR-2 over-privileged agents (05-governance.md section 5) |
| Proof for the individual | IM-04 People wrongly acted on: excess grants found per review |

### TRN: Staff training on AI

| Id | Item | Risk | Persona | Worse | Blast | Metric | Rank |
|---|---|---|---|---|---|---|---|
| `W-TRN-01` | Technician training: reading suggestions and approvals | R0 | P-30 Theo Grant | FN | BR-5 | IM-12 |  |
| `W-TRN-02` | Account manager training: explaining AI to clients | R0 | P-25 Owen Price | FP | BR-5 | IM-11 |  |
| `W-TRN-03` | Correction feedback loop coaching | R0 | P-20 tech-ana | FP | BR-5 | IM-12 |  |

#### `W-TRN-01` Technician training: reading suggestions and approvals

R0 · report · repo: planned · persona: P-30 Theo Grant, new Tier 1 technician, first month, the MSP (synthetic)

| | |
|---|---|
| L1 Individual | Theo learns to read a diff and to reject a wrong proposal, and sees the program as a promotion path, not a threat. |
| L2 Client business | Better approvals for clients. |
| L3 MSP | Skilled reviewers. |
| L4 Community | Automation moves people up, not out, only if people are trained to move up. |
| When it works | Training sessions. |
| FP: acts when it should not | Training teaches over-trust. |
| FN: misses it | Untrained approvers. |
| Worse direction | FN |
| Blast radius | `BR-5` how every approval is made |
| Safeguards | Inventory rule: Human-led training with synthetic exercises; C-42 Staff training and acceptable use (partial) |
| Proof for the individual | IM-12 Technician toil and growth: share of technicians who caught a seeded wrong proposal in a drill |

#### `W-TRN-02` Account manager training: explaining AI to clients

R0 · report · repo: planned · persona: P-25 Owen Price, account manager and vCIO, the MSP (synthetic)

| | |
|---|---|
| L1 Individual | Owen explains to Dr. Patel what the AI does and does not do, honestly. |
| L2 Client business | Clients choose what the AI may touch with real understanding, including which data stays out of it. |
| L3 MSP | Account managers sell what exists, labeled as it is; no overclaim becomes a contract dispute. |
| L4 Community | Honest explanations at hundreds of small businesses are how local trust in AI is earned or lost. |
| When it works | Quarterly session with a plain script and the repo's honest labels. |
| FP: acts when it should not | The account manager oversells ('the AI handles security') and the client relaxes its own vigilance. |
| FN: misses it | The account manager cannot explain it, and the client refuses a safe, useful automation. |
| Worse direction | FP |
| Blast radius | `BR-5` client trust |
| Safeguards | Inventory rule: Human-led; claims limited to measured, labelled results; C-42 Staff training and acceptable use (partial); C-45 Synthetic data only and honest labels (partial) |
| Proof for the individual | IM-11 Understood and accountable: clients who can say what the AI does for them |

#### `W-TRN-03` Correction feedback loop coaching

R0 · eval, report · repo: partial · persona: P-20 tech-ana, Tier 1 technician (repo identity), the MSP (synthetic)

| | |
|---|---|
| L1 Individual | tech-ana's corrections improve triage and are never used to judge her. |
| L2 Client business | Better suggestions. |
| L3 MSP | Learning loop. |
| L4 Community | Feedback without fear. |
| When it works | Coaching on corrections. |
| FP: acts when it should not | Corrections used to judge individuals. |
| FN: misses it | No feedback. |
| Worse direction | FP |
| Blast radius | `BR-5` the learning loop |
| Safeguards | Inventory rule: Corrections are about the system's accuracy, not a score of the technician; W-TRN-04 New technician onboarding and performance coaching (kept human); C-41 Evaluation gate before promotion (partial) |
| Proof for the individual | IM-12 Technician toil and growth: corrections per week; correction-driven accuracy gains |

## 6. Macro: how the chains add up

### 6.1 Across 50 to 500 clients

Volumes are the inventory's reference scale (200 tenants, about 5,000 end users), scaled linearly as `01-work-inventory.md` suggests (50 tenants about x0.25, 500 tenants about x2.5). The minutes column is an **assumption, unverified**, chosen to be conservative; the MSP's PSA data replaces it (IQ-01). The output is person-hours returned *to the client's staff*, not technician hours.

| Chain | Items | Events/month at 200 tenants | Assumed minutes returned per event | Person-hours/month at 50 | at 200 | at 500 |
|---|---|---|---|---|---|---|
| Lockouts: password and MFA resets | W-IDM-01, W-IDM-02 | 280-700 | 20-40 | 23-117 | 93-467 | 233-1,167 |
| New hires ready on day one | W-ONB-01..07 | 60-150 | 120-240 | 30-150 | 120-600 | 300-1,500 |
| Tier 1 scripted fixes | W-SD-11 | 300-600 | 15-30 | 19-75 | 75-300 | 188-750 |
| Mail delivery questions answered | W-M365-03 | 100-250 | 15-45 | 6-47 | 25-188 | 62-469 |
| Quarantine releases | W-M365-04 | 100-300 | 10-30 | 4-38 | 17-150 | 42-375 |
| Technician questions answered with a source (end user's wait) | W-KB-04 | 2,000-6,000 | 3-5 | 25-125 | 100-500 | 250-1,250 |
| **Total (these six only)** | | | | **108-551** | **430-2,204** | **1,075-5,510** |

Read the total as roughly 3-14 full-time-equivalent people's worth of working time per month given back across the client base at reference scale (160 working hours per month), spread across thousands of people in pieces of 10-40 minutes. That is the honest shape of the benefit: no single client sees a dramatic number; each person sees a morning that was not lost. The protective chains (backups, baselines, BEC rules, exploited-flaw response) do not appear in this table at all, because their value is the rare day that does not become a disaster, and that is not measured in minutes.

**Correlated failure is the mirror image.** The same property that multiplies benefit multiplies harm. 16 chains have a worst case of `BR-4` (many tenants at once) and 10 of `BR-5` (the MSP itself). A lever with a 1% wrong-target rate, executed 500 times a month across 200 tenants, harms about 5 people a month; the same bug shipped to 500 tenants without rings harms them all in one afternoon. The bounds that matter at scale are therefore the ones that are still planned: staged rollout rings (`CM-5`, `C-37` partial), blast-radius caps (`C-32` planned), the kill switch (`C-31` planned), automation monitoring (`C-40` planned) and the restore-the-person-first runbook (`C-34`, `IR-3`, planned). Per-call bounds (registry, schema, scope, dry-run, four-eyes approval, audit) are built for the sample levers.

**Shared-mode risk across tenants.** CISA and partner agencies warn that attackers target MSPs because one foothold reaches many customers (joint advisory AA22-131A). Every automation platform is a new shared mode: one model gateway, one lever registry, one approval queue, one agent identity used across tenants. The per-client scope (`C-04`, `ISO-1`), per-tenant retrieval (`C-26`), tenant isolation of prompts and logs (`C-27`) and least-privilege delegated access (`C-38`, `ISO-10`) are what keep one compromised piece from becoming 500 compromised clients.

### 6.2 Second-order effects

**Technician job design: toil out, people up, not out.** The chains with the largest technician-hour effect are intake and triage (`W-SD-01`, `W-SD-02`: est. 3,000-5,000 tickets a month; at an assumed 2-4 minutes saved each, about 100-330 technician hours a month at reference scale), scripted fixes, backup and patch failure queues, and alert grouping. The design intent for those hours, written down so it can be held to:

- **Where the hours go.** Out-of-band verification calls (`W-IDM-04`, `C-30`), reviewing diffs carefully instead of clicking through (`W-TOOL-06`, `AIR-10`), proactive work (baseline gaps, stale accounts, oversharing), client conversations, and building the next lever. Every one of those is more skilled than the toil it replaces.
- **Growth path.** A Tier 1 technician who learns to read a diff, write a fixture and propose a lever (`W-TOOL-13`) is on the path to Tier 2 and to automation work. `W-TRN-01` and `W-TRN-03` exist to make that path real.
- **What it must not become.** Automation metrics and correction logs are never used to rank or judge individual technicians (`W-TRN-04` stays human; `W-TRN-03` coaching is about the system). If the program is seen as a headcount-cutting tool, technicians will stop correcting it, and the correction loop that keeps it safe dies. Leadership's stated position on this is an open question (IQ-03).
- **Deskilling and rubber-stamping.** If people only approve, they lose the skill to tell a right diff from a wrong one, and approvals become automatic. Counter-measures: seeded wrong proposals in training drills (`W-TRN-01` metric), alerts on approvals faster than a diff can be read (`C-40`), rotating technicians through manual work, and runbooks that teach the why (`W-KB-03`).
- **On-call humanity.** After-hours triage (`W-SD-12`) is the clearest case where automation improves a technician's own life: fewer 2 am pages that did not need a person.

**Client trust.** Small businesses did not choose the MSP's AI, and their staff did not choose it at all. Trust compounds or collapses per person: one hygienist wrongly locked out tells the whole practice, and practice owners talk to each other. The commitments in `05-governance.md` section 9 (`EU-1` to `EU-8`: plain notices, a fast way back, never locked out by a bot alone, verified before changed, no silent decisions, a human when asked, mistakes owned) are the client-side half of every chain here; most are planned. Honest reporting (`C-21` reconciliation, `C-45` honest labels) matters as much: a report or an insurance answer that overclaims (`W-CMP-08`) can cost a client its insurance payout after an attack, which is a livelihood-ending FP.

**Dependency risks.**

| Dependency | What goes wrong | Who feels it first | Bound |
|---|---|---|---|
| Model or gateway down | suggestions stop | technicians (slower), then end users waiting | every workflow must fall back to the manual path; `C-17` timeouts and failure containment (built); write levers never depend on a model being up |
| One AI provider | price, terms or retention change | the MSP's margin; regulated clients if data terms shift | `C-16` provider abstraction (built), `C-28` approval gate and `C-43` vendor register (planned) |
| Microsoft Graph, PSA, RMM APIs | silent change breaks a lever | end users whose fix silently fails | `W-TOOL-11` contract tests, `C-17`, `C-40` (planned) |
| One AI & Automation Engineer | the platform has one owner at a small MSP (the MSP lists about 32 employees publicly) | everyone, slowly | documentation and runbooks (`W-KB-03`), CI (`C-24`), PR review (`CM-1`), and training others to propose and review levers |
| Clients' dependence on the MSP | the better the automation, the less in-house knowledge clients keep | the client, at the moment it changes providers | plain-language documentation the client owns, exportable audit records (`C-27`, `EU-5`), MSP offboarding stays human (`W-PRJ-02`) |
| Technicians' dependence on suggestions | skills fade | the end user on the day the suggestion is wrong | section above: drills, rotation, refusal-when-no-source in RAG (`C-26`) |

**The community.** A dental practice that cannot open is patients who go without care that day; a bookkeeping firm that misses close is twenty small businesses whose books are late; a financial firm hit by BEC is a local family's savings. Reported BEC losses in the US were about $2.77B in 2024 (FBI IC3, via secondary summaries; verify against the IC3 report). The highest-leverage chains below are mostly the quiet protective ones, because their benefit lands on everyone at once and their failure modes are mostly read-only. That is also how trust in AI is earned locally: by being boring, correct and honest, many thousands of times.

## 7. The 10 highest-leverage automations

### 7.1 Method

Leverage = **B x N x S**, each scored 1-5 (maximum 125). Scores are judgment from the chains above, recorded in Appendix A so anyone can challenge one.

| Factor | 1 | 3 | 5 |
|---|---|---|---|
| **B** benefit to one person when the automation matters for them | internal convenience | saves minutes or improves quality of something they rely on | restores their ability to work, or prevents loss of their data, money or identity |
| **N** people it matters for per month at reference scale | under 50 | 500-2,000 | over 5,000, or every person in many tenants |
| **S** safety: how well its worst failure is bounded | R3 write with an irreversible FP | R2 write, reversible, approved | read-only or report; worst case is a missed or wrong finding a human reviews |

Ties are broken by B, then N, then S, then by judgment (stated below). Platform, governance and training items (`W-TOOL-*`, `W-GOV-*`, `W-TRN-*`, and `W-CMP-05` audit verification) are **enablers**: they are prerequisites for every chain rather than benefits on their own, so they are scored in Appendix A but not ranked.

### 7.2 Ranking

| Rank | Id | Automation | B | N | S | Score | Risk | Repo | Why it ranks here |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `W-BDR-01` | Daily backup job review | 5 | 4 | 5 | 100 | R0 | not in blueprint | A silent backup failure is invisible until the worst day of a client's life; catching it is read-only, daily, and protects every person's data at once. Highest benefit with the safest failure mode. Not in the blueprint today (no backup adapter; proposed Phase 4). |
| 2 | `W-PAT-05` | Emergency patch for actively exploited vulnerabilities | 5 | 4 | 5 | 100 | R2 | not in blueprint | Exploited flaws hit many small businesses in the same week; hours, not days, decide who is breached. Read-only matching to CISA KEV; humans decide the window. Tied with W-BDR-01; ranked second because a missed backup is unrecoverable while a missed patch can still be caught by other layers. |
| 3 | `W-SD-02` | Ticket triage: category, priority, queue | 4 | 5 | 4 | 80 | R1 | exists | Every ticket passes through it, so it is the floor for time back to work for every person; built and evaluated on fixtures, rules pick the lever, approval still required. |
| 4 | `W-M365-11` | Tenant security baseline and drift check | 4 | 4 | 5 | 80 | R0 | exists | The same gaps (MFA, legacy auth, stale admins) repeat across small tenants; one built check finds them everywhere, with numbers that cannot be invented (`C-21`). |
| 5 | `W-SD-08` | Outage and widespread-issue detection | 4 | 4 | 4 | 64 | R1 | planned | One detection spares dozens of people a wasted morning and gives clients honest status during outages that hit many businesses at once. Ordered ahead of KB-04 and SEC-01 (exact ties) because it reaches end users directly. |
| 6 | `W-KB-04` | Cited question answering for technicians (RAG) | 4 | 4 | 4 | 64 | R0 | partial | 2,000-6,000 questions a month answered from the client's own sources makes new technicians effective fast, which shortens every user's wait; refusal-when-no-source and per-tenant retrieval bound it. |
| 7 | `W-SEC-01` | Security alert intake and grouping | 4 | 4 | 4 | 64 | R0 | planned | Grouping is what lets a small security team see the one real attack among thousands of alerts across all tenants; the agent never closes or suppresses alerts on its own. |
| 8 | `W-IDM-13` | Self-service password reset and MFA method coverage | 4 | 3 | 5 | 60 | R0 | partial | Self-service recovery is the cheapest time back to work there is and removes the riskiest manual reset path; pure reporting. First among four exact ties because it reduces W-IDM-01 volume and the social-engineering surface together. |
| 9 | `W-KB-06` | Authorized contacts and escalation lists per client | 4 | 3 | 5 | 60 | R0 | planned | Current authorized-contact lists are the root of trust for every access change (onboarding, resets, offboarding); a read lever a human consults. Second of the four ties because it bounds the FP of several R3 chains. |
| 10 | `W-M365-03` | Mail delivery troubleshooting (message trace) | 4 | 3 | 5 | 60 | R0 | not in blueprint | Answering 'where is my email' in a minute is a direct, frequent time-back-to-work gain with a read-only failure mode. Third of the four ties; `W-BDR-08` (immutability review) is the fourth and ranks 11th. |

Next five (ranks 11-15, not in `leverage_rank`): `W-BDR-08` Backup retention and immutability review (60), `W-SD-01` Ticket intake and logging (60), `W-PAT-01` Monthly patch review and ring approval (60), `W-M365-10` DMARC, SPF and DKIM monitoring (60), `W-EP-01` Device inventory reconciliation (RMM vs Intune vs PSA) (60).

What the ranking says: seven of the ten are read-only (R0) and none is R3. The highest leverage is in *seeing* problems early across all tenants, because benefit times reach is large and the failure mode is a human reviewing a finding. Two of the ten exist in the repo today, mocked on fixtures (`W-SD-02` triage, `W-M365-11` baseline) and two in part (`W-KB-04` keyword `kb.search`, `W-IDM-13` MFA registration check inside the baseline). The top two, backup review (`W-BDR-01`) and exploited-flaw response (`W-PAT-05`), plus message trace (`W-M365-03`), are not in the blueprint at all (`01-work-inventory.md` proposes Phase 3-4 for them). That is the strongest build-order signal in this map.

### 7.3 Highest stakes per person (not the same list)

These have the largest benefit to one person (B = 5) but lower reach or safety, so they are not in the top 10. They are where a single chain most directly protects a livelihood, and where the planned controls matter most before anything goes live:

| Id | Automation | Score | Why it is not higher | Control to build first |
|---|---|---|---|---|
| `W-IDM-05` | Risky sign-in and risky user review | 50 | tens of events a month, not thousands | `W-SEC-04` containment path with `C-30` |
| `W-M365-05` | Suspicious inbox rule and external forwarding audit | 50 | few findings a month, but each can be a stolen payment | weekly scan across all tenants; `C-40` |
| `W-ONB-02` | Create the user account (cloud or hybrid) | 20 | R3 identity creation | `C-29` risk class enforcement |
| `W-ONB-08` | Offboarding: block sign-in and revoke sessions | 20 | R3: an FP locks out the wrong person with patients waiting | `C-30`, `C-33`, `EU-2` fast way back |
| `W-IDM-01` | Password reset | 20 | R3: an FP hands an attacker a mailbox | `C-30` requester verification; `W-IDM-04` stays human |
| `W-IDM-02` | MFA reset (lost or new phone) | 20 | R3: same social-engineering exposure | `C-30`, `C-33` undo, `EU-1` notice |
| `W-SEC-04` | Business email compromise containment | 10 | rare (2-10 a month) and R3 | `C-30`, `C-33`, `C-34` incident runbook |

### 7.4 What would change the ranking

- Real volumes from the MSP's PSA (IQ-01) change N for every item; the identity chains could move up if lockouts are more frequent than estimated.
- Requester verification (`C-30`), undo levers (`C-33`) and the kill switch (`C-31`) would raise S for the R3 identity chains from 2 toward 3.
- If backup and DR are out of scope for the AI role (inventory Q-09), ranks 1 and 11 move to whoever owns backup, and the map should say who.

## 8. Cross-document notes

Found while tracing. The synthesis pass (2026-10-20, `docs/map/README.md`) resolved the second note in the other documents; the first stays open for the owner.

- **Risk-class definitions differ between `01` and `05`.** `01-work-inventory.md` puts MFA reset, password reset and disable in **R3** (identity changes); `05-governance.md` section 6.1 lists `user.reset-mfa` and `user.disable` as **R2** and reserves R3 for irreversible or tenant-wide changes. This document uses the inventory's class for each item and the governance doc's control ids. One definition should win before `C-29` (risk class enforced by the runner) is built (IQ-06; the same question is ROADMAP `RQ-01`). Until then the roadmap and the registry (`B-01`) use the governance classes. **Resolved 2026-10-21:** identity changes are R3 in both maps (D-024; `06-decisions.md` D6-07).
- **`05-governance.md` section 9 trace names Ana Lopez for ticket T-3101**; in `fixtures/tickets/contoso-dental.json` the requester and affected user of T-3101 is Priya Nair, and Ana Lopez is the office manager. This document follows the fixture. **Resolved:** `05-governance.md` section 9 and the W1 story in `docs/ROADMAP.md` and `map/roadmap.json` now name Priya Nair; the technician on the ticket is identity `tech-ana` ("Ana (technician, synthetic)" in `config/identities.json`), who is not persona `P-02` Ana Lopez.
- **Personas.** No separate personas file was created, per the task; personas live in section 2 here. If later documents need them, they should reference the `P-nn` ids.

## 9. Open questions only the owner or the MSP can answer

| Id | Question | Who |
|---|---|---|
| `IQ-01` | What are the MSP's real monthly volumes and current time-to-resolution for lockouts, new hires, mail issues and scripted fixes? Replaces every N score and every assumed minute in section 6.1. **Decided: see 06-decisions.md D6-03.** | The MSP |
| `IQ-02` | Which individual metric does the MSP already track, if any (time to resolution, first-contact resolution, CSAT)? Is 'minutes until the person can work again' measurable in their PSA (needs a 'user confirmed working' timestamp)? **Decided: see 06-decisions.md D6-21.** | The MSP |
| `IQ-03` | What is leadership's stated position on how technician hours saved by automation are used? This map assumes 'moved up, not out'; it should be written down before the program starts, because technicians' willingness to correct the system depends on it. **Decided: see 06-decisions.md D6-22.** | The MSP leadership |
| `IQ-04` | Which restore-access target will the MSP commit to for a person locked out by an automation (`EU-2` proposes one business hour during support hours)? **Decided: see 06-decisions.md D6-20.** | The MSP (also 05 GQ-09) |
| `IQ-05` | Are backup review and exploited-vulnerability response (ranks 1 and 2) in scope for the AI & Automation role, and which backup and vulnerability tools would the read levers use? **Decided: see 06-decisions.md D6-24, D6-01.** | The MSP (also 01 Q-01, Q-09) |
| `IQ-06` | Which risk-class definition wins for identity changes: R3 as in `01` or R2 as in `05`? **Decided: see 06-decisions.md D6-07.** | The owner |
| `IQ-07` | Do the MSP's clients include practice types beyond dental and financial (legal, bookkeeping, nonprofit) in meaningful numbers? Changes which personas should anchor the chains. **Decided: see 06-decisions.md D6-13.** | The MSP |
| `IQ-08` | After hours: may a single on-call engineer approve containment (`W-SEC-04`, `W-SEC-05`) alone, or does four-eyes hold at 2 am? The FN harm of waiting and the FP harm of acting alone are both real. **Decided: see 06-decisions.md D6-08.** | The MSP (also 01 Q-04, Q-10) |
| `IQ-09` | The owner: are the B, N, S scores in Appendix A acceptable as the planning basis, and is excluding the enabler items from the ranking the right call? **Decided: see 06-decisions.md D6-23.** | The owner |

## 10. Sources

Public sources behind the macro statements. 'Checked' means a web search in this session returned the page or a consistent summary of it on 2026-10-20; the page itself was not read in full. Everything else is unverified.

- FBI IC3, 2024 Internet Crime Report (BEC losses about $2.77B; about 66% success freezing BEC transfers by the Recovery Asset Team): https://www.ic3.gov/AnnualReport/Reports/2024_IC3Report.pdf (figures checked via secondary summaries, for example https://www.nacha.org/news/fbis-ic3-finds-almost-85-billion-lost-business-email-compromise-last-three-years ; the PDF itself not opened; verify before quoting)
- CISA and partners, joint advisory AA22-131A, Protecting Against Cyber Threats to Managed Service Providers and their Customers (May 2022): https://www.cisa.gov/news-events/cybersecurity-advisories/aa22-131a (checked: archived alert page https://www.cisa.gov/ncas/alerts/aa22-131a)
- FTC Safeguards Rule notification amendment (notify the FTC within 30 days of discovering a notification event involving 500 or more consumers; effective May 2024): https://www.ftc.gov/business-guidance/resources/ftc-safeguards-rule-what-your-business-needs-know (checked via law-firm summaries; rule text at https://www.ecfr.gov/current/title-16/chapter-I/subchapter-C/part-314)
- HHS, HIPAA Breach Notification Rule: https://www.hhs.gov/hipaa/for-professionals/breach-notification/index.html (unverified this session)
- HHS, HIPAA Security Rule risk analysis guidance: https://www.hhs.gov/hipaa/for-professionals/security/guidance/guidance-risk-analysis/index.html (unverified this session)
- CISA, Known Exploited Vulnerabilities catalog: https://www.cisa.gov/known-exploited-vulnerabilities-catalog (unverified this session)
- Microsoft Learn, Conditional Access report-only mode: https://learn.microsoft.com/en-us/entra/identity/conditional-access/concept-conditional-access-report-only (unverified this session)
- NIST AI Risk Management Framework: https://www.nist.gov/itl/ai-risk-management-framework (unverified this session)
- General knowledge of MSP practice for the reference MSP (a small provider with regulated healthcare and financial clients; SOC 2 Type II assumed): planning assumptions, not re-verified.
- Repo sources: `map/inventory.json`, `docs/map/01-work-inventory.md`, `map/controls.json`, `docs/map/05-governance.md`, `fixtures/tenant/*.json`, `fixtures/tickets/*.json`, `config/identities.json`.

## Appendix A. Leverage scores for every chain

| Id | Item | Risk | B | N | S | Score | Rank | Enabler |
|---|---|---|---|---|---|---|---|---|
| `W-SD-01` | Ticket intake and logging | R1 | 3 | 5 | 4 | 60 |  |  |
| `W-SD-02` | Ticket triage: category, priority, queue | R1 | 4 | 5 | 4 | 80 | 3 |  |
| `W-SD-03` | Duplicate and related ticket detection | R1 | 2 | 3 | 4 | 24 |  |  |
| `W-SD-04` | Ticket summary for handoff and escalation | R0 | 3 | 3 | 5 | 45 |  |  |
| `W-SD-05` | Draft reply to the end user from the knowledge base | R1 | 3 | 4 | 4 | 48 |  |  |
| `W-SD-06` | SLA breach watch | R0 | 3 | 3 | 5 | 45 |  |  |
| `W-SD-07` | Escalation tier 1 to 2 to 3 with context package | R0 | 3 | 3 | 5 | 45 |  |  |
| `W-SD-08` | Outage and widespread-issue detection | R1 | 4 | 4 | 4 | 64 | 5 |  |
| `W-SD-09` | Closure confirmation and follow-up | R1 | 2 | 4 | 4 | 32 |  |  |
| `W-SD-10` | Stale ticket and backlog grooming | R0 | 2 | 3 | 5 | 30 |  |  |
| `W-SD-11` | Common tier 1 fixes via scripts (print spooler, mapped drives, Outlook profile, cache clear) | R2 | 4 | 3 | 3 | 36 |  |  |
| `W-SD-12` | After-hours and on-call triage | R1 | 4 | 2 | 3 | 24 |  |  |
| `W-SD-13` | Recurring-issue analysis (problem management) | R0 | 3 | 3 | 5 | 45 |  |  |
| `W-SD-14` | Customer satisfaction feedback review | R0 | 2 | 3 | 5 | 30 |  |  |
| `W-ONB-01` | New-hire request intake and requester authorization check | R0 | 4 | 2 | 4 | 32 |  |  |
| `W-ONB-02` | Create the user account (cloud or hybrid) | R3 | 5 | 2 | 2 | 20 |  |  |
| `W-ONB-03` | Assign licenses | R2 | 4 | 2 | 3 | 24 |  |  |
| `W-ONB-04` | Role-based access: groups, shared mailboxes, Teams and SharePoint | R2 | 4 | 2 | 3 | 24 |  |  |
| `W-ONB-05` | MFA enrollment and Temporary Access Pass | R3 | 4 | 2 | 2 | 16 |  |  |
| `W-ONB-06` | Device provisioning (Autopilot, Intune enrollment, app set) | R2 | 4 | 2 | 3 | 24 |  |  |
| `W-ONB-07` | Day-one welcome and handoff to the manager | R1 | 3 | 2 | 4 | 24 |  |  |
| `W-ONB-08` | Offboarding: block sign-in and revoke sessions | R3 | 5 | 2 | 2 | 20 |  |  |
| `W-ONB-09` | Offboarding: mailbox conversion, forwarding and auto-reply | R2 | 3 | 2 | 3 | 18 |  |  |
| `W-ONB-10` | Offboarding: OneDrive and file ownership transfer | R2 | 3 | 2 | 3 | 18 |  |  |
| `W-ONB-11` | Offboarding: license removal after retention window | R2 | 2 | 2 | 3 | 12 |  |  |
| `W-ONB-12` | Offboarding: device retire or wipe and hardware recovery | R3 | 3 | 2 | 2 | 12 |  |  |
| `W-ONB-13` | Offboarding: line-of-business and third-party apps | R3 | 3 | 2 | 5 | 30 |  |  |
| `W-ONB-14` | Offboarding completion proof | R0 | 3 | 2 | 5 | 30 |  |  |
| `W-ONB-16` | Role change or transfer (mover) | R2 | 3 | 2 | 3 | 18 |  |  |
| `W-ONB-17` | Guest and contractor account lifecycle | R2 | 3 | 2 | 3 | 18 |  |  |
| `W-IDM-01` | Password reset | R3 | 5 | 2 | 2 | 20 |  |  |
| `W-IDM-02` | MFA reset (lost or new phone) | R3 | 5 | 2 | 2 | 20 |  |  |
| `W-IDM-03` | Sign-in failure and lockout investigation | R0 | 4 | 2 | 5 | 40 |  |  |
| `W-IDM-05` | Risky sign-in and risky user review | R0 | 5 | 2 | 5 | 50 |  |  |
| `W-IDM-06` | Conditional Access policy change | R3 | 3 | 3 | 4 | 36 |  |  |
| `W-IDM-08` | Break-glass account monitoring | R0 | 3 | 3 | 5 | 45 |  |  |
| `W-IDM-09` | Quarterly admin access review across tenants | R0 | 3 | 3 | 5 | 45 |  |  |
| `W-IDM-10` | Partner delegated access (GDAP) relationship management | R3 | 2 | 4 | 4 | 32 |  |  |
| `W-IDM-11` | Stale account cleanup | R3 | 3 | 3 | 2 | 18 |  |  |
| `W-IDM-12` | App registration and service principal secret expiry | R0 | 3 | 2 | 5 | 30 |  |  |
| `W-IDM-13` | Self-service password reset and MFA method coverage | R0 | 4 | 3 | 5 | 60 | 8 |  |
| `W-M365-01` | Shared mailbox and distribution list changes | R2 | 3 | 3 | 3 | 27 |  |  |
| `W-M365-02` | Mailbox permission grants (Full Access, Send As) | R2 | 3 | 2 | 3 | 18 |  |  |
| `W-M365-03` | Mail delivery troubleshooting (message trace) | R0 | 4 | 3 | 5 | 60 | 10 |  |
| `W-M365-04` | Quarantine release requests | R2 | 4 | 3 | 3 | 36 |  |  |
| `W-M365-05` | Suspicious inbox rule and external forwarding audit | R0 | 5 | 2 | 5 | 50 |  |  |
| `W-M365-06` | SharePoint and Teams site creation and permissions | R2 | 3 | 2 | 3 | 18 |  |  |
| `W-M365-07` | Oversharing and external sharing review (Copilot readiness) | R0 | 3 | 3 | 5 | 45 |  |  |
| `W-M365-08` | Sensitivity labels and DLP policy changes | R3 | 3 | 3 | 4 | 36 |  |  |
| `W-M365-09` | Mailbox size and archive management | R2 | 3 | 2 | 3 | 18 |  |  |
| `W-M365-10` | DMARC, SPF and DKIM monitoring | R0 | 3 | 4 | 5 | 60 |  |  |
| `W-M365-11` | Tenant security baseline and drift check | R0 | 4 | 4 | 5 | 80 | 4 |  |
| `W-EP-01` | Device inventory reconciliation (RMM vs Intune vs PSA) | R0 | 3 | 4 | 5 | 60 |  |  |
| `W-EP-02` | RMM agent and Defender sensor health | R0 | 3 | 4 | 5 | 60 |  |  |
| `W-EP-03` | Disk space and performance alert remediation | R2 | 4 | 3 | 3 | 36 |  |  |
| `W-EP-04` | Software deployment requests | R2 | 3 | 3 | 3 | 27 |  |  |
| `W-EP-05` | Intune compliance follow-up | R1 | 3 | 3 | 4 | 36 |  |  |
| `W-EP-06` | Disk encryption status and recovery key retrieval | R3 | 4 | 2 | 3 | 24 |  |  |
| `W-EP-07` | Remote reboot and service restart | R2 | 3 | 3 | 3 | 27 |  |  |
| `W-EP-08` | Lost or stolen device: lock, retire or wipe | R3 | 4 | 1 | 2 | 8 |  |  |
| `W-EP-09` | macOS and Linux endpoint scripts | R2 | 2 | 2 | 3 | 12 |  |  |
| `W-EP-10` | Hardware lifecycle and warranty forecast | R0 | 2 | 3 | 5 | 30 |  |  |
| `W-PAT-01` | Monthly patch review and ring approval | R2 | 3 | 5 | 4 | 60 |  |  |
| `W-PAT-02` | Patch compliance reporting per client | R0 | 2 | 4 | 5 | 40 |  |  |
| `W-PAT-03` | Failed patch remediation | R2 | 3 | 3 | 3 | 27 |  |  |
| `W-PAT-04` | Third-party application patching | R2 | 3 | 4 | 3 | 36 |  |  |
| `W-PAT-05` | Emergency patch for actively exploited vulnerabilities | R2 | 5 | 4 | 5 | 100 | 2 |  |
| `W-PAT-06` | Server patch windows and client notice | R2 | 3 | 3 | 3 | 27 |  |  |
| `W-PAT-07` | Network device firmware (firewalls, switches, access points) | R3 | 2 | 3 | 4 | 24 |  |  |
| `W-BDR-01` | Daily backup job review | R0 | 5 | 4 | 5 | 100 | 1 |  |
| `W-BDR-02` | Failed backup remediation | R2 | 4 | 3 | 3 | 36 |  |  |
| `W-BDR-03` | Restore requests (file, mailbox, VM) | R2 | 4 | 2 | 3 | 24 |  |  |
| `W-BDR-04` | Scheduled restore tests | R1 | 3 | 3 | 4 | 36 |  |  |
| `W-BDR-05` | Microsoft 365 backup coverage check | R0 | 3 | 4 | 5 | 60 |  |  |
| `W-BDR-06` | Disaster recovery plan upkeep and tabletop exercise | R0 | 3 | 3 | 5 | 45 |  |  |
| `W-BDR-08` | Backup retention and immutability review | R0 | 4 | 3 | 5 | 60 |  |  |
| `W-SEC-01` | Security alert intake and grouping | R0 | 4 | 4 | 4 | 64 | 7 |  |
| `W-SEC-02` | Alert enrichment | R0 | 3 | 4 | 5 | 60 |  |  |
| `W-SEC-03` | User-reported phishing triage | R2 | 4 | 4 | 3 | 48 |  |  |
| `W-SEC-04` | Business email compromise containment | R3 | 5 | 1 | 2 | 10 |  |  |
| `W-SEC-05` | Endpoint isolation | R3 | 4 | 1 | 2 | 8 |  |  |
| `W-SEC-06` | Vulnerability scan review and prioritization | R0 | 3 | 4 | 5 | 60 |  |  |
| `W-SEC-08` | Threat advisory relevance check | R0 | 3 | 4 | 5 | 60 |  |  |
| `W-SEC-10` | Security awareness training and phishing simulation results | R0 | 2 | 3 | 4 | 24 |  |  |
| `W-CMP-01` | SOC 2 evidence collection for the MSP's own audit | R0 | 2 | 2 | 4 | 16 |  |  |
| `W-CMP-02` | Client HIPAA security risk analysis support | R0 | 3 | 2 | 4 | 24 |  |  |
| `W-CMP-03` | Client FTC Safeguards Rule evidence (financial clients) | R0 | 3 | 2 | 4 | 24 |  |  |
| `W-CMP-04` | Change records and change advisory review | R1 | 2 | 3 | 4 | 24 |  |  |
| `W-CMP-05` | Audit log integrity verification | R0 | 3 | 5 | 5 | 75 |  | yes |
| `W-CMP-06` | Business associate agreements and vendor due diligence tracking | R0 | 2 | 3 | 5 | 30 |  |  |
| `W-CMP-08` | Cyber insurance questionnaires | R0 | 4 | 2 | 4 | 32 |  |  |
| `W-CMP-09` | Client security questionnaires about the MSP itself | R0 | 2 | 2 | 4 | 16 |  |  |
| `W-VND-01` | License reconciliation | R0 | 2 | 4 | 5 | 40 |  |  |
| `W-VND-03` | Renewal alerts (subscriptions, warranties, domains) | R0 | 3 | 4 | 5 | 60 |  |  |
| `W-VND-04` | Vendor and ISP escalation | R1 | 3 | 3 | 4 | 36 |  |  |
| `W-VND-05` | TLS certificate expiry monitoring | R0 | 3 | 4 | 5 | 60 |  |  |
| `W-RPT-01` | Monthly client health report | R0 | 2 | 3 | 5 | 30 |  |  |
| `W-RPT-02` | Quarterly business review draft | R0 | 2 | 3 | 5 | 30 |  |  |
| `W-RPT-03` | Weekly 'what we did for you' digest | R1 | 2 | 3 | 4 | 24 |  |  |
| `W-RPT-04` | Technology roadmap and budget recommendations | R0 | 2 | 3 | 5 | 30 |  |  |
| `W-RPT-05` | Client AI-use policy starter | R0 | 3 | 3 | 5 | 45 |  |  |
| `W-RPT-06` | Internal operations metrics (resolution time, first-contact resolution, SLA, backlog) | R0 | 2 | 3 | 4 | 24 |  |  |
| `W-KB-01` | KB article drafting from resolved tickets | R1 | 2 | 3 | 4 | 24 |  |  |
| `W-KB-02` | Client documentation upkeep (network, contacts, configurations) | R1 | 3 | 3 | 4 | 36 |  |  |
| `W-KB-03` | Runbook and SOP authoring | R0 | 2 | 2 | 5 | 20 |  |  |
| `W-KB-04` | Cited question answering for technicians (RAG) | R0 | 4 | 4 | 4 | 64 | 6 |  |
| `W-KB-05` | Stale and conflicting article detection | R0 | 2 | 3 | 5 | 30 |  |  |
| `W-KB-06` | Authorized contacts and escalation lists per client | R0 | 4 | 3 | 5 | 60 | 9 |  |
| `W-BIL-01` | Time entry and ticket note quality | R1 | 2 | 3 | 4 | 24 |  |  |
| `W-BIL-02` | Per-seat and per-device count true-up | R0 | 2 | 3 | 5 | 30 |  |  |
| `W-BIL-03` | Managed versus project or out-of-scope classification | R1 | 2 | 3 | 4 | 24 |  |  |
| `W-PRJ-01` | New client onboarding to the MSP (discovery and baseline) | R0 | 3 | 3 | 5 | 45 |  |  |
| `W-PRJ-03` | Microsoft 365 migrations (tenant to tenant, mailbox moves) | R3 | 4 | 2 | 2 | 16 |  |  |
| `W-PRJ-04` | Copilot and AI adoption readiness for clients | R0 | 3 | 3 | 5 | 45 |  |  |
| `W-PRJ-05` | Azure infrastructure projects | R3 | 2 | 2 | 2 | 8 |  |  |
| `W-PRJ-06` | Project scoping and estimates | R0 | 2 | 2 | 5 | 20 |  |  |
| `W-TOOL-01` | Lever authoring (new PowerShell or Python lever) | R1 | 2 | 5 | 4 | 40 |  | yes |
| `W-TOOL-02` | Model gateway and routing configuration | R1 | 2 | 5 | 4 | 40 |  | yes |
| `W-TOOL-03` | Prompt library and standards | R0 | 2 | 4 | 5 | 40 |  | yes |
| `W-TOOL-04` | Eval golden sets and accuracy reports | R0 | 2 | 5 | 5 | 50 |  | yes |
| `W-TOOL-05` | Prompt-injection corpus and guard maintenance | R0 | 3 | 5 | 5 | 75 |  | yes |
| `W-TOOL-06` | Approval queue operation | R1 | 4 | 4 | 4 | 64 |  | yes |
| `W-TOOL-07` | CI/CD pipelines and release process | R1 | 2 | 5 | 5 | 50 |  | yes |
| `W-TOOL-09` | Production monitoring of AI and automation | R0 | 3 | 5 | 5 | 75 |  | yes |
| `W-TOOL-10` | MCP server and Teams technician assistant | R1 | 3 | 4 | 3 | 36 |  | yes |
| `W-TOOL-11` | PSA, RMM and Graph integration maintenance | R1 | 2 | 5 | 4 | 40 |  | yes |
| `W-TOOL-12` | Review of existing automation scripts | R0 | 3 | 5 | 5 | 75 |  | yes |
| `W-TOOL-13` | Use-case intake and ROI scoring | R0 | 2 | 3 | 5 | 30 |  | yes |
| `W-TOOL-14` | Emerging technology evaluation | R0 | 1 | 3 | 5 | 15 |  | yes |
| `W-GOV-01` | AI acceptable-use policy and data-in-prompt rules | R0 | 3 | 4 | 5 | 60 |  | yes |
| `W-GOV-03` | Agent identity and lever permission review | R0 | 2 | 5 | 5 | 50 |  | yes |
| `W-TRN-01` | Technician training: reading suggestions and approvals | R0 | 3 | 3 | 5 | 45 |  | yes |
| `W-TRN-02` | Account manager training: explaining AI to clients | R0 | 2 | 3 | 5 | 30 |  | yes |
| `W-TRN-03` | Correction feedback loop coaching | R0 | 2 | 3 | 5 | 30 |  | yes |
