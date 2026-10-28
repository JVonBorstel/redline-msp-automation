"""B-04 affected-person notice drafts: executed-only, a template per write lever, plain and safe text, HO-9 header.

Acceptance ids B04-1 to B04-4 are defined in specs/B-04.md. Every test is offline and works in a private state folder
(tmp_path) with a copy of the synthetic mock tenant; committed fixtures are never modified.
Run: uv run --frozen pytest tests/py/notify
"""

from __future__ import annotations

import ast
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.audit import redact
from core.identity import IdentityStore
from core.levers import DEFAULT_TENANT_DIR, MockTenant, Registry
from core.levers.models import Verification
from core.queue import Proposal, ProposalQueue, open_queue
from workflows.notify import (
    DEFAULT_CONTACTS_PATH,
    DRAFT_HEADER,
    TEMPLATES_DIR,
    NotifyError,
    NotifyRefused,
    draft_notice,
    load_contacts,
    missing_templates,
)
from workflows.notify.__main__ import main

REPO = Path(__file__).resolve().parents[3]
CONTOSO = "contoso-dental"
PRIYA = "priya.nair@contosodental.example"
JAMIE = "jamie.chen@contosodental.example"
PHONE = re.compile(r"(?:\+?1[ -.]?)?\(?\b\d{3}\)?[ -.]?\d{3}[ -.]?\d{4}\b|\b555[ -.]?01\d\d\b")


# -- helpers ----------------------------------------------------------------------------------------------


def _queue(state: Path) -> ProposalQueue:
    return open_queue(state)


def _proposal(lever: str, params: dict[str, str], ref: str = "T-3101", source: str = "triage") -> Proposal:
    return Proposal.new(
        source=source,  # type: ignore[arg-type]
        ref=ref,
        lever=lever,
        client=CONTOSO,
        params=dict(params),
        requested_by="tech-ana",
        reason=f"{ref} needs {lever}",
    )


def _executed(state: Path, lever: str = "user.reset-mfa", params: dict[str, str] | None = None, **kw: str) -> str:
    queue = _queue(state)
    stored = queue.add(_proposal(lever, params or {"upn": PRIYA}, **kw))
    # identity levers need a recorded requester verification since B-02 (C-30)
    verified = Verification(method="callback-on-file", by="lead-lee", at=datetime(2026, 10, 20, 9, 0, tzinfo=UTC))
    decision = queue.decide(stored.id, "lead-lee", approve=True, verification=verified)
    assert decision.proposal.status == "executed", decision.result
    return stored.id


def _draft(state: Path, proposal: Proposal) -> str:
    return draft_notice(
        proposal,
        registry=Registry.load(),
        identities=IdentityStore.load(),
        tenant=MockTenant(state / "tenant"),
        contacts=load_contacts(),
    ).text


def _syllables(word: str) -> int:
    word = word.lower()
    groups = re.findall(r"[aeiouy]+", word)
    count = len(groups)
    if word.endswith("e") and not word.endswith(("le", "ee")) and count > 1:
        count -= 1
    return max(1, count)


def _fk_grade(text: str) -> float:
    """Flesch-Kincaid grade: 0.39 * words/sentences + 11.8 * syllables/words - 15.59."""
    sentences = [s for s in re.split(r"[.!?]+(?:\s|$)", text) if re.search(r"[A-Za-z0-9]", s)]
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", text)
    syllables = sum(_syllables(w) for w in words)
    return 0.39 * len(words) / len(sentences) + 11.8 * syllables / len(words) - 15.59


def _words(text: str) -> int:
    return len(text.split())


def _tenant_phones() -> set[str]:
    digits: set[str] = set()
    for path in DEFAULT_TENANT_DIR.glob("*.json"):
        for match in re.findall(r'"phoneNumber":\s*"([^"]+)"', path.read_text(encoding="utf-8")):
            digits.add(re.sub(r"\D", "", match)[-7:])
    return digits


@pytest.fixture
def state(tmp_path: Path) -> Path:
    folder = tmp_path / "state"
    folder.mkdir()
    shutil.copytree(DEFAULT_TENANT_DIR, folder / "tenant")
    return folder


# -- B04-1 executed only -----------------------------------------------------------------------------------


