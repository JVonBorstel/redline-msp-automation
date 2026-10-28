# MailboxOps sources

Status: **nothing here is verified against a vendor.** The mailbox state in `fixtures/tenant/<client>/mailboxes.json` is synthetic (invented people, `.example` domains, `c0000000-` and `f0000000-` ids). No vendor documentation was read for this item, and no call was made to a real Exchange Online, SharePoint Online or Microsoft Graph endpoint. The cmdlet names and field names below were written from memory of Exchange Online PowerShell and are marked UNVERIFIED until someone reads the vendor page and records the date.

## Exchange Online PowerShell, not Graph

Mailbox, distribution list, Full Access, Send As, auto-reply and archive settings are managed through the Exchange Online PowerShell module (the `ExchangeOnlineManagement` module, cmdlets such as `Get-Mailbox`), not through Microsoft Graph. The shapes in the fixture therefore follow cmdlet output (PascalCase properties in the vendor's own tools, written here in camelCase), not Graph resources. Which of these actions have a Graph equivalent is UNVERIFIED and is not claimed. The OneDrive grant is a SharePoint Online / OneDrive administration action; whether a real build would use the SharePoint Online module or Graph is UNVERIFIED and left open.

The MSP's own stack is mostly inferred (`docs/map/07-msp-profile.md` section 5): they are a direct Microsoft CSP, so Exchange Online is likely and Microsoft 365 is CONFIRMED as something they manage; which admin tools they use for mailbox work is UNKNOWN.

## Levers

| Lever | Stands in for (UNVERIFIED cmdlet) | API family | Role or scope needed | Status |
| --- | --- | --- | --- | --- |
| `mailbox.add-dl-member` | `Add-DistributionGroupMember` | Exchange Online PowerShell | Exchange role to manage group members (UNVERIFIED) | UNVERIFIED cmdlet, parameters and role |
| `mailbox.remove-dl-member` | `Remove-DistributionGroupMember` | Exchange Online PowerShell | as above | UNVERIFIED cmdlet, parameters and role |
| `mailbox.grant-full-access` | `Add-MailboxPermission -AccessRights FullAccess` | Exchange Online PowerShell | Exchange role to manage mailbox permissions (UNVERIFIED) | UNVERIFIED cmdlet, parameters, role and auto-mapping behaviour |
| `mailbox.revoke-full-access` | `Remove-MailboxPermission` | Exchange Online PowerShell | as above | UNVERIFIED cmdlet, parameters and role |
| `mailbox.grant-send-as` | `Add-RecipientPermission -AccessRights SendAs` | Exchange Online PowerShell | Exchange role to manage recipient permissions (UNVERIFIED) | UNVERIFIED cmdlet, parameters and role |
| `mailbox.revoke-send-as` | `Remove-RecipientPermission` | Exchange Online PowerShell | as above | UNVERIFIED cmdlet, parameters and role |
| `mailbox.convert-shared` | `Set-Mailbox -Type Shared` | Exchange Online PowerShell | Exchange role to change mailbox type (UNVERIFIED) | UNVERIFIED cmdlet; the 50 GB unlicensed shared-mailbox limit used as a guard is UNVERIFIED |
| `mailbox.set-auto-reply` | `Set-MailboxAutoReplyConfiguration -AutoReplyState Enabled` | Exchange Online PowerShell | Exchange role to manage mailbox settings (UNVERIFIED) | UNVERIFIED cmdlet, parameters and audience values |
| `mailbox.clear-auto-reply` | `Set-MailboxAutoReplyConfiguration -AutoReplyState Disabled` | Exchange Online PowerShell | as above | UNVERIFIED cmdlet and parameters |
| `mailbox.enable-archive` | `Enable-Mailbox -Archive` | Exchange Online PowerShell | Exchange role to enable archives (UNVERIFIED) | UNVERIFIED cmdlet; licence requirement for an archive is UNVERIFIED |
| `mailbox.grant-onedrive-manager` | adding a site collection administrator to the user's OneDrive (for example `Set-SPOUser -IsSiteCollectionAdmin`) | SharePoint Online (PowerShell or Graph) | SharePoint administrator (UNVERIFIED) | UNVERIFIED cmdlet, scope and whether Graph can do it |
| `mailbox.revoke-onedrive-manager` | removing that site collection administrator | SharePoint Online (PowerShell or Graph) | as above | UNVERIFIED cmdlet and scope |

Time-bound access is the prototype's own rule: the end date is a lever parameter checked by the module (after the as-of date, at most 30 days away). Neither Exchange nor SharePoint is claimed to expire a grant by itself; the revoke lever ends it and a person or a scheduled job has to run that lever.

## Not offered

Forwarding a mailbox to an address outside the client is **not offered** as a lever (B33-2). It is the classic business-email-compromise move, and the weekly audit `W-M365-05` (suspicious inbox rules and external forwarding, read-only) flags it. Nothing in `MailboxOps` reads or writes a forwarding address; a test scans the registry and the module source for it. Litigation hold, retention and eDiscovery stay on the never-automate list (`governance/never-automate.json`).

## Fixture fields (`fixtures/tenant/<client>/mailboxes.json`)

Every field is UNVERIFIED. `_meta.client` matches the folder name, `_meta.as_of` pins the date (2026-10-21), and every file says it is synthetic.

| Field | Stands in for (UNVERIFIED) | Used by |
| --- | --- | --- |
| `mailboxes[].id` | an invented id with a per-client prefix | all mailbox levers (diff paths) |
| `mailboxes[].userPrincipalName` | `PrimarySmtpAddress` of `Get-Mailbox` | all |
| `mailboxes[].displayName` | `DisplayName` | none (label) |
| `mailboxes[].recipientTypeDetails` | `RecipientTypeDetails` (`UserMailbox`, `SharedMailbox`) | `mailbox.convert-shared` |
| `mailboxes[].totalItemSizeGb` | the size of `Get-MailboxStatistics`, in GB (the real property is text) | `mailbox.convert-shared` guard |
| `mailboxes[].archiveStatus` | `ArchiveStatus` (`None`, `Active`) | `mailbox.enable-archive` |
| `mailboxes[].autoReply` | `Get-MailboxAutoReplyConfiguration` | `mailbox.set-auto-reply`, `mailbox.clear-auto-reply` |
| `state` | `AutoReplyState` (`Disabled`, `Enabled`) | auto-reply levers |
| `internalMessage` | `InternalMessage` | `mailbox.set-auto-reply` |
| `externalMessage` | `ExternalMessage` | `mailbox.set-auto-reply` |
| `externalAudience` | `ExternalAudience` (`None`, `Known`, `All`) | `mailbox.set-auto-reply` |
| `mailboxes[].forwardingSmtpAddress` | `ForwardingSmtpAddress` | read by tests only; always `null`; no lever touches it |
| `mailboxes[].fullAccess` | users returned by `Get-MailboxPermission` with `FullAccess` | Full Access levers |
| `mailboxes[].sendAs` | trustees returned by `Get-RecipientPermission` with `SendAs` | Send As levers |
| `distributionLists[].id` | an invented id | DL levers (diff paths) |
| `distributionLists[].primarySmtpAddress` | `PrimarySmtpAddress` of a distribution group | DL levers |
| `distributionLists[].displayName` | `DisplayName` | none (label) |
| `distributionLists[].members` | `Get-DistributionGroupMember` | DL levers |
| `oneDrive[].id` | an invented id | OneDrive levers (diff paths) |
| `oneDrive[].owner` | the user whose OneDrive it is | OneDrive levers |
| `oneDrive[].access` | the site collection administrators other than the owner | OneDrive levers |
| `grantee` | the person granted access | OneDrive levers |
| `grantedOn` | the as-of date of the grant | OneDrive levers |
| `expiresOn` | the prototype's own end date (not a vendor property) | OneDrive levers |
| `accessLevel` | `SiteCollectionAdmin`, a label for the administrator right; a narrower right may exist and is UNVERIFIED | OneDrive levers |

## Seeded cases (and the clean ones)

- Contoso Dental: Jamie Chen (synthetic) has left; `jamie.chen@` is a 12 GB user mailbox with no auto-reply and an empty OneDrive access list, the offboarding case. `info@` is a shared mailbox where Ana Lopez already has Full Access and Send As (the revoke cases). `frontdesk@` lists Jamie and Priya.
- Fabrikam Capital: Alex Ward's mailbox is 61.5 GB, so conversion to shared is refused. Dana Kim has Full Access and Send As on `compliance@`. Morgan Reyes, Riley Brooks and Chris Osei are clean.
- Neither file sets forwarding. A decoy of the other client is not mixed into either file; cross-client tests use the other client's file and person.
