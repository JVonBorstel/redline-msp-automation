# Model and tool approval process

Status: **built** for the record format and the checker (tests pass on this repo's files); the sign-offs in the committed records are **placeholders** (see section 8). Owner: the `compliance-owner` role; decisions by the `ai-change-approver` role (D6-17: roles, not names). Controls `C-28`, `C-43`. Spec: `specs/B-93.md`.

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only. Not a certification, an attestation or a compliance claim. Not legal advice. It is a starter for the `compliance-owner` and counsel to review, and it extends any AI change process the MSP already has.

## 1. The rule

New AI tools arrive through a door, not a side window. A model, a provider, an MCP server, a lever namespace or an adapter is used only when `governance/model_tool_approvals.json` holds an approved, in-date record for it, with evidence that exists in the repo. A hosted provider also needs an entry in `governance/ai-vendor-register.json` (B-90), and that entry is added only through this process: this is the only way an entry gets there. `AI_POLICY.md` section 5 says why; this page says how.

## 2. What needs a request

| Kind | `subject` is | Example |
| --- | --- | --- |
| `model` | `provider/model-name` from `config/models.json` | `ollama/llama3.2:3b` |
| `provider` | an enabled provider in `config/models.json` | `ollama` |
| `mcp-server` | the server name in `mcp/server.py` | `redline-levers` |
| `lever-namespace` | the part of a lever name before the dot | `ticket` |
| `adapter` | a folder under `adapters/` | `psa` |

A new lever inside an approved namespace is covered by that namespace's record, but a new lever still goes through the lever registry rules (risk class, undo, never-automate list). A new namespace needs its own request.

## 3. Who does what

| Role | Does |
| --- | --- |
| `technician`, `automation-engineer`, `lead` | **Propose.** Fill the request from `governance/templates/ai-change-request.md`, attach the evidence, name the owner role. The proposer's role may not also approve (`self-approval`). |
| `technical-reviewer` | Checks the evidence is what it says and the rollback works. Advisory; never enough alone. |
| `ai-change-approver` | **Approves.** Required on every approved record. |
| `security-lead` | Also required when the risk class is R2 or R3, the thing is hosted, or data classes DC-4 or DC-5 are named. |
| `compliance-owner` | Same cases as `security-lead`. Owns this process and the retention, BAA and ZDR facts. |

Any reviewer who rejects blocks the record (`reviewer-rejected`). Roles are on configuration, never names. Who holds each role at the MSP is UNVERIFIED and for the `compliance-owner` to set.

## 4. Evidence an approval must carry

Every approved record lists evidence links. The checker requires these types and that each link exists:

| Kind | Required evidence types |
| --- | --- |
| `model` | `eval_report` (a file under `evals/`) and `redaction_test` (`tests/...py::test_name`) |
| `provider`, `mcp-server`, `lever-namespace`, `adapter` | `contract_test` and `redaction_test` (both `tests/...py::test_name`) |

- **Eval report:** fixture-based results for the thing, in `evals/`. Real-data quality is not claimed.
- **Contract test:** a test that the thing behaves as its interface says. The checker proves the test name is defined in the file; it does not run it.
- **Redaction test:** a test that sensitive text is not leaked through it (B-55 gate, audit redaction, or the like).
- **Retention terms:** for anything `hosted`, the provider's retention and training terms in `retention_terms` (a short summary; the document itself is kept where `approval_ref` points).
- **BAA or ZDR status:** `baa_status` and `zdr_status`. DC-4 on a hosted route needs a signed BAA for that exact service (`baa-required`); DC-5 needs a signed BAA or confirmed ZDR. The gateway still refuses DC-4 and DC-5 text on a hosted route unless the register allows the class (B-55, B-90).
- **Rollback:** how to switch it off and what stops working.
- DC-6 (credentials and secrets) is never an allowed data class.

## 5. Steps

1. Copy the template, fill it as a record with `status: "draft"`, and add it to `governance/model_tool_approvals.json` in a pull request. Nothing covers a draft.
2. Add the evidence. Run `uv run --frozen python -m workflows.assurance.approvals check`.
3. Reviewers record their decisions in `reviewers` (role, decision, date). The `ai-change-approver` sets `status: "approved"`, `approved_on` and a `review_date`.
4. For a hosted provider, the same pull request adds or updates the entry in `governance/ai-vendor-register.json` with `approval_ref` set to the provider record's id. The checker fails an approved vendor entry that no approved `provider` record names (`vendor-unrecorded`).
5. Merge needs the repo owner's review as usual (`CONTRIBUTING.md`). Agents never approve or merge.
6. After `review_date` the approval stops covering anything (`expired`). Re-review or remove the thing.
7. To withdraw: set `status: "revoked"` and switch the thing off using its `rollback`.

## 6. What the checker fails on

`uv run --frozen python -m workflows.assurance.approvals check [--as-of YYYY-MM-DD]` exits 0 clean, 1 on any problem, 2 on bad input. Codes:

| Code | Means |
| --- | --- |
| `missing-record` | A model or enabled provider in config, a lever namespace in the registry, an adapter folder or the MCP server has no approved, in-date record |
| `not-approved` | The record is draft, revoked or rejected |
| `expired` | Today is after `review_date` |
| `not-yet-in-effect` | `approved_on` is in the future |
| `duplicate-subject` | Two records for the same kind and subject |
| `evidence-required` | A required evidence type is absent |
| `evidence-missing` | A cited file does not exist, or a cited test name is not defined in its file |
| `evidence-bad-ref` | A link is absolute, leaves the repo, is not under `evals/` or `tests/`, or a test link has no `::test_name` |
| `approver-missing` | The `ai-change-approver`, or for the heavier cases the `security-lead` or `compliance-owner`, has not approved |
| `self-approval` | The proposer's role also approved |
| `reviewer-rejected` | A reviewer rejected |
| `review-after-approval` | A decision is dated after `approved_on` |
| `hosting-mismatch` | The record's `hosting` disagrees with the provider (azure_openai and anthropic are hosted) |
| `baa-required` | DC-4 or DC-5 on a hosted route without the BAA or ZDR the rule asks for |
| `vendor-unknown` | A hosted record names a vendor id that is not in the register |
| `vendor-wrong-provider` | The vendor entry is for another provider |
| `vendor-not-approved` | The vendor entry is pending or revoked |
| `vendor-overdue` | The vendor entry is past its review date |
| `vendor-classes-exceed` | The vendor entry allows a data class the record does not |
| `vendor-unrecorded` | An approved vendor entry is not backed by an approved `provider` record that names it |

Record shape (unknown fields are refused): `governance/model_tool_approval.schema.json`, generated from `workflows/assurance/approvals.py` (`python -m workflows.assurance.approvals schema [--write]`).

## 7. Worked example (synthetic)

Contoso Dental (synthetic) wants a hosted Azure OpenAI model, `gpt-example`, to summarise tickets with only DC-0 and DC-1 text. The proposer is an `automation-engineer`. The provider record comes first because the vendor entry cites it:

```json
{
  "id": "AC-901",
  "kind": "provider",
  "subject": "azure_openai",
  "title": "Azure OpenAI provider for Contoso Dental summaries",
  "inventory_ids": ["W-TOOL-02", "W-GOV-02"],
  "owner_role": "automation-engineer",
  "proposed_by_role": "automation-engineer",
  "purpose": "Summarise Contoso Dental tickets with DC-0 and DC-1 text only. Not for DC-2 and above.",
  "risk_class": "R1",
  "data_classes": ["DC-0", "DC-1"],
  "hosting": "hosted",
  "retention_terms": "synthetic: no retention beyond the request, no training on inputs",
  "baa_status": "not-applicable",
  "zdr_status": "confirmed",
  "vendor_approval_id": "azure-openai-contoso",
  "evidence": [
    {"type": "contract_test", "ref": "tests/py/gateway/test_b90_hosted.py::test_b90_2_the_adapter_builds_one_request_from_resolved_references"},
    {"type": "redaction_test", "ref": "tests/py/guard/test_b55_redaction.py::test_b55_3_eval_refuses_every_ticket_on_the_hosted_route_and_serves_it_locally"}
  ],
  "reviewers": [
    {"role": "ai-change-approver", "decision": "approve", "on": "2026-10-27"},
    {"role": "security-lead", "decision": "approve", "on": "2026-10-27"},
    {"role": "compliance-owner", "decision": "approve", "on": "2026-10-27"}
  ],
  "rollback": "Set providers.azure_openai.enabled to false; routes fall back to the local provider.",
  "status": "approved",
  "approved_on": "2026-10-27",
  "review_date": "2027-04-27"
}
```

The model record, same reviewers, with an eval report as evidence (the report here is a stand-in: a real request attaches a new run for this model):

```json
{
  "id": "AC-902",
  "kind": "model",
  "subject": "azure_openai/gpt-example",
  "title": "gpt-example for ticket summaries",
  "inventory_ids": ["W-TOOL-02", "W-GOV-02"],
  "owner_role": "automation-engineer",
  "proposed_by_role": "automation-engineer",
  "purpose": "Ticket summaries for Contoso Dental, DC-0 and DC-1 only.",
  "risk_class": "R1",
  "data_classes": ["DC-0", "DC-1"],
  "hosting": "hosted",
  "retention_terms": "synthetic: no retention beyond the request, no training on inputs",
  "baa_status": "not-applicable",
  "zdr_status": "confirmed",
  "vendor_approval_id": "azure-openai-contoso",
  "evidence": [
    {"type": "eval_report", "ref": "evals/routing/report.md"},
    {"type": "redaction_test", "ref": "tests/py/guard/test_b55_redaction.py::test_b55_3_eval_refuses_every_ticket_on_the_hosted_route_and_serves_it_locally"}
  ],
  "reviewers": [
    {"role": "ai-change-approver", "decision": "approve", "on": "2026-10-27"},
    {"role": "security-lead", "decision": "approve", "on": "2026-10-27"},
    {"role": "compliance-owner", "decision": "approve", "on": "2026-10-27"}
  ],
  "rollback": "Remove the alias from providers.azure_openai.models in config/models.json.",
  "status": "approved",
  "approved_on": "2026-10-27",
  "review_date": "2027-04-27"
}
```

Only then does the same pull request turn the pending Azure entry in the vendor register into this approved one (`approval_ref` is the provider record's id, and the classes may not exceed the record's):

```json
{
  "id": "azure-openai-contoso",
  "provider": "azure_openai",
  "name": "Azure OpenAI",
  "status": "approved",
  "allowed_data_classes": ["DC-0", "DC-1"],
  "clients": ["contoso-dental"],
  "purposes": ["summarise"],
  "retention_terms": "synthetic: no retention beyond the request, no training on inputs",
  "review_date": "2027-04-27",
  "approved_by": "ai-change-approver",
  "approved_on": "2026-10-27",
  "approval_ref": "AC-901"
}
```

With the config enabling `azure_openai` and the model, the checker passes. Remove the provider record and `vendor-unrecorded` and `missing-record` fail; change the data classes to include DC-4 without a signed BAA and `baa-required` fails; wait past 2027-04-27 and `expired` fails. These three cases are in `tests/py/governance/test_b93_approval.py`. This example is not in the committed records or register; nothing hosted is approved in this repo.

## 8. Limits

- The committed records (`AC-001` to `AC-028`) are a baseline of what existed on 2026-10-27. They were written by the prototype's builder, and their reviewer entries are role placeholders, not real sign-off. The MSP's `ai-change-approver` has to re-decide them. Until then they show the format works, not that anyone accountable agreed.
- The checker proves files, names and dates agree. It does not run the cited tests, judge whether an eval report is good, or check the retention terms against a provider's real contract (UNVERIFIED for every provider; no vendor page was opened).
- Evidence for lever namespaces and adapters is shared tests (registry and runner gates, adapter contract table), not a test per namespace. Data classes and risk classes in the records are declared, not measured.
- `config/models.json` and the registry are the only inputs. A tool that never appears there (a script, a browser extension, an outside chatbot) is not seen; `ACCEPTABLE_USE.md` covers those for people.
- `model_processing` on a client record is still only a schema field (see `AI_POLICY.md`). This process does not change that.
- Review cadence (six months in the records) is a proposal for the `compliance-owner` to confirm.
