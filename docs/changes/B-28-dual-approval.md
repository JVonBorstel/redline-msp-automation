# B-28 follow-up change note: R3 dual approval through the queue and the approval page

Status: **built** (queue, page and `python -m ui` wiring, with tests). Sign-in is checked against the **mock** B-89 issuer or the `--demo` picker; nothing here has run against a real Entra tenant. Synthetic data only. Spec: `specs/B-28.md` ("Dual approval in the queue and the page"). Decision: D-067. Closes the gap recorded in `specs/B-28.md` and `specs/B-65.md` ("Limits") and in D-052.

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only.

## What changed

- `core/queue/store.py`: new status `awaiting-second-approval` (`AWAITING`), `RecordedApproval` (approver, runner-clock time, `ApproverAuth`, runner attestation, proposal digest, verification, contact confirmation) and `Proposal.approvals` (left out of the JSON when empty, so the shared Slice A/B/C contract and existing queue files are unchanged); `Proposal.digest` (SHA-256 over what a lead approves). `decide()` takes `contact`, `token` and `seen_digest`. With a runner policy and a lever that needs more than one lead: the first approval is checked by the runner (`attest`) together with the requester (and contact) verification and saved as awaiting, audited as `awaiting-second-approval` with the approver's sign-in record; a different lead's approval is checked the same way and only then is the proposal saved as `approved` and executed with every approval. Refusals (audited, nothing applied): the same lead twice, the requester, a lead outside the client, a first approval at or past the policy's age limit, an attestation the runner no longer accepts, an approval of a proposal that changed (the last three put the proposal back to `pending`), a page that showed a different digest. Either lead may reject. `open_queue(state, policy=None)`.
- `core/levers/runner.py`: `LeverRunner.now()`, `approvers_needed()`, `attest()` (returns a `SigninAttestation`, HMAC-SHA256 under a per-runner key held only in memory), `attestation_problem()`, `verification_problem()`, `SigninRefused`; `_check_signin` accepts an attested approval (the audit marks it with `attested_at`). `core/levers/models.py`: `SigninAttestation`, `Approval.attestation` (at most one of token, demo pick or attestation).
- `ui/app.py`: an R3 card says how many leads it needs; an awaiting card says `Approved by X, waiting for a second lead (1 of 2)` with the recorded verification; the lead who approved sees only **Reject**; another lead sees **Approve as second lead** with the card's digest in the form. `requester+contact` levers (B-65) get a contact picker filled from the client record's `authorized_contacts` (record ids only) and require a callback on the number on file. Verification times use the runner's clock. The demo picker label now says `not authentication`. In token mode the bearer token is passed to the runner for its own check and is never stored.
- `ui/__main__.py`: the page always runs under a `RunnerPolicy` (`--demo` maps to `RunnerPolicy(demo=True)`, `--auth-config` to the validator); new optional `--client-records FILE`; a bad file exits 2 before anything is created.
- `config/identities.json`: second synthetic lead `lead-mia` (W3-E1). `workflows/notify/notify.py`: the notice names the first approver on a dual-approved change (the R3 device templates already say "and a second service desk lead"). `core/queue/__main__.py`: `list --status` accepts the new status.
- Tests: `tests/py/queue/test_b28_queue_dual.py` (18), `tests/py/ui/test_b28_page_dual.py` (12), `tests/py/ui/test_b28_dual_e2e.py` (2: `user.reset-mfa` with two token-signed leads; `device.lock` with the authorized contact, through the PowerShell bridge). Updated for the new behaviour, none weakened: `tests/demo/test_b10_demo_smoke.py` (step 6a now approves as lead-lee, then completes as lead-mia, and the execute record must name both), `tests/phase1/test_identity.py` (the shipped identities now include `lead-mia`).
- Docs: `specs/B-28.md`, `specs/B-65.md`, `docs/DEMO.md` step 6a, `README.md`, `docs/changes/B-28.md`, `docs/changes/B-65.md`, `docs/map/05-governance.md`, `map/controls.json`, `docs/DECISIONS.md` (D-067).

## Why

D6-05 and HO-3 say an identity or device change of class R3 needs two different leads, neither the requester. The runner enforced it, but the only live path (the page) sent one approval to a runner without a policy, so the rule held in tests and nowhere else. A lead could still reset an MFA alone.

## Individual to macro (L1 to L4)

- **L1, one person.** Priya's MFA reset, or a lock of the office manager's laptop, now waits for a second lead after the first approves. A caller who talks one lead round still gets nowhere, and nothing changes for her until two people have looked.
- **L2, the client business.** The contact who confirms a device lock is one of the client's own named contacts, picked from its record, never typed. A lead outside the client cannot be the second approver.
- **L3, the MSP.** No single engineer can push an R3 change through the page. The audit chain shows the first approval (who, how they signed in) and the execute that names both approvers, so an auditor sees the four-eyes control happen, not just a policy that says it should.
- **L4, community.** The same two-person rule at every client makes help-desk impersonation, the usual way into a managed environment, harder everywhere at once.

## How the tests prove it

The queue tests drive `ProposalQueue.decide` on a private tenant copy with the runner clock pinned and moved by hand: a partial approval applies nothing and is audited; a second lead executes once with both in the runner's audit record; each refusal leaves the tenant unchanged and writes a denied record; a forged or foreign attestation is denied by the runner itself; a lever needing three leads stays awaiting after two. The page tests drive `App.handle` as the B-03 tests do, in demo-picker and token mode. The end-to-end tests dry-run as the triage agent, approve on the page as two leads, and verify the client's audit chain.

## Not done, and caveats

- **Restart voids partial approvals.** The attestation key lives in the runner's memory, so after `python -m ui` restarts, a proposal awaiting a second lead is refused on its next approval, audited, and put back to `pending`; the first lead approves again. Deliberate (no key on disk), and it fails closed.
- **The offline CLIs still run W1.** `python -m core.levers invoke --execute --approved-by`, `tools/packaged_demo.py` and the workflow CLIs that call `open_queue()` without a policy execute an R3 lever on one approval with no sign-in (the DEMO.md fallback for step 6 uses that path). Only the page is the live approval path.
- **Second lead in config.** `lead-mia` is synthetic. ROADMAP W3-E1 lists adding a second lead as the owner's step; it is applied here and recorded in D-067 for review.
- **The demo picker is not authentication.** It is accepted only with `--demo` and marked `demo` in the audit; with `--auth-config` each lead needs a valid token, checked by the mock issuer's validator only.
- **Client records are optional.** Without `--client-records`, levers that need an authorized contact or a business-hours window are refused (fail closed); no client records file is committed.
- Pre-authorized containment (on-call single approval, D6-08) is not offered on the page; the queue never marks an approval `on_call`.