def test_b04_1_cli_writes_draft_for_executed_proposal(state: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pid = _executed(state)
    assert main([pid, "--state", str(state)]) == 0
    draft = state / "notices" / f"{pid}.md"
    assert draft.is_file()
    out = capsys.readouterr()
    assert out.out == draft.read_text(encoding="utf-8")
    assert str(draft) in out.err


@pytest.mark.parametrize("status", ["pending", "approved", "rejected", "failed"])
def test_b04_1_cli_refuses_every_other_status(state: Path, capsys: pytest.CaptureFixture[str], status: str) -> None:
    proposal = _proposal("user.reset-mfa", {"upn": PRIYA})
    if status != "pending":
        proposal = proposal.model_copy(
            update={"status": status, "decided_by": "lead-lee", "decided_at": "2026-10-21T10:00:00Z"}
        )
    (state / "queue.jsonl").write_text(proposal.model_dump_json() + "\n", encoding="utf-8")
    assert main([proposal.id, "--state", str(state)]) == 1
    err = capsys.readouterr().err
    assert f"is {status}" in err
    assert "only after the change was executed" in err
    assert "no draft was written" in err
    assert not (state / "notices").exists()
    with pytest.raises(NotifyRefused):
        _draft(state, proposal)


def test_b04_1_rejected_through_queue_is_refused(state: Path, capsys: pytest.CaptureFixture[str]) -> None:
    queue = _queue(state)
    stored = queue.add(_proposal("user.reset-mfa", {"upn": PRIYA}))
    queue.decide(stored.id, "lead-lee", approve=False)
    assert main([stored.id, "--state", str(state)]) == 1
    assert "is rejected" in capsys.readouterr().err
    assert not (state / "notices").exists()


def test_b04_1_unknown_or_bad_id_or_missing_queue_exits_2(state: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["P-000000000000", "--state", str(state)]) == 2  # no queue file yet
    assert "no readable queue" in capsys.readouterr().err
    _executed(state)
    assert main(["P-000000000000", "--state", str(state)]) == 2
    assert "no proposal P-000000000000" in capsys.readouterr().err
    assert main(["../../etc", "--state", str(state)]) == 2
    assert "is not a proposal id" in capsys.readouterr().err
    assert not (state / "notices").exists()


def test_b04_1_cli_reads_queue_without_writing_it(state: Path) -> None:
    pid = _executed(state)
    before = (state / "queue.jsonl").read_bytes()
    assert main([pid, "--state", str(state)]) == 0
    assert (state / "queue.jsonl").read_bytes() == before


# -- B04-2 templates, deterministic, no model ----------------------------------------------------------------


def test_b04_2_every_write_lever_has_a_template() -> None:
    registry = Registry.load()
    writes = [n for n in registry.names() if (s := registry.get(n)) is not None and s.lever_class == "write"]
    assert writes, "registry has no write levers"
    assert missing_templates(registry) == [], "write lever without workflows/notify/templates/<lever>.md"
    for name in writes:
        assert (TEMPLATES_DIR / f"{name}.md").is_file(), name


def test_b04_2_missing_template_is_reported_and_fails_closed(state: Path, tmp_path: Path) -> None:
    partial = tmp_path / "templates"
    partial.mkdir()
    shutil.copy(TEMPLATES_DIR / "user.reset-mfa.md", partial / "user.reset-mfa.md")
    registry = Registry.load()
    writes = {n for n in registry.names() if (s := registry.get(n)) is not None and s.lever_class == "write"}
    assert set(missing_templates(registry, partial)) == writes - {"user.reset-mfa"}  # every other write lever
    assert {"ticket.link", "user.disable"} <= set(missing_templates(registry, partial))
    pid = _executed(state, "user.disable", {"upn": JAMIE, "reason": "Left the practice"}, ref="T-3101")
    proposal = _queue(state).get(pid)
    assert proposal is not None
    with pytest.raises(NotifyError, match="no notice template for user.disable"):
        draft_notice(
            proposal,
            registry=Registry.load(),
            identities=IdentityStore.load(),
            tenant=MockTenant(state / "tenant"),
            contacts=load_contacts(),
            templates_dir=partial,
        )


def test_b04_2_unknown_placeholder_fails_closed(state: Path, tmp_path: Path) -> None:
    bad = tmp_path / "templates"
    bad.mkdir()
    (bad / "user.reset-mfa.md").write_text("Hi $first_name, your $ticket_body\n", encoding="utf-8")
    proposal = _queue(state).get(_executed(state))
    assert proposal is not None
    with pytest.raises(NotifyError, match="no trusted value"):
        draft_notice(
            proposal,
            registry=Registry.load(),
            identities=IdentityStore.load(),
            tenant=MockTenant(state / "tenant"),
            contacts=load_contacts(),
            templates_dir=bad,
        )


def test_b04_2_filling_is_deterministic(state: Path) -> None:
    pid = _executed(state)
    proposal = _queue(state).get(pid)
    assert proposal is not None
    first = _draft(state, proposal)
    assert _draft(state, proposal) == first
    assert main([pid, "--state", str(state)]) == 0
    one = (state / "notices" / f"{pid}.md").read_bytes()
    assert main([pid, "--state", str(state)]) == 0
    assert (state / "notices" / f"{pid}.md").read_bytes() == one == first.encode("utf-8")


def test_b04_2_no_model_import() -> None:
    for path in (REPO / "workflows" / "notify").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                assert not name.startswith("core.gateway"), f"{path.name} imports {name}"
                assert "classify" not in name, f"{path.name} imports {name}"


def test_b04_2_free_text_never_reaches_the_draft(state: Path) -> None:
    pid = _executed(state)
    proposal = _queue(state).get(pid)
    assert proposal is not None
    text = _draft(state, proposal)
    body = json.loads((REPO / "fixtures" / "tickets" / "contoso-dental.json").read_text(encoding="utf-8"))
    t3101 = next(t for t in body["tickets"] if t["id"] == "T-3101")
    assert "lake" not in text and t3101["subject"] not in text
    assert proposal.reason not in text  # the triage reason line is for leads, not the person


# -- B04-3 the T-3101 draft --------------------------------------------------------------------------------


def _check_plain_and_safe(text: str) -> None:
    assert _words(text) <= 120, _words(text)
    assert _fk_grade(text) <= 8.0, _fk_grade(text)
    assert redact(text) == text, "secret-shaped value in the draft"
    fast = {c.fast_phone for c in load_contacts().values()}
    personal = _tenant_phones()
    for found in PHONE.findall(text):
        assert found.strip() in fast, f"unexpected phone-shaped value {found!r}"
        assert re.sub(r"\D", "", found)[-7:] not in personal
    assert "@" not in text, "no address in the draft"


def test_b04_3_t3101_draft_says_what_why_who_back_and_undo(state: Path) -> None:
    pid = _executed(state)
    assert main([pid, "--state", str(state)]) == 0
    text = (state / "notices" / f"{pid}.md").read_text(encoding="utf-8")
    contoso = load_contacts()[CONTOSO]
    assert re.fullmatch(r"555-01\d\d", contoso.fast_phone)
    assert "Hi Priya," in text
    assert "What changed: we reset the sign-in check (MFA)" in text
    assert "Why: you asked for it in ticket T-3101." in text
    assert "Who approved it: Lee" in text
    assert "How to undo it:" in text
    assert f"Call your IT help desk at {contoso.fast_phone}" in text
    _check_plain_and_safe(text)


def test_b04_3_t3101_has_no_secret_or_personal_phone_even_with_seeded_values(state: Path) -> None:
    tenant = MockTenant(state / "tenant")
    data = tenant.load(CONTOSO)
    priya = next(u for u in data["users"] if u["userPrincipalName"] == PRIYA)
    priya["mobilePhone"] = "+1 555 0123"
    priya["note"] = "sk-" + "A1b2C3d4" * 4
    tenant.save(CONTOSO, data)
    pid = _executed(state)
    proposal = _queue(state).get(pid)
    assert proposal is not None
    text = _draft(state, proposal)
    assert "0123" not in text and "sk-" not in text
    _check_plain_and_safe(text)


def test_b04_3_user_disable_draft_is_plain_and_safe(state: Path) -> None:
    pid = _executed(
        state, "user.disable", {"upn": JAMIE, "reason": "Left the practice"}, ref="F-STALE-01", source="baseline"
    )
    proposal = _queue(state).get(pid)
    assert proposal is not None
    text = _draft(state, proposal)
    assert "Hi Jamie," in text
    assert "turned off sign-in" in text
    assert "Why: a security check flagged it (F-STALE-01)." in text
    assert "Left the practice" not in text
    _check_plain_and_safe(text)


def test_b04_3_isolation_contoso_draft_never_shows_fabrikam_contact(state: Path) -> None:
    pid = _executed(state)
    proposal = _queue(state).get(pid)
    assert proposal is not None
    text = _draft(state, proposal)
    contacts = load_contacts()
    assert contacts["fabrikam-capital"].fast_phone not in text
    assert contacts[CONTOSO].fast_phone in text
    only_fabrikam = {"fabrikam-capital": contacts["fabrikam-capital"]}
    with pytest.raises(NotifyError, match="no fast-path contact for client 'contoso-dental'"):
        draft_notice(
            proposal,
            registry=Registry.load(),
            identities=IdentityStore.load(),
            tenant=MockTenant(state / "tenant"),
            contacts=only_fabrikam,
        )


def test_b04_3_contacts_fixture_is_synthetic_and_fails_closed(tmp_path: Path) -> None:
    raw = json.loads(DEFAULT_CONTACTS_PATH.read_text(encoding="utf-8"))
    assert "Synthetic" in raw["_note"]
    for contact in raw["clients"].values():
        assert re.fullmatch(r"555-01\d\d", contact["fast_phone"])
    raw["clients"][CONTOSO]["fast_phone"] = "303-555-1234"
    bad = tmp_path / "contacts.json"
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(NotifyError, match="cannot load contacts"):
        load_contacts(bad)


# -- B04-4 HO-9 header -------------------------------------------------------------------------------------


def test_b04_4_first_line_is_the_draft_header(state: Path) -> None:
    assert DRAFT_HEADER == "Draft. A person reviews and sends this."
    for lever, params in (("user.reset-mfa", {"upn": PRIYA}), ("user.disable", {"upn": JAMIE, "reason": "Left"})):
        pid = _executed(state, lever, params)
        assert main([pid, "--state", str(state)]) == 0
        text = (state / "notices" / f"{pid}.md").read_text(encoding="utf-8")
        assert text.splitlines()[0] == DRAFT_HEADER


def test_b04_4_templates_do_not_carry_their_own_header() -> None:
    for path in TEMPLATES_DIR.glob("*.md"):
        assert DRAFT_HEADER not in path.read_text(encoding="utf-8"), path.name
