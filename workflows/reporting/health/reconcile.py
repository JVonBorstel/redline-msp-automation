"""The validator: every number in a rendered report recomputed from the raw source files (B-71, C-21 pattern).

It reads only the finished HTML and the client's source files. It does not call the builder's figure code: the figures
here come from a second implementation (plain ``json``, ``Fraction`` arithmetic, no adapter), so a bug has to be
made twice to go unnoticed. It shares only wording and thresholds with the builder (`policy`) and file hashing
(`sources`).

What it checks, with the report's own HTML as the thing under test:

- every ``data-metric`` figure equals the recomputed figure, none is missing and none is invented;
- every section's status and fired rules follow from the recomputed figures;
- every source file the report names has the hash and date the file has now;
- the summary is the computed text, or a rephrase that keeps every figure and fact phrase (``policy.check_rephrase``).

``reconcile_html`` returns the mismatches (empty = the report reconciles). It never raises for a wrong number.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from fractions import Fraction
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from workflows.reporting.health import policy
from workflows.reporting.health.policy import Metric
from workflows.reporting.health.sources import (
    DEFAULT_SOURCES,
    Sources,
    digest,
    display_name,
    display_path,
    period_label,
)


@dataclass(frozen=True, slots=True)
class Mismatch:
    """One figure (or check) where the report and its sources disagree."""

    key: str
    expected: str
    shown: str


@dataclass(slots=True)
class _Seen:
    """What the HTML says, collected by ``_Reader``."""

    client: str = ""
    period: str = ""
    metrics: list[tuple[str, str]] = field(default_factory=list)
    status: dict[str, str] = field(default_factory=dict)
    reasons: dict[str, list[str]] = field(default_factory=dict)
    sources: list[tuple[str, list[str]]] = field(default_factory=list)
    summary_origin: str = ""
    summary_text: str = ""


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.seen = _Seen()
        self._section = ""
        self._metric: str | None = None
        self._buf: list[str] = []
        self._summary = False
        self._row: tuple[str, list[str]] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "main":
            self.seen.client, self.seen.period = a.get("data-client", ""), a.get("data-period", "")
        elif tag == "section":
            self._section = a.get("data-section", "")
            if "data-status" in a:
                self.seen.status[self._section] = a["data-status"]
        elif tag == "span" and "data-metric" in a:
            self._metric, self._buf = a["data-metric"], []
        elif tag == "li" and "data-reason" in a:
            self.seen.reasons.setdefault(self._section, []).append(a["data-reason"])
        elif tag == "p" and "data-summary" in a:
            self._summary, self._buf = True, []
            self.seen.summary_origin = a["data-summary"]
        elif tag == "tr" and "data-source" in a:
            self._row = (a["data-source"], [])
        elif tag == "td" and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._metric is not None:
            self.seen.metrics.append((self._metric, "".join(self._buf)))
            self._metric = None
        elif tag == "p" and self._summary:
            self.seen.summary_text = "".join(self._buf)
            self._summary = False
        elif tag == "td" and self._row is not None and self._cell is not None:
            self._row[1].append("".join(self._cell))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.seen.sources.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._metric is not None or self._summary:
            self._buf.append(data)
        if self._cell is not None:
            self._cell.append(data)


# -- the figures, recomputed ----------------------------------------------------------------------------------------
def _json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _month(stamp: str) -> str:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(UTC).strftime("%Y-%m")


def _tenths(num: int, den: int) -> float | None:
    """num/den as a percentage with one decimal, half up, from integer arithmetic."""
    if den == 0:
        return None
    return ((Fraction(num * 1000, den) + Fraction(1, 2)) // 1) / 10


def _hours_text(seconds: list[int]) -> float | None:
    if not seconds:
        return None
    ordered = sorted(seconds)
    n = len(ordered)
    mid = Fraction(ordered[n // 2]) if n % 2 else Fraction(ordered[n // 2 - 1] + ordered[n // 2], 2)
    return ((mid / 3600 * 10 + Fraction(1, 2)) // 1) / 10


@dataclass(slots=True)
class _Expected:
    path: Path
    as_of: str
    metrics: dict[str, Metric]  # empty when the source is outside the period


def _tickets(path: Path, period: str) -> _Expected:
    raw = _json(path)
    out = _Expected(path, str(raw["as_of"]), {})
    if _month(out.as_of) != period:
        return out
    mine = [t for t in raw["tickets"] if _month(t["created"]) == period]
    done = [t for t in mine if t["status"] == "resolved"]
    secs = [
        int(
            (
                datetime.fromisoformat(t["updated"].replace("Z", "+00:00"))
                - datetime.fromisoformat(t["created"].replace("Z", "+00:00"))
            ).total_seconds()
        )
        for t in done
    ]
    out.metrics = {
        "tickets.opened": len(mine),
        "tickets.resolved": len(done),
        "tickets.open": len(mine) - len(done),
        "tickets.resolved_pct": _tenths(len(done), len(mine)),
        "tickets.median_hours_to_resolve": _hours_text(secs),
    }
    for channel, n in sorted(Counter(t["source"] for t in mine).items()):
        out.metrics[policy.CHANNEL_PREFIX + channel] = n
    return out


def _baseline(path: Path, period: str) -> _Expected:
    raw = _json(path)
    out = _Expected(path, str(raw["as_of"]), {})
    if _month(out.as_of) != period:
        return out
    sev = Counter(f["Severity"] for f in raw["findings"])
    drift = raw["drift"]
    out.metrics = {
        "baseline.findings": len(raw["findings"]),
        "baseline.high": sev["High"],
        "baseline.medium": sev["Medium"],
        "baseline.low": sev["Low"],
        "baseline.new": len(drift["new"]),
        "baseline.resolved": len(drift["resolved"]),
        "baseline.unchanged": len(drift["unchanged"]),
        "baseline.ca_changes": sum(
            len(drift["ca"][k]) for k in ("added", "removed", "state_changed", "assignments_changed")
        ),
    }
    return out


def _patching(path: Path, period: str) -> _Expected:
    raw = _json(path)
    out = _Expected(path, str(raw["as_of"]), {})
    if _month(out.as_of) != period:
        return out
    devices = raw["devices"]
    day = datetime.fromisoformat(out.as_of.replace("Z", "+00:00")).date()
    clean = [d for d in devices if d["pending_critical"] == 0 and d["pending_other"] == 0]
    out.metrics = {
        "patching.devices": len(devices),
        "patching.up_to_date": len(clean),
        "patching.up_to_date_pct": _tenths(len(clean), len(devices)),
        "patching.critical_pending_devices": len([d for d in devices if d["pending_critical"] > 0]),
        "patching.critical_pending_updates": sum(d["pending_critical"] for d in devices),
        "patching.not_patched_30d": len(
            [d for d in devices if (day - date.fromisoformat(d["last_patched"])).days > policy.PATCH_STALE_DAYS]
        ),
    }
    return out


def _backup(path: Path, period: str) -> _Expected:
    raw = _json(path)
    out = _Expected(path, str(raw["asOf"]), {})
    if _month(out.as_of) != period:
        return out
    org = raw["organization"]["id"]
    jobs = [j for j in raw["jobs"] if j["organizationId"] == org and _month(j["scheduledStart"]) == period]
    count = Counter(j["status"] for j in jobs)
    out.metrics = {
        "backup.jobs": len(jobs),
        "backup.success": count["success"],
        "backup.failed": count["failed"],
        "backup.missed": count["missed"],
        "backup.other": len(jobs) - count["success"] - count["failed"] - count["missed"],
        "backup.boot_check_failed": len([j for j in jobs if (j.get("bootCheck") or {}).get("status") == "failed"]),
        "backup.success_pct": _tenths(count["success"], len(jobs)),
    }
    return out


def _awareness(path: Path, period: str) -> _Expected:
    raw = _json(path)
    out = _Expected(path, str(raw["as_of"]), {})
    if _month(out.as_of) != period:
        return out
    camps = [c for c in raw["services"]["phishing_simulation"]["campaigns"] if c["launched"][:7] == period]
    sent, clicked, reported = (sum(c[k] for c in camps) for k in ("sent", "clicked", "reported"))
    vault = raw["services"]["password_vault"]
    out.metrics = {
        "phish.campaigns": len(camps),
        "phish.sent": sent,
        "phish.clicked": clicked,
        "phish.reported": reported,
        "phish.click_pct": _tenths(clicked, sent),
        "phish.report_pct": _tenths(reported, sent),
        "vault.audit_score": vault["audit_score"],
        "vault.users_total": vault["users_total"],
        "vault.users_enrolled": vault["users_enrolled"],
        "vault.enrolled_pct": _tenths(vault["users_enrolled"], vault["users_total"]),
        "vault.mfa_enforced": "yes" if vault["mfa_enforced"] is True else "no",
    }
    return out


_RECOMPUTE = {
    "tickets": _tickets,
    "baseline": _baseline,
    "patching": _patching,
    "backup": _backup,
    "awareness": _awareness,
}


def _text(value: Metric) -> str:
    return policy.show(value)


def reconcile_html(page: str, sources: Sources = DEFAULT_SOURCES) -> tuple[Mismatch, ...]:
    """Mismatches between a rendered report and its source files; empty when every number reconciles."""
    reader = _Reader()
    reader.feed(page)
    reader.close()
    seen = reader.seen
    client, period = seen.client, seen.period
    try:
        label = period_label(period)
        expected = {
            key: _RECOMPUTE[key](path, period)
            for key in policy.SECTION_KEYS
            if (path := sources.path_for(key, client)).is_file()
        }
    except (ValueError, KeyError, TypeError, AssertionError, OSError) as exc:
        return (Mismatch("header", "a readable client, period and source files", f"{type(exc).__name__}: {exc}"),)
    found: list[Mismatch] = []

    # 1. figures
    want: dict[str, Metric] = {}
    section_of: dict[str, str] = {}
    for key, exp in expected.items():
        for name, value in exp.metrics.items():
            want[name] = value
            section_of[name] = key
    shown: dict[str, list[str]] = {}
    for name, text in seen.metrics:
        shown.setdefault(name, []).append(text)
    for name, value in want.items():
        got = shown.get(name)
        if not got:
            found.append(Mismatch(name, _text(value), "(not shown)"))
            continue
        found.extend(Mismatch(name, _text(value), text) for text in dict.fromkeys(got) if text != _text(value))
    found.extend(Mismatch(name, "", texts[0]) for name, texts in shown.items() if name not in want)

    # 2. status and fired rules
    for key in policy.SECTION_KEYS:
        metrics = expected[key].metrics if key in expected else {}
        want_status = policy.status_of(key, metrics) if metrics else "no-data"
        if seen.status.get(key) != want_status:
            found.append(Mismatch(f"status.{key}", want_status, str(seen.status.get(key))))
        want_rules = list(policy.firing(key, metrics)) if metrics else []
        if seen.reasons.get(key, []) != want_rules:
            found.append(Mismatch(f"reasons.{key}", ",".join(want_rules), ",".join(seen.reasons.get(key, []))))

    # 3. sources: file, hash and date as they are now
    rows = {section: cells for section, cells in seen.sources}
    for key, exp in expected.items():
        want_row = [display_path(exp.path), digest(exp.path), exp.as_of]
        cells = rows.get(key)
        if cells is None or cells[:3] != want_row:
            found.append(
                Mismatch(f"source.{key}", " | ".join(want_row), " | ".join(cells[:3]) if cells else "(not listed)")
            )
    found.extend(Mismatch(f"source.{key}", "", "(listed but no such file)") for key in rows if key not in expected)

    # 4. summary
    live = {key: exp.metrics for key, exp in expected.items() if exp.metrics}
    facts = policy.facts_for(live)
    computed = policy.computed_summary(
        display_name(client),
        label,
        facts,
        tuple(k for k in policy.SECTION_KEYS if k in live and policy.status_of(k, live[k]) == "attention"),
        tuple(k for k in policy.SECTION_KEYS if k in live and policy.status_of(k, live[k]) == "healthy"),
        tuple(k for k in policy.SECTION_KEYS if k not in live),
    )
    if seen.summary_origin == "computed":
        if seen.summary_text != computed:
            found.append(Mismatch("summary", computed, seen.summary_text))
    elif seen.summary_origin == "rephrased":
        problem = policy.check_rephrase(seen.summary_text, computed, facts, label)
        if problem:
            found.append(Mismatch("summary", f"a text that keeps the computed figures ({problem})", seen.summary_text))
    else:
        found.append(Mismatch("summary", "computed or rephrased", seen.summary_origin or "(missing)"))
    return tuple(found)
