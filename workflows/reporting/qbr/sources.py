"""Where each month of a QBR reads its health sources from (B-72)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from workflows.reporting.health import DEFAULT_SOURCES, Sources

DEFAULT_HISTORY = Path(__file__).with_name("data")


@dataclass(frozen=True, slots=True)
class QbrSources:
    """Where each month's health sources are read from.

    A month with a folder ``<history_dir>/<YYYY-MM>/{data,tickets,backup}`` reads its files there; every other month
    reads ``default`` (B-71's own fixtures), where a file dated in another month simply has no data for this one.
    """

    history_dir: Path = DEFAULT_HISTORY
    default: Sources = DEFAULT_SOURCES

    def for_month(self, month: str) -> Sources:
        folder = Path(self.history_dir) / month
        if folder.is_dir():
            return Sources(data_dir=folder / "data", tickets_dir=folder / "tickets", backup_dir=folder / "backup")
        return self.default


DEFAULT_QBR_SOURCES = QbrSources()
