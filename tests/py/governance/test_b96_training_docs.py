"""B-96 staff training, client conversation guide, AI explainer and client data-handling summary (B96-1 to B96-3).

The four pages are hand-written plain language. Every claim about what the system does carries a tag, "(proof: ...)"
with a test that backs it, or "(policy: ...)" with the file that states a rule for people; the checker in
workflows/training fails when a cited file or test does not exist. The ten-minute exercise is replayed here.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/governance
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from workflows.training import claims
from workflows.training.__main__ import main as training_main
from workflows.triage.__main__ import main as triage_main

REPO = Path(__file__).resolve().parents[3]
TRAINING = REPO / "governance" / "STAFF_TRAINING.md"
GUIDE = REPO / "governance" / "CLIENT_CONVERSATION_GUIDE.md"
EXPLAINER = REPO / "docs" / "AI_EXPLAINER.md"
HANDLING = REPO / "docs" / "CLIENT_DATA_HANDLING.md"
STUBS = (REPO / "docs" / "planned" / "STAFF_TRAINING.md", REPO / "docs" / "planned" / "CLIENT_CONVERSATION_GUIDE.md")
ONE_PAGE = (EXPLAINER, HANDLING)

GOOD = """# A page

Status: **document-only** (a test page)

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only.

This page says hello and nothing else.

## What happens

- The runner refuses a lever that is not registered. (proof: `tests/phase1/test_levers.py::test_p1_4_unregistered_lever_denied_and_logged`)
- Your part: read the diff before you approve.

| Question | Answer |
|---|---|
| Hosted models | Off in the shipped config. (proof: `tests/phase1/test_gateway.py::test_shipped_config_keeps_hosted_providers_off`) |

## Limits

