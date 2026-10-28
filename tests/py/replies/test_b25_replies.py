"""B-25 draft replies with KB citations and closure follow-up drafts.

Acceptance ids B25-1 to B25-3 are defined in specs/B-25.md. Every test is offline and works in a private folder
(tmp_path); committed fixtures are never modified. Run: uv run --frozen pytest -p no:cacheprovider tests/py/replies
"""

from __future__ import annotations

import ast
import json
import re
import shutil
from pathlib import Path

import pytest

from core.audit import AuditLog, redact, verify_chain
from core.identity import IdentityStore
from core.levers import DEFAULT_TENANT_DIR, LeverRunner, MockTenant, Registry
from evals.replies.gold import get_gold_ticket, load_gold_tickets
from evals.replies.report import EVAL_AGENT, REPORT, eval_runner, evaluate, render
from workflows.notify import DRAFT_HEADER, load_contacts
from workflows.replies import (
    FLAGGED,
    NO_SOURCE,
    ReplyError,
    ReplyTicket,
    check_citations,
    draft_closure,
    draft_reply,
    get_ticket,
    kb_ids,
    load_tickets,
    search_query,
)
from workflows.replies.__main__ import main

REPO = Path(__file__).resolve().parents[3]
CONTOSO, FABRIKAM, LITWARE = "contoso-dental", "fabrikam-capital", "litware-legal"
PHONE = re.compile(r"\b555-01\d\d\b")


# -- helpers ----------------------------------------------------------------------------------------------


@pytest.fixture
def runner(tmp_path: Path) -> LeverRunner:
    """Eval runner: kb.search also enabled for litware-legal, an eval agent scoped to all three clients."""
    return eval_runner(tmp_path)


@pytest.fixture
def real_runner(tmp_path: Path) -> LeverRunner:
    """The committed registry and identities (triage-bot), as the CLI uses them."""
    return LeverRunner(Registry.load(), IdentityStore.load(), MockTenant(), AuditLog(tmp_path / "audit.jsonl"))


@pytest.fixture
def state(tmp_path: Path) -> Path:
    folder = tmp_path / "state"
    folder.mkdir()
    shutil.copytree(DEFAULT_TENANT_DIR, folder / "tenant")
    return folder


def _ticket(ticket_id: str) -> ReplyTicket:
    return get_gold_ticket(ticket_id).ticket()


def _custom(client: str, subject: str, body: str = "Please help.", status: str = "in-progress") -> ReplyTicket:
    return ReplyTicket.model_validate(
        {
            "id": "T-9999",
            "client": client,
            "subject": subject,
            "body": body,
            "requester": "nobody@example.example",
            "status": status,
        }
    )


def _body_lines(text: str) -> list[str]:
    return [ln for ln in text.split("\n")[1:] if ln.strip()][1:]


def _syllables(word: str) -> int:
    word = word.lower()
    count = len(re.findall(r"[aeiouy]+", word))
    if word.endswith("e") and not word.endswith(("le", "ee")) and count > 1:
        count -= 1
    return max(1, count)


def _fk_grade(text: str) -> float:
    sentences = [s for s in re.split(r"[.!?]+(?:\s|$)", text) if re.search(r"[A-Za-z0-9]", s)]
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", text)
    syllables = sum(_syllables(w) for w in words)
    return 0.39 * len(words) / len(sentences) + 11.8 * syllables / len(words) - 15.59


def _audit_records(runner: LeverRunner) -> list[dict[str, object]]:
    path = runner.audit.path
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# -- B25-1 every sentence cites a same-client article; no source means no draft ------------------------------


@pytest.mark.parametrize(
    ("ticket_id", "client", "expected"),
    [("T-5102", CONTOSO, "KB-CD-001"), ("T-5226", FABRIKAM, "KB-FC-001"), ("T-5301", LITWARE, "KB-LL-001")],
)
def test_b25_1_every_sentence_cites_an_article_of_the_same_client(
    runner: LeverRunner, ticket_id: str, client: str, expected: str
) -> None:
    draft = draft_reply(_ticket(ticket_id), runner=runner, agent=EVAL_AGENT)
    assert draft.drafted and expected in draft.sources
    lines = _body_lines(draft.text)
    assert lines
    own = kb_ids(runner.tenant, client)
    for line in lines:
        cited = re.findall(r"\[(KB-[A-Z]+-\d{3})\]$", line)
        assert len(cited) == 1 and cited[0] in own, line
    assert check_citations(draft.text, own) == []


