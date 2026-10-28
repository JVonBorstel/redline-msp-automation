# Notice drafts (workflows/notify)

Status: **built** (B-04). Synthetic data only; nothing is sent.

> Independently built prototype. Not affiliated with any vendor's or real company's systems.

**Purpose.** After a lead approved a write-lever proposal and it was executed, draft a plain-words message for the person whose account changed: what changed, why, who approved it, how to undo it, and the fast way back (EU-1, EU-2, C-35, C-36). A person reviews and sends it (HO-9); the first line of every draft says so.

**Run.**

    uv run --frozen python -m workflows.notify <proposal-id> --state .tmp/demo

Writes `.tmp/demo/notices/<proposal-id>.md` and prints it. Exit 0 = draft written; 1 = refused (the proposal is not `executed`); 2 = unknown id, missing queue or bad input.

**Inputs (trusted fields only).** The proposal in `<state>/queue.jsonl` (read only), the ticket's form fields (`requester`, `affected_user`; never subject or body), the person's `displayName` in the state folder's mock tenant, the approver's display name from `config/identities.json`, and the client's fast-path line from `fixtures/notify/contacts.json`. No model is called.

**Templates.** One per write lever: `templates/<lever>.md`, `string.Template` placeholders `$first_name`, `$request`, `$approver`, `$team`, `$fast_phone`, `$hours`. A new write lever without a template fails `tests/py/notify/test_b04_notify.py`.

**Permissions.** Reads only; needs no lever role. It writes nothing outside `<state>/notices/`.

**Eval result (fixture-based).** Both templates are at most 120 words (101 and 86) with a Flesch-Kincaid grade near 2 to 3 by the test's own syllable heuristic; no secret-shaped value and no personal phone number. These are pipeline checks on synthetic fixtures, not a readability study.

**Known limits.** No reply-to address yet (phone only); one language (English); the person's first name comes from `displayName` and falls back to "there"; the queue is read without its lock.
