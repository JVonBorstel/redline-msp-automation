# AI policy

Status: **document-only** (a policy for people; the rules marked "enforced" are built in the code paths named). Owner: the compliance owner role; changes approved by the AI change approver role (D6-17: roles, not names). Review: proposed every six months (UNVERIFIED: no review cycle is set in the repo; the compliance owner chooses), and whenever a data class, a hosted provider or the never-automate list changes.

> Synthetic data only. Not legal advice. Independently built prototype. Not affiliated with any vendor's or real company's systems. A starter for the compliance owner and counsel to review; it extends any AI change process the MSP already has.

## 1. Scope

Everyone at the MSP who uses AI in client work: technicians, leads, engineers and account managers. It covers this tool and any other AI tool (chat assistants, code assistants, browser plug-ins). The day-to-day rules are in `governance/ACCEPTABLE_USE.md`; where each data class may go is in `governance/DLP_MAPPING.md`.

## 2. Five rules

1. **AI proposes, people decide.** A model may suggest a lever and fill its fields. The lever runner (`core/levers/runner.py`) decides whether it runs, under the lever's own `approval` field; an agent can only dry-run a change. Client-facing text is drafted by AI and sent by a person.
2. **Only registered levers act.** Nothing a model writes is executed as code, shell or SQL. A lever is registered in `levers/registry.json` (and its `levers/registry.d/` fragments), or it does not exist.
3. **Local first.** The default model runs on this machine. Hosted models are off (`config/models.json`) and are turned on only by the approval process (`C-28`, `B-93`) plus a decision record.
4. **One client per call.** A prompt, a lever call and an approval each belong to exactly one client.
5. **Ticket text is untrusted.** Instructions inside a ticket, email or document are wrapped as data (`core/guard/wrap.py`) and checked by a heuristic detector (`detect_injection` in `core/guard/detect.py`), never followed. This is not a guarantee: a missed injection is possible, and the lever permissions are the real control.

## 3. Data classes

Every piece of text in AI work has one class. The class decides what may enter a prompt, a log or an index (`governance/DLP_MAPPING.md`).

| Class | Meaning | Example |
|---|---|---|
| DC-0 | Public | a published KB article |
| DC-1 | MSP internal | a runbook, a ticket category |
| DC-2 | Client confidential | a client's network diagram |
| DC-3 | End-user PII | a name, UPN or phone number |
| DC-4 | PHI (dental and healthcare clients) | a patient name in a ticket |
| DC-5 | NPI (financial, legal, accounting clients) | an account number, an SSN |
| DC-6 | Credentials and secrets | a password, an API key, a recovery key |

- **Unknown is high.** Unlabelled text takes the client's floor: dental DC-4; financial, RIA, legal, accounting and other DC-5; no client record DC-5.
- **Highest wins.** One SSN makes the whole ticket DC-5.
- **DC-6 goes nowhere.** No prompt, no log, no index, no ticket body.

**Enforced in code today** (`B-55`): the class and floor (`core/guard/classify.py`); placeholders for PHI, NPI and PII before any prompt, and a hard block on DC-6 (`core/guard/redact_prompt.py`); refusal of DC-4 and DC-5 on any hosted route (`core/gateway/gateway.py`); secret redaction before every audit write (`core/audit/redact.py`). The shape rules are a tripwire, not a guarantee: names without a cue word are not found, so people still must not paste regulated data where it does not belong.

## 4. The never-automate list

`governance/never-automate.json` lists the work that stays with people: 22 entries today, from urgent terminations and caller identity checks to breach notification decisions and AI incident response. The lever registry refuses to load any lever whose name matches an entry (`core/levers/registry.py`). Changing the list needs a decision record. Decisions about a person's access to lending, housing, insurance, employment, healthcare, legal or education services also stay human (D6-19). The full list in plain words is in `governance/ACCEPTABLE_USE.md`.

## 5. Hosted models and new tools

A hosted model, MCP server or new AI tool is used for client data only after the AI change approver records an approval with retention and training terms, a signed BAA for that exact service and configuration where DC-4 may be present (`BA-3` in `docs/map/05-governance.md`), and the client's data-handling setting (`C-28`, `B-93`). Until then only DC-0 may go to such a tool. The client record's `model_processing` field defaults to `none` (D6-11), but it is only a schema field today and nothing in `core` reads it; hosted providers are off because `config/models.json` disables them.

## 6. Accountability and incidents

- Every lever call writes a hash-chained audit record; `uv run python -m core.audit.verify` proves the chain is intact.
- Any lead may pause a lever at once, without approval (`LeverRunner.pause` in `core/levers/runner.py`).
- Report a wrong automated action, a leak or a suspected prompt injection to the on-call lead at once. Breach determination and notification stay with people, the client and counsel (never-automate `W-SEC-07`; the notice duties are UNVERIFIED, see `docs/map/05-governance.md` `BA-5`). The AI incident runbook is planned (`B-94`).
- Breaking this policy: the consequence is the MSP's own to set (UNVERIFIED: the repo names no HR or disciplinary process). AI metrics never rank technicians (D6-22, a proposal for leadership).

## 7. Unverified

Nothing here is a legal reading. For the compliance owner and counsel to confirm: which regulations apply to which client (`docs/map/05-governance.md` sections 1 to 3 hedge them); the review cycle; the consequence for breaking the policy; the breach notice duties (`BA-5`); who holds the owner and approver roles; and whether the Colorado AI Act reaches any client use (D6-19, status unverified).