def test_b25_1_draft_sentences_are_quoted_from_the_clients_kb_not_from_the_ticket(runner: LeverRunner) -> None:
    ticket = _ticket("T-5301")
    draft = draft_reply(ticket, runner=runner, agent=EVAL_AGENT)
    kb = {a["id"]: a for a in runner.tenant.load(LITWARE)["kb"]}
    for line in _body_lines(draft.text):
        sentence, article_id = re.fullmatch(r"(.+) \[(KB-LL-\d{3})\]", line).groups()  # type: ignore[union-attr]
        article = kb[article_id]
        assert sentence in article["body"] or sentence == f'We have a guide that matches this: "{article["title"]}".'
    assert ticket.body not in draft.text and ticket.subject not in draft.text


def test_b25_1_no_source_returns_the_exact_line_and_does_not_guess(runner: LeverRunner) -> None:
    ticket = _custom(CONTOSO, "Quote for new operatory PCs", "We want a price for three new computers.")
    draft = draft_reply(ticket, runner=runner, agent=EVAL_AGENT)
    assert draft.drafted is False
    assert draft.text == "no draft: no source article" == NO_SOURCE
    assert draft.sources == ()
    # a ticket with nothing searchable also yields no draft, and no search is run for it
    empty = _custom(CONTOSO, "a", "b")
    assert search_query(empty) == ""
    assert draft_reply(empty, runner=runner, agent=EVAL_AGENT).text == NO_SOURCE


def test_b25_1_single_weak_keyword_is_not_a_source(runner: LeverRunner) -> None:
    ticket = _custom(CONTOSO, "phone", "phone")  # one keyword hit on KB-CD-001 only
    assert draft_reply(ticket, runner=runner, agent=EVAL_AGENT).text == NO_SOURCE


def test_b25_1_no_cross_client_citation_even_when_the_ticket_uses_another_clients_words(runner: LeverRunner) -> None:
    # Litware's trust-account and docketing vocabulary, asked at Contoso: Contoso's KB has none of it.
    ticket = _custom(CONTOSO, "docketing calendar trust account wire change", "e-filing portal litigation hold")
    draft = draft_reply(ticket, runner=runner, agent=EVAL_AGENT)
    assert draft.text == NO_SOURCE
    # and the same words at Litware do find Litware's own articles, with only Litware ids
    other = draft_reply(
        _custom(LITWARE, "docketing calendar trust account wire change", "e-filing portal litigation hold"),
        runner=runner,
        agent=EVAL_AGENT,
    )
    assert other.drafted and all(s.startswith("KB-LL-") for s in other.sources)
    assert not re.search(r"KB-(CD|FC)-", other.text)


def test_b25_1_validator_rejects_uncited_foreign_and_unknown_citations(runner: LeverRunner) -> None:
    own = kb_ids(runner.tenant, CONTOSO)
    good = f"{DRAFT_HEADER}\n\nHi Priya,\n\nVerify the caller first. [KB-CD-001]\n"
    assert check_citations(good, own) == []
    uncited = good + "We will fix it today.\n"
    assert any("without a citation" in p for p in check_citations(uncited, own))
    foreign = good + "Add Full Access. [KB-FC-001]\n"
    assert any("KB-FC-001 is not an article of this client" in p for p in check_citations(foreign, own))
    unknown = good + "Anything at all. [KB-CD-999]\n"
    assert any("KB-CD-999" in p for p in check_citations(unknown, own))
    two = f"{DRAFT_HEADER}\n\nHi Priya,\n\nFirst thing. Second thing. [KB-CD-001]\n"
    assert any("more than one sentence" in p for p in check_citations(two, own))
    assert check_citations("Hi Priya,\n\nA sentence. [KB-CD-001]\n", own) == ["the first line is not the draft label"]
    assert check_citations(f"{DRAFT_HEADER}\n\nVerify. [KB-CD-001]\n", own) == ["no salutation line"]
    assert check_citations(f"{DRAFT_HEADER}\n\nHi Priya,\n", own) == ["the draft has no sentences"]


