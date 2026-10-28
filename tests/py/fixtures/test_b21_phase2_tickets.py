"""B-21 Phase 2 ticket set: 210 labelled synthetic tickets across three clients, and the Litware Legal tenant.

Acceptance ids B21-1 to B21-4 are defined in specs/B-21.md; the schema is in evals/phase2/README.md. Every test
reads the committed fixtures and never writes them. Offline, no wall clock (every date is checked against the
file's own as_of). Run: uv run --frozen pytest -p no:cacheprovider tests/py/fixtures
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, get_args

import pytest

from core.levers import DEFAULT_REGISTRY_PATH, MockTenant
from core.levers.tenant import DEFAULT_TENANT_DIR
from workflows.triage import load_tickets
from workflows.triage.tickets import Category, Priority, Queue

ROOT = Path(__file__).resolve().parents[3]
PHASE2 = ROOT / "fixtures" / "tickets" / "phase2"
CLIENTS = ("contoso-dental", "fabrikam-capital", "litware-legal")
DOMAINS = {
    "contoso-dental": "contosodental.example",
    "fabrikam-capital": "fabrikamcapital.example",
    "litware-legal": "litwarelegal.example",
}
ID_RANGE = {"contoso-dental": 5100, "fabrikam-capital": 5200, "litware-legal": 5300}
INPUT_FIELDS = (
    "id",
    "client",
    "subject",
    "body",
    "requester",
    "affected_user",
    "technician",
    "source",
    "status",
    "created",
    "updated",
)
LABEL_KEYS = {
    "category",
    "priority",
    "queue",
    "expected_lever",
    "injection",
    "duplicate_group",
    "sla_tier",
    "summary_facts",
    "reply_sources",
    "sensitive",
}
STATUSES = {"new", "in-progress", "waiting-client", "waiting-vendor", "resolved"}
SOURCES = {"portal", "email", "phone"}
SLA_TIERS = {"P1", "P2", "P3", "P4"}
KIND_CLASS = {
    "patient-name": "phi",
    "date-of-birth": "phi",
    "member-id": "phi",
    "account-number": "npi",
    "ssn-shaped": "npi",
    "investor-name": "npi",
    "phone": "pii",
    "client-name": "pii",
    "matter-number": "pii",
}
# Fictional-by-construction shapes. Built at runtime so no literal looks like a real identifier.
DIGIT2, DIGIT4 = r"\d{2}", r"\d{4}"
SHAPES = {
    "phone": "555-01" + DIGIT2,
    "account-number": "00-" + DIGIT4 + "-" + DIGIT4,
    "member-id": "00-" + DIGIT4 + "-" + DIGIT4,
    "ssn-shaped": "000-" + DIGIT2 + "-" + DIGIT4,
    "date-of-birth": DIGIT2 + "/" + DIGIT2 + "/(?:19|20)" + DIGIT2,
    "matter-number": "LL-20" + DIGIT2 + "-" + DIGIT4,
}
# The 60 Phase 1 tickets, as committed (LF line endings; hashed after normalising CRLF checkouts).
PHASE1_SHA256 = {
    "contoso-dental.json": "0a8142c475aa61937fdb6826ac1c2887cb9cceb4846228ba8a9265d4cb215835",
    "fabrikam-capital.json": "375293d1768e7cce03b2d196b67bbac4818a6fcf8fed6eb559007d6356f8b114",
}
DUPLICATE_WINDOW = timedelta(hours=4)


def _load(client: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((PHASE2 / f"{client}.json").read_text(encoding="utf-8"))
    return data


def _ts(value: str) -> datetime:
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value), value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.fixture(scope="module")
def files() -> dict[str, dict[str, Any]]:
    return {c: _load(c) for c in CLIENTS}


@pytest.fixture(scope="module")
def tickets(files: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [t for c in CLIENTS for t in files[c]["tickets"]]


@pytest.fixture(scope="module")
def tenants() -> dict[str, dict[str, Any]]:
    return {c: MockTenant(DEFAULT_TENANT_DIR).load(c) for c in CLIENTS}


def _text(ticket: dict[str, Any]) -> str:
    return f"{ticket['subject']}\n{ticket['body']}"


# B21-1 ------------------------------------------------------------------------------------------------------


def test_b21_1_at_least_200_tickets_across_three_clients(files: dict[str, dict[str, Any]]) -> None:
    assert sorted(p.stem for p in PHASE2.glob("*.json")) == sorted(CLIENTS)
    counts = {c: len(files[c]["tickets"]) for c in CLIENTS}
    assert sum(counts.values()) >= 200, counts
    assert all(n > 0 for n in counts.values()), counts
    for client, doc in files.items():
        assert doc["client"] == client
        assert all(t["client"] == client for t in doc["tickets"])


def test_b21_1_every_ticket_has_every_gold_label_with_valid_values(
    tickets: list[dict[str, Any]], tenants: dict[str, dict[str, Any]]
) -> None:
    levers = {lever["name"] for lever in json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))["levers"]}
    for t in tickets:
        assert set(t) == {*INPUT_FIELDS, "labels"}, t["id"]
        labels = t["labels"]
        assert LABEL_KEYS <= set(labels) <= LABEL_KEYS | {"note"}, t["id"]
        assert labels["category"] in get_args(Category), t["id"]
        assert labels["priority"] in get_args(Priority), t["id"]
        assert labels["queue"] in get_args(Queue), t["id"]
        assert labels["sla_tier"] in SLA_TIERS, t["id"]
        assert t["status"] in STATUSES and t["source"] in SOURCES, t["id"]
        assert labels["summary_facts"], f"{t['id']} has no summary facts"
        for fact in labels["summary_facts"]:
            assert fact["field"] in ("subject", "body"), t["id"]
            assert fact["fact"] and fact["fact"] in t[fact["field"]], (t["id"], fact)
        kb = {a["id"] for a in tenants[t["client"]]["kb"]}
        assert set(labels["reply_sources"]) <= kb, (t["id"], labels["reply_sources"])
        lever = labels["expected_lever"]
        if lever is not None:
            assert lever in levers, t["id"]
            users = {u["userPrincipalName"] for u in tenants[t["client"]]["users"]}
            assert t["affected_user"] in users, f"{t['id']} expects {lever} for a user outside its tenant"
        if labels["injection"]:
            assert labels["queue"] == "security" and lever is None and not labels["reply_sources"], t["id"]


def test_b21_1_duplicate_groups_are_one_client_one_category_within_four_hours(tickets: list[dict[str, Any]]) -> None:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in tickets:
        if t["labels"]["duplicate_group"] is not None:
            groups[t["labels"]["duplicate_group"]].append(t)
    assert len(groups) >= 10, sorted(groups)
    for gid, members in groups.items():
        assert re.fullmatch(r"DG-(CD|FC|LL)-\d\d", gid), gid
        assert len(members) >= 2, gid
        assert len({m["client"] for m in members}) == 1, gid
        assert len({m["labels"]["category"] for m in members}) == 1, gid
        times = sorted(_ts(m["created"]) for m in members)
        assert times[-1] - times[0] <= DUPLICATE_WINDOW, gid
    assert {g[3:5] for g in groups} == {"CD", "FC", "LL"}


def test_b21_1_the_original_60_tickets_are_untouched_and_ids_do_not_collide(tickets: list[dict[str, Any]]) -> None:
    tickets_dir = ROOT / "fixtures" / "tickets"
    for name, digest in PHASE1_SHA256.items():
        content = (tickets_dir / name).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(content).hexdigest() == digest, f"{name} changed"
    phase1 = load_tickets()
    assert len(phase1) == 60
    phase1_ids = {t.id for t in phase1}
    assert all(re.fullmatch(r"T-3[12]\d\d", i) for i in phase1_ids)
    ids = [t["id"] for t in tickets]
    assert len(ids) == len(set(ids)), "duplicate Phase 2 ticket id"
    assert not phase1_ids & set(ids)
    for t in tickets:
        n = int(t["id"][2:])
        assert ID_RANGE[t["client"]] < n < ID_RANGE[t["client"]] + 100, t["id"]


# B21-2 ------------------------------------------------------------------------------------------------------


def test_b21_2_at_least_20_tickets_carry_labelled_phi_or_npi(tickets: list[dict[str, Any]]) -> None:
    sensitive = [t for t in tickets if any(s["class"] in ("phi", "npi") for s in t["labels"]["sensitive"])]
    assert len(sensitive) >= 20, len(sensitive)
    assert {t["client"] for t in sensitive} == set(CLIENTS)
    classes = {s["class"] for t in sensitive for s in t["labels"]["sensitive"]}
    assert {"phi", "npi"} <= classes


def test_b21_2_every_sensitive_span_is_verbatim_labelled_and_fictional(tickets: list[dict[str, Any]]) -> None:
    for t in tickets:
        for span in t["labels"]["sensitive"]:
            assert set(span) == {"kind", "class", "text"}, t["id"]
            assert KIND_CLASS[span["kind"]] == span["class"], (t["id"], span)
            assert span["text"] in _text(t), (t["id"], span)
            if span["kind"] in SHAPES:
                assert re.fullmatch(SHAPES[span["kind"]], span["text"]), (t["id"], span)


def test_b21_2_no_unlabelled_sensitive_shaped_string_in_any_ticket(tickets: list[dict[str, Any]]) -> None:
    """The answer key is complete: a later leakage eval can count misses against these labels."""
    for t in tickets:
        labelled = {s["text"] for s in t["labels"]["sensitive"]}
        for kind, shape in SHAPES.items():
            for match in re.findall(r"(?<![\w-])" + shape + r"(?![\w-])", _text(t)):
                assert match in labelled, f"{t['id']}: unlabelled {kind} {match!r}"


# B21-3 ------------------------------------------------------------------------------------------------------


def test_b21_3_every_file_is_self_labelled_synthetic_with_an_as_of(files: dict[str, dict[str, Any]]) -> None:
    for client, doc in files.items():
        assert "synthetic" in doc["_note"].lower(), client
        as_of = _ts(doc["as_of"])
        for t in doc["tickets"]:
            created, updated = _ts(t["created"]), _ts(t["updated"])
            assert created <= updated <= as_of, t["id"]
    meta = json.loads((DEFAULT_TENANT_DIR / "litware-legal.json").read_text(encoding="utf-8"))["_meta"]
    assert meta["client"] == "litware-legal" and "synthetic" in meta["note"].lower()
    _ts(meta["as_of"])


def test_b21_3_labels_are_never_read_by_the_code_under_test(tickets: list[dict[str, Any]]) -> None:
    # The Phase 1 loader (what triage and its eval read) does not descend into phase2/.
    assert {t.id for t in load_tickets()}.isdisjoint(t["id"] for t in tickets)
    # No production module names the Phase 2 folder; only evals and tests may.
    for folder in ("core", "workflows", "levers"):
        for path in (ROOT / folder).rglob("*"):
            if path.is_file() and path.suffix in (".py", ".ps1", ".psm1", ".json"):
                assert "phase2" not in path.read_text(encoding="utf-8", errors="replace"), path
    # No label value leaks into the untrusted text a model would see.
    for t in tickets:
        text = _text(t)
        assert not re.search(r"\bKB-[A-Z]{2}-\d{3}\b|\bDG-[A-Z]{2}-\d\d\b", text), t["id"]
        assert not any(key in text for key in LABEL_KEYS if "_" in key), t["id"]


def test_b21_3_litware_tenant_is_synthetic_and_loads_like_the_others(tenants: dict[str, dict[str, Any]]) -> None:
    tenant = tenants["litware-legal"]
    assert set(tenant) == set(tenants["contoso-dental"]) == {"_meta", "users", "tickets", "kb"}
    assert tenant["users"] and tenant["kb"]
    for user in tenant["users"]:
        assert user["displayName"].endswith("(synthetic)"), user["displayName"]
        assert user["userPrincipalName"].endswith("@litwarelegal.example")
        assert user["id"].startswith("1a000000-")
        for method in user["authentication"]["methods"]:
            assert method["id"].startswith("1a000000-")
            if "phoneNumber" in method:
                assert re.fullmatch(r"\+1 555 01\d\d", method["phoneNumber"]), method
    assert all(re.fullmatch(r"KB-LL-\d{3}", a["id"]) for a in tenant["kb"])
    assert all(u["userPrincipalName"].endswith(".example") for t in tenants.values() for u in t["users"])


# B21-4 ------------------------------------------------------------------------------------------------------


def test_b21_4_at_least_half_the_new_tickets_are_financial_or_legal(files: dict[str, dict[str, Any]]) -> None:
    counts = {c: len(files[c]["tickets"]) for c in CLIENTS}
    assert counts["fabrikam-capital"] + counts["litware-legal"] >= sum(counts.values()) / 2, counts
    # Contoso Dental stays the W1 demo client: its Phase 1 file and T-3101 are still there.
    assert any(t.id == "T-3101" and t.client == "contoso-dental" for t in load_tickets())


def test_b21_4_form_fields_stay_inside_the_ticket_client_except_labelled_attacks(
    tickets: list[dict[str, Any]],
) -> None:
    cross = []
    for t in tickets:
        domain = DOMAINS[t["client"]]
        people = [t["requester"], *([t["affected_user"]] if t["affected_user"] else [])]
        if any(not p.endswith("@" + domain) for p in people):
            cross.append(t["id"])
            assert t["labels"]["injection"], f"{t['id']} names another client's user but is not labelled an attack"
    assert cross, "the set should include cross-client attack tickets for isolation tests"
    assert len({t["technician"] for t in tickets}) == len(CLIENTS)
