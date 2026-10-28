"""Software deployment from an approved catalog, and third-party update review (B-63). Mock only; nothing installs.

``device.install-app`` records ONE install request for one catalog package on one device in the client's own state,
under ``softwareInstallRequests["<device uid>:<package id>"]``, with the version and SHA-256 the catalog pins. Only
catalog ids pass the registry enum, and the handler re-checks that the package is in THIS client's approved list. The
request is a record for a real RMM to act on after approval; no installer is fetched, run or even named here (D6-26).
Asking twice for the same package version changes nothing (STD-LV-6). The handler gets one client's state copy and
validated params only (STD-LV-8); the catalog is this lever's own committed policy data, not client data.

``propose_updates`` is the review: for one client it compares the installed versions on the client's own RMM devices
with the versions the catalog pins and returns proposals per ring (pilot first) with the device count and one dry-run
lever call per device. It never invokes a lever, never writes, and holds back devices in the ``hold`` ring.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapters.rmm.base import RmmAdapter
from core.levers.handlers import LeverFailed
from core.levers.tenant import JsonDict

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = REPO_ROOT / "fixtures" / "catalog" / "approved-software.json"
DEFAULT_INSTALLED = REPO_ROOT / "fixtures" / "catalog" / "installed-software.json"

LEVER = "device.install-app"
RINGS = ("pilot", "broad")  # proposal order; a "hold" device is listed but never proposed
HOLD = "hold"

_PACKAGE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}$")
_VERSION = re.compile(r"^[0-9]+(\.[0-9]+)*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_PACKAGE_FIELDS = {"id", "name", "publisher", "version", "sha256", "installer"}


class CatalogError(RuntimeError):
    """The catalog, the inventory or the request for a review is invalid. Nothing is used from a bad catalog."""


@dataclass(frozen=True)
class Package:
    id: str
    name: str
    publisher: str
    version: str
    sha256: str
    installer: str


@dataclass(frozen=True)
class Catalog:
    packages: Mapping[str, Package]
    approved: Mapping[str, tuple[str, ...]]

    def approved_for(self, client: str) -> tuple[str, ...]:
        if client not in self.approved:
            raise CatalogError(f"the catalog has no approved list for client {client!r}")
        return self.approved[client]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CatalogError(f"no readable file at {Path(path).name} ({type(exc).__name__})") from exc
    if not isinstance(data, dict):
        raise CatalogError(f"{Path(path).name} must be a JSON object")
    return data


def _text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value or "\n" in value:
        raise CatalogError(f"package field {key!r} must be a short text")
    return value


def _package(raw: object) -> Package:
    if not isinstance(raw, dict) or set(raw) != _PACKAGE_FIELDS:
        raise CatalogError(f"a catalog package must have exactly the fields {sorted(_PACKAGE_FIELDS)}")
    package = Package(**{k: _text(raw, k) for k in sorted(_PACKAGE_FIELDS)})
    if not _PACKAGE_ID.fullmatch(package.id):
        raise CatalogError(f"package id {package.id!r} is not a plain slug")
    if not _VERSION.fullmatch(package.version):
        raise CatalogError(f"package {package.id}: version must be pinned digits and dots, not {package.version!r}")
    if not _SHA256.fullmatch(package.sha256):
        raise CatalogError(f"package {package.id}: sha256 must be 64 lowercase hex characters")
    return package


def load_catalog(path: Path = DEFAULT_CATALOG) -> Catalog:
    """Load and validate the whole catalog; one bad entry refuses all of it."""
    data = _read_json(path)
    if data.get("catalog_version") != 1:
        raise CatalogError("catalog_version must be 1")
    packages: dict[str, Package] = {}
    rows = data.get("packages")
    if not isinstance(rows, list) or not rows:
        raise CatalogError("the catalog needs a non-empty packages list")
    for row in rows:
        package = _package(row)
        if package.id in packages:
            raise CatalogError(f"package id {package.id!r} appears twice")
        packages[package.id] = package
    approved: dict[str, tuple[str, ...]] = {}
    clients = data.get("clients")
    if not isinstance(clients, dict):
        raise CatalogError("the catalog needs a clients object")
    for client, entry in clients.items():
        ids = entry.get("approved") if isinstance(entry, dict) else None
        if not _CLIENT_ID.fullmatch(str(client)) or not isinstance(ids, list):
            raise CatalogError(f"client {client!r}: needs an approved list")
        unknown = [i for i in ids if i not in packages]
        if unknown:
            raise CatalogError(f"client {client!r} approves ids that are not in the catalog: {unknown}")
        approved[client] = tuple(sorted(set(ids)))
    return Catalog(packages, approved)


def device_install_app(state: JsonDict, params: Mapping[str, Any]) -> Any:
    """Record that ``package_id`` (at the catalog's pinned version) was asked for on ``device_uid``."""
    meta = state.get("_meta")
    client = meta.get("client") if isinstance(meta, dict) else None
    if not isinstance(client, str):
        raise LeverFailed("the client's state does not say which client it is")
    package_id = str(params["package_id"])
    try:
        catalog = load_catalog()
        approved = catalog.approved_for(client)
    except CatalogError as exc:
        raise LeverFailed(f"the approved catalog could not be used: {exc}") from exc
    if package_id not in approved:
        raise LeverFailed(f"package {package_id!r} is not in this client's approved catalog")
    package = catalog.packages[package_id]
    requests = state.setdefault("softwareInstallRequests", {})
    if not isinstance(requests, dict):
        raise LeverFailed("software install requests are in an unexpected shape")
    wanted = {"package_id": package.id, "version": package.version, "sha256": package.sha256, "status": "requested"}
    requests.setdefault(f"{params['device_uid']}:{package.id}", wanted)
    return {"device_uid": params["device_uid"], "package_id": package.id, "version": package.version}


# -- third-party update review ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RingProposal:
    """One package, one ring: the devices behind the catalog version. A proposal, not an action (B63-3)."""

    ring: str
    package_id: str
    version: str
    sha256: str
    device_uids: tuple[str, ...]
    after_ring: str | None
    calls: tuple[Mapping[str, Any], ...]
    lever: str = LEVER
    approval: str = "lead"
    status: str = "proposed"

    @property
    def device_count(self) -> int:
        return len(self.device_uids)


@dataclass(frozen=True)
class Finding:
    """Something on a device the review lists but does not propose to change."""

    device_uid: str
    package_id: str
    installed: str
    kind: str  # held | newer-than-catalog | unreadable-version | not-approved


@dataclass(frozen=True)
class UpdateReview:
    client: str
    as_of: str
    proposals: tuple[RingProposal, ...]
    findings: tuple[Finding, ...]
    ignored_devices: int  # inventory records of devices that are not this client's RMM devices


def _parse(version: str) -> tuple[int, ...] | None:
    if not _VERSION.fullmatch(version):
        return None
    parts = [int(p) for p in version.split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def propose_updates(
    client: str, rmm: RmmAdapter, *, catalog: Catalog, installed: Path = DEFAULT_INSTALLED
) -> UpdateReview:
    """Propose catalog-version updates per ring for ``client``'s own RMM devices. Read only; idempotent."""
    approved = set(catalog.approved_for(client))
    if rmm.client != client:
        raise CatalogError("the RMM adapter belongs to a different client; nothing is compared")
    listed = rmm.list_devices()
    if not listed.ok or listed.data is None:
        raise CatalogError(f"the RMM device list could not be read: {listed.reason}")
    mine = {str(d["uid"]) for d in listed.data if not d.get("deleted")}
    data = _read_json(installed)
    clients = data.get("clients")
    inventory = clients.get(client) if isinstance(clients, dict) else None
    if not isinstance(inventory, dict) or not isinstance(inventory.get("devices"), dict):
        raise CatalogError(f"no installed-software inventory for client {client!r}")
    behind: dict[tuple[str, str], list[str]] = {}
    findings: list[Finding] = []
    ignored = 0
    for uid in sorted(inventory["devices"]):
        record = inventory["devices"][uid]
        if uid not in mine:
            ignored += 1
            continue
        ring = record.get("ring")
        if ring not in (*RINGS, HOLD):
            raise CatalogError(f"device {uid}: ring must be one of {[*RINGS, HOLD]}")
        for package_id in sorted(record.get("installed", {})):
            have = str(record["installed"][package_id])
            if package_id not in approved:
                findings.append(Finding(uid, package_id, have, "not-approved"))
                continue
            want = _parse(catalog.packages[package_id].version)
            got = _parse(have)
            if got is None or want is None:
                findings.append(Finding(uid, package_id, have, "unreadable-version"))
            elif got > want:
                findings.append(Finding(uid, package_id, have, "newer-than-catalog"))
            elif got < want:
                if ring == HOLD:
                    findings.append(Finding(uid, package_id, have, "held"))
                else:
                    behind.setdefault((ring, package_id), []).append(uid)
    proposals = []
    for index, ring in enumerate(RINGS):
        for package_id in sorted(p for r, p in behind if r == ring):
            package = catalog.packages[package_id]
            uids = tuple(behind[(ring, package_id)])
            calls = tuple(
                {"lever": LEVER, "mode": "dry-run", "params": {"device_uid": u, "package_id": package_id}} for u in uids
            )
            after = RINGS[index - 1] if index > 0 else None
            proposals.append(RingProposal(ring, package_id, package.version, package.sha256, uids, after, calls))
    return UpdateReview(client, str(data.get("asOf", "")), tuple(proposals), tuple(findings), ignored)
