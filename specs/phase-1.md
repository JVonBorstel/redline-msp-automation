# Phase 1 spec: foundation (gateway, levers, audit, identity)

Status: spec written 2026-10-20, before code (blueprint section 7). Built one work item per deliverable, each merged only after CI is green and the owner says yes.

## Goal
Every later workflow runs through four pieces:
1. **A model gateway** with one interface.
2. **A lever registry** that enforces permissions in code.
3. **A hash-chained audit log** with a verifier.
4. **Agent identities** with per-client scoping.

The phase is done when the four proof tests from the blueprint pass and a technician can run the demo from the README offline.

## Deliverables
1. **`core/identity`.**
   - **Identities:** agents and humans, each with an id, a role (`technician`, `lead`, `agent`) and an allowed client list.
   - Loaded from `config/identities.json` (synthetic).
   - Unknown identity → denied.
2. **`core/levers`.** A registry that loads lever definitions from `levers/registry.json`.
   - **Fields per lever:** name, description, client scope (`any` or a list), required role, class (`read` | `write`), `approval` (`none` | `lead`), idempotency key fields, parameter schema (types, required, enum, max length, regex), `dryRun` support, timeout.
   - **Invoke:** `Invoke(lever, params, identity, client, mode = dry-run | execute, approval?)`. It:
     1. validates params against the schema;
     2. checks the identity's role and client;
     3. checks the lever's client scope;
     4. requires an approval record for `approval: lead` in execute mode;
     5. runs dry-run by default (returns a diff and changes nothing);
     6. enforces the timeout;
     7. rejects unregistered levers.
   - Every call (allowed or denied) writes an audit record.
3. **`core/audit`.**
   - **Log:** append-only JSONL. Each record has: seq, ts, agent, client, lever, params (secrets redacted), mode, result, approver, prevHash, hash (SHA-256 over the canonical record + prevHash).
   - **Verifier CLI:** `audit verify <file>` exits 0 on an intact chain and non-zero on the first broken record, naming its seq.
   - **Head pin:** the head hash is written to a separate head file, so truncating the log is also detected.
4. **`core/gateway`.**
   - **Interface:** `Complete(task, input) -> {text, model, provider, ms}`.
   - **Providers:**
     - `mock`: deterministic, fixture-driven, the default.
     - `ollama`: OpenAI-compatible HTTP to 127.0.0.1 only; model names come from `config/models.json`.
     - Hosted adapters are stubs behind a flag and off.
   - **Routing:** `config/routing.json` maps the task type (`classify`, `summarize`, `reason`) to a provider and model.
   - **Untrusted data:** the gateway never passes tool or permission decisions to the model output without registry validation.
5. **`core/guard`.**
   - **Untrusted-input marker:** ticket, email and document text is wrapped and labelled as data.
   - **Injection detector:** a simple heuristic plus a corpus of 30 cases that flags instruction-like text (for example "ignore previous", "you are now", hidden HTML, requests to call levers).
   - **Flagging:** flagged input is reported, never obeyed.
6. **Sample levers**, mock-backed and synthetic:
   - `ticket.get` (read);
   - `user.reset-mfa` (write, approval: lead, dry-run diff);
   - `user.disable` (write, approval: lead);
   - `kb.search` (read, scoped per client).
7. **Docs:** update ARCHITECTURE (with a mermaid flow), DECISIONS, COVERAGE, and README "how to run the demo".

## Acceptance tests (written first; CI runs them)
- **P1-1 Cross-client refused:** a technician scoped to Contoso Dental calling `ticket.get` for Fabrikam Capital is denied, and the denial is in the audit log.
- **P1-2 Tamper detected:**
  - change one byte of a middle audit record → the verifier names that seq;
  - delete the last record → the verifier detects it via the head pin;
  - an intact log → exit 0.
- **P1-3 Dry-run changes nothing:** `user.reset-mfa` in dry-run returns a diff, leaves the mock tenant state byte-identical, and writes an audit record with mode `dry-run`.
- **P1-4 Unregistered or out-of-scope lever denied and logged:**
  - a lever name not in the registry → denied;
  - an agent identity calling a `write` lever its role lacks → denied;
  - both are audited.
- **P1-5 Approval gate:**
  - `user.disable` in execute mode without a lead approval record → denied;
  - with one → allowed;
  - the approver is recorded.
- **P1-6 Schema:** a missing required param, the wrong type, a value over max length, or an enum violation → each is denied with a clear reason.
- **P1-7 Injection:** each of the 30 corpus cases is flagged; 20 benign tickets are not flagged. Precision and recall are printed and labelled fixture-based.
- **P1-8 Gateway:**
  - the mock is deterministic (same input → same output);
  - routing picks the configured provider;
  - an ollama URL that is not localhost is refused;
  - a provider that is down returns an error object, never a crash.
- **P1-9 Secrets:** a param named like `password` or `token`, or a value shaped like a secret, is redacted in the audit log.

## Out of scope
Real Microsoft Graph calls, any cloud resource, UI (Phase 2+), and RAG (Phase 5).

## Language
- **Python:** the core (Python 3.11 via uv: pydantic v2 schemas, pytest), if the owner approves installing uv.
- **PowerShell:** the levers, in PowerShell 7.
- **If uv is not approved:** the core is PowerShell 7 too, with plain-PowerShell tests like Phase 0. The acceptance tests above stay the same either way.
