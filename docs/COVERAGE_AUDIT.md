# Coverage audit

Status: **generated** by `tools/coverage_audit.py` (B-98). Do not edit by hand: rerun `uv run --frozen python tools/coverage_audit.py --write`; a test fails when this file is out of date.

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only.

## What this is
The map (`map/inventory.json`, `map/controls.json`, `map/roadmap.json`) says what is planned, partial or built. This report recomputes each status from the files that exist in this checkout and lists every place the two disagree. It is fixture-based and static: it reads files and never re-runs a test, so "built" means the evidence files are present, not that the suites passed today (the test suites say that).

## Headline
Roadmap: 96 of 98 items built, 0 partial, 2 not demonstrated, 0 planned (96 change notes say built, mocked or document-only). Inventory: 149 of 152 built, 1 partial, 0 planned, 2 not demonstrated, 0 not planned by design. Controls: 40 of 45 built, 2 partial, 0 planned, 3 not demonstrated. Map-versus-code disagreements: 5 (3 error, 0 stale, 0 gap, 2 info).

| Level | Total | Built | Partial | Not demonstrated | Planned | Not planned (by design) |
|---|---|---|---|---|---|---|
| Roadmap items | 98 | 96 | 0 | 2 | 0 | 0 |
| Inventory rows | 152 | 149 | 1 | 2 | 0 | 0 |
| Controls | 45 | 40 | 2 | 3 | 0 | 0 |

Levers: 60, of which 0 have no test naming them. Workflow folders: 40, of which 0 have no spec.

## How a status is decided
- **Roadmap item**: built when `docs/changes/B-nn.md` and `specs/B-nn.md` exist, every other path it owns exists, and a test file is tied to it (owned, named `bNN`, or naming `B-nn` in its first 400 characters). Partial when a note, spec or owned path is missing. Planned when none exist. Not demonstrated when the files exist but no test is tied to them or the note says nothing was compiled or run. The note's own word (built, mocked, document-only) is shown as its kind.
- **Inventory row**: derived from the roadmap items that list it: built when all are built, partial when some are built or partial, planned when none are. This is an upper bound: an item may cover only part of a row.
- **Control**: from `implemented_in` and `evidence`. Built when the cited paths exist and a cited test file exists with every named test function in it. Partial when something cited is missing. Not demonstrated when paths exist but no test is cited. Planned when the map says planned and nothing proves otherwise.
- **Lever**: built when a test file names the lever. **Workflow folder**: built when a roadmap item owns it, that item has a spec, and a test imports it.

## Disagreements and gaps
Severity: **error** = the map claims more than the files show; **stale** = the map claims less than the files show; **gap** = a file the process requires is missing; **info** = worth knowing.

