"""Weeks, figure text and the plain-field checks the digest and its validator share (B-72). No data access."""

from __future__ import annotations

import re
from datetime import date

from workflows.reporting.health.sources import HealthError

Metric = int | float | None
_WEEK = re.compile(r"^(\d{4})-W(0[1-9]|[1-4]\d|5[0-3])$")
TICKET_ID = re.compile(r"^T-\d{1,8}$")
CHANNEL = re.compile(r"^[a-z][a-z-]{0,23}$")


class DigestError(HealthError):
    """The input is bad (client, week, dates, a ticket id that is not plain) or the draft did not reconcile."""


def week_bounds(week: str) -> tuple[date, date]:
    """Monday and Sunday of an ISO week such as ``2026-W42``."""
    match = _WEEK.fullmatch(week) if isinstance(week, str) else None
    if match is None:
        raise DigestError(f"week must look like 2026-W42 (ISO week), got {week!r}")
    try:
        year, number = int(match.group(1)), int(match.group(2))
        return date.fromisocalendar(year, number, 1), date.fromisocalendar(year, number, 7)
    except ValueError:
        raise DigestError(f"week {week!r} does not exist (ISO week)") from None


def show(value: Metric) -> str:
    """The text a figure has in the page, the one form the builder writes and the validator compares."""
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)