- A test that is defined has not necessarily passed. (policy: `governance/AI_POLICY.md`)
"""  # noqa: E501


def problems_for(text: str) -> list[str]:
    return claims.check_doc(text, REPO, "test.md")


def committed(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# -- B96-1: finished pages, the stubs left alone, the exercise on synthetic tickets ----
def test_b96_1_the_four_finished_pages_exist_and_the_planned_stubs_are_left_for_phase0() -> None:
    for path in (TRAINING, GUIDE, EXPLAINER, HANDLING):
        assert path.is_file(), path
    for stub in STUBS:
        assert stub.is_file(), f"{stub} must stay: the protected Phase 0 test requires it"
        assert committed(stub).startswith("# ")


def test_b96_1_the_training_covers_the_seven_outline_topics_in_order() -> None:
    text = committed(TRAINING)
    headings = re.findall(r"(?m)^## (\d)\. ", text)
    assert headings == ["1", "2", "3", "4", "5", "6", "7"]
    stub = committed(STUBS[0])
    for topic in ("DLP_MAPPING", "AI incident response"):
        assert topic in stub
    assert "governance/DLP_MAPPING.md" in text and "docs/runbooks/ai-incident-response.md" in text


def test_b96_1_the_guide_covers_the_five_outline_topics() -> None:
    headings = re.findall(r"(?m)^## (\d)\. ", committed(GUIDE))
    assert headings == ["1", "2", "3", "4", "5"]
    text = committed(GUIDE)
    for question in ("train on my data", "who can see it", "if it is wrong", "opt out"):
        assert question in text.lower(), question


def _exercise_tickets() -> list[str]:
    section = re.search(r"(?ms)^## 7\. .*", committed(TRAINING))
    assert section is not None
    return list(dict.fromkeys(re.findall(r"\bT-\d{4}\b", section.group(0))))


def test_b96_1_the_exercise_uses_synthetic_tickets_that_exist_in_the_fixtures() -> None:
    tickets = {}
    for f in (REPO / "fixtures" / "tickets").glob("*.json"):
        for t in json.loads(f.read_text(encoding="utf-8"))["tickets"]:
            tickets[t["id"]] = t
    ids = _exercise_tickets()
    assert ids == ["T-3101", "T-3127", "T-3128"]
    section = committed(TRAINING).split("## 7. ", 1)[1]
    for tid in ids:
        assert tid in tickets
        assert tickets[tid]["subject"] in section, f"{tid}: quote the fixture subject"
    assert "fixtures/tickets/contoso-dental.json" in section
    assert re.search(r"synthetic", section, re.I)
    assert "ten minutes" in section.lower() or "10 minutes" in section.lower()


@pytest.fixture
def exercise_state(tmp_path: Path) -> Path:
    return tmp_path / "training"


def _triage(ticket: str, state: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    capsys.readouterr()
    assert triage_main([ticket, "--state", str(state), "--json"]) == 0
    out = capsys.readouterr().out
    return json.loads(out[out.index("{") :])  # type: ignore[no-any-return]


def test_b96_1_the_exercise_answer_key_matches_what_the_commands_print(
    exercise_state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = committed(TRAINING).split("### Answer key", 1)[1]
    ok = _triage("T-3101", exercise_state, capsys)
    assert ok["category"] == "mfa" and ok["queue"] == "identity"
    proposal = ok["proposal"]
    assert isinstance(proposal, dict) and proposal["lever"] == "user.reset-mfa" and proposal["status"] == "pending"
    dry = ok["dry_run"]
    assert isinstance(dry, dict) and dry["status"] == "ok" and dry["reason"] == "dry-run: nothing applied"
    assert "user.reset-mfa" in key and "pending" in key
    for tid, rule in (("T-3127", "instruction-override"), ("T-3128", "safety-bypass")):
        bad = _triage(tid, exercise_state, capsys)
        assert bad["proposal"] is None and bad["dry_run"] is None and bad["queue"] == "security"
        injection = bad["injection"]
        assert isinstance(injection, dict) and injection["flagged"] is True
        assert injection["reasons"][0]["rule"] == rule  # type: ignore[index]
        assert rule in key, rule


def test_b96_1_the_exercise_commands_are_the_triage_command_with_a_private_state_folder() -> None:
    section = committed(TRAINING).split("## 7. ", 1)[1]
    commands = re.findall(r"(?m)^uv run .*$", section)
    assert commands
    for c in commands:
        assert re.fullmatch(r"uv run --frozen python -m workflows\.triage T-\d{4} --state \.tmp/training", c), c


# -- B96-2: one page each, plain words, computed reading grade ----
def test_b96_2_the_grade_function_scores_plain_text_low_and_dense_text_high() -> None:
    plain = "We keep each client apart. A person checks every change. The tool shows what it would do first."
    dense = (
        "Notwithstanding organizational heterogeneity, authentication infrastructure necessitates "
        "comprehensive administrative authorization methodologies."
    )
    assert claims.reading_grade(plain) < 5
    assert claims.reading_grade(dense) > 14


@pytest.mark.parametrize("path", ONE_PAGE, ids=lambda p: p.name)
def test_b96_2_the_explainer_and_data_handling_are_grade_8_or_lower(path: Path) -> None:
    grade = claims.reading_grade(claims.reading_text(committed(path)))
    assert grade <= 8.0, f"{path.name}: grade {grade:.1f}"


@pytest.mark.parametrize("path", ONE_PAGE, ids=lambda p: p.name)
def test_b96_2_the_explainer_and_data_handling_fit_on_one_page(path: Path) -> None:
    words = claims.word_count(claims.reading_text(committed(path)))
    assert 150 <= words <= claims.ONE_PAGE_WORDS, f"{path.name}: {words} words"


@pytest.mark.parametrize("path", [TRAINING, GUIDE], ids=lambda p: p.name)
def test_b96_2_training_and_guide_are_plain_enough_for_non_engineers(path: Path) -> None:
    assert claims.reading_grade(claims.reading_text(committed(path))) <= 10.0


def test_b96_2_the_checker_fails_a_one_page_doc_that_is_too_hard_or_too_long() -> None:
    hard = GOOD.replace(
        "This page says hello and nothing else.",
        "Notwithstanding organizational heterogeneity, authentication infrastructure necessitates comprehensive "
        "administrative authorization methodologies.",
    )
    rule = claims.Rule(grade_max=8.0, words_max=claims.ONE_PAGE_WORDS)
    assert any("reading grade" in p for p in claims.check_doc(hard, REPO, "x.md", rule))
    long = GOOD.replace("hello and nothing else.", "hello. " + "We keep each client apart. " * 120)
    assert any("words" in p for p in claims.check_doc(long, REPO, "x.md", rule))


# -- B96-3: every claim links to a file or test that exists ----
def test_b96_3_the_committed_pages_pass_the_checker() -> None:
    assert claims.check_all(REPO) == []


def test_b96_3_the_good_page_passes() -> None:
    assert problems_for(GOOD) == []


def test_b96_3_every_page_has_many_claims_and_each_proof_names_a_test() -> None:
    for name in claims.DOCS:
        text = committed(REPO / name)
        tags = claims.tags(text)
        assert len(tags) >= 8, f"{name}: only {len(tags)} tagged claims"
        proofs = [t for t in tags if t.kind == "proof"]
        assert proofs, name
        for tag in proofs:
            assert any("::" in ref for ref in tag.refs), f"{name}: a proof without a test: {tag.refs}"


def test_b96_3_checker_fails_on_a_test_file_that_does_not_exist() -> None:
    bad = GOOD.replace("tests/phase1/test_levers.py::test", "tests/phase1/test_no_such_file.py::test")
    assert any("test_no_such_file.py" in p and "does not exist" in p for p in problems_for(bad))


def test_b96_3_checker_fails_on_a_test_name_that_is_not_defined() -> None:
    bad = GOOD.replace("test_p1_4_unregistered_lever_denied_and_logged", "test_there_is_no_such_test")
    assert any("test_there_is_no_such_test" in p and "not defined" in p for p in problems_for(bad))


def test_b96_3_checker_fails_on_a_file_or_folder_that_does_not_exist() -> None:
    bad = GOOD.replace("`governance/AI_POLICY.md`", "`governance/NO_SUCH_POLICY.md`")
    assert any("NO_SUCH_POLICY.md" in p for p in problems_for(bad))


def test_b96_3_checker_refuses_paths_that_climb_out_of_the_repo() -> None:
    bad = GOOD.replace("`governance/AI_POLICY.md`", "`../outside.txt`")
    assert any("outside" in p for p in problems_for(bad))


def test_b96_3_a_proof_must_name_a_test_and_a_policy_must_name_a_file() -> None:
    no_test = GOOD.replace("::test_p1_4_unregistered_lever_denied_and_logged", "")
    assert any("proof" in p and "test" in p for p in problems_for(no_test))
    no_ref = GOOD.replace("(policy: `governance/AI_POLICY.md`)", "(policy: see the policy)")
    assert any("policy" in p and "file" in p for p in problems_for(no_ref))


def test_b96_3_a_claim_line_without_a_tag_fails() -> None:
    bad = GOOD.replace(" (proof: `tests/phase1/test_levers.py::test_p1_4_unregistered_lever_denied_and_logged`)", "")
    assert any("no proof or policy tag" in p and "refuses a lever" in p for p in problems_for(bad))
    row = GOOD.replace(" (proof: `tests/phase1/test_gateway.py::test_shipped_config_keeps_hosted_providers_off`)", "")
    assert any("no proof or policy tag" in p and "Hosted models" in p for p in problems_for(row))


def test_b96_3_a_loose_paragraph_that_talks_about_the_system_needs_a_tag() -> None:
    bad = GOOD.replace("This page says hello and nothing else.", "The system never sends data to a hosted model.")
    assert any("paragraph" in p and "never sends" in p for p in problems_for(bad))


def test_b96_3_a_your_part_line_is_guidance_and_needs_no_tag_but_still_gets_the_phrase_check() -> None:
    ok = GOOD.replace("read the diff before you approve.", "read the diff.")
    assert problems_for(ok) == []
    bad = GOOD.replace("read the diff before you approve.", "this is certified.")
    assert any("certified" in p for p in problems_for(bad))


@pytest.mark.parametrize(
    "claim",
    [
        "It is used in production at clients.",
        "The program is SOC 2 compliant.",
        "Customers trust it.",
        "It is certified.",
        "We guarantee the answer is right.",
        "It saves 40% of the time.",
        "It saves $5,000 a month.",
    ],
)
def test_b96_3_overclaims_and_unlabelled_numbers_fail(claim: str) -> None:
    bad = GOOD.replace("This page says hello and nothing else.", claim)
    assert problems_for(bad), claim


def test_b96_3_a_negated_overclaim_is_allowed() -> None:
    ok = GOOD.replace(
        "This page says hello and nothing else.", "This page is not a certification and not in use in production."
    )
    assert problems_for(ok) == []


def test_b96_3_a_fixture_based_number_is_allowed() -> None:
    ok = GOOD.replace(
        "This page says hello and nothing else.", "On fixtures, 90% of 60 test tickets match (fixture-based)."
    )
    assert problems_for(ok) == []


def test_b96_3_the_standard_labels_and_a_limits_section_are_required() -> None:
    assert any("prototype label" in p for p in problems_for(GOOD.replace("Independently built prototype. ", "")))
    assert any("Synthetic data only" in p for p in problems_for(GOOD.replace("Synthetic data only.", "")))
    assert any("Status" in p for p in problems_for(GOOD.replace("Status: **document-only**", "Status: fine")))
    assert any("Limits" in p for p in problems_for(GOOD.replace("## Limits", "## Other")))


def test_b96_3_an_empty_tag_fails() -> None:
    assert any("empty" in p for p in problems_for(GOOD.replace("(policy: `governance/AI_POLICY.md`)", "(policy: )")))


def test_b96_3_the_committed_pages_name_what_they_do_not_show() -> None:
    for name in claims.DOCS:
        text = committed(REPO / name)
        limits = text.split("## Limits", 1)[1]
        assert "fixture" in limits.lower() and "not" in limits.lower(), name


def test_b96_3_the_pages_make_no_production_certification_or_result_claim() -> None:
    for name in claims.DOCS:
        text = committed(REPO / name)
        assert "not affiliated" in text.lower()
        assert not re.search(r"\bis (SOC 2 |HIPAA )?(certified|compliant)\b", text, re.I), name
        assert "$" not in text, name


# -- the command line ----
def test_b96_3_the_cli_check_exits_zero_on_the_repo(capsys: pytest.CaptureFixture[str]) -> None:
    assert training_main(["check"]) == 0
    assert "B-96 checks: ok" in capsys.readouterr().out


def test_b96_3_the_cli_check_exits_one_and_names_the_problem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "repo"
    for name in claims.DOCS:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(committed(REPO / name), encoding="utf-8")
    assert claims.check_all(root) != []  # the proofs point at files the temp repo does not have
    assert training_main(["check", "--root", str(root)]) == 1
    assert "does not exist" in capsys.readouterr().out


def test_b96_3_a_missing_page_is_a_problem(tmp_path: Path) -> None:
    assert any("missing" in p for p in claims.check_all(tmp_path))


def test_b96_3_the_checker_proves_each_cited_test_is_defined_not_that_it_passes() -> None:
    assert "defined" in (claims.__doc__ or "")
