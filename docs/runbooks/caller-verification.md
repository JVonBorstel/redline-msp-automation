# Runbook: caller identity verification (W-IDM-04)

Status: procedure for humans, following D6-06. The MSP's real procedure is UNKNOWN (map 07). Synthetic data only.

> Independently built prototype. Not affiliated with any vendor's or real company's systems.

## Rule

A model never judges whether a person is who they claim. Tooling may show facts and record that a human verified. Knowledge checks (date of birth, employee id, manager name) are not verification.

## The callback-on-file method

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
