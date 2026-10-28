# workflows/baseline_proposals (B-38)

Turns TenantBaseline findings and the client's guest fixture into `user.disable` proposals for the normal approval queue. Proposes only: a lead approves, and nothing here runs a write lever. Synthetic data only. Spec: `specs/B-38.md`.

```
uv run --frozen python -m workflows.baseline_proposals --client contoso-dental --findings out/findings.json [--state .tmp/demo] [--as-of 2026-10-01]
```

Exit 0 = proposed, nothing to do, or deferred. Exit 2 = bad input (unreadable or wrong-tenant findings, bad config, bad guest file).

## What is proposed

- A stale member: a finding with `CheckId` `STALE` and `FixLever` `user.disable`. The proposal `ref` is the finding id.
- An expired guest: a guest in `fixtures/tenant/<client>/guests.json` that is still enabled and whose `expiresOn` is before the as-of date. The `ref` is the finding id if the baseline also flagged that account, otherwise the guest record id.
- Each proposal is dry-run first as `requested_by` (audited). The lead's approval records `Proposed.verification(by, at)`: method `finding-reference`, `ref` = that id.

## Never proposed

Break-glass accounts: the UPN starts with `breakGlass.namePrefix`, or the display name matches `breakGlass.candidateDisplayNamePattern`, both read from `levers/powershell/TenantBaseline/TenantBaseline.config.json`. An account that cannot be looked up is skipped, never proposed. Disabled accounts and guests that have not expired are skipped with the reason.

## Options (`config.json`)

| Key | Meaning |
|---|---|
| `version` | `1`. Unknown keys fail the load. |
| `max_proposals_per_client_per_run` | Blast-radius cap, an integer from 1 to 1000. Proposals past it are listed as `deferred` and picked up by the next run. Already-queued proposals and refused dry-runs do not use the cap. Default 5 (synthetic, UNVERIFIED as a policy number). |
| `requested_by` | Agent identity that dry-runs and queues (default `triage-bot`). The proposal itself is owned by the first technician (by id) who may act for the client, because the queue executes as its requester and `user.disable` needs a technician to execute. No such technician: the run fails loudly. |

## Known limits

- `user.disable` only accepts a UPN matching its registry pattern, which has no `#`. A real guest UPN (`..#EXT#@..`) is refused at the dry-run and shows up under `skipped` as "not queued".
- The mock tenant file `fixtures/tenant/contoso-dental.json` has none of the baseline's graph-fixture users, so their dry-run is refused there too. Both are reported, never hidden.
