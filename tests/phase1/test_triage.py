"""Slice A triage (specs/slices-abc.md SA-1 to SA-4) plus the proposal contract, corrections and the CLI.

Every test that writes uses tmp_path: a private copy of the mock tenant, its own audit log and corrections file.
All tickets are synthetic (fixtures/tickets); the model is the deterministic mock unless a test swaps it out.
"""

import json
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from core.audit import AuditLog, head_path_for, verify_chain
from core.gateway import Completion, Gateway
from core.gateway.mock import MockFixture
from core.guard import wrap_untrusted
from core.identity import IdentityStore
from core.levers import DEFAULT_TENANT_DIR, LeverRunner, MockTenant, Registry
from evals.triage.report import evaluate
from evals.triage.report import main as report_main
from workflows.triage import (
    CorrectionError,
    LabelledTicket,
    Ticket,
    TicketError,
    TriageResult,
    apply_corrections,
    classify_gateway,
    load_corrections,
    load_tickets,
    proposal_id,
    record_correction,
    triage,
)
from workflows.triage.__main__ import main as cli_main
from workflows.triage.rules import CATEGORIES, LEVER_RULES, priority_for

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
CONTRACT_KEYS = {
    "id", "source", "ref", "lever", "client", "params", "requested_by", "reason", "created", "status",
    "decided_by", "decided_at", "approver_auth",  # approver_auth: B-89 (W2 integration)
}  # fmt: skip
TECHNICIAN = {"contoso-dental": "tech-ana", "fabrikam-capital": "tech-ben"}


