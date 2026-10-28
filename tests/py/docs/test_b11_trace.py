"""B-11 one-ticket trace leave-behind: docs/TRACE_T3101.md is one honest page that matches what the code does.

Acceptance ids B11-1 to B11-3 are defined in specs/B-11.md. The page is read as committed; the fixture run of
T-3101 uses a private state folder (tmp_path), the deterministic mock model and no network.
Run: uv run --frozen pytest tests/py/docs -o addopts=
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from core.audit.verify import main as verify_main
from core.levers.models import Approval, Verification
from core.queue.store import open_queue
from workflows.notify.__main__ import main as notify_main
from workflows.triage.__main__ import main as triage_main

ROOT = Path(__file__).resolve().parents[3]
PAGE = ROOT / "docs" / "TRACE_T3101.md"
DEMO = ROOT / "docs" / "DEMO.md"
GOVERNANCE = ROOT / "docs" / "map" / "05-governance.md"

MAX_WORDS = 850
STEP_ROWS = (
    "The ticket",
    "The triage proposal",
    "The verification",
    "The approval",
    "The audit record",
    "The notice draft",
)
IMPACT_ROWS = ("Contoso Dental", "The MSP", "The community")
ITEM_IDS = {"W-IDM-02", "W-TRN-02", "C-45", "C-08", "C-30"}
CITED_ID = re.compile(r"\b(?:W-[A-Z]+-\d{2}|C-\d{2}|EU-\d+|ISO-\d+|HO-\d+)\b")
ANY_ID = re.compile(r"\b[A-Z]+(?:-[A-Z0-9]+)*-\d+[A-Za-z0-9]*\b")
FENCE = re.compile(r"```[a-z]*\n(.*?)```", re.S)
INLINE_CODE = re.compile(r"`([^`\n]+)`")
ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]*[A-Z][A-Z0-9]*\b")
COMMAND_START = ("uv run", "pwsh", "python -m", "Invoke-", "Get-Content")

PRIYA = "priya.nair@contosodental.example"
PROPOSAL = "P-d01c53bdf1dc"


# ---------- page parsing and the three checkers (pure functions, so they can be tested on a bad page) ----------


def page_text() -> str:
    return PAGE.read_text(encoding="utf-8")


def table_rows(text: str) -> dict[str, list[str]]:
    """First cell -> all cells, for every markdown table row that is not a header or separator."""
    rows: dict[str, list[str]] = {}
    for line in text.splitlines():
        if not line.startswith("|") or set(line) <= {"|", "-", " "}:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[0] in ("Step", "For whom"):
            continue
        rows[cells[0]] = cells
    return rows


def prose(text: str) -> str:
    """The page without fenced blocks and inline code."""
    return INLINE_CODE.sub(" ", FENCE.sub(" ", text))


def commands(text: str) -> list[str]:
    found: list[str] = []
    for block in FENCE.findall(text):
        found += [line.strip() for line in block.splitlines() if line.strip() and not line.strip().startswith("#")]
    found += [
        span.strip() for span in INLINE_CODE.findall(FENCE.sub(" ", text)) if span.strip().startswith(COMMAND_START)
    ]
    return found


def commands_missing_from_demo(text: str, demo: str) -> list[str]:
    return [c for c in commands(text) if c not in demo]


def unlabelled_number_lines(text: str) -> list[str]:
    bad = []
    for line in prose(text).splitlines():
        stripped = ANY_ID.sub(" ", line)
        if re.search(r"\d", stripped) and "fixture-based" not in line:
            bad.append(line)
    return bad


def unexplained_acronyms(text: str) -> list[str]:
    """Acronyms whose first use in the prose is not `words (ACR)`."""
    body = ANY_ID.sub(" ", prose(text))
    bad = []
    for acr in dict.fromkeys(ACRONYM.findall(body)):
        first = re.search(rf"\b{acr}\b", body)
        assert first is not None
        start = first.start()
        defined = body[start - 1 : start] == "(" and body[start + len(acr) : start + len(acr) + 1] == ")"
        defined = defined and bool(re.search(r"[a-z]", body[max(0, start - 40) : start]))
        if not defined:
            bad.append(acr)
    return bad


def known_ids() -> set[str]:
    inventory = json.loads((ROOT / "map" / "inventory.json").read_text(encoding="utf-8"))
    controls = json.loads((ROOT / "map" / "controls.json").read_text(encoding="utf-8"))
    ids = {_id(x) for x in _items(inventory)} | {_id(x) for x in _items(controls)}
    governance = GOVERNANCE.read_text(encoding="utf-8")
    ids |= set(re.findall(r"^\| `((?:EU|ISO|HO)-\d+)`", governance, re.M))
    ids |= set(re.findall(r"\| `(HO-\d+)` ", governance))
    return ids


def _items(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    for key in ("items", "controls", "inventory"):
        if isinstance(data.get(key), list):
            return list(data[key])
    raise AssertionError("unexpected map file shape")


def _id(item: Any) -> str:
    return str(item["id"])


# ---------- B11-1 one page, every step and level, every line citing resolvable ids, matching the code ----------


def test_b11_1_the_page_has_one_row_for_each_step_and_each_level() -> None:
    rows = table_rows(page_text())
    for name in STEP_ROWS + IMPACT_ROWS:
        assert name in rows, f"missing row: {name}"


def test_b11_1_every_row_cites_ids_of_the_five_kinds_only() -> None:
    for name, cells in table_rows(page_text()).items():
        rests_on = cells[-1]
        cited = CITED_ID.findall(rests_on)
        assert cited, f"row {name!r} cites no id"
        leftover = CITED_ID.sub("", rests_on).replace(",", "").strip()
        assert leftover == "", f"row {name!r} cites something that is not a W-, C-, EU-, ISO- or HO- id: {leftover!r}"


def test_b11_1_every_cited_id_resolves_in_the_map() -> None:
    known = known_ids()
    cited = set(CITED_ID.findall(page_text()))
    assert cited, "the page cites no ids"
    assert sorted(cited - known) == []


def test_b11_1_the_impact_rows_carry_the_items_inventory_ids_and_controls() -> None:
    rows = table_rows(page_text())
    cited = set().union(*(set(CITED_ID.findall(rows[name][-1])) for name in IMPACT_ROWS))
    assert ITEM_IDS <= cited


def test_b11_1_fits_on_one_page() -> None:
    assert len(page_text().split()) <= MAX_WORDS


def test_b11_1_names_priya_and_t3101_as_synthetic() -> None:
    text = page_text()
    assert "Priya Nair (synthetic)" in text
    assert "Contoso Dental (synthetic)" in text
    assert "T-3101" in text
    assert "Independently built prototype" in text


def test_b11_1_the_pages_claims_match_a_fixture_run_of_t3101(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = page_text()
    state = tmp_path / "state"

    # the ticket and the triage proposal: one lever, dry-run, the callback line
    assert triage_main(["T-3101", "--enqueue", "--state", str(state)]) == 0
    out = capsys.readouterr().out
    assert "lever user.reset-mfa for contoso-dental" in out and PRIYA in out
    assert "nothing applied" in out
    assert "call back on the number on file" in out and "call Priya back on the phone number already on file" in text

    # the approval with the recorded verification (the page's form, through the queue)
    queue = open_queue(state)
    verification = Verification(
        method="callback-on-file", by="lead-lee", at=datetime.now(UTC), ref="number-on-file:psa-contact"
    )
    decision = queue.decide(PROPOSAL, "lead-lee", True, verification)
    assert decision.proposal.status == "executed" and decision.result is not None and decision.result.applied
    assert "Lee" in text and "Lee) approves" in text

    # the audit record: approver, verification, phone details masked, 2 records (the page's number)
    chain = state / "audit" / "contoso-dental.jsonl"  # B-42: one chain per client
    records = [json.loads(line) for line in chain.read_text(encoding="utf-8").splitlines()]
    execute = records[-1]
    assert execute["approver"] == "lead-lee" and execute["agent"] == "tech-ana"
    assert execute["result"]["verification"]["method"] == "callback-on-file"
    assert "iPhone" not in json.dumps(execute)
    assert verify_main([str(chain)]) == 0
    verified = capsys.readouterr().out
    assert "OK: 2 records" in verified and "2 records" in text

    # the notice draft: password unchanged, Lee named, a person sends it
    assert notify_main([PROPOSAL, "--state", str(state)]) == 0
    notice = (state / "notices" / f"{PROPOSAL}.md").read_text(encoding="utf-8")
    assert notice.startswith("Draft. A person reviews and sends this.")
    assert "Your password is the same" in notice and "Lee" in notice and "Hi Priya" in notice
    assert "password is the same" in text and "a person reads it and sends it" in text


def test_b11_1_without_the_recorded_callback_the_change_is_refused(tmp_path: Path) -> None:
    queue = open_queue(tmp_path)
    unverified = Approval(approver="lead-lee", lever="user.reset-mfa", client="contoso-dental", params={"upn": PRIYA})
    result = queue.runner.invoke(
        "user.reset-mfa", {"upn": PRIYA}, "tech-ana", "contoso-dental", mode="execute", approval=unverified
    )
    assert result.status == "denied" and "verification" in result.reason
    assert "Without that record, the software refuses to make the change" in page_text()


# ---------- B11-2 commands in DEMO.md, numbers labelled, limits stated ----------


def test_b11_2_every_command_on_the_page_is_in_demo_md() -> None:
    text = page_text()
    assert len(commands(text)) >= 3
    assert commands_missing_from_demo(text, DEMO.read_text(encoding="utf-8")) == []


def test_b11_2_the_command_checker_catches_a_command_not_in_demo_md() -> None:
    bad = "Run `uv run --frozen python -m workflows.notify P-1 --state .tmp/demo` to see it."
    assert commands_missing_from_demo(bad, DEMO.read_text(encoding="utf-8")) != []


def test_b11_2_every_number_is_labelled_fixture_based() -> None:
    text = page_text()
    assert "Every number on this page is fixture-based" in text
    assert unlabelled_number_lines(text) == []


def test_b11_2_the_number_checker_catches_an_unlabelled_number() -> None:
    assert unlabelled_number_lines("Resets take 4 minutes on average.") != []
    assert unlabelled_number_lines("Resets take 4 minutes (fixture-based).") == []
    assert unlabelled_number_lines("Rests on C-30 and W-IDM-02, see `uv run x 9`.") == []


def test_b11_2_it_states_plainly_what_is_not_proven() -> None:
    text = page_text()
    assert "## What this does not prove" in text
    assert "Nothing has run against a real tenant" in text
    assert "**No real callback.**" in text and "Nobody's phone rang" in text
    assert "**Nothing is sent.**" in text


def test_b11_2_status_line_first() -> None:
    lines = [line for line in page_text().splitlines() if line.strip()]
    assert lines[1].startswith("Status: **built**")


# ---------- B11-3 readable by a non-technical reader ----------


def test_b11_3_every_acronym_is_spelled_out_at_first_use() -> None:
    text = page_text()
    assert unexplained_acronyms(text) == []
    for acr in ("MFA", "MSP", "IT"):
        assert f"({acr})" in text


def test_b11_3_the_acronym_checker_catches_an_unexplained_one() -> None:
    assert unexplained_acronyms("The PSA ticket goes to the MSP.") == ["PSA", "MSP"]
    assert unexplained_acronyms("A managed service provider (MSP) runs it. The MSP is the MSP.") == []
    assert unexplained_acronyms("Rests on W-IDM-02 and `HO-` rules.") == []
