# IdentityOps

Three identity levers for the Python bridge (B-29): end a user's sessions, turn an account back on (the undo of `user.disable`), and change a mover's department, job title or manager. They work on the offline mock tenant only (`fixtures/tenant/<client>.json` and `fixtures/tenant/<client>/sessions.json`, or the folder in `$env:REDLINE_MOCK_TENANT_DIR`, which the bridge sets). Synthetic data only; nothing here has run against a real tenant, and every Graph name below that is not marked checked is **UNVERIFIED**.

| Lever | Function | Risk | `graph_scopes` | Verification |
|-------|----------|------|----------------|--------------|
| `user.revoke-sessions` | `Revoke-UserSessions` | R2 | `User.RevokeSessions.All` | none (containment) |
| `user.enable` | `Enable-UserAccount` | R2 | `User.EnableDisableAccount.All` (UNVERIFIED) | requester (callback on file) |
| `user.set-properties` | `Set-UserProperty` | R2 | `User.ReadWrite.All` (UNVERIFIED) | requester (callback on file) |

The registry fragment is `levers/registry.d/identity.json`. Each lever is `runtime: "powershell"`; the Python runner checks role, client scope, approval, pause and verification before the host starts (B-16).

## user.revoke-sessions

Mock of Graph `revokeSignInSessions` (the permission name `User.RevokeSessions.All` is the one the item specifies; the rest of the Graph behaviour is described from memory and is UNVERIFIED here).

- **Dry-run** returns a one-entry diff: `/sessions/<userId>/activeSessionCount` from N to 0. Execute applies exactly that diff. A user with no active sessions is an empty diff (idempotent).
- **Lag.** Revoking invalidates refresh tokens; access tokens already issued can keep working for a short while afterwards, so a revoked person may stay signed in to an app for a few minutes. The result says so in `data.lag`; tell the client the same. Pair this with `user.disable` when access must stop now.
- **Guest users.** The lever does not apply to guest users. A guest (`userType: "Guest"` in `sessions.json`) is refused and nothing is written. Through the lever host the refusal shows as `user.revoke-sessions crashed: RuntimeException` (the host never carries message text); the reason is in the operational log and the direct function call throws `NotSupportedException`.
- `activeSessionCount` is invented for the mock (Graph has no such counter); see the `_meta.note` in `sessions.json`. `litware-legal` has no `sessions.json`, so the lever errors there.
- **Manual undo.** There is no undo lever: a revoked session cannot be restored and the person simply signs in again. Nothing is put back; tell them (B-41 prints this section).

## user.enable

`accountEnabled` false to true; true to true is an empty diff. It is the registered `undo` of `user.disable` and `user.disable` is the undo of `user.enable`. Disable then enable gives back the same bytes, measured against the canonical layout the Python `MockTenant` writes (the committed fixture is hand-formatted, so the first write by any writer re-lays it out; the line ending of the file is kept). Verified in `tests/py/levers/test_b29_identity.py`.

## user.set-properties

Parameters `upn`, `field` (one of `department`, `jobTitle`, `manager`; any other value is refused by the registry before PowerShell runs and again by `ValidateSet`) and `value`. Idempotent: the same value is an empty diff. `manager` takes the manager's UPN, which must be another user of the same client; it is stored as that UPN (a mock shape; Graph models manager as a relationship, UNVERIFIED). Group membership that follows these fields is not modelled.

**Manual undo.** No undo lever is registered: propose `user.set-properties` again with the same `upn` and `field` and the old value from the audit record's before-state (`python -m workflows.rollback <audit_seq>` prints it). It is a normal change: dry-run, lead approval, callback on file.

## Scope check

Each function first asserts the Graph permission it needs (`Assert-IdScope`). `$env:REDLINE_MOCK_GRAPH_SCOPES` (space, comma or semicolon separated) lists the granted permissions; unset means the registered set is granted, which is the normal mock run. A call without its permission throws `UnauthorizedAccessException` before any file is read. The bridge scrubs the child environment, so this check is exercised by the plain-script tests, not through the runner.

## Tests

`pwsh -NoProfile -File levers/powershell/IdentityOps/tests/IdentityOps.Tests.ps1` (dry-run, execute, idempotency, scope denial; STD-PS-9 plain-script style), part of `tests/ps/Test-Modules.ps1`. End to end through the runner: `uv run --frozen pytest tests/py/levers/test_b29_identity.py` (needs `pwsh` 7.4+; those tests skip without it).
