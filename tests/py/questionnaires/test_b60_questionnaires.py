"""B-60 answer drafts. Acceptance ids B60-1 to B60-3: specs/B-60.md.

Offline and deterministic: the embedder is the hash-based stand-in, nothing calls a model. Questionnaires, policy
passages and past projects are the synthetic ones in fixtures/questionnaires/.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/questionnaires
"""

from __future__ import annotations

import ast
import dataclasses
import json
import re
from pathlib import Path

import pytest

from core.paths import REPO_ROOT
from workflows.questionnaires import (
    NEEDS_PERSON,
    Cite,
    Claim,
    Draft,
    Item,
    QuestionnaireError,
    build_context,
    check_draft,
    draft_item,
    draft_questionnaire,
    inflation_problems,
    load_questionnaire,
    render_draft,
    validate_owner,
)
from workflows.questionnaires.__main__ import main

FIX = REPO_ROOT / "fixtures" / "questionnaires"
OWNER = "Dana Whitfield"
CONTOSO = "contoso-dental"
FABRIKAM = "fabrikam-capital"
CANARIES = ["zebra-cq-canary-5521", "quokka-fq-canary-6602"]
FILES = ["security_questionnaire.json", "cyber_insurance.json", "proposal.json"]
CHUNK = re.compile(r"\[(ch-[0-9a-f]{20})\]")


@pytest.fixture(scope="module")
def ctx():  # type: ignore[no-untyped-def]
    return build_context()


def _all(ctx):  # type: ignore[no-untyped-def]
    out = []
    for name in FILES:
        q = load_questionnaire(FIX / name)
        out.append((q, draft_questionnaire(ctx, q, OWNER)))
    return out


def _by_id(drafts: list[Draft]) -> dict[str, Draft]:
    return {d.item_id: d for d in drafts}


def _security(ctx) -> dict[str, Draft]:  # type: ignore[no-untyped-def]
    q = load_questionnaire(FIX / "security_questionnaire.json")
    return _by_id(draft_questionnaire(ctx, q, OWNER))


# -- B60-1: cited policy passages, or "needs a person" ----------------------------------------------------------------


def test_b60_1_a_policy_question_is_answered_with_a_quote_and_a_chunk_citation(ctx) -> None:  # type: ignore[no-untyped-def]
    d = _security(ctx)["S-01"]
    assert not d.refused
    text = render_draft(d)
    assert "Staff accounts should use multifactor authentication for remote access." in text
    assert "KB-POL-001" in text
    assert CHUNK.search(text)
    assert all(c.kind in {"passage", "control", "test"} for claim in d.claims for c in claim.cites)


def test_b60_1_every_claim_has_at_least_one_citation(ctx) -> None:  # type: ignore[no-untyped-def]
    for _, drafts in _all(ctx):
        for d in drafts:
            for claim in d.claims:
                assert claim.cites, (d.item_id, claim.text)


def test_b60_1_a_question_without_a_source_is_marked_needs_a_person(ctx) -> None:  # type: ignore[no-untyped-def]
    d = _security(ctx)["S-10"]
    assert d.refused and not d.claims
    text = render_draft(d)
    assert NEEDS_PERSON in text.lower()
    assert "needs a human answer" in text.lower()
    assert not CHUNK.search(text)


def test_b60_1_each_refusal_class_is_refused_with_its_own_reason(ctx) -> None:  # type: ignore[no-untyped-def]
    s = _security(ctx)
    assert "production" in s["S-06"].reason or "operat" in s["S-06"].reason
    assert "certif" in s["S-07"].reason
    assert "result" in s["S-12"].reason
    assert "no source" in s["S-10"].reason
    for key in ("S-06", "S-07", "S-10", "S-12"):
        assert s[key].refused and not s[key].claims


def test_b60_1_questions_that_ask_for_production_or_certification_are_refused_even_with_matching_policy(ctx) -> None:  # type: ignore[no-untyped-def]
    # The MFA policy passage is retrievable for S-06, yet the question asks whether it is enforced in production.
    d = _security(ctx)["S-06"]
    assert d.refused
    assert "KB-POL-001" not in render_draft(d)


