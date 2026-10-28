"""Expiry watch (B-54, specs/B-54.md; W-M365-10, W-IDM-12, W-VND-05, W-IDM-10; C-38, C-20, C-21).

For one client this reads fixtures (never the network) and lists what is about to lapse or is weak: SPF, DKIM and
DMARC policy per domain; the DMARC aggregate report per domain; app-registration secrets and certificates; TLS
certificates; GDAP relationships that expire soon, have expired, or hold Global Administrator.

It only reports. Every finding is a reminder row with a due date and an owner (B54-3). The module imports no lever
runner and has no write path: nothing is renewed, rotated, published or changed by automation. A person renews.

Isolation (C-20). Every entry point takes the client explicitly and opens only that client's files; a file whose
``client`` field differs from its name is refused. Credentials are metadata only (id, label, end date): a field that
could hold a secret value is refused when the file is loaded, and no value is ever copied into a result.

Dates come from ``as_of`` (the fixture's pinned date by default), never the wall clock (STD-TS-4, STD-FX-6).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DNS_DIR = REPO_ROOT / "fixtures" / "dns"
DEFAULT_PARTNER_DIR = REPO_ROOT / "fixtures" / "partner"
REPORT_NOTE = "Reminders only: nothing was renewed, rotated or changed. A person acts."
DEFAULT_WITHIN_DAYS = 30
GDAP_MIN_WINDOW_DAYS = 60
UNASSIGNED = "unassigned"
# Entra role template id for Global Administrator. UNVERIFIED (from memory; see fixtures/partner/SOURCES.md).
GLOBAL_ADMIN_ROLE = "62e90394-69f5-4237-9190-012177145e10"
CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
DOMAIN = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$")
_SECRET_KEYS = frozenset({"secrettext", "secret", "value", "password", "privatekey", "key"})
_STATUS_ORDER = {"expired": 0, "global-admin": 1, "fail": 2, "expiring": 3, "warn": 4}


class ExpiryError(ValueError):
    """The input is bad (client id, file, XML); nothing was reported."""


@dataclass(frozen=True)
class Reminder:
    """One report row (B54-3): what, which client, why, the due date and the owner."""

    client: str
    kind: str  # dns | dmarc | app-secret | app-certificate | tls | gdap
    subject: str
    status: str  # expired | expiring | fail | warn | global-admin
    due: str  # ISO date: the expiry date, or the review-by date (as_of) for a policy gap
    owner: str
    detail: str
    days_left: int | None = None

    def row(self) -> dict[str, Any]:
        return {
            "client": self.client,
            "kind": self.kind,
            "subject": self.subject,
            "status": self.status,
            "due": self.due,
            "owner": self.owner,
            "detail": self.detail,
            "days_left": self.days_left,
            "action": "reminder-only",
        }


@dataclass(frozen=True)
class DomainCheck:
    domain: str
    owner: str
    spf: str  # pass | warn | fail
    dkim: str
    dmarc: str
    notes: tuple[str, ...]  # one plain sentence each for SPF, DKIM, DMARC

    @property
    def overall(self) -> str:
        states = (self.spf, self.dkim, self.dmarc)
        return "fail" if "fail" in states else ("warn" if "warn" in states else "pass")


@dataclass(frozen=True)
class DmarcSummary:
    domain: str
    policy: str
    adkim: str
    aspf: str
    messages: int
    dmarc_pass: int
    dmarc_fail: int
    dkim_aligned_pass: int
    spf_aligned_pass: int
    failing_sources: tuple[tuple[str, int, str], ...]  # (source ip, count, disposition)


@dataclass(frozen=True)
class ExpiryReport:
    client: str
    as_of: str
    within_days: int
    domains: tuple[DomainCheck, ...]
    dmarc: tuple[DmarcSummary, ...]
    reminders: tuple[Reminder, ...]
    note: str = REPORT_NOTE

    def rows(self) -> list[dict[str, Any]]:
        return [r.row() for r in self.reminders]


# --------------------------------------------------------------------------------------------------- loading


def _client(client: str) -> str:
    if not isinstance(client, str) or not CLIENT_ID.match(client):
        raise ExpiryError("client id must be a slug like 'contoso-dental'")
    return client


def _forbid_secrets(node: object, where: str) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() in _SECRET_KEYS:
                raise ExpiryError(f"{where}: field {key!r} could hold a secret value; fixtures carry metadata only")
            _forbid_secrets(value, where)
    elif isinstance(node, list):
        for item in node:
            _forbid_secrets(item, where)


def _load_json(path: Path, client: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ExpiryError(f"no fixture for client {client!r}: {path.name}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ExpiryError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(data, dict) or data.get("client") != client:
        raise ExpiryError(f"{path.name}: 'client' must equal {client!r}")
    _forbid_secrets(data, path.name)
    return data


def _when(text: object, where: str) -> date:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).astimezone(UTC).date()
    except ValueError as exc:
        raise ExpiryError(f"{where}: not an ISO date: {text!r}") from exc


def _owner(item: dict[str, Any]) -> str:
    owner = item.get("owner")
    return owner if isinstance(owner, str) and owner.strip() else UNASSIGNED


# --------------------------------------------------------------------------------------------------- DNS checks


def _spf_lookups(record: str) -> int:
    count = 0
    for term in record.lower().split()[1:]:
        bare = term.lstrip("+-~?")
        if bare.startswith(("include:", "exists:", "redirect=", "a:", "a/", "mx:", "mx/", "ptr:")) or bare in (
            "a",
            "mx",
            "ptr",
        ):
            count += 1
    return count


def _check_spf(spf: object) -> tuple[str, str]:
    if spf is None or spf == "":
        return "fail", "no SPF record"
    records = [spf] if isinstance(spf, str) else list(spf) if isinstance(spf, list) else [None]
    if len(records) != 1:
        return "fail", "more than one SPF record (invalid)"
    record = str(records[0]).strip()
    if not record.lower().startswith("v=spf1"):
        return "fail", "record does not start with v=spf1"
    if _spf_lookups(record) > 10:
        return "fail", "more than 10 DNS lookups (SPF permanent error)"
    final = record.lower().split()[-1]
    if final == "-all":
        return "pass", "ends with -all"
    if final == "~all":
        return "warn", "ends with ~all (soft fail); -all is stricter"
    return "fail", "no closing -all or ~all, or ?all / +all (does not restrict senders)"


def _check_dkim(dkim: object) -> tuple[str, str]:
    selectors = dkim if isinstance(dkim, list) else []
    if not selectors:
        return "fail", "no DKIM selector listed"
    published = [s for s in selectors if isinstance(s, dict) and s.get("published") is True]
    if not published:
        return "fail", "no DKIM key published for any selector"
    if len(published) < len(selectors):
        return "warn", "a listed DKIM selector has no published key"
    return "pass", f"{len(published)} selector(s) published"


def _check_dmarc(dmarc: object) -> tuple[str, str]:
    if not dmarc:
        return "fail", "no DMARC record"
    tags: dict[str, str] = {}
    for part in str(dmarc).split(";"):
        name, sep, value = part.partition("=")
        if sep:
            tags[name.strip().lower()] = value.strip().lower()
    if tags.get("v") != "dmarc1":
        return "fail", "record does not start with v=DMARC1"
    policy = tags.get("p", "")
    if policy not in ("none", "quarantine", "reject"):
        return "fail", "missing or invalid p= policy"
    if policy == "none":
        return "warn", "p=none only monitors; spoofed mail is still delivered"
    if "rua" not in tags:
        return "warn", f"p={policy} but no rua= address for aggregate reports"
    if tags.get("pct", "100") != "100":
        return "warn", f"p={policy} applies to only pct={tags['pct']} of mail"
    return "pass", f"p={policy}, aggregate reports requested"


def check_domain(entry: dict[str, Any]) -> DomainCheck:
    """SPF, DKIM and DMARC state of one domain entry, from record text only (no lookup)."""
    domain = str(entry.get("domain", ""))
    if not DOMAIN.match(domain):
        raise ExpiryError(f"bad domain name {domain!r}")
    spf, spf_note = _check_spf(entry.get("spf"))
    dkim, dkim_note = _check_dkim(entry.get("dkim"))
    dmarc, dmarc_note = _check_dmarc(entry.get("dmarc"))
    notes = (f"SPF: {spf_note}", f"DKIM: {dkim_note}", f"DMARC: {dmarc_note}")
    return DomainCheck(domain, _owner(entry), spf, dkim, dmarc, notes)


# --------------------------------------------------------------------------------------------------- DMARC XML


def parse_dmarc_aggregate(xml_text: str) -> DmarcSummary:
    """Summarise one RFC 7489 aggregate report. A document with a DTD or entity is refused (no expansion attacks)."""
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", xml_text, re.IGNORECASE):
        raise ExpiryError("aggregate report refused: it declares a DTD or entity")
    try:
        root = ElementTree.fromstring(xml_text)  # noqa: S314 - DTD and entities were refused above
    except ElementTree.ParseError as exc:
        raise ExpiryError(f"aggregate report is not valid XML: {exc}") from exc
    published = root.find("policy_published")
    if root.tag != "feedback" or published is None:
        raise ExpiryError("aggregate report must be a <feedback> with <policy_published>")
    domain = (published.findtext("domain") or "").strip().lower()
    if not DOMAIN.match(domain):
        raise ExpiryError("aggregate report has no usable policy_published/domain")
    total = passed = dkim_ok = spf_ok = 0
    failing: dict[tuple[str, str], int] = {}
    for record in root.findall("record"):
        row = record.find("row")
        evaluated = row.find("policy_evaluated") if row is not None else None
        if row is None or evaluated is None:
            raise ExpiryError("aggregate report record without row/policy_evaluated")
        try:
            count = int(row.findtext("count") or "")
        except ValueError as exc:
            raise ExpiryError("aggregate report record with a non-integer count") from exc
        if count < 0:
            raise ExpiryError("aggregate report record with a negative count")
        dkim = (evaluated.findtext("dkim") or "").strip().lower() == "pass"
        spf = (evaluated.findtext("spf") or "").strip().lower() == "pass"
        total += count
        dkim_ok += count if dkim else 0
        spf_ok += count if spf else 0
        if dkim or spf:  # DMARC passes when either aligned mechanism passes
            passed += count
        else:
            key = ((row.findtext("source_ip") or "?").strip(), (evaluated.findtext("disposition") or "?").strip())
            failing[key] = failing.get(key, 0) + count
    sources = sorted(((ip, n, disp) for (ip, disp), n in failing.items()), key=lambda t: (-t[1], t[0]))
    return DmarcSummary(
        domain=domain,
        policy=(published.findtext("p") or "").strip().lower(),
        adkim=(published.findtext("adkim") or "r").strip().lower(),
        aspf=(published.findtext("aspf") or "r").strip().lower(),
        messages=total,
        dmarc_pass=passed,
        dmarc_fail=total - passed,
        dkim_aligned_pass=dkim_ok,
        spf_aligned_pass=spf_ok,
        failing_sources=tuple(sources),
    )


# --------------------------------------------------------------------------------------------------- the report


def _expiry(
    out: list[Reminder],
    client: str,
    kind: str,
    subject: str,
    end: object,
    owner: str,
    as_of: date,
    within: int,
    what: str,
) -> None:
    due = _when(end, subject)
    days = (due - as_of).days
    if days < 0:
        detail = f"{what} expired {-days} day(s) ago"
        out.append(Reminder(client, kind, subject, "expired", due.isoformat(), owner, detail, days))
    elif days <= within:
        detail = f"{what} expires in {days} day(s)"
        out.append(Reminder(client, kind, subject, "expiring", due.isoformat(), owner, detail, days))


def _dns_rows(out: list[Reminder], client: str, chk: DomainCheck, day: date) -> None:
    states = (chk.spf, chk.dkim, chk.dmarc)
    problems = [note for note, state in zip(chk.notes, states, strict=True) if state != "pass"]
    if problems:
        out.append(Reminder(client, "dns", chk.domain, chk.overall, day.isoformat(), chk.owner, "; ".join(problems)))


def build_report(
    client: str,
    *,
    as_of: str | None = None,
    within_days: int = DEFAULT_WITHIN_DAYS,
    dns_dir: Path = DEFAULT_DNS_DIR,
    partner_dir: Path = DEFAULT_PARTNER_DIR,
) -> ExpiryReport:
    """Everything that is expiring or weak for ONE client, as reminder rows. Reads that client's files only."""
    client = _client(client)
    if not isinstance(within_days, int) or isinstance(within_days, bool) or not 1 <= within_days <= 366:
        raise ExpiryError("within_days must be an integer from 1 to 366")
    dns = _load_json(Path(dns_dir) / f"{client}.json", client)
    partner = _load_json(Path(partner_dir) / f"{client}.json", client)
    day = _when(as_of or dns.get("as_of"), "as_of")
    out: list[Reminder] = []

    checks = tuple(check_domain(d) for d in dns.get("domains", []))
    for chk in checks:
        _dns_rows(out, client, chk, day)
    owners = {c.domain: c.owner for c in checks}

    summaries: list[DmarcSummary] = []
    for path in sorted(Path(dns_dir).glob(f"{client}-dmarc-*.xml")):
        summary = parse_dmarc_aggregate(path.read_text(encoding="utf-8"))
        if summary.domain not in owners:
            raise ExpiryError(f"{path.name}: domain {summary.domain!r} is not one of {client!r}'s domains")
        summaries.append(summary)
        if summary.dmarc_fail:
            detail = (
                f"{summary.dmarc_fail} of {summary.messages} message(s) failed DMARC "
                f"(policy {summary.policy}); review the sending sources"
            )
            out.append(
                Reminder(client, "dmarc", summary.domain, "warn", day.isoformat(), owners[summary.domain], detail)
            )

    for cert in dns.get("tlsCertificates", []):
        subject = str(cert.get("subject"))
        _expiry(out, client, "tls", subject, cert.get("notAfter"), _owner(cert), day, within_days, "TLS certificate")

    for app in partner.get("appRegistrations", []):
        name, owner = str(app.get("displayName")), _owner(app)
        for cred in app.get("passwordCredentials", []):
            subject = f"{name} / {cred.get('displayName')}"
            _expiry(
                out, client, "app-secret", subject, cred.get("endDateTime"), owner, day, within_days, "client secret"
            )
        for cred in app.get("keyCredentials", []):
            subject = f"{name} / {cred.get('displayName')}"
            _expiry(
                out, client, "app-certificate", subject, cred.get("endDateTime"), owner, day, within_days, "certificate"
            )

    for rel in partner.get("gdapRelationships", []):
        subject, owner = str(rel.get("displayName")), _owner(rel)
        end = _when(rel.get("endDateTime"), subject)
        days = (end - day).days
        if rel.get("status") == "expired":
            detail = "GDAP relationship has expired; support access through it is gone"
            out.append(Reminder(client, "gdap", subject, "expired", end.isoformat(), owner, detail, days))
            continue
        _expiry(
            out,
            client,
            "gdap",
            subject,
            rel.get("endDateTime"),
            owner,
            day,
            max(within_days, GDAP_MIN_WINDOW_DAYS),
            "GDAP relationship",
        )
        if GLOBAL_ADMIN_ROLE in (rel.get("roles") or []):
            detail = "relationship holds Global Administrator (decision D6-09: no Global Admin)"
            out.append(Reminder(client, "gdap", subject, "global-admin", end.isoformat(), owner, detail, days))

    out.sort(key=lambda r: (_STATUS_ORDER[r.status], r.due, r.kind, r.subject))
    return ExpiryReport(client, day.isoformat(), within_days, checks, tuple(summaries), tuple(out))


