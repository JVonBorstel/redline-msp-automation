"""B-59 client documentation upkeep and runbook linting. Acceptance ids B59-1 to B59-3 are defined in specs/B-59.md.

Offline and deterministic: dates are pinned with as_of, nothing is written outside tmp_path, committed fixtures and
runbooks are never modified (a test hashes them before and after). Secret-shaped strings are assembled at run time so
this file does not trip the repo's secret scan.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/kb
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from core.levers.registry import Registry
from workflows.doc_upkeep import (
    DocUpkeepError,
    build_report,
    render_markdown,
    write_report,
)
from workflows.doc_upkeep.__main__ import main as upkeep_main

REPO = Path(__file__).resolve().parents[3]
AS_OF = "2026-10-23"
LINT_SCRIPT = REPO / "tools" / "lint_runbook.py"
SPEC = REPO / "specs" / "B-59.md"
DATA = REPO / "workflows" / "doc_upkeep" / "data"
ACTIONS = {"add-page", "add-claim", "revise-claim", "remove-claim", "re-review", "fix-ownership"}


def _load_linter() -> ModuleType:
    spec = importlib.util.spec_from_file_location("lint_runbook_under_test", LINT_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["lint_runbook_under_test"] = module
    spec.loader.exec_module(module)
    return module


def _tree_hash(*roots: Path) -> str:
    digest = hashlib.sha256()
    for root in roots:
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            digest.update(path.relative_to(REPO).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


# ---------------------------------------------------------------------------------------------------------------
# B59-1 documentation upkeep
# ---------------------------------------------------------------------------------------------------------------


def _by_kind(report: Any, kind: str) -> list[Any]:
    return [f for f in report.findings if f.kind == kind]


def _subjects(report: Any, kind: str) -> set[str]:
    return {f.subject for f in _by_kind(report, kind)}


def _copy_data(tmp_path: Path, client: str = "contoso-dental") -> tuple[Path, dict[str, Any]]:
    data = tmp_path / "data"
    data.mkdir()
    body: dict[str, Any] = json.loads((DATA / f"{client}.json").read_text(encoding="utf-8"))
    return data, body


def test_b59_1_contoso_flags_stale_missing_and_contradictory_pages() -> None:
    report = build_report("contoso-dental", as_of=AS_OF)
    assert report.client == "contoso-dental"
    assert report.as_of == AS_OF
    assert report.summary == {"stale": 3, "missing": 8, "contradictory": 5}
    assert {f.page for f in _by_kind(report, "stale")} == {"KB-CD-001", "KB-CD-002", "KB-CD-003"}


def test_b59_1_stale_cases_are_old_review_dormant_device_and_vanished_contact() -> None:
    report = build_report("contoso-dental", as_of=AS_OF)
    assert _subjects(report, "stale") == {"review date", "RECEPTION-OLD", "Dee Okafor"}


def test_b59_1_missing_cases_are_undocumented_state_and_a_required_topic() -> None:
    report = build_report("contoso-dental", as_of=AS_OF)
    assert _subjects(report, "missing") == {
        "OPERATORY-02",
        "XRAY-WS01",
        "OFFICE-MGR",
        "HYGIENE-03",
        "CHAIRSIDE-04",
        "Priya Nair",
        "O365_BUSINESS_ESSENTIALS",
        "topic: backup",
    }


def test_b59_1_contradictions_name_the_page_and_the_observed_value() -> None:
    report = build_report("contoso-dental", as_of=AS_OF)
    contradictions = {f.subject: f for f in _by_kind(report, "contradictory")}
    assert set(contradictions) == {"DENTAL-SRV01", "Sam Patel", "O365_BUSINESS_PREMIUM", "HYGIENE-03", "ownership"}
    assert contradictions["DENTAL-SRV01"].page == "KB-CD-002"
    assert "Server" in contradictions["DENTAL-SRV01"].detail and "Desktop" in contradictions["DENTAL-SRV01"].detail
    assert contradictions["ownership"].page == "KB-CD-004"
    assert contradictions["HYGIENE-03"].page is None  # two RMM records: the observed side disagrees with itself


def test_b59_1_fabrikam_has_its_own_findings_and_a_doc_vs_doc_conflict() -> None:
    report = build_report("fabrikam-capital", as_of=AS_OF)
    assert report.summary == {"stale": 0, "missing": 6, "contradictory": 3}
    assert _subjects(report, "missing") == {
        "FAB-WS01",
        "FAB-WS02",
        "Dana Kim",
        "O365_BUSINESS_PREMIUM",
        "review date",
        "topic: backup",
    }
    pairs = [f for f in _by_kind(report, "contradictory") if "KB-FC-002" in f.detail and f.page == "KB-FC-001"]
    assert len(pairs) == 1  # the two pages disagree with each other about the seat count


def test_b59_1_no_client_sees_another_clients_devices_or_contacts() -> None:
    fab = json.dumps(build_report("fabrikam-capital", as_of=AS_OF).to_dict())
    con = json.dumps(build_report("contoso-dental", as_of=AS_OF).to_dict())
    assert "FRONTDESK-01" not in fab and "FAB-WS01" not in con  # decoy devices of the other site never leak
    assert "Priya" not in fab and "Dana" not in con


def test_b59_1_every_finding_carries_a_draft_proposal_and_changes_nothing() -> None:
    report = build_report("contoso-dental", as_of=AS_OF)
    for finding in report.findings:
        assert finding.proposal.status == "draft"
        assert finding.proposal.draft.strip()
        assert finding.proposal.action in ACTIONS
        assert finding.sources  # says which data it used
    assert report.read_only is True


def test_b59_1_page_text_is_never_echoed_and_injection_text_is_flagged_not_followed() -> None:
    report = build_report("contoso-dental", as_of=AS_OF)
    blob = json.dumps(report.to_dict()) + render_markdown(report)
    assert "ignore all previous instructions" not in blob
    assert "user.disable" not in blob
    assert report.flagged_pages == ("KB-CD-003",)


def test_b59_1_vault_entries_are_skipped_and_counted_never_read() -> None:
    report = build_report("contoso-dental", as_of=AS_OF)
    assert report.vault_skipped == 1
    assert "vaultcanary" not in json.dumps(report.to_dict()) + render_markdown(report)
    assert "KB-CD-900" not in json.dumps(report.to_dict())
    assert build_report("fabrikam-capital", as_of=AS_OF).vault_skipped == 1


def test_b59_1_report_is_deterministic_and_hashed() -> None:
    a = build_report("contoso-dental", as_of=AS_OF)
    b = build_report("contoso-dental", as_of=AS_OF)
    assert a.to_dict() == b.to_dict()
    assert re.fullmatch(r"[0-9a-f]{64}", a.sha256)
    assert a.sha256 != build_report("fabrikam-capital", as_of=AS_OF).sha256
    assert build_report("contoso-dental").as_of == AS_OF  # default is the documentation fixture's pinned date


def test_b59_1_a_later_as_of_makes_more_pages_stale() -> None:
    later = build_report("contoso-dental", as_of="2027-12-01")
    assert later.summary["stale"] > 3
    assert "KB-CD-004" in {f.page for f in _by_kind(later, "stale")}


def test_b59_1_unknown_client_and_bad_date_are_refused() -> None:
    with pytest.raises(DocUpkeepError):
        build_report("litware-legal", as_of=AS_OF)
    with pytest.raises(DocUpkeepError):
        build_report("../etc", as_of=AS_OF)
    with pytest.raises(DocUpkeepError):
        build_report("contoso-dental", as_of="23/10/2026")


def test_b59_1_a_documentation_fixture_for_the_wrong_client_is_refused(tmp_path: Path) -> None:
    data, body = _copy_data(tmp_path)
    body["client"] = "fabrikam-capital"
    (data / "contoso-dental.json").write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(DocUpkeepError):
        build_report("contoso-dental", as_of=AS_OF, data_dir=data)


def test_b59_1_a_page_that_is_not_in_the_kb_is_a_missing_page(tmp_path: Path) -> None:
    data, body = _copy_data(tmp_path)
    body["pages"].append({"article_id": "KB-CD-777", "last_reviewed": "2026-01-01", "claims": []})
    (data / "contoso-dental.json").write_text(json.dumps(body), encoding="utf-8")
    report = build_report("contoso-dental", as_of=AS_OF, data_dir=data)
    assert "KB-CD-777" in _subjects(report, "missing")


def test_b59_1_write_report_writes_only_json_and_markdown_and_leaves_inputs_alone(tmp_path: Path) -> None:
    before = _tree_hash(REPO / "fixtures", DATA)
    report = build_report("contoso-dental", as_of=AS_OF)
    written = write_report(report, tmp_path / "out")
    assert sorted(p.name for p in written) == ["contoso-dental.json", "contoso-dental.md"]
    body = json.loads((tmp_path / "out" / "contoso-dental.json").read_text(encoding="utf-8"))
    assert body["report_sha256"] == report.sha256
    assert "draft" in (tmp_path / "out" / "contoso-dental.md").read_text(encoding="utf-8").lower()
    assert _tree_hash(REPO / "fixtures", DATA) == before


def test_b59_1_cli_prints_a_summary_and_can_fail_on_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = ["report", "contoso-dental", "--as-of", AS_OF, "--out", str(tmp_path)]
    assert upkeep_main(base) == 0
    assert "stale 3" in capsys.readouterr().out
    assert upkeep_main([*base, "--fail-on-findings"]) == 1
    assert upkeep_main(["report", "nobody", "--out", str(tmp_path)]) == 2


# ---------------------------------------------------------------------------------------------------------------
# B59-2 runbook linter
# ---------------------------------------------------------------------------------------------------------------

LEVERS = frozenset({"user.disable", "user.enable", "kb.search"})

GOOD = """# Runbook: restart the print spooler