@pytest.mark.parametrize(
    "text",
    [
        "Are all laptops encrypted right now?",
        "Is our firewall fully deployed?",
        "Do you hold ISO 27001 or HITRUST status?",
        "Are you HIPAA compliant?",
        "What percentage of staff completed training?",
        "Has an attestation report been issued?",
        "Describe the penetration test results.",
    ],
)
def test_b60_1_claims_the_repo_cannot_verify_are_refused(ctx, text: str) -> None:  # type: ignore[no-untyped-def]
    d = draft_item(ctx, CONTOSO, Item("X-1", "msp", text), OWNER)
    assert d.refused and not d.claims, text


def test_b60_1_injection_flagged_question_text_is_withheld(ctx) -> None:  # type: ignore[no-untyped-def]
    d = _security(ctx)["S-11"]
    assert d.refused and d.withheld_question
    text = render_draft(d)
    assert "ignore previous instructions" not in text.lower()
    assert "withheld" in text.lower()
    assert NEEDS_PERSON in text.lower()


def test_b60_1_injected_policy_text_is_never_quoted(ctx) -> None:  # type: ignore[no-untyped-def]
    for _, drafts in _all(ctx):
        for d in drafts:
            text = render_draft(d).lower()
            assert "ignore all previous" not in text
            assert "soc 2 certified" not in text
    # ingestion withholds the whole chunk, so even the clean sentence beside the planted one is not quoted
    item = Item("X-2", "msp", "Who records policy exceptions?")
    d = draft_item(ctx, CONTOSO, item, OWNER)
    assert "Policy exceptions are recorded" not in render_draft(d)
    assert "ignore" not in render_draft(d).lower()


def test_b60_1_policy_items_quote_only_msp_passages_not_client_records(ctx) -> None:  # type: ignore[no-untyped-def]
    for _, drafts in _all(ctx):
        for d in drafts:
            if d.scope == "msp":
                for claim in d.claims:
                    for c in claim.cites:
                        if c.kind == "passage":
                            assert c.scope == "msp-internal", (d.item_id, c)


# -- B60-2: client facts only from that client's namespace; controls cite their id -------------------------------------


def test_b60_2_client_fact_comes_from_the_clients_own_records(ctx) -> None:  # type: ignore[no-untyped-def]
    d = _security(ctx)["S-08"]
    assert not d.refused
    text = render_draft(d)
    assert "Contoso Dental chart data is copied nightly to a cloud backup service." in text
    assert "KB-CQ-001" in text
    for claim in d.claims:
        assert all(c.scope == "client" for c in claim.cites if c.kind == "passage")


def test_b60_2_a_client_fact_the_client_has_no_record_of_is_refused_not_borrowed(ctx) -> None:  # type: ignore[no-untyped-def]
    # S-09 is about Fabrikam's VPN; asked for Contoso it must be refused and carry nothing from Fabrikam.
    d = _security(ctx)["S-09"]
    assert d.refused
    assert "quokka" not in render_draft(d).lower()
    assert "hardware token" not in render_draft(d).lower()


def test_b60_2_a_client_item_is_not_answered_from_msp_policy_alone(ctx) -> None:  # type: ignore[no-untyped-def]
    item = Item("X-3", "client", "How are backup copies encrypted?")
    d = draft_item(ctx, CONTOSO, item, OWNER)
    assert d.refused and "client" in d.reason


def test_b60_2_no_client_text_or_canary_reaches_another_clients_draft(ctx) -> None:  # type: ignore[no-untyped-def]
    items = [i for name in FILES for i in load_questionnaire(FIX / name).items]
    for caller, other_canary, other_words in (
        (CONTOSO, "quokka-fq-canary-6602", ("fabrikam", "trade records", "hardware token", "vault", "kb-fq", "prj-fc")),
        (
            FABRIKAM,
            "zebra-cq-canary-5521",
            ("contoso", "imaging server", "cloud backup", "front desk", "kb-cq", "prj-cd"),
        ),
        ("litware-legal", "zebra-cq-canary-5521", ("contoso", "fabrikam", "kb-cq", "kb-fq")),
    ):
        for item in items:
            d = draft_item(ctx, caller, item, OWNER)
            text = render_draft(d).replace(d.question, "").lower()  # the question may name anything
            assert other_canary not in text
            for word in other_words:
                assert word not in text, (caller, item.id, word)


