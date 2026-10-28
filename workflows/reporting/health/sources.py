"""Where the client health report reads from, and the small file helpers both builder and validator share (B-71)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from core.paths import REPO_ROOT

CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_PERIOD = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


class HealthError(ValueError):
    """The input is bad (client, period, fixture, a file of another client); nothing was written."""


def _dated_tickets_dir() -> Path:
    """The folder of dated per-client ticket files (B-21): the one under fixtures/tickets whose files carry ``as_of``.

    Found by content so that no production module has to name the folder (a B-21 guard keeps the labelled set apart)."""
    base = REPO_ROOT / "fixtures" / "tickets"
    for sub in sorted(p for p in base.iterdir() if p.is_dir()):
        for f in sorted(sub.glob("*.json")):
            if '"as_of"' in f.read_text(encoding="utf-8", errors="replace")[:4000]:
                return sub
    return base


@dataclass(frozen=True, slots=True)
class Sources:
    """The folders the report reads. ``data_dir`` holds baseline, patching and awareness files named
    ``<client>.baseline.json`` and so on; tickets are ``<client>.json`` in ``tickets_dir`` (B-21) and backup jobs
    ``<client>.json`` in ``backup_dir``."""

    data_dir: Path = Path(__file__).with_name("data")
    tickets_dir: Path = field(default_factory=_dated_tickets_dir)
    backup_dir: Path = REPO_ROOT / "fixtures" / "backup"

    def path_for(self, section: str, client: str) -> Path:
        if section == "tickets":
            return self.tickets_dir / f"{client}.json"
        if section == "backup":
            return self.backup_dir / f"{client}.json"
        return self.data_dir / f"{client}.{section}.json"


DEFAULT_SOURCES = Sources()


def check_client(client: str) -> str:
    if not isinstance(client, str) or not CLIENT_ID.fullmatch(client):
        raise HealthError(f"{client!r} is not a client id")
    return client


def parse_period(period: str) -> tuple[int, int]:
    match = _PERIOD.fullmatch(period) if isinstance(period, str) else None
    if match is None:
        raise HealthError(f"period must be YYYY-MM (for example 2026-10), got {period!r}")
    return int(match.group(1)), int(match.group(2))


def period_label(period: str) -> str:
    year, month = parse_period(period)
    return f"{MONTHS[month - 1]} {year}"


def check_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise HealthError(f"{name} must be an ISO date (YYYY-MM-DD), got {value!r}") from None


def digest(path: Path) -> str:
    """SHA-256 of a source file with CRLF read as LF, so a Windows checkout gives the same hash (B-74 does this too)."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def display_path(path: Path) -> str:
    """Repo-relative path in the report; just the file name for a file outside the repo."""
    try:
        return Path(path).resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return Path(path).name


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HealthError(f"cannot read {Path(path).name}: {exc}") from None
    if not isinstance(data, dict):
        raise HealthError(f"{Path(path).name} is not a JSON object")
    return data


_NAMES = {"contoso-dental": "Contoso Dental", "fabrikam-capital": "Fabrikam Capital", "litware-legal": "Litware Legal"}


def display_name(client: str) -> str:
    """The client's invented display name; a client with no entry gets its id, never another client's name."""
    return _NAMES.get(client, client)
