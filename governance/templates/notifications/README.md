# Incident notification templates (IR-6)

Status: **document-only** (templates for a person to fill and send; checked by `tests/py/governance/test_b94_incident_response.py`). Synthetic data only. Not legal advice.

> Independently built prototype. Not affiliated with any vendor's or real company's systems.

Control `C-35`. Used at step `IR-6` of `docs/runbooks/ai-incident-response.md`. A person fills each template and sends it (HO-9). No automation sends any of them, and no model writes them.

## The three templates

| File | Sent to | Sent by | What it must say |
| --- | --- | --- | --- |
| `affected-person.md` | the person whose account was changed | technician on call | sorry; what happened; what we fixed; what to do; the fast way back (EU-1, EU-2, EU-8) |
| `client-contact.md` | the client's primary contact | account manager | what happened, who, what we fixed and when, what we paused, what the audit search found, the data note, the review date |
| `privacy-officer.md` | the client's privacy or security officer | account manager with the compliance owner | the facts early, what data, exposure and availability, the client-only audit export, the legal timelines to check |

Rules the test holds every template to: plain words (Flesch-Kincaid grade at most 8 by the test's own syllable count, no sentence over 25 words, none of the internal words listed in the test such as lever, audit chain, tenant, rollback, `DC-4` or `IR-3`); every line that names a deadline says "confirm with counsel"; a `Timelines` list in each; no phone number other than a placeholder; no real names.

## Placeholders

`string.Template` style (`$name`), the same style as `workflows/notify/templates/`.

| Placeholder | Filled with |
| --- | --- |
| `$first_name`, `$contact_first_name`, `$officer_first_name` | the reader's first name |
| `$when` | date and time of the wrong change, in the client's time zone |
| `$what_happened` | one plain sentence, for example "turned off your sign-in by mistake" |
| `$pause_scope` | the IR-2 pause scope in words, for example "for all of our clients" or "for your account only"; it must match what IR-2 actually did |
| `$restart_note` | person confirms before sending: what the sender will actually do before the tool is turned back on, for example "We will tell you before it is turned back on."; remove the sentence if the owner has not agreed to it |
| `$scope_check` | person confirms before sending: what was actually searched and what was found, in words; never "every change" unless the search really covered every change |
| `$files_note` | person confirms before sending: a sentence about the person's files and mail that is true for this lever, for example "Your files and mail are still there."; for a lever that does not touch them, say what was changed instead |
| `$next_note` | person confirms before sending: what is stopped now and why it is true, for example "We have stopped this kind of change until we fix the cause."; the pause covers one lever only, so name only what was paused |
| `$what_we_fixed`, `$what_you_do` | one plain sentence each |
| `$people_affected` | how many people, and their roles; no names in the client and officer notices unless the client asks |
| `$restored_at`, `$paused_at` | times from the audit records (IR-3, IR-2) |
| `$data_note`, `$exposure_note`, `$availability_note` | from the compliance owner (IR-5), in words, never a data-class code |
| `$review_date` | five business days after the incident (IR-8) |
| `$team`, `$fast_phone`, `$hours` | the client's fast-path line in `fixtures/notify/contacts.json` |
| `$client_name`, `$sender`, `$sender_role`, `$sender_phone` | the client's name, and the sender's name, role and work number |

Free-text placeholders (`$what_happened`, `$data_note`, `$exposure_note`) must be paraphrased by the reviewing person in plain words, never pasted from ticket, alert or log text.

### Person confirms before sending

These are statements of fact or promises that a template cannot know. The sender checks each one is true for this incident and edits it if not:

- `$files_note` and `$next_note` in `affected-person.md`.
- `$pause_scope` in `client-contact.md` and `privacy-officer.md`.
- The line "We will tell you before it is turned back on." in `client-contact.md` is a commitment. The owner must confirm the MSP will keep it (IR-9 re-enables in rings) before this is sent.
- The first Timelines line in `privacy-officer.md` starts with UNVERIFIED: counsel decides whether the MSP is the client's business associate and which deadline applies. Remove the word only on counsel's say-so.

## Timelines and sources

The timelines in `privacy-officer.md` are the ones `docs/map/05-governance.md` already states (BA-5: a business associate tells the covered entity without unreasonable delay and no later than 60 days after discovery, if the MSP is a business associate at all, which counsel must confirm; GLBA-7: an FTC notice within 30 days for a notification event involving 500 or more consumers; state laws; contracts may be shorter). The sources are the ones listed in that file's Sources section (HHS and FTC pages). They were not re-read for B-94. Every one is marked "confirm with counsel": this repo gives no legal advice, and the client's own counsel and contract decide.

## Review of the existing per-lever drafts (B-04, `workflows/notify/templates/`)

Reviewed for use in an incident by running the tabletop, which is dated 2026-10-27 (`docs/TABLETOP_2026.md`). The findings below come from that run. An earlier date in this section (2026-10-23) had no record behind it and was removed.

| Template | Fit for an incident notice | Finding |
| --- | --- | --- |
| `user.disable.md` | no | A routine change notice: it says the change was approved and "Why: <request>". For a wrong disable that is the wrong message. |
| `user.enable.md` | no, as sent | The draft for the rollback proposal read "Why: a security check flagged it (audit-2)". `workflows/notify/notify.py` (`_request`) gives that reason to every proposal that is not from triage, including `source: rollback`. It is untrue for an incident restore. Fixing it is outside B-94's files; logged as tabletop lesson L-1. |
| all others | no | Same shape (what changed, why, who approved, how to undo). Good plain words (B-04 test: at most 120 words, grade at most 8), but none says sorry, none says what was paused, none reaches the client contact or officer. |

Conclusion: the per-lever drafts stay for routine changes. In an incident the person gets `affected-person.md`, filled by a human. The per-lever draft may be read for its facts (who approved, what changed).
