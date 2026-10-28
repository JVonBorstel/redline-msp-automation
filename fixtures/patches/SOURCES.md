# Patch fixture sources

Status: **mocked** (fixtures only). Independently built prototype. Synthetic data only. Pinned to `as_of` 2026-10-22T12:00:00Z (patch cycle 2026-10, Patch Tuesday 2026-10-13); results computed from these files are fixture-based.

Every file carries a `_note` that starts with `SYNTHETIC`, and every per-client file's `client` matches its file name (STD-FX-3). Clients are Contoso Dental and Fabrikam Capital. KB ids (`KB-SYN-*`), known-issue ids, advisory ids (`ADV-SYN-*`), vendors (Northwind Systems, Tailspin Labs, Adatum), models and hosts are invented and match nothing real.

## Layout

| File | Imitates | Status |
| --- | --- | --- |
| `releases.json` | a month's released updates, rings and known issues | Neutral shape of this repo. No vendor schema is claimed (UNVERIFIED how any RMM or Windows Update source reports this). |
| `<client>.json` | per-device update state (installed, pending, failed with an error code), a server window, network device firmware versions | Neutral shape of this repo. Device uids are those of `fixtures/rmm/<client>.json` (B-61). |

No call was made to any vendor and no vendor document was read for these shapes. The error codes in `workflows/patching/config.json` (`0x80070005`, `0x800f0922`) are written from general knowledge; their meaning is UNVERIFIED there.

## Seeded cases (STD-FX-4)

| Client | What the fixtures seed | Expected |
| --- | --- | --- |
| Contoso Dental | 9 RMM devices: 2 compliant (FRONTDESK-01, OFFICE-MGR), 4 non-compliant (OPERATORY-02, DENTAL-SRV01, XRAY-WS01, HYGIENE-03 online copy), 2 stale (RECEPTION-OLD, HYGIENE-03 old copy), 1 with no patch record (CHAIRSIDE-04) | 2 of 6 evaluated = 33.3 percent |
| Contoso Dental | failed rows: `0x80070005` on two evaluated devices (a third, on a stale device, is left out), `0x800f0922` on one | 2 groups |
| Contoso Dental | one decoy patch record for a device of Fabrikam's RMM site | dropped, counted in `patch_records_unmatched`, never named |
| Contoso Dental | a server (DENTAL-SRV01) with a pending update, reboot expected | window Saturday 22:00 and a notice draft |
| Contoso Dental | firewall behind an open advisory fix, a switch that is current, an access point behind, an access point with a non-numeric version | `advisory-open`, `current`, `behind`, `unknown` |
| Fabrikam Capital | 4 RMM devices: 3 compliant, 1 non-compliant with an error code that is not in the table | 3 of 4 = 75.0 percent; one group with no lever |
| Fabrikam Capital | one decoy patch record for a Contoso RMM device | dropped, counted |
| Fabrikam Capital | a server that is compliant, no reboot | window Sunday 02:00 and a notice draft |
| both | `releases.json`: an open known issue on a client OS update (hold), a fixed known issue whose fix is in the list, an update inside the grace period (not required yet), an optional preview (defer), a server update with an open known issue (hold) | see `review_pack` |

The clean twin for the seeded problems is Fabrikam's compliant devices: they raise no failure, no missing update and no flag.