def test_b25_1_a_flagged_ticket_gets_no_draft_and_no_search(runner: LeverRunner) -> None:
    flagged = [g for g in load_gold_tickets() if g.labels.injection]
    assert len(flagged) == 15
    for gold in flagged:
        draft = draft_reply(gold.ticket(), runner=runner, agent=EVAL_AGENT)
        assert draft.text == FLAGGED and not draft.drafted, gold.id
    assert _audit_records(runner) == [], "a flagged ticket must not reach kb.search"


def test_b25_1_kb_search_goes_through_the_runner_as_the_agent_and_is_audited(runner: LeverRunner) -> None:
    draft = draft_reply(_ticket("T-5102"), runner=runner, agent=EVAL_AGENT)
    records = _audit_records(runner)
    assert len(records) == 1 and len(draft.audit_seqs) == 1
    record = records[0]
    assert record["lever"] == "kb.search" and record["client"] == CONTOSO and record["agent"] == EVAL_AGENT
    assert verify_chain(runner.audit.path).ok


def test_b25_1_search_denied_for_the_client_means_no_draft_and_an_audited_denial(real_runner: LeverRunner) -> None:
    # The committed kb.search is not enabled for litware-legal and triage-bot has no litware scope: denied, not guessed.
    draft = draft_reply(_ticket("T-5301"), runner=real_runner)
    assert draft.drafted is False
    assert draft.text.startswith("no draft: the knowledge base search was not allowed (")
    records = _audit_records(real_runner)
    assert len(records) == 1 and records[0]["lever"] == "kb.search"
    assert records[0]["client"] == LITWARE and "denied" in json.dumps(records[0])


def test_b25_1_a_client_the_agent_is_not_scoped_to_is_denied(runner: LeverRunner) -> None:
    ghost = _custom("ghost-client", "lost phone mfa authenticator")
    draft = draft_reply(ghost, runner=runner, agent=EVAL_AGENT)
    assert draft.drafted is False and draft.text != NO_SOURCE


def test_b25_1_drafts_are_deterministic(runner: LeverRunner) -> None:
    first = draft_reply(_ticket("T-5301"), runner=runner, agent=EVAL_AGENT)
    second = draft_reply(_ticket("T-5301"), runner=runner, agent=EVAL_AGENT)
    assert first.text == second.text and first.sources == second.sources


def test_b25_1_search_query_fits_the_lever_limit_and_drops_filler() -> None:
    long_body = " ".join(f"word{i:03d}" for i in range(80))
    query = search_query(_custom(CONTOSO, "The printer is offline today", long_body))
    assert 0 < len(query) <= 100
    assert query.startswith("printer offline")
    assert "the" not in query.split() and "today" not in query.split()


def test_b25_1_first_name_comes_from_the_tenant_and_falls_back_to_there(runner: LeverRunner) -> None:
    known = draft_reply(_ticket("T-5301"), runner=runner, agent=EVAL_AGENT).text
    assert "\nHi Hannah,\n" in known
    stranger = _custom(LITWARE, "lost phone mfa authenticator new phone")
    assert "\nHi there,\n" in draft_reply(stranger, runner=runner, agent=EVAL_AGENT).text


def test_b25_1_ticket_loader_fails_closed_on_a_bad_file(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ReplyError):
        load_gold_tickets(tmp_path)
    with pytest.raises(ReplyError):
        load_gold_tickets(tmp_path / "missing")
    with pytest.raises(ReplyError):
        get_gold_ticket("T-0000")


# -- B25-2 closure follow-ups: plain words, the way back, draft label, never sent ---------------------------