def render_markdown(report: ExpiryReport) -> str:
    """A plain report a person reads. Fixture-based; reminders only."""
    lines = [
        f"# Expiry watch: {report.client} (as of {report.as_of}, window {report.within_days} days)",
        "",
        f"> Fixture-based, synthetic. {report.note}",
        "",
        "## Reminders",
        "",
        "| Due | Owner | Kind | Subject | Status | Detail |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    lines += [f"| {r.due} | {r.owner} | {r.kind} | {r.subject} | {r.status} | {r.detail} |" for r in report.reminders]
    if not report.reminders:
        lines.append("| - | - | - | nothing expiring or weak | ok | - |")
    lines += [
        "",
        "## Mail authentication per domain",
        "",
        "| Domain | SPF | DKIM | DMARC |",
        "| --- | --- | --- | --- |",
    ]
    lines += [f"| {d.domain} | {d.spf} | {d.dkim} | {d.dmarc} |" for d in report.domains]
    lines += [
        "",
        "## DMARC aggregate reports",
        "",
        "| Domain | Policy | Alignment (dkim/spf) | Messages | DMARC pass | DMARC fail |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {s.domain} | {s.policy} | {s.adkim}/{s.aspf} | {s.messages} | {s.dmarc_pass} | {s.dmarc_fail} |"
        for s in report.dmarc
    ]
    return "\n".join(lines) + "\n"
