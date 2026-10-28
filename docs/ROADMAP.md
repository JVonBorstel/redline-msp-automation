# Roadmap: build waves for the whole program

Status: **planned** (mapping only, 2026-10-20). No code was written for this document. Machine-readable twin: `map/roadmap.json` (same ids, same fields, generated from one source so they cannot disagree). The item blocks between the `gen:items` markers are generated from the JSON: edit `map/roadmap.json`, then run `uv run --frozen python tools/gen_roadmap_md.py`.

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only. Nothing here has run against a real tenant, PSA, RMM or backup system, and nothing is claimed as production.

This roadmap covers every remaining piece of work in the work inventory (`docs/map/01-work-inventory.md`, 152 items) with **98 build items in 10 waves**. It uses the controls in `docs/map/05-governance.md` (`C-nn`), the rules in `docs/STANDARDS.md` (`STD-xx-n`), the architecture ids in `docs/map/03-architecture-target.md` (`ARC-`, `TEN-`, `SL-`, `DR-`) and the repo layout in `docs/map/04-repo-organization.md`.

## 0. How to read this

| Id | Meaning |
|---|---|
| `B-nn` | a build item: one pull request (or a short series), one owner, one spec |
| `W1`..`W10` | a build wave; one GitHub milestone each |
| `B<nn>-<k>` | an acceptance test of item `B-nn` (for example `B02-3`). Same style as `P1-2` and `SA-1` (STD-TS-2): defined in `specs/B-nn.md` before code; Python test names start with `test_b02_3_...`, Pester `It` names with `B02-3:` |
| `Wn-En`, `Wn-Xn` | a wave's entry step (owner or the MSP; applied before the wave, or during it right after the item it names) and exit step (the wave's definition of done) |
| `NN-nn` | a "not now" decision |

**Fields of every item** (both here and in `map/roadmap.json`): id, title, inventory ids covered, controls required, depends on, files it owns, acceptance tests, size, the standard sections it must follow, owner-only flag, and one line on why it matters.

**Ownership rule (parallel builders never collide).** An item may create or edit only the paths it owns. A path ending in `/` owns everything under it. Within one wave no two items create the same new path, and no item owns a path inside another item's folder; the map integrity test (`B-06`) fails CI if this is ever broken. Two items sharing a file that already exists is only a warning, because the build automation runs same-file orders one after another. Every item also owns its own spec (`specs/B-nn.md`) and its own change fragment (`docs/changes/B-nn.md`). Shared ledgers (`docs/DECISIONS.md`, `docs/COVERAGE.md`, `CHANGELOG.md`, `docs/RUNBOOKS.md`, `README.md`, `map/inventory.json`, `map/controls.json`) are edited only at a wave's exit (`Wn-X1`), by folding the fragments. That is what lets ten builders work at once.

**Dependencies.** `depends_on` lists the items that must be merged first. Items in a later wave also depend on every earlier wave's exit, so only the important cross-wave seams are listed. Dependencies inside one wave are allowed and mean "build in this order".

**Size.** Sized against the commit budget (12 files and 800 lines per commit).

| Size | Meaning |
|---|---|
| S | at most 5 files and about 300 changed lines, including tests and the spec |
| M | at most 12 files and 800 lines: fits one commit |
| L | larger than one commit. **No L items remain**: every L found while mapping was split (for example the PowerShell bridge into `B-15` host and `B-16` bridge, Bicep into `B-85` and `B-86`, alerts into `B-43` and `B-44`) |

**Owner-only items** (`B-07`, `B-08`) touch protected files (`.github/**`; also `pyproject.toml` and `config/**` in later entry steps). An agent drafts the exact diff in the item's change fragment; the owner applies it. Agents never approve or merge (CONTRIBUTING).

**Risk classes.** Lever risk in this roadmap uses the governance definitions (`docs/map/05-governance.md` section 6.1), because those are what the registry will enforce (`C-29`, item `B-01`). The inventory's `risk_class` column is a planning class and differs for a few items (for example `W-IDM-02` MFA reset is R3 in the inventory and R2 in governance). `B-06` prints every such mismatch as a warning. Decided (D-024, D6-07 in `docs/map/06-decisions.md`): identity changes are R3, and governance section 6.1 now says so.

## 1. Ordering principles

