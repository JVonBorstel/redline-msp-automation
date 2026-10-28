# DeviceR3

Six device levers for the Python bridge (B-65): lock, retire, wipe and isolate (R3, two lead approvals) and the two undo levers, unlock and release. They work on the offline mock device state only (`fixtures/tenant/<client>/devices.json`, or the folder in `$env:REDLINE_MOCK_TENANT_DIR`, which the bridge sets). Synthetic data only; nothing here has run against a real RMM, Intune or Defender, and every product name and field below is **UNVERIFIED** (see `SOURCES.md`).

| Lever | Function | Risk | Undo | Verification | Window | Containment |
|-------|----------|------|------|--------------|--------|-------------|
| `device.lock` | `Lock-ManagedDevice` | R3 | `device.unlock` | requester + contact | business hours | yes |
| `device.unlock` | `Unlock-ManagedDevice` | R2 | `device.lock` | requester | none | no |
| `device.isolate` | `Block-DeviceNetwork` | R3 | `device.release` | requester | business hours | yes |
| `device.release` | `Unblock-DeviceNetwork` | R3 | `device.isolate` | requester | none | no |
| `device.retire` | `Remove-ManagedDevice` | R3, irreversible | none | requester + contact | business hours | **never** |
| `device.wipe` | `Clear-ManagedDevice` | R3, irreversible | none | requester + contact | business hours | **never** |

The registry fragment is `levers/registry.d/device-r3.json`. The Python runner checks role, client scope, two lead approvals, requester verification, window, caps and approval age before the host starts (B-16, B-28, B-42); these functions check none of that.

- **One device per call.** Params are `device` (an RMM device uid) and `upn` (its assigned user). The owner must match, so a wrong uid cannot land on someone else's device. A device of another client is simply not in this client's file; absent, other-client and wrong-owner all give the same refusal.
- **Dry-run** returns the one-entry diff (for example `/devices/<uid>/isolation/state` from `none` to `isolated`) and `data.blast_radius`: devices and users affected (1), class, online, last seen, role, whether it is the client's only device for that role, regulated data, legal hold, share of the client's devices, and notes. `data.undo` is the line the approval page shows.
- **Convergent.** The same call again is an empty diff.
- **Refusals** are typed exceptions: `KeyNotFoundException` (no such device for this user), `InvalidOperationException` (legal hold, or an unexpected state), `NotSupportedException` (retired, no longer managed). A direct call shows the type and message; through the lever host the audit shows only `<lever> crashed: RuntimeException` (the host never carries message text), so a legal-hold refusal is not self-explanatory in the audit. The dry-run of any other lever shows the hold in `blast_radius`.

## device.lock

`lock.state` `unlocked` to `locked`. Data stays on the device. Undo: `device.unlock`.

## device.unlock

`lock.state` `locked` to `unlocked`. The registered undo of `device.lock`.

## device.isolate

`isolation.state` `none` to `isolated`. The dry-run says when the device is the only one for its role. Undo: `device.release`.

## device.release

`isolation.state` `isolated` to `none`. The registered undo of `device.isolate`. Check the device is clean first.

## device.retire

`enrollment.state` `enrolled` to `retired`. Company data and management are removed; re-enrolling does not bring them back. **No undo lever.** Refused for a device under legal hold. After a retire no managed action works on the device.

Manual steps (the rollback workflow, B-41, prints this section): there is no undo. Do not try to restore from the device. Open a ticket, check whether the owner needs data that was on it, and restore from the client's backup if it covers the user. Re-enrol the device only as a new device.

## device.wipe

`wipe.state` `none` to `requested`. **No undo lever.** This only records the request: a person starts the wipe in the RMM or Intune console after the approval (D6-08), and nothing in this repository starts it. Refused for a device under legal hold and for a retired device. The runner refuses an approval that is 24 hours old or older.

Manual steps (the rollback workflow, B-41, prints this section): there is no undo. If the wipe has not been started in the console, cancel it there and tell the lead; the recorded request stays in the audit chain. If it has run, the data is gone: restore from the client's backup, and record the loss for the human breach assessment (W-SEC-07). Never re-run a wipe to "fix" a wrong device.
