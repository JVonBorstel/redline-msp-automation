# Runbook: urgent or hostile termination (W-ONB-15)

Status: procedure for humans. The MSP's real procedure is UNKNOWN (map 07); this is the prototype's proposal, to be replaced by theirs. Synthetic data only.

> Independently built prototype. Not affiliated with any vendor's or real company's systems.

## What a bot never does

A bot never decides whether to terminate access, never chooses the time, and never runs a lever on its own initiative. The inventory rule for W-ONB-15 is NEVER AUTOMATE the decision or the timing. The fact pack (`python -m workflows.factpack termination --client <id> --target <upn>`) only puts facts on one page. It registers no lever and proposes nothing.

## Who decides what (named humans, recorded before the call, not by this tool)

| Decision | Who | Where it is recorded |
| --- | --- | --- |
| That access ends, and the exact minute | The client's authorized contact with the client's HR, by phone | The ticket note, written by the lead on the call |
| That the caller is who they claim | The technician taking the call, by callback on the number already on file (see `caller-verification.md`) | The approval record (method, source of number, who, when) |
| That the actions run | Two distinct human leads scoped to this client, neither the requester (R3, D6-05, D6-07) | The approval page |
| Conduct on the call | The service desk lead owns the call; one technician executes; nobody else is told | The ticket note |

Names go in the ticket for the day, taken from the client's escalation list. This file names roles, never people.

## Steps

1. **Verify the caller** by callback on the number on file, never a number the caller gives (D6-06). A caller who cannot be called back does not start this runbook; the lead is told.
2. **Open the fact pack** for the person (`termination`). Read it with the lead: privileged roles or groups, devices and whether they are managed, active sessions, Conditional Access exclusions, gaps. A person who holds a privileged role is handled by Tier 3 with a second lead in the room.
3. **Agree the time with HR** through the client contact. Do not act early; do not act late. The lead writes the agreed minute in the ticket.
4. **At the agreed minute** the executing technician, in one sitting, asks for the pre-built approved levers (disable sign-in, revoke sessions, block or retire devices) through the approval page. Each needs its own approvals; the tool never runs them ahead of time.
5. **Confirm** with the lead that sessions are revoked and devices handled; read the fact pack again and note anything still open.
6. **Record** in the ticket what was done and when. The audit log holds the approvals.

## Conduct

- Calm, brief, no commentary on the person. Nothing is said to other staff by the technician.
- Nothing about the termination goes into a chat message, a model prompt or an email subject.
- If the client changes the time, stop and agree a new minute. Do not "prepare" by running anything.
- If anything looks wrong (caller cannot be verified, name does not match, request arrives by email only) stop and tell the lead.

## Out of scope for the tool

The decision, the timing and the conduct. Mailbox, device wipe and legal hold decisions are separate and also human.