def test_b60_2_a_caller_with_no_records_still_gets_policy_answers_and_client_refusals(ctx) -> None:  # type: ignore[no-untyped-def]
    d = draft_item(ctx, "litware-legal", Item("X-4", "msp", "How is administrator access granted?"), OWNER)
    assert not d.refused
    d2 = draft_item(ctx, "litware-legal", Item("X-5", "client", "How is chart data backed up?"), OWNER)
    assert d2.refused


def test_b60_2_an_answer_about_a_control_cites_the_control_id_and_its_tests(ctx) -> None:  # type: ignore[no-untyped-def]
    d = _security(ctx)["S-05"]  # audit logs: no policy sentence, a repo control
    assert not d.refused
    text = render_draft(d)
    assert "C-08" in text
    kinds = {c.kind for claim in d.claims for c in claim.cites}
    assert {"control", "test"} <= kinds
    assert "tests/phase1/test_audit.py::test_p1_2_one_byte_changed_in_a_middle_record_names_its_seq" in text
    assert "not demonstrated" in text.lower()
    assert "fixture" in text.lower()


def test_b60_2_cited_tests_exist_in_the_repo(ctx) -> None:  # type: ignore[no-untyped-def]
    for _, drafts in _all(ctx):
        for d in drafts:
            for claim in d.claims:
                for c in claim.cites:
                    if c.kind == "test":
                        path, name = c.ref.split("::")
                        source = (REPO_ROOT / path).read_text(encoding="utf-8")
                        assert re.search(rf"def {re.escape(name)}\b", source), c.ref


def test_b60_2_a_planned_control_is_not_cited_as_if_it_existed(ctx) -> None:  # type: ignore[no-untyped-def]
    # "endpoint detection" maps to C-25, which the map lists as planned.
    d = draft_item(ctx, FABRIKAM, Item("X-6", "msp", "Describe your endpoint detection arrangements."), OWNER)
    text = render_draft(d)
    assert "C-25" not in text


def test_b60_2_a_control_with_no_test_is_not_cited(ctx) -> None:  # type: ignore[no-untyped-def]
    c = dataclasses.replace(ctx, mapping={"controls": {**ctx.mapping["controls"], "C-08": {"tests": [], "files": []}}})
    d = draft_item(c, CONTOSO, Item("X-7", "msp", "How are audit logs protected from tampering?"), OWNER)
    assert d.refused


def test_b60_2_a_partial_control_is_described_as_partial(ctx) -> None:  # type: ignore[no-untyped-def]
    d = draft_item(ctx, CONTOSO, Item("X-8", "msp", "Describe the retrieval isolation between clients."), OWNER)
    text = render_draft(d)
    assert "C-26" in text
    assert "partial" in text.lower()


# -- B60-3: scoping drafts give a cited range from similar past projects -----------------------------------------------


def test_b60_3_scoping_lists_similar_projects_with_actual_hours_as_a_range(ctx) -> None:  # type: ignore[no-untyped-def]
    q = load_questionnaire(FIX / "proposal.json")
    d = _by_id(draft_questionnaire(ctx, q, OWNER))["P-03"]
    assert not d.refused
    text = render_draft(d)
    for pid in ("PRJ-M-001", "PRJ-M-002", "PRJ-M-003", "PRJ-CD-010"):
        assert pid in text
    assert "between 34 and 58 hours" in text
    assert "not an estimate" in text.lower()


def test_b60_3_the_range_never_collapses_to_one_promised_number(ctx) -> None:  # type: ignore[no-untyped-def]
    q = load_questionnaire(FIX / "proposal.json")
    d = _by_id(draft_questionnaire(ctx, q, OWNER))["P-03"]
    claim = d.claims[0]
    numbers = [int(n) for n in re.findall(r"\b\d+\b", claim.body)]
    hours = {34, 41, 58, 47}
    assert set(numbers) <= hours | {len(claim.cites)}
    assert min(hours) in numbers and max(hours) in numbers
    for bad in ("average", "mean", "typically", "will take", "quote", "fixed price", "guarantee"):
        assert bad not in claim.body.lower()


