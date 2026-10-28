# Sample

Two sample PowerShell levers for the Python bridge (B-16): a read (`Get-SampleUser`, lever `sampleuser.get`) and a write (`Set-SampleUserTitle`, lever `sampleuser.set-title`). They work on the offline mock tenant (`fixtures/tenant/<client>.json`, or the folder in `$env:REDLINE_MOCK_TENANT_DIR`, which the bridge sets). Synthetic data only; nothing here talks to a real tenant.

- **Registry fragment:** `Sample.registry.json` (`runtime: "powershell"`, `entry: "Sample\\Get-SampleUser"` in the JSON file, that is `Sample\Get-SampleUser`). It is not in `levers/registry.d/`, so the live registry does not list sample levers. Copy it there to try them.
- **Inputs:** `-Upn`, `-Title` (write only), `-Client` (the host passes it from the request; a client id is a plain slug and the only thing that becomes a path).
- **Outputs:** the read returns an object (id, display name, upn, job title, enabled flag; no contact or sign-in details). The write returns `data`, `diff` and `applied`; the diff is exactly what the Python runner produces for the same change: `{"op":"replace","path":"/users/<id>/jobTitle","before":...,"after":...}`.
- **Dry-run:** the host calls the write with `-WhatIf`: it computes the diff and writes nothing. Execute applies exactly that diff in one atomic file replace. The same title again is an empty diff (convergent, STD-LV-6).
- **Permissions:** none here. The Python runner has already checked role, client scope, approval, pause and verification before the host is started.
- **Tests:** `tests/py/levers/test_b16_bridge.py` (needs `pwsh` 7.4+; those tests skip when it is missing).
