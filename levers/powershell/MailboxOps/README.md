# MailboxOps

Twelve PowerShell levers for the mailbox half of joiners, movers and leavers (B-33): distribution list membership, Full Access and Send As, convert to shared, auto-reply, online archive, and a time-bound manager grant to a leaver's OneDrive. They work on the offline mock mailbox state (`fixtures/tenant/<client>/mailboxes.json`, or the folder in `$env:REDLINE_MOCK_TENANT_DIR`, which the bridge sets). Synthetic data only; nothing here talks to a real tenant. Every vendor shape is UNVERIFIED and mostly Exchange Online PowerShell, not Graph: read `SOURCES.md` first.

| Lever (registry.d/mailbox.json) | Function | Undo lever |
| --- | --- | --- |
| `mailbox.add-dl-member` / `mailbox.remove-dl-member` | `Add-MailboxDlMember` / `Remove-MailboxDlMember` | each other |
| `mailbox.grant-full-access` / `mailbox.revoke-full-access` | `Grant-MailboxFullAccess` / `Revoke-MailboxFullAccess` | each other |
| `mailbox.grant-send-as` / `mailbox.revoke-send-as` | `Grant-MailboxSendAs` / `Revoke-MailboxSendAs` | each other |
| `mailbox.convert-shared` | `Convert-MailboxToShared` | none (converting back needs a licence) |
| `mailbox.set-auto-reply` / `mailbox.clear-auto-reply` | `Set-MailboxAutoReply` / `Clear-MailboxAutoReply` | each other |
| `mailbox.enable-archive` | `Enable-MailboxArchive` | none (switching an archive off can delete mail) |
| `mailbox.grant-onedrive-manager` / `mailbox.revoke-onedrive-manager` | `Grant-OneDriveManagerAccess` / `Revoke-OneDriveManagerAccess` | each other |

- **Risk:** all `R2` (one lead who is not the requester approves), `approval: lead`, an agent may dry-run, a technician executes. Notice templates: `workflows/notify/templates/mailbox.*.md`.
- **Inputs:** `-Upn` (the mailbox or person the change is about, which is also who the notice goes to), then `-List`, `-Delegate`, `-Manager`, `-Message` or `-ExpiresOn` as the lever needs, and `-Client` from the host. `-AsOf` is optional; the default is the date in the fixture's `_meta.as_of`. The wall clock is never read.
- **Outputs:** `{ data, diff, applied }`. The diff paths are `/mailboxes/<id>/...`, `/distributionLists/<id>/members/<upn>` and `/oneDrive/<id>/access/<upn>`.
- **Dry-run:** the host calls with `-WhatIf`: the diff is computed and nothing is written. Execute applies exactly that diff in one atomic file replace. The same call again is an empty diff, and an empty diff does not rewrite the file.
- **Guards inside the module:** a person named as delegate or manager must be a user mailbox of the same client (not a shared mailbox, not an outside address, not the mailbox itself); a person or list of another client answers exactly like an absent one; a mailbox over 50 GB is not converted (limit UNVERIFIED); a OneDrive end date must be after the as-of date and at most 30 days away.
- **Not offered:** forwarding to an outside address. `W-M365-05` (read-only audit) flags it. A test scans the registry and the module source.
- **Refusals:** a thrown refusal reaches the Python caller as `<lever> crashed: RuntimeException` (the host reports the type only, STD-ER-5). The sentence is visible when the function is called directly, and in these tests.
- **Tests:** `pwsh -NoProfile -File levers/powershell/MailboxOps/tests/MailboxOps.Tests.ps1` (module behaviour, 69 checks) and `uv run --frozen pytest -p no:cacheprovider tests/py/mailbox` (registry, runner gates, undo, fixtures, SOURCES; needs `pwsh` 7.4+ for the runner tests).