def test_b60_3_other_clients_projects_never_appear(ctx) -> None:  # type: ignore[no-untyped-def]
    q = load_questionnaire(FIX / "proposal.json")
    d = _by_id(draft_questionnaire(ctx, q, OWNER))["P-03"]
    text = render_draft(d)
    assert "PRJ-FC-020" not in text and "190" not in text
    # and for Fabrikam the Contoso project is invisible while its own shows
    item = Item("X-9", "scoping", "Estimate the effort for the mailbox migration.", project_kind="email-migration")
    t2 = render_draft(draft_item(ctx, FABRIKAM, item, OWNER))
    assert "PRJ-FC-020" in t2 and "PRJ-CD-010" not in t2


def test_b60_3_too_few_similar_projects_means_needs_a_person(ctx) -> None:  # type: ignore[no-untyped-def]
    q = load_questionnaire(FIX / "proposal.json")
    drafts = _by_id(draft_questionnaire(ctx, q, OWNER))
    # network-refresh: one MSP project visible to Contoso (Fabrikam's two must not be borrowed); satellite-office: none
    assert drafts["P-04"].refused and "PRJ-FC" not in render_draft(drafts["P-04"])
    assert drafts["P-05"].refused
    assert NEEDS_PERSON in render_draft(drafts["P-04"]).lower()


def test_b60_3_an_injection_flagged_project_note_is_withheld_and_its_hours_not_used(ctx) -> None:  # type: ignore[no-untyped-def]
    q = load_questionnaire(FIX / "proposal.json")
    d = _by_id(draft_questionnaire(ctx, q, OWNER))["P-03"]
    text = render_draft(d)
    assert "PRJ-M-099" not in text
    assert "ignore all previous" not in text.lower()
    assert d.withheld_sources == 1
    assert "withheld" in text.lower()


# -- Labels: DRAFT, named owner, no assertion of certification or compliance ------------------------------------------


def test_b60_every_draft_is_labelled_draft_and_names_its_reviewer(ctx) -> None:  # type: ignore[no-untyped-def]
    for _, drafts in _all(ctx):
        for d in drafts:
            text = render_draft(d)
            assert text.startswith("DRAFT"), d.item_id
            assert f"requires review by {OWNER}" in text
            assert d.owner == OWNER and d.status == "DRAFT"


def test_b60_the_cli_header_and_files_say_draft_and_name_the_owner(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["draft", str(FIX / "security_questionnaire.json"), "--owner", OWNER, "--out", str(tmp_path)])
    assert code == 0
    md = (tmp_path / "security_questionnaire.md").read_text(encoding="utf-8")
    assert md.startswith("# DRAFT")
    assert f"requires review by {OWNER}" in md
    assert "synthetic" in md.lower()
    data = json.loads((tmp_path / "security_questionnaire.json").read_text(encoding="utf-8"))
    assert data["status"] == "DRAFT" and data["owner"] == OWNER
    assert all(item["status"] in {"DRAFT", "needs a person"} for item in data["items"])
    assert "answered" in capsys.readouterr().out


@pytest.mark.parametrize("owner", ["", "  ", "tbd", "TBD", "owner", "n/a", "x", "12345", "anyone", "Unknown"])
def test_b60_an_unnamed_owner_is_refused(owner: str) -> None:
    with pytest.raises(QuestionnaireError):
        validate_owner(owner)


def test_b60_the_cli_refuses_to_run_without_a_named_owner(tmp_path: Path) -> None:
    assert main(["draft", str(FIX / "proposal.json"), "--owner", "tbd", "--out", str(tmp_path)]) == 2
    assert not list(tmp_path.iterdir())


def test_b60_no_draft_asserts_certification_compliance_or_production_operation(ctx) -> None:  # type: ignore[no-untyped-def]
    banned = re.compile(
        r"\b(certified|certification|compliant|attested|audited|guarantee[sd]?|in production|production environment)\b",
        re.IGNORECASE,
    )
    for _, drafts in _all(ctx):
        for d in drafts:
            for claim in d.claims:
                assert not banned.search(claim.body), (d.item_id, claim.body)
                assert not banned.search(claim.lead), (d.item_id, claim.lead)


