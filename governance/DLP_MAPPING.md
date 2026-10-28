# DLP mapping: what each data class may enter

Status: **document-only** (a mapping page; the rows marked "enforced" are built in the code paths named, the rest are rules for people). Owner: the compliance owner role (D6-17). Review: when `docs/map/05-governance.md` section 1 changes; a test fails until this page matches it.

> Synthetic data only. Not legal advice. Independently built prototype. Not affiliated with any vendor's or real company's systems. Every regulatory statement here is a map for the compliance owner and counsel to confirm.

Used by `governance/AI_POLICY.md` and `governance/ACCEPTABLE_USE.md`. Data loss prevention (DLP) here means: which data may go where in AI work.

## 1. The mapping

The first three "May enter" columns are copied word for word from `docs/map/05-governance.md` section 1. `tests/py/governance/test_b92_policy.py` compares them cell by cell, so this table cannot drift from the map.

| Id | Class | May enter a local model prompt? | May enter a hosted model prompt? | May enter the audit log? | May enter a retrieval index? |
|---|---|---|---|---|---|
| `DC-0` | Public | yes | yes | yes | yes, MSP-internal namespace |
| `DC-1` | MSP internal | yes | yes, with an approved provider (C-28) | yes | yes, MSP-internal namespace |
| `DC-2` | Client confidential | yes, scoped to that client (ISO-1) | only with an approved provider and the client's data-handling setting (C-28) | identifiers only | only that client's namespace (ISO-2) |
| `DC-3` | End-user PII | minimum necessary, scoped to that client | redacted by default (C-25) | identifiers needed for evidence (UPN, object id); never read results (D-017) | only that client's namespace (ISO-2), minimum necessary |
| `DC-4` | PHI (dental and other healthcare clients) | only if the model host is covered (local machine under the MSP's BA safeguards), minimum necessary | **no**, unless the provider has a signed BAA for that exact service and configuration (BA-3) | **never**; tokenised reference only | no (not set by the map; unknown is high) |
| `DC-5` | NPI / customer information (financial clients: RIAs, accountants, lenders) | minimum necessary, scoped | **no** by default; only with provider due diligence and contract terms (GLBA-3) | **never** | no (not set by the map; unknown is high) |
| `DC-6` | Credentials and secrets | **never** | **never** | **never** (redacted, C-10) | **never** |

**Where the index column comes from.** The map's section 1 table has no index column; it only says the class "decides what may enter a prompt, a log, a retrieval index or a hosted model". This column is derived, not copied: DC-0 and DC-1 follow the MSP-internal namespace of `ARC-12` (map 03); DC-2 and DC-3 follow `ISO-2` (one namespace per client); DC-4 and DC-5 are "no" because the map sets no rule and rule 1 says unknown is high; DC-6 follows rule 4 (secrets never leave a vault). No retrieval index exists in the repo yet (RAG is Phase 5, `C-26`), so nothing enforces this column today. The compliance owner should confirm or change it.

Rules that apply to every row (map section 1): unknown is high; the class of a text is the highest class of anything in it; the client's industry sets the floor; secrets never leave a vault; logs carry identifiers, not content.

## 2. The unknown-text floor per client industry

Text whose class nobody declared takes its client's floor. Copied from `INDUSTRY_FLOOR` and `DEFAULT_FLOOR` in `core/guard/classify.py`; the test compares them.

| Client industry | Floor |
|---|---|
| dental | DC-4 |
| financial | DC-5 |
| ria | DC-5 |
| legal | DC-5 |
| accounting | DC-5 |
| other | DC-5 |
| no client record | DC-5 |

## 3. What the code enforces today

| Rule | Enforced where | Proof |
|---|---|---|
| Every gateway text gets a class DC-0 to DC-6; shapes raise it, text cannot lower it | `core/guard/classify.py` | `tests/py/guard/test_b55_redaction.py` |
| PHI, NPI and PII spans become typed placeholders before any model reads the text | `core/guard/redact_prompt.py` | same file, `test_b55_2_*` |
| DC-6 text is blocked: no model is called, not even the mock | `core/guard/redact_prompt.py`, `core/gateway/gateway.py` | `test_b55_2_dc6_canaries_block_the_call_before_any_provider` |
| DC-4 and DC-5 text is refused on a hosted route whatever config says | `HOSTED_REFUSED_FROM` in `core/gateway/gateway.py` | `test_b55_3_hosted_routes_refuse_dc4_and_dc5_text` |
| Hosted providers are off and local models are loopback only | `config/models.json`, `core/gateway/hosted.py`, `core/gateway/loopback.py` | `tests/phase1/test_gateway.py` |
| Secret-named and secret-shaped values are redacted before an audit write | `core/audit/redact.py`, called from `core/audit/chain.py` | `tests/phase1/test_audit.py` |

**Not enforced in code (people follow the rule):** the DC-1 to DC-3 hosted conditions (no approval gate exists, `C-28` planned; today the gateway would send redacted DC-0 to DC-3 text to a hosted route only if someone enabled one); the audit-log column beyond secrets (the audit record holds lever parameters and the change diff, not ticket text, but no scanner rejects PHI there); the index column; the client record's `model_processing` field (a schema field in `adapters/binding.py`; nothing in `core` reads it, so it does not stop a call); AI tools outside this repo.
