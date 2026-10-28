# Runbook: offboarding a client from the MSP (W-PRJ-02)

Owner: account manager (the project engineer runs the checklist)
Last reviewed: 2026-10-27

Status: document-only. A procedure for humans; nothing in it is automated. The MSP's real procedure is UNKNOWN (map 07); this is the prototype's proposal, to be replaced by theirs. Synthetic data only.

> Independently built prototype. Not affiliated with any vendor's or real company's systems.

## Purpose

Use this when a client relationship with the MSP ends. It ends with the client holding its own admin access and its documentation, and the MSP holding no account, agent or delegated relationship in the client's systems, each step checked by a second engineer.

## Prerequisites

- The agreed end date and the named receiver, from the contract notice.
- An offboarding ticket to copy the checklist into.
- The discovery pack for the client (see below) so the list of accounts, licences and devices is complete.
- The client's confirmation that its own backup is running, before any MSP backup agent is removed.
- A second engineer for the check at the end.

## What the tool never does

Nothing here is automated (B77-2). There is no lever, no workflow command and no queue entry for ending a client relationship: the program never hands back credentials, never removes GDAP relationships, never exports or deletes documentation and never removes agents. Each step below is done by a named person, by hand, and recorded in the ticket. The inventory rule for `W-PRJ-02` is "none-keep-human" (R3): access must truly end, and the client must be treated with respect while it does.

The only tools that help are read-only: the discovery pack (`python -m workflows.client_lifecycle discover --client <id>`, B-77) shows what the MSP still holds for the client (accounts, licences, devices) so the checklist is complete. It changes nothing.

## Who decides what (roles, recorded before work starts)

| Decision | Who | Where it is recorded |
| --- | --- | --- |
| That the relationship ends, and on which date | MSP leadership with the client's authorized contact | The contract notice and the offboarding ticket |
| That the person asking for the hand-over is the client's authorized contact | The account manager, by callback on the number already on file (see `caller-verification.md`) | The offboarding ticket |
| Who receives the credentials and documentation | The client's authorized contact, in writing | The offboarding ticket |
| That each step is done | The project engineer who did it, then a second engineer who checks it | The checklist below, copied into the ticket |

This file names roles, never people. Names go in the ticket, taken from the client record.

## Checklist (do in this order; tick each line in the ticket with who and when)

1. **Agree the date and the receiver.** Confirm the end date and the person who receives everything, by callback on the number on file. Do not use a number or address given in the request.
2. **Export documentation.** Export the client's documentation (network diagrams, asset lists, runbooks written for the client, licence and renewal list) from the documentation system. Credentials are not part of the export; they are handed back in step 3. Hand it over by an agreed secure method. The export method and format of the MSP's documentation tool are UNVERIFIED.
3. **Hand back credentials.** For every admin account the MSP created or managed (Microsoft 365 global admin, break-glass accounts, firewall, Wi-Fi, line-of-business apps, domain registrar, DNS host): the client sets a new password and new MFA while the MSP watches, then the MSP confirms it can no longer sign in. Break-glass accounts are handed over, never deleted. No credential is sent in email, chat or a ticket body.
4. **Remove GDAP.** End every Granular Delegated Admin Privileges relationship between the MSP's partner tenant and the client tenant, and remove the MSP's security groups from any remaining role assignment. Then check from the client side that no delegated relationship is left. The exact Partner Center and admin center screens are UNVERIFIED here; follow Microsoft's current documentation on the day.
5. **Remove MSP tooling.** Uninstall the RMM agent, the MSP's backup agents (only after the client confirms its own backup is running), the MSP's security and monitoring agents, and any MSP app registration or enterprise application in the client tenant. Remove the MSP from vendor portals where it is the partner of record.
6. **Remove MSP accounts and access.** Disable, then delete after the agreed retention, every MSP technician account and service account in the client tenant and in the client's other systems. Revoke API keys and tokens the MSP holds for the client. Per-user offboarding of the client's own staff is not part of this runbook (B-36 covers one leaver).
7. **Close the books.** Final invoice and licence transfer (the client or its new provider becomes the licence partner). The PSA company is marked inactive, not deleted, so history and audit evidence stay.
8. **Confirm in writing.** Send the client a short written confirmation of what was handed over and what access was removed, drafted by a person and sent by the account manager. Keep the audit records and the ticket for the retention period.

## Check (a second engineer, after the last step)

- Sign-in with every former MSP account fails.
- No GDAP or other delegated relationship remains, seen from the client tenant.
- No MSP agent reports in for this client in the RMM or the backup console.
- The client has confirmed receipt of credentials and documentation.

Anything not done is written in the ticket with the reason and an owner; the relationship is not marked closed until each line is done or the client has agreed in writing to leave it.

## Rollback

Most steps cannot be undone by the MSP once done, which is why nothing is removed before the agreed date. If the client asks to pause, stop at the current step and record it in the ticket. Restoring a delegated relationship, an agent or an account is a new request from the client's authorized contact, verified by callback, not an undo. Documentation already handed over cannot be recalled.

## Conduct

- Respectful and clear: the client chose to leave, and a clean exit is the MSP's reputation.
- Nothing is removed before the agreed date; nothing is kept after it.
- If anything looks wrong (an unverified requester, a request to send passwords by email, a third party asking for access) stop and tell the account manager.