Owner: service desk lead
Last reviewed: 2026-10-01

## Purpose
Bring a stuck print queue back. See [the other runbook](../other.md) and `docs/other.md`.

## Prerequisites
- A technician with access to the workstation.

## Steps
1. Ask for `user.disable` only when the lead says so.
2. Restart the spooler.

## Rollback
Start the spooler again.

## Verification
Print a test page.
"""


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs" / "other.md").write_text("# other\n", encoding="utf-8")
    (tmp_path / "other.md").write_text("# other\n", encoding="utf-8")
    return tmp_path


def _lint(text: str, tmp_path: Path, as_of: str = AS_OF) -> list[Any]:
    linter = _load_linter()
    repo = _repo(tmp_path)
    return list(linter.lint_text(text, "docs/runbooks/x.md", repo=repo, levers=LEVERS, as_of=as_of))


def _rules(findings: list[Any]) -> set[str]:
    return {f.rule for f in findings}


def test_b59_2_a_complete_runbook_passes(tmp_path: Path) -> None:
    assert _lint(GOOD, tmp_path) == []


@pytest.mark.parametrize("section", ["Purpose", "Prerequisites", "Steps", "Rollback", "Verification"])
def test_b59_2_each_missing_required_section_fails(section: str, tmp_path: Path) -> None:
    broken = re.sub(rf"## {section}\n", "## Notes\n", GOOD)
    findings = _lint(broken, tmp_path)
    assert [f.rule for f in findings] == ["missing-section"]
    assert section.lower() in findings[0].message.lower()
    assert findings[0].proposal  # a proposal for the fix, never an edit


def test_b59_2_owner_is_required_as_a_line_or_a_section(tmp_path: Path) -> None:
    no_owner = GOOD.replace("Owner: service desk lead\n", "")
    assert [f.rule for f in _lint(no_owner, tmp_path)] == ["missing-owner"]
    assert _lint(no_owner + "\n## Owner\nService desk lead.\n", tmp_path) == []
    assert _rules(_lint(GOOD.replace("Owner: service desk lead", "Owner:   "), tmp_path)) == {"missing-owner"}


def test_b59_2_last_reviewed_must_exist_be_a_real_date_and_not_be_old(tmp_path: Path) -> None:
    assert _rules(_lint(GOOD.replace("Last reviewed: 2026-10-01\n", ""), tmp_path)) == {"missing-last-reviewed"}
    assert _rules(_lint(GOOD.replace("2026-10-01", "2026-13-45"), tmp_path)) == {"bad-last-reviewed"}
    assert _rules(_lint(GOOD.replace("2026-10-01", "2026-11-30"), tmp_path)) == {"bad-last-reviewed"}  # future
    assert _rules(_lint(GOOD.replace("2026-10-01", "2024-01-01"), tmp_path)) == {"stale-review"}
    assert _lint(GOOD.replace("2026-10-01", "2025-11-01"), tmp_path) == []  # inside the 365 day window


def test_b59_2_broken_links_and_cited_files_are_found(tmp_path: Path) -> None:
    text = GOOD + "\nSee [gone](missing.md) and `docs/nowhere.md` and `tools/ghost.py`.\n"
    findings = _lint(text, tmp_path)
    assert _rules(findings) == {"broken-link", "missing-file"}
    assert {f.rule for f in findings if "missing.md" in f.message} == {"broken-link"}
    assert sum(f.rule == "missing-file" for f in findings) == 2
    assert all(f.line > 0 for f in findings)


def test_b59_2_links_that_are_not_files_are_not_checked(tmp_path: Path) -> None:
    skipped = (
        "[site](https://example.com/x) [mail](mailto:a@b.example) [here](#purpose) "
        "`.tmp/demo/audit/x.jsonl` `audit/<client>.jsonl` `docs/*.md` `build/out/` `a b/c.md`"
    )
    assert _lint(GOOD + "\n" + skipped + "\n", tmp_path) == []


def test_b59_2_paths_in_code_fences_are_commands_not_citations(tmp_path: Path) -> None:
    text = GOOD + "\n```powershell\nGet-Content docs/nowhere.md\n```\n"
    assert _lint(text, tmp_path) == []


def test_b59_2_secret_shaped_text_fails_and_the_value_is_never_repeated(tmp_path: Path) -> None:
    aws = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
    pwd = "pass" + "word: " + "Tr0ub4dor&3x"
    key = "-----BEGIN RSA PRIV" + "ATE KEY-----"
    for secret in (aws, pwd, key):
        findings = _lint(GOOD + f"\nStep note: {secret}\n", tmp_path)
        assert _rules(findings) == {"secret"}
        assert secret not in json.dumps([asdict(f) for f in findings])


def test_b59_2_a_step_naming_an_unregistered_lever_fails(tmp_path: Path) -> None:
    findings = _lint(GOOD + "\nThen run `user.obliterate` for the person.\n", tmp_path)
    assert _rules(findings) == {"unregistered-lever"}
    assert "user.obliterate" in findings[0].message


def test_b59_2_lever_commands_are_checked_and_placeholders_are_not(tmp_path: Path) -> None:
    cmd = "uv run --frozen python -m core.levers"
    ok = GOOD + f"\n```powershell\n{cmd} pause user.disable --as <lead>\n{cmd} invoke <lever> --as <tech>\n```\n"
    assert _lint(ok, tmp_path) == []
    bad = GOOD + f"\n```powershell\n{cmd} resume user.nuke --as <lead>\n```\n"
    assert _rules(_lint(bad, tmp_path)) == {"unregistered-lever"}


def test_b59_2_dotted_names_that_are_not_levers_are_left_alone(tmp_path: Path) -> None:
    text = GOOD + "\nModules `core.levers` and `workflows.factpack`, files `kb.json`, host `contosodental.example`.\n"
    assert _lint(text, tmp_path) == []


def test_b59_2_cli_fails_on_a_broken_runbook_and_passes_a_good_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    linter = _load_linter()
    repo = _repo(tmp_path)
    good = repo / "docs" / "good.md"
    good.write_text(GOOD, encoding="utf-8")
    broken = repo / "docs" / "broken.md"
    broken.write_text(GOOD.replace("## Rollback\n", "## Notes\n"), encoding="utf-8")
    base = ["--repo", str(repo), "--as-of", AS_OF]
    assert linter.main([str(good), *base]) == 0
    capsys.readouterr()
    assert linter.main([str(broken), *base]) == 1
    out = capsys.readouterr().out
    assert "missing-section" in out and "broken.md" in out and "proposal" in out.lower()
    assert linter.main([str(repo / "docs" / "nope.md"), *base]) == 2
    assert linter.main([str(good), "--repo", str(repo), "--as-of", "yesterday"]) == 2


def test_b59_2_cli_json_output_is_machine_readable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    linter = _load_linter()
    repo = _repo(tmp_path)
    broken = repo / "docs" / "broken.md"
    broken.write_text(GOOD.replace("Owner: service desk lead\n", ""), encoding="utf-8")
    assert linter.main([str(broken), "--repo", str(repo), "--as-of", AS_OF, "--json"]) == 1
    body = json.loads(capsys.readouterr().out)
    assert body["files"] == 1 and body["findings"][0]["rule"] == "missing-owner"


# ---------------------------------------------------------------------------------------------------------------
# B59-3 this repo's own runbooks
# ---------------------------------------------------------------------------------------------------------------


def _real_gaps() -> dict[str, set[str]]:
    linter = _load_linter()
    levers = frozenset(Registry.load().names())
    gaps: dict[str, set[str]] = {}
    for path in linter.default_targets(REPO):
        rel = path.relative_to(REPO).as_posix()
        text = path.read_text(encoding="utf-8")
        found = linter.lint_text(text, rel, repo=REPO, levers=levers, as_of=AS_OF)
        gaps[rel] = {f.rule for f in found}
    return gaps


def test_b59_3_default_targets_are_the_runbooks_folder_and_the_index() -> None:
    linter = _load_linter()
    names = {p.relative_to(REPO).as_posix() for p in linter.default_targets(REPO)}
    assert names == {
        "docs/RUNBOOKS.md",
        "docs/runbooks/ai-incident-response.md",
        "docs/runbooks/caller-verification.md",
        "docs/runbooks/client-offboarding.md",
        "docs/runbooks/urgent-termination.md",
    }


def test_b59_3_the_real_runbooks_are_linted_and_the_linter_exits_nonzero_while_gaps_remain() -> None:
    linter = _load_linter()
    assert any(_real_gaps().values())  # the committed runbooks predate the template; the gaps are real, not hidden
    assert linter.main(["--repo", str(REPO), "--as-of", AS_OF]) == 1


def test_b59_3_every_gap_is_listed_in_the_spec_and_nothing_else_is() -> None:
    listed: dict[str, set[str]] = {}
    in_section = False
    for line in SPEC.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_section = line.startswith("## Gaps in the repo's runbooks")
            continue
        match = re.match(r"^- `(docs/[^`]+\.md)`: (.+)$", line)
        if in_section and match:
            listed[match.group(1)] = {r.strip(" `.") for r in match.group(2).split(",")}
    real = {path: rules for path, rules in _real_gaps().items() if rules}
    assert listed == real


def test_b59_3_linting_the_real_runbooks_changes_nothing() -> None:
    before = _tree_hash(REPO / "docs" / "runbooks")
    _real_gaps()
    assert _tree_hash(REPO / "docs" / "runbooks") == before
