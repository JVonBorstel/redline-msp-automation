# LicenseOps

Two PowerShell levers over the offline mock tenant (B-31): `license.add` (`Add-LicenseAssignment`, R1) and `license.remove` (`Remove-LicenseAssignment`, R2). Synthetic data only; nothing talks to a real tenant.

- **Registry fragment:** `levers/registry.d/license.json`.
- **Data:** `fixtures/tenant/<client>/licenses.json` (a B-19 family file) for SKUs and assignments, and the client's base file to check the user exists. The bridge sets `$env:REDLINE_MOCK_TENANT_DIR`.
- **Free stock only.** A seat is free when `prepaidUnits.enabled` is more than the assignments of that SKU. With none, `license.add` returns `no free seat: a purchase needs the client's consent (W-VND-02)` and an empty diff. There is no purchase function; `governance/never-automate.json` (`license.purchase*`) blocks a lever with that name.
- **Retention.** `license.remove` works only on an assignment whose `retentionEndsOn` (last day of the window) is before the as-of date (`-AsOf`, default today UTC). The diff shows the SKU and that date.
- **Refusals are data.** The host reports a thrown error as its type name only, so a refusal the reader should see comes back as `data.outcome: "refused"` with `data.message` and an empty diff.
- **Tests:** `tests/py/levers/test_b31_license.py` (module tests need `pwsh` 7.4+ and skip without it).
