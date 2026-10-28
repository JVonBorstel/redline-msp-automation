"""Alerts mock: serves one client's synthetic alert fixture (fixtures/alerts/<client>.json).

Built for exactly one client from that client's ``alerts`` binding (TEN-04). The fixture's ``account_id`` must equal
the binding's ``external_id`` or construction is refused. A row that names another client is dropped at load, so even a
mis-filed alert never reaches a caller. Read-only; fixtures are never modified; nothing touches a network.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from adapters.alerts.base import CLIENT_ID, Alert, AlertsAdapter
from adapters.base import AdapterError, AdapterResult
from adapters.binding import BoundBinding
from core.paths import REPO_ROOT

DEFAULT_ALERTS_DIR = REPO_ROOT / "fixtures" / "alerts"


class AlertsMock(AlertsAdapter):
    def __init__(self, client: str, binding: BoundBinding, root: Path = DEFAULT_ALERTS_DIR) -> None:
        super().__init__(client, binding)
        if binding.implementation != "mock":
            raise AdapterError("AlertsMock serves the 'mock' implementation only")
        if not CLIENT_ID.fullmatch(client):
            raise AdapterError("invalid client id; adapter not built")
        path = Path(root) / f"{client}.json"
        try:
            data: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AdapterError(f"no readable alerts fixture for this client ({type(exc).__name__})") from exc
        if not isinstance(data, dict) or data.get("client") != client or data.get("account_id") != binding.external_id:
            raise AdapterError("alerts fixture does not belong to this client's binding; adapter not built")
        rows = data.get("alerts")
        if not isinstance(rows, list):
            raise AdapterError("alerts fixture has no alert list; adapter not built")
        try:
            parsed = [Alert.model_validate(row) for row in rows]
        except ValidationError as exc:
            # Names the field and rule, never the offending value.
            problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['type']}" for e in exc.errors())
            raise AdapterError(f"alerts fixture is invalid ({problems}); adapter not built") from exc
        ids = [a.id for a in parsed]
        if len(set(ids)) != len(ids):
            raise AdapterError("alerts fixture repeats an alert id; adapter not built")
        # TEN-04: another client's row is dropped before anything can be returned.
        self._alerts = sorted((a for a in parsed if a.client == client), key=lambda a: (a.created_at, a.id))

    def list_alerts(self, since: datetime | None = None, until: datetime | None = None) -> AdapterResult[list[Alert]]:
        def run() -> AdapterResult[list[Alert]]:
            rows = [
                a
                for a in self._alerts
                if (since is None or a.created_at >= since) and (until is None or a.created_at <= until)
            ]
            return AdapterResult.success(rows)

        return self._guard(run)

    def get_alert(self, alert_id: str) -> AdapterResult[Alert]:
        def run() -> AdapterResult[Alert]:
            for a in self._alerts:
                if a.id == alert_id:
                    return AdapterResult.success(a)
            return AdapterResult.failure("no such alert for this client")

        return self._guard(run)
