# Teams approval prompts (B-88)

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only.

Status: **mocked, dry-run only.** Nothing is posted to Teams, no network call is made, no credential is held. The card
shape is **UNVERIFIED** against Microsoft documentation (see `specs/B-88.md`).

## What it does

For one client, it takes every **pending** proposal in the approval queue and builds the Teams card for it with
`adapters/m365` (`build_approval_card`). It then writes what it *would* post to
`<state>/teams-approvals/<client>.json`: one entry per card (proposal id, lever, the card, and its SHA-256) plus the
pending proposals that got no card and why. The file is replaced on each run and is byte-identical for the same queue
and audit.

Each card shows the person affected, the lever's L1 impact line, the dry-run diff as the audit holds it, and the undo
lever. It has exactly one action: a link (`Action.OpenUrl`) back to the loopback approval page
(`http://127.0.0.1:<port>/#<proposal id>`). **The card cannot approve or reject.** A lead decides on the approval page,
signed in, with the four-eyes rule and the requester check (B-03, B-89).

## What it never does

- It never decides: no call to `ProposalQueue.decide`, `refuse`, `propose` or the lever runner (a test reads the code).
- It never posts: `plan_posts(..., dry_run=False)` is refused, and there is no Teams, Graph or HTTP code (a test reads
  the imports).
- It never writes the queue or the audit chains (a test compares their bytes before and after).
- It never mixes clients: a run covers one client id, and only that client's proposals get a card.
- It reads no free text of its own. The proposal reason and parameters reach the card only through the adapter, which
  makes each one plain line and withholds text the injection tripwire flags.

## How to run

From the repo root (synthetic state folder; the queue's demo seed is `uv run --frozen python -m core.queue seed --demo`):

```powershell
uv run --frozen python -m workflows.teams_approvals contoso-dental --state .tmp/demo
uv run --frozen python -m workflows.teams_approvals contoso-dental --state .tmp/demo --base-url http://127.0.0.1:8765
```

Exit 0: recorded (zero cards is fine). Exit 2: bad client id, a link base that is not the loopback page, or an
unreadable queue; nothing is written.

## Known limits

- Dry-run only. Posting needs a reviewed Teams adapter (incoming webhook or Graph `chatMessage`), its own approval
  record and a secret store; none of that exists.
- One file per client per run; there is no history of earlier runs and no de-duplication across runs (a card that
  "was posted" yesterday is recorded again today while the proposal is still pending).
- The card reflects the dry-run on record, not the tenant at decision time.

Tests: `tests/py/m365/test_b88_m365.py` (`test_b88_teams_*`).
