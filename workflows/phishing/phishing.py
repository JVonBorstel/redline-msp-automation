"""Phishing triage of a user-reported message, as data only (B-45, specs/B-45.md).

Inventory W-SEC-03, W-M365-03, W-M365-04; controls C-12, C-13, C-14, C-05, C-06.

The user who reports a phish gets an answer, and the next user is protected. A report arrives in Microsoft
Defender's user-reported shape or INKY's "Report Phish" shape (MP-21); both are UNVERIFIED stand-ins (see
fixtures/mailflow/SOURCES.md). Each shape has one small mapper into ``ReportedMessage``; after it there is one
path (B45-4).

Data only (B45-1). Headers are read as text, URLs are split with ``urllib.parse`` and never requested, and
attachments are judged by name only; the mapper drops their content. Every finding names the field it came from,
and the draft lists the fields read. No module here imports a network, mail or archive library (a test checks it).

Untrusted text (C-12, B45-3). Subject, From, body and link text are scanned with ``detect_injection``. They never
change the verdict; the draft shows them only inside ``wrap_untrusted``, and a flagged report's text is withheld
and it gets no lever suggestion at all (D-022).

Levers (B45-2). Suggestions come from structured fields only (STD-LV-9): ``message.trace`` for a suspicious or
worse message, ``quarantine.release`` only for a likely-clean one that names a quarantine id. Nothing runs here;
the release lever itself also refuses high-confidence phish and malware.

No model is called: the weights and thresholds below are the rules a reviewer reads (D-022).
"""

from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from core.guard import detect_injection, wrap_untrusted
from core.paths import REPO_ROOT
from workflows.notify import DRAFT_HEADER

DEFAULT_REPORTS_DIR = REPO_ROOT / "fixtures" / "mailflow" / "reports"
Verdict = Literal["high-confidence-phish", "suspicious", "likely-clean"]
VERDICTS: tuple[Verdict, ...] = ("high-confidence-phish", "suspicious", "likely-clean")
HEADER_FIELDS = ("Authentication-Results", "From", "Reply-To", "Return-Path")
HIGH_AT, SUSPICIOUS_AT = 6, 2
WEIGHTS = {
    "spf-fail": 2,
    "dkim-fail": 1,
    "dmarc-fail": 3,
    "auth-missing": 1,
    "reply-to-mismatch": 2,
    "return-path-mismatch": 1,
    "lookalike-domain": 3,
    "not-https": 1,
    "userinfo-in-url": 3,
    "ip-host": 3,
    "punycode-host": 2,
    "shortener": 1,
    "link-text-mismatch": 2,
    "risky-attachment": 4,
    "double-extension": 2,
}
_AUTH_BAD = {"spf": ("fail", "softfail"), "dkim": ("fail",), "dmarc": ("fail",)}
SHORTENERS = frozenset({"bit.ly", "tinyurl.com", "t.co", "short.example"})  # names only; never resolved
RISKY_EXTENSIONS = frozenset({"exe", "scr", "js", "vbs", "hta", "lnk", "iso", "img", "html", "htm", "docm", "xlsm"})

_CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_REPORT_ID = re.compile(r"^R-[0-9]{4}$")
_UPN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_MESSAGE_ID = re.compile(r"^<[A-Za-z0-9._%+-]{1,100}@[A-Za-z0-9.-]{1,100}>$")
_QUARANTINE_ID = re.compile(r"^Q-[0-9]{4}$")
_SHOWN_HOST = re.compile(r"^(?:https?://)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)(?:[/:?#]|$)", re.IGNORECASE)
_URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


class PhishingError(ValueError):
    """The input is bad (client id, file, shape); nothing was analysed."""


@dataclass(frozen=True, slots=True)
class Link:
    href: str
    text: str


@dataclass(frozen=True, slots=True)
class Attachment:
    name: str
    content_type: str
    size: int


