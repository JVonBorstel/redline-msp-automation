# Provisioning

One joiner lever for the Python bridge (B-35): `user.new`. It works on the offline mock tenant only (`fixtures/tenant/<client>.json` and `fixtures/tenant/<client>/mailboxes.json`, or the folder in `$env:REDLINE_MOCK_TENANT_DIR`, which the bridge sets). Synthetic data only; nothing here has run against a real tenant, and every Graph or Exchange name below is **UNVERIFIED**.

| Lever | Function | Risk | `graph_scopes` | Verification |
|-------|----------|------|----------------|--------------|
| `user.new` | `New-UserAccount` | R3 (two distinct leads) | `User.ReadWrite.All` (UNVERIFIED) | requester + the client's authorized contact |

The registry fragment is `levers/registry.d/provisioning.json`. The lever is `runtime: "powershell"`; the Python runner checks role, client scope, approval, pause and verification before the host starts (B-16).

## user.new

Parameters `upn`, `display_name`, `job_title`, `department`, `manager_upn`. All five come from the new-hire form (`workflows/onboarding`); there is no free-text parameter, and the module checks the same patterns as the registry, case-sensitively.

- **Dry-run** returns the diff: one `add` of `/users/<id>` and one `add` of `/mailboxes/<id>`, each holding the whole record that execute writes. Ids are a hash of the client and the upn, so the dry-run and the real run agree. A plan can replay this diff into a scratch copy to dry-run the steps that need the user to exist.
- **The account** is created enabled, with the department, job title and manager (stored as the manager's UPN, a mock shape; Graph models manager as a relationship, UNVERIFIED), and **no credential and no license**. The first sign-in is a separate approved step, `user.new-tap`; licenses and groups are `license.add` and `group.add-member`.
- **The mailbox record** (`mailboxes.json`) is a mock stand-in: a real tenant creates the mailbox from the license (UNVERIFIED). A client with no `mailboxes.json` gets the user only, and the result says the mailbox is not tracked.
- **Idempotent.** The same upn with the same values is an empty diff. A half-finished earlier run (user without mailbox record, or the reverse) adds only the missing part. The same upn with different values throws `InvalidOperationException` and changes nothing; the lever never overwrites.
- **Manager.** Must already be a user of the same client, and cannot be the new user.
- **Manual undo.** No undo lever is registered. `user.disable` stops the account from signing in but does not remove it, so it is not offered as an undo. A person removes a wrongly created account in the admin centre.

Through the lever host a refusal shows as `user.new crashed: RuntimeException` (the host never carries message text). Called directly, the type says why: `UnauthorizedAccessException` = scope not granted, `KeyNotFoundException` = no such manager, `InvalidOperationException` = exists with other values, `ArgumentException` = bad value, `FileNotFoundException` = no state for the client.

## Scope check

The function first asserts the Graph permission it needs (`Assert-PvScope`). `$env:REDLINE_MOCK_GRAPH_SCOPES` (space, comma or semicolon separated) lists the granted permissions; unset means the registered set is granted, which is the normal mock run.

## Tests

`pwsh -NoProfile -File levers/powershell/Provisioning/tests/Provisioning.Tests.ps1` (dry-run, execute, idempotency, half-finished run, refusals, scope denial; STD-PS-9 plain-script style), part of `tests/ps/Test-Modules.ps1`. End to end through the runner: `uv run --frozen pytest tests/py/onboarding/test_b35_onboarding.py` (needs `pwsh` 7.4+; those tests skip without it).
