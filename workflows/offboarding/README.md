# Offboarding change plan with completion proof (B-36)

Synthetic data only. Builds on B-29 (identity levers), B-31 (license), B-32 (groups), B-33 (mailbox and OneDrive). Spec: `specs/B-36.md`.

```
uv run --frozen python -m workflows.offboarding plan      <upn> --client contoso-dental [--manager <upn>] [--as tech-ana] [--as-of 2026-10-21] [--leave-at 2026-10-23] [--state .tmp/demo]
uv run --frozen python -m workflows.offboarding verify    <upn> --client contoso-dental [--state .tmp/demo]
uv run --frozen python -m workflows.offboarding reconcile <upn> --client contoso-dental [--state .tmp/demo]
```

Each command prints JSON. Exit 0 means done and in order; exit 2 means refused, bad input, a step not in its target state, or a mismatch (the output lists each one).

## What each command does

- **plan** dry-runs every step through the runner (audited) and queues one proposal per change for a lead. It executes nothing. It saves the plan to `<state>/offboarding/<client>--<name>.plan.json`.
- **verify** is read-only. It reads each target state from the tenant files, lists every step not in its target state, and writes `<client>--<name>.completion.json` with a `sha256` over its body.
- **reconcile** checks that record against the audit log (chain verifies, every dry-run record is there and says the same thing, every applied step has an execute record).

## The steps, in order (`config.json`)

1. Block sign-in (`user.disable`)
2. Revoke sessions (`user.revoke-sessions`)
3. Convert the mailbox to shared (`mailbox.convert-shared`)
4. Automatic reply (`mailbox.set-auto-reply`)
5. OneDrive access for the manager until the end date (`mailbox.grant-onedrive-manager`)
6. One `group.remove-member` per group the person is in
7. One `license.remove` per license, only after its retention window (`retentionEndsOn`); before then the step is `deferred` and nothing is dry-run or proposed

Device steps are listed as `manual until W6` (no lever). Line-of-business apps are a checklist from `data/lob-apps.json`.

## Options

| Option | Default | Where |
|---|---|---|
| `--manager` | none: the OneDrive step is listed as skipped with the reason | CLI |
| `--as-of` | the `as_of` date in the client's mailbox fixture | CLI, `plan(as_of=)` |
| `onedrive_days` | 14 (the lever allows at most 30) | `config.json` |
| `auto_reply_message` | fixed text, letters and basic punctuation only | `config.json` |
| `order`, `steps` | the order and lever names above | `config.json` |
| `device_steps`, `device_label` | three manual device lines, `manual until W6` | `config.json` |
| `queue_source` | `baseline` (see the change note: the queue has no `offboarding` source yet) | `config.json` |
| LOB apps | one invented list per client | `data/lob-apps.json` |

## Step states

Plan: `proposed` (waits for a lead), `planned` (no queue given), `deferred` (retention window open), `already-met` (dry-run shows no change), `refused` (dry-run or queue refused; reason given), `skipped` (cannot be built; reason given).
Verify: `met`, `not-met`, `pending-retention` (license inside its window; not a failure, but not complete), `not-applicable` (no mailbox).

## Limits

- Mock only. Fixture field names are UNVERIFIED against vendor docs.
- The LOB list is a stand-in: no client record has such a field yet.
- The completion record is not an audit-chain entry (the audit modes and events are closed sets in `core/`); it pins the chain head and lists the plan's audit seqs instead.
