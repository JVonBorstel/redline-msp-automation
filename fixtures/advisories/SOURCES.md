# Advisory fixture sources

Status: **mocked** (fixtures only). Independently built prototype. Synthetic data only. Pinned to `as_of` 2026-10-21T12:00:00Z; results computed from these files are fixture-based.

Every file carries a `_note` that starts with `SYNTHETIC`, and every per-client file's `client` matches its file name (STD-FX-3). Vendors (Examplesoft, Exampleware, Northwind Systems, Tailspin Labs, Adatum), products, hosts and CVE ids (`CVE-2099-*`) are invented and match nothing real.

## Layout

| File | Imitates | Status |
| --- | --- | --- |
| `kev-feed.json` | CISA Known Exploited Vulnerabilities JSON feed | Field names **Verified 2026-10-21** |
| `inventory/<client>.json` | a per-client software inventory (stands in for an RMM software list) | Neutral shape of this repo. No RMM schema is claimed. |
| `scans/nessus/<client>.json` | a Tenable Nessus CSV export, one JSON object per row (MP-26) | Column names **UNVERIFIED** |
| `scans/vpentest/<client>.json` | a Vonahi vPenTest findings report (MP-25) | Every field name **UNVERIFIED** |

## CISA KEV

Source: the public feed `https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json` (catalog page: https://www.cisa.gov/known-exploited-vulnerabilities-catalog). Read on 2026-10-21 (catalogVersion `2026.10.21`, 1754 entries at the time).

Verified on that date, from the live file:

- Top level: `title`, `catalogVersion`, `dateReleased`, `count`, `vulnerabilities`.
- Each entry: `cveID`, `vendorProject`, `product`, `vulnerabilityName`, `dateAdded` (`YYYY-MM-DD`), `shortDescription`, `requiredAction`, `dueDate` (`YYYY-MM-DD`), `knownRansomwareCampaignUse` (values seen: `Known`, `Unknown`), `forensicTriage` (values seen: `Yes`, `No`), `notes` (one string), `cwes` (list of strings).
- There is **no version or version-range field**. So matching a KEV entry to an inventory is by vendor and product only, and a person must check the installed version.

Not verified: how the feed changes over time (new fields may appear, as `forensicTriage` seems to have); the fixture loader rejects an unknown field so a changed shape fails loudly. The fixture adds one key the real feed does not have, `as_of`, to pin the date.

## Tenable Nessus export (MP-26)

No call was made to Nessus and no export was read. The export columns are written from general knowledge (see the table above).

The columns used are the ones a Nessus CSV export is commonly known to have: `Plugin ID`, `CVE`, `CVSS v2.0 Base Score`, `Risk`, `Host`, `Protocol`, `Port`, `Name`. **All UNVERIFIED**: they come from general knowledge, not from a vendor document read on the build date. What would verify them: a real (redacted) export or the Tenable export documentation. Not claimed: other columns (Synopsis, Description, Solution, Plugin Output), CVSS v3 columns, the `.nessus` XML format, and whether `CVE` can hold several ids in one cell (the loader accepts a comma-separated list; that is an assumption).

## Vonahi vPenTest findings report (MP-25)

No public schema or sample report was found or read. **Every field name is UNVERIFIED and invented** as a neutral stand-in for a penetration-test findings report.

## Seeded cases (STD-FX-4)

| Client | What the fixtures seed | Expected |
| --- | --- | --- |
| `contoso-dental` | EdgeVPN firewall (internet, critical) with a KEV CVE seen by inventory, Nessus and the pen test; RemoteDesk on a file server with ransomware-known KEV, next declared window falls after the KEV due date; PrintHub on the only front-desk PC; one Nessus row and one pen-test finding with no KEV CVE | 4 exposed rows on 3 devices, 2 emergency rows |
| `fabrikam-capital` | RemoteDesk on an internet-facing RDS server (two CVEs), MailGate on an internet-facing mail server, PrintHub on a workstation, and a Nessus-only finding on `FC-OLD07`, which is not in the inventory | 5 exposed rows on 4 devices, 3 emergency rows, `FC-OLD07` listed as a scanner host not in the inventory |
| `litware-legal` | **clean twin**: no inventory product is in the KEV fixture; scanner rows carry only non-KEV or no CVE | 0 exposed rows |

`CVE-2099-0005` (Tailspin Labs Practice Manager) is in the feed and in no client's inventory.