1. **The individual first.** Early waves favour work that decides whether one person can work today or is protected today: W1 (one person's MFA reset done safely), W2 (faster, cited answers on their ticket), W3 (joiner, mover, leaver, password and lockout help). Business-level and MSP-level work follows in W4 (security and evidence) and W7 (reports), because it rolls up from the same levers.
2. **Seams before families.** One shared change unlocks many parallel items: registry fragments (`B-14`), the PowerShell host and bridge (`B-15`, `B-16`), adapters with per-client bindings (`B-18`, `B-19`), audit v2 (`B-17`). Each lever family after that is its own module, registry fragment and fixture file.
3. **Read before write.** Every new system (PSA, Graph, alerts, RMM, backup) arrives first as a mock adapter and read levers; write levers follow with dry-run, approval, verification where a person is affected, and a notice template.
4. **The runner changes once per wave.** `core/levers/runner.py` has exactly one owner per wave (`B-02`, `B-16`, `B-28`, `B-42`), so permission logic is never edited by two builders at once.
5. **Never-automate is a gate, not a promise.** From W2 the registry refuses any lever matching `governance/never-automate.json` (`B-14`); the human-only work gets read-only fact packs and runbooks (`B-37`, `B-48`).
6. **Quality over volume in W1.** Everything in W1 is additive to Phase 1 and Slices A to C, and nothing merges after the freeze.

## 2. Waves at a glance

| Wave | Name | Items | S/M/L | Inventory items first covered | Window (estimate) |
|---|---|---|---|---|---|
| W1 | Demo story: one person, end to end | B-01 to B-11 (11) | 6/5/0 | 17 | 2026-10-21 to 2026-10-25 (freeze 2026-10-25 18:00 MT; 2026-10-26 rehearsal only) |
| W2 | Platform seams and service-desk drafts | B-12 to B-27, B-89 (17) | 5/12/0 | 23 | after the demo, about 2 weeks |
| W3 | Identity lifecycle: one person's access | B-28 to B-41, B-68 (15) | 5/10/0 | 26 | about 3 weeks |
| W4 | Security monitoring and compliance evidence | B-42 to B-54 (13) | 3/10/0 | 25 | about 3 weeks |
| W5 | Knowledge and retrieval | B-55 to B-60 (6) | 1/5/0 | 9 | about 2 weeks |
| W6 | Endpoints, patching and backup | B-61 to B-70 except B-68 (9) | 3/6/0 | 23 | about 3 weeks |
| W7 | Client reporting, licensing and billing inputs | B-71 to B-77 (7) | 3/4/0 | 19 | about 2 weeks |
| W8 | Scale, evaluation and hardening | B-78 to B-84 (7) | 0/7/0 | 3 | about 3 weeks |
| W9 | Cloud, DevOps and Microsoft 365 integrations | B-85 to B-91 except B-89 (6) | 1/5/0 | 5 | about 3 weeks |
| W10 | Governance pack, people and packaging | B-92 to B-98 (7) | 3/4/0 | 2 | about 2 weeks |

Totals: 98 items (30 S, 68 M, 0 L), 2 owner-only. Inventory coverage: 152 of 152 inventory items are covered by at least one build item. For human-only items, that item is a gate, fact pack, runbook or report that supports the person deciding, never the decision itself. 9 inventory items also appear in the not-now list, for the part that stays human. Controls referenced: 43 of 45; `C-22` (build-time agent guardrails) and `C-23` (commit secret scan) are already built and have no remaining build work.

## 3. Wave 1 in detail: the first demo

**The story the demo tells, granular to macro.** Priya Nair at Contoso Dental (synthetic; requester and affected user of ticket T-3101 in `fixtures/tickets/contoso-dental.json`, technician `tech-ana`) loses her phone. Triage proposes `user.reset-mfa` and shows who it affects at each level (`B-05`, from the lever's own `impact` field, `B-01`). The lead cannot approve until the caller is verified by a callback to the number on file (`B-02`, `B-03`), which is the control against the help-desk social engineering behind well-known 2023 breaches (AIR-11). After approval, Priya gets a plain-language notice draft that says what changed and how to get back (`B-04`). Any lead can pause the lever instantly (`B-02`). The audit chain proves every step, and a smoke test proves the whole script runs (`B-10`). A one-page leave-behind traces the same ticket up to the MSP and the community (`B-11`).

**Calendar (estimate, MT).**

| Day | Build | Merge when green |
|---|---|---|
| Wed 10-21 | `B-06` map test and suite runner; the owner applies `B-07`; `B-01` registry fields; `B-09` exporter | `B-06`, `B-07`, `B-01` |
| Thu 10-22 | `B-02` runner gates; `B-04` notice drafts; `B-05` triage trace | `B-04`, `B-05`, `B-09` |
| Fri 10-23 | `B-03` approval page; the owner applies `B-08` (labels, milestones, issues) | `B-02` and `B-03` **together** |
| Sat 10-24 | `B-10` demo v2 and smoke test; `B-11` leave-behind | `B-10`, `B-11` |
| Sun 10-25 | 18:00 freeze: W1 exit steps, tag `demo-2026-10-27` | close-out only |
| Mon 10-26 | rehearsal from the tag; no merges | - |

**Cut line.** If time runs short, cut from the bottom of this list and keep the rest. The demo of Phase 1 and Slices A to C already works, so a cut costs story, never the demo.

1. `B-06`, `B-01`, `B-10`: must have (they protect quality and carry the trace).
2. `B-02` and `B-03` together: **merge as a pair or not at all.** `B-02` alone would refuse the UI approval in demo step 6, because the page could not yet record a verification.
3. `B-05`, then `B-04`.
4. `B-11`, `B-09`, `B-08`: useful, not demo-critical.

**W1 risks.** Visible output changes (DR-02 masking, DR-12 scoped listing, the extra verification field) are listed in each PR and in DEMO v2. Readability scoring in `B-04` is a simple formula computed in the test, not a claim of accessibility compliance. Nothing in W1 adds a dependency or an install.

## 4. Definition of done (shared by every item)

An item is done when all of these hold. They extend STD-DD (`docs/STANDARDS.md` section 15), which still applies line by line.

| Id | Rule |
|---|---|
| DOD-1 | `specs/B-nn.md` exists before code and defines the item's acceptance ids `B<nn>-<k>`, refined from this roadmap (the roadmap wording is the floor, not the ceiling). |
| DOD-2 | Every acceptance id has a test that names it; every denial path is tested together with its audit record (STD-TS-3); tests are offline and deterministic (STD-TS-4). |
| DOD-3 | The item changed only the paths it owns. A needed change to another path is a new item or a note for the owning item, never a quiet edit. |
| DOD-4 | All existing suites still pass (`tests/phase1`, `tests/sliceb`, `tests/py`, `tests/ps`, `tests/demo`), and so do lint and types for the touched packages (`ruff`, `mypy --strict`, PSScriptAnalyzer when installed). |
| DOD-5 | Every lever follows STD-DD-4 and also declares `risk_class`, `impact` (L1 to L4), `undo` or "manual", and has a notice template if it is a write lever (`B-01`, `B-04`). |
| DOD-6 | Every workflow has an eval set and a fixture-based result (STD-DD-5); every client-facing number is reconciled by a validator (C-21 pattern); every client-facing text is a draft that a person sends (HO-9). |
| DOD-7 | Isolation: anything that reads client data has a test showing client A cannot see client B (STD-TS-6). |
| DOD-8 | Security: no secrets, loopback only, untrusted text scanned and wrapped, never-log list respected (STD-AU-4). An independent review and a security review have run, and their findings are fixed or recorded. |
| DOD-9 | `docs/changes/B-nn.md` holds the DECISIONS entry or entries, the COVERAGE row changes with strict status words, the CHANGELOG line, the inventory and control status changes, and any runbook. |
| DOD-10 | The PR is titled `B-nn: <title>`, links its issue, and states who it helps at L1 to L4 in one line each (STD-DD-10), naming the impact chain ids (the inventory ids of its chains, RF-02). |
| DOD-11 | It fits the commit budget (12 files, 800 lines) or is split; CI is green; the owner approves; agents never merge. |
| DOD-12 | Honest labels: every number is fixture-based and says so; anything unverified is marked UNVERIFIED with what would verify it. |

## W1: Demo story: one person, end to end

**Window (estimate):** 2026-10-21 to 2026-10-25 (freeze 2026-10-25 18:00 MT; 2026-10-26 rehearsal only)  
**Items:** 11 (6 S, 5 M, 0 L)

**Goal.** Make the Oct 27 demo tell one unbroken story from one person at one client (Priya Nair, ticket T-3101) up to the MSP and the community: the lever carries who it affects, a lead cannot approve an identity change until the caller was verified out of band, any lead can pause a lever instantly, the person gets a plain-language notice draft, and a smoke test proves the whole script still runs. Every change is additive to Phase 1 and Slices A-C; anything not green by the freeze is cut, not rushed.

**Entry steps (owner or the MSP).**
- W1-E1: the owner approves this roadmap and the W1 cut line (section 3).
- W1-E2: the owner applies B-07 (CI) on day one so the build automation can run the new suites.

| Id | Title | Size | Inventory | Controls | Depends on |
|---|---|---|---|---|---|
| `B-01` | Registry fields: risk class, undo, impact trace, verification rule | M | W-TOOL-01, W-GOV-03, W-IDM-04 | C-29, C-30, C-02, C-01 | - |
| `B-02` | Runner gates: pause switch, requester verification, contact-detail masking | M | W-IDM-02, W-ONB-08, W-SEC-04, W-GOV-04, W-CMP-05 | C-31, C-30, C-11, C-18, C-08, C-09 | B-01 |
| `B-03` | Approval page: verification capture, scoped listing, diff, undo and impact shown | M | W-TOOL-06, W-IDM-02, W-IDM-04 | C-30, C-06, C-07, C-19, C-27 | B-01, B-02 |
| `B-04` | Affected-person notice drafts | M | W-IDM-02, W-ONB-08, W-SD-09, W-SEC-04 | C-35, C-36, C-45 | B-01 |
| `B-05` | Triage output shows the impact trace and the verification needed | S | W-SD-02, W-SD-07 | C-14, C-30, C-45 | B-01 |
| `B-06` | Map integrity test and the Python test suite runner | S | W-TOOL-13, W-TOOL-04 | C-37, C-45 | - |
| `B-07` | CI for the new suites (owner) | S | W-TOOL-07 | C-24, C-37 | B-06 |
| `B-08` | GitHub organization: labels, milestones, issue form, PR template, CODEOWNERS (owner) | S | W-TOOL-07, W-TOOL-13 | C-37, C-24, C-22, C-23 | B-09 |
| `B-09` | Roadmap-to-issues exporter and change-fragment folder | S | W-TOOL-13 | C-37 | B-06 |
| `B-10` | Demo v2 and its end-to-end smoke test | M | W-TOOL-06, W-CMP-05, W-SD-02, W-M365-11 | C-41, C-45, C-08 | B-02, B-03, B-04, B-05 |
| `B-11` | One-ticket trace leave-behind (T-3101, granular to macro) | S | W-IDM-02, W-TRN-02 | C-45, C-08, C-30 | B-03, B-04, B-05 |

<!-- gen:items:start -->
**`B-01` Registry fields: risk class, undo, impact trace, verification rule**
- Why: Puts the granular-to-macro trace and the social-engineering rule on the lever itself, where permissions already live.
- Owns: `core/levers/models.py`, `core/levers/registry.py`, `levers/registry.json`, `tests/py/levers/test_b01_registry_fields.py`, `specs/B-01.md`, `docs/changes/B-01.md`
- Standards: STD-LV, STD-PY, STD-TS, STD-CF
- Acceptance:
  - **B01-1** every lever in levers/registry.json declares `risk_class` (R0-R3, governance 6.1), `reversibility`, `undo` (lever name or null), `lever_version` and `impact` (one line each for L1-L4); a write lever without `risk_class` or `impact` fails the load with a RegistryError that names the lever
  - **B01-2** a `read` lever declaring R1-R3, or a `write` lever declaring R0, fails the load (class and risk must agree)
  - **B01-3** `verification: "requester"` is accepted on write levers only; `Approval` gains an optional `verification` object {method, by, at, ref} whose `method` is one of callback-on-file, in-person, manager-confirmed, finding-reference; any other value is rejected
  - **B01-4** all existing tests in tests/phase1 pass unchanged; the four existing levers keep their names, params and approval rules

**`B-02` Runner gates: pause switch, requester verification, contact-detail masking**
- Why: Stops the help-desk social-engineering pattern (AIR-11) at the runner, and gives every lead a kill switch.
- Owns: `core/levers/runner.py`, `core/levers/pause.py`, `core/levers/__main__.py`, `tests/py/levers/test_b02_runner_gates.py`, `specs/B-02.md`, `docs/changes/B-02.md`
- Standards: STD-LV, STD-AU, STD-ER, STD-TS, STD-PY
- Acceptance:
  - **B02-1** `python -m core.levers pause <lever> [--client <id>] --as <lead> --reason <text>` pauses a lever globally or for one client; a paused lever is denied in dry-run and execute with reason `lever paused by <id>: <reason>`; pause and resume each write one audit record; only a `lead` may pause or resume, and pausing needs no approval (IR-2)
  - **B02-2** executing a lever with `verification: "requester"` (user.reset-mfa, user.disable) without an approval whose `verification.method` is set is denied with reason `needs a recorded requester verification (C-30)` and audited; with it, the audit record carries method, by and at
  - **B02-3** after a user.reset-mfa execute on the Contoso fixture, no audit record contains a phone-shaped value or an authentication-method field other than type and id (DR-02); the dry-run result returned to the caller still shows the full diff; a `ticket.get` read leaves no ticket field in its audit record (closes the C-11 test gap)
  - **B02-4** the crash path records the idempotency key (DR-03); every pre-existing Phase 1 test passes, except demo-fallback expectations that change by adding `--verified`, each listed in the PR

**`B-03` Approval page: verification capture, scoped listing, diff, undo and impact shown**
- Why: The human approval step becomes the place where the person is protected: verified, scoped, and shown exactly what will happen.
- Owns: `core/queue/store.py`, `core/queue/__main__.py`, `ui/app.py`, `ui/static/app.css`, `tests/py/queue/test_b03_approval_page.py`, `specs/B-03.md`, `docs/changes/B-03.md`
- Standards: STD-PR, STD-ID, STD-SC, STD-AU, STD-TS
- Acceptance:
  - **B03-1** a lead sees only proposals for clients in their own list (DR-12); a decide POST for another client is refused and audited
  - **B03-2** for a lever with `verification: "requester"`, approve is refused server-side unless the form carries a method from the allowed list and, for callback-on-file, the number-on-file source (never the number itself); the decision record holds the verification
  - **B03-3** each pending proposal shows the dry-run diff, the undo lever (or `no undo lever: manual undo`), the affected person's UPN and the lever's L1 impact line; the page still sends a CSP with no script and every value is escaped
  - **B03-4** `seed --demo` sends each seeded proposal through the runner as triage-bot in dry-run first (DR-15), so every seeded proposal has a dry-run audit record; SC-1, SC-2 and SC-3 still pass

**`B-04` Affected-person notice drafts**
- Why: The end user hears, in plain words, what was done to their account and how to get back (EU-1, EU-2).
- Owns: `workflows/notify/`, `fixtures/notify/`, `tests/py/notify/test_b04_notify.py`, `specs/B-04.md`, `docs/changes/B-04.md`
- Standards: STD-PY, STD-FX, STD-DC, STD-TS
- Acceptance:
  - **B04-1** `python -m workflows.notify <proposal-id> --state <dir>` writes a draft for an executed proposal only; any other status is refused with a clear reason
  - **B04-2** every write lever in the registry has a template in workflows/notify/templates/<lever>.md (the test fails when a write lever lacks one); filling is deterministic from trusted fields (no model)
  - **B04-3** the T-3101 draft says what changed, why, who approved it, how to get back (the fast-path contact from fixtures/notify/contacts.json, 555-01xx) and how to undo; it contains no secret-shaped value and no personal phone number, is at most 120 words, and scores grade 8 or lower on a Flesch-Kincaid formula computed in the test
  - **B04-4** the first line of every draft is `Draft. A person reviews and sends this.` (HO-9)

**`B-05` Triage output shows the impact trace and the verification needed**
- Why: Step 2 of the demo shows the person behind the proposal before anyone approves it.
- Owns: `workflows/triage/triage.py`, `workflows/triage/__main__.py`, `tests/py/triage/test_b05_trace.py`, `specs/B-05.md`, `docs/changes/B-05.md`
- Standards: STD-PR, STD-SC, STD-TS
- Acceptance:
  - **B05-1** for T-3101 the triage output adds `who this affects` (the lever's L1-L4 lines) and `before approval: call back on the number on file` because the lever requires requester verification
  - **B05-2** flagged tickets (the 8 injection tickets) still get no lever and no trace; SA-1 to SA-4 still pass with the same numbers
  - **B05-3** the JSON output (`--json`) carries the same fields; no ticket free text is copied into them

**`B-06` Map integrity test and the Python test suite runner**
- Why: Keeps the maps honest and makes parallel building safe: a collision fails CI before two builders meet. The map checks of B06-1 to B06-4 already exist (map/check_map.py, enforced through tests/phase1/test_map.py, written in the mapping-stage synthesis pass); B-06 adds the Py suite runner, the inventory-versus-governance risk-class warning (RQ-01) and the spec, and keeps both files passing.
- Owns: `tests/py/Test-Py.ps1`, `map/check_map.py`, `tests/phase1/test_map.py`, `specs/B-06.md`, `docs/changes/B-06.md`
- Standards: STD-TS, STD-DC
- Acceptance:
  - **B06-1** every id in map/inventory.json, map/controls.json and map/roadmap.json is unique and matches its pattern (W-<AREA>-<nn>, C-<nn>, B-<nn>, W<n>)
  - **B06-2** every inventory id and control id named in roadmap.json resolves; every depends_on resolves to an item in the same or an earlier wave and the graph has no cycle
  - **B06-3** every inventory id is covered by at least one roadmap item or by a `not_now` entry
  - **B06-4** no two items in one wave own the same path, and no owned directory contains a path owned by another item in that wave; `tests/py/Test-Py.ps1` prints `Py tests: N passed, M failed` (STD-TS-5)

**`B-07` CI for the new suites (owner)** (owner only: protected files, the owner applies)
- Why: Protected files: the agent drafts the diff in docs/changes/B-07.md, the owner applies it.
- Owns: `.github/workflows/ci.yml`, `docs/changes/B-07.md`, `specs/B-07.md`
- Standards: STD-SC, STD-TS
- Acceptance:
  - **B07-1** CI runs tests/py/Test-Py.ps1 and (after B-10) tests/demo/Test-Demo.ps1 on windows-latest; actions stay pinned to released versions and `permissions: contents: read` is unchanged
  - **B07-2** the runner's suite list names the same suites
  - **B07-3** a deliberately failing test on a throwaway branch turns CI red (checked once, not merged)

**`B-08` GitHub organization: labels, milestones, issue form, PR template, CODEOWNERS (owner)** (owner only: protected files, the owner applies)
- Why: Protected files and GitHub changes: agents are blocked from both, so the owner applies them.
- Owns: `.github/ISSUE_TEMPLATE/work-item.yml`, `.github/ISSUE_TEMPLATE/config.yml`, `.github/pull_request_template.md`, `.github/CODEOWNERS`, `.github/labels.json`, `docs/changes/B-08.md`, `specs/B-08.md`
- Standards: STD-DC, STD-VR
- Acceptance:
  - **B08-1** every label in docs/map/04-repo-organization.md section 6.1 exists with its description; one milestone per wave W1-W10 with the wave goal as its description
  - **B08-2** the issue form requires roadmap id, inventory ids, impact chain id or L1-L4 lines, controls, acceptance ids and owned paths; blank issues are disabled
  - **B08-3** the PR template adds the L1-L4 traceability lines (STD-DD-10) and the roadmap id; CODEOWNERS adds the explicit paths in 04 section 6.4
  - **B08-4** one issue exists per W1 item, created from the B-09 exporter's output by the owner

**`B-09` Roadmap-to-issues exporter and change-fragment folder**
- Why: One source of truth (roadmap.json) drives GitHub or Azure Boards; ledgers are folded once per wave, so parallel PRs never edit the same file.
- Owns: `tools/roadmap_issues.py`, `tools/fold_changes.py`, `docs/changes/README.md`, `tests/py/tools/test_b09_tools.py`, `specs/B-09.md`, `docs/changes/B-09.md`
- Standards: STD-PY, STD-TS, STD-DC
- Acceptance:
  - **B09-1** `uv run python tools/roadmap_issues.py --wave W1` prints one `gh issue create` command per item (title `B-nn: <title>`, labels, milestone, body with every roadmap field) and runs nothing itself
  - **B09-2** `--format ado-csv` prints the same items as an Azure Boards import CSV (work item type, title, tags, iteration, description), for the MSP's Azure DevOps
  - **B09-3** `tools/fold_changes.py --wave W1 --dry-run` prints the ledger edits the wave's fragments would make and changes nothing; without `--dry-run` it appends them and is idempotent (a second run changes nothing)

**`B-10` Demo v2 and its end-to-end smoke test**
- Why: The demo becomes a tested artifact, so a late change cannot silently break it.
- Owns: `docs/DEMO.md`, `tests/demo/Test-Demo.ps1`, `tests/demo/test_b10_demo_smoke.py`, `specs/B-10.md`, `docs/changes/B-10.md`
- Standards: STD-TS, STD-DC
- Acceptance:
  - **B10-1** the smoke test runs every typed command of DEMO.md steps 1-8 (and the fallbacks) in a temp state folder, offline, and checks each expected marker (`"status": "ok"`, the two denial reasons, `OK: <n> records`, `BROKEN at seq`)
  - **B10-2** the script adds, inside the same five minutes: the callback verification before approve, the notice draft after execute, and `pause` then a denied invoke then `resume`; the timing table still sums to 5:00 or less
  - **B10-3** the smoke test finishes in under 120 seconds on the laptop and prints `Demo tests: N passed, M failed`
  - **B10-4** honesty lines and the week-one plan are unchanged in substance; every number shown is still labelled fixture-based

**`B-11` One-ticket trace leave-behind (T-3101, granular to macro)**
- Why: A page the reader can keep that shows the mantra in one concrete case.
- Owns: `docs/TRACE_T3101.md`, `specs/B-11.md`, `docs/changes/B-11.md`
- Standards: STD-DC
- Acceptance:
  - **B11-1** one page: the ticket, the triage proposal, the verification, the approval, the audit record, the notice draft, and what it means for Contoso Dental, the MSP and the community, each line citing the ids (W-, C-, EU-, ISO-, HO-) it rests on
  - **B11-2** every command in it is also in DEMO.md (the smoke test covers it); every number is labelled fixture-based; it states plainly what is not proven (no real tenant, no real callback)
  - **B11-3** readable by a non-technical reader: no unexplained acronym (each spelled out once)
<!-- gen:items:end -->

**Exit steps (wave definition of done).**
- W1-X1: Fold every docs/changes/B-nn.md of the wave into docs/DECISIONS.md, docs/COVERAGE.md, CHANGELOG.md and docs/RUNBOOKS.md (one PR, `tools/fold_changes.py` once B-09 exists; by hand before).
- W1-X2: Update `repo_status` in map/inventory.json and `implemented_in`/`evidence` in map/controls.json for every id the wave touched; a control moves to built only with a named passing test.
- W1-X3: All suites green locally and in CI; map integrity test (B-06) green; demo smoke test (B-10) green.
- W1-X4: the owner reviews the wave report (BUILT / MOCKED / NOT DONE / RISKS / HOW TO RUN / WHAT I SHOULD REVIEW) and says yes before the next wave starts.
- W1-X5: Tag the freeze commit on main `demo-2026-10-27`; nothing merges to main after the freeze until the demo is over.

## W2: Platform seams and service-desk drafts

**Window (estimate):** after the demo, about 2 weeks  
**Items:** 17 (5 S, 12 M, 0 L)

**Goal.** Build the shared seams every later lever needs (schemas, registry fragments, the PowerShell bridge, adapters with per-client bindings, audit v2) and, in parallel, the read-only service-desk helpers that save a technician minutes on every ticket without touching a client system.

**Entry steps (owner or the MSP).**
- W2-E1: the owner applies the W2 owner wiring: `version: 1` in config/models.json and config/routing.json (DR-07), config/clients/<id>.json for the synthetic clients (ONB-01, after B-13 publishes client.schema.json), the third synthetic client in config/identities.json (B-21), pyproject.toml mypy `files` += workflows, evals, ui (after B-27), and the tests/ps suite in CI (after B-15).

| Id | Title | Size | Inventory | Controls | Depends on |
|---|---|---|---|---|---|
| `B-12` | Repo paths, gateway and guard drift, config version field | S | W-TOOL-02 | C-16, C-15 | - |
| `B-13` | schemas/ folder, generator and cross-language drift check | M | W-TOOL-01 | C-02, C-21 | - |
| `B-14` | Registry fragments, Python lever modules and the never-automate gate | M | W-TOOL-01, W-ONB-15, W-IDM-04, W-IDM-06, W-IDM-07, W-M365-12, W-BDR-07, W-SEC-07, W-CMP-07, W-VND-02, W-KB-07, W-BIL-04, W-TRN-04 | C-01, C-29, C-20 | B-13 |
| `B-15` | PowerShell lever host module | M | W-TOOL-01 | C-05, C-17, C-10 | B-13 |
| `B-16` | Python bridge and runner dispatch by runtime | M | W-TOOL-01 | C-17, C-05, C-04, C-08 | B-15, B-14 |
| `B-17` | Audit record v2 and verifier | M | W-CMP-05, W-CMP-01 | C-08, C-39, C-11 | - |
| `B-18` | Adapter base, per-client bindings and the PSA mock | M | W-TOOL-11, W-SD-01 | C-04, C-27, C-10 | B-13 |
| `B-19` | Graph mock adapter with per-family state | M | W-TOOL-11 | C-04, C-05, C-27 | B-18 |
| `B-20` | Prompt library and prompt standards | S | W-TOOL-03 | C-12, C-41, C-16 | - |
| `B-21` | Phase 2 ticket set: 200+ labelled tickets and a third synthetic client | M | W-SD-01, W-SD-03, W-SD-04, W-SD-05, W-SD-06 | C-45, C-41 | - |
| `B-22` | Ticket summaries, intake matching and escalation context packages | M | W-SD-01, W-SD-04, W-SD-07, W-VND-04 | C-12, C-13, C-27, C-41 | B-20, B-21, B-18 |
| `B-23` | Duplicate, related-ticket and outage grouping | M | W-SD-03, W-SD-08 | C-27, C-41, C-05 | B-14, B-21, B-18 |
| `B-24` | SLA breach watch and backlog grooming report | S | W-SD-06, W-SD-10 | C-27, C-21 | B-18, B-21 |
| `B-25` | Draft replies with KB citations and closure follow-up drafts | M | W-SD-05, W-SD-09 | C-12, C-26, C-41, C-45 | B-20, B-21 |
| `B-26` | Drift fixes: single proposal definitions and TenantBaseline canonical ids | S | W-TOOL-06, W-M365-11 | C-06, C-21 | - |
| `B-27` | mypy strict across workflows, evals and ui (code side of DR-06) | S | W-TOOL-07 | C-24 | B-26 |
| `B-89` | Entra sign-in for approvers (design and mock token validation) | M | W-TOOL-06 | C-44, C-19, C-07 | B-03 |

<!-- gen:items:start -->
**`B-12` Repo paths, gateway and guard drift, config version field**
- Why: Removes working-directory surprises before many new modules depend on them.
- Owns: `core/paths.py`, `core/gateway/config.py`, `core/gateway/base.py`, `core/gateway/gateway.py`, `core/gateway/hosted.py`, `core/gateway/loopback.py`, `core/gateway/mock.py`, `core/gateway/ollama.py`, `core/guard/wrap.py`, `core/guard/detect.py`, `tests/py/core/test_b12_paths.py`, `specs/B-12.md`, `docs/changes/B-12.md`
- Standards: STD-PY, STD-CF
- Acceptance:
  - **B12-1** `core.paths.REPO_ROOT` is the default root for the gateway config loader (DR-08); running from another working directory loads the same files
  - **B12-2** every gateway and guard module has `from __future__ import annotations` (DR-14) with no behaviour change; P1-7 and P1-8 still pass
  - **B12-3** GatewayConfig accepts `version: 1`, rejects any other value, and accepts an absent version only until the owner wiring adds it (DR-07, tracked)

**`B-13` schemas/ folder, generator and cross-language drift check**
- Why: One written-down shape for Python and PowerShell, so the bridge cannot drift.
- Owns: `schemas/`, `tools/gen_schemas.py`, `tests/py/contract/test_b13_schemas.py`, `tests/ps/Test-Schemas.ps1`, `specs/B-13.md`, `docs/changes/B-13.md`
- Standards: STD-XL, STD-CF, STD-PS, STD-TS
- Acceptance:
  - **B13-1** schemas/ holds lever-registry, identities, change, lever-request, lever-result, proposal, audit-record, finding and client schemas (draft 2020-12, STD-XL-1); `tools/gen_schemas.py` regenerates the pydantic-sourced ones
  - **B13-2** a test fails when a committed schema differs from the generated one
  - **B13-3** PowerShell `Test-Json -SchemaFile` accepts a known-good and rejects a known-bad document for each schema (closes the STD-XL-3 UNVERIFIED note, or records which keyword fails)

**`B-14` Registry fragments, Python lever modules and the never-automate gate**
- Why: Lets many lever families land in parallel without touching one file, and makes the never list a hard gate.
- Owns: `core/levers/registry.py`, `core/levers/handlers.py`, `levers/registry.d/README.md`, `levers/python/__init__.py`, `governance/never-automate.json`, `tests/py/levers/test_b14_fragments.py`, `specs/B-14.md`, `docs/changes/B-14.md`
- Standards: STD-LV, STD-CF, STD-TS
- Acceptance:
  - **B14-1** levers/registry.json plus every levers/registry.d/*.json load as one registry; a duplicate name across files, a fragment without `version`, or an unknown field fails the whole load
  - **B14-2** a Python lever's `entry` resolves only to a callable inside the `levers.python` package; any other module path is refused at load
  - **B14-3** governance/never-automate.json lists each never-automate inventory id with lever-name patterns (for example `role.grant*`, `ca.set*`, `hold.*`, `vault.*`, `license.purchase*`); the loader refuses any lever matching a pattern, with the inventory id and reason in the error
  - **B14-4** the four existing levers load unchanged and P1-1 to P1-9 pass

**`B-15` PowerShell lever host module**
- Why: The PowerShell side of 'Python orchestrates, PowerShell acts'.
- Owns: `levers/powershell/LeverHost/`, `tests/ps/Test-Modules.ps1`, `specs/B-15.md`, `docs/changes/B-15.md`
- Standards: STD-PS, STD-XL, STD-ER, STD-TS
- Acceptance:
  - **B15-1** `Invoke-LeverRequest.ps1` reads one JSON request on stdin (lever-request schema), imports only the module named in `entry`, calls the function with `-WhatIf` for dry-run, and writes one JSON result (lever-result schema) on stdout with exit code 0/1/2
  - **B15-2** a thrown error inside a lever becomes `{status: error, reason: "<lever> crashed: <type>"}` with no stack text on stdout (STD-ER-5, STD-ER-7)
  - **B15-3** a request naming a function not exported by its module is refused; tests/ps/Test-Modules.ps1 runs every levers/powershell/*/tests file and prints `PS modules tests: N passed, M failed`

**`B-16` Python bridge and runner dispatch by runtime**
- Why: Every identity, device and M365 lever after this is PowerShell with no core change.
- Owns: `core/levers/bridge.py`, `core/levers/runner.py`, `tests/py/levers/test_b16_bridge.py`, `levers/powershell/Sample/`, `specs/B-16.md`, `docs/changes/B-16.md`
- Standards: STD-LV, STD-XL, STD-ER, STD-TS
- Acceptance:
  - **B16-1** a lever with `runtime: "powershell"` runs through `pwsh -NoProfile -NonInteractive` with every runner check (registry, schema, role, scope, approval, pause, verification, audit) done in Python first
  - **B16-2** the child process is killed at `timeout_s` and the result is `error` with nothing applied (SL-06)
  - **B16-3** a sample read lever and a sample write lever in levers/powershell/Sample/ produce the same diff shape in dry-run as a Python lever, and an execute applies exactly the dry-run diff

**`B-17` Audit record v2 and verifier**
- Why: Correlates every action with its trace and its lever version, which audits and incident scoping need.
- Owns: `core/audit/chain.py`, `core/audit/verify.py`, `core/audit/__init__.py`, `tests/py/audit/test_b17_audit_v2.py`, `specs/B-17.md`, `docs/changes/B-17.md`
- Standards: STD-AU, STD-VR, STD-TS
- Acceptance:
  - **B17-1** new records carry `v: 2`, `event`, `actor_kind`, `lever_version` and `request_id` (STD-AU-2), with defaults when the caller does not pass them; v1 records are never rewritten
  - **B17-2** the verifier accepts a v1 prefix followed by v2 records and rejects a v1 record after a v2 one; P1-2 tamper tests pass for both
  - **B17-3** the `Mode` literal lists the four values actually written (DR-04) and `append` is typed with it

**`B-18` Adapter base, per-client bindings and the PSA mock**
- Why: The seam where the MSP's real PSA plugs in later (Q-01), with isolation built in.
- Owns: `adapters/__init__.py`, `adapters/base.py`, `adapters/binding.py`, `adapters/psa/`, `fixtures/psa/`, `tests/py/adapters/test_b18_psa.py`, `specs/B-18.md`, `docs/changes/B-18.md`
- Standards: STD-ID, STD-ER, STD-CF, STD-FX, STD-SC
- Acceptance:
  - **B18-1** an adapter instance is built for exactly one client from that client's binding (config/clients/<id>.json: implementation, external ids, credential reference name); asking it for another client's object is refused at construction (TEN-04)
  - **B18-2** the PSA mock serves tickets, contacts, companies and SLA settings from fixtures/psa/ and returns typed results with `ok` and `reason` (STD-ER-1), never raising to the caller
  - **B18-3** a binding that holds a credential value instead of a reference name fails validation (STD-CF-7); real implementations are absent and selecting one fails closed with `real adapter not configured`
  - **B18-4** the PSA mock's entities and fields follow the public Autotask REST API shape (Companies, Contacts, Tickets, TicketNotes, Resources), each field marked Verified or UNVERIFIED in the spec; the adapter interface stays vendor-neutral, so a ConnectWise or Halo binding is the same seam (D6-01)

**`B-19` Graph mock adapter with per-family state**
- Why: Lets each identity lever family bring its own fixture file without editing a shared one.
- Owns: `adapters/graph/`, `tests/py/adapters/test_b19_graph.py`, `fixtures/graph/SOURCES.md`, `specs/B-19.md`, `docs/changes/B-19.md`
- Standards: STD-FX, STD-ID, STD-LV
- Acceptance:
  - **B19-1** the Graph mock reads the existing fixtures/tenant/<client>.json plus optional fixtures/tenant/<client>/<family>.json files; a family file for another client is never read
  - **B19-2** state reads return copies; writes go only through the runner's diff-and-save path (SL-04)
  - **B19-3** SOURCES.md lists each new Graph shape with its Microsoft Learn page and Verified/UNVERIFIED per field (STD-FX-2)

**`B-20` Prompt library and prompt standards**
- Why: Reusable, reviewable prompts instead of strings scattered in code (posting: prompt standards and libraries).
- Owns: `prompts/STANDARDS.md`, `prompts/library/`, `prompts/__init__.py`, `tests/py/prompts/test_b20_prompts.py`, `specs/B-20.md`, `docs/changes/B-20.md`
- Standards: STD-DC, STD-SC, STD-VR
- Acceptance:
  - **B20-1** each prompt is a versioned file `prompts/library/<task>.v<n>.md` with front matter (task, version, inputs, output schema, owner); the loader refuses an unknown version
  - **B20-2** every prompt that takes untrusted text places it only inside the `wrap_untrusted` block and states that data is not instructions (test checks each file)
  - **B20-3** STANDARDS.md covers structure, minimum-necessary inputs (BA-4), output schemas, versioning and how a prompt change goes through evals (C-41)

**`B-21` Phase 2 ticket set: 200+ labelled tickets and a third synthetic client**
- Why: Phase 2 needs a set big enough to measure; a third client makes isolation tests real.
- Owns: `fixtures/tickets/phase2/`, `fixtures/tenant/litware-legal.json`, `evals/phase2/README.md`, `specs/B-21.md`, `docs/changes/B-21.md`
- Standards: STD-FX, STD-TS
- Acceptance:
  - **B21-1** at least 200 synthetic tickets across three clients (Contoso Dental, Fabrikam Capital, Litware Legal) with gold labels for category, priority, queue, duplicate group, SLA tier, summary facts and reply source articles; the original 60 tickets are untouched
  - **B21-2** at least 20 tickets contain synthetic PHI or NPI-shaped strings (fake patient names, 555 numbers, fake account numbers) labelled as such, for the redaction and leakage evals later
  - **B21-3** every file carries `_note` (synthetic), dates come with an `as_of`, and labels are never read by the code under test (STD-FX-5)
  - **B21-4** at least half of the new tickets belong to Fabrikam Capital (financial, RIA) and Litware Legal, matching the verticals the MSP publishes (financial services, legal, accounting); Contoso Dental stays as the W1 demo client (D6-13)

**`B-22` Ticket summaries, intake matching and escalation context packages**
- Why: Saves the next technician from re-asking the end user what already happened.
- Owns: `workflows/summary/`, `evals/summary/`, `tests/py/summary/test_b22_summary.py`, `specs/B-22.md`, `docs/changes/B-22.md`
- Standards: STD-PR, STD-SC, STD-TS, STD-DC
- Acceptance:
  - **B22-1** for each ticket the workflow proposes client, contact and a short summary; client and contact are matched only against that client's PSA contacts (never chosen by the model)
  - **B22-2** an escalation package lists ticket facts, steps tried, related tickets and device facts from read levers, each fact citing its source field; nothing is invented (every fact string is traced to a source field in the eval)
  - **B22-3** fixture-based eval report: fact recall and zero unsupported facts on the gold set, labelled fixture-based; injection tickets are summarised as flagged and never obeyed

**`B-23` Duplicate, related-ticket and outage grouping**
- Why: Fewer duplicate tickets worked twice; a widespread issue is seen as one event.
- Owns: `workflows/duplicates/`, `evals/duplicates/`, `levers/registry.d/ticket.json`, `levers/python/ticket.py`, `workflows/notify/templates/ticket.link.md`, `tests/py/duplicates/test_b23_duplicates.py`, `specs/B-23.md`, `docs/changes/B-23.md`
- Standards: STD-LV, STD-ID, STD-TS
- Acceptance:
  - **B23-1** candidates come only from the same client's open tickets (a ticket from another client is never compared or shown)
  - **B23-2** a `ticket.link` R1 write lever links two tickets in the PSA mock in dry-run with a diff; executing needs the usual approval
  - **B23-3** outage grouping raises one group when N or more tickets for one client share a category and window (N in config of the workflow); precision and recall on the gold duplicate groups are reported fixture-based

**`B-24` SLA breach watch and backlog grooming report**
- Why: The end user waiting longest is seen before the deadline, not after.
- Owns: `workflows/sla/`, `tests/py/sla/test_b24_sla.py`, `specs/B-24.md`, `docs/changes/B-24.md`
- Standards: STD-PY, STD-TS
- Acceptance:
  - **B24-1** given an `as_of`, the report lists tickets that will breach first response or resolution within the next N hours per the SLA matrix in fixtures/psa/, per client
  - **B24-2** backlog grooming lists tickets waiting on client or vendor longer than the threshold, with a suggested follow-up draft (never sent)
  - **B24-3** every count in the report reconciles to the ticket fixtures (validator in the test)

**`B-25` Draft replies with KB citations and closure follow-up drafts**
- Why: Faster first response for the end user, without the Air Canada failure mode (AIR-4).
- Owns: `workflows/replies/`, `evals/replies/`, `tests/py/replies/test_b25_replies.py`, `specs/B-25.md`, `docs/changes/B-25.md`
- Standards: STD-SC, STD-TS, STD-DC
- Acceptance:
  - **B25-1** every sentence of a draft reply cites a KB article id from the same client (via kb.search); with no source the workflow returns `no draft: no source article` instead of guessing
  - **B25-2** closure follow-up drafts confirm the fix in plain words and offer the way back; both kinds start with the draft label and are never sent by code (HO-9)
  - **B25-3** eval: citation coverage 100% and zero cross-client citations on the gold set, labelled fixture-based

**`B-26` Drift fixes: single proposal definitions and TenantBaseline canonical ids**
- Why: Small fixes from the drift table that later waves would otherwise trip over.
- Owns: `workflows/triage/proposal.py`, `levers/powershell/TenantBaseline/TenantBaseline.config.json`, `levers/powershell/TenantBaseline/TenantBaseline.psd1`, `tests/py/levers/test_b26_fix_levers.py`, `specs/B-26.md`, `docs/changes/B-26.md`
- Standards: STD-PR, STD-ID, STD-PS
- Acceptance:
  - **B26-1** triage imports `proposal_id`, `Source` and the timestamp helper from core.queue (DR-01); the proposal contract test is unchanged
  - **B26-2** TenantBaseline accepts `-Tenant contoso-dental` and keeps `contoso` and `clean` as aliases (DR-05); the demo command still works
  - **B26-3** every fix lever named in TenantBaseline.config.json is either registered or listed in an explicit `planned` list (DR-10); the module manifest declares PowerShell 7.4 (DR-09); SB-1 to SB-4 pass

**`B-27` mypy strict across workflows, evals and ui (code side of DR-06)**
- Why: Lets the owner widen mypy `files` without breaking CI.
- Owns: `workflows/triage/rules.py`, `workflows/triage/tickets.py`, `workflows/triage/corrections.py`, `evals/triage/report.py`, `evals/injection/report.py`, `ui/app.py`, `specs/B-27.md`, `docs/changes/B-27.md`
- Standards: STD-PY
- Acceptance:
  - **B27-1** `uv run mypy --strict workflows evals ui` reports no errors
  - **B27-2** no behaviour change: tests/phase1 and the demo smoke test pass unchanged

**`B-89` Entra sign-in for approvers (design and mock token validation)**
- Why: An approval is a real person's act, proven, as auditors expect. Pulled from W9 to W2 so no R2 or R3 approval rests on a picked name (D-024, D6-05).
- Owns: `core/auth/`, `tests/py/auth/test_b89_auth.py`, `specs/B-89.md`, `docs/changes/B-89.md`
- Standards: STD-ID, STD-SC
- Acceptance:
  - **B89-1** approval decisions require a validated token (issuer, audience, expiry, signature against a test key); the demo picker remains only behind an explicit `--demo` flag
  - **B89-2** the approval record carries the authentication method claim and session id
  - **B89-3** an unauthenticated or wrong-audience POST cannot decide (test)
<!-- gen:items:end -->

**Exit steps (wave definition of done).**
- W2-X1: Fold every docs/changes/B-nn.md of the wave into docs/DECISIONS.md, docs/COVERAGE.md, CHANGELOG.md and docs/RUNBOOKS.md (one PR, `tools/fold_changes.py` once B-09 exists; by hand before).
- W2-X2: Update `repo_status` in map/inventory.json and `implemented_in`/`evidence` in map/controls.json for every id the wave touched; a control moves to built only with a named passing test.
- W2-X3: All suites green locally and in CI; map integrity test (B-06) green; demo smoke test (B-10) green.
- W2-X4: the owner reviews the wave report (BUILT / MOCKED / NOT DONE / RISKS / HOW TO RUN / WHAT I SHOULD REVIEW) and says yes before the next wave starts.

## W3: Identity lifecycle: one person's access

**Window (estimate):** about 3 weeks  
**Items:** 15 (5 S, 10 M, 0 L)

**Goal.** Automate the account work that most often decides whether one person can work today (joiners, movers, leavers, password and MFA help, lockouts) as PowerShell levers through the bridge, each dry-run first, approved by a lead, verified, reversible where possible, and announced to the person.

**Entry steps (owner or the MSP).**
- W3-E1: the owner applies: a second synthetic lead in config/identities.json (dual approval for R3), the Pester 5 / PSScriptAnalyzer install decision (OQ-11) or confirms plain-script tests continue, mypy `files` += adapters, levers/python.

| Id | Title | Size | Inventory | Controls | Depends on |
|---|---|---|---|---|---|
| `B-28` | Runner: idempotency enforcement, per-client lock, audit v2 fields, R3 dual approval | M | W-TOOL-01, W-ONB-02, W-EP-08 | C-18, C-29, C-06, C-07, C-08 | B-16, B-17, B-89 |
| `B-29` | IdentityOps: revoke sessions, enable (undo of disable), mover property changes | M | W-ONB-08, W-SEC-04, W-ONB-16 | C-05, C-06, C-30, C-33, C-35 | B-28, B-16, B-19 |
| `B-30` | Password reset and Temporary Access Pass with out-of-band delivery | M | W-IDM-01, W-ONB-05 | C-10, C-30, C-06, C-07, C-11 | B-28, B-16, B-19 |
| `B-31` | LicenseOps: assign and remove from free stock only | M | W-ONB-03, W-ONB-11, W-VND-02 | C-05, C-06, C-32, C-35 | B-28, B-16, B-19 |
| `B-32` | GroupOps: group membership with privileged-group refusal | M | W-ONB-04, W-ONB-16, W-IDM-07 | C-05, C-06, C-32, C-01 | B-28, B-16, B-19 |
| `B-33` | MailboxOps and OneDrive transfer | M | W-M365-01, W-M365-02, W-M365-09, W-ONB-09, W-ONB-10 | C-05, C-06, C-35, C-25 | B-28, B-16, B-19 |
| `B-34` | Requester authorization check and authorized contacts | S | W-ONB-01, W-KB-06, W-IDM-04 | C-30, C-04, C-27 | B-28, B-18, B-14 |
| `B-35` | Onboarding change plan | M | W-ONB-01, W-ONB-02, W-ONB-07 | C-05, C-06, C-07, C-29, C-35 | B-29, B-30, B-31, B-32, B-33, B-34 |
| `B-36` | Offboarding change plan with completion proof | M | W-ONB-08, W-ONB-09, W-ONB-10, W-ONB-11, W-ONB-13, W-ONB-14 | C-05, C-06, C-08, C-33, C-35 | B-29, B-31, B-32, B-33 |
| `B-37` | Fact packs for human-only identity decisions | S | W-ONB-15, W-IDM-04, W-IDM-06, W-IDM-07 | C-20, C-27, C-42 | B-19 |
| `B-38` | Guests, stale accounts and baseline-sourced proposals | S | W-ONB-17, W-IDM-11 | C-30, C-05, C-32 | B-29, B-40 |
| `B-39` | Sign-in failure and lockout investigation | M | W-IDM-03 | C-20, C-27, C-12 | B-19, B-14 |
| `B-40` | TenantBaseline: MFA and SSPR coverage, break-glass sign-in watch | S | W-IDM-13, W-IDM-08 | C-21, C-20 | - |
| `B-41` | Rollback from recorded before-state | S | W-GOV-04, W-CMP-04 | C-33, C-31, C-08 | B-29 |
| `B-68` | Backup adapter mock, daily job review and failed-backup triage | M | W-BDR-01, W-BDR-02 | C-27, C-21, C-05 | B-18, B-14 |

<!-- gen:items:start -->
**`B-28` Runner: idempotency enforcement, per-client lock, audit v2 fields, R3 dual approval**
- Why: The runner rules that identity changes at scale depend on.
- Owns: `core/levers/runner.py`, `core/levers/models.py`, `tests/py/levers/test_b28_runner3.py`, `specs/B-28.md`, `docs/changes/B-28.md`
- Standards: STD-LV, STD-AU, STD-PY, STD-TS
- Acceptance:
  - **B28-1** a second execute whose idempotency key already has an `applied: true` record not authorised by this approval is denied and audited (STD-LV-6a)
  - **B28-2** executes for two different clients run concurrently; two for one client serialise (SL-05); a test proves both
  - **B28-3** an R3 lever executes only with two approvals from two different leads, neither the requester, both scoped to the client (HO-3); a single approval is denied and audited
  - **B28-4** every record the runner writes carries request_id, actor_kind and lever_version
  - **B28-5** an `irreversible` lever executes only with an approval younger than 24 hours, and the approval page shows `no undo` (STD-LV-4); the runner owns this rule so device and mailbox families in later waves do not need to edit runner.py
  - **B28-6** an R2 or R3 approval is accepted only from an approver authenticated by the B-89 token validator; the demo identity picker works only behind `--demo` and its approvals are marked `demo` in the audit (D6-05, D-024)
  - **B28-7** the approver minimum per risk class (R2: 1, R3: 2 distinct humans, never the requester, never an agent) can be raised per lever or per client from the client record, never lowered; a lowered value fails the load (D6-05)
  - **B28-8** levers declaring `verification: "requester+contact"` (MFA reset, TAP, authentication-method or contact-detail changes) need two verification records: callback-on-file (number source recorded, never the number) and confirmation by the client's authorized contact; a target holding a privileged directory role is refused (D6-06)

**`B-29` IdentityOps: revoke sessions, enable (undo of disable), mover property changes**
- Why: The first real offboarding and mover steps, each reversible.
- Owns: `levers/powershell/IdentityOps/`, `levers/registry.d/identity.json`, `workflows/notify/templates/user.revoke-sessions.md`, `workflows/notify/templates/user.enable.md`, `workflows/notify/templates/user.set-properties.md`, `fixtures/tenant/contoso-dental/sessions.json`, `fixtures/tenant/fabrikam-capital/sessions.json`, `specs/B-29.md`, `docs/changes/B-29.md`
- Standards: STD-LV, STD-PS, STD-XL, STD-TS
- Acceptance:
  - **B29-1** `user.revoke-sessions` (R2, `graph_scopes: [User.RevokeSessions.All]`) dry-runs a diff and its README states the documented lag and that it does not apply to guest users
  - **B29-2** `user.enable` (R2) is the registered `undo` of `user.disable`; disable then enable returns the fixture to byte-identical state
  - **B29-3** `user.set-properties` changes only department, jobTitle and manager (enum of fields); idempotent; Pester or plain-script tests per STD-PS-9 cover dry-run, execute, idempotency and a scope denial

**`B-30` Password reset and Temporary Access Pass with out-of-band delivery**
- Why: Password help is the most common lockout fix; the secret never touches the AI.
- Owns: `levers/powershell/CredentialOps/`, `levers/registry.d/credential.json`, `core/levers/oob.py`, `workflows/notify/templates/user.reset-password.md`, `workflows/notify/templates/user.new-tap.md`, `tests/py/levers/test_b30_oob.py`, `specs/B-30.md`, `docs/changes/B-30.md`
- Standards: STD-LV, STD-SC, STD-AU, STD-PS
- Acceptance:
  - **B30-1** `user.reset-password` and `user.new-tap` are R3 and need requester verification; the generated value goes only to the out-of-band channel (mock: a file under .tmp/oob/ readable by the requesting technician) and never into the lever result, the queue, the audit, a notice or a prompt
  - **B30-2** a sweep test runs both levers end to end and finds no secret-shaped value in any audit record, proposal, result object or log
  - **B30-3** the audit records that a credential was issued (type, expiry, target id) and nothing else
  - **B30-4** both levers declare `verification: "requester+contact"` (B28-8) and refuse targets holding a privileged directory role; a TAP is single-use with the shortest lifetime the tenant policy allows (D6-06)

**`B-31` LicenseOps: assign and remove from free stock only**
- Why: New hires get licensed on day one without anyone spending the client's money.
- Owns: `levers/powershell/LicenseOps/`, `levers/registry.d/license.json`, `workflows/notify/templates/license.add.md`, `workflows/notify/templates/license.remove.md`, `fixtures/tenant/contoso-dental/licenses.json`, `fixtures/tenant/fabrikam-capital/licenses.json`, `specs/B-31.md`, `docs/changes/B-31.md`
- Standards: STD-LV, STD-PS, STD-FX
- Acceptance:
  - **B31-1** `license.add` (R1) succeeds in dry-run only when the SKU has a free seat; with none it returns `no free seat: a purchase needs the client's consent (W-VND-02)` and proposes nothing
  - **B31-2** `license.remove` (R2) after the retention window only; the diff shows the SKU and the date the window ended
  - **B31-3** no lever named license.purchase or similar can load (never-automate gate)

**`B-32` GroupOps: group membership with privileged-group refusal**
- Why: Right access on day one and on a move, never admin rights by automation.
- Owns: `levers/powershell/GroupOps/`, `levers/registry.d/group.json`, `workflows/notify/templates/group.add-member.md`, `workflows/notify/templates/group.remove-member.md`, `fixtures/tenant/contoso-dental/groups.json`, `fixtures/tenant/fabrikam-capital/groups.json`, `specs/B-32.md`, `docs/changes/B-32.md`
- Standards: STD-LV, STD-PS, STD-FX
- Acceptance:
  - **B32-1** `group.add-member` and `group.remove-member` (R2 when the group grants data access, R1 for distribution only, from a group attribute in the fixture)
  - **B32-2** a role-assignable group or a group named in the client's privileged list is refused in dry-run with the W-IDM-07 reason
  - **B32-3** each change is idempotent and has the other as its undo

**`B-33` MailboxOps and OneDrive transfer**
- Why: The mailbox half of joiners and leavers, which technicians do by hand many times a month.
- Owns: `levers/powershell/MailboxOps/`, `levers/registry.d/mailbox.json`, `workflows/notify/templates/mailbox.add-dl-member.md`, `workflows/notify/templates/mailbox.clear-auto-reply.md`, `workflows/notify/templates/mailbox.convert-shared.md`, `workflows/notify/templates/mailbox.enable-archive.md`, `workflows/notify/templates/mailbox.grant-full-access.md`, `workflows/notify/templates/mailbox.grant-onedrive-manager.md`, `workflows/notify/templates/mailbox.grant-send-as.md`, `workflows/notify/templates/mailbox.remove-dl-member.md`, `workflows/notify/templates/mailbox.revoke-full-access.md`, `workflows/notify/templates/mailbox.revoke-onedrive-manager.md`, `workflows/notify/templates/mailbox.revoke-send-as.md`, `workflows/notify/templates/mailbox.set-auto-reply.md`, `fixtures/tenant/contoso-dental/mailboxes.json`, `fixtures/tenant/fabrikam-capital/mailboxes.json`, `specs/B-33.md`, `docs/changes/B-33.md`
- Standards: STD-LV, STD-PS, STD-FX
- Acceptance:
  - **B33-1** levers for DL membership, Full Access and Send As grants, convert to shared, auto-reply, archive enable, and a time-bound manager grant to a leaver's OneDrive; each with dry-run diff, undo where one exists, and a template
  - **B33-2** external forwarding is not offered as a lever (it is flagged by W-M365-05 instead); a test asserts no registered lever sets forwarding to an external domain
  - **B33-3** SOURCES.md entries mark which shapes are Exchange Online PowerShell rather than Graph and which are UNVERIFIED

**`B-34` Requester authorization check and authorized contacts**
- Why: Stops an outsider from requesting a new account or access in someone else's name.
- Owns: `levers/registry.d/contact.json`, `levers/python/contact.py`, `fixtures/psa/contacts-authorized.json`, `tests/py/levers/test_b34_contacts.py`, `specs/B-34.md`, `docs/changes/B-34.md`
- Standards: STD-LV, STD-ID, STD-TS
- Acceptance:
  - **B34-1** `contact.check` (R0) answers whether a named requester may request a given change type for a client, from that client's authorized-contacts list only
  - **B34-2** an unknown requester returns `not authorized: confirm with the client's primary contact`, never a guess; another client's list is never read
  - **B34-3** the result is shown on the approval page as evidence for the verification record; it never sets verification by itself (verification stays a human act, W-IDM-04)

**`B-35` Onboarding change plan**
- Why: A new hire can work on day one, and the request is proven to be legitimate.
- Owns: `levers/powershell/Provisioning/`, `levers/registry.d/provisioning.json`, `workflows/onboarding/`, `workflows/notify/templates/user.new.md`, `tests/py/onboarding/test_b35_onboarding.py`, `specs/B-35.md`, `docs/changes/B-35.md`
- Standards: STD-LV, STD-PR, STD-PS, STD-TS
- Acceptance:
  - **B35-1** from a structured new-hire request (form fields, never free text) the workflow builds one change plan: `user.new` (R3, dual approval), licenses, groups, mailbox, TAP; each step is a dry-run proposal with its diff
  - **B35-2** the plan is refused when `contact.check` says the requester is not authorized
  - **B35-3** a welcome and manager-handoff draft is produced after the plan executes (never sent); a plan re-run after partial execution proposes only the remaining steps (idempotent)

**`B-36` Offboarding change plan with completion proof**
- Why: A leaver's access is provably gone, which protects the client's patients and customers.
- Owns: `workflows/offboarding/`, `tests/py/offboarding/test_b36_offboarding.py`, `specs/B-36.md`, `docs/changes/B-36.md`
- Standards: STD-PR, STD-AU, STD-TS
- Acceptance:
  - **B36-1** the plan orders block sign-in, revoke sessions, mailbox conversion and auto-reply, OneDrive grant, group removal, and license removal after the retention window; device steps are listed as `manual until W6` and line-of-business apps as a checklist from the client record
  - **B36-2** after execution a read-only verify step checks every target state and writes a completion record; any step not in its target state is listed, not hidden (W-ONB-14)
  - **B36-3** the completion record is part of the client's evidence (it reconciles with the audit records of the plan)

**`B-37` Fact packs for human-only identity decisions**
- Why: Humans decide the hardest cases faster, with facts in front of them, and no bot in the loop.
- Owns: `workflows/factpack/`, `docs/runbooks/urgent-termination.md`, `docs/runbooks/caller-verification.md`, `tests/py/factpack/test_b37_factpack.py`, `specs/B-37.md`, `docs/changes/B-37.md`
- Standards: STD-DC, STD-ID, STD-TS
- Acceptance:
  - **B37-1** `python -m workflows.factpack <kind> --client <id> --target <id>` assembles read-only facts (accounts, sessions, devices, roles, CA policies) for one person or one policy and registers no lever and proposes nothing
  - **B37-2** the urgent-termination runbook keeps timing and conduct with named humans; the caller-verification runbook describes the callback-on-file method the approval page records
  - **B37-3** a test asserts the fact pack module imports no runner execute path

**`B-38` Guests, stale accounts and baseline-sourced proposals**
- Why: Dormant accounts stop being an open door, without bulk changes nobody reviewed.
- Owns: `workflows/baseline_proposals/`, `fixtures/tenant/contoso-dental/guests.json`, `tests/py/baseline/test_b38_baseline_proposals.py`, `specs/B-38.md`, `docs/changes/B-38.md`
- Standards: STD-PR, STD-LV, STD-TS
- Acceptance:
  - **B38-1** from findings.json (TenantBaseline) and guest fixtures, the workflow proposes `user.disable` for stale members and expired guests, each with `verification.method: finding-reference` and the finding id
  - **B38-2** break-glass accounts are never proposed (pattern from the baseline config)
  - **B38-3** at most N proposals per client per run (blast-radius cap from the workflow config), the rest listed as deferred

**`B-39` Sign-in failure and lockout investigation**
- Why: The 'why can't I sign in' call is answered in minutes.
- Owns: `levers/registry.d/signin.json`, `levers/python/signin.py`, `fixtures/tenant/contoso-dental/signins.json`, `fixtures/tenant/fabrikam-capital/signins.json`, `workflows/lockout/`, `tests/py/lockout/test_b39_lockout.py`, `specs/B-39.md`, `docs/changes/B-39.md`
- Standards: STD-LV, STD-FX, STD-SC
- Acceptance:
  - **B39-1** `signins.list` (R0) returns one user's recent sign-ins from the client's mock; read results are never written to the audit
  - **B39-2** the lockout summary maps failure codes to plain causes from a cited table (Microsoft Learn sign-in error codes, marked UNVERIFIED per code where not checked) and suggests the right lever, never executes
  - **B39-3** IP addresses and locations appear only in the technician's view, not in prompts (DC-3 minimum necessary)

**`B-40` TenantBaseline: MFA and SSPR coverage, break-glass sign-in watch**
- Why: Coverage gaps and break-glass use are found before an attacker finds them.
- Owns: `levers/powershell/TenantBaseline/TenantBaseline.psm1`, `tests/sliceb/Test-SliceB.ps1`, `fixtures/graph/contoso/userRegistrationDetails.json`, `specs/B-40.md`, `docs/changes/B-40.md`
- Standards: STD-PS, STD-FX, STD-TS
- Acceptance:
  - **B40-1** new checks: SSPR registration coverage per client and any sign-in by a break-glass account in the window (high severity)
  - **B40-2** SB-1 holds for the new checks: exactly the seeded problems on Contoso, none on the clean fixture; SB-2 reconciliation covers the new counts
  - **B40-3** the demo's 14-finding output is unchanged unless the demo script is updated in the same PR

**`B-41` Rollback from recorded before-state**
- Why: When an automation is wrong, the person is put back first (EU-8).
- Owns: `workflows/rollback/`, `tests/py/rollback/test_b41_rollback.py`, `specs/B-41.md`, `docs/changes/B-41.md`
- Standards: STD-PR, STD-AU, STD-TS
- Acceptance:
  - **B41-1** given an applied audit record whose lever has an `undo`, the workflow builds the undo proposal from the recorded before-state, in dry-run, for normal approval (IR-3)
  - **B41-2** for a lever without `undo` it prints the manual undo steps from the lever README and proposes nothing
  - **B41-3** a full test: disable, then rollback proposal, approval, execute; the fixture returns to byte-identical state and both actions are in the audit

**`B-68` Backup adapter mock, daily job review and failed-backup triage**
- Why: A failed backup is fixed the same day, not discovered during a restore. Pulled from W6 to W3 because it is the highest-leverage chain and the MSP sells backup (D6-24).
- Owns: `adapters/backup/`, `fixtures/backup/`, `workflows/backup_review/`, `levers/registry.d/backup.json`, `levers/python/backup.py`, `workflows/notify/templates/backup.retry-job.md`, `tests/py/backup/test_b68_backup.py`, `specs/B-68.md`, `docs/changes/B-68.md`
- Standards: STD-ER, STD-FX, STD-LV
- Acceptance:
  - **B68-1** daily review lists failed, missed and long-running jobs per client with the reason from the job record
  - **B68-2** `backup.retry-job` (R2) dry-runs and needs approval; repeated failures are grouped into one ticket draft
  - **B68-3** counts reconcile; job data of another client is never shown
  - **B68-4** the backup mock models image-based appliance and agent jobs (with boot-check screenshot result) and Microsoft 365 SaaS backup jobs as two job types, field names marked UNVERIFIED; the review is read-only and `backup.retry-job` is the only write (D6-24)
<!-- gen:items:end -->

**Exit steps (wave definition of done).**
- W3-X1: Fold every docs/changes/B-nn.md of the wave into docs/DECISIONS.md, docs/COVERAGE.md, CHANGELOG.md and docs/RUNBOOKS.md (one PR, `tools/fold_changes.py` once B-09 exists; by hand before).
- W3-X2: Update `repo_status` in map/inventory.json and `implemented_in`/`evidence` in map/controls.json for every id the wave touched; a control moves to built only with a named passing test.
- W3-X3: All suites green locally and in CI; map integrity test (B-06) green; demo smoke test (B-10) green.
- W3-X4: the owner reviews the wave report (BUILT / MOCKED / NOT DONE / RISKS / HOW TO RUN / WHAT I SHOULD REVIEW) and says yes before the next wave starts.
- W3-X5: Move core/levers/tenant.py to adapters/graph/mock_state.py in one PR once every Graph lever reads state through the adapter (move M-04 in 04-repo-organization.md).

## W4: Security monitoring and compliance evidence

**Window (estimate):** about 3 weeks  
**Items:** 13 (3 S, 10 M, 0 L)

**Goal.** Protect the client business: group and enrich alerts, contain account compromise with a reviewed plan, watch drift and expiries, and produce the evidence that HIPAA business associates, Safeguards service providers and the MSP's own SOC 2 audit need.

**Entry steps (owner or the MSP).**
- W4-E1: the owner confirms whether W4 waits for answers to GQ-01 (compliance owner) and GQ-11 (SOC 2 scope); evidence packs are built either way but labelled 'mapping, confirm with counsel'.

| Id | Title | Size | Inventory | Controls | Depends on |
|---|---|---|---|---|---|
| `B-42` | Runner: blast-radius caps and per-client audit chains | M | W-TOOL-01, W-CMP-01 | C-32, C-39, C-27, C-08 | B-28 |
| `B-43` | Security alert adapter mock, grouping and after-hours summary | M | W-SEC-01, W-SD-12, W-EP-02 | C-12, C-13, C-27, C-41 | B-18 |
| `B-44` | Alert enrichment and risky sign-in review | M | W-SEC-02, W-IDM-05, W-SD-07 | C-20, C-27, C-12 | B-43 |
| `B-45` | Phishing triage, message trace and quarantine release | M | W-SEC-03, W-M365-03, W-M365-04 | C-12, C-13, C-14, C-05, C-06 | B-43, B-16 |
| `B-46` | Business email compromise containment plan and inbox-rule audit | M | W-SEC-04, W-M365-05 | C-05, C-06, C-07, C-30, C-32, C-35 | B-45 |
| `B-47` | Vulnerability, advisory and emergency-patch relevance | M | W-SEC-06, W-SEC-08, W-PAT-05 | C-21, C-27 | - |
| `B-48` | Incident and recovery fact packs and timeline export | S | W-SEC-07, W-BDR-07, W-SEC-09, W-VND-06 | C-34, C-08, C-27 | B-42 |
| `B-49` | Access reviews: tenant admins and agent/technician identities | S | W-IDM-09, W-GOV-03 | C-38, C-03, C-08 | B-42, B-28 |
| `B-50` | Conditional Access and baseline drift over time | S | W-IDM-06, W-M365-11 | C-21, C-20 | - |
| `B-51` | SOC 2 evidence bundle and change records | M | W-CMP-01, W-CMP-04, W-CMP-05, W-CMP-07 | C-08, C-37, C-38, C-39 | B-42, B-49 |
| `B-52` | HIPAA and FTC Safeguards evidence packs per client, BAA and vendor tracking | M | W-CMP-02, W-CMP-03, W-CMP-06 | C-25, C-43, C-45 | B-51 |
| `B-53` | Oversharing, Copilot readiness and labels/DLP assessment | M | W-M365-07, W-PRJ-04, W-M365-08 | C-25, C-21, C-20 | - |
| `B-54` | Expiry watch: DMARC/SPF/DKIM, app secrets, TLS certificates, GDAP relationships | M | W-M365-10, W-IDM-12, W-VND-05, W-IDM-10 | C-38, C-20, C-21 | - |

<!-- gen:items:start -->
**`B-42` Runner: blast-radius caps and per-client audit chains**
- Why: One runaway or one mistake cannot spread across 300 tenants.
- Owns: `core/levers/runner.py`, `core/levers/caps.py`, `core/audit/router.py`, `core/levers/__main__.py`, `core/queue/store.py`, `ui/app.py`, `core/levers/models.py`, `levers/registry.d/identity.json`, `levers/registry.json`, `schemas/lever-registry.schema.json`, `tests/py/levers/test_b42_caps.py`, `specs/B-42.md`, `docs/changes/B-42.md`
- Standards: STD-LV, STD-AU, STD-ID, STD-TS
- Acceptance:
  - **B42-1** each write lever's caps (targets per run, executes per client per hour, clients per day) come from the registry; the N+1th execute in a window is denied and audited (HO-6)
  - **B42-2** audit records go to `audit/<client>.jsonl` plus `audit/_msp.jsonl` for MSP-level events (SL-01 step 1); each chain verifies alone; a client's chain exported alone reveals no other client
  - **B42-3** a cross-process file lock guards append (SL-01 step 2); the UI and CLI construct the router, not a single log
  - **B42-4** write levers flagged `window: business-hours` or `window: maintenance` are refused outside the window held on the client record (business hours, time zone, maintenance window); a client with no window defined is refused, not defaulted; an approval may record a named override (D6-08, RQ-13)
  - **B42-5** pre-authorized containment: `user.disable`, `user.revoke-sessions` and device isolate may execute on one on-call approval when the client record sets `containment_preauthorized: true`; the runner opens a second-review item due by the next business day, an overdue review is audited and alerts; `irreversible` levers never use this path (D6-08)

**`B-43` Security alert adapter mock, grouping and after-hours summary**
- Why: On-call engineers wake up to five grouped events, not fifty alerts.
- Owns: `adapters/alerts/`, `fixtures/alerts/`, `workflows/alerts/`, `evals/alerts/`, `tests/py/alerts/test_b43_alerts.py`, `specs/B-43.md`, `docs/changes/B-43.md`
- Standards: STD-ER, STD-FX, STD-SC, STD-TS
- Acceptance:
  - **B43-1** alerts are grouped per client by entity and time window; a group never mixes clients
  - **B43-2** the on-call summary lists groups by severity with the facts used and the read levers that would enrich them; alert text is wrapped untrusted
  - **B43-3** fixture-based grouping precision and recall against gold groups; RMM agent and Defender sensor health alerts form their own group type
  - **B43-4** alert sources are modelled as types, not products: EDR/MDR, Microsoft 365 identity threat detection, SIEM, RMM monitors and backup; when an external SOC already owns an alert, the group carries its case id and the summary says the SOC is the responder (D6-04)
  - **B43-5** SaaS-monitoring alerts (MP-20; vendor possibly SaaS Alerts, UNVERIFIED) are one more source type through the same grouping path

**`B-44` Alert enrichment and risky sign-in review**
- Why: The analyst sees the whole picture in one place.
- Owns: `workflows/enrichment/`, `levers/registry.d/risk.json`, `levers/python/risk.py`, `fixtures/tenant/contoso-dental/risky-users.json`, `tests/py/enrichment/test_b44_enrichment.py`, `specs/B-44.md`, `docs/changes/B-44.md`
- Standards: STD-LV, STD-FX, STD-SC
- Acceptance:
  - **B44-1** an enrichment pack adds user, device and recent sign-in facts through read levers only, each fact citing its lever and field
  - **B44-2** `risk.list-users` (R0) reads the mock riskyUsers shape (Entra ID P2 dependency noted UNVERIFIED per client); the review lists recommended levers, never executes
  - **B44-3** no read result enters the audit log; packs are built under one client

**`B-45` Phishing triage, message trace and quarantine release**
- Why: The user who reports a phish gets an answer, and the next user is protected.
- Owns: `workflows/phishing/`, `levers/powershell/MailFlowOps/`, `levers/registry.d/mailflow.json`, `fixtures/mailflow/`, `evals/phishing/`, `workflows/notify/templates/quarantine.release.md`, `specs/B-45.md`, `docs/changes/B-45.md`
- Standards: STD-LV, STD-SC, STD-TS, STD-FX
- Acceptance:
  - **B45-1** a reported message is analysed from headers and URLs as data only (no URL is fetched, no attachment opened); the verdict draft cites the header fields used
  - **B45-2** `message.trace` (R0) and `quarantine.release` (R2) levers; release is refused for messages with a high-confidence phish or malware verdict
  - **B45-3** the injection corpus emails (hidden instructions) are flagged and get no lever; verdict accuracy reported fixture-based
  - **B45-4** the user-reported message fixture is shaped like an INKY phish report (MP-21; cited, unverified fields marked UNVERIFIED) beside the Defender shape, and both take the same verdict path

**`B-46` Business email compromise containment plan and inbox-rule audit**
- Why: A compromised mailbox is contained in minutes, with a person approving each step.
- Owns: `workflows/bec/`, `levers/registry.d/inboxrule.json`, `levers/python/inboxrule.py`, `fixtures/tenant/contoso-dental/inbox-rules.json`, `fixtures/tenant/fabrikam-capital/inbox-rules.json`, `workflows/notify/templates/inboxrule.disable.md`, `tests/py/bec/test_b46_bec.py`, `specs/B-46.md`, `docs/changes/B-46.md`
- Standards: STD-PR, STD-LV, STD-TS
- Acceptance:
  - **B46-1** `inboxrule.list` (R0) flags rules that forward externally, delete, or move to RSS or obscure folders; `inboxrule.disable` (R2, undo `inboxrule.enable`) turns one rule off
  - **B46-2** the containment plan for one user proposes, in order: block sign-in, revoke sessions, reset MFA, disable the flagged rules; each a dry-run proposal needing approval; one target per plan
  - **B46-3** the plan's evidence (rules found, times) goes into an incident timeline (B-48 format) and never into a prompt

**`B-47` Vulnerability, advisory and emergency-patch relevance**
- Why: The one exploited bug that matters to this client is found first.
- Owns: `workflows/advisories/`, `fixtures/advisories/`, `tests/py/advisories/test_b47_advisories.py`, `specs/B-47.md`, `docs/changes/B-47.md`
- Standards: STD-FX, STD-DC, STD-TS
- Acceptance:
  - **B47-1** a fixture shaped like the CISA Known Exploited Vulnerabilities JSON feed (cited, shape verified on read date) is matched to each client's synthetic software inventory; output lists affected clients and devices per CVE
  - **B47-2** prioritisation uses KEV presence, exposure and asset criticality, each shown; no number is invented (counts reconcile to the fixture)
  - **B47-3** the emergency-patch list is a report and proposed change windows only; nothing is deployed
  - **B47-4** scanner and penetration-test findings come from fixtures shaped like a Tenable Nessus export and a Vonahi vPenTest findings report (MP-25, MP-26; cited, unverified fields marked UNVERIFIED) and are joined to the KEV match by CVE

**`B-48` Incident and recovery fact packs and timeline export**
- Why: The people who must decide get a trustworthy timeline fast.
- Owns: `workflows/timeline/`, `tests/py/timeline/test_b48_timeline.py`, `specs/B-48.md`, `docs/changes/B-48.md`
- Standards: STD-AU, STD-DC, STD-TS
- Acceptance:
  - **B48-1** exports one client's incident timeline from its audit chain, alerts and ticket ids (no ticket text), verified chain first
  - **B48-2** fact packs for breach determination, recovery-point choice, firewall rule and DNS changes list facts only; they register no lever
  - **B48-3** the export states on its first line that declaration and notification decisions belong to the client and counsel
  - **B48-4** firewall and SASE events in the timeline come from a fixture shaped like a FortiGate event log (MP-27, MP-28; cited); rule changes stay human (NN-05)

**`B-49` Access reviews: tenant admins and agent/technician identities**
- Why: Who can touch each client is reviewed, as SOC 2 CC6.2 and HIPAA 164.308(a)(4) expect.
- Owns: `workflows/access_review/`, `tests/py/access_review/test_b49_access_review.py`, `specs/B-49.md`, `docs/changes/B-49.md`
- Standards: STD-ID, STD-AU, STD-TS
- Acceptance:
  - **B49-1** quarterly per-client export of directory role members (from Graph mock) and of every repo identity with role and client list, dated and SHA-256 hashed
  - **B49-2** each row has a lead decision field (keep, remove, investigate); the export is re-verifiable from its hash
  - **B49-3** agents with any execute capability or with more clients than their workflow needs are flagged

**`B-50` Conditional Access and baseline drift over time**
- Why: A silently weakened policy is noticed the next morning.
- Owns: `levers/powershell/TenantBaseline/`, `tests/sliceb/`, `specs/B-50.md`, `docs/changes/B-50.md`
- Standards: STD-PS, STD-TS
- Acceptance:
  - **B50-1** `-CompareTo <previous findings.json>` reports new, resolved and unchanged findings and any Conditional Access policy whose state or assignments changed
  - **B50-2** drift output is a report only; CA changes are never proposed as levers (never-automate)
  - **B50-3** SB-1 and SB-2 still pass; the demo command is unchanged

**`B-51` SOC 2 evidence bundle and change records**
- Why: Audit evidence is collected every month, not rebuilt the week before the auditor arrives.
- Owns: `workflows/evidence/`, `tests/py/evidence/test_b51_evidence.py`, `specs/B-51.md`, `docs/changes/B-51.md`
- Standards: STD-AU, STD-DC, STD-TS
- Acceptance:
  - **B51-1** a monthly bundle per period: audit verify output per chain, approvals and denials summary, registry snapshot with lever versions, access-review exports, merged PR list from a local git log, all hashed into a manifest
  - **B51-2** re-running for the same period produces the same manifest hash (deterministic, `as_of`)
  - **B51-3** the bundle supports a human's management assertion and says so; it never signs or asserts anything (W-CMP-07)

**`B-52` HIPAA and FTC Safeguards evidence packs per client, BAA and vendor tracking**
- Why: Small regulated clients get the evidence their own obligations need.
- Owns: `workflows/regpacks/`, `fixtures/regpacks/`, `tests/py/regpacks/test_b52_regpacks.py`, `specs/B-52.md`, `docs/changes/B-52.md`
- Standards: STD-DC, STD-FX
- Acceptance:
  - **B52-1** for a dental client, findings and controls are mapped to 45 CFR 164.308/312 items; for a financial client, to 16 CFR 314.4 elements; every mapping line cites the governance map id (BA-n, GLBA-n)
  - **B52-2** a BAA and vendor due-diligence tracker lists each vendor, data classes, contract status and review date (synthetic rows)
  - **B52-3** every page is labelled 'mapping for the client's compliance owner; not legal advice'
  - **B52-4** for an investment-adviser client, findings map to SEC Regulation S-P as amended in 2024 (incident response program, service-provider oversight, customer notice), each mapping marked hedged until checked against the rule text; the HIPAA pack stays for any healthcare client (D6-12)

**`B-53` Oversharing, Copilot readiness and labels/DLP assessment**
- Why: Copilot does not surface the wrong patient file to the wrong employee.
- Owns: `workflows/copilot_readiness/`, `fixtures/sharepoint/`, `tests/py/copilot/test_b53_copilot.py`, `specs/B-53.md`, `docs/changes/B-53.md`
- Standards: STD-FX, STD-DC, STD-TS
- Acceptance:
  - **B53-1** from SharePoint/OneDrive sharing fixtures (Everyone links, external shares, unlabelled sensitive sites) the assessment scores readiness per client with every point traced to a finding
  - **B53-2** label and DLP gaps are reported as recommendations; no policy change is proposed as a lever
  - **B53-3** the score's formula is printed with the report; counts reconcile to the fixture

**`B-54` Expiry watch: DMARC/SPF/DKIM, app secrets, TLS certificates, GDAP relationships**
- Why: Mail stops being spoofable and nothing expires by surprise on a Monday.
- Owns: `workflows/expiry/`, `fixtures/dns/`, `fixtures/partner/`, `tests/py/expiry/test_b54_expiry.py`, `specs/B-54.md`, `docs/changes/B-54.md`
- Standards: STD-FX, STD-TS
- Acceptance:
  - **B54-1** DNS fixtures (no live lookups in tests) are checked for SPF, DKIM and DMARC policy per domain; app-registration secrets and certificates expiring within N days and GDAP relationships expiring or holding Global Administrator are listed per client
  - **B54-2** fixture shapes for Partner Center GDAP are marked UNVERIFIED field by field
  - **B54-3** every reminder is a report row with the date and owner; nothing is renewed by automation
  - **B54-4** DMARC aggregate reports are read from a fixture shaped like the RFC 7489 aggregate XML that EasyDMARC collects (MP-22; cited); pass, fail, policy and alignment are shown per domain
<!-- gen:items:end -->

**Exit steps (wave definition of done).**
- W4-X1: Fold every docs/changes/B-nn.md of the wave into docs/DECISIONS.md, docs/COVERAGE.md, CHANGELOG.md and docs/RUNBOOKS.md (one PR, `tools/fold_changes.py` once B-09 exists; by hand before).
- W4-X2: Update `repo_status` in map/inventory.json and `implemented_in`/`evidence` in map/controls.json for every id the wave touched; a control moves to built only with a named passing test.
- W4-X3: All suites green locally and in CI; map integrity test (B-06) green; demo smoke test (B-10) green.
- W4-X4: the owner reviews the wave report (BUILT / MOCKED / NOT DONE / RISKS / HOW TO RUN / WHAT I SHOULD REVIEW) and says yes before the next wave starts.

## W5: Knowledge and retrieval

**Window (estimate):** about 2 weeks  
**Items:** 6 (1 S, 5 M, 0 L)

**Goal.** Answer technicians' questions from the right client's documents with citations, refuse when there is no source, never leak one client's knowledge into another's answer, and keep PHI and NPI out of prompts by default.

**Entry steps (owner or the MSP).**
- W5-E1: the owner decides whether a vector store dependency is allowed (pgvector or Qdrant need installs); until then retrieval uses a standard-library index behind the same interface.

| Id | Title | Size | Inventory | Controls | Depends on |
|---|---|---|---|---|---|
| `B-55` | Data classes and the pre-prompt redaction gate | M | W-GOV-01, W-SD-01 | C-25, C-15, C-27 | B-21 |
| `B-56` | RAG ingestion with per-client namespaces and vault exclusion | M | W-KB-04, W-KB-07 | C-26, C-12, C-13, C-25 | B-55, B-18 |
| `B-57` | Cited retrieval, refusal and leakage evals | M | W-KB-04 | C-26, C-27, C-41 | B-56 |
| `B-58` | KB drafts from resolved tickets; stale and conflicting article detection | M | W-KB-01, W-KB-05 | C-12, C-25, C-41 | B-57 |
| `B-59` | Client documentation upkeep and runbook linting | S | W-KB-02, W-KB-03 | C-27, C-21 | B-56 |
| `B-60` | Answer drafts: security questionnaires, cyber insurance, project scoping | M | W-CMP-09, W-CMP-08, W-PRJ-06 | C-26, C-45, C-41 | B-57 |

<!-- gen:items:start -->
**`B-55` Data classes and the pre-prompt redaction gate**
- Why: A patient's name in a printer ticket never reaches a model it should not.
- Owns: `core/guard/classify.py`, `core/guard/redact_prompt.py`, `core/gateway/gateway.py`, `evals/redaction/`, `tests/py/guard/test_b55_redaction.py`, `specs/B-55.md`, `docs/changes/B-55.md`
- Standards: STD-SC, STD-AU, STD-TS
- Acceptance:
  - **B55-1** every text passed to the gateway carries a data class (DC-0 to DC-6); unknown text takes the client's industry floor (dental DC-4; financial, legal and accounting DC-5) from the client record (D6-12)
  - **B55-2** PHI- and NPI-shaped strings from the Phase 2 set are replaced by typed placeholders before any prompt; DC-6 shapes block the call
  - **B55-3** redaction eval: leak rate on the synthetic PHI/NPI set reported fixture-based, with the miss list; the gateway refuses a hosted route for DC-4/DC-5 text

**`B-56` RAG ingestion with per-client namespaces and vault exclusion**
- Why: The knowledge base is useful without becoming a cross-client leak or a credential store.
- Owns: `rag/__init__.py`, `rag/ingest/`, `rag/store/`, `fixtures/kb/`, `tests/py/rag/test_b56_ingest.py`, `specs/B-56.md`, `docs/changes/B-56.md`
- Standards: STD-ID, STD-SC, STD-FX, STD-TS
- Acceptance:
  - **B56-1** each client's documents go into that client's namespace plus one MSP-internal namespace; the namespace comes from the ingestion job's client, never from document text
  - **B56-2** documents are scanned with the injection tripwire and classified before indexing; flagged passages are stored with the flag
  - **B56-3** sources tagged as credential vault or containing DC-6 shapes are refused (W-KB-07), proven with canary secrets

**`B-57` Cited retrieval, refusal and leakage evals**
- Why: Technicians get answers they can check, and clients' knowledge stays theirs.
- Owns: `rag/retrieve/`, `levers/registry.d/rag.json`, `evals/rag/`, `tests/py/rag/test_b57_retrieve.py`, `specs/B-57.md`, `docs/changes/B-57.md`
- Standards: STD-LV, STD-ID, STD-TS
- Acceptance:
  - **B57-1** `rag.search` (R0) returns passages with article ids from the caller's client and MSP-internal namespaces only; the filter is applied in the store
  - **B57-2** answers cite every claim; with no passage above the threshold the answer is `no source found`
  - **B57-3** leakage eval: canary strings planted in client B never appear for client A across the whole question set (must be 0); groundedness and refusal rates reported fixture-based

**`B-58` KB drafts from resolved tickets; stale and conflicting article detection**
- Why: Knowledge from one fix helps the next person with the same problem.
- Owns: `workflows/kb_drafts/`, `evals/kb_drafts/`, `tests/py/kb/test_b58_kb_drafts.py`, `specs/B-58.md`, `docs/changes/B-58.md`
- Standards: STD-DC, STD-TS
- Acceptance:
  - **B58-1** a resolved ticket produces an article draft with steps and the ticket id as source; PHI placeholders stay placeholders
  - **B58-2** articles older than N days or contradicting another article on the same topic (same client) are listed with both ids
  - **B58-3** drafts are never published by code; eval reports step coverage fixture-based

**`B-59` Client documentation upkeep and runbook linting**
- Why: Documentation that matches reality, so the 2 a.m. engineer is not misled.
- Owns: `workflows/doc_upkeep/`, `tools/lint_runbook.py`, `tests/py/kb/test_b59_doc_upkeep.py`, `specs/B-59.md`, `docs/changes/B-59.md`
- Standards: STD-DC, STD-TS
- Acceptance:
  - **B59-1** compares a client's documentation fixture with observed adapter state (devices, contacts, licenses) and proposes doc updates as drafts
  - **B59-2** the runbook linter checks required sections (purpose, prerequisites, steps, rollback, verification, owner) and fails a runbook missing any
  - **B59-3** docs/RUNBOOKS.md passes the linter or each gap is listed

**`B-60` Answer drafts: security questionnaires, cyber insurance, project scoping**
- Why: Hours of copy-paste per questionnaire become a review of cited drafts.
- Owns: `workflows/questionnaires/`, `fixtures/questionnaires/`, `tests/py/questionnaires/test_b60_questionnaires.py`, `specs/B-60.md`, `docs/changes/B-60.md`
- Standards: STD-DC, STD-TS
- Acceptance:
  - **B60-1** each answer cites MSP-internal policy passages; a question without a source is marked `needs a human answer`
  - **B60-2** client-specific facts come only from that client's namespace; answers about controls cite the control id
  - **B60-3** project scoping drafts list similar past synthetic projects with their actual hours as cited ranges, never a single promised number
<!-- gen:items:end -->

**Exit steps (wave definition of done).**
- W5-X1: Fold every docs/changes/B-nn.md of the wave into docs/DECISIONS.md, docs/COVERAGE.md, CHANGELOG.md and docs/RUNBOOKS.md (one PR, `tools/fold_changes.py` once B-09 exists; by hand before).
- W5-X2: Update `repo_status` in map/inventory.json and `implemented_in`/`evidence` in map/controls.json for every id the wave touched; a control moves to built only with a named passing test.
- W5-X3: All suites green locally and in CI; map integrity test (B-06) green; demo smoke test (B-10) green.
- W5-X4: the owner reviews the wave report (BUILT / MOCKED / NOT DONE / RISKS / HOW TO RUN / WHAT I SHOULD REVIEW) and says yes before the next wave starts.

## W6: Endpoints, patching and backup

**Window (estimate):** about 3 weeks  
**Items:** 9 (3 S, 6 M, 0 L)

**Goal.** Keep each person's device working and each client's data recoverable: RMM, Intune and backup adapters as mocks, vetted remediation scripts as levers, device R3 actions under dual approval, and patch and backup reports that reconcile.

**Entry steps (owner or the MSP).**
- W6-E1: the MSP answers Q-01 (RMM, backup products) and Q-09 (is backup in scope) or the owner confirms building against generic mock shapes.

| Id | Title | Size | Inventory | Controls | Depends on |
|---|---|---|---|---|---|
| `B-61` | RMM and Intune mock adapters and device reconciliation | M | W-EP-01 | C-27, C-21 | B-18, B-16 |
| `B-62` | Device remediation script levers | M | W-SD-11, W-EP-03, W-EP-07 | C-05, C-06, C-17, C-32, C-41 | B-61, B-28, B-42 |
| `B-63` | Software deployment from an approved catalog and third-party patching | S | W-EP-04, W-PAT-04 | C-05, C-06, C-32 | B-61 |
| `B-64` | Device compliance, encryption and LAPS coverage reports; provisioning readiness | S | W-EP-05, W-EP-06, W-EP-11, W-ONB-06 | C-20, C-21, C-10 | B-61 |
| `B-65` | Device R3 levers: lock, retire, wipe and isolate with dual approval | M | W-EP-08, W-ONB-12, W-SEC-05 | C-05, C-06, C-07, C-29, C-30, C-32 | B-61, B-28, B-16, B-42 |
| `B-66` | macOS and Linux levers through a bash runtime | M | W-EP-09 | C-05, C-17, C-01 | B-61 |
| `B-67` | Patch review pack, compliance report, failed-patch triage, server windows, firmware report | M | W-PAT-01, W-PAT-02, W-PAT-03, W-PAT-06, W-PAT-07 | C-21, C-05, C-37 | B-61 |
| `B-69` | Restore requests to an alternate location and scheduled restore tests | M | W-BDR-03, W-BDR-04 | C-05, C-06, C-30, C-08 | B-68 |
| `B-70` | M365 backup coverage, retention and immutability review, DR plan upkeep | S | W-BDR-05, W-BDR-08, W-BDR-06 | C-21, C-39 | B-68 |

<!-- gen:items:start -->
**`B-61` RMM and Intune mock adapters and device reconciliation**
- Why: One true device list per client, which billing, patching and security all need.
- Owns: `adapters/rmm/`, `adapters/intune/`, `fixtures/rmm/`, `fixtures/intune/`, `workflows/device_reconcile/`, `tests/py/devices/test_b61_reconcile.py`, `specs/B-61.md`, `docs/changes/B-61.md`
- Standards: STD-ER, STD-FX, STD-ID
- Acceptance:
  - **B61-1** devices are matched across RMM, Intune and PSA assets per client by serial, then name; each mismatch type (only in one system, stale, duplicate) is listed
  - **B61-2** counts reconcile to the fixtures; no device of another client is ever compared
  - **B61-3** real adapter selection fails closed (`real adapter not configured`)
  - **B61-4** the RMM mock follows the public Datto RMM API shape (sites, devices, alerts, jobs, components), each field marked Verified or UNVERIFIED; existing RMM components are listed read-only and never run by the program until vetted into the registry (D6-01, D6-26)

**`B-62` Device remediation script levers**
- Why: Tier 1 fixes take one approval instead of a remote session.
- Owns: `levers/powershell/DeviceOps/`, `levers/registry.d/device.json`, `workflows/notify/templates/device.cleanup-temp.md`, `workflows/notify/templates/device.reboot-server.md`, `workflows/notify/templates/device.reboot.md`, `workflows/notify/templates/device.repair-mapped-drive.md`, `workflows/notify/templates/device.reset-outlook-profile.md`, `workflows/notify/templates/device.restart-service.md`, `workflows/notify/templates/device.restart-spooler.md`, `tests/py/devices/test_b62_remed.py`, `specs/B-62.md`, `docs/changes/B-62.md`
- Standards: STD-LV, STD-PS, STD-SC, STD-TS
- Acceptance:
  - **B62-1** levers for print spooler restart, mapped-drive repair, Outlook profile reset, temp cleanup, service restart and reboot run only vetted scripts named in the registry (no free-form script parameter)
  - **B62-2** each dry-run returns what would run and on which device; reboot is flagged `window: business-hours` (servers `window: maintenance`) and the runner rule B42-4 refuses it inside the client's business hours unless the approval records an override; the lever holds no time logic (D6-08)
  - **B62-3** per-script golden tests on mock RMM output; caps per client per hour apply
  - **B62-4** a remediation proposal links the technicians remote-support session record when one exists, from a fixture shaped like a Splashtop session log (MP-13; cited, unverified fields marked UNVERIFIED)

**`B-63` Software deployment from an approved catalog and third-party patching**
- Why: The person gets the app they need without an unvetted installer.
- Owns: `levers/registry.d/software.json`, `levers/python/software.py`, `fixtures/catalog/approved-software.json`, `workflows/notify/templates/device.install-app.md`, `tests/py/devices/test_b63_deploy.py`, `specs/B-63.md`, `docs/changes/B-63.md`
- Standards: STD-LV, STD-TS
- Acceptance:
  - **B63-1** `device.install-app` (R2) accepts only catalog ids (enum from the client's approved catalog); an unknown package is refused
  - **B63-2** third-party updates are proposed per ring with the device count; idempotent when already at the version
  - **B63-3** deployment is a proposal; nothing installs without approval

**`B-64` Device compliance, encryption and LAPS coverage reports; provisioning readiness**
- Why: Gaps on devices are known before a lost laptop becomes a breach.
- Owns: `workflows/device_reports/`, `tests/py/devices/test_b64_device_reports.py`, `specs/B-64.md`, `docs/changes/B-64.md`
- Standards: STD-SC, STD-TS
- Acceptance:
  - **B64-1** per client: non-compliant devices with reason, encryption status, LAPS coverage, and Autopilot/enrollment readiness for incoming hires
  - **B64-2** recovery keys and LAPS passwords are never retrieved or shown (status only); a test asserts no secret-shaped value in any output
  - **B64-3** counts reconcile to the fixtures

**`B-65` Device R3 levers: lock, retire, wipe and isolate with dual approval**
- Why: A stolen laptop is contained fast, and nobody wipes the wrong device.
- Owns: `levers/powershell/DeviceR3/`, `levers/registry.d/device-r3.json`, `workflows/notify/templates/device.isolate.md`, `workflows/notify/templates/device.lock.md`, `workflows/notify/templates/device.release.md`, `workflows/notify/templates/device.retire.md`, `workflows/notify/templates/device.unlock.md`, `workflows/notify/templates/device.wipe.md`, `tests/py/devices/test_b65_device_r3.py`, `specs/B-65.md`, `docs/changes/B-65.md`
- Standards: STD-LV, STD-PS, STD-TS
- Acceptance:
  - **B65-1** lock, retire, wipe and Defender isolate are R3: two leads approve, the requester is verified, one device per approval
  - **B65-2** wipe is `irreversible`: approval older than 24 hours is refused by the runner rule from B28-5 and the page shows `no undo`; isolate has `release` as its undo
  - **B65-3** after-hours execution is refused unless the client record allows it, enforced by runner rules B42-4 and B42-5; wipe and retire never use pre-authorized containment, and wipe stays human-executed after approval (D6-08)

**`B-66` macOS and Linux levers through a bash runtime**
- Why: Mac and Linux users get the same safe automation as Windows users.
- Owns: `core/levers/bridge.py`, `levers/bash/`, `levers/registry.d/unix.json`, `tests/py/levers/test_b66_bash.py`, `specs/B-66.md`, `docs/changes/B-66.md`
- Standards: STD-LV, STD-XL, STD-SC
- Acceptance:
  - **B66-1** `runtime: "bash"` levers run a vetted script named in the registry, through the bridge, with the same JSON request and result schemas; dry-run is a `--what-if` flag the script must honour
  - **B66-2** three levers (disk usage report, service restart, cache clear) with golden-output tests; if shellcheck is not installed the test reports skipped, never passed
  - **B66-3** no script accepts a free-form command parameter

**`B-67` Patch review pack, compliance report, failed-patch triage, server windows, firmware report**
- Why: Patching becomes a reviewed monthly rhythm with proof per client.
- Owns: `workflows/patching/`, `fixtures/patches/`, `tests/py/patching/test_b67_patching.py`, `specs/B-67.md`, `docs/changes/B-67.md`
- Standards: STD-DC, STD-TS
- Acceptance:
  - **B67-1** monthly review pack lists released updates by ring with known issues (fixture) for a human approval; compliance per client reconciles to the fixture
  - **B67-2** failed patches are grouped by error code with a suggested remediation lever; server windows produce a client notice draft
  - **B67-3** network firmware is a version report only (never upgraded by automation)

**`B-69` Restore requests to an alternate location and scheduled restore tests**
- Why: The person gets their file back, and the client knows restores actually work.
- Owns: `levers/registry.d/restore.json`, `levers/python/restore.py`, `workflows/restore_tests/`, `workflows/notify/templates/restore.to-alternate.md`, `tests/py/backup/test_b69_restore.py`, `specs/B-69.md`, `docs/changes/B-69.md`
- Standards: STD-LV, STD-AU, STD-TS
- Acceptance:
  - **B69-1** `restore.to-alternate` (R2) restores a file, mailbox item or VM to an alternate location only; in-place overwrite is not a lever
  - **B69-2** a scheduled restore test picks a random synthetic item per client, restores it to the alternate location in the mock, verifies its hash and records evidence
  - **B69-3** the requester is verified for user-data restores

**`B-70` M365 backup coverage, retention and immutability review, DR plan upkeep**
- Why: Ransomware does not find the one mailbox nobody backed up.
- Owns: `workflows/backup_coverage/`, `tests/py/backup/test_b70_coverage.py`, `specs/B-70.md`, `docs/changes/B-70.md`
- Standards: STD-DC, STD-TS
- Acceptance:
  - **B70-1** lists users, mailboxes and sites not covered by M365 backup per client and policies without immutability or with retention below the client's requirement
  - **B70-2** a DR plan checklist per client flags sections older than N months and produces a tabletop exercise outline draft
  - **B70-3** counts reconcile to the fixtures
<!-- gen:items:end -->

**Exit steps (wave definition of done).**
- W6-X1: Fold every docs/changes/B-nn.md of the wave into docs/DECISIONS.md, docs/COVERAGE.md, CHANGELOG.md and docs/RUNBOOKS.md (one PR, `tools/fold_changes.py` once B-09 exists; by hand before).
- W6-X2: Update `repo_status` in map/inventory.json and `implemented_in`/`evidence` in map/controls.json for every id the wave touched; a control moves to built only with a named passing test.
- W6-X3: All suites green locally and in CI; map integrity test (B-06) green; demo smoke test (B-10) green.
- W6-X4: the owner reviews the wave report (BUILT / MOCKED / NOT DONE / RISKS / HOW TO RUN / WHAT I SHOULD REVIEW) and says yes before the next wave starts.

## W7: Client reporting, licensing and billing inputs

**Window (estimate):** about 2 weeks  
**Items:** 7 (3 S, 4 M, 0 L)

**Goal.** Give account managers and clients reports whose every number reconciles to source data, and give the MSP clean inputs for licences, renewals and billing, without ever judging an individual technician.

**Entry steps (owner or the MSP).**
- W7-E1: the owner confirms the Power BI export format (CSV only, or CSV plus Parquet, which needs a dependency).

| Id | Title | Size | Inventory | Controls | Depends on |
|---|---|---|---|---|---|
| `B-71` | Monthly client health report with reconciliation | M | W-RPT-01, W-SEC-10 | C-21, C-27, C-41 | B-21, B-50 |
| `B-72` | QBR draft and weekly 'what we did for you' digest | M | W-RPT-02, W-RPT-03 | C-21, C-45 | B-71 |
| `B-73` | Technology roadmap recommendations and the client AI-use policy starter | S | W-RPT-04, W-RPT-05 | C-21, C-42, C-45 | B-71 |
| `B-74` | Operations metrics, Power BI exports, problem and CSAT analysis | M | W-RPT-06, W-SD-13, W-SD-14, W-TRN-03, W-TRN-04 | C-21, C-41 | - |
| `B-75` | Licence reconciliation, seat and device true-up, renewals, hardware lifecycle | M | W-VND-01, W-VND-02, W-BIL-02, W-VND-03, W-EP-10 | C-21, C-27 | - |
| `B-76` | Billing classification and time-entry note quality | S | W-BIL-01, W-BIL-03 | C-14, C-41 | - |
| `B-77` | MSP client onboarding discovery, offboarding checklist, migration pre-flight checks | S | W-PRJ-01, W-PRJ-02, W-PRJ-03 | C-20, C-27, C-45 | - |

<!-- gen:items:start -->
**`B-71` Monthly client health report with reconciliation**
- Why: A client owner sees, in plain words, what is healthy and what is not.
- Owns: `workflows/reporting/health/`, `tests/py/reporting/test_b71_health.py`, `specs/B-71.md`, `docs/changes/B-71.md`
- Standards: STD-TS, STD-DC, STD-ID
- Acceptance:
  - **B71-1** one HTML report per client from tickets, baseline, patching, backup and security-awareness fixtures; a validator fails the run if any number differs from its source (C-21 pattern)
  - **B71-2** the plain-English summary is generated from computed counts, then (optionally) rephrased through the gateway; the validator runs after the rephrase
  - **B71-3** no other client's data appears (isolation test)
  - **B71-4** the security-awareness lines (phishing simulation results, vault audit score; MP-23, MP-24) come from per-client fixtures labelled service-level with the vendor UNVERIFIED

**`B-72` QBR draft and weekly 'what we did for you' digest**
- Why: Account managers spend their time on the conversation, not the slides.
- Owns: `workflows/reporting/qbr/`, `workflows/reporting/digest/`, `tests/py/reporting/test_b72_qbr.py`, `specs/B-72.md`, `docs/changes/B-72.md`
- Standards: STD-DC, STD-TS
- Acceptance:
  - **B72-1** the QBR draft reuses the health data for the quarter with trends; every number reconciles
  - **B72-2** the weekly digest lists closed tickets and changes in plain words without ticket free text; it is a draft (an Outlook draft arrives in W9)
  - **B72-3** both start with the draft label

**`B-73` Technology roadmap recommendations and the client AI-use policy starter**
- Why: Small clients get a credible plan and a first AI policy.
- Owns: `workflows/reporting/roadmap/`, `governance/templates/client-ai-policy-starter.md`, `tests/py/reporting/test_b73_vcio.py`, `specs/B-73.md`, `docs/changes/B-73.md`
- Standards: STD-DC
- Acceptance:
  - **B73-1** roadmap recommendations list hardware lifecycle, licence and security items with the finding each rests on and a budget range from the fixture price list
  - **B73-2** the AI-use policy starter is filled with the client's industry (dental or financial) defaults from the governance map and labelled 'starter, review with your counsel'
  - **B73-3** no recommendation without a cited finding

**`B-74` Operations metrics, Power BI exports, problem and CSAT analysis**
- Why: Leadership sees where time goes, and nobody is ranked by an AI.
- Owns: `workflows/reporting/ops/`, `docs/EXPORTS.md`, `docs/POWERBI_SEMANTIC_MODEL.md`, `tests/py/reporting/test_b74_ops.py`, `specs/B-74.md`, `docs/changes/B-74.md`
- Standards: STD-DC, STD-TS
- Acceptance:
  - **B74-1** CSV exports (resolution time, first-contact resolution, reopen rate, suggestion acceptance and correction rates) with a documented semantic model
  - **B74-2** recurring-issue analysis groups resolved tickets by cause per client; CSAT comments are summarised by theme with counts
  - **B74-3** no metric is grouped by individual technician; a test fails if any export has a technician id column (W-TRN-04 guard)
  - **B74-4** the per-person metric is time until the person can work again: PSA completed minus created, plus a proposed `user confirmed working` field; CSAT comes from a mock CSAT-tool export, never per technician (D6-21)

**`B-75` Licence reconciliation, seat and device true-up, renewals, hardware lifecycle**
- Why: Clients stop paying for seats nobody uses, with proof.
- Owns: `workflows/licensing/`, `fixtures/licensing/`, `tests/py/licensing/test_b75_licensing.py`, `specs/B-75.md`, `docs/changes/B-75.md`
- Standards: STD-FX, STD-TS
- Acceptance:
  - **B75-1** per client: licences bought vs assigned vs active users, unused seats, users and devices for billing true-up; all counts reconcile
  - **B75-2** renewals (subscriptions, warranties, domains) due in N days and hardware past lifecycle are listed
  - **B75-3** purchases and reductions are recommendations with the evidence; nothing is bought or cancelled (W-VND-02)

**`B-76` Billing classification and time-entry note quality**
- Why: Clients are billed for what their contract says, and notes explain the work.
- Owns: `workflows/billing/`, `evals/billing/`, `tests/py/billing/test_b76_billing.py`, `specs/B-76.md`, `docs/changes/B-76.md`
- Standards: STD-TS, STD-DC
- Acceptance:
  - **B76-1** each ticket is suggested managed vs project vs out-of-scope against a fixture contract scope with the clause cited; a human decides
  - **B76-2** time-entry notes missing the work done, outcome or time are flagged with a suggested rewrite draft
  - **B76-3** accuracy against gold labels reported fixture-based; no per-technician score is produced

**`B-77` MSP client onboarding discovery, offboarding checklist, migration pre-flight checks**
- Why: A new client starts with a clear baseline; a departing client leaves cleanly.
- Owns: `workflows/client_lifecycle/`, `docs/runbooks/client-offboarding.md`, `tests/py/projects/test_b77_client_lifecycle.py`, `specs/B-77.md`, `docs/changes/B-77.md`
- Standards: STD-DC, STD-TS
- Acceptance:
  - **B77-1** a discovery pack for a new client runs the baseline, device reconciliation and licence report in read-only mode and lists gaps
  - **B77-2** the MSP offboarding checklist (credentials handed back, GDAP removed, documentation exported) is a human runbook; nothing is automated
  - **B77-3** migration pre-flight checks (mailbox sizes, licence availability, conflicting addresses) are read-only; executing migrations stays in not-now
<!-- gen:items:end -->

**Exit steps (wave definition of done).**
- W7-X1: Fold every docs/changes/B-nn.md of the wave into docs/DECISIONS.md, docs/COVERAGE.md, CHANGELOG.md and docs/RUNBOOKS.md (one PR, `tools/fold_changes.py` once B-09 exists; by hand before).
- W7-X2: Update `repo_status` in map/inventory.json and `implemented_in`/`evidence` in map/controls.json for every id the wave touched; a control moves to built only with a named passing test.
- W7-X3: All suites green locally and in CI; map integrity test (B-06) green; demo smoke test (B-10) green.
- W7-X4: the owner reviews the wave report (BUILT / MOCKED / NOT DONE / RISKS / HOW TO RUN / WHAT I SHOULD REVIEW) and says yes before the next wave starts.

## W8: Scale, evaluation and hardening

**Window (estimate):** about 3 weeks  
**Items:** 7 (0 S, 7 M, 0 L)

**Goal.** Make the system hold at 50-500 tenants and many technicians: routing set by evals, budgets and circuit breakers, a scheduler with per-client fan-out, database-backed queue and audit, operational logs and alerts, and CI gates on every eval.

**Entry steps (owner or the MSP).**
- W8-E1: the owner decides on any new dependency the items need (OpenTelemetry SDK, a SQLite version check) per STD-PY-2.
- W8-E2: After B-84 lands, the owner adds `tools/eval_gate.py` to CI (protected files).

| Id | Title | Size | Inventory | Controls | Depends on |
|---|---|---|---|---|---|
| `B-78` | Routing evals and escalation thresholds | M | W-TOOL-02, W-TOOL-14 | C-16, C-41, C-15 | - |
| `B-79` | Injection corpus for email, documents and tool output; guard maintenance | M | W-TOOL-05 | C-12, C-13, C-14 | - |
| `B-80` | Gateway budgets, circuit breaker and model-call audit | M | W-TOOL-02, W-TOOL-09 | C-17, C-32, C-40, C-11 | B-17 |
| `B-81` | Scheduler with per-client fan-out and job keys | M | W-TOOL-09, W-IDM-09, W-M365-11 | C-32, C-18, C-27 | B-42 |
| `B-82` | SQLite queue and append-only audit store | M | W-TOOL-06, W-CMP-05 | C-08, C-09, C-39, C-07 | B-42 |
| `B-83` | Operational logs, request ids and monitoring alert rules | M | W-TOOL-09 | C-40, C-11, C-27 | B-80 |
| `B-84` | Load, failure and retry tests; eval gates in CI | M | W-TOOL-04, W-TOOL-07 | C-41, C-17, C-18 | B-82 |

<!-- gen:items:start -->
**`B-78` Routing evals and escalation thresholds**
- Why: The smallest model that is good enough does the work.
- Owns: `evals/routing/`, `tests/py/evals/test_b78_routing.py`, `specs/B-78.md`, `docs/changes/B-78.md`
- Standards: STD-TS, STD-DC
- Acceptance:
  - **B78-1** the golden sets run on the mock and, when installed, the local model; a table reports accuracy, latency and estimated cost per task and model, labelled fixture-based
  - **B78-2** escalation thresholds are written to a proposed routing change file for review, never applied automatically
  - **B78-3** without a local model the report says `skipped: no local model`, never a number

**`B-79` Injection corpus for email, documents and tool output; guard maintenance**
- Why: The tripwire is measured on cases it was not tuned on.
- Owns: `evals/injection/corpus-v2.jsonl`, `evals/injection/report_v2.py`, `tests/py/evals/test_b79_injection_v2.py`, `specs/B-79.md`, `docs/changes/B-79.md`
- Standards: STD-SC, STD-TS
- Acceptance:
  - **B79-1** at least 150 new synthetic cases across email, KB documents and tool output, plus benign look-alikes; held-out cases written by a different author pass are labelled so
  - **B79-2** the report shows precision and recall per channel and states the held-out result separately
  - **B79-3** for every flagged case in every workflow, no lever is proposed (structural test across workflows)

**`B-80` Gateway budgets, circuit breaker and model-call audit**
- Why: A loop or an outage cannot run up cost or hide behind silence.
- Owns: `core/gateway/gateway.py`, `core/gateway/budget.py`, `tests/py/gateway/test_b80_budgets.py`, `specs/B-80.md`, `docs/changes/B-80.md`
- Standards: STD-AU, STD-ER, STD-CF
- Acceptance:
  - **B80-1** per-client and global budgets (calls, tokens) from config; over budget returns `Completion(ok=False, error="budget exceeded")`
  - **B80-2** a provider failing N times opens a breaker for T seconds; calls fail fast and recover after T
  - **B80-3** each call writes a `model.complete` v2 audit record with provider, model, task, prompt SHA-256, lengths, latency and ok, and no prompt or completion text (DR-17)

**`B-81` Scheduler with per-client fan-out and job keys**
- Why: Daily baselines and monthly evidence run for every client without a person remembering.
- Owns: `core/scheduler/`, `tests/py/scheduler/test_b81_scheduler.py`, `specs/B-81.md`, `docs/changes/B-81.md`
- Standards: STD-PY, STD-ID, STD-TS
- Acceptance:
  - **B81-1** jobs are config (name, workflow, schedule, per-client enable, concurrency cap); a run fans out one unit per client with key `job/client/period`
  - **B81-2** a repeated key is skipped (idempotent); caps per client and global are honoured in a test with 300 synthetic clients
  - **B81-3** results become reports or proposals, never direct writes

**`B-82` SQLite queue and append-only audit store**
- Why: Many leads and many jobs at once without a forked chain.
- Owns: `core/queue/sqlite_store.py`, `core/audit/sqlite_store.py`, `tests/py/storage/test_b82_sqlite.py`, `specs/B-82.md`, `docs/changes/B-82.md`
- Standards: STD-AU, STD-PR, STD-PY
- Acceptance:
  - **B82-1** proposal status changes use `UPDATE ... WHERE id = ? AND status = 'pending'` (compare-and-set); two leads deciding at once produce one decision
  - **B82-2** audit rows are insert-only (triggers refuse UPDATE and DELETE); the hash chain is kept and verifies the same as the JSONL store
  - **B82-3** the JSONL stores remain the default until a DECISIONS entry switches them

**`B-83` Operational logs, request ids and monitoring alert rules**
- Why: Problems are seen by the MSP before the client calls.
- Owns: `core/obs/`, `workflows/monitoring/`, `tests/py/obs/test_b83_obs.py`, `specs/B-83.md`, `docs/changes/B-83.md`
- Standards: STD-SC, STD-AU, STD-TS
- Acceptance:
  - **B83-1** content-free JSON logs with request_id, component, event, outcome and timing; a test fails if any log line holds ticket text, a prompt or a secret shape
  - **B83-2** alert rules over the audit stream: denial spikes, after-hours executes, approvals faster than a human could read, verify failures; replayed synthetic incidents fire the expected alerts
  - **B83-3** client id is a label on every log line

**`B-84` Load, failure and retry tests; eval gates in CI**
- Why: Quality is enforced by CI, not remembered.
- Owns: `evals/gates.json`, `tests/py/load/test_b84_load.py`, `tools/eval_gate.py`, `specs/B-84.md`, `docs/changes/B-84.md`
- Standards: STD-TS
- Acceptance:
  - **B84-1** evals/gates.json holds each workflow's threshold; `tools/eval_gate.py` fails when any report is below its gate (owner adds it to CI)
  - **B84-2** load test: 10,000 synthetic lever calls across 300 clients complete with zero chain breaks and zero cross-client results
  - **B84-3** failure tests: adapter timeouts and crashes produce `error` results with nothing applied; retries never double-apply (idempotency)
<!-- gen:items:end -->

**Exit steps (wave definition of done).**
- W8-X1: Fold every docs/changes/B-nn.md of the wave into docs/DECISIONS.md, docs/COVERAGE.md, CHANGELOG.md and docs/RUNBOOKS.md (one PR, `tools/fold_changes.py` once B-09 exists; by hand before).
- W8-X2: Update `repo_status` in map/inventory.json and `implemented_in`/`evidence` in map/controls.json for every id the wave touched; a control moves to built only with a named passing test.
- W8-X3: All suites green locally and in CI; map integrity test (B-06) green; demo smoke test (B-10) green.
- W8-X4: the owner reviews the wave report (BUILT / MOCKED / NOT DONE / RISKS / HOW TO RUN / WHAT I SHOULD REVIEW) and says yes before the next wave starts.

## W9: Cloud, DevOps and Microsoft 365 integrations

**Window (estimate):** about 3 weeks  
**Items:** 6 (1 S, 5 M, 0 L)

**Goal.** Show the Azure and Microsoft 365 side of the job as code that validates but never deploys: Bicep, Azure DevOps pipelines, Key Vault with managed identity, MCP, Teams, Outlook and SharePoint integration mocks, Entra sign-in for approvers, and the gate that keeps hosted models off until approved.

**Entry steps (owner or the MSP).**
- W9-E1: the owner confirms the Bicep CLI is installed (`az bicep build` and `what-if` only; the hooks already limit az to those).

| Id | Title | Size | Inventory | Controls | Depends on |
|---|---|---|---|---|---|
| `B-85` | Bicep: Key Vault, managed identity, Log Analytics; secrets doc | M | W-TOOL-08, W-PRJ-05 | C-39, C-40, C-10 | - |
| `B-86` | Bicep compute and Azure DevOps pipeline; branching and release doc | M | W-TOOL-07, W-PRJ-05 | C-24, C-37 | B-85 |
| `B-87` | MCP server over approved levers | M | W-TOOL-10 | C-01, C-03, C-04, C-43 | B-16, B-42 |
| `B-88` | Teams approval card, Outlook draft and SharePoint ingestion mocks; site creation lever | M | W-TOOL-10, W-RPT-03, W-M365-06 | C-06, C-19, C-26 | B-03, B-56 |
| `B-90` | Hosted provider approval gate and Azure OpenAI adapter (mocked) | M | W-TOOL-02, W-GOV-02 | C-28, C-43, C-15, C-25 | B-55 |
| `B-91` | Adapter contract tests and real-adapter stubs | S | W-TOOL-11 | C-02, C-27 | B-18, B-61, B-68 |

<!-- gen:items:start -->
**`B-85` Bicep: Key Vault, managed identity, Log Analytics; secrets doc**
- Why: The secrets pattern the MSP would actually run, reviewed as code.
- Owns: `infra/bicep/core/`, `docs/SECRETS.md`, `tests/py/infra/test_b85_bicep_core.py`, `specs/B-85.md`, `docs/changes/B-85.md`
- Standards: STD-SC, STD-DC
- Acceptance:
  - **B85-1** modules build with `az bicep build` and lint clean; Key Vault uses Azure RBAC, soft delete and purge protection; no secret value in any parameter file
  - **B85-2** docs/SECRETS.md shows the managed-identity-first pattern and how an adapter binding names a secret reference; rotation stays a human task (W-TOOL-08)
  - **B85-3** nothing is deployed: the test asserts no `az deployment ... create` appears in any script
  - **B85-4** one Key Vault per environment (dev, prod), secrets named `client-<id>-<purpose>`, access by managed identity with RBAC; a separate per-client vault only where a client contract requires it, recorded on the client record (D6-10)

**`B-86` Bicep compute and Azure DevOps pipeline; branching and release doc**
- Why: The same quality gates in the pipeline tool the MSP uses.
- Owns: `infra/bicep/compute/`, `infra/azure-pipelines.yml`, `docs/BRANCHING_RELEASE.md`, `specs/B-86.md`, `docs/changes/B-86.md`
- Standards: STD-VR, STD-SC, STD-DC
- Acceptance:
  - **B86-1** Functions, Logic App and Automation Account modules build and lint clean; managed identities, no keys
  - **B86-2** azure-pipelines.yml mirrors ci.yml (same suites, secret scan, eval gate) and adds a validate and what-if stage with a manual approval before any deploy stage (deploy stage disabled)
  - **B86-3** the release doc covers branches, PR rules, versioning (STD-VR), staged rollout rings (CM-5) and rollback (CM-6)

**`B-87` MCP server over approved levers**
- Why: Other agents can press only the buttons they are allowed to.
- Owns: `mcp/`, `tests/py/mcp/test_b87_mcp.py`, `specs/B-87.md`, `docs/changes/B-87.md`
- Standards: STD-LV, STD-SC, STD-ER
- Acceptance:
  - **B87-1** the server exposes registered R0 levers by default; write levers are exposed only in dry-run; every call goes through the runner with the caller's identity
  - **B87-2** token audience is validated and tokens are never passed through to adapters; an unknown or out-of-scope lever is denied and audited
  - **B87-3** runs on stdio or 127.0.0.1 only; the security checks are listed in mcp/README.md with their tests

**`B-88` Teams approval card, Outlook draft and SharePoint ingestion mocks; site creation lever**
- Why: Approvals and drafts arrive where technicians already work.
- Owns: `adapters/m365/`, `workflows/teams_approvals/`, `levers/registry.d/site.json`, `workflows/notify/templates/site.new.md`, `tests/py/m365/test_b88_m365.py`, `specs/B-88.md`, `docs/changes/B-88.md`
- Standards: STD-LV, STD-SC, STD-FX
- Acceptance:
  - **B88-1** an Adaptive Card JSON for a pending proposal shows the diff, undo and impact; a card response is validated exactly like a UI decision (scope, four-eyes, verification)
  - **B88-2** the weekly digest becomes an Outlook draft in the mock (never sent); SharePoint documents ingest into the client's RAG namespace in the mock
  - **B88-3** `site.new` (R2) creates a Teams or SharePoint site in the mock with an owner and default private sharing

**`B-90` Hosted provider approval gate and Azure OpenAI adapter (mocked)**
- Why: Hosted models stay off until someone accountable says yes in writing.
- Owns: `core/gateway/azure_openai.py`, `core/gateway/gateway.py`, `governance/ai-vendor-register.json`, `tests/py/gateway/test_b90_hosted.py`, `specs/B-90.md`, `docs/changes/B-90.md`
- Standards: STD-SC, STD-CF, STD-ER
- Acceptance:
  - **B90-1** a hosted provider loads only when config names an approval id present in governance/ai-vendor-register.json with allowed data classes, retention terms and review date
  - **B90-2** the Azure OpenAI adapter is tested against a fake server on 127.0.0.1 only; no real endpoint is ever called in tests
  - **B90-3** DC-4/DC-5 text is refused by a hosted route unless the register entry allows that class (C-25)
  - **B90-4** governance/ai-vendor-register.json starts with Azure OpenAI and the Anthropic API as `status: pending` with no allowed data classes; nothing hosted loads until the MSP approves in writing, and a client record defaults to `model_processing: none` (D6-11)

**`B-91` Adapter contract tests and real-adapter stubs**
- Why: When the MSP's real PSA and RMM are known, plugging them in is a checked step.
- Owns: `tests/py/contract/test_b91_adapters.py`, `docs/ADAPTERS.md`, `specs/B-91.md`, `docs/changes/B-91.md`
- Standards: STD-TS, STD-DC
- Acceptance:
  - **B91-1** one contract suite per adapter interface runs against every implementation present (mocks today); a real implementation must pass it before it can be selected
  - **B91-2** docs/ADAPTERS.md lists for each system the real API, least-privilege scopes, throttling behaviour (Graph 429 and Retry-After, cited) and what is UNVERIFIED
  - **B91-3** every adapter's real implementation selection fails closed when not configured
  - **B91-4** docs/ADAPTERS.md names, per Microsoft 365 lever, the least-privileged GDAP role and the Secure Application Model delegated scope; app-only access is listed only for documented per-client app registrations (D6-09)
<!-- gen:items:end -->

**Exit steps (wave definition of done).**
- W9-X1: Fold every docs/changes/B-nn.md of the wave into docs/DECISIONS.md, docs/COVERAGE.md, CHANGELOG.md and docs/RUNBOOKS.md (one PR, `tools/fold_changes.py` once B-09 exists; by hand before).
- W9-X2: Update `repo_status` in map/inventory.json and `implemented_in`/`evidence` in map/controls.json for every id the wave touched; a control moves to built only with a named passing test.
- W9-X3: All suites green locally and in CI; map integrity test (B-06) green; demo smoke test (B-10) green.
- W9-X4: the owner reviews the wave report (BUILT / MOCKED / NOT DONE / RISKS / HOW TO RUN / WHAT I SHOULD REVIEW) and says yes before the next wave starts.

## W10: Governance pack, people and packaging

**Window (estimate):** about 2 weeks  
**Items:** 7 (3 S, 4 M, 0 L)

**Goal.** Finish the parts of the job that are about people and decisions: policies, approval processes, incident response, training, prioritisation by ROI, adoption recommendations, and a packaged demo with an honest coverage audit.

**Entry steps (owner or the MSP).**
- W10-E1: the owner reviews which governance documents should be adoptable by the MSP as-is versus kept as examples (GQ-02).

| Id | Title | Size | Inventory | Controls | Depends on |
|---|---|---|---|---|---|
| `B-92` | AI policy, acceptable use and DLP mapping | S | W-GOV-01 | C-42, C-25, C-45 | B-55 |
| `B-93` | Model and tool approval process | S | W-GOV-02 | C-28, C-43 | B-90 |
| `B-94` | AI incident response runbook, notification templates review and tabletop | S | W-GOV-04 | C-34, C-35, C-31, C-33 | B-41, B-02 |
| `B-95` | Use-case intake, ROI tracker, SOC 2 control mapping and risk register | M | W-TOOL-13 | C-37, C-45 | B-06 |
| `B-96` | Staff training, client conversation guide, explainer and data-handling summary | M | W-TRN-01, W-TRN-02 | C-42 | - |
| `B-97` | Tech radar, leadership brief, 30/60/90 plan and automation framework review method | M | W-TOOL-14, W-TOOL-12 | C-43, C-45 | - |
| `B-98` | Packaged demo, final README and coverage audit | M | W-TOOL-07 | C-45, C-41 | B-10 |

<!-- gen:items:start -->
**`B-92` AI policy, acceptable use and DLP mapping**
- Why: One short policy staff can actually follow.
- Owns: `governance/AI_POLICY.md`, `governance/ACCEPTABLE_USE.md`, `governance/DLP_MAPPING.md`, `specs/B-92.md`, `docs/changes/B-92.md`
- Standards: STD-DC
- Acceptance:
  - **B92-1** the policy and acceptable-use page each fit on two pages and reference data classes DC-0 to DC-6 and the never-automate list
  - **B92-2** DLP mapping lists for each data class what may enter a local prompt, a hosted prompt, a log and an index, matching governance map section 1 exactly (a test compares the tables)
  - **B92-3** every page carries the synthetic-data and not-legal-advice labels

**`B-93` Model and tool approval process**
- Why: New AI tools arrive through a door, not a side window.
- Owns: `governance/MODEL_TOOL_APPROVAL.md`, `governance/templates/ai-change-request.md`, `workflows/assurance/approvals.py`, `specs/B-93.md`, `docs/changes/B-93.md`
- Standards: STD-DC
- Acceptance:
  - **B93-1** the process names who proposes, who approves and what evidence is needed (retention terms, BAA or ZDR status, eval results) for a model, provider, MCP server or tool
  - **B93-2** the AI change request template carries inventory id, risk class, data classes and rollback
  - **B93-3** the process is the only way an entry is added to the vendor register (B-90 file)

**`B-94` AI incident response runbook, notification templates review and tabletop**
- Why: When something goes wrong, the person is restored first and the client hears from a human.
- Owns: `docs/runbooks/ai-incident-response.md`, `governance/templates/notifications/`, `docs/TABLETOP_2026.md`, `specs/B-94.md`, `docs/changes/B-94.md`
- Standards: STD-DC
- Acceptance:
  - **B94-1** the runbook follows IR-1 to IR-9 with commands for pause, scope (audit query) and rollback that exist in the repo
  - **B94-2** notification templates for the affected person, client contact and privacy officer are plain language and list the timelines as 'confirm with counsel'
  - **B94-3** one tabletop on synthetic tenants (wrong user disabled at Contoso Dental) is recorded with times and lessons

**`B-95` Use-case intake, ROI tracker, SOC 2 control mapping and risk register**
- Why: Leadership can rank the next automation by measured value and risk.
- Owns: `governance/USE_CASE_INTAKE.md`, `governance/ROI_TRACKER.md`, `workflows/assurance/__init__.py`, `workflows/assurance/__main__.py`, `workflows/assurance/rubric.py`, `workflows/assurance/intake.py`, `workflows/assurance/roi.py`, `workflows/assurance/soc2.py`, `workflows/assurance/risk.py`, `workflows/assurance/render.py`, `governance/SOC2_CONTROL_MAPPING.md`, `governance/RISK_REGISTER.md`, `docs/planned/ROI_TRACKER.md`, `specs/B-95.md`, `docs/changes/B-95.md`
- Standards: STD-DC
- Acceptance:
  - **B95-1** intake scores a use case by hours (assumed), acceptance rate (measured on fixtures), effort and risk weight, as docs/planned/ROI_TRACKER.md planned; the planned file is moved to docs/ROI_TRACKER.md (move M-07)
  - **B95-2** the ROI tracker is filled from this repo's eval reports and labelled fixture-based on every row
  - **B95-3** the SOC 2 mapping and risk register are generated from map/controls.json and the governance map AIR table, so they cannot drift

**`B-96` Staff training, client conversation guide, explainer and data-handling summary**
- Why: Technicians and clients understand what the AI does and does not do.
- Owns: `governance/STAFF_TRAINING.md`, `governance/CLIENT_CONVERSATION_GUIDE.md`, `workflows/training/`, `docs/AI_EXPLAINER.md`, `docs/CLIENT_DATA_HANDLING.md`, `docs/planned/STAFF_TRAINING.md`, `docs/planned/CLIENT_CONVERSATION_GUIDE.md`, `specs/B-96.md`, `docs/changes/B-96.md`
- Standards: STD-DC
- Acceptance:
  - **B96-1** the planned outlines are filled and moved out of docs/planned (move M-07); the ten-minute exercise uses synthetic tickets from fixtures
  - **B96-2** the explainer and data-handling summary are one page each, readable by a client owner (grade 8 or lower, computed)
  - **B96-3** every claim about what the system does links to the test that proves it

**`B-97` Tech radar, leadership brief, 30/60/90 plan and automation framework review method**
- Why: Recommendations are earned by evidence, not enthusiasm.
- Owns: `governance/TECH_RADAR.md`, `workflows/assurance/briefs.py`, `docs/LEADERSHIP_BRIEF.md`, `docs/PLAN_30_60_90.md`, `docs/AUTOMATION_FRAMEWORK_REVIEW.md`, `docs/planned/TECH_RADAR.md`, `specs/B-97.md`, `docs/changes/B-97.md`
- Standards: STD-DC
- Acceptance:
  - **B97-1** radar rings are assigned only from this repo's eval results or cited sources; every 'adopt' names its evidence
  - **B97-2** the leadership brief ranks automations by ROI and risk from the intake scores
  - **B97-3** the framework review method is a checklist for existing RMM scripts (rights, secrets, idempotency, logging, owner) with no claim about any real script (Q-07)

**`B-98` Packaged demo, final README and coverage audit**
- Why: A reviewer can run the whole thing in five minutes.
- Owns: `docker-compose.yml`, `Dockerfile`, `README.md`, `docs/ARCHITECTURE.md`, `specs/B-98.md`, `docs/changes/B-98.md`
- Standards: STD-DC, STD-SC
- Acceptance:
  - **B98-1** `docker compose up` (when Docker is available) starts the UI with seeded synthetic data on 127.0.0.1 only; without Docker the README gives the uv path
  - **B98-2** the README has the architecture diagram, design trade-offs, honest limitations and 'how I would adapt this to a real MSP in week one'
  - **B98-3** the demo smoke test passes inside the container image
<!-- gen:items:end -->

**Exit steps (wave definition of done).**
- W10-X1: Fold every docs/changes/B-nn.md of the wave into docs/DECISIONS.md, docs/COVERAGE.md, CHANGELOG.md and docs/RUNBOOKS.md (one PR, `tools/fold_changes.py` once B-09 exists; by hand before).
- W10-X2: Update `repo_status` in map/inventory.json and `implemented_in`/`evidence` in map/controls.json for every id the wave touched; a control moves to built only with a named passing test.
- W10-X3: All suites green locally and in CI; map integrity test (B-06) green; demo smoke test (B-10) green.
- W10-X4: the owner reviews the wave report (BUILT / MOCKED / NOT DONE / RISKS / HOW TO RUN / WHAT I SHOULD REVIEW) and says yes before the next wave starts.
- W10-X5: Final COVERAGE.md audit: every row's status word is checked against tests (Phase 11).


## Not now

These are deliberate. Each has a reason and a trigger to revisit.

| Id | What | Inventory | Why not now | Revisit |
|---|---|---|---|---|
| `NN-01` | eDiscovery, retention and litigation-hold requests | W-M365-12 | Never-automate: legal authority and message content. No tooling, not even a fact pack, until the MSP's legal owner asks for one. | only on a written request from the MSP's legal or compliance owner |
| `NN-02` | Contract terms, pricing and billing disputes | W-BIL-04 | Never-automate: relationships, not tasks. Billing inputs (B-76) stop at classification suggestions. | never as automation |
| `NN-03` | Technician performance coaching or ranking from AI output or ticket metrics | W-TRN-04 | Never-automate; B-74 adds a test that no export carries a per-technician column. | never |
| `NN-04` | Executing tenant-to-tenant or mailbox migrations | W-PRJ-03 | R3 bulk change across many users; mature vendor tools exist. Only read-only pre-flight checks are planned (B-77). | after W3 identity levers have a record of clean executions and the MSP names its migration tool |
| `NN-05` | Licence purchase or cancellation, Conditional Access changes, privileged role or PIM grants, firewall/SASE and DNS registrar changes | W-VND-02, W-IDM-06, W-IDM-07, W-SEC-09, W-VND-06 | Never-automate or kept human; the never-automate gate (B-14) refuses levers that would do them. Reports and fact packs only. | never for the change itself |
| `NN-06` | Unattended R1 standard changes (HO-5 autonomy) | - | Needs 30 days of shadow mode per tenant with no corrections, which needs real tickets. | after a pilot at the MSP with real data and the MSP's approval |
| `NN-07` | Any real tenant, PSA, RMM or backup connection | - | Hard rule: synthetic data only. Real adapters stay stubs that fail closed. | after hire, with an MSP test tenant and written approval |
| `NN-08` | Hosted models on client data | - | C-28 gate stays closed until a provider is approved with retention and BAA terms (GQ-04). | when the MSP approves a provider in writing |
| `NN-09` | Vector database product, Postgres, multi-host deployment, FastAPI rewrite of the UI | - | Each needs a dependency or install decision; the interfaces are built so the swap is local. | W5/W8 decisions, or after hire |
| `NN-10` | Proposal id v2 with a separator (DR-19) | - | Theoretical collision only; changing ids now churns every test and the demo. | when two levers with colliding names are proposed |
| `NN-11` | Publishing the repo or choosing a license | - | The owner's decision (D-008, GQ-13). | The owner |

## Coverage index: every inventory item to its build items

| Inventory id | Work | Inventory risk | Roadmap items | Not now |
|---|---|---|---|---|
| `W-SD-01` | Ticket intake and logging | R1 | B-18, B-21, B-22, B-55 | - |
| `W-SD-02` | Ticket triage: category, priority, queue | R1 | B-05, B-10 | - |
| `W-SD-03` | Duplicate and related ticket detection | R1 | B-21, B-23 | - |
| `W-SD-04` | Ticket summary for handoff and escalation | R0 | B-21, B-22 | - |
| `W-SD-05` | Draft reply to the end user from the knowledge base | R1 | B-21, B-25 | - |
| `W-SD-06` | SLA breach watch | R0 | B-21, B-24 | - |
| `W-SD-07` | Escalation tier 1 to 2 to 3 with context package | R0 | B-05, B-22, B-44 | - |
| `W-SD-08` | Outage and widespread-issue detection | R1 | B-23 | - |
| `W-SD-09` | Closure confirmation and follow-up | R1 | B-04, B-25 | - |
| `W-SD-10` | Stale ticket and backlog grooming | R0 | B-24 | - |
| `W-SD-11` | Common tier 1 fixes via scripts (print spooler, mapped drives, Outlook profile, cache clear) | R2 | B-62 | - |
| `W-SD-12` | After-hours and on-call triage | R1 | B-43 | - |
| `W-SD-13` | Recurring-issue analysis (problem management) | R0 | B-74 | - |
| `W-SD-14` | Customer satisfaction feedback review | R0 | B-74 | - |
| `W-ONB-01` | New-hire request intake and requester authorization check | R0 | B-34, B-35 | - |
| `W-ONB-02` | Create the user account (cloud or hybrid) | R3 | B-28, B-35 | - |
| `W-ONB-03` | Assign licenses | R2 | B-31 | - |
| `W-ONB-04` | Role-based access: groups, shared mailboxes, Teams and SharePoint | R2 | B-32 | - |
| `W-ONB-05` | MFA enrollment and Temporary Access Pass | R3 | B-30 | - |
| `W-ONB-06` | Device provisioning (Autopilot, Intune enrollment, app set) | R2 | B-64 | - |
| `W-ONB-07` | Day-one welcome and handoff to the manager | R1 | B-35 | - |
| `W-ONB-08` | Offboarding: block sign-in and revoke sessions | R3 | B-02, B-04, B-29, B-36 | - |
| `W-ONB-09` | Offboarding: mailbox conversion, forwarding and auto-reply | R2 | B-33, B-36 | - |
| `W-ONB-10` | Offboarding: OneDrive and file ownership transfer | R2 | B-33, B-36 | - |
| `W-ONB-11` | Offboarding: license removal after retention window | R2 | B-31, B-36 | - |
| `W-ONB-12` | Offboarding: device retire or wipe and hardware recovery | R3 | B-65 | - |
| `W-ONB-13` | Offboarding: line-of-business and third-party apps | R3 | B-36 | - |
| `W-ONB-14` | Offboarding completion proof | R0 | B-36 | - |
| `W-ONB-15` | Urgent or hostile termination | R3 | B-14, B-37 | - |
| `W-ONB-16` | Role change or transfer (mover) | R2 | B-29, B-32 | - |
| `W-ONB-17` | Guest and contractor account lifecycle | R2 | B-38 | - |
| `W-IDM-01` | Password reset | R3 | B-30 | - |
| `W-IDM-02` | MFA reset (lost or new phone) | R3 | B-02, B-03, B-04, B-11 | - |
| `W-IDM-03` | Sign-in failure and lockout investigation | R0 | B-39 | - |
| `W-IDM-04` | Caller identity verification | R3 | B-01, B-03, B-14, B-34, B-37 | - |
| `W-IDM-05` | Risky sign-in and risky user review | R0 | B-44 | - |
| `W-IDM-06` | Conditional Access policy change | R3 | B-14, B-37, B-50 | NN-05 |
| `W-IDM-07` | Privileged role grants and PIM activation approval | R3 | B-14, B-32, B-37 | NN-05 |
| `W-IDM-08` | Break-glass account monitoring | R0 | B-40 | - |
| `W-IDM-09` | Quarterly admin access review across tenants | R0 | B-49, B-81 | - |
| `W-IDM-10` | Partner delegated access (GDAP) relationship management | R3 | B-54 | - |
| `W-IDM-11` | Stale account cleanup | R3 | B-38 | - |
| `W-IDM-12` | App registration and service principal secret expiry | R0 | B-54 | - |
| `W-IDM-13` | Self-service password reset and MFA method coverage | R0 | B-40 | - |
| `W-M365-01` | Shared mailbox and distribution list changes | R2 | B-33 | - |
| `W-M365-02` | Mailbox permission grants (Full Access, Send As) | R2 | B-33 | - |
| `W-M365-03` | Mail delivery troubleshooting (message trace) | R0 | B-45 | - |
| `W-M365-04` | Quarantine release requests | R2 | B-45 | - |
| `W-M365-05` | Suspicious inbox rule and external forwarding audit | R0 | B-46 | - |
| `W-M365-06` | SharePoint and Teams site creation and permissions | R2 | B-88 | - |
| `W-M365-07` | Oversharing and external sharing review (Copilot readiness) | R0 | B-53 | - |
| `W-M365-08` | Sensitivity labels and DLP policy changes | R3 | B-53 | - |
| `W-M365-09` | Mailbox size and archive management | R2 | B-33 | - |
| `W-M365-10` | DMARC, SPF and DKIM monitoring | R0 | B-54 | - |
| `W-M365-11` | Tenant security baseline and drift check | R0 | B-10, B-26, B-50, B-81 | - |
| `W-M365-12` | Retention, litigation hold and eDiscovery requests | R3 | B-14 | NN-01 |
| `W-EP-01` | Device inventory reconciliation (RMM vs Intune vs PSA) | R0 | B-61 | - |
| `W-EP-02` | RMM agent and Defender sensor health | R0 | B-43 | - |
| `W-EP-03` | Disk space and performance alert remediation | R2 | B-62 | - |
| `W-EP-04` | Software deployment requests | R2 | B-63 | - |
| `W-EP-05` | Intune compliance follow-up | R1 | B-64 | - |
| `W-EP-06` | Disk encryption status and recovery key retrieval | R3 | B-64 | - |
| `W-EP-07` | Remote reboot and service restart | R2 | B-62 | - |
| `W-EP-08` | Lost or stolen device: lock, retire or wipe | R3 | B-28, B-65 | - |
| `W-EP-09` | macOS and Linux endpoint scripts | R2 | B-66 | - |
| `W-EP-10` | Hardware lifecycle and warranty forecast | R0 | B-75 | - |
| `W-EP-11` | Local admin password (LAPS) retrieval and admin-rights requests | R3 | B-64 | - |
| `W-PAT-01` | Monthly patch review and ring approval | R2 | B-67 | - |
| `W-PAT-02` | Patch compliance reporting per client | R0 | B-67 | - |
| `W-PAT-03` | Failed patch remediation | R2 | B-67 | - |
| `W-PAT-04` | Third-party application patching | R2 | B-63 | - |
| `W-PAT-05` | Emergency patch for actively exploited vulnerabilities | R2 | B-47 | - |
| `W-PAT-06` | Server patch windows and client notice | R2 | B-67 | - |
| `W-PAT-07` | Network device firmware (firewalls, switches, access points) | R3 | B-67 | - |
| `W-BDR-01` | Daily backup job review | R0 | B-68 | - |
| `W-BDR-02` | Failed backup remediation | R2 | B-68 | - |
| `W-BDR-03` | Restore requests (file, mailbox, VM) | R2 | B-69 | - |
| `W-BDR-04` | Scheduled restore tests | R1 | B-69 | - |
| `W-BDR-05` | Microsoft 365 backup coverage check | R0 | B-70 | - |
| `W-BDR-06` | Disaster recovery plan upkeep and tabletop exercise | R0 | B-70 | - |
| `W-BDR-07` | Ransomware or disaster recovery decision | R3 | B-14, B-48 | - |
| `W-BDR-08` | Backup retention and immutability review | R0 | B-70 | - |
| `W-SEC-01` | Security alert intake and grouping | R0 | B-43 | - |
| `W-SEC-02` | Alert enrichment | R0 | B-44 | - |
| `W-SEC-03` | User-reported phishing triage | R2 | B-45 | - |
| `W-SEC-04` | Business email compromise containment | R3 | B-02, B-04, B-29, B-46 | - |
| `W-SEC-05` | Endpoint isolation | R3 | B-65 | - |
| `W-SEC-06` | Vulnerability scan review and prioritization | R0 | B-47 | - |
| `W-SEC-07` | Security incident declaration and breach notification decision | R3 | B-14, B-48 | - |
| `W-SEC-08` | Threat advisory relevance check | R0 | B-47 | - |
| `W-SEC-09` | Firewall and SASE rule changes | R3 | B-48 | NN-05 |
| `W-SEC-10` | Security awareness training and phishing simulation results | R0 | B-71 | - |
| `W-CMP-01` | SOC 2 evidence collection for the MSP's own audit | R0 | B-17, B-42, B-51 | - |
| `W-CMP-02` | Client HIPAA security risk analysis support | R0 | B-52 | - |
| `W-CMP-03` | Client FTC Safeguards Rule evidence (financial clients) | R0 | B-52 | - |
| `W-CMP-04` | Change records and change advisory review | R1 | B-41, B-51 | - |
| `W-CMP-05` | Audit log integrity verification | R0 | B-02, B-10, B-17, B-51, B-82 | - |
| `W-CMP-06` | Business associate agreements and vendor due diligence tracking | R0 | B-52 | - |
| `W-CMP-07` | Policy attestations and management assertions | R3 | B-14, B-51 | - |
| `W-CMP-08` | Cyber insurance questionnaires | R0 | B-60 | - |
| `W-CMP-09` | Client security questionnaires about the MSP itself | R0 | B-60 | - |
| `W-VND-01` | License reconciliation | R0 | B-75 | - |
| `W-VND-02` | License purchase or reduction | R3 | B-14, B-31, B-75 | NN-05 |
| `W-VND-03` | Renewal alerts (subscriptions, warranties, domains) | R0 | B-75 | - |
| `W-VND-04` | Vendor and ISP escalation | R1 | B-22 | - |
| `W-VND-05` | TLS certificate expiry monitoring | R0 | B-54 | - |
| `W-VND-06` | Domain and DNS registrar changes | R3 | B-48 | NN-05 |
| `W-RPT-01` | Monthly client health report | R0 | B-71 | - |
| `W-RPT-02` | Quarterly business review draft | R0 | B-72 | - |
| `W-RPT-03` | Weekly 'what we did for you' digest | R1 | B-72, B-88 | - |
| `W-RPT-04` | Technology roadmap and budget recommendations | R0 | B-73 | - |
| `W-RPT-05` | Client AI-use policy starter | R0 | B-73 | - |
| `W-RPT-06` | Internal operations metrics (resolution time, first-contact resolution, SLA, backlog) | R0 | B-74 | - |
| `W-KB-01` | KB article drafting from resolved tickets | R1 | B-58 | - |
| `W-KB-02` | Client documentation upkeep (network, contacts, configurations) | R1 | B-59 | - |
| `W-KB-03` | Runbook and SOP authoring | R0 | B-59 | - |
| `W-KB-04` | Cited question answering for technicians (RAG) | R0 | B-56, B-57 | - |
| `W-KB-05` | Stale and conflicting article detection | R0 | B-58 | - |
| `W-KB-06` | Authorized contacts and escalation lists per client | R0 | B-34 | - |
| `W-KB-07` | Credential vault entries in the documentation platform | R3 | B-14, B-56 | - |
| `W-BIL-01` | Time entry and ticket note quality | R1 | B-76 | - |
| `W-BIL-02` | Per-seat and per-device count true-up | R0 | B-75 | - |
| `W-BIL-03` | Managed versus project or out-of-scope classification | R1 | B-76 | - |
| `W-BIL-04` | Contract terms, pricing and billing disputes | R3 | B-14 | NN-02 |
| `W-PRJ-01` | New client onboarding to the MSP (discovery and baseline) | R0 | B-77 | - |
| `W-PRJ-02` | Client offboarding from the MSP | R3 | B-77 | - |
| `W-PRJ-03` | Microsoft 365 migrations (tenant to tenant, mailbox moves) | R3 | B-77 | NN-04 |
| `W-PRJ-04` | Copilot and AI adoption readiness for clients | R0 | B-53 | - |
| `W-PRJ-05` | Azure infrastructure projects | R3 | B-85, B-86 | - |
| `W-PRJ-06` | Project scoping and estimates | R0 | B-60 | - |
| `W-TOOL-01` | Lever authoring (new PowerShell or Python lever) | R1 | B-01, B-13, B-14, B-15, B-16, B-28, B-42 | - |
| `W-TOOL-02` | Model gateway and routing configuration | R1 | B-12, B-78, B-80, B-90 | - |
| `W-TOOL-03` | Prompt library and standards | R0 | B-20 | - |
| `W-TOOL-04` | Eval golden sets and accuracy reports | R0 | B-06, B-84 | - |
| `W-TOOL-05` | Prompt-injection corpus and guard maintenance | R0 | B-79 | - |
| `W-TOOL-06` | Approval queue operation | R1 | B-03, B-10, B-26, B-82, B-89 | - |
| `W-TOOL-07` | CI/CD pipelines and release process | R1 | B-07, B-08, B-27, B-84, B-86, B-98 | - |
| `W-TOOL-08` | Secrets and managed identity management | R3 | B-85 | - |
| `W-TOOL-09` | Production monitoring of AI and automation | R0 | B-80, B-81, B-83 | - |
| `W-TOOL-10` | MCP server and Teams technician assistant | R1 | B-87, B-88 | - |
| `W-TOOL-11` | PSA, RMM and Graph integration maintenance | R1 | B-18, B-19, B-91 | - |
| `W-TOOL-12` | Review of existing automation scripts | R0 | B-97 | - |
| `W-TOOL-13` | Use-case intake and ROI scoring | R0 | B-06, B-08, B-09, B-95 | - |
| `W-TOOL-14` | Emerging technology evaluation | R0 | B-78, B-97 | - |
| `W-GOV-01` | AI acceptable-use policy and data-in-prompt rules | R0 | B-55, B-92 | - |
| `W-GOV-02` | Model and tool approval | R3 | B-90, B-93 | - |
| `W-GOV-03` | Agent identity and lever permission review | R0 | B-01, B-49 | - |
| `W-GOV-04` | AI incident response | R3 | B-02, B-41, B-94 | - |
| `W-TRN-01` | Technician training: reading suggestions and approvals | R0 | B-96 | - |
| `W-TRN-02` | Account manager training: explaining AI to clients | R0 | B-11, B-96 | - |
| `W-TRN-03` | Correction feedback loop coaching | R0 | B-74 | - |
| `W-TRN-04` | New technician onboarding and performance coaching | R3 | B-14, B-74 | NN-03 |

## Conflicts and gaps found while mapping

| Id | Finding | Handling |
|---|---|---|
| RF-01 | Inventory risk classes (01) and governance risk classes (05) disagree for some levers (for example `W-IDM-02` R3 vs `user.reset-mfa` R2). | Registry uses governance classes (`B-01`). `B-06` lists mismatches. Resolved: identity changes are R3 in both maps (D-024, D6-07). |
| RF-02 | The issue template and DOD-10 call for an **impact chain id**. When this roadmap was drafted no impact-chain map existed; `docs/map/02-impact-chains.md` and `map/impact.json` have since landed (synthesis pass, 2026-10-20). | Resolved: a chain has no separate id. **The impact chain id is the inventory id it traces** (chain `W-IDM-02` in `map/impact.json`), so an item cites the chains of its `inventory_ids`. `map/check_map.py` proves every automatable inventory item has exactly one chain. The PR's L1 to L4 lines and the lever's `impact` field carry the same trace. |
| RF-03 | Client records (`config/clients/*.json`) are under the protected `config/**` path. | Adding a client is change-managed by design: owner entry step `W2-E1`. The schema (`B-13`) and the loader (`B-18`) are agent work. |
| RF-04 | `pyproject.toml` (protected) limits `pytest` to `tests/phase1` and `mypy` to `core`. | New Python suites run through `tests/py/Test-Py.ps1` with explicit paths (no pyproject change). Widening mypy is an owner entry step once `B-27` makes the code pass. |
| RF-05 | Acceptance ids `B<nn>-<k>` are a new spec prefix under STD-TS-2. | Recorded as a DECISIONS entry in the W1 exit fold. |
| RF-06 | Branch protection on a **private** repository may need a paid GitHub plan; the owner's rule is free tools only. | See `docs/map/04-repo-organization.md` section 6.5. Required checks are enforced by convention plus CI until that is resolved (RQ-03). |
| RF-07 | `user.reset-password` and TAP issue secrets, which must never reach an agent, the audit or a prompt. | `B-30` adds an out-of-band channel, and a sweep test proves no secret-shaped value lands anywhere else. |

## Open questions only the owner or the MSP can answer

| Id | Question | Who | Blocks |
|---|---|---|---|
| RQ-01 | Which risk class rule wins where the inventory and governance maps disagree (RF-01)? **Decided: see 06-decisions.md D6-07.** | The owner | `B-01` values; W3 lever classes |
| RQ-02 | Approve the W1 scope, calendar and cut line, including the visible demo changes (verification field, masked phone numbers, scoped queue listing)? **Decided: see 06-decisions.md D6-32.** | The owner | W1 start |
| RQ-03 | GitHub: keep the repo private (branch protection may not be enforced on the free plan) or make it public (D-008)? Create the labels and milestones with `gh` yourself? **the owner's call: see 06-decisions.md J-01, J-02** (recommendation there). | The owner | `B-08` |
| RQ-04 | Is it acceptable for each wave's protected-file changes to be applied by you as entry steps (pyproject, CI, config), as this roadmap assumes? **the owner's call: see 06-decisions.md J-03** (recommendation there). | The owner | every wave |
| RQ-05 | Which PSA, RMM, backup and documentation products does the MSP run, and would they want issues in GitHub or Azure Boards (the exporter, `B-09`, does both)? **Decided: see 06-decisions.md D6-01, D6-02.** | The MSP | W2 adapters, W6 |
| RQ-06 | Who approves R2 and R3 changes, and should R3 really need two approvers (lead plus Technical Services Manager)? **Decided: see 06-decisions.md D6-05.** | The MSP | `B-28`, `B-65` |
| RQ-07 | How do technicians verify a caller today, and is callback-on-file acceptable as the recorded method? **Decided: see 06-decisions.md D6-06.** | The MSP | `B-02`, `B-03` wording |
| RQ-08 | Is backup and disaster recovery in scope for this role? **Decided: see 06-decisions.md D6-24.** | The MSP | W6 backup items `B-68` to `B-70` |
| RQ-09 | Which installs are approved: Pester 5 and PSScriptAnalyzer, the Bicep CLI, a vector store, OpenTelemetry, Docker? **the owner's call: see 06-decisions.md J-04** (recommendation there). | The owner | W3, W5, W8, W9, W10 |
| RQ-10 | Which clients may ever have ticket text processed by a model (local or hosted), and under which BAA or contract terms? **Decided: see 06-decisions.md D6-11.** | The MSP | `B-55`, `B-90`; hosted stays off until then |
| RQ-11 | Confirm the demo date. W1's calendar, freeze time and the tag `demo-2026-10-27` assume Oct 27; if the date moves, shift the calendar and rename the tag before W1 starts. **the owner's call: see 06-decisions.md J-05** (recommendation there). | The owner | W1 calendar, `W1-X5` |
| RQ-12 | Approver sign-in (`C-44`, `B-89`) lands in W9, but R3 dual approval (`B-28`) and device wipe (`B-65`) arrive in W3 and W6, so until W9 every approval rests on the demo identity picker. Pull the design and mock-token part of `B-89` forward to W3? **Decided: see 06-decisions.md D6-05.** | The owner | `B-28`, `B-65`, `B-89` |
| RQ-13 | Business-hours and after-hours rules (`B62-2` reboot, `B65-3` device R3) need the runner, because a handler sees only state and params (STD-LV-8), yet no runner owner (`B-28`, `B-42`) has an acceptance test for them. Add them to `B-42` (it already owns time-window caps) or give `B-65` the runner in W6? **Decided: see 06-decisions.md D6-08.** | The owner | `B-42`, `B-62`, `B-65` |

## Sources

Repo: `docs/map/01-work-inventory.md`, `map/inventory.json`, `docs/STANDARDS.md`, `docs/map/03-architecture-target.md`, `docs/map/05-governance.md`, `map/controls.json`, `docs/BLUEPRINT.md`, `docs/COVERAGE.md`, `docs/DEMO.md`, `specs/slices-abc.md`, `.github/`, `CONTRIBUTING.md`. Job context: the public posting and the owner's company brief (read-only).

Public facts referenced (read 2026-10-20 unless noted; anything not re-read is marked in the item):
- Microsoft Graph `revokeSignInSessions` (lag, guest limits, `User.RevokeSessions.All`): https://learn.microsoft.com/graph/api/user-revokesigninsessions (as cited in the governance map)
- Microsoft Graph throttling (429, `Retry-After`): https://learn.microsoft.com/en-us/graph/throttling
- GDAP introduction: https://learn.microsoft.com/en-us/partner-center/customers/gdap-introduction
- PowerShell approved verbs and `Test-Json`: https://learn.microsoft.com/en-us/powershell/scripting/developer/cmdlet/approved-verbs-for-windows-powershell-commands, https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/test-json
- CISA Known Exploited Vulnerabilities catalog (shape for `B-47` fixtures; shape to be verified on the build date): https://www.cisa.gov/known-exploited-vulnerabilities-catalog
- GitHub protected branches (plan availability; see 04 section 6.5): https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
