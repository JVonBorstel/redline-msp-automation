# MailFlowOps (B-45)

Status: **mocked**. Offline levers over synthetic mail-flow state; no Exchange Online is called. Synthetic data only.

| Lever | Function | Class | Approval | What it does |
|---|---|---|---|---|
| `message.trace` | `Get-MailFlowTrace` | read, R0 | none (technician) | Every recipient of one message in this client's mail flow, with status and quarantine id. No subject or body. Another client's message id answers like an unknown one (no rows). |
| `quarantine.release` | `Restore-QuarantinedMessage` | write, R2 | lead | Releases one held message to one of its own recipients. Refused (denied, audited) for `HighConfPhish` and `Malware` (`$script:ReleaseRefused`) and for anyone not on the message. Convergent; supports `-WhatIf`. |

State: `<folder beside the tenant folder>/mailflow/<client>.json`, so `fixtures/mailflow/<client>.json` by default and `<tmp>/mailflow/` in tests (the bridge passes only the tenant folder). Fields and the stand-in cmdlet names (`Get-MessageTraceV2`, `Release-QuarantineMessage`) are UNVERIFIED; see `fixtures/mailflow/SOURCES.md`.

Dry-run example (an agent may propose, never execute):

    uv run --frozen python -m core.levers quarantine.release --client contoso-dental --identity triage-bot --params '{"upn":"priya.nair@contosodental.example","quarantine_id":"Q-1003"}'

(UNVERIFIED: the exact `core.levers` CLI flags; see `core/levers/__main__.py`.) Tests: `tests/py/phishing/test_b45_phishing.py`. Eval: `evals/phishing/report.md`.

Known limits: no undo lever (a delivered message cannot be pulled back by this module); no Graph or Exchange connection exists; the quarantine id is this repo's own `Q-nnnn`.
