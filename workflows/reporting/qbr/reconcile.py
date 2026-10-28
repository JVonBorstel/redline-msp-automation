"""The validator: every number in a rendered QBR recomputed from the raw source files (B-72, C-21 pattern).

It reads only the finished HTML and the client's source files. It does not call the builder, B-71's ``build_report`` or
B-71's validator: the monthly figures here come from a second implementation (plain ``json`` and ``Fraction``
arithmetic), and the quarter totals, changes, wins, risks and suggestions are worked out again from them. It shares only
wording, rules and thresholds with the builder (``policy``) and file hashing (``workflows.reporting.health.sources``).

What it checks, with the page itself as the thing under test:

- every ``data-metric`` figure equals the recomputed figure, none is missing and none is invented;
- the months shown as "no data" are the months with no source dated in them;
- the wins, risks and suggestions are the ones the rules give for the recomputed figures, in order, with the sentence
  each one should have;
- every source file the page names has the hash and date the file has now, and no other file is listed.

``reconcile_html`` returns the mismatches (empty = the page reconciles). It never raises for a wrong number.
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

from workflows.reporting.health import Mismatch
from workflows.reporting.health.sources import digest, display_path
from workflows.reporting.qbr import policy
from workflows.reporting.qbr.policy import Metric
from workflows.reporting.qbr.sources import DEFAULT_QBR_SOURCES, QbrSources


@dataclass(slots=True)
class _Seen:
    client: str = ""
    quarter: str = ""
    generated_on: str = ""
    metrics: list[tuple[str, str]] = field(default_factory=list)
    nodata: list[str] = field(default_factory=list)
    lists: dict[str, list[tuple[str, str, list[str]]]] = field(default_factory=dict)  # name -> (id, text, span keys)
    sources: list[tuple[str, list[str]]] = field(default_factory=list)


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.seen = _Seen()
        self._metric: str | None = None
        self._buf: list[str] = []
        self._list = ""
        self._item: tuple[str, list[str], list[str]] | None = None  # id, text parts, span keys
        self._row: tuple[str, list[str]] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "main":
            self.seen.client, self.seen.quarter = a.get("data-client", ""), a.get("data-quarter", "")
            self.seen.generated_on = a.get("data-generated-on", "")
        elif tag == "span" and "data-metric" in a:
            self._metric, self._buf = a["data-metric"], []
            if self._item is not None:
                self._item[2].append(a["data-metric"])
        elif tag == "ul" and "data-list" in a:
            self._list = a["data-list"]
            self.seen.lists.setdefault(self._list, [])
        elif tag == "li" and "data-item" in a:
            self._item = (a["data-item"], [], [])
        elif tag == "td" and "data-nodata" in a:
            self.seen.nodata.append(a.get("data-key", ""))
        elif tag == "tr" and "data-source" in a:
            self._row = (a["data-source"], [])
        elif tag == "td" and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._metric is not None:
            self.seen.metrics.append((self._metric, "".join(self._buf)))
            self._metric = None
        elif tag == "li" and self._item is not None:
            item_id, parts, keys = self._item
            self.seen.lists.setdefault(self._list, []).append((item_id, " ".join("".join(parts).split()), keys))
            self._item = None
        elif tag == "td" and self._row is not None and self._cell is not None:
            self._row[1].append("".join(self._cell))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.seen.sources.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._metric is not None:
            self._buf.append(data)
        if self._item is not None:
            self._item[1].append(data)
        if self._cell is not None:
            self._cell.append(data)


# -- the monthly figures, recomputed from the raw files ---------------------------------------------------------------
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
    return int((Fraction(num * 1000, den) + Fraction(1, 2)) // 1) / 10


@dataclass(slots=True)
class _Source:
    section: str
    path: Path
    as_of: str


MonthFigures = dict[str, dict[str, Metric]]  # section -> figure -> value (only sections with data)


def _month_figures(client: str, month: str, qs: QbrSources) -> tuple[MonthFigures, list[_Source]]:
    src = qs.for_month(month)
    figures: MonthFigures = {}
    used: list[_Source] = []

    path = src.path_for("tickets", client)
    if path.is_file() and _month(str(_json(path)["as_of"])) == month:
        raw = _json(path)
        mine = [t for t in raw["tickets"] if _month(t["created"]) == month]
        done = [t for t in mine if t["status"] == "resolved"]
        figures["tickets"] = {
            "tickets.opened": len(mine),
            "tickets.resolved": len(done),
            "tickets.resolved_pct": _tenths(len(done), len(mine)),
        }
        used.append(_Source("tickets", path, str(raw["as_of"])))

    path = src.path_for("baseline", client)
    if path.is_file() and _month(str(_json(path)["as_of"])) == month:
        raw = _json(path)
        figures["baseline"] = {
            "baseline.findings": len(raw["findings"]),
            "baseline.high": len([f for f in raw["findings"] if f["Severity"] == "High"]),
        }
        used.append(_Source("baseline", path, str(raw["as_of"])))

    path = src.path_for("patching", client)
    if path.is_file() and _month(str(_json(path)["as_of"])) == month:
        raw = _json(path)
        day = datetime.fromisoformat(str(raw["as_of"]).replace("Z", "+00:00")).date()
        devices = raw["devices"]
        figures["patching"] = {
            "patching.devices": len(devices),
            "patching.critical_pending_devices": len([d for d in devices if d["pending_critical"] > 0]),
            "patching.not_patched_30d": len(
                [d for d in devices if (day - date.fromisoformat(d["last_patched"])).days > policy.PATCH_STALE_DAYS]
            ),
        }
        used.append(_Source("patching", path, str(raw["as_of"])))

    path = src.path_for("backup", client)
    if path.is_file() and _month(str(_json(path)["asOf"])) == month:
        raw = _json(path)
        org = raw["organization"]["id"]
        jobs = [j for j in raw["jobs"] if j["organizationId"] == org and _month(j["scheduledStart"]) == month]
        count = Counter(j["status"] for j in jobs)
        figures["backup"] = {
            "backup.jobs": len(jobs),
            "backup.success": count["success"],
            "backup.failed": count["failed"],
            "backup.missed": count["missed"],
            "backup.success_pct": _tenths(count["success"], len(jobs)),
        }
        used.append(_Source("backup", path, str(raw["asOf"])))

    path = src.path_for("awareness", client)
    if path.is_file() and _month(str(_json(path)["as_of"])) == month:
        raw = _json(path)
        camps = [c for c in raw["services"]["phishing_simulation"]["campaigns"] if c["launched"][:7] == month]
        sent, clicked = sum(c["sent"] for c in camps), sum(c["clicked"] for c in camps)
        figures["awareness"] = {
            "phish.sent": sent,
            "phish.clicked": clicked,
            "phish.click_pct": _tenths(clicked, sent),
            "vault.audit_score": raw["services"]["password_vault"]["audit_score"],
        }
        used.append(_Source("awareness", path, str(raw["as_of"])))
    return figures, used


def _quarter(
    per_month: dict[str, MonthFigures],
) -> tuple[dict[str, Metric], dict[str, int]]:
    cov = {s: len([m for m in per_month if s in per_month[m]]) for s in policy.SECTIONS}
    values: dict[str, Metric] = {}
    for spec in policy.SPECS:
        have = [per_month[m][spec.section][spec.key] for m in sorted(per_month) if spec.section in per_month[m]]
        if spec.kind == "flow":
            values[spec.key] = sum(int(v) for v in have if v is not None) if have else None
        elif spec.kind == "point":
            values[spec.key] = have[-1] if have else None
    for spec in policy.SPECS:
        if spec.kind == "derived":
            num, den = values[spec.numerator], values[spec.denominator]
            values[spec.key] = _tenths(int(num), int(den)) if num is not None and den is not None else None
    return values, cov


def _words(value: Metric, key: str) -> str:
    return policy.signed(value) if key.startswith("d.") else policy.show(value)


def reconcile_html(page: str, sources: QbrSources = DEFAULT_QBR_SOURCES) -> tuple[Mismatch, ...]:
    """Mismatches between a rendered QBR and its source files; empty when every number reconciles."""
    reader = _Reader()
    reader.feed(page)
    reader.close()
    seen = reader.seen
    try:
        client, quarter = seen.client, seen.quarter
        previous = policy.previous_quarter(quarter)
        last = seen.generated_on[:7]
        per: dict[str, dict[str, MonthFigures]] = {quarter: {}, previous: {}}
        used: dict[str, list[_Source]] = {}
        for q in (quarter, previous):
            for month in policy.months_of(q):
                if month > last:
                    continue
                figures, files = _month_figures(client, month, sources)
                if figures:
                    per[q][month] = figures
                    used[month] = files
        cur, cur_cov = _quarter(per[quarter])
        prev, prev_cov = _quarter(per[previous])
    except (ValueError, KeyError, TypeError, AssertionError, OSError, IndexError) as exc:
        return (Mismatch("header", "a readable client, quarter and source files", f"{type(exc).__name__}: {exc}"),)

    want: dict[str, Metric] = {}
    delta: dict[str, Metric] = {}
    for spec in policy.SPECS:
        want[policy.q_key(quarter, spec.key)] = cur[spec.key]
        want[policy.q_key(previous, spec.key)] = prev[spec.key]
        same = policy.comparable(spec, cur_cov[spec.section], prev_cov[spec.section])
        delta[spec.key] = policy.difference(cur[spec.key], prev[spec.key]) if same else None
        want[policy.d_key(spec.key)] = delta[spec.key]
    for section in policy.SECTIONS:
        want[policy.cov_key(quarter, section)] = cur_cov[section]
        want[policy.cov_key(previous, section)] = prev_cov[section]
    missing_months: list[str] = []
    for month in policy.months_of(quarter):
        for spec in policy.SPECS:
            key = policy.m_key(month, spec.key)
            if month in per[quarter] and spec.section in per[quarter][month]:
                want[key] = per[quarter][month][spec.section][spec.key]
            else:
                missing_months.append(key)

    found: list[Mismatch] = []
    # 1. figures
    shown: dict[str, list[str]] = {}
    for name, text in seen.metrics:
        shown.setdefault(name, []).append(text)
    for name, value in want.items():
        text = _words(value, name)
        got = shown.get(name)
        if not got:
            found.append(Mismatch(name, text, "(not shown)"))
            continue
        found.extend(Mismatch(name, text, g) for g in dict.fromkeys(got) if g != text)
    found.extend(Mismatch(name, "", texts[0]) for name, texts in shown.items() if name not in want)

    # 2. months shown as "no data"
    if sorted(seen.nodata) != sorted(missing_months):
        found.append(Mismatch("no-data months", ",".join(sorted(missing_months)), ",".join(sorted(seen.nodata))))

    # 3. wins, risks, suggestions: the ids the rules give, in order, with their sentences
    wins, risks, recs = policy.evaluate(policy.Context(cur, delta, cur_cov))
    for name, ids in (("wins", wins), ("risks", risks), ("recommendations", recs)):
        got_items = seen.lists.get(name, [])
        if [i for i, _, _ in got_items] != list(ids):
            found.append(Mismatch(name, ",".join(ids), ",".join(i for i, _, _ in got_items)))
            continue
        for item_id, text, keys in got_items:
            values = {k: v for k, v in want.items()}
            wanted_keys: list[str] = []

            def collect(key: str | None, value: Metric | str, _keys: list[str] = wanted_keys) -> str:
                if key is None:
                    return str(value)
                _keys.append(key)
                return policy.plain(key, value)

            expected = " ".join(policy.fill_item(item_id, quarter, values, collect).split())
            if text != expected or keys != wanted_keys:
                found.append(Mismatch(f"{name}.{item_id}", expected, text))

    # 4. sources: file, hash and date as they are now; no other file
    rows = {key: cells for key, cells in seen.sources}
    listed: set[str] = set()
    for q in (quarter, previous):
        for month in per[q]:
            for entry in used[month]:
                key = f"{month}:{entry.section}"
                listed.add(key)
                want_row = [display_path(entry.path), digest(entry.path), entry.as_of]
                cells = rows.get(key)
                if cells is None or cells[:3] != want_row:
                    found.append(
                        Mismatch(
                            f"source.{key}", " | ".join(want_row), " | ".join(cells[:3]) if cells else "(not listed)"
                        )
                    )
    found.extend(Mismatch(f"source.{key}", "", "(not a source of this review)") for key in rows if key not in listed)
    return tuple(found)
