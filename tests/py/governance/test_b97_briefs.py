"""B-97 tech radar, leadership brief, 30/60/90 plan and automation framework review: the checker and the pages.

Acceptance ids B97-1 to B97-3 are defined in specs/B-97.md. The four pages are hand-written except one generated
ranking table; the checker in workflows/assurance/briefs.py fails when a claim line cites no real file or test, when a
radar ring is assigned without evidence, when the ranking differs from the intake scores, or when a page promises a
result. Run: uv run --frozen pytest -p no:cacheprovider tests/py/governance -o addopts=
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from workflows.assurance import briefs
from workflows.assurance.__main__ import main
from workflows.assurance.render import ordered, score_examples

ROOT = Path(__file__).resolve().parents[3]


def _text(key: str) -> str:
    return (ROOT / briefs.PAGES[key]).read_text(encoding="utf-8")


def _radar_with(row: str) -> str:
    """The radar page with one more row appended to the radar table."""
    lines = _text("radar").split("\n")
    end = next(i for i, ln in enumerate(lines) if ln.startswith("| Area"))
    while lines[end].startswith("|"):
        end += 1
    return "\n".join([*lines[:end], row, *lines[end:]])


# ---------------------------------------------------------------------------------------------------------------
# the committed pages


def test_b97_all_the_committed_pages_pass_the_check() -> None:
    assert briefs.check_all(ROOT) == []


def test_b97_the_four_pages_exist_and_the_planned_stub_is_left_alone() -> None:
    for rel in briefs.PAGES.values():
        assert (ROOT / rel).is_file(), rel
    assert (ROOT / "docs" / "planned" / "TECH_RADAR.md").is_file()  # protected by the Phase 0 test
    assert briefs.PAGES["radar"] == "governance/TECH_RADAR.md"


def test_b97_every_page_carries_the_honest_labels() -> None:
    for key in briefs.PAGES:
        text = _text(key)
        assert "Independently built prototype. Not affiliated with any vendor's or real company's systems." in text
        assert "fixture-based" in text
        assert "UNVERIFIED" in text
        assert re.search(r"^## (Not shown|Unverified|Limits)", text, re.M), key
        assert "$" not in text, key


def test_b97_no_page_promises_a_result() -> None:
    for key in briefs.PAGES:
        assert briefs.check_promises(key, _text(key)) == [], key
    for phrase in ("This will save 40 hours a month.", "We guarantee fewer tickets.", "Expect a 30% saving."):
        assert briefs.check_promises("brief", phrase), phrase


# ---------------------------------------------------------------------------------------------------------------
# the citation rule


def test_b97_a_claim_line_without_a_citation_fails() -> None:
    assert briefs.check_citations("brief", "- Triage is accurate.\n", ROOT)
    assert briefs.check_citations("brief", "- Triage is accurate (`evals/triage/report.md`).\n", ROOT) == []


def test_b97_a_citation_to_a_missing_file_or_test_fails() -> None:
    assert briefs.check_citations("brief", "- Claim (`evals/triage/nope.md`).\n", ROOT)
    assert briefs.check_citations("brief", "- Claim (`tests/py/mcp/test_b87_mcp.py::test_not_there`).\n", ROOT)
    ok = "- Claim (`tests/py/mcp/test_b87_mcp.py::test_b87_1_default_listing_is_exactly_the_registered_read_levers`).\n"
    assert briefs.check_citations("brief", ok, ROOT) == []


def test_b97_a_citation_may_not_leave_the_repo() -> None:
    assert briefs.check_citations("brief", "- Claim (`../outside.md`).\n", ROOT)
    assert briefs.check_citations("brief", "- Claim (`C:/Windows/win.ini`).\n", ROOT)


def test_b97_table_rows_need_a_citation_but_the_header_and_separator_do_not() -> None:
    table = "| Area | Source |\n|---|---|\n| Routing | `evals/routing/report.md` |\n"
    assert briefs.check_citations("brief", table, ROOT) == []
    assert briefs.check_citations("brief", table + "| Vectors | none |\n", ROOT)


def test_b97_code_fences_and_plain_paragraphs_are_not_claim_lines() -> None:
    text = "A plain sentence.\n\n```\n- not a claim\n```\n"
    assert briefs.check_citations("brief", text, ROOT) == []


def test_b97_every_claim_line_of_every_page_is_checked_and_there_are_many() -> None:
    for key in briefs.PAGES:
        assert len(briefs.claim_lines(_text(key))) >= 8, key


# ---------------------------------------------------------------------------------------------------------------
# B97-1: the radar


def test_b97_1_every_radar_row_has_a_known_ring_and_evidence() -> None:
    rows = briefs.parse_radar(_text("radar"))
    assert len(rows) >= 8
    for row in rows:
        assert row.ring in briefs.RINGS, row
        assert briefs.cited(row.evidence, ROOT), row
        assert row.not_shown.strip(), row


def test_b97_1_every_adopt_row_names_an_eval_or_a_test() -> None:
    adopts = [r for r in briefs.parse_radar(_text("radar")) if r.ring == "adopt"]
    assert adopts, "the radar should adopt at least what this repo's own evals and tests support"
    for row in adopts:
        assert any(c.path.startswith(("evals/", "tests/py/")) for c in briefs.cited(row.evidence, ROOT)), row


def test_b97_1_an_adopt_row_with_only_a_document_as_evidence_fails() -> None:
    row = "| Vector store | pgvector | adopt | `docs/BLUEPRINT.md` | no code exists |"
    problems = briefs.check_radar(_radar_with(row), ROOT)
    assert any("adopt" in p for p in problems), problems


def test_b97_1_an_adopt_row_with_an_eval_report_passes() -> None:
    row = "| Routing | rules-first cascade 2 | adopt | `evals/routing/report.md` | mock tiers only |"
    assert briefs.check_radar(_radar_with(row), ROOT) == []


def test_b97_1_an_unknown_ring_or_an_empty_not_shown_cell_fails() -> None:
    assert briefs.check_radar(_radar_with("| A | B | must-have | `evals/routing/report.md` | x |"), ROOT)
    assert briefs.check_radar(_radar_with("| A | B | trial | `evals/routing/report.md` |  |"), ROOT)
    assert briefs.check_radar(_radar_with("| A | B | trial | enthusiasm | x |"), ROOT)


def test_b97_1_things_with_no_code_or_eval_in_the_repo_are_not_adopted() -> None:
    rows = {r.candidate: r for r in briefs.parse_radar(_text("radar"))}
    for name in ("OpenTelemetry", "pgvector", "Qdrant", "Azure OpenAI", "Anthropic API"):
        assert name in rows, name
        assert rows[name].ring in {"assess", "hold"}, rows[name]


def test_b97_1_the_stub_candidates_are_all_still_on_the_radar() -> None:
    stub = (ROOT / "docs" / "planned" / "TECH_RADAR.md").read_text(encoding="utf-8")
    page = _text("radar")
    for name in ("Ollama", "vLLM", "LM Studio", "pgvector", "Qdrant", "MCP", "OpenTelemetry", "Azure OpenAI"):
        assert name in stub and name in page, name


# ---------------------------------------------------------------------------------------------------------------
# B97-2: the leadership brief ranks from the intake scores


def test_b97_2_the_ranking_block_is_the_generated_one() -> None:
    assert briefs.ranking_block(_text("brief")) == briefs.render_ranking(ROOT)


def test_b97_2_the_ranking_follows_the_intake_scores() -> None:
    scored = ordered(score_examples(ROOT))
    block = briefs.render_ranking(ROOT)
    rows = [ln for ln in block.splitlines() if re.match(r"\| (\d+|-) \|", ln)]
    assert len(rows) == len(scored)
    ids = [re.search(r"UC-\d{3}", ln).group(0) for ln in rows if re.search(r"UC-\d{3}", ln)]  # type: ignore[union-attr]
    assert ids == [s.id for s in scored]
    for s, ln in zip(scored, rows, strict=True):
        assert s.verdict in ln
        assert s.risk_class in ln
        if s.priority is not None:
            assert f"{s.priority:.2f}" in ln
        else:
            assert re.match(r"\| - \|", ln), ln  # blocked or unmeasured: never given a rank


def test_b97_2_every_ranking_row_cites_its_intake_file_and_labels_assumptions() -> None:
    block = briefs.render_ranking(ROOT)
    assert "(assumed)" in block and "(fixture)" in block
    assert "$" not in block
    for line in block.splitlines():
        if re.match(r"\| (\d+|-) \|", line):
            assert "fixtures/governance/intakes/UC-" in line
    assert briefs.check_citations("brief", block, ROOT) == []


def test_b97_2_a_swapped_or_edited_ranking_row_fails() -> None:
    text = _text("brief")
    lines = text.split("\n")
    idx = [i for i, ln in enumerate(lines) if re.match(r"\| 1 \|", ln)]
    assert idx
    lines[idx[0]] = lines[idx[0]].replace("candidate", "approved")
    problems = briefs.check_brief(("\n".join(lines)), ROOT)
    assert any("ranking" in p for p in problems), problems


def test_b97_2_a_missing_ranking_block_fails() -> None:
    stripped = re.sub(r"<!-- ranking:begin -->.*<!-- ranking:end -->", "", _text("brief"), flags=re.S)
    assert any("ranking" in p for p in briefs.check_brief(stripped, ROOT))


def test_b97_2_the_brief_says_where_the_inputs_come_from_and_what_they_are_not() -> None:
    text = _text("brief")
    assert "governance/intake_rubric.json" in text
    assert "not a saving" in text.lower()
    assert "leadership decides" in text.lower()


# ---------------------------------------------------------------------------------------------------------------
# B97-3: the framework review method


def test_b97_3_the_checklist_has_the_five_questions() -> None:
    text = _text("review")
    for name in ("Rights", "Secrets", "Idempotency", "Logging", "Owner"):
        assert re.search(rf"^### \d\. {name}\b", text, re.M), name
    assert briefs.check_review(text, ROOT) == []


def test_b97_3_removing_a_checklist_question_fails() -> None:
    text = re.sub(r"^### \d\. Idempotency.*?(?=^### |^## )", "", _text("review"), flags=re.S | re.M)
    assert any("Idempotency" in p for p in briefs.check_review(text, ROOT))


def test_b97_3_the_method_makes_no_claim_about_any_real_script() -> None:
    text = _text("review")
    assert "Q-07" in text and "D6-26" in text
    assert "no claim about any real script" in text.lower()
    # nothing that looks like a named script, a file extension of one, or a count of real scripts
    assert not re.search(r"\.(ps1|bat|cmd|vbs|sh)\b", re.sub(r"`[^`]*`", "", text))
    assert briefs.check_review(text.replace("Q-07", "Q-00"), ROOT)


def test_b97_3_an_answer_form_is_provided_and_blank() -> None:
    text = _text("review")
    assert "Review record" in text
    assert re.search(r"\|\s*Script\s*\|", text)


# ---------------------------------------------------------------------------------------------------------------
# the plan


def test_b97_plan_has_three_windows_each_with_an_exit_check() -> None:
    text = _text("plan")
    assert briefs.check_plan(text, ROOT) == []
    for heading in ("## Days 1 to 30", "## Days 31 to 60", "## Days 61 to 90"):
        assert heading in text
    assert text.count("Exit check") >= 3


def test_b97_plan_roadmap_ids_exist_in_the_roadmap() -> None:
    known = {
        i["id"]
        for w in json.loads((ROOT / "map" / "roadmap.json").read_text(encoding="utf-8"))["waves"]
        for i in w.get("items", [])
    }
    assert known, "roadmap shape changed"
    mentioned = set(re.findall(r"\bB-\d{2}\b", _text("plan")))
    assert mentioned and mentioned <= known
    bad = _text("plan") + "\n- Build B-99 next (`map/roadmap.json`).\n"
    assert briefs.check_plan(bad, ROOT)


def test_b97_plan_is_an_ordered_proposal_not_a_commitment() -> None:
    text = _text("plan").lower()
    assert "proposal" in text
    assert "no dates" in text or "relative to day 1" in text


# ---------------------------------------------------------------------------------------------------------------
# the command line


def test_b97_cli_check_passes_on_the_repo(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["briefs", "check"]) == 0
    assert "B-97 checks: ok" in capsys.readouterr().out


def test_b97_cli_ranking_is_a_dry_run_unless_write(capsys: pytest.CaptureFixture[str]) -> None:
    before = _text("brief")
    assert main(["briefs", "ranking"]) == 0
    assert _text("brief") == before
    assert "in sync" in capsys.readouterr().out
