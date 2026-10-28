"""The validator: every number and every listed ticket in a rendered digest recomputed from the raw files (B-72, C-21).

It reads only the finished HTML and the client's source files. It does not call the builder or the backup adapter: the
figures here come from a second implementation (plain ``json`` and ``Fraction`` arithmetic, rows filtered by the
backup fixture's own organization id), so a bug has to be made twice to go unnoticed. It shares only the week
arithmetic and the figure text with the builder (``window``) and file hashing (``workflows.reporting.health.sources``).

What it checks, with the page itself as the thing under test:

- every ``data-metric`` figure equals the recomputed figure, none is missing and none is invented;
- the closed tickets listed (id, channel, opened, closed, in order) are exactly the tickets the source closed that week;
- each section's "data" or "no-data" status and its "partial" flag follow from the source dates;
- every source file the page names has the hash and date the file has now, and no other file is listed.

``reconcile_html`` returns the mismatches (empty = the digest reconciles). It never raises for a wrong number.
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

from workflows.reporting.digest.window import Metric, show, week_bounds
from workflows.reporting.health import DEFAULT_SOURCES, Mismatch, Sources
from workflows.reporting.health.sources import digest, display_path


@dataclass(slots=True)
class _Seen:
    client: str = ""
    week: str = ""
    metrics: list[tuple[str, str]] = field(default_factory=list)
    sections: dict[str, tuple[str, str]] = field(default_factory=dict)  # name -> (status, partial flag)
    tickets: list[tuple[str, str, str, str]] = field(default_factory=list)
    sources: list[tuple[str, list[str]]] = field(default_factory=list)


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.seen = _Seen()
        self._metric: str | None = None
        self._buf: list[str] = []
        self._row: tuple[str, list[str]] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "main":
            self.seen.client, self.seen.week = a.get("data-client", ""), a.get("data-week", "")
        elif tag == "section" and "data-status" in a:
            self.seen.sections[a.get("data-section", "")] = (a["data-status"], a.get("data-partial", ""))
        elif tag == "span" and "data-metric" in a:
            self._metric, self._buf = a["data-metric"], []
        elif tag == "tr" and "data-ticket" in a:
            self.seen.tickets.append(
                (a["data-ticket"], a.get("data-channel", ""), a.get("data-opened", ""), a.get("data-closed", ""))
            )
        elif tag == "tr" and "data-source" in a:
            self._row = (a["data-source"], [])
        elif tag == "td" and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._metric is not None:
            self.seen.metrics.append((self._metric, "".join(self._buf)))
            self._metric = None
        elif tag == "td" and self._row is not None and self._cell is not None:
            self._row[1].append("".join(self._cell))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.seen.sources.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._metric is not None:
            self._buf.append(data)
        if self._cell is not None:
            self._cell.append(data)


# -- the figures, recomputed ----------------------------------------------------------------------------------------
def _json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _utc(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(UTC)


def _tenths(value: Fraction) -> float:
    return int((value * 10 + Fraction(1, 2)) // 1) / 10


@dataclass(slots=True)
class _Expected:
    status: dict[str, str] = field(default_factory=dict)
    partial: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, Metric] = field(default_factory=dict)
    tickets: list[tuple[str, str, str, str]] = field(default_factory=list)
    sources: dict[str, tuple[Path, str]] = field(default_factory=dict)


def _expected(client: str, monday: date, sunday: date, sources: Sources) -> _Expected:
    out = _Expected()
    out.status = {"tickets": "no-data", "changes": "no-data", "backup": "no-data"}

    path = sources.path_for("tickets", client)
    if path.is_file():
        raw = _json(path)
        if _utc(str(raw["as_of"])).date() >= monday:
            out.status["tickets"] = "data"
            out.partial["tickets"] = "yes" if _utc(str(raw["as_of"])).date() < sunday else "no"
            out.sources["tickets"] = (path, str(raw["as_of"]))
            closed = [
                t for t in raw["tickets"] if t["status"] == "resolved" and monday <= _utc(t["updated"]).date() <= sunday
            ]
            closed.sort(key=lambda t: (_utc(t["updated"]), t["id"]))
            seconds = sorted(int((_utc(t["updated"]) - _utc(t["created"])).total_seconds()) for t in closed)
            m = out.metrics
            m["closed.count"] = len(closed)
            for channel, n in sorted(Counter(t["source"] for t in closed).items()):
                m[f"closed.channel.{channel}"] = n
            if seconds:
                n = len(seconds)
                mid = Fraction(seconds[n // 2]) if n % 2 else Fraction(seconds[n // 2 - 1] + seconds[n // 2], 2)
                m["closed.median_hours"] = _tenths(mid / 3600)
            else:
                m["closed.median_hours"] = None
            for t in closed:
                m[f"row.{t['id']}.hours"] = _tenths(
                    Fraction(int((_utc(t["updated"]) - _utc(t["created"])).total_seconds()), 3600)
                )
                out.tickets.append(
                    (t["id"], t["source"], _utc(t["created"]).date().isoformat(), _utc(t["updated"]).date().isoformat())
                )

    path = sources.path_for("baseline", client)
    if path.is_file():
        raw = _json(path)
        if monday <= _utc(str(raw["as_of"])).date() <= sunday:
            out.status["changes"] = "data"
            out.sources["baseline"] = (path, str(raw["as_of"]))
            drift = raw["drift"]
            out.metrics["chg.new"] = len(drift["new"])
            out.metrics["chg.resolved"] = len(drift["resolved"])
            out.metrics["chg.ca_changes"] = sum(
                len(drift["ca"][k]) for k in ("added", "removed", "state_changed", "assignments_changed")
            )

    path = sources.path_for("backup", client)
    if path.is_file():
        raw = _json(path)
        if _utc(str(raw["asOf"])).date() >= monday:
            out.status["backup"] = "data"
            out.partial["backup"] = "yes" if _utc(str(raw["asOf"])).date() < sunday else "no"
            out.sources["backup"] = (path, str(raw["asOf"]))
            org = raw["organization"]["id"]
            jobs = [
                j
                for j in raw["jobs"]
                if j["organizationId"] == org and monday <= _utc(j["scheduledStart"]).date() <= sunday
            ]
            count = Counter(j["status"] for j in jobs)
            m = out.metrics
            m["backup.jobs"] = len(jobs)
            m["backup.success"] = count["success"]
            m["backup.failed"] = count["failed"]
            m["backup.missed"] = count["missed"]
            m["backup.other"] = len(jobs) - count["success"] - count["failed"] - count["missed"]
    return out


def reconcile_html(page: str, sources: Sources = DEFAULT_SOURCES) -> tuple[Mismatch, ...]:
    """Mismatches between a rendered digest and its source files; empty when every number and ticket reconciles."""
    reader = _Reader()
    reader.feed(page)
    reader.close()
    seen = reader.seen
    try:
        monday, sunday = week_bounds(seen.week)
        want = _expected(seen.client, monday, sunday, sources)
    except (ValueError, KeyError, TypeError, AssertionError, OSError) as exc:
        return (Mismatch("header", "a readable client, week and source files", f"{type(exc).__name__}: {exc}"),)
    found: list[Mismatch] = []

    # 1. figures
    shown: dict[str, list[str]] = {}
    for name, text in seen.metrics:
        shown.setdefault(name, []).append(text)
    for name, value in want.metrics.items():
        got = shown.get(name)
        if not got:
            found.append(Mismatch(name, show(value), "(not shown)"))
            continue
        found.extend(Mismatch(name, show(value), g) for g in dict.fromkeys(got) if g != show(value))
    found.extend(Mismatch(name, "", texts[0]) for name, texts in shown.items() if name not in want.metrics)

    # 2. the closed tickets, in order
    if seen.tickets != want.tickets:
        got_ids = ",".join(t[0] for t in seen.tickets)
        found.append(Mismatch("tickets", ",".join(t[0] for t in want.tickets), got_ids))
        found.extend(
            Mismatch(f"ticket.{w[0]}", " ".join(w), " ".join(s))
            for w, s in zip(want.tickets, seen.tickets, strict=False)
            if w != s and w[0] == s[0]
        )

    # 3. section status and partial flag
    for name, status in want.status.items():
        got_status, got_partial = seen.sections.get(name, ("(missing)", ""))
        if got_status != status:
            found.append(Mismatch(f"status.{name}", status, got_status))
        elif name in want.partial and got_partial != want.partial[name]:
            found.append(Mismatch(f"partial.{name}", want.partial[name], got_partial))

    # 4. sources: file, hash and date as they are now; no other file
    rows = {section: cells for section, cells in seen.sources}
    for section, (path, as_of) in want.sources.items():
        want_row = [display_path(path), digest(path), as_of]
        cells = rows.get(section)
        if cells is None or cells[:3] != want_row:
            found.append(
                Mismatch(f"source.{section}", " | ".join(want_row), " | ".join(cells[:3]) if cells else "(not listed)")
            )
    found.extend(Mismatch(f"source.{s}", "", "(not a source of this digest)") for s in rows if s not in want.sources)
    return tuple(found)