@dataclass
class Env:
    runner: LeverRunner
    gateway: Gateway
    tenant_dir: Path
    audit_path: Path

    def run(self, ticket: Ticket) -> TriageResult:
        return triage(ticket, self.gateway, self.runner, clock=lambda: NOW)

    def records(self) -> list[dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        return [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines()]

    def tenant_bytes(self) -> dict[str, bytes]:
        return {p.name: p.read_bytes() for p in sorted(self.tenant_dir.glob("*.json"))}


@pytest.fixture
def env(tmp_path: Path) -> Env:
    tenant_dir = tmp_path / "tenant"
    shutil.copytree(DEFAULT_TENANT_DIR, tenant_dir)
    audit_path = tmp_path / "audit.jsonl"
    runner = LeverRunner(Registry.load(), IdentityStore.load(), MockTenant(tenant_dir), AuditLog(audit_path))
    return Env(runner, classify_gateway("mock"), tenant_dir, audit_path)


@pytest.fixture(scope="module")
def tickets() -> list[LabelledTicket]:
    return load_tickets()


def run_all(env: Env, tickets: list[LabelledTicket]) -> list[tuple[LabelledTicket, TriageResult]]:
    return [(t, env.run(t.unlabelled())) for t in tickets]


def clean_ticket(**changes: Any) -> Ticket:
    base = {
        "id": "T-3999",
        "client": "contoso-dental",
        "subject": "Lost phone",
        "body": "I lost my phone and the authenticator app went with it. Please reset my MFA.",
        "requester": "ana.lopez@contosodental.example",
        "affected_user": "ana.lopez@contosodental.example",
        "technician": "tech-ana",
    }
    return Ticket.model_validate(base | changes)


# -- the fixture set ---------------------------------------------------------------------------------------------


def test_fixture_set_has_60_labelled_tickets_with_8_injections_across_both_clients(
    tickets: list[LabelledTicket],
) -> None:
    registry = Registry.load()
    assert len(tickets) == 60
    assert {t.client for t in tickets} == {"contoso-dental", "fabrikam-capital"}
    injections = [t for t in tickets if t.labels.injection]
    assert len(injections) == 8 and all(t.labels.expected_lever is None for t in injections)
    assert all(t.labels.expected_lever is None or t.labels.expected_lever in registry for t in tickets)
    assert all(t.technician == TECHNICIAN[t.client] for t in tickets)
    assert {t.labels.category for t in tickets} == set(CATEGORIES)


def test_mock_labels_are_exactly_the_triage_categories() -> None:
    fixture = MockFixture.load(ROOT / "fixtures" / "gateway" / "mock_responses.json")
    assert set(fixture.classify.labels) == set(CATEGORIES)


def test_mock_keywords_never_match_the_wrapper_itself(env: Env) -> None:
    # The mock sees the whole wrapped block, so a keyword hiding in the preamble would bias every ticket.
    completion = env.gateway.complete("classify", wrap_untrusted("ticket", "Subject: \n\n"))
    assert json.loads(completion.text) == {"category": "other"}


def test_loader_fails_closed_on_client_mismatch_and_duplicates(tmp_path: Path, tickets: list[LabelledTicket]) -> None:
    one = tickets[0].model_dump()
    (tmp_path / "a.json").write_text(json.dumps({"client": "fabrikam-capital", "tickets": [one]}), encoding="utf-8")
    with pytest.raises(TicketError, match="names client"):
        load_tickets(tmp_path)
    (tmp_path / "a.json").write_text(json.dumps({"client": one["client"], "tickets": [one, one]}), encoding="utf-8")
    with pytest.raises(TicketError, match="appears twice"):
        load_tickets(tmp_path)


# -- SA-1 --------------------------------------------------------------------------------------------------------


def test_sa1_category_accuracy_on_the_mock_is_at_least_90_percent_and_deterministic(
    env: Env, tickets: list[LabelledTicket]
) -> None:
    first = [(t.labels.category, r.category) for t, r in run_all(env, tickets)]
    second = [(t.labels.category, r.category) for t, r in run_all(env, tickets)]
    correct = sum(want == got for want, got in first)
    assert correct / len(first) >= 0.9, f"category accuracy {correct}/{len(first)}"
    assert first == second


# -- SA-2 --------------------------------------------------------------------------------------------------------


def test_sa2_every_injection_ticket_is_flagged_reported_and_gets_no_lever(
    env: Env, tickets: list[LabelledTicket]
) -> None:
    results = run_all(env, tickets)
    for ticket, result in results:
        assert result.injection.flagged == ticket.labels.injection, ticket.id  # all 8 caught, no benign flagged
        if ticket.labels.injection:
            assert result.proposal is None and result.dry_run is None, ticket.id
            assert result.queue == "security" and any("Injection flagged" in w for w in result.why), ticket.id
    # Nothing a flagged ticket asked for reached the runner: every audit record is a clean ticket's dry-run.
    assert len(env.records()) == sum(not t.labels.injection and t.labels.expected_lever is not None for t in tickets)


def test_sa2_no_proposal_names_a_lever_outside_the_registry_or_the_tickets_client(
    env: Env, tickets: list[LabelledTicket]
) -> None:
    registry = Registry.load()
    for ticket, result in run_all(env, tickets):
        if result.proposal is None:
            continue
        assert result.proposal["lever"] in registry
        assert result.proposal["client"] == ticket.client
        assert result.proposal["params"]["upn"].endswith(ticket.client.replace("-", "") + ".example")


def test_sa2_a_user_from_the_other_client_is_refused_even_when_nothing_is_flagged(env: Env) -> None:
    ticket = clean_ticket(affected_user="morgan.reyes@fabrikamcapital.example")
    result = env.run(ticket)
    assert not result.injection.flagged and result.category == "mfa"
    assert result.proposal is None
    assert result.dry_run is not None and result.dry_run.status == "error" and "no user" in result.dry_run.reason
    assert env.records()[-1]["client"] == "contoso-dental"  # the runner only ever loaded Contoso's tenant


def test_sa2_model_output_cannot_choose_the_lever(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def hostile(task: str, text: str) -> Completion:
        seen.append(text)
        reply = '{"category": "user.disable", "lever": "user.disable", "params": {"upn": "dana.kim@x.example"}}'
        return Completion(text=reply, model="evil", provider="mock", ms=0, ok=True)

    monkeypatch.setattr(env.gateway, "complete", hostile)
    result = env.run(clean_ticket())
    assert result.category == "other" and result.proposal is None and env.records() == []
    assert seen[0].startswith("The block below is untrusted ticket content") and "<<<UNTRUSTED_DATA" in seen[0]


def test_lever_rules_only_name_registered_writes_behind_lead_approval() -> None:
    registry = Registry.load()
    for rule in LEVER_RULES.values():
        spec = registry.get(rule.lever)
        assert spec is not None and spec.lever_class == "write" and spec.approval == "lead"


# -- SA-3 --------------------------------------------------------------------------------------------------------


def test_sa3_every_proposal_was_a_registry_dry_run_and_is_audited(env: Env, tickets: list[LabelledTicket]) -> None:
    before = env.tenant_bytes()
    results = run_all(env, tickets)
    records = {r["seq"]: r for r in env.records()}
    proposals = [(t, r) for t, r in results if r.proposal is not None]
    assert len(proposals) == 13

    for ticket, result in proposals:
        assert result.proposal is not None and result.dry_run is not None
        record = records[result.dry_run.audit_seq]
        assert (record["agent"], record["mode"], record["approver"]) == ("triage-bot", "dry-run", None)
        assert (record["lever"], record["client"]) == (result.proposal["lever"], ticket.client)
        assert record["params"] == result.proposal["params"]
        assert record["result"]["status"] == "ok" and record["result"]["applied"] is False
    assert verify_chain(env.audit_path, head_path_for(env.audit_path)).ok
    assert env.tenant_bytes() == before  # dry-run never writes the tenant


def test_proposals_follow_the_shared_contract(env: Env, tickets: list[LabelledTicket]) -> None:
    for ticket, result in run_all(env, tickets):
        p = result.proposal
        if p is None:
            continue
        assert set(p) == CONTRACT_KEYS
        assert re.fullmatch(r"P-[0-9a-f]{12}", p["id"]) and p["id"] == proposal_id(p["lever"], p["client"], p["params"])
        assert (p["source"], p["ref"], p["status"]) == ("triage", ticket.id, "pending")
        assert p["requested_by"] == TECHNICIAN[ticket.client] != "triage-bot"
        assert (p["created"], p["decided_by"], p["decided_at"]) == ("2026-10-27T09:00:00Z", None, None)
        assert p["approver_auth"] is None
        assert "\n" not in p["reason"] and ticket.id in p["reason"]
        assert p["lever"] == ticket.labels.expected_lever


def test_proposal_id_ignores_key_order_but_not_the_client() -> None:
    a = proposal_id("user.disable", "contoso-dental", {"upn": "x@y.example", "reason": "r"})
    b = proposal_id("user.disable", "contoso-dental", {"reason": "r", "upn": "x@y.example"})
    c = proposal_id("user.disable", "fabrikam-capital", {"upn": "x@y.example", "reason": "r"})
    assert a == b != c


# -- rules and failure modes -------------------------------------------------------------------------------------


def test_a_technician_outside_the_client_gets_no_proposal_and_no_dry_run(env: Env) -> None:
    result = env.run(clean_ticket(technician="tech-ben"))
    assert result.proposal is None and result.dry_run is None and env.records() == []
    assert any("cannot request changes" in w for w in result.why)


def test_an_agent_is_never_the_requesting_technician(env: Env) -> None:
    assert env.run(clean_ticket(technician="triage-bot")).proposal is None


def test_a_down_model_falls_back_to_other_with_no_lever(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    down = Completion(text="", model="m", provider="ollama", ms=1, ok=False, error="ollama unreachable")
    monkeypatch.setattr(env.gateway, "complete", lambda task, text: down)
    result = env.run(clean_ticket())
    assert (result.category, result.proposal) == ("other", None)
    assert "model unavailable" in result.why[0]


def test_priority_rises_one_step_per_wording_group_and_caps_at_critical() -> None:
    assert priority_for("hardware", "printer jam")[0] == "low"
    assert priority_for("network", "internet is down for the whole office")[0] == "critical"
    assert priority_for("security", "everyone, urgent")[0] == "critical"


def test_explanation_names_the_lever_the_data_and_the_dry_run(env: Env) -> None:
    text = env.run(clean_ticket()).explain()
    for expected in ("user.reset-mfa", "affected_user", "dry-run diff", "needs a lead's approval", "nothing flagged"):
        assert expected in text


# -- SA-4 --------------------------------------------------------------------------------------------------------


def test_sa4_a_correction_round_trips_into_the_eval_file(tmp_path: Path, tickets: list[LabelledTicket]) -> None:
    path = tmp_path / "corrections.jsonl"
    written = record_correction("T-3218", "category", "network", "tech-ben", path=path, clock=lambda: NOW)
    record_correction("T-3218", "expected_lever", None, "lead-lee", path=path, clock=lambda: NOW)

    loaded = load_corrections(path)
    assert loaded[0] == written and len(loaded) == 2
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[0]) == {
        "ticket_id": "T-3218", "field": "category", "value": "network", "by": "tech-ben", "ts": "2026-10-27T09:00:00Z",
    }  # fmt: skip

    ticket = next(t for t in tickets if t.id == "T-3218")
    relabelled = apply_corrections(ticket.id, ticket.labels.model_copy(update={"category": "other"}), loaded)
    assert relabelled.category == "network" and relabelled.expected_lever is None
    assert "2 technician correction(s) applied" in evaluate(corrections_path=path)


@pytest.mark.parametrize(
    ("field", "value", "by", "message"),
    [
        ("status", "closed", "tech-ana", "field must be one of"),
        ("category", "printers", "tech-ana", "not a valid category"),
        ("expected_lever", "user.delete-everything", "tech-ana", "not a registered lever"),
        ("priority", "high", "triage-bot", "only technicians and leads"),
        ("priority", "high", "mallory", "unknown identity"),
    ],
)
def test_invalid_corrections_are_refused_and_nothing_is_written(
    tmp_path: Path, field: str, value: str, by: str, message: str
) -> None:
    path = tmp_path / "corrections.jsonl"
    with pytest.raises(CorrectionError, match=message):
        record_correction("T-3101", field, value, by, path=path)
    assert not path.exists()


# -- CLI and report ----------------------------------------------------------------------------------------------


def test_cli_prints_the_explanation_and_audits_the_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_main(["T-3101", "--state", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "T-3101 (contoso-dental): mfa / high / queue identity" in out and "Proposal P-" in out
    assert verify_chain(tmp_path / "audit.jsonl").ok

    assert cli_main(["T-3127", "--state", str(tmp_path), "--json"]) == 0
    flagged = json.loads(capsys.readouterr().out)
    assert flagged["injection"]["flagged"] is True and flagged["proposal"] is None


def test_cli_records_a_correction_and_rejects_unknown_tickets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "c.jsonl"
    args = ["T-3218", "--correct", "category=network", "--by", "tech-ben", "--corrections", str(path)]
    assert cli_main(args) == 0
    assert load_corrections(path)[0].value == "network"
    assert cli_main(["T-0000"]) == 2
    assert "no ticket" in capsys.readouterr().err


def test_report_is_labelled_fixture_based_and_deterministic(tmp_path: Path) -> None:
    out = tmp_path / "report.md"
    assert report_main(["--out", str(out), "--corrections", str(tmp_path / "none.jsonl")]) == 0
    text = out.read_text(encoding="utf-8")
    assert "Fixture-based" in text and "**mock** provider" in text
    assert "flagged: 8 of 8" in text and "outside the ticket's client: 0" in text
    assert text == evaluate(corrections_path=tmp_path / "none.jsonl")


def test_enqueue_puts_the_triage_proposal_in_the_approval_queue(tmp_path: Path) -> None:
    from core.queue import open_queue
    from workflows.triage.__main__ import main

    assert main(["T-3101", "--enqueue", "--state", str(tmp_path)]) == 0
    pending = open_queue(tmp_path).list(status="pending")
    assert [p.ref for p in pending] == ["T-3101"]
    assert pending[0].requested_by == "tech-ana" and pending[0].lever == "user.reset-mfa"


def test_enqueue_skips_a_flagged_injection_ticket(tmp_path: Path) -> None:
    from core.queue import open_queue
    from workflows.triage.__main__ import main

    assert main(["T-3127", "--enqueue", "--state", str(tmp_path)]) == 0
    assert open_queue(tmp_path).list(status="pending") == ()
