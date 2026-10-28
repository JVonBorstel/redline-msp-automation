# workflows/timeline (B-48)

Status: **mocked** on synthetic fixtures (change note `docs/changes/B-48.md`). Synthetic data only.

`export` prints one client's incident timeline from its verified audit chain (format incident-timeline/1, or Markdown with `--text`). `pack` prints a fact pack (`breach`, `recovery-point`, `firewall`, `dns`): facts and gaps only, no recommendation. Declaring an incident, notifying anyone, choosing a recovery point and changing firewall, SASE or DNS rules stay with people.

## Command

```
uv run --frozen python -m workflows.timeline export --client contoso-dental --audit-dir state/audit [--ticket T-...] [--text]
uv run --frozen python -m workflows.timeline pack recovery-point --client contoso-dental
```

## Inputs

`<audit-dir>/<client>.jsonl` (verified against its head pin first), `fixtures/tickets/`, `fixtures/dns/`, and `fixtures/devices.json` and `fixtures/fortigate/` here.

## Outputs

JSON Lines or Markdown on stdout. Nothing is written. Exit 0 printed, 2 bad input or a missing source, 3 the audit chain did not verify.

## What is mock

Firewall logs, devices, DNS and backup data are synthetic fixtures (shapes in `fixtures/SOURCES.md`).

## Spec and tests

Spec: `specs/B-48.md`. Tests: `tests/py/timeline/test_b48_timeline.py`.