@dataclass(frozen=True, slots=True)
class ReportedMessage:
    """One reported message in the shared shape. It holds no attachment content: the mappers never read it."""

    report_id: str
    shape: str
    reporter: str
    message_id: str
    quarantine_id: str | None
    headers: tuple[tuple[str, str], ...]
    links: tuple[Link, ...]
    attachments: tuple[Attachment, ...]
    body: str

    def header(self, name: str) -> str | None:
        return next((v for n, v in self.headers if n.lower() == name.lower()), None)


@dataclass(frozen=True, slots=True)
class Finding:
    signal: str
    field: str  # the header field (or URL, Attachment name) the finding was read from
    evidence: str


@dataclass(frozen=True, slots=True)
class Triage:
    message: ReportedMessage
    findings: tuple[Finding, ...]
    score: int
    verdict: Verdict
    flagged_rules: tuple[str, ...]

    @property
    def flagged(self) -> bool:
        return bool(self.flagged_rules)


@dataclass(frozen=True, slots=True)
class ReportFile:
    client: str
    accepted_domains: tuple[str, ...]
    reports: tuple[ReportedMessage, ...]


# -- the two shapes, one path -------------------------------------------------------------------------------------


def _raw_headers(raw: str) -> list[tuple[str, str]]:
    """``Name: value`` lines, folded continuation lines joined with one space. Parsed as text, nothing else."""
    out: list[tuple[str, str]] = []
    for line in raw.replace("\r\n", "\n").split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] = (out[-1][0], f"{out[-1][1]} {line.strip()}")
        elif ":" in line:
            name, _, value = line.partition(":")
            out.append((name.strip(), value.strip()))
    return out


def _defender(p: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        p["reportedBy"],
        p["internetMessageId"],
        p.get("quarantineId"),
        [(h["name"], h["value"]) for h in p["headers"]],
        [(u["url"], u["displayText"]) for u in p["urls"]],
        [(a["fileName"], a["contentType"], a["size"]) for a in p["attachments"]],  # contentBytes is never read
        p["body"],
    )


def _inky(p: Mapping[str, Any]) -> tuple[Any, ...]:
    m = p["message"]
    return (
        p["reporter"]["email"],
        m["message_id"],
        m.get("quarantine_id"),
        _raw_headers(m["raw_headers"]),
        [(link["href"], link["text"]) for link in m["links"]],
        [(a["filename"], a["mime_type"], a["size_bytes"]) for a in m["attachments"]],  # content_base64 is never read
        m["body_html"],
    )


_MAPPERS: dict[str, Callable[[Mapping[str, Any]], tuple[Any, ...]]] = {"defender": _defender, "inky": _inky}


