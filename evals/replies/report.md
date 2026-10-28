# Reply draft eval (B-25)

Label: **fixture-based**. 210 synthetic Phase 2 tickets (B-21) and the synthetic KB articles of three
invented clients; one author wrote both, so this checks the pipeline, not a model and not real tickets.
No model is called: draft sentences are quoted from the ticket's own client's KB.

## Gates (B25-3)

- Citation coverage: **100.0%** (192 of 192 sentences cite an article of the ticket's own client).
- Cross-client citations: **0**.
- Result: **PASS**.

## Per client

| Client | Tickets | Drafted | No source | Flagged | Sentences | Cited | Cross-client |
|---|---|---|---|---|---|---|---|
| contoso-dental | 50 | 8 | 37 | 5 | 16 | 16 | 0 |
| fabrikam-capital | 80 | 6 | 69 | 5 | 12 | 12 | 0 |
| litware-legal | 80 | 48 | 27 | 5 | 164 | 164 | 0 |
| **all** | 210 | 62 | 133 | 15 | 192 | 192 | 0 |

## Reported, not gated

- Source recall on tickets labelled with a reply source: 34 of 49 (69.4%).
- Drafts that cite none of the labelled articles: 6 of 49 labelled tickets. Still cited and from the right client, but a person must catch the wrong article.
- Drafts made for tickets labelled with no source and no injection: 21 of 161 (13.0%). A draft here is grounded in a real article, but a person must still check it answers the ticket.
- Closure follow-ups drafted for resolved tickets: 85 of 136 (a client without a fast-path contact in `fixtures/notify/contacts.json` gets `no draft`; litware-legal has none).
- Other no-draft outcomes: 0.

## Honest limits

- `MIN_SCORE` (2 keyword hits) was chosen by looking at these same fixtures, so recall is optimistic.
- The KB articles are written for technicians; a quoted sentence is correct but not always in the
  right voice for an end user. A person edits before sending (HO-9).
- Contoso and Fabrikam have 3 and 2 articles, so most of their tickets correctly get `no source`.