| Kind | Severity | Count | Meaning |
|---|---|---|---|
| COV-COUNT-MISMATCH | error | 0 | docs/COVERAGE.md states counts that differ from its own table |
| COV-MISSING-PATH | error | 0 | a docs/COVERAGE.md row marked built/mocked cites a path that is not in the repo |
| CTL-MISSING-PATH | error | 0 | control cites an implementation path that is not in the repo |
| CTL-MISSING-TEST-FILE | error | 0 | control cites a test file that is not in the repo |
| CTL-MISSING-TEST-NAME | error | 3 | control cites a test function that is not in its file |
| INV-MISSING-PATH | error | 0 | inventory row cites a path (as existing) that is not in the repo |
| INV-UNSUPPORTED | error | 0 | inventory row says exists/partial but no covering roadmap item is built |
| ITEM-NOTE-SAYS-BUILT | error | 0 | the change note says built/mocked/document-only but the files say partial/planned |
| CTL-ITEM-BUILT-CONTROL-PLANNED | stale | 0 | a built roadmap item cites the control but the control is still planned |
| CTL-STALE-PLANNED | stale | 0 | control says planned but its paths and cited tests exist |
| INV-STALE-PLANNED | stale | 0 | inventory row says planned/proposed but roadmap items covering it are built |
| CTL-NO-EVIDENCE | gap | 0 | control claims to be implemented but cites no evidence |
| INV-UNCOVERED | gap | 0 | inventory row is covered by no roadmap item and no not_now entry |
| ITEM-MISSING-OWNED | gap | 0 | a path the item owns does not exist |
| ITEM-NO-NOTE | gap | 0 | roadmap item has no docs/changes/B-nn.md |
| ITEM-NO-SPEC | gap | 0 | roadmap item has no specs/B-nn.md |
| ITEM-NO-TEST | gap | 0 | no test file is tied to the item (owned, named bNN, or named in its first lines) |
| LEVER-NO-TEST | gap | 0 | no test file mentions the lever by name |
| NOTE-NO-ITEM | gap | 0 | a change note exists for an id that is not in the roadmap |
| WF-NO-SPEC | gap | 0 | workflow folder has no spec (its owner's specs/B-nn.md is missing, or it has no owner) |
| WF-NO-TEST | gap | 0 | no test imports or names the workflow folder |
| WF-UNOWNED | gap | 0 | workflow folder is owned by no roadmap item |
| CTL-ORPHAN | info | 0 | no roadmap item cites the control |
| INV-BY-DESIGN-BUILT | info | 0 | inventory row is kept out by design but a built roadmap item covers it |
| ITEM-NO-STATUS-LINE | info | 0 | the change note has no Status line |
| ITEM-NOT-DEMONSTRATED | info | 2 | files exist but the note says nothing was compiled, validated or run |
| LEVER-NO-OWNER | info | 0 | the lever's registry fragment is owned by no roadmap item |
| WF-NO-README | info | 0 | workflow folder has no README.md (STD-DC-7) |

### CTL-MISSING-TEST-NAME (error, 3)
control cites a test function that is not in its file.

- C-24: evidence cites `tests/py/tools/test_b07_ci_wiring.py::test_b07_1_every_action_is_pinned_to_a_full_commit_sha`; no such function
- C-24: evidence cites `tests/py/tools/test_b07_ci_wiring.py::test_b07_1_ci_runs_the_roadmap_item_tests_and_the_demo_smoke_test`; no such function
- C-37: evidence cites `tests/py/tools/test_b07_ci_wiring.py::test_b07_1_ci_runs_the_roadmap_item_tests_and_the_demo_smoke_test`; no such function

### ITEM-NOT-DEMONSTRATED (info, 2)
files exist but the note says nothing was compiled, validated or run.

- B-85: the change note says nothing was compiled or run
- B-86: the change note says nothing was compiled or run

## Roadmap items

| Id | Title | Status | Kind | Problems |
|---|---|---|---|---|
| B-01 | Registry fields: risk class, undo, impact trace, verification rule | built | built |  |
| B-02 | Runner gates: pause switch, requester verification, contact-detail ... | built | built |  |
| B-03 | Approval page: verification capture, scoped listing, diff, undo and... | built | built |  |
| B-04 | Affected-person notice drafts | built | built |  |
| B-05 | Triage output shows the impact trace and the verification needed | built | built |  |
| B-06 | Map integrity test and the Python test suite runner | built | built |  |
| B-07 | CI for the new suites (owner) | built | built (owner) |  |
| B-08 | GitHub organization: labels, milestones, issue form, PR template, C... | built | built (owner) |  |
| B-09 | Roadmap-to-issues exporter and change-fragment folder | built | built |  |
| B-10 | Demo v2 and its end-to-end smoke test | built | built |  |
| B-11 | One-ticket trace leave-behind (T-3101, granular to macro) | built | built |  |
| B-12 | Repo paths, gateway and guard drift, config version field | built | built |  |
| B-13 | schemas/ folder, generator and cross-language drift check | built | built |  |
| B-14 | Registry fragments, Python lever modules and the never-automate gate | built | built |  |
| B-15 | PowerShell lever host module | built | built |  |
| B-16 | Python bridge and runner dispatch by runtime | built | built |  |
| B-17 | Audit record v2 and verifier | built | built |  |
| B-18 | Adapter base, per-client bindings and the PSA mock | built | mocked |  |
| B-19 | Graph mock adapter with per-family state | built | mocked |  |
| B-20 | Prompt library and prompt standards | built | built |  |
| B-21 | Phase 2 ticket set: 200+ labelled tickets and a third synthetic client | built | built |  |
| B-22 | Ticket summaries, intake matching and escalation context packages | built | built |  |
| B-23 | Duplicate, related-ticket and outage grouping | built | built |  |
| B-24 | SLA breach watch and backlog grooming report | built | built |  |
| B-25 | Draft replies with KB citations and closure follow-up drafts | built | built |  |
| B-26 | Drift fixes: single proposal definitions and TenantBaseline canonic... | built | built |  |
| B-27 | mypy strict across workflows, evals and ui (code side of DR-06) | built | built |  |
| B-89 | Entra sign-in for approvers (design and mock token validation) | built | built |  |
| B-28 | Runner: idempotency enforcement, per-client lock, audit v2 fields, ... | built | built |  |
| B-29 | IdentityOps: revoke sessions, enable (undo of disable), mover prope... | built | built |  |
| B-30 | Password reset and Temporary Access Pass with out-of-band delivery | built | built |  |
| B-31 | LicenseOps: assign and remove from free stock only | built | built |  |
| B-32 | GroupOps: group membership with privileged-group refusal | built | built |  |
| B-33 | MailboxOps and OneDrive transfer | built | built |  |
| B-34 | Requester authorization check and authorized contacts | built | built |  |
| B-35 | Onboarding change plan | built | built |  |
| B-36 | Offboarding change plan with completion proof | built | built |  |
| B-37 | Fact packs for human-only identity decisions | built | built |  |
| B-38 | Guests, stale accounts and baseline-sourced proposals | built | built |  |
| B-39 | Sign-in failure and lockout investigation | built | built |  |
| B-40 | TenantBaseline: MFA and SSPR coverage, break-glass sign-in watch | built | built |  |
| B-41 | Rollback from recorded before-state | built | built |  |
| B-68 | Backup adapter mock, daily job review and failed-backup triage | built | built |  |
| B-42 | Runner: blast-radius caps and per-client audit chains | built | built |  |
| B-43 | Security alert adapter mock, grouping and after-hours summary | built | mocked |  |
| B-44 | Alert enrichment and risky sign-in review | built | built |  |
| B-45 | Phishing triage, message trace and quarantine release | built | mocked |  |
| B-46 | Business email compromise containment plan and inbox-rule audit | built | mocked |  |
| B-47 | Vulnerability, advisory and emergency-patch relevance | built | mocked |  |
| B-48 | Incident and recovery fact packs and timeline export | built | mocked |  |
| B-49 | Access reviews: tenant admins and agent/technician identities | built | built |  |
| B-50 | Conditional Access and baseline drift over time | built | built |  |
| B-51 | SOC 2 evidence bundle and change records | built | built |  |
| B-52 | HIPAA and FTC Safeguards evidence packs per client, BAA and vendor ... | built | built |  |
| B-53 | Oversharing, Copilot readiness and labels/DLP assessment | built | built |  |
| B-54 | Expiry watch: DMARC/SPF/DKIM, app secrets, TLS certificates, GDAP r... | built | built |  |
| B-55 | Data classes and the pre-prompt redaction gate | built | built |  |
| B-56 | RAG ingestion with per-client namespaces and vault exclusion | built | built |  |
| B-57 | Cited retrieval, refusal and leakage evals | built | built |  |
| B-58 | KB drafts from resolved tickets; stale and conflicting article dete... | built | built |  |
| B-59 | Client documentation upkeep and runbook linting | built | built |  |
| B-60 | Answer drafts: security questionnaires, cyber insurance, project sc... | built | built |  |
| B-61 | RMM and Intune mock adapters and device reconciliation | built | mocked |  |
| B-62 | Device remediation script levers | built | built |  |
| B-63 | Software deployment from an approved catalog and third-party patching | built | mocked |  |
| B-64 | Device compliance, encryption and LAPS coverage reports; provisioni... | built | mocked |  |
| B-65 | Device R3 levers: lock, retire, wipe and isolate with dual approval | built | mocked |  |
| B-66 | macOS and Linux levers through a bash runtime | built | built |  |
| B-67 | Patch review pack, compliance report, failed-patch triage, server w... | built | mocked |  |
| B-69 | Restore requests to an alternate location and scheduled restore tests | built | built |  |
| B-70 | M365 backup coverage, retention and immutability review, DR plan up... | built | built |  |
| B-71 | Monthly client health report with reconciliation | built | built |  |
| B-72 | QBR draft and weekly 'what we did for you' digest | built | built |  |
| B-73 | Technology roadmap recommendations and the client AI-use policy sta... | built | built |  |
| B-74 | Operations metrics, Power BI exports, problem and CSAT analysis | built | built |  |
| B-75 | Licence reconciliation, seat and device true-up, renewals, hardware... | built | built |  |
| B-76 | Billing classification and time-entry note quality | built | built |  |
| B-77 | MSP client onboarding discovery, offboarding checklist, migration p... | built | mocked |  |
| B-78 | Routing evals and escalation thresholds | built | built |  |
| B-79 | Injection corpus for email, documents and tool output; guard mainte... | built | built |  |
| B-80 | Gateway budgets, circuit breaker and model-call audit | built | built |  |
| B-81 | Scheduler with per-client fan-out and job keys | built | built |  |
| B-82 | SQLite queue and append-only audit store | built | built |  |
| B-83 | Operational logs, request ids and monitoring alert rules | built | built |  |
| B-84 | Load, failure and retry tests; eval gates in CI | built | built |  |
| B-85 | Bicep: Key Vault, managed identity, Log Analytics; secrets doc | not demonstrated | source-only |  |
| B-86 | Bicep compute and Azure DevOps pipeline; branching and release doc | not demonstrated | source-only |  |
| B-87 | MCP server over approved levers | built | built |  |
| B-88 | Teams approval card, Outlook draft and SharePoint ingestion mocks; ... | built | mocked |  |
| B-90 | Hosted provider approval gate and Azure OpenAI adapter (mocked) | built | built |  |
| B-91 | Adapter contract tests and real-adapter stubs | built | built |  |
| B-92 | AI policy, acceptable use and DLP mapping | built | document-only |  |
| B-93 | Model and tool approval process | built | built |  |
| B-94 | AI incident response runbook, notification templates review and tab... | built | built |  |
| B-95 | Use-case intake, ROI tracker, SOC 2 control mapping and risk register | built | built |  |
| B-96 | Staff training, client conversation guide, explainer and data-handl... | built | document-only |  |
| B-97 | Tech radar, leadership brief, 30/60/90 plan and automation framewor... | built | built |  |
| B-98 | Packaged demo, final README and coverage audit | built | built |  |

## Controls

| Id | Name | Map says | Evidence says | Problems |
|---|---|---|---|---|
| C-01 | Lever registry, default deny | claimed | built |  |
| C-02 | Parameter schema validation | claimed | built |  |
| C-03 | Role-based authorization; agents may only dry-run writes | claimed | built |  |
| C-04 | Per-client scope at the tool layer | claimed | built |  |
| C-05 | Dry-run by default with a diff | claimed | built |  |
| C-06 | Lead approval bound to lever, client and params | claimed | built |  |
| C-07 | Four-eyes rule (no self-approval) | claimed | built |  |
| C-08 | Hash-chained audit log with head pin and verifier | claimed | built |  |
| C-09 | Audit before apply | claimed | built |  |
| C-10 | Secret redaction before logging | claimed | built |  |
| C-11 | Data minimisation in the audit log | partial | built |  |
| C-12 | Untrusted input wrapping | claimed | built |  |
| C-13 | Prompt-injection tripwire | claimed | built |  |
| C-14 | Model output cannot choose the lever or its parameters | claimed | built |  |
| C-15 | Loopback-only model gateway, hosted providers off | claimed | built |  |
| C-16 | Provider abstraction against lock-in | claimed | built |  |
| C-17 | Timeouts and failure containment | claimed | built |  |
| C-18 | Idempotency on write levers | partial | built |  |
| C-19 | Approval queue and viewer hardening | claimed | built |  |
| C-20 | Read levers cannot write | claimed | built |  |
| C-21 | Output reconciliation (no invented numbers) | claimed | built |  |
| C-22 | Protected paths need owner review | claimed | not demonstrated |  |
| C-23 | Commit-time secret scan | claimed | not demonstrated |  |
| C-24 | CI with least-privilege token and pinned actions | claimed | partial | missing test test_b07_1_every_action_is_pinned_to_a_full_commit_sha; missing test test_b07_1_ci_runs_the_ro... |
| C-25 | Data classification and pre-prompt redaction gate | claimed | built |  |
| C-26 | Per-tenant retrieval isolation | partial | built |  |
| C-27 | Tenant isolation of prompts, context, logs and error text | partial | built |  |
| C-28 | Hosted AI provider approval gate | claimed | built |  |
| C-29 | Risk class and version on every lever, enforced by class | partial | built |  |
| C-30 | Requester identity verification for access-affecting levers | claimed | built |  |
| C-31 | Kill switch per lever and per tenant | claimed | built |  |
| C-32 | Blast-radius and rate limits | partial | built |  |
| C-33 | Rollback from recorded before-state | partial | built |  |
| C-34 | Wrong-automated-action incident runbook | claimed | built |  |
| C-35 | Notification templates and timelines | partial | built |  |
| C-36 | End-user fast path back | partial | built |  |
| C-37 | Lever change management with staged rollout | partial | partial | missing test test_b07_1_ci_runs_the_roadmap_item_tests_and_the_demo_smoke_test |
| C-38 | Agent and technician access review; least-privilege deleg... | partial | built |  |
| C-39 | Write-once audit head pinning and retention | partial | built |  |
| C-40 | Monitoring and alerting on automation behaviour | partial | built |  |
| C-41 | Evaluation gate before promotion | partial | built |  |
| C-42 | Staff training and acceptable use | partial | built |  |
| C-43 | AI vendor and subprocessor register | claimed | built |  |
| C-44 | Authenticated approvers | claimed | built |  |
| C-45 | Synthetic data only and honest labels | partial | not demonstrated |  |

## Inventory

| Id | Name | Map says | Evidence says | Covering items |
|---|---|---|---|---|
| W-SD-01 | Ticket intake and logging | partial | built | B-18, B-21, B-22, B-55 |
| W-SD-02 | Ticket triage: category, priority, queue | exists | built | B-05, B-10 |
| W-SD-03 | Duplicate and related ticket detection | exists | built | B-21, B-23 |
| W-SD-04 | Ticket summary for handoff and escalation | exists | built | B-21, B-22 |
| W-SD-05 | Draft reply to the end user from the knowledge base | partial | built | B-21, B-25 |
| W-SD-06 | SLA breach watch | exists | built | B-21, B-24 |
| W-SD-07 | Escalation tier 1 to 2 to 3 with context package | exists | built | B-05, B-22, B-44 |
| W-SD-08 | Outage and widespread-issue detection | exists | built | B-23 |
| W-SD-09 | Closure confirmation and follow-up | exists | built | B-04, B-25 |
| W-SD-10 | Stale ticket and backlog grooming | exists | built | B-24 |
| W-SD-11 | Common tier 1 fixes via scripts (print spooler, mapp... | exists | built | B-62 |
| W-SD-12 | After-hours and on-call triage | exists | built | B-43 |
| W-SD-13 | Recurring-issue analysis (problem management) | exists | built | B-74 |
| W-SD-14 | Customer satisfaction feedback review | exists | built | B-74 |
| W-ONB-01 | New-hire request intake and requester authorization ... | exists | built | B-34, B-35 |
| W-ONB-02 | Create the user account (cloud or hybrid) | exists | built | B-28, B-35 |
| W-ONB-03 | Assign licenses | exists | built | B-31 |
| W-ONB-04 | Role-based access: groups, shared mailboxes, Teams a... | exists | built | B-32 |
| W-ONB-05 | MFA enrollment and Temporary Access Pass | exists | built | B-30 |
| W-ONB-06 | Device provisioning (Autopilot, Intune enrollment, a... | exists | built | B-64 |
| W-ONB-07 | Day-one welcome and handoff to the manager | exists | built | B-35 |
| W-ONB-08 | Offboarding: block sign-in and revoke sessions | exists | built | B-02, B-04, B-29, B-36 |
| W-ONB-09 | Offboarding: mailbox conversion, forwarding and auto... | exists | built | B-33, B-36 |
| W-ONB-10 | Offboarding: OneDrive and file ownership transfer | exists | built | B-33, B-36 |
| W-ONB-11 | Offboarding: license removal after retention window | exists | built | B-31, B-36 |
| W-ONB-12 | Offboarding: device retire or wipe and hardware reco... | exists | built | B-65 |
| W-ONB-13 | Offboarding: line-of-business and third-party apps | exists | built | B-36 |
| W-ONB-14 | Offboarding completion proof | exists | built | B-36 |
| W-ONB-15 | Urgent or hostile termination | exists | built | B-14, B-37 |
| W-ONB-16 | Role change or transfer (mover) | exists | built | B-29, B-32 |
| W-ONB-17 | Guest and contractor account lifecycle | partial | built | B-38 |
| W-IDM-01 | Password reset | exists | built | B-30 |
| W-IDM-02 | MFA reset (lost or new phone) | exists | built | B-02, B-03, B-04, B-11 |
| W-IDM-03 | Sign-in failure and lockout investigation | exists | built | B-39 |
| W-IDM-04 | Caller identity verification | exists | built | B-01, B-03, B-14, B-34, B-37 |
| W-IDM-05 | Risky sign-in and risky user review | exists | built | B-44 |
| W-IDM-06 | Conditional Access policy change | partial | built | B-14, B-37, B-50 |
| W-IDM-07 | Privileged role grants and PIM activation approval | partial | built | B-14, B-32, B-37 |
| W-IDM-08 | Break-glass account monitoring | partial | built | B-40 |
| W-IDM-09 | Quarterly admin access review across tenants | exists | built | B-49, B-81 |
| W-IDM-10 | Partner delegated access (GDAP) relationship management | exists | built | B-54 |
| W-IDM-11 | Stale account cleanup | partial | built | B-38 |
| W-IDM-12 | App registration and service principal secret expiry | exists | built | B-54 |
| W-IDM-13 | Self-service password reset and MFA method coverage | partial | built | B-40 |
| W-M365-01 | Shared mailbox and distribution list changes | exists | built | B-33 |
| W-M365-02 | Mailbox permission grants (Full Access, Send As) | exists | built | B-33 |
| W-M365-03 | Mail delivery troubleshooting (message trace) | exists | built | B-45 |
| W-M365-04 | Quarantine release requests | exists | built | B-45 |
| W-M365-05 | Suspicious inbox rule and external forwarding audit | exists | built | B-46 |
| W-M365-06 | SharePoint and Teams site creation and permissions | partial | built | B-88 |
| W-M365-07 | Oversharing and external sharing review (Copilot rea... | exists | built | B-53 |
| W-M365-08 | Sensitivity labels and DLP policy changes | exists | built | B-53 |
| W-M365-09 | Mailbox size and archive management | exists | built | B-33 |
| W-M365-10 | DMARC, SPF and DKIM monitoring | exists | built | B-54 |
| W-M365-11 | Tenant security baseline and drift check | exists | built | B-10, B-26, B-50, B-81 |
| W-M365-12 | Retention, litigation hold and eDiscovery requests | exists | built | B-14 |
| W-EP-01 | Device inventory reconciliation (RMM vs Intune vs PSA) | exists | built | B-61 |
| W-EP-02 | RMM agent and Defender sensor health | exists | built | B-43 |
| W-EP-03 | Disk space and performance alert remediation | exists | built | B-62 |
| W-EP-04 | Software deployment requests | exists | built | B-63 |
| W-EP-05 | Intune compliance follow-up | exists | built | B-64 |
| W-EP-06 | Disk encryption status and recovery key retrieval | exists | built | B-64 |
| W-EP-07 | Remote reboot and service restart | exists | built | B-62 |
| W-EP-08 | Lost or stolen device: lock, retire or wipe | exists | built | B-28, B-65 |
| W-EP-09 | macOS and Linux endpoint scripts | exists | built | B-66 |
| W-EP-10 | Hardware lifecycle and warranty forecast | exists | built | B-75 |
| W-EP-11 | Local admin password (LAPS) retrieval and admin-righ... | exists | built | B-64 |
| W-PAT-01 | Monthly patch review and ring approval | exists | built | B-67 |
| W-PAT-02 | Patch compliance reporting per client | exists | built | B-67 |
| W-PAT-03 | Failed patch remediation | exists | built | B-67 |
| W-PAT-04 | Third-party application patching | exists | built | B-63 |
| W-PAT-05 | Emergency patch for actively exploited vulnerabilities | exists | built | B-47 |
| W-PAT-06 | Server patch windows and client notice | exists | built | B-67 |
| W-PAT-07 | Network device firmware (firewalls, switches, access... | exists | built | B-67 |
| W-BDR-01 | Daily backup job review | exists | built | B-68 |
| W-BDR-02 | Failed backup remediation | exists | built | B-68 |
| W-BDR-03 | Restore requests (file, mailbox, VM) | exists | built | B-69 |
| W-BDR-04 | Scheduled restore tests | exists | built | B-69 |
| W-BDR-05 | Microsoft 365 backup coverage check | exists | built | B-70 |
| W-BDR-06 | Disaster recovery plan upkeep and tabletop exercise | exists | built | B-70 |
| W-BDR-07 | Ransomware or disaster recovery decision | exists | built | B-14, B-48 |
| W-BDR-08 | Backup retention and immutability review | exists | built | B-70 |
| W-SEC-01 | Security alert intake and grouping | exists | built | B-43 |
| W-SEC-02 | Alert enrichment | exists | built | B-44 |
| W-SEC-03 | User-reported phishing triage | partial | built | B-45 |
| W-SEC-04 | Business email compromise containment | partial | built | B-02, B-04, B-29, B-46 |
| W-SEC-05 | Endpoint isolation | exists | built | B-65 |
| W-SEC-06 | Vulnerability scan review and prioritization | exists | built | B-47 |
| W-SEC-07 | Security incident declaration and breach notificatio... | exists | built | B-14, B-48 |
| W-SEC-08 | Threat advisory relevance check | exists | built | B-47 |
| W-SEC-09 | Firewall and SASE rule changes | exists | built | B-48 |
| W-SEC-10 | Security awareness training and phishing simulation ... | exists | built | B-71 |
| W-CMP-01 | SOC 2 evidence collection for the MSP's own audit | partial | built | B-17, B-42, B-51 |
| W-CMP-02 | Client HIPAA security risk analysis support | exists | built | B-52 |
| W-CMP-03 | Client FTC Safeguards Rule evidence (financial clients) | exists | built | B-52 |
| W-CMP-04 | Change records and change advisory review | partial | built | B-41, B-51 |
| W-CMP-05 | Audit log integrity verification | exists | built | B-02, B-10, B-17, B-51, B-82 |
| W-CMP-06 | Business associate agreements and vendor due diligen... | exists | built | B-52 |
| W-CMP-07 | Policy attestations and management assertions | exists | built | B-14, B-51 |
| W-CMP-08 | Cyber insurance questionnaires | exists | built | B-60 |
| W-CMP-09 | Client security questionnaires about the MSP itself | exists | built | B-60 |
| W-VND-01 | License reconciliation | exists | built | B-75 |
| W-VND-02 | License purchase or reduction | exists | built | B-14, B-31, B-75 |
| W-VND-03 | Renewal alerts (subscriptions, warranties, domains) | exists | built | B-75 |
| W-VND-04 | Vendor and ISP escalation | exists | built | B-22 |
| W-VND-05 | TLS certificate expiry monitoring | exists | built | B-54 |
| W-VND-06 | Domain and DNS registrar changes | exists | built | B-48 |
| W-RPT-01 | Monthly client health report | exists | built | B-71 |
| W-RPT-02 | Quarterly business review draft | exists | built | B-72 |
| W-RPT-03 | Weekly 'what we did for you' digest | partial | built | B-72, B-88 |
| W-RPT-04 | Technology roadmap and budget recommendations | exists | built | B-73 |
| W-RPT-05 | Client AI-use policy starter | exists | built | B-73 |
| W-RPT-06 | Internal operations metrics (resolution time, first-... | exists | built | B-74 |
| W-KB-01 | KB article drafting from resolved tickets | exists | built | B-58 |
| W-KB-02 | Client documentation upkeep (network, contacts, conf... | exists | built | B-59 |
| W-KB-03 | Runbook and SOP authoring | partial | built | B-59 |
| W-KB-04 | Cited question answering for technicians (RAG) | partial | built | B-56, B-57 |
| W-KB-05 | Stale and conflicting article detection | exists | built | B-58 |
| W-KB-06 | Authorized contacts and escalation lists per client | exists | built | B-34 |
| W-KB-07 | Credential vault entries in the documentation platform | exists | built | B-14, B-56 |
| W-BIL-01 | Time entry and ticket note quality | exists | built | B-76 |
| W-BIL-02 | Per-seat and per-device count true-up | exists | built | B-75 |
| W-BIL-03 | Managed versus project or out-of-scope classification | exists | built | B-76 |
| W-BIL-04 | Contract terms, pricing and billing disputes | exists | built | B-14 |
| W-PRJ-01 | New client onboarding to the MSP (discovery and base... | partial | built | B-77 |
| W-PRJ-02 | Client offboarding from the MSP | exists | built | B-77 |
| W-PRJ-03 | Microsoft 365 migrations (tenant to tenant, mailbox ... | exists | built | B-77 |
| W-PRJ-04 | Copilot and AI adoption readiness for clients | exists | built | B-53 |
| W-PRJ-05 | Azure infrastructure projects | planned | not demonstrated | B-85, B-86 |
| W-PRJ-06 | Project scoping and estimates | exists | built | B-60 |
| W-TOOL-01 | Lever authoring (new PowerShell or Python lever) | exists | built | B-01, B-13, B-14, B-15, B-16, B-28, B-42 |
| W-TOOL-02 | Model gateway and routing configuration | exists | built | B-12, B-78, B-80, B-90 |
| W-TOOL-03 | Prompt library and standards | exists | built | B-20 |
| W-TOOL-04 | Eval golden sets and accuracy reports | exists | built | B-06, B-84 |
| W-TOOL-05 | Prompt-injection corpus and guard maintenance | exists | built | B-79 |
| W-TOOL-06 | Approval queue operation | exists | built | B-03, B-10, B-26, B-89, B-82 |
| W-TOOL-07 | CI/CD pipelines and release process | partial | partial | B-07, B-08, B-27, B-84, B-86, B-98 |
| W-TOOL-08 | Secrets and managed identity management | planned | not demonstrated | B-85 |
| W-TOOL-09 | Production monitoring of AI and automation | exists | built | B-80, B-81, B-83 |
| W-TOOL-10 | MCP server and Teams technician assistant | partial | built | B-87, B-88 |
| W-TOOL-11 | PSA, RMM and Graph integration maintenance | exists | built | B-18, B-19, B-91 |
| W-TOOL-12 | Review of existing automation scripts | exists | built | B-97 |
| W-TOOL-13 | Use-case intake and ROI scoring | exists | built | B-06, B-08, B-09, B-95 |
| W-TOOL-14 | Emerging technology evaluation | exists | built | B-78, B-97 |
| W-GOV-01 | AI acceptable-use policy and data-in-prompt rules | exists | built | B-55, B-92 |
| W-GOV-02 | Model and tool approval | exists | built | B-90, B-93 |
| W-GOV-03 | Agent identity and lever permission review | partial | built | B-01, B-49 |
| W-GOV-04 | AI incident response | exists | built | B-02, B-41, B-94 |
| W-TRN-01 | Technician training: reading suggestions and approvals | exists | built | B-96 |
| W-TRN-02 | Account manager training: explaining AI to clients | exists | built | B-11, B-96 |
| W-TRN-03 | Correction feedback loop coaching | partial | built | B-74 |
| W-TRN-04 | New technician onboarding and performance coaching | exists | built | B-14, B-74 |

## Workflow folders

| Folder | Status | Owner | Spec | Test files |
|---|---|---|---|---|
| workflows/access_review | built | B-49 | yes | 2 |
| workflows/advisories | built | B-47 | yes | 1 |
| workflows/alerts | built | B-43 | yes | 2 |
| workflows/assurance | built | B-93 | yes | 5 |
| workflows/backup_coverage | built | B-70 | yes | 1 |
| workflows/backup_review | built | B-68 | yes | 2 |
| workflows/baseline_proposals | built | B-38 | yes | 1 |
| workflows/bec | built | B-46 | yes | 2 |
| workflows/billing | built | B-76 | yes | 1 |
| workflows/client_lifecycle | built | B-77 | yes | 1 |
| workflows/copilot_readiness | built | B-53 | yes | 1 |
| workflows/device_reconcile | built | B-61 | yes | 3 |
| workflows/device_reports | built | B-64 | yes | 1 |
| workflows/doc_upkeep | built | B-59 | yes | 2 |
| workflows/duplicates | built | B-23 | yes | 3 |
| workflows/enrichment | built | B-44 | yes | 1 |
| workflows/evidence | built | B-51 | yes | 1 |
| workflows/expiry | built | B-54 | yes | 1 |
| workflows/factpack | built | B-37 | yes | 2 |
| workflows/kb_drafts | built | B-58 | yes | 1 |
| workflows/licensing | built | B-75 | yes | 1 |
| workflows/lockout | built | B-39 | yes | 1 |
| workflows/monitoring | built | B-83 | yes | 1 |
| workflows/notify | built | B-04 | yes | 23 |
| workflows/offboarding | built | B-36 | yes | 1 |
| workflows/onboarding | built | B-35 | yes | 1 |
| workflows/patching | built | B-67 | yes | 1 |
| workflows/phishing | built | B-45 | yes | 2 |
| workflows/questionnaires | built | B-60 | yes | 1 |
| workflows/regpacks | built | B-52 | yes | 1 |
| workflows/replies | built | B-25 | yes | 2 |
| workflows/reporting | built | B-71 | yes | 4 |
| workflows/restore_tests | built | B-69 | yes | 1 |
| workflows/rollback | built | B-41 | yes | 5 |
| workflows/sla | built | B-24 | yes | 1 |
| workflows/summary | built | B-22 | yes | 2 |
| workflows/teams_approvals | built | B-88 | yes | 1 |
| workflows/timeline | built | B-48 | yes | 1 |
| workflows/training | built | B-96 | yes | 1 |
| workflows/triage | built | B-05 | yes | 10 |

## Levers

| Lever | Status | Registry file | Test files naming it |
|---|---|---|---|
| ticket.get | built | levers/registry.json | 20 |
| kb.search | built | levers/registry.json | 12 |
| user.reset-mfa | built | levers/registry.json | 27 |
| user.disable | built | levers/registry.json | 44 |
| backup.retry-job | built | levers/registry.d/backup.json | 3 |
| contact.check | built | levers/registry.d/contact.json | 4 |
| user.reset-password | built | levers/registry.d/credential.json | 2 |
| user.new-tap | built | levers/registry.d/credential.json | 3 |
| device.lock | built | levers/registry.d/device-r3.json | 4 |
| device.unlock | built | levers/registry.d/device-r3.json | 1 |
| device.isolate | built | levers/registry.d/device-r3.json | 1 |
| device.release | built | levers/registry.d/device-r3.json | 1 |
| device.retire | built | levers/registry.d/device-r3.json | 1 |
| device.wipe | built | levers/registry.d/device-r3.json | 1 |
| device.restart-spooler | built | levers/registry.d/device.json | 2 |
| device.repair-mapped-drive | built | levers/registry.d/device.json | 2 |
| device.reset-outlook-profile | built | levers/registry.d/device.json | 2 |
| device.cleanup-temp | built | levers/registry.d/device.json | 2 |
| device.restart-service | built | levers/registry.d/device.json | 2 |
| device.reboot | built | levers/registry.d/device.json | 2 |
| device.reboot-server | built | levers/registry.d/device.json | 2 |
| group.add-member | built | levers/registry.d/group.json | 3 |
| group.remove-member | built | levers/registry.d/group.json | 3 |
| user.revoke-sessions | built | levers/registry.d/identity.json | 9 |
| user.enable | built | levers/registry.d/identity.json | 9 |
| user.set-properties | built | levers/registry.d/identity.json | 4 |
| inboxrule.list | built | levers/registry.d/inboxrule.json | 2 |
| inboxrule.disable | built | levers/registry.d/inboxrule.json | 4 |
| inboxrule.enable | built | levers/registry.d/inboxrule.json | 2 |
| license.add | built | levers/registry.d/license.json | 3 |
| license.remove | built | levers/registry.d/license.json | 3 |
| mailbox.add-dl-member | built | levers/registry.d/mailbox.json | 1 |
| mailbox.remove-dl-member | built | levers/registry.d/mailbox.json | 1 |
| mailbox.grant-full-access | built | levers/registry.d/mailbox.json | 1 |
| mailbox.revoke-full-access | built | levers/registry.d/mailbox.json | 1 |
| mailbox.grant-send-as | built | levers/registry.d/mailbox.json | 1 |
| mailbox.revoke-send-as | built | levers/registry.d/mailbox.json | 1 |
| mailbox.convert-shared | built | levers/registry.d/mailbox.json | 2 |
| mailbox.set-auto-reply | built | levers/registry.d/mailbox.json | 2 |
| mailbox.clear-auto-reply | built | levers/registry.d/mailbox.json | 1 |
| mailbox.enable-archive | built | levers/registry.d/mailbox.json | 2 |
| mailbox.grant-onedrive-manager | built | levers/registry.d/mailbox.json | 2 |
| mailbox.revoke-onedrive-manager | built | levers/registry.d/mailbox.json | 1 |
| message.trace | built | levers/registry.d/mailflow.json | 2 |
| quarantine.release | built | levers/registry.d/mailflow.json | 3 |
| user.new | built | levers/registry.d/provisioning.json | 2 |
| rag.search | built | levers/registry.d/rag.json | 2 |
| restore.to-alternate | built | levers/registry.d/restore.json | 2 |
| risk.list-users | built | levers/registry.d/risk.json | 2 |
| risk.user-facts | built | levers/registry.d/risk.json | 1 |
| risk.device-facts | built | levers/registry.d/risk.json | 1 |
| signins.list | built | levers/registry.d/signin.json | 3 |
| site.get | built | levers/registry.d/site.json | 1 |
| site.new | built | levers/registry.d/site.json | 2 |
| site.remove-empty | built | levers/registry.d/site.json | 1 |
| device.install-app | built | levers/registry.d/software.json | 2 |
| ticket.link | built | levers/registry.d/ticket.json | 4 |
| unix.disk-usage | built | levers/registry.d/unix.json | 1 |
| unix.restart-service | built | levers/registry.d/unix.json | 1 |
| unix.clear-cache | built | levers/registry.d/unix.json | 1 |

## Proposed fix for the owner
`docs/changes/B-98-map-status.patch` is a patch for `map/inventory.json` that rewrites only the rows where the map says planned and every covering roadmap item is built. Review it, then `git apply` it from the repo root. The audit does not edit `map/` itself. Rows covered by a mix of built and unbuilt items are listed above but not patched.