def _text(value: Any, what: str, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or (pattern is not None and not pattern.fullmatch(value)):
        raise PhishingError(f"{what} is missing or not valid")
    return value


def _size(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PhishingError("attachment size is missing or not valid")
    return value


def normalise(report_id: str, shape: str, payload: Mapping[str, Any]) -> ReportedMessage:
    """One report in either shape to ``ReportedMessage``; an unknown shape or a malformed payload raises."""
    _text(report_id, "report id", _REPORT_ID)
    mapper = _MAPPERS.get(shape)
    if mapper is None:
        raise PhishingError(f"report {report_id}: unknown shape {shape!r} (known: {', '.join(_MAPPERS)})")
    try:
        reporter, message_id, quarantine_id, headers, links, attachments, body = mapper(payload)
        return ReportedMessage(
            report_id=report_id,
            shape=shape,
            reporter=_text(reporter, "reporter", _UPN),
            message_id=_text(message_id, "message id", _MESSAGE_ID),
            quarantine_id=None if quarantine_id is None else _text(quarantine_id, "quarantine id", _QUARANTINE_ID),
            headers=tuple((_text(n, "header name"), _text(v, "header value")) for n, v in headers),
            links=tuple(Link(_text(h, "URL"), _text(t, "link text")) for h, t in links),
            attachments=tuple(
                Attachment(_text(n, "attachment name"), _text(c, "content type"), _size(s)) for n, c, s in attachments
            ),
            body=_text(body, "body"),
        )
    except PhishingError as exc:
        raise PhishingError(f"report {report_id} ({shape}): {exc}") from None
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise PhishingError(f"report {report_id}: not a {shape} report ({type(exc).__name__}: {exc})") from None


def load_reports(client: str, path: Path | None = None) -> ReportFile:
    """One client's reported messages. Another client's file, a malformed file or an unknown shape fails closed."""
    if not _CLIENT_ID.fullmatch(client):
        raise PhishingError(f"invalid client id {client!r}; nothing was read")
    path = Path(path) if path is not None else DEFAULT_REPORTS_DIR / f"{client}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw["_meta"]["client"] != client:
            raise PhishingError(f"the file does not belong to client {client}")
        domains = tuple(_text(d, "accepted domain").lower() for d in raw["_meta"]["accepted_domains"])
        items = raw["reports"]
        if not isinstance(items, list):
            raise PhishingError("reports is not a list")
        reports = tuple(normalise(item["id"], item["shape"], item["payload"]) for item in items)
    except PhishingError as exc:
        raise PhishingError(f"{path}: {exc}; nothing was analysed") from None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PhishingError(f"{path}: not a readable reports file ({type(exc).__name__}); nothing read") from None
    if len({(r.report_id, r.shape) for r in reports}) != len(reports):
        raise PhishingError(f"{path}: a report id appears twice in one shape; nothing was analysed")
    return ReportFile(client, domains, reports)


# -- analysis: headers, URLs and attachment names, as data --------------------------------------------------------


def _domain(value: str | None) -> str:
    """The domain of the address in a header (the one in angle brackets when there is one), lowercased."""
    if not value:
        return ""
    bracketed = re.search(r"<([^<>]*)>\s*$", value)
    address = (bracketed.group(1) if bracketed else value).strip()
    return address.rpartition("@")[2].lower() if "@" in address else ""


def _skeleton(domain: str) -> str:
    return domain.split(".")[0].translate(str.maketrans("0135", "oles")).replace("-", "")


def defang(text: str) -> str:
    """Every URL in ``text`` made unclickable: ``hxxp(s)://`` and each dot as ``[.]``."""
    return _URL_IN_TEXT.sub(lambda m: re.sub(r"^http", "hxxp", m.group(0), flags=re.I).replace(".", "[.]"), text)


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def analyse(msg: ReportedMessage, accepted_domains: tuple[str, ...]) -> tuple[Finding, ...]:
    """Findings from headers, URLs and attachment names only. Subject and body are never read here."""
    found: list[Finding] = []
    auth = msg.header("Authentication-Results")
    if auth is None:
        found.append(Finding("auth-missing", "Authentication-Results", "no Authentication-Results header"))
    for mech, bad in _AUTH_BAD.items():
        result = re.search(rf"\b{mech}=([a-z]+)", auth or "", re.IGNORECASE)
        if result and result.group(1).lower() in bad:
            found.append(Finding(f"{mech}-fail", "Authentication-Results", f"{mech}={result.group(1).lower()}"))
    sender = _domain(msg.header("From"))
    for name in ("Reply-To", "Return-Path"):
        other = _domain(msg.header(name))
        if other and sender and other != sender:
            evidence = f"{name} domain {other} differs from From domain {sender}"
            found.append(Finding(f"{name.lower()}-mismatch", name, evidence))
    own = next((d for d in accepted_domains if sender == d or sender.endswith("." + d)), None)
    look = next((d for d in accepted_domains if _skeleton(d) in _skeleton(sender)), None) if sender else None
    if own is None and look is not None:
        found.append(Finding("lookalike-domain", "From", f"From domain {sender} looks like the client's own {look}"))
    for link in msg.links:
        parts, shown = urlsplit(link.href), defang(link.href)
        host = (parts.hostname or "").lower()
        text_host = _SHOWN_HOST.match(link.text.strip())
        checks = (
            ("not-https", parts.scheme.lower() != "https", "not https"),
            ("userinfo-in-url", "@" in parts.netloc, "an @ in the address hides the real host"),
            ("ip-host", _is_ip(host), "host is an IP address"),
            ("punycode-host", any(label.startswith("xn--") for label in host.split(".")), "punycode host"),
            ("shortener", host in SHORTENERS, "link shortener hides the target"),
            (
                "link-text-mismatch",
                text_host is not None and text_host.group(1).lower() != host,
                "link text shows " + (text_host.group(1).replace(".", "[.]") if text_host else ""),
            ),
        )
        found += [Finding(signal, "URL", f"{shown}: {why}") for signal, hit, why in checks if hit]
    for att in msg.attachments:
        pieces = att.name.lower().split(".")
        if len(pieces) > 1 and pieces[-1] in RISKY_EXTENSIONS:
            found.append(Finding("risky-attachment", "Attachment name", f"{att.name}: .{pieces[-1]} can run code"))
            if len(pieces) > 2:
                found.append(Finding("double-extension", "Attachment name", f"{att.name}: hides its real type"))
    return tuple(found)


def untrusted_text(msg: ReportedMessage) -> str:
    """Everything a sender wrote freely: scanned for injection, never used for the verdict."""
    parts = [msg.header("Subject") or "", msg.header("From") or "", msg.body, *(link.text for link in msg.links)]
    return "\n".join(parts)


def triage(msg: ReportedMessage, accepted_domains: tuple[str, ...]) -> Triage:
    findings = analyse(msg, accepted_domains)
    score = sum(WEIGHTS[f.signal] for f in findings)
    verdict = VERDICTS[0] if score >= HIGH_AT else VERDICTS[1] if score >= SUSPICIOUS_AT else VERDICTS[2]
    return Triage(msg, findings, score, verdict, tuple(sorted(detect_injection(untrusted_text(msg)).rules)))


def suggested_levers(t: Triage) -> tuple[dict[str, Any], ...]:
    """Levers a person may press, filled from structured fields only. A flagged report gets none (B45-3)."""
    m = t.message
    if t.flagged:
        return ()
    out: list[dict[str, Any]] = []
    if t.verdict != "likely-clean":
        why = "find everyone else who received it, so the next person is protected"
        out.append({"lever": "message.trace", "params": {"message_id": m.message_id}, "why": why})
    if t.verdict == "likely-clean" and m.quarantine_id is not None:
        params = {"upn": m.reporter, "quarantine_id": m.quarantine_id}
        out.append({"lever": "quarantine.release", "params": params, "why": "release it to the person who asked"})
    return tuple(out)


def draft(t: Triage, client: str) -> str:
    """The answer for the person who reported it, as a draft a person sends. Deterministic; every URL defanged."""
    m = t.message
    lines = [
        DRAFT_HEADER,
        f"Phishing triage for report {m.report_id} ({m.shape} report) from {m.reporter}, client {client}.",
        f"Verdict: {t.verdict} (score {t.score}; high-confidence at {HIGH_AT} or more, suspicious at "
        f"{SUSPICIOUS_AT} or more).",
        f"Read as data only: header fields {', '.join(HEADER_FIELDS)}; {len(m.links)} URL(s); "
        f"{len(m.attachments)} attachment name(s). No URL was fetched and no attachment was opened.",
        "Findings (field: evidence):",
        *([f"- {f.field}: {f.evidence}" for f in t.findings] or ["- none"]),
        "Suggested levers (a person decides; nothing ran):",
    ]
    if t.flagged:
        lines += [
            "- none: the message text was flagged, so no lever is suggested until a person has read it.",
            f"Message text: withheld. The injection detector flagged it ({', '.join(t.flagged_rules)}); "
            "a person must read it.",
        ]
        return "\n".join(lines)
    levers = suggested_levers(t)
    for s in levers:
        params = " ".join(f"{k}={v}" for k, v in s["params"].items())
        lines.append(f"- {s['lever']} {params}: {s['why']}")
    if not levers:
        lines.append("- none")
    body = defang(f"Subject: {m.header('Subject') or ''}\n\n{m.body}")
    return "\n".join([*lines, "Message text (untrusted, shown as data):", wrap_untrusted("email", body)])
