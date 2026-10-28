# DeviceR3 sources

Status: **nothing here is verified against a vendor.** The device state in `fixtures/tenant/<client>/devices.json` is synthetic (invented people, `.example` domains, `c0000000-` and `f0000000-` ids; device uids and hostnames follow `fixtures/rmm`, owners follow `fixtures/intune`). No vendor documentation was read for this item and no call was made to a real RMM, Intune, Defender or Microsoft Graph endpoint. The names below were written from memory and stay UNVERIFIED until someone reads the vendor page and records the date.

## What each lever stands in for

| Lever | Stands in for (UNVERIFIED) | API family | Permission named in `graph_scopes` (UNVERIFIED) |
| --- | --- | --- | --- |
| `device.lock` | Intune managed device remote lock | Microsoft Graph, `managedDevices/{id}/remoteLock` | `DeviceManagementManagedDevices.PrivilegedOperations.All` |
| `device.unlock` | clearing the lock (Intune has no plain "unlock" action that I can cite; the mock models it as a state flip) | none | same as lock |
| `device.isolate` | Defender for Endpoint machine isolation | Defender for Endpoint API, `machines/{id}/isolate` | `Machine.Isolate` |
| `device.release` | Defender for Endpoint release from isolation | Defender for Endpoint API, `machines/{id}/unisolate` | `Machine.Isolate` |
| `device.retire` | Intune retire | Microsoft Graph, `managedDevices/{id}/retire` | `DeviceManagementManagedDevices.PrivilegedOperations.All` |
| `device.wipe` | Intune wipe | Microsoft Graph, `managedDevices/{id}/wipe` | `DeviceManagementManagedDevices.PrivilegedOperations.All` |

- Whether a real lock can be undone by an API call, what an offline device does with each action, and how long each takes are UNVERIFIED; the mock treats them as state flips that apply at the next check-in.
- Defender for Endpoint is a separate API from Graph and needs its own app registration; the mock does not model that. Whether the MSP licenses Defender for Endpoint at each client is UNKNOWN (`docs/map/07-msp-profile.md`).
- The RMM (inferred as Datto RMM, B-61) has no lever here: the program's RMM adapter is read-only by design (D6-26).
- `legalHold`, `onlyDeviceForRole`, `holdsRegulatedData` and `role` are fields invented for the mock. A real build would read hold status from the client's records, not from a device field.
- The `device` uid is the RMM device uid. Intune and Defender use their own ids; reconciling them is B-61's job and is not done here.
