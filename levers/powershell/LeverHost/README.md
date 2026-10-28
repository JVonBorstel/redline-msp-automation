# LeverHost

The PowerShell side of "Python orchestrates, PowerShell acts" (B-15). Synthetic data only; nothing here has run against a real tenant.

```
'{"version":1,"request_id":"req-0001-t3101","lever":"user.reset-mfa","lever_version":1,"client":"contoso-dental","mode":"dry-run","params":{"upn":"priya.nair@contosodental.example"},"entry":{"module":"IdentityLevers","function":"Reset-UserMfa"}}' |
  pwsh -NoProfile -NonInteractive -File levers/powershell/LeverHost/Invoke-LeverRequest.ps1
```

- **In:** one `lever-request` JSON document on stdin (`schemas/lever-request.schema.json`).
- **Out:** one JSON line on stdout: `status`, `reason`, `lever`, `client`, `mode`, `data`, `diff`, `applied`. The Python bridge adds `identity`, `approver`, `audit_seq` (it writes the audit).
- **Exit:** 0 ok, 1 denied or error, 2 bad request or host configuration.
- **Dry-run** calls the function with `-WhatIf`; a function without `-WhatIf` is refused in dry-run. **Execute** runs it with no prompt.
- Only the module named in `entry` is imported; the function must be one it exports.
- A thrown error becomes `"<lever> crashed: <ExceptionType>"`. Stack text goes only to `-LogPath`.

Writing a lever function: approved verb, `[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]` for anything that changes state, a parameter per `params` key (`ticket_id` becomes `-TicketId`), optional `-Client` and `-AsOf`, and return one object. A `diff` member (`op`, `path`, `before`, `after`) plus `applied` and optional `data` becomes the result; otherwise the object is `data`. See `specs/B-15.md`.

Tests: `pwsh -NoProfile -File levers/powershell/LeverHost/tests/LeverHost.Tests.ps1`, or all modules with `pwsh -NoProfile -File tests/ps/Test-Modules.ps1`.
