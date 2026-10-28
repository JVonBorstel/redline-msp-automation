# Exports

Status: **built** for the operations metrics export (B-74); other exports are documented with their own item. Synthetic data only. Every figure is **fixture-based**.

> Independently built prototype. Not affiliated with any vendor's or real company's systems.

## Operations metrics (B-74)

```
uv run --frozen python -m workflows.reporting.ops export contoso-dental --as-of 2026-10-31
uv run --frozen python -m workflows.reporting.ops export --msp --as-of 2026-10-31
uv run --frozen python -m workflows.reporting.ops verify build/ops-metrics/contoso-dental
```

Writes `build/ops-metrics/<client>/` (that client's rows only) or `build/ops-metrics/_msp/` (every client, plus an `ALL` row in `summary`). Read-only: nothing in any ticket system changes. `--as-of` is a date; the wall clock is never read, so the same inputs give the same bytes.

| File | One row per | Use |
|---|---|---|
| `ticket_facts.csv/.json` | ticket | the fact table: times, SLA flags, reopen count, CSAT score |
| `weekly_metrics.csv/.json` | client and creation week | trend of volume, resolution, reopens |
| `summary.csv/.json` | client (and `ALL` in the MSP export) | headline figures: volumes, SLA attainment, response and resolution times, reopen rate, CSAT |
| `volume_by_category.csv/.json` | client and category | volume by category |
| `problem_clusters.csv/.json` | repeat-problem cluster | a topic raised by 3 or more tickets from 2 or more people, with a PROPOSED problem record id and title |
| `problem_cluster_tickets.csv/.json` | cluster and ticket | which tickets belong to a cluster |
| `csat_weekly.csv/.json` | client and answer week | CSAT trend |
| `csat_themes.csv/.json` | client and theme | CSAT comment themes with counts (comment text is never exported) |
| `data_dictionary.csv/.json` | column | table, column, type, unit, description, source |
| `manifest.json`, `manifest.json.sha256` | file | SHA-256 and row count of every file, the source files read, `as_of`, scope, label |

CSV is UTF-8, comma separated, LF line ends, header row, empty cell for "no value". JSON is a flat array of the same rows. `verify` re-hashes every file against the manifest and the manifest against its sidecar (`sha256sum -c manifest.json.sha256` works too); an extra, missing or edited file fails.

Rules that hold for every file:

- **No person columns.** No technician, assignee, requester or e-mail column, and no such value. The code refuses a table with a person-like column name, and a test scans every export. Not an oversight: ranking technicians from ticket metrics is never automated (NN-03).
- **No cross-client data.** A client folder names only that client; the MSP folder is the only place clients appear together.
- **Fixture-based.** Every row has `data_basis = fixture-based`; the manifest carries the label. Do not present these numbers as real results.

Definitions (wall-clock hours, completed = ticket `updated` when resolved, SLA targets from the PSA mock) are in the data dictionary and `specs/B-74.md`. How to load the files in Power BI: `docs/POWERBI_SEMANTIC_MODEL.md`.