def test_b25_2_closure_confirms_the_fix_and_offers_the_way_back(runner: LeverRunner) -> None:
    draft = draft_closure(_ticket("T-5104"), runner=runner, agent=EVAL_AGENT)
    contoso = load_contacts()[CONTOSO]
    assert draft.drafted and draft.kind == "closure"
    text = draft.text
    assert text.startswith(DRAFT_HEADER + "\n")
    assert "Your ticket T-5104 is now marked resolved." in text
    assert 'The fix follows our guide "Re-register MFA after a lost or replaced phone". [KB-CD-001]' in text
    assert "Please check that it works the way you expect." in text
    assert f"call {contoso.fast_phone} ({contoso.hours}) and we will reopen your ticket." in text
    assert check_citations_in_closure(text, kb_ids(runner.tenant, CONTOSO)) == []


def check_citations_in_closure(text: str, own: frozenset[str]) -> list[str]:
    """Any citation that appears in a closure draft must be an article of the client."""
    return [c for c in re.findall(r"\[(KB-[A-Z]+-\d{3})\]", text) if c not in own]


def test_b25_2_closure_uses_the_technicians_fix_line_when_given(runner: LeverRunner) -> None:
    draft = draft_closure(
        _ticket("T-5104"), runner=runner, fix_summary="We set up your new phone as a sign-in method", agent=EVAL_AGENT
    )
    assert "What we did: We set up your new phone as a sign-in method." in draft.text
    assert draft.sources == () and "[KB-" not in draft.text
    assert _audit_records(runner) == [], "the technician's line needs no search"


@pytest.mark.parametrize(
    "bad", ["", "line one\nline two", "uses $variable", "has <angle>", "see [KB-CD-001]", "x" * 201]
)
def test_b25_2_unsafe_fix_summary_is_refused(runner: LeverRunner, bad: str) -> None:
    with pytest.raises(ReplyError):
        draft_closure(_ticket("T-5104"), runner=runner, fix_summary=bad, agent=EVAL_AGENT)


@pytest.mark.parametrize("ticket_id", ["T-5102", "T-5225"])
def test_b25_2_only_resolved_tickets_get_a_closure_draft(runner: LeverRunner, ticket_id: str) -> None:
    ticket = _ticket(ticket_id)
    assert ticket.status != "resolved"
    draft = draft_closure(ticket, runner=runner, agent=EVAL_AGENT)
    assert draft.drafted is False
    assert draft.text == f"no draft: ticket {ticket_id} is {ticket.status}, not resolved"


def test_b25_2_closure_without_a_fast_path_contact_fails_closed(runner: LeverRunner) -> None:
    assert LITWARE not in load_contacts()
    draft = draft_closure(_ticket("T-5301"), runner=runner, agent=EVAL_AGENT)
    assert draft.drafted is False and draft.text == "no draft: no fast-path contact on file for this client"


def test_b25_2_closure_with_a_bad_contacts_file_raises(runner: LeverRunner, tmp_path: Path) -> None:
    bad = tmp_path / "contacts.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(ReplyError):
        draft_closure(_ticket("T-5104"), runner=runner, contacts_path=bad, agent=EVAL_AGENT)


def test_b25_2_closure_is_short_plain_and_safe(runner: LeverRunner) -> None:
    for ticket_id, client in (("T-5104", CONTOSO), ("T-5226", FABRIKAM)):
        text = draft_closure(_ticket(ticket_id), runner=runner, agent=EVAL_AGENT).text
        assert len(text.split()) <= 120
        assert _fk_grade(text) <= 8.0, _fk_grade(text)
        assert redact(text) == text
        assert "@" not in text
        mine = load_contacts()[client].fast_phone
        others = {c.fast_phone for name, c in load_contacts().items() if name != client}
        assert set(PHONE.findall(text)) == {mine} and mine not in others


def test_b25_2_every_drafted_reply_and_closure_starts_with_the_draft_label(runner: LeverRunner) -> None:
    drafted = 0
    for gold in load_gold_tickets():
        for draft in (
            draft_reply(gold.ticket(), runner=runner, agent=EVAL_AGENT),
            draft_closure(gold.ticket(), runner=runner, agent=EVAL_AGENT),
        ):
            if draft.drafted:
                drafted += 1
                assert draft.text.split("\n", 1)[0] == "Draft. A person reviews and sends this." == DRAFT_HEADER
    assert drafted > 100


