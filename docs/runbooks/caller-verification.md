# Runbook: caller identity verification (W-IDM-04)

Owner: service desk lead
Last reviewed: 2026-10-27

Status: procedure for humans, following D6-06. The MSP's real procedure is UNKNOWN (map 07). Synthetic data only.

> Independently built prototype. Not affiliated with any vendor's or real company's systems.

## Purpose

Use this before acting on any phone or chat request for a change that a lever marks as needing the requester verified: MFA reset, Temporary Access Pass, authentication-method changes, changes to the phone or email on file, and disable or enable on request. It ends with a verification recorded on the approval page, or with the request refused.

## Rule

A model never judges whether a person is who they claim. Tooling may show facts and record that a human verified. Knowledge checks (date of birth, employee id, manager name) are not verification.

## Prerequisites

- Read access, for this client, to the three sources of a number on file: the PSA contact, the onboarding form and the client's contact list.
- A phone you control for the callback.
- The approval page, and for identity changes (R3) two distinct leads scoped to the client who can approve.
- The client's authorized contact, reachable, for the changes in step 4.

## Steps: the callback-on-file method

1. Take the request and **do not act on it**. Do not call the number the caller gave you.
2. Find the number **already on file** in one of the three sources the approval page lists: the PSA contact (`psa-contact`), the onboarding form (`onboarding-form`) or the client's contact list (`client-contact-list`). The number was on file before this call; one added or changed today does not count.
3. Call that number yourself. Confirm the person and the request in your own words.
4. For MFA reset, Temporary Access Pass, authentication-method changes and changes to the phone or email on file, also get confirmation from the client's authorized contact.
5. For an account that holds a privileged directory role, stop: it is never reset from a phone request (D6-06). A lead runs the human-only procedure.
6. Record the result on the approval page.

## What the approval page records

When a lever is marked as needing the requester verified, the approver chooses the method `callback-on-file` and where the number on file came from. The record keeps the method, the source label (`number-on-file:<source>`), who verified and when. It never keeps the number itself, and a decision form carrying a number or a free-text note is refused. Other methods the page offers: in person, confirmed by the client's manager, and finding reference (no caller). Identity changes are R3, so two distinct human leads scoped to the client approve (D6-05, D6-07).

## The fact pack helps; it does not decide

`python -m workflows.factpack caller --client <id> --target <upn>` shows the account, the authentication method types (never phone numbers or other contact details), recent sign-ins, devices, roles and Conditional Access exclusions. Use it to spot a mismatch (for example sign-ins from a country the person has never been in) and to see whether the person holds a privileged role. It proposes nothing.

## Pressure

An urgent executive on the phone is the textbook attack. A request that cannot wait for a callback waits for the callback.

## Rollback

A verification changes nothing by itself, so there is nothing to undo. If a verification was recorded wrongly (wrong source, wrong person, a number added today), do not approve: reject the proposal on the approval page and start again at step 1. If a change already ran on a wrong verification, treat it as a wrong automated action and follow `docs/runbooks/ai-incident-response.md`.

## Verification

The approver, a second person who did not make the call, checks the approval record before approving: the method is `callback-on-file`, the source label names one of the three sources, it says who verified and when, and it holds no number and no free-text note. For an identity change the page shows two distinct leads, neither of them the requester.
