# schemas/

Status: **built** (B-13). Independently built prototype. Not affiliated with any vendor's or real company's systems. Every example here is synthetic.

One JSON Schema (draft 2020-12) per shape that Python and PowerShell pass to each other (STD-XL-1). Python orchestrates, PowerShell acts; they share these files, not code.

| File | Shape | Source of truth | How it is kept honest |
|------|-------|-----------------|-----------------------|
| `lever-registry.schema.json` | `levers/registry.json` | `_RegistryFile` + `LeverDef` | generated |
| `identities.schema.json` | `config/identities.json` | `_IdentityFile` + `Identity` | generated |
| `change.schema.json` | one diff entry | `Change` | generated |
| `lever-result.schema.json` | runner (and later bridge) result | `InvokeResult` | generated |
| `proposal.schema.json` | queue proposal | `Proposal` | generated |
| `lever-request.schema.json` | bridge request (B-15) | this file | hand-written; patterns tested against the Python ones |
| `audit-record.schema.json` | v1 record, v2 as proposed (STD-AU-2, B-17) | `core/audit/chain.py` | hand-written; v1 fields tested against `RECORD_FIELDS` |
| `finding.schema.json` | a TenantBaseline finding | `TenantBaselineFinding` class | hand-written; fields tested against the class and real output |
| `client.schema.json` | proposed `config/clients/<id>.json` (B-18, W2-E1) | this file | hand-written |

## Commands

```
uv run --frozen python tools/gen_schemas.py            # rewrite the five generated files after a model change
uv run --frozen python tools/gen_schemas.py --check    # exit 1 and name each file that has drifted
pwsh -NoProfile -File tests/ps/Test-Schemas.ps1        # PowerShell Test-Json over every example and the real files
uv run --frozen pytest -p no:cacheprovider tests/py/contract
```

Never edit a generated file by hand: change the pydantic model, then run the generator. The drift test fails until you do.

## Examples

`examples/<name>.good*.json` must pass and `examples/<name>.bad-<why>.json` must fail, in Python (pydantic or the audit verifier, where a reader exists) and in PowerShell (`Test-Json -SchemaFile`). Each bad example breaks one rule, named in its file name. The files carry no `_note` because most schemas forbid extra keys; this README is their label (STD-FX-3).

## What a schema does not check

- **Cross-field rules.** A write lever needs lead approval and dry-run; a proposal id is a hash of its lever, client and params; an audit record's hash chains to the one before. The Python loaders and `core.audit.verify` enforce these. The schemas carry shape only.
- **`format`.** Recorded by B13-3 with PowerShell 7.6.7 (JsonSchema.Net 7.0.0): `Test-Json` treats `format` (for example `date-time`) as an annotation, so `"not-a-date"` passes. Python (pydantic `AwareDatetime`) does reject it. A PowerShell reader that needs a date must parse it itself. Every other keyword used here is enforced; the keyword probe in `tests/ps/Test-Schemas.ps1` proves it and fails if a new keyword appears unprobed.
