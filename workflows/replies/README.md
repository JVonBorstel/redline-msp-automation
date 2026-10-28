# Draft replies and closure follow-ups (workflows/replies)

Status: **built** (B-25). Synthetic data only; nothing is sent.

> Independently built prototype. Not affiliated with any vendor's or real company's systems.

**Purpose.** Two drafts a technician reviews and sends (HO-9): a **reply** to the end user made only of sentences from the client's own knowledge base, each followed by its article id (`[KB-CD-001]`), and a **closure follow-up** for a resolved ticket that confirms the fix in plain words and offers the way back. The Air Canada failure mode (AIR-4) is closed by construction: with no source article the answer is `no draft: no source article`, and the code never writes a sentence of its own into a reply.

**Run.**

    uv run --frozen python -m workflows.replies reply T-5102 --state .tmp/demo
    uv run --frozen python -m workflows.replies closure T-5104 --state .tmp/demo --fix "We set up your new phone"

Writes `<state>/replies/<ticket>.<kind>.md` and prints it. Exit 0 = draft written; 1 = no draft (the `no draft: ...` line is printed and written); 2 = unknown ticket or bad input. The state folder's `tenant/` is used when present.

**How a reply is made.**
1. `detect_injection` scans the ticket text (C-12). A flagged ticket gets `no draft: ...` and no search.
2. `kb.search` runs through the lever runner as `triage-bot` for the ticket's client (audited, scoped, C-26). Subject and body only become search keywords (at most 100 characters).
3. An article counts as a source with at least 2 keyword hits (`MIN_SCORE`); at most 2 articles, the second at least half as strong as the first.
4. The draft quotes the article title and up to 3 sentences per source, each followed by `[<id>]`. Text comes from the same client's tenant KB, never from the ticket.
5. `check_citations` validates the result (every sentence cited, every id in this client's KB). A draft that fails is never returned. Any later model-written reply must pass the same check.

**Closure.** Only for a `resolved` ticket. Values: ticket id, first name (from the tenant), the technician's `--fix` line (one plain line) or the matched KB guide (cited), and the client's fast-path number from `fixtures/notify/contacts.json`. A client with no contact there gets `no draft` (fails closed).

**Permissions.** Reads only (`kb.search`, read class, agent role). It writes nothing but `<state>/replies/` and the audit log. No network, no mail library, no model.

**Eval result (fixture-based).** `uv run --frozen python -m evals.replies.report` writes `evals/replies/report.md`: on the 210 synthetic Phase 2 tickets, citation coverage 100% (192 of 192 sentences) and 0 cross-client citations. Source recall on labelled tickets is 69% and is reported, not gated.

**Known limits.**
- KB articles are written for technicians, so a quoted sentence can be correct but in the wrong voice for an end user; the person edits before sending.
- Keyword search is crude: 6 of 49 labelled tickets get a cited draft from the wrong article, and 21 of 161 tickets labelled "no source" get a draft from a real but loosely related article. A person must check that the draft answers the ticket.
- `kb.search` is not enabled for `litware-legal` in `levers/registry.json`, and `triage-bot` has no Litware scope, so the CLI returns `no draft: the knowledge base search was not allowed` for Litware tickets until a registry and identity change (not owned by this item). The eval uses a throwaway copy that enables it.
- Closure drafts for `litware-legal` need a contacts entry (not built). Contoso and Fabrikam KBs are thin (3 and 2 articles).
- No record yet that a person sent the draft.
