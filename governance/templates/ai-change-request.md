# AI change request (model, provider, MCP server, lever namespace or adapter)

Status: template. Process: `governance/MODEL_TOOL_APPROVAL.md`. Controls `C-28`, `C-43`.

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only. Roles, never names. No endpoints, keys or secrets.

The request is a record in `governance/model_tool_approvals.json`. Copy the block below into that file's `records` list, keep `status` as `draft` until the reviewers have decided, then run `uv run --frozen python -m workflows.assurance.approvals check`.

## Fields in plain words

| Field | Fill in |
| --- | --- |
| Inventory id | `inventory_ids`: the work inventory ids (W-AREA-nn) it serves |
| Risk class | `risk_class`: R0 to R3, as the lever registry defines them |
| Data classes | `data_classes`: every class it may touch, DC-0 to DC-5 (DC-6 never) |
| Rollback | `rollback`: how to switch it off and what stops working |
| Owner | `owner_role`: the role that owns it |
| Purpose | `purpose`: what it is for, and what it is not for |
| Evidence | `evidence`: eval report (models), contract test and redaction test (everything else), as `evals/...` or `tests/...py::test_name` |
| Hosted terms | `retention_terms`, `baa_status`, `zdr_status`, `vendor_approval_id`: only when `hosting` is `hosted` |
| Reviewers | `reviewers`: filled by the reviewers, not the proposer |

## Record to copy

```json
{
  "id": "AC-000",
  "kind": "adapter",
  "subject": "example",
  "title": "Short name of the request",
  "inventory_ids": ["W-GOV-02"],
  "owner_role": "automation-engineer",
  "proposed_by_role": "automation-engineer",
  "purpose": "What it is for and what it is not for.",
  "risk_class": "R1",
  "data_classes": ["DC-0"],
  "hosting": "local",
  "retention_terms": null,
  "baa_status": "not-applicable",
  "zdr_status": "not-applicable",
  "vendor_approval_id": null,
  "evidence": [],
  "reviewers": [],
  "rollback": "How to switch it off and what stops working.",
  "status": "draft",
  "approved_on": null,
  "review_date": null
}
```

Give it the next free `AC-nnn` id. Do not set `status` to `approved` yourself: the `ai-change-approver` does, after the evidence is attached.