def test_b25_2_code_never_sends_anything() -> None:
    banned = {
        "smtplib",
        "socket",
        "ssl",
        "http",
        "urllib",
        "requests",
        "httpx",
        "email",
        "subprocess",
        "imaplib",
        "ftplib",
    }
    package = REPO / "workflows" / "replies"
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                assert name.split(".")[0] not in banned, f"{path.name} imports {name}"
                assert not name.startswith("core.gateway"), f"{path.name} calls a model gateway"
            if isinstance(node, ast.FunctionDef):
                assert not node.name.lstrip("_").startswith(("send", "post", "deliver")), node.name


def test_b25_2_cli_writes_only_the_draft_file_and_the_audit_log(
    state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = {p.relative_to(state) for p in state.rglob("*") if p.is_file()}
    assert main(["reply", "T-5102", "--state", str(state)]) == 0
    out = capsys.readouterr()
    target = state / "replies" / "T-5102.reply.md"
    assert target.read_text(encoding="utf-8") == out.out
    assert out.out.startswith(DRAFT_HEADER)
    after = {p.relative_to(state) for p in state.rglob("*") if p.is_file()}
    assert {p.parts[0] for p in after - before} <= {"replies", "audit.jsonl", "audit.jsonl.head", "pauses.json"}
    assert Path("replies/T-5102.reply.md") in after
    assert before <= after


def test_b25_2_cli_closure_and_exit_codes(state: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["closure", "T-5104", "--state", str(state), "--fix", "We reset your sign-in setup"]) == 0
    assert "What we did: We reset your sign-in setup." in capsys.readouterr().out
    assert main(["closure", "T-5102", "--state", str(state)]) == 1  # not resolved
    assert (state / "replies" / "T-5102.closure.md").read_text(encoding="utf-8").startswith("no draft: ticket T-5102")
    assert main(["reply", "T-5112", "--state", str(state)]) == 1  # no source for this ticket
    assert (state / "replies" / "T-5112.reply.md").read_text(encoding="utf-8") == NO_SOURCE + "\n"
    capsys.readouterr()
    assert main(["reply", "T-0000", "--state", str(state)]) == 2
    assert main(["closure", "T-5104", "--state", str(state), "--fix", "has $bad"]) == 2
    assert "error:" in capsys.readouterr().err


# -- B25-3 eval: coverage 100%, zero cross-client citations, fixture-based --------------------------------------


def test_b25_3_gold_set_has_100_percent_citation_coverage_and_no_cross_client_citation(runner: LeverRunner) -> None:
    tickets = load_gold_tickets()
    assert len(tickets) == 210
    stats = evaluate(tickets, runner)
    assert set(stats) == {CONTOSO, FABRIKAM, LITWARE}
    sentences = sum(s.sentences for s in stats.values())
    assert sentences > 150
    assert sum(s.cited_sentences for s in stats.values()) == sentences
    assert sum(s.cross_client for s in stats.values()) == 0
    assert [p for s in stats.values() for p in s.problems] == []
    assert sum(s.drafted + s.no_source + s.flagged + s.other_no_draft for s in stats.values()) == 210
    assert sum(s.other_no_draft for s in stats.values()) == 0


def test_b25_3_committed_report_is_current_and_labelled_fixture_based(runner: LeverRunner) -> None:
    text = REPORT.read_text(encoding="utf-8")
    assert text == render(evaluate(load_gold_tickets(), runner)), "run: uv run --frozen python -m evals.replies.report"
    assert "fixture-based" in text
    assert "Citation coverage: **100.0%**" in text and "Cross-client citations: **0**" in text
    assert "Result: **PASS**" in text


def test_b25_2_default_loader_reads_both_ticket_sets_and_ignores_labels() -> None:
    tickets = load_tickets()
    ids = {t.id for t in tickets}
    assert len(tickets) == 270 and {"T-3101", "T-5301"} <= ids
    phase1 = get_ticket("T-3101")
    assert phase1.status is None and not hasattr(phase1, "labels")


def test_b25_2_closure_for_a_ticket_with_no_status_says_so(runner: LeverRunner) -> None:
    draft = draft_closure(get_ticket("T-3101"), runner=runner, agent=EVAL_AGENT)
    assert draft.drafted is False and draft.text == "no draft: ticket T-3101 is of unknown status, not resolved"
