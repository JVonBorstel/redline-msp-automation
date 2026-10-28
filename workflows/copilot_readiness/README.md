# Copilot readiness (B-53)

Scores how ready one client's Microsoft 365 tenant is for Copilot, from SharePoint and OneDrive sharing fixtures. Report only: nothing is changed. Spec: `specs/B-53.md`. Synthetic data only.

## Run

    uv run --frozen python -m workflows.copilot_readiness contoso-dental [--as-of 2026-10-22] [--markdown]

Exit 0 = ran, 2 = bad input (message on stderr).

## Inputs

`fixtures/sharepoint/<client>.json` (see `fixtures/sharepoint/SOURCES.md`): the tenant's label and DLP coverage, and the sites with their links and shares. The client is explicit; only that client's file is opened, and a file whose `client` differs from its name is refused. A field that could hold a secret value is refused.

## Outputs

JSON (or Markdown) with the score out of 100, the formula and weights, the counts, `findings` (each with an id, the site, a severity, its points and a detail) and `recommendations`.

- Findings: `everyone-link` (anyone or Everyone-except-external link), `external-share` (share to an outside guest), `unlabelled-sensitive-site` (health, finance or legal content, no label).
- Recommendations: `label-gap` and `dlp-gap`, one per sensitive category on the client's sites that no label or DLP policy covers. Each is `recommendation-only` with 0 points.
- Score: `FORMULA` in `copilot_readiness.py`, printed with every report.

## Scopes

Reads fixtures only. No Graph, SharePoint or Purview call, and no write path.

## Example

`contoso-dental` scores 55: an Everyone-except-external link (15), a guest share (10) and an unlabelled health site (20), plus a label-gap and a dlp-gap recommendation for health content. `fabrikam-capital` scores 100.

## Limits

- Weights are invented for a fixture-based pipeline check, not calibrated on real tenants.
- Organization-wide links are not flagged. Item-level inheritance and group membership are not modelled.
- Every vendor field name is UNVERIFIED (written from memory, no Microsoft page opened).
