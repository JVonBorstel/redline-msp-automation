# Tabletop 2026: wrong user disabled at Contoso Dental
Status: **recorded** (one rehearsal on synthetic tenants; the commands were replayed by a script, not by people; no real tenant touched). Not legal advice. Synthetic data only.

> Independently built prototype. Not affiliated with any vendor's or real company's systems.

Roadmap item B-94, acceptance B94-3. Runbook rehearsed: `docs/runbooks/ai-incident-response.md` (steps `IR-1` to `IR-9`). Control `C-34`.

Date: 2026-10-27 (UTC)

## How to read the times

The runbook's own command blocks were run in order against a private synthetic state folder (the replay in `tests/py/governance/test_b94_incident_response.py` does the same on every test run). The times are the wall-clock UTC start of each step in that replay. They show how long the **commands** take, a few seconds each. They say nothing about how long people take to read, call, decide and write. Do not quote them as a recovery time (the one-business-hour target of IR-3 is an MSP question, GQ-09). In a live exercise, people write their own times in the same table.

## Scenario (synthetic)

Contoso Dental (synthetic dental practice, data class floor `DC-4`, PHI). Ticket text from `fixtures/tenant/contoso-dental.json`: "Jamie Chen left the practice on Friday. Please disable their account." The disable proposal named the wrong user, `priya.nair@contosodental.example` (Priya Nair, dental hygienist), instead of the leaver `jamie.chen@contosodental.example`. An approver let it through, and `user.disable` ran. Priya cannot sign in. This is the AIR-3 pattern: right lever, wrong person, caught by nobody before the execute.

Cast, by role (D6-17): on-call lead (`lead-lee`), technician on call (`tech-ana`), engineer, compliance owner, account manager, AI and Automation Engineer. Who holds these roles at the MSP is GQ-01 (unknown); in a live exercise people read the roles aloud.

## Inject script (facilitator reads one line at a time)

| Inject | Facilitator says | Expected move |
| --- | --- | --- |
| 0 | "Priya Nair, hygienist at Contoso Dental, phones the fast line: she cannot sign in; patients are waiting." | IR-1: verify the chains, check overdue reviews |
| 1 | "The audit shows `user.disable` ran on her account an hour ago. Fabrikam Capital also uses the lever. Is it safe to carry on?" | IR-2: lead pauses `user.disable` for every client; asks what a pause costs |
| 2 | "Priya is waiting." | IR-3: roll back from the recorded before-state; call her on the number on file; a lead approves |
| 3 | "How many other wrong disables are there?" | IR-4: verify, run the audit filter over every chain, export Contoso's own chain only |
| 4 | "Contoso is a dental practice. Do we have to tell anyone besides Priya?" | IR-5: compliance owner decides; no deadline is quoted from memory; counsel is asked |
| 5 | "Write to Priya, to the practice manager and to the privacy officer." | IR-6: a person fills the `governance/templates/notifications/` templates; no automation sends |
| 6 | "Why did a wrong target get through?" | IR-7: name the fix; add a case beside the lever's tests |
| 7 | "Five business days later." | IR-8: blameless review |
| 8 | "Can `user.disable` come back for the real leaver?" | IR-9: hold the other clients, resume, dry-run on Contoso, then rings |

Ground rules: nobody reads real data; no names beyond the synthetic ones; the facilitator does not accept "we would check" without the command or the file where it lives.

## Timeline

| Step | Time (UTC) | What was run or decided | Result |
| --- | --- | --- | --- |
| IR-1 | 20:17:28 | `core.levers verify`, `core.levers reviews` after the wrong disable ran (audit `seq` 2 in `contoso-dental`) | chain intact (2 records); no overdue review |
| IR-2 | 20:17:31 | `core.levers pause user.disable --as lead-lee` (all clients), `core.levers paused` | paused for all clients; a dry-run of the lever is now denied with the pause reason |
| IR-3 | 20:17:34 | `workflows.rollback 2 --client contoso-dental --as tech-ana`; lead approves the `user.enable` proposal | outcome `proposed`, nothing executed by the workflow; the approval executed it; Priya's `accountEnabled` is true again |
| IR-4 | 20:17:38 | `core.levers verify`; PowerShell filter over `audit/*.jsonl`; `core.levers export --client contoso-dental` | one applied `user.disable` execute, the wrong one; the export holds `contoso-dental.jsonl` and its head pin only |
| IR-5 | 20:17:43 | class floor query (`INDUSTRY_FLOOR`) | dental is `DC-4`; whether PHI was exposed or made unavailable is the compliance owner's call, with counsel (not decided by the script) |
| IR-6 | 20:17:43 | `workflows.notify <proposal-id>` read for facts; the three templates are filled by people (not in the replay) | the per-lever draft gives an untrue reason (L-1) |
| IR-7 | 20:17:45 | name the fix; the test and lint commands are listed, not re-run inside the replay | fix not built (L-3) |
| IR-8 | 20:17:45 | blameless review set for five business days later | this document is the record for the rehearsal |
| IR-9 | 20:17:45 | hold `fabrikam-capital`, resume globally, dry-run `user.disable` for `jamie.chen@contosodental.example` on Contoso, resume `fabrikam-capital`, `core.levers paused` | the dry-run targets the real leaver; `no levers are paused` |

The replay ended at 20:17:53. The chain `_msp` holds the global pause and resume; each client's own chain holds its client pause and resume.

## What worked

- Every command in the runbook exists and ran; the replay fails if one is renamed.
- The restore is a normal proposal, so the four-eyes rule held even in an incident.
- One client's evidence can be exported without any other client's records.

## Lessons

- **L-1** The per-lever draft for the restore (`workflows.notify <proposal-id>`) says "Why: a security check flagged it (audit-2)". That is untrue for an incident restore: `workflows/notify/notify.py` gives that reason to every proposal that is not from triage, including `source: rollback`. Follow-up: the owner of B-04 changes the reason for rollback proposals; until then the runbook says to use the draft for facts only, and a test fails when the draft changes so this lesson is re-read.
- **L-2** A global pause also stops the correct disable for the real leaver, and `resume` has no ring option, so IR-9 needs one `pause --client` per other client before the global `resume`. Follow-up: the engineer decides whether a ring-aware resume is worth building (CM-5); until then the on-call lead tells the client about the side effect.
- **L-3** The wrong target was approved by a person, as AIR-3 predicts, so the fix cannot be a code change alone. Requester verification (C-30) and showing the ticket text beside the target on the approval page might have caught it. Follow-up: the engineer files the idea against the approval page and C-30; not built in B-94.
- **L-4** There is no audit query command; IR-4 is a PowerShell filter that prints times in the viewer's local zone while the audit stores UTC. Follow-up: the engineer adds a `core.levers` query command later; until then read `ts` as UTC and say so in the review.
- **L-5** The templates deliberately state no legal deadline of their own. Follow-up: the compliance owner and counsel confirm the HIPAA, FTC and state timelines and the client contract terms (GQ-01, GQ-06) before the templates are used for real.
- **L-6** The times above are machine times. Follow-up: run the inject script once with real people in a room, write their times in the table, and only then discuss a restore target.

## Not covered

No paging or chat tool, no real PSA ticket, no real notification sent, and no judgement about whether the event is a reportable breach.
