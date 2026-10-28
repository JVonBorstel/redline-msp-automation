# CredentialOps

Two PowerShell levers over the offline mock tenant (B-30): `user.reset-password` (`Reset-UserPassword`) and `user.new-tap` (`New-UserTap`). Synthetic data only; nothing talks to a real tenant.

- **The value never travels with the result.** The password or Temporary Access Pass is generated here with `RandomNumberGenerator` and written to one file, `<oob root>/<client>/<user id>-<password|tap>.json` (root: `$env:REDLINE_OOB_DIR`, else `.tmp/oob`). The returned object, the diff, the tenant file and every error message hold no value. A technician reads the file with `core/levers/oob.py`.
- **Audit:** the runner records the diff, so the marker's path (target id and type) and its `expiryMinutes` are the audit's "a credential was issued"; the diff holds no value.
- **Result data:** `target_id`, `credential_type`, `expiry_minutes`, `delivery: "out-of-band"`. The absolute expiry is inside the out-of-band file.
- **Tenant effect:** password: `passwordProfile.forceChangePasswordNextSignIn = true` and a `pendingCredentials.password` marker (type, single-use flag, lifetime). TAP: one `temporaryAccessPassAuthenticationMethod` with `isUsableOnce = true` and `lifetimeInMinutes` set to the policy minimum, plus a `pendingCredentials.tap` marker (optional mock policy `authenticationMethodsPolicy.temporaryAccessPass.minimumLifetimeInMinutes`, default 10; a `state` other than `enabled` refuses).
- **Refusals here too:** a user holding a `directoryRoles` membership is refused (the runner refuses first, D6-06).
- **Convergent:** while a credential is pending the diff is empty and no second value is issued.
- **UNVERIFIED:** Graph field names for a TAP, the real policy minimum and the default length. See the constants at the top of the module.
- **Tests:** `tests/py/levers/test_b30_oob.py` (the PowerShell-backed tests need `pwsh` 7.4+ and skip without it).
