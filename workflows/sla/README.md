# SLA breach watch and backlog grooming (workflows/sla)

Status: **built** (B-24). Synthetic data only; fixture-based; nothing is sent.

> Independently built prototype. Not affiliated with any vendor's or real company's systems.

**Purpose.** The end user who has waited longest is seen before the deadline, not after. For one `as_of`, per client: which open tickets will breach first response or resolution in the next N hours, which already have, and which tickets have been waiting on the client or a vendor too long, each with a follow-up *draft* a person edits and sends (HO-9).

**Run.**

    uv run --frozen python -m workflows.sla --as-of 2026-10-16T23:00:00Z --hours 4 --waiting-hours 72 --state .tmp/demo

Writes `<state>/sla/report.json`, `report.md` and `drafts/<ticket>.followup.md`, prints the report, and re-checks every number against the raw fixtures (C-21). Exit 0 = reconciled, 1 = does not reconcile, 2 = bad input. `--json` prints the JSON.

**Where numbers come from.** The SLA matrix (`fixtures/psa/<client>.json`, `slaSettings`) is read through the client's own PSA adapter (TEN-04). Tickets come from `fixtures/tickets/**` and the PSA adapter. Subject and body are never read into the report or a draft; gold labels are ignored.

**Assumptions (UNVERIFIED).** Wall-clock hours (no business-hour calendar, so it warns early, never late); `new` means no first response; `waiting-client` pauses the resolution clock, `waiting-vendor` does not; waiting age is `as_of - updated`. Details and acceptance ids B24-1 to B24-3 are in `specs/B-24.md`.

**Known limits.** Litware Legal has no PSA fixture, so its open tickets are counted as `cannot be judged: no SLA matrix`. The MSP's real SLA terms are UNKNOWN. With `as_of` on the Phase 2 snapshot (2026-10-16T23:00:00Z) most open tickets are long past their deadlines; the list is a demonstration of the mechanism, not a statement about real service.
