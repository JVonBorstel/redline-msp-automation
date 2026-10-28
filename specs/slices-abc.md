# Slices A to C spec (ticket triage, Microsoft 365 baseline check, approval queue)

Goal: a 5-minute live demo that shows the three things a technical services manager cares about: access control, auditability, and real MSP time saved. Everything uses synthetic tenants (Contoso Dental, Fabrikam Capital), runs offline on a laptop, and is labelled "independently built prototype".

Order of build:
1. Phase 1 (specs/phase-1.md).
2. Slice A, then Slice B, then Slice C.
3. The demo script.

Each step is one or more work items on this repo. Each merges only when CI is green and the owner says yes.

## Slice A: AI ticket triage for technicians (thin Phase 2)
**What it shows:**
- Model-driven agents as "button pushers".
- Small model first, then rules.
- Untrusted ticket text that is never obeyed.

**Deliverables:**
- **Synthetic tickets:** `fixtures/tickets/` holds 60 tickets across 2 tenants. Each is labelled with category, priority, queue, and a suggested lever when one applies. 8 of them carry prompt-injection attempts.
- **Triage:** `workflows/triage` classifies through the gateway (the mock by default, the local model optional) and proposes at most one registered lever per ticket in dry-run. The output explains the category, why, the data used, and the lever with its parameters.
- **Corrections:** a technician correction is stored as eval data (`evals/triage/corrections.jsonl`).
- **Eval report:** `evals/triage/report.md` gives accuracy per field, labelled fixture-based.

**Acceptance tests:**
- **SA-1:** on the mock provider, category accuracy is at least 90% on the fixture set (deterministic).
- **SA-2:** none of the 8 injection tickets causes a lever outside the registry or outside its client. All 8 are flagged.
- **SA-3:** every proposal goes through the lever registry in dry-run, and each one is audited.
- **SA-4:** a correction round-trips into the eval file.

## Slice B: Microsoft 365 security baseline check (thin Phase 4, PowerShell)
**What it shows:**
- PowerShell 7 and the Microsoft Graph data model.
- Security posture, and a client report in plain English.

**Deliverables:**
- **Module:** `levers/powershell/TenantBaseline/` is a PowerShell 7 module.
- **Tenant data:** it reads tenant data from a mock Graph adapter, JSON fixtures shaped like real Microsoft Graph responses (users with signInActivity, authentication methods registration details, directoryRoles and members, conditionalAccess policies, and secure score). Fixtures are cited to the Graph docs field names, and anything not verified is marked as such.
- **Checks:**
  - users without MFA registered;
  - accounts with no sign-in for 90 or more days;
  - more than N global admins;
  - legacy-auth not blocked by Conditional Access;
  - break-glass accounts that do not follow the documented pattern;
  - guest users with admin roles.
- **Output:**
  - **Findings:** structured findings (severity, evidence, fix lever name);
  - **Reports:** an HTML report plus a CSV that is Power BI ready;
  - **Summary:** a plain-English client summary paragraph through the gateway.
- **Real Graph adapter:** stubbed behind `-UseGraph` with the exact scopes listed (read-only: User.Read.All, AuditLog.Read.All, Policy.Read.All, RoleManagement.Read.Directory, Reports.Read.All). It is not run without a test tenant.
- **Fix levers:** suggested fixes are registry levers in dry-run only (for example `user.require-mfa`, `user.disable`).

**Acceptance tests:**
- **SB-1:** each check finds exactly the seeded problems in the Contoso fixture and none in a clean fixture.
- **SB-2:** the HTML and CSV are produced, and every number in the summary reconciles to the findings (a validator script fails on a mismatch).
- **SB-3:** `-UseGraph` without a configured tenant exits with a clear message and makes no network call.
- **SB-4:** PSScriptAnalyzer is clean (if installed). The tests use Pester 5 if installed, and plain PowerShell otherwise.

## Slice C: approval queue and audit viewer (minimal UI)
**What it shows:** the human stays in the loop, and the audit evidence that SOC 2 needs.

**Deliverables:**
- **Local web page:** one local page (HTMX or plain HTML from a small local server, whichever needs no installs).
- **Pending actions:** it lists pending write-lever proposals (from Slices A and B). A lead approves or rejects each, and the approval record goes into the registry call.
- **Audit view:** an audit log view with a "verify chain" button.

**Acceptance tests:**
- **SC-1:** approve → the lever executes against the mock and is audited with the approver; reject → nothing changes.
- **SC-2:** a tampered log shows as broken in the viewer.
- **SC-3:** the server binds 127.0.0.1 only.

## Demo script (docs/DEMO.md)
Five minutes, in this order:
1. A ticket arrives.
2. Triage proposes a lever.
3. Then an injection ticket is flagged and ignored.
4. The baseline check on Contoso shows its findings.
5. The plain-English client summary.
6. The lead approves one fix in the queue.
7. The audit chain verifies.
8. One byte is tampered and the chain shows broken.

The script closes with "how I'd adapt this to the MSP in week one" (their PSA/RMM, a real Graph app registration with read-only scopes, Azure Key Vault, Azure DevOps pipelines).

## Honesty rules for the room
Fixture-based numbers are labelled as such. No claims of production use. Known gaps are stated plainly: no hands-on Azure tenant work and no MSP production experience behind these mocks.