def test_b60_every_answered_draft_states_what_it_is_not(ctx) -> None:  # type: ignore[no-untyped-def]
    for _, drafts in _all(ctx):
        for d in drafts:
            if not d.refused:
                text = render_draft(d).lower()
                assert "not evidence that" in text or "not an estimate" in text
                assert d.limits


def test_b60_questionnaires_are_labelled_synthetic_and_unlabelled_ones_refused(tmp_path: Path) -> None:
    bad = tmp_path / "q.json"
    bad.write_text(json.dumps({"client": CONTOSO, "kind": "security", "items": []}), encoding="utf-8")
    with pytest.raises(QuestionnaireError, match="synthetic"):
        load_questionnaire(bad)
    for name in FILES:
        assert json.loads((FIX / name).read_text(encoding="utf-8"))["synthetic"] is True


def test_b60_malformed_questionnaires_are_refused(tmp_path: Path) -> None:
    for payload in (
        {"synthetic": True, "client": "client:x", "kind": "security", "items": []},
        {"synthetic": True, "client": CONTOSO, "kind": "weird", "items": []},
        {"synthetic": True, "client": CONTOSO, "kind": "security", "items": [{"id": "A", "scope": "msp"}]},
        {
            "synthetic": True,
            "client": CONTOSO,
            "kind": "security",
            "items": [{"id": "A", "scope": "all", "text": "x y"}],
        },
        {
            "synthetic": True,
            "client": CONTOSO,
            "kind": "security",
            "items": [{"id": "A", "scope": "msp", "text": "a b"}] * 2,
        },
    ):
        p = tmp_path / "q.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(QuestionnaireError):
            load_questionnaire(p)


# -- Claim inflation: an answer must not say more than its evidence ---------------------------------------------------


def test_b60_inflation_a_policy_should_stays_a_should(ctx) -> None:  # type: ignore[no-untyped-def]
    d = _security(ctx)["S-01"]
    claim = d.claims[0]
    assert "should" in claim.body and "enforce" not in claim.body.lower()
    assert "states" in claim.lead  # reported as what the policy says, not as what is done


def test_b60_inflation_check_catches_a_strengthened_quote(ctx) -> None:  # type: ignore[no-untyped-def]
    d = _security(ctx)["S-01"]
    assert check_draft(ctx, CONTOSO, d) == []
    claim = d.claims[0]
    stronger = dataclasses.replace(claim, body=claim.body.replace("should use", "always use"))
    bad = dataclasses.replace(d, claims=(stronger,))
    problems = check_draft(ctx, CONTOSO, bad)
    assert problems and any("not quoted" in p or "differs" in p for p in problems)


def test_b60_inflation_check_catches_words_the_evidence_does_not_contain() -> None:
    assert inflation_problems("Backups are always encrypted in production.", ["Backup copies should be encrypted."])
    assert inflation_problems("All staff are certified.", ["Staff should be trained."])
    assert inflation_problems("Backups run on 14 servers.", ["Backups run on servers."])
    assert inflation_problems("Backup copies should be encrypted.", ["Backup copies should be encrypted."]) == []
    # a strong word that the evidence itself uses is a quote, not an inflation
    assert (
        inflation_problems("A restore test is planned every quarter.", ["A restore test is planned every quarter."])
        == []
    )


def test_b60_inflation_check_catches_an_invented_control_or_citation(ctx) -> None:  # type: ignore[no-untyped-def]
    d = _security(ctx)["S-05"]
    claim = d.claims[0]
    fake = dataclasses.replace(claim, cites=(Cite("control", "C-99", "Invented", "msp-internal"),))
    assert check_draft(ctx, CONTOSO, dataclasses.replace(d, claims=(fake,)))
    swapped = dataclasses.replace(claim, body=claim.body + " It is running in production.")
    assert check_draft(ctx, CONTOSO, dataclasses.replace(d, claims=(swapped,)))


def test_b60_inflation_check_catches_a_citation_to_a_passage_that_does_not_contain_the_quote(ctx) -> None:  # type: ignore[no-untyped-def]
    s = _security(ctx)
    other = s["S-03"].claims[0].cites[0]
    moved = dataclasses.replace(s["S-01"].claims[0], cites=(other,))
    assert check_draft(ctx, CONTOSO, dataclasses.replace(s["S-01"], claims=(moved,)))


