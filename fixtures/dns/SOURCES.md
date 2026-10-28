# DNS, TLS and DMARC aggregate fixture sources

These fixtures are **synthetic**: invented clients, `.example` domains, documentation IP addresses (RFC 5737: 192.0.2.0/24, 198.51.100.0/24). Nothing was looked up in real DNS or captured from a real certificate store or mail receiver. Pinned to `as_of` 2026-10-21. Results are fixture-based. Tests make no live lookup.

- `fixtures/dns/<client>.json`: per domain the SPF, DKIM selector and DMARC record texts, and the TLS certificates (`tlsCertificates`, subject and expiry only). The `client` field matches the file name.
- `fixtures/dns/<client>-dmarc-<domain>.xml`: one DMARC aggregate report per domain.
- Seeded problems (contoso-dental): `contosodental.example` has SPF `~all` and DMARC `p=none`; `smile.contosodental.example` has no SPF, no DKIM and no DMARC; `appointments.contosodental.example` is clean; certificate `tls-vpn` ends within 30 days. The aggregate report for `contosodental.example` has 164 messages, 44 failing DKIM alignment and 14 failing both DKIM and SPF. fabrikam-capital is the clean twin and triggers nothing.

## Record texts

| Fixture field | Format | Status |
| --- | --- | --- |
| `spf` | SPF record text, RFC 7208 section 4 (`v=spf1 ... all`) | Verified by RFC text as a shape; RFC not re-read in this session, so the mechanism rules used by the check (`all` qualifiers, 10 DNS lookups limit) are UNVERIFIED against it |
| `dkim[].selector`, `published` | selector name and whether a key record is published at `<selector>._domainkey.<domain>` (RFC 6376 section 3.6.2.1) | selector names are invented; the shape is UNVERIFIED against the RFC text |
| `dmarc` | DMARC record text at `_dmarc.<domain>` (RFC 7489 section 6.3 tags `v`, `p`, `rua`, `pct`) | UNVERIFIED against the RFC text in this session |
| `tlsCertificates` | subject and `notAfter` only | invented, not a vendor shape |
| `owner` | who in the MSP owns the item | invented |

## DMARC aggregate XML

The elements follow the aggregate report schema in RFC 7489 Appendix C (https://www.rfc-editor.org/rfc/rfc7489): `feedback`, `report_metadata` (`org_name`, `email`, `report_id`, `date_range/begin,end`), `policy_published` (`domain`, `adkim`, `aspf`, `p`, `sp`, `pct`), `record` with `row` (`source_ip`, `count`, `policy_evaluated/disposition,dkim,spf`), `identifiers/header_from` and `auth_results` (`dkim/domain,result,selector`, `spf/domain,result`). **UNVERIFIED:** the element list was written from memory, not compared with the RFC in this session. MP-22 (EasyDMARC) collects reports of this format; EasyDMARC's own export, API and dashboard shapes are NOT imitated. In `policy_evaluated`, `dkim` and `spf` mean "aligned and passing" (the policy result), as in the RFC; the checker reads those.
