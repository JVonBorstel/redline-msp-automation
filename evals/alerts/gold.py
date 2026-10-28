"""The B-43 gold set for the alert-grouping eval: the committed alert fixtures plus ``gold.json`` (the answer key).

Evals and tests only. The adapter and the workflow never import this module and never read ``gold.json``
(STD-FX-5).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from adapters.alerts import Alert
from adapters.alerts.mock import DEFAULT_ALERTS_DIR

GOLD_PATH = Path(__file__).with_name("gold.json")


@dataclass(frozen=True, slots=True)
class GoldGroup:
    id: str
    group_type: str
    alert_ids: tuple[str, ...]
    why: str


def load_gold(path: Path = GOLD_PATH) -> dict[str, tuple[GoldGroup, ...]]:
    """Gold groups per client, in file order."""
    raw = json.loads(path.read_text(encoding="utf-8"))["clients"]
    return {
        client: tuple(GoldGroup(gid, g["type"], tuple(g["alerts"]), g["why"]) for gid, g in groups.items())
        for client, groups in raw.items()
    }


def load_all_alerts(root: Path = DEFAULT_ALERTS_DIR) -> list[Alert]:
    """Every client's alerts, mixed in one list, so the eval proves the workflow keeps clients apart."""
    alerts: list[Alert] = []
    for path in sorted(Path(root).glob("*.json")):
        alerts.extend(Alert.model_validate(row) for row in json.loads(path.read_text(encoding="utf-8"))["alerts"])
    return alerts
