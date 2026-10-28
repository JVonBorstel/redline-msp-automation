# Power BI semantic model for the operations exports

Status: **document-only** for the Power BI side (no `.pbix` was built and Power BI was not opened or tested; UNVERIFIED). The tables it describes are **built** (B-74, `workflows/reporting/ops`). Every figure is **fixture-based**, synthetic.

> Independently built prototype. Not affiliated with any vendor's or real company's systems.

## Load

Get data, Text/CSV, one query per `.csv` in an export folder (or JSON, which has the same rows). Set column types from `data_dictionary.csv` (`date`, `integer`, `decimal`, `text`). Empty cells are "no value": keep them as blank, not zero. Use the MSP export for an all-clients report; use a client folder for a report shared with that client (it holds no other client).

## Model (star around `ticket_facts`)

| From | To | Key | Cardinality |
|---|---|---|---|
| `summary` | `ticket_facts` | `client` | one to many |
| `weekly_metrics` | `ticket_facts` | `client` + `week_start` | one to many |
| `volume_by_category` | `ticket_facts` | `client` + `category` | one to many |
| `problem_clusters` | `problem_cluster_tickets` | `cluster_id` | one to many |
| `problem_cluster_tickets` | `ticket_facts` | `ticket_id` | many to one |
| `csat_weekly`, `csat_themes` | `summary` | `client` | many to one |

Tables: `ticket_facts`, `weekly_metrics`, `summary`, `volume_by_category`, `problem_clusters`, `problem_cluster_tickets`, `csat_weekly`, `csat_themes`. Add a date table over `week_start` / `created_date` if you want calendar slicers.

## Measures

Prefer the pre-computed `summary` columns for headline cards: `sla_first_response_attainment`, `sla_resolution_attainment`, `mean_first_response_hours`, `mean_completed_hours`, `reopen_rate`, `csat_mean`. If a measure is rebuilt from `ticket_facts`, use the same definitions:

- Attainment = sum(`sla_*_met`) / count of non-blank `sla_*_met`. Never divide by all tickets.
- Reopen rate = tickets with `reopen_count` >= 1 / tickets that are resolved or have `reopen_count` >= 1.
- Do not average the `ALL` row's ratios with client rows; `ALL` is pooled from tickets and its SLA figures cover only clients that have an SLA (`sla_status = ok`).
- Time until the person can work again is `user_confirmed_working_hours` (a PROPOSED field, empty when not recorded) next to `completed_hours`.

## Do not

- Do not add a technician or assignee column to any report; it is not in the data and building one would break NN-03.
- Do not label these figures as real. A report page should show the `data_basis` value.