def test_b60_inflation_check_catches_a_refusal_that_carries_a_claim(ctx) -> None:  # type: ignore[no-untyped-def]
    s = _security(ctx)
    sneaky = dataclasses.replace(s["S-10"], claims=s["S-01"].claims)
    assert check_draft(ctx, CONTOSO, sneaky)


def test_b60_inflation_check_catches_a_range_collapsed_to_one_number(ctx) -> None:  # type: ignore[no-untyped-def]
    q = load_questionnaire(FIX / "proposal.json")
    d = _by_id(draft_questionnaire(ctx, q, OWNER))["P-03"]
    claim = d.claims[0]
    assert check_draft(ctx, CONTOSO, d) == []
    single = dataclasses.replace(claim, body="Past projects took 47 hours.")
    assert check_draft(ctx, CONTOSO, dataclasses.replace(d, claims=(single,)))


def test_b60_every_fixture_draft_passes_its_own_check_for_every_caller(ctx) -> None:  # type: ignore[no-untyped-def]
    items = [i for name in FILES for i in load_questionnaire(FIX / name).items]
    for caller in (CONTOSO, FABRIKAM, "litware-legal"):
        for item in items:
            d = draft_item(ctx, caller, item, OWNER)
            assert check_draft(ctx, caller, d) == [], (caller, item.id)


def test_b60_strong_words_in_any_claim_body_appear_in_its_evidence(ctx) -> None:  # type: ignore[no-untyped-def]
    # Independent of check_draft: re-derive the evidence text from the citations and compare word by word.
    strong = {"always", "never", "all", "every", "enforced", "verified", "continuously", "fully", "ensures"}
    passages = {
        p.chunk_id: p.text
        for _, d in _all(ctx)
        for dr in d
        for cl in dr.claims
        for c in cl.cites
        for p in ctx.passages_for(c)
    }
    for _, drafts in _all(ctx):
        for d in drafts:
            for claim in d.claims:
                words = set(re.findall(r"[a-z0-9]+", claim.body.lower())) & strong
                evidence = " ".join(passages.get(c.ref, "") for c in claim.cites).lower()
                evidence += " " + (ctx.control_objective(claim.cites[0].ref) or "").lower()
                for w in words:
                    assert w in evidence, (d.item_id, w)


# -- Structure, guard classification, reproducibility ------------------------------------------------------------------


def test_b60_drafts_are_deterministic_and_make_no_network_or_model_call(ctx) -> None:  # type: ignore[no-untyped-def]
    a = [render_draft(d) for _, ds in _all(ctx) for d in ds]
    b = [render_draft(d) for _, ds in _all(ctx) for d in ds]
    assert a == b
    banned = {"socket", "urllib", "http", "requests", "httpx", "subprocess", "datetime", "time"}
    for path in (REPO_ROOT / "workflows" / "questionnaires").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [n.name.split(".")[0] for n in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]]
            assert not banned & set(names), (path.name, names)


def test_b60_the_workflow_is_listed_in_the_injection_classification() -> None:
    text = (REPO_ROOT / "tests" / "py" / "evals" / "test_b79_injection_v2.py").read_text(encoding="utf-8")
    assert '"questionnaires"' in text
    assert "detect_injection" in (REPO_ROOT / "workflows" / "questionnaires" / "drafts.py").read_text(encoding="utf-8")


def test_b60_the_fixture_set_covers_all_three_kinds_and_both_outcomes(ctx) -> None:  # type: ignore[no-untyped-def]
    kinds = set()
    answered = refused = 0
    for q, drafts in _all(ctx):
        kinds.add(q.kind)
        answered += sum(not d.refused for d in drafts)
        refused += sum(d.refused for d in drafts)
    assert kinds == {"security", "insurance", "proposal"}
    assert answered >= 10 and refused >= 10


def test_b60_draft_dataclasses_are_frozen() -> None:
    claim = Claim("policy", "lead ", "body", (Cite("passage", "ch-" + "0" * 20, "T", "msp-internal"),))
    with pytest.raises(dataclasses.FrozenInstanceError):
        claim.body = "x"  # type: ignore[misc]
